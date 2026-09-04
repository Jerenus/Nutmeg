"""``nutmeg ontology`` — kernel init/status operations (Package 1).

``init`` applies migrations and is idempotent; ``status`` is strictly read-only
and never initializes the database. ``status`` exits non-zero when the kernel is
uninitialized or its integrity check is not ``ok``, so it doubles as a health
gate. Every CLI-package global is reached through ``_cli`` to preserve the test
monkeypatch conventions.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_runtime import OntologyWriterLease

ontology_app = _cli.typer.Typer(help="Ontology Kernel v2 operations")
_cli.app.add_typer(ontology_app, name="ontology")


def _require_format(fmt: str) -> None:
    if fmt not in ("text", "json"):
        _cli.typer.echo(f"invalid --format {fmt!r}: expected 'text' or 'json'", err=True)
        raise _cli.typer.Exit(code=2)


def _read_database_facts(database: Path) -> dict[str, object]:
    """Read the migration and row-count facts used to prove a faithful backup."""
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
        schema_version = counts.get("schema_migrations", 0)
        if "schema_migrations" in tables:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = row[0] or 0
        action_high_water = 0
        if "actions" in tables:
            row = connection.execute("SELECT COALESCE(MAX(rowid), 0) FROM actions").fetchone()
            action_high_water = row[0]
    return {
        "integrity_check": integrity,
        "schema_version": schema_version,
        "action_high_water": action_high_water,
        "table_counts": counts,
    }


def _assert_healthy_facts(facts: dict[str, object], *, label: str) -> None:
    if facts["integrity_check"] != "ok":
        raise ValueError(f"{label} ontology integrity check failed")


def _assert_backup_matches_source(
    source: dict[str, object], backup: dict[str, object]
) -> None:
    if source != backup:
        raise ValueError("backup ontology facts do not match source")


def _assert_migration_preserved_source(
    before: dict[str, object], after: dict[str, object]
) -> None:
    if after["action_high_water"] != before["action_high_water"]:
        raise ValueError("migration changed Action high water")
    before_counts = before["table_counts"]
    after_counts = after["table_counts"]
    assert isinstance(before_counts, dict)
    assert isinstance(after_counts, dict)
    mutable_migration_tables = {"schema_migrations", "action_permissions"}
    for table, count in before_counts.items():
        if table in mutable_migration_tables:
            continue
        if after_counts.get(table) != count:
            raise ValueError(f"migration changed row count for {table}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guarded_initialize(
    *,
    settings: AppSettings,
    data_dir: Path,
    backup_file: Path,
    stage_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Back up and migrate the configured production ontology under one lease."""
    if not data_dir.is_absolute() or not backup_file.is_absolute():
        raise ValueError("data and backup paths must be absolute")
    production_dir = settings.production_data_dir.resolve()
    resolved_data_dir = data_dir.resolve()
    resolved_backup = backup_file.resolve()
    archive_dir = (production_dir / "archive").resolve()
    if resolved_data_dir != production_dir:
        raise ValueError("data directory must match configured production directory")
    if not resolved_backup.is_relative_to(archive_dir):
        raise ValueError("backup file must be inside the production archive directory")
    if resolved_backup.exists():
        raise ValueError("backup file already exists")

    source_database = resolved_data_dir / "ontology" / "ontology.db"
    if not source_database.is_file():
        raise ValueError("production ontology source does not exist")
    hook = stage_hook or (lambda _stage: None)
    lease = OntologyWriterLease.exclusive(resolved_data_dir)
    lease.acquire()
    try:
        source_before = _read_database_facts(source_database)
        _assert_healthy_facts(source_before, label="source")
        hook("source_audited")

        resolved_backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(source_database)) as source_connection:
            with sqlite3.connect(str(resolved_backup)) as backup_connection:
                source_connection.backup(backup_connection)
        hook("backup_created")

        backup_facts = _read_database_facts(resolved_backup)
        _assert_healthy_facts(backup_facts, label="backup")
        _assert_backup_matches_source(source_before, backup_facts)
        hook("backup_audited")

        guarded_settings = settings.model_copy(update={"data_dir": resolved_data_dir})
        kernel = build_ontology_kernel(guarded_settings)
        migration_report = kernel.initialize()
        hook("migration_applied")

        source_after = _read_database_facts(source_database)
        _assert_healthy_facts(source_after, label="migrated source")
        _assert_migration_preserved_source(source_before, source_after)
        if source_after["schema_version"] != MIGRATIONS[-1].version:
            raise ValueError("production ontology did not reach the current schema")
        hook("source_verified")
        return {
            "schema_version": source_after["schema_version"],
            "backup_file": str(resolved_backup),
            "backup_sha256": _sha256_file(resolved_backup),
            "action_high_water": source_after["action_high_water"],
            "lease": {
                "data_dir": str(resolved_data_dir),
                "mode": "exclusive",
                "path": str(lease.path),
            },
            "source_before": source_before,
            "backup": backup_facts,
            "applied_versions": list(migration_report.applied_versions),
            "source_after": source_after,
        }
    finally:
        lease.release()


@ontology_app.command("init")
def ontology_init(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _require_format(format)
    settings = _cli.get_settings()
    kernel = _cli.build_ontology_kernel(settings)
    before = kernel.status()
    if (
        settings.data_dir.resolve() == settings.production_data_dir.resolve()
        and before.initialized
        and before.pending_migrations
    ):
        _cli.typer.echo("production_migration_requires_guarded_init", err=True)
        raise _cli.typer.Exit(code=1)
    report = kernel.initialize()
    status = kernel.status()
    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(
                {
                    "applied_versions": list(report.applied_versions),
                    "schema_version": status.schema_version,
                    "ontology_db_path": str(settings.ontology_db_path),
                    "ontology_artifact_dir": str(settings.ontology_artifact_dir),
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return
    _cli.console.print(
        f"ontology initialized: applied={list(report.applied_versions)} "
        f"schema_version={status.schema_version}"
    )
    _cli.console.print(f"db={settings.ontology_db_path}")
    _cli.console.print(f"artifacts={settings.ontology_artifact_dir}")


@ontology_app.command("guarded-init")
def ontology_guarded_init(
    data_dir: Annotated[Path, _cli.typer.Option("--data-dir")],
    backup_file: Annotated[Path, _cli.typer.Option("--backup-file")],
    format: Annotated[str, _cli.typer.Option("--format", help="text or json")] = "text",
) -> None:
    """Back up and migrate the configured production ontology under an exclusive lease."""
    _require_format(format)
    try:
        report = guarded_initialize(
            settings=_cli.get_settings(),
            data_dir=data_dir,
            backup_file=backup_file,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        _cli.typer.echo(str(error), err=True)
        raise _cli.typer.Exit(code=1) from error
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(report, indent=2, sort_keys=True))
        return
    _cli.console.print(
        f"ontology guarded migration complete: schema_version={report['schema_version']}"
    )
    _cli.console.print(f"backup={report['backup_file']}")


@ontology_app.command("status")
def ontology_status(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _require_format(format)
    settings = _cli.get_settings()
    status = _cli.build_ontology_kernel(settings).status()
    healthy = status.initialized and status.integrity_check == "ok"
    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(status.to_dict(), indent=2, sort_keys=True, default=str)
        )
    else:
        _cli.console.print(
            f"ontology initialized={status.initialized} "
            f"schema_version={status.schema_version} integrity={status.integrity_check}"
        )
    raise _cli.typer.Exit(code=0 if healthy else 1)
