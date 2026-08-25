"""Atomic local backups and isolated restore drills for the ontology authority."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel

_CHUNK_SIZE = 1024 * 1024
_MANIFEST_KEYS = {
    "manifest_version",
    "tool_version",
    "created_at",
    "source_data_root",
    "schema_version",
    "sqlite_integrity",
    "action_high_watermark",
    "outbox_cursor",
    "table_counts",
    "ticket_hashes",
    "ledger_balances",
    "files",
}
_FILE_KEYS = {"path", "kind", "byte_size", "sha256"}
_COUNT_TABLES = tuple(sorted(schema.metadata.tables))


class RecoveryError(RuntimeError):
    """A backup or restore invariant was not satisfied."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    backup_dir: Path
    manifest_path: Path
    manifest: dict[str, object]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class RestoreDrillReport:
    status: str
    restore_data_dir: Path
    source_manifest_sha256: str
    action_high_watermark: int
    outbox_cursor: int
    projection_high_watermark: int
    table_counts: dict[str, int]


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise RecoveryError(f"backup source must be a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    _fsync_file(destination)
    _fsync_directory(destination.parent)


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()
    _fsync_file(destination)
    _fsync_directory(destination.parent)


def _sqlite_facts(database: Path) -> dict[str, object]:
    uri = f"file:{database.resolve().as_posix()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RecoveryError(f"SQLite integrity check failed: {integrity}")
        existing_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = set(_COUNT_TABLES) - existing_tables
        if missing:
            raise RecoveryError(f"SQLite is missing tables: {', '.join(sorted(missing))}")
        counts = {
            table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
            for table in _COUNT_TABLES
        }
        schema_version = int(
            connection.execute(
                "SELECT coalesce(max(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        action_high_watermark = int(
            connection.execute("SELECT coalesce(max(rowid), 0) FROM actions").fetchone()[0]
        )
        outbox_cursor = int(
            connection.execute(
                "SELECT coalesce(max(sequence), 0) FROM outbox_events"
            ).fetchone()[0]
        )
        ticket_hashes = [
            str(row[0])
            for row in connection.execute(
                "SELECT ticket_hash FROM audited_ticket_artifacts ORDER BY ticket_hash"
            ).fetchall()
        ]
        ledger_balances = [
            {
                "account_id": str(row[0]),
                "balance": float(row[2]),
                "currency": str(row[1]),
            }
            for row in connection.execute(
                "SELECT a.account_id, a.currency, coalesce(sum(t.amount), 0) "
                "FROM cash_accounts AS a "
                "LEFT JOIN cash_transactions AS t ON t.account_id = a.account_id "
                "GROUP BY a.account_id, a.currency ORDER BY a.account_id"
            ).fetchall()
        ]
    return {
        "schema_version": schema_version,
        "sqlite_integrity": integrity,
        "action_high_watermark": action_high_watermark,
        "outbox_cursor": outbox_cursor,
        "table_counts": counts,
        "ticket_hashes": ticket_hashes,
        "ledger_balances": ledger_balances,
    }


def _file_entry(path: Path, relative: Path, kind: str) -> dict[str, object]:
    return {
        "path": relative.as_posix(),
        "kind": kind,
        "byte_size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _validate_cas_blob(path: Path, relative: Path) -> None:
    parts = relative.parts
    if (
        len(parts) != 3
        or parts[0] != "sha256"
        or len(parts[1]) != 2
        or len(parts[2]) != 64
        or parts[1] != parts[2][:2]
        or any(char not in "0123456789abcdef" for char in parts[2])
    ):
        raise RecoveryError(f"invalid CAS storage path: {relative.as_posix()}")
    if _sha256(path) != parts[2]:
        raise RecoveryError(
            f"CAS content hash mismatch: {relative.as_posix()}"
        )


def _atomic_publish(staging: Path, destination: Path) -> None:
    os.replace(staging, destination)
    _fsync_directory(destination.parent)


def create_backup(
    kernel: OntologyKernel,
    destination: Path | str,
    requested_at: datetime,
    acknowledge_writers_stopped: bool,
) -> BackupResult:
    _require_aware(requested_at, "requested_at")
    if not acknowledge_writers_stopped:
        raise ValueError("acknowledge_writers_stopped must be true")
    destination = Path(destination).resolve()
    source_root = kernel.paths.root.resolve()
    if _overlaps(destination, source_root):
        raise ValueError("backup destination cannot overlap the ontology source")
    if destination.exists():
        raise FileExistsError(destination)
    status = kernel.status()
    if (
        not status.initialized
        or status.integrity_check != "ok"
        or status.pending_migrations
        or status.schema_version != MIGRATIONS[-1].version
    ):
        raise RecoveryError("ontology source is not a healthy current-schema store")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid4().hex}"
    staging.mkdir()
    try:
        sqlite_relative = Path("ontology") / "ontology.db"
        sqlite_destination = staging / sqlite_relative
        _sqlite_backup(kernel.paths.database, sqlite_destination)
        files = [_file_entry(sqlite_destination, sqlite_relative, "sqlite")]

        if kernel.paths.analytics.exists():
            duck_relative = Path("ontology") / "analytics.duckdb"
            duck_destination = staging / duck_relative
            _copy_file(kernel.paths.analytics, duck_destination)
            files.append(_file_entry(duck_destination, duck_relative, "duckdb"))

        if kernel.paths.artifacts.exists():
            for source in sorted(kernel.paths.artifacts.rglob("*")):
                if source.is_dir():
                    continue
                relative = Path("ontology") / "artifacts" / source.relative_to(
                    kernel.paths.artifacts
                )
                copied = staging / relative
                _copy_file(source, copied)
                _validate_cas_blob(
                    copied,
                    source.relative_to(kernel.paths.artifacts),
                )
                files.append(_file_entry(copied, relative, "cas"))

        facts = _sqlite_facts(sqlite_destination)
        manifest: dict[str, object] = {
            "manifest_version": "backup-v1",
            "tool_version": "m6-v1",
            "created_at": requested_at.astimezone(UTC).isoformat(),
            "source_data_root": str(kernel.paths.root.parent.resolve()),
            **facts,
            "files": sorted(files, key=lambda entry: str(entry["path"])),
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        _fsync_file(manifest_path)
        _fsync_directory(staging)
        manifest_hash = _sha256(manifest_path)
        _atomic_publish(staging, destination)
        return BackupResult(
            backup_dir=destination,
            manifest_path=destination / "manifest.json",
            manifest=manifest,
            manifest_sha256=manifest_hash,
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _load_manifest(backup_dir: Path) -> tuple[dict[str, object], str]:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RecoveryError("backup manifest is missing or is not a regular file")
    raw = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RecoveryError("backup manifest is not valid JSON") from error
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise RecoveryError("backup manifest has an invalid shape")
    if raw.strip() != canonical_json(manifest):
        raise RecoveryError("backup manifest is not canonical JSON")
    if manifest["manifest_version"] != "backup-v1":
        raise RecoveryError("unsupported backup manifest version")
    if manifest["schema_version"] != MIGRATIONS[-1].version:
        raise RecoveryError("backup schema version is not current")
    return manifest, _sha256(manifest_path)


def _manifest_files(
    backup_dir: Path, manifest: dict[str, object]
) -> list[tuple[Path, Path, dict[str, object]]]:
    raw_files = manifest["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise RecoveryError("backup manifest files must be a non-empty array")
    resolved: list[tuple[Path, Path, dict[str, object]]] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != _FILE_KEYS:
            raise RecoveryError("backup file entry has an invalid shape")
        relative = Path(str(raw["path"]))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "ontology":
            raise RecoveryError("backup file path escapes the backup root")
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise RecoveryError(f"duplicate backup file path: {relative_text}")
        seen.add(relative_text)
        source = backup_dir / relative
        if source.is_symlink() or not source.is_file():
            raise RecoveryError(f"backup component is missing: {relative_text}")
        size = raw["byte_size"]
        digest = raw["sha256"]
        kind = raw["kind"]
        if kind not in {"sqlite", "duckdb", "cas"}:
            raise RecoveryError(f"invalid kind for backup component: {relative_text}")
        if kind == "sqlite" and relative_text != "ontology/ontology.db":
            raise RecoveryError("SQLite component has an invalid path")
        if kind == "duckdb" and relative_text != "ontology/analytics.duckdb":
            raise RecoveryError("DuckDB component has an invalid path")
        if kind == "cas" and not relative_text.startswith("ontology/artifacts/"):
            raise RecoveryError("CAS component has an invalid path")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RecoveryError(f"invalid size for backup component: {relative_text}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RecoveryError(f"invalid hash for backup component: {relative_text}")
        if source.stat().st_size != size:
            raise RecoveryError(f"backup component size mismatch: {relative_text}")
        if _sha256(source) != digest:
            raise RecoveryError(f"backup component hash mismatch: {relative_text}")
        resolved.append((source, relative, raw))
    actual = {
        path.relative_to(backup_dir).as_posix()
        for path in backup_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != seen:
        raise RecoveryError("backup contains unmanifested or missing components")
    kinds = {str(item[2]["kind"]) for item in resolved}
    if "sqlite" not in kinds or sum(item[2]["kind"] == "sqlite" for item in resolved) != 1:
        raise RecoveryError("backup must contain exactly one SQLite component")
    return resolved


def _assert_manifest_facts(manifest: dict[str, object], facts: dict[str, object]) -> None:
    for key in (
        "schema_version",
        "sqlite_integrity",
        "action_high_watermark",
        "outbox_cursor",
        "table_counts",
        "ticket_hashes",
        "ledger_balances",
    ):
        if facts[key] != manifest[key]:
            raise RecoveryError(f"restored SQLite invariant mismatch: {key}")


def run_restore_drill(
    backup_dir: Path | str,
    restore_data_dir: Path | str,
    requested_at: datetime,
) -> RestoreDrillReport:
    _require_aware(requested_at, "requested_at")
    backup_dir = Path(backup_dir).resolve()
    restore_data_dir = Path(restore_data_dir).resolve()
    if not backup_dir.is_dir():
        raise FileNotFoundError(backup_dir)
    if _overlaps(backup_dir, restore_data_dir):
        raise ValueError("restore destination cannot overlap the backup")
    if restore_data_dir.exists():
        raise FileExistsError(restore_data_dir)

    manifest, manifest_hash = _load_manifest(backup_dir)
    files = _manifest_files(backup_dir, manifest)
    restore_data_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = restore_data_dir.parent / (
        f".{restore_data_dir.name}.staging-{uuid4().hex}"
    )
    staging.mkdir()
    try:
        for source, relative, _entry in files:
            _copy_file(source, staging / relative)
        restored_database = staging / "ontology" / "ontology.db"
        facts = _sqlite_facts(restored_database)
        _assert_manifest_facts(manifest, facts)

        kernel = build_ontology_kernel(AppSettings(data_dir=staging))
        try:
            status = kernel.status()
            if (
                not status.initialized
                or status.integrity_check != "ok"
                or status.pending_migrations
                or status.schema_version != MIGRATIONS[-1].version
            ):
                raise RecoveryError(
                    "restored kernel is not healthy before projection rebuild"
                )
            rebuild = kernel.calibrate.build(
                CalibrateRequest(
                    as_of=requested_at.astimezone(UTC).isoformat(),
                    built_at=requested_at.astimezone(UTC).isoformat(),
                    high_watermark=int(manifest["action_high_watermark"]),
                )
            )
        finally:
            kernel.engine.dispose()
        if rebuild.status != "succeeded":
            raise RecoveryError("restored projection rebuild failed")
        _fsync_directory(staging)
        _atomic_publish(staging, restore_data_dir)
        return RestoreDrillReport(
            status="passed",
            restore_data_dir=restore_data_dir,
            source_manifest_sha256=manifest_hash,
            action_high_watermark=int(manifest["action_high_watermark"]),
            outbox_cursor=int(manifest["outbox_cursor"]),
            projection_high_watermark=rebuild.high_watermark,
            table_counts=dict(facts["table_counts"]),
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
