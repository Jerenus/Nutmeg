import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.repository.finance import CashAccountRow, CashTransactionRow
from nutmeg.ontology.repository.tickets import (
    AuditedTicketArtifactRow,
    TicketBatchRevisionRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.reliability import backup as backup_module
from nutmeg.reliability.backup import (
    RecoveryError,
    create_backup,
    run_restore_drill,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _seed_kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    artifact = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b'{"ticket":"audited","stake":25}',
            content_type="application/json",
            source_name="m6-backup-test",
            source_type="fixture",
            actor_id="source:m6-backup",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="m6:backup:artifact",
            retrieved_at=NOW,
        )
    )
    source_artifact_id = next(
        ref.object_id
        for ref in artifact.result_refs
        if ref.object_type == "source_artifact"
    )
    ticket_hash = source_artifact_id.removeprefix("sha256:")
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
        uow.finance.insert_cash_transaction(
            CashTransactionRow(
                transaction_id="txn-backup",
                account_id="acct-jczq",
                ticket_id=None,
                ticket_settlement_id=None,
                kind="deposit",
                amount=125.0,
                occurred_at=NOW.isoformat(),
                idempotency_key="m6:backup:cash",
            )
        )
        uow.tickets.insert_batch_revision(
            TicketBatchRevisionRow(
                ticket_batch_revision_id="tbr-backup",
                ticket_batch_id="tb-backup",
                revision_no=1,
                supersedes_revision_id=None,
                run_date="2026-08-24",
                channel="jczq",
                account_id="acct-jczq",
                currency="CNY",
                deadline_at="2026-08-24T13:00:00+00:00",
                input_legs=[],
                composition={"tickets": 1},
                audit_findings=[],
                state="approved",
                content_hash="a" * 64,
                source_artifact_id=source_artifact_id,
                created_at=NOW.isoformat(),
                created_by_action_id=artifact.action_id,
            )
        )
        uow.tickets.insert_ticket_artifact(
            AuditedTicketArtifactRow(
                ticket_artifact_id="ta-backup",
                ticket_batch_revision_id="tbr-backup",
                ticket_index=0,
                ticket_hash=ticket_hash,
                source_artifact_id=source_artifact_id,
                amount=25.0,
                currency="CNY",
                channel="jczq",
                deadline_at="2026-08-24T13:00:00+00:00",
                payload={"ticket": "audited", "stake": 25},
                approved_at=NOW.isoformat(),
                approved_by_action_id=artifact.action_id,
            )
        )
    build = kernel.calibrate.build(
        CalibrateRequest(
            as_of=NOW.isoformat(),
            built_at="2026-08-24T12:01:00+00:00",
        )
    )
    assert build.status == "succeeded"
    return kernel, ticket_hash


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_backup_manifest_and_restore_round_trip_all_invariants(tmp_path: Path) -> None:
    kernel, ticket_hash = _seed_kernel(tmp_path)
    destination = tmp_path / "backups" / "m6-one"

    result = create_backup(
        kernel,
        destination,
        requested_at=NOW,
        acknowledge_writers_stopped=True,
    )

    assert result.backup_dir == destination.resolve()
    assert result.manifest_path == destination.resolve() / "manifest.json"
    assert result.manifest["manifest_version"] == "backup-v1"
    assert result.manifest["schema_version"] == 14
    assert result.manifest["sqlite_integrity"] == "ok"
    assert result.manifest["action_high_watermark"] == 1
    assert result.manifest["outbox_cursor"] == 1
    assert result.manifest["ticket_hashes"] == [ticket_hash]
    assert result.manifest["ledger_balances"] == [
        {"account_id": "acct-jczq", "balance": 125.0, "currency": "CNY"}
    ]
    assert result.manifest["table_counts"]["actions"] == 1
    assert result.manifest["table_counts"]["audited_ticket_artifacts"] == 1
    files = {entry["kind"]: entry for entry in result.manifest["files"]}
    assert {"sqlite", "duckdb", "cas"} <= set(files)
    assert result.manifest_sha256 == _sha256(result.manifest_path)

    restore_dir = tmp_path / "restored-data"
    drill = run_restore_drill(
        destination,
        restore_dir,
        requested_at=NOW,
    )

    assert drill.status == "passed"
    assert drill.restore_data_dir == restore_dir.resolve()
    assert drill.source_manifest_sha256 == result.manifest_sha256
    assert drill.action_high_watermark == 1
    assert drill.outbox_cursor == 1
    assert drill.projection_high_watermark == 1
    restored = build_ontology_kernel(AppSettings(data_dir=restore_dir))
    status = restored.status()
    assert status.schema_version == 14
    assert status.integrity_check == "ok"
    assert status.artifact_count == 1


def test_backup_requires_acknowledgement_new_non_overlapping_target(
    tmp_path: Path,
) -> None:
    kernel, _ticket_hash = _seed_kernel(tmp_path)
    destination = tmp_path / "backup"

    with pytest.raises(ValueError, match="writers_stopped"):
        create_backup(
            kernel,
            destination,
            requested_at=NOW,
            acknowledge_writers_stopped=False,
        )
    destination.mkdir()
    with pytest.raises(FileExistsError):
        create_backup(
            kernel,
            destination,
            requested_at=NOW,
            acknowledge_writers_stopped=True,
        )
    with pytest.raises(ValueError, match="overlap"):
        create_backup(
            kernel,
            kernel.paths.root / "backup",
            requested_at=NOW,
            acknowledge_writers_stopped=True,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        create_backup(
            kernel,
            tmp_path / "naive",
            requested_at=datetime(2026, 8, 24, 12),
            acknowledge_writers_stopped=True,
        )


def test_interrupted_backup_never_publishes_partial_or_changes_prior_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, _ticket_hash = _seed_kernel(tmp_path)
    stable = create_backup(
        kernel,
        tmp_path / "stable",
        requested_at=NOW,
        acknowledge_writers_stopped=True,
    )
    stable_hash = _sha256(stable.manifest_path)
    original_copy = backup_module._copy_file

    def interrupted_copy(source: Path, destination: Path) -> None:
        if source.name == "analytics.duckdb":
            raise OSError("injected copy interruption")
        original_copy(source, destination)

    monkeypatch.setattr(backup_module, "_copy_file", interrupted_copy)
    failed = tmp_path / "failed"
    with pytest.raises(OSError, match="injected copy interruption"):
        create_backup(
            kernel,
            failed,
            requested_at=NOW,
            acknowledge_writers_stopped=True,
        )

    assert not failed.exists()
    assert _sha256(stable.manifest_path) == stable_hash
    assert not list(tmp_path.glob(".failed.staging-*"))

    monkeypatch.setattr(backup_module, "_copy_file", original_copy)

    def interrupted_publish(_staging: Path, _destination: Path) -> None:
        raise OSError("injected publish interruption")

    monkeypatch.setattr(backup_module, "_atomic_publish", interrupted_publish)
    unpublished = tmp_path / "unpublished"
    with pytest.raises(OSError, match="injected publish interruption"):
        create_backup(
            kernel,
            unpublished,
            requested_at=NOW,
            acknowledge_writers_stopped=True,
        )
    assert not unpublished.exists()
    assert _sha256(stable.manifest_path) == stable_hash
    assert not list(tmp_path.glob(".unpublished.staging-*"))


@pytest.mark.parametrize("kind", ["sqlite", "duckdb", "cas"])
def test_restore_rejects_component_tampering_before_publication(
    tmp_path: Path, kind: str
) -> None:
    kernel, _ticket_hash = _seed_kernel(tmp_path)
    source = create_backup(
        kernel,
        tmp_path / "source-backup",
        requested_at=NOW,
        acknowledge_writers_stopped=True,
    )
    tampered = tmp_path / f"tampered-{kind}"
    shutil.copytree(source.backup_dir, tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    target_entry = next(entry for entry in manifest["files"] if entry["kind"] == kind)
    target_file = tampered / target_entry["path"]
    target_file.write_bytes(target_file.read_bytes() + b"tampered")
    restore_dir = tmp_path / f"restore-{kind}"

    with pytest.raises(RecoveryError, match="hash|size"):
        run_restore_drill(tampered, restore_dir, requested_at=NOW)

    assert not restore_dir.exists()


def test_restore_rejects_existing_or_overlapping_destination(tmp_path: Path) -> None:
    kernel, _ticket_hash = _seed_kernel(tmp_path)
    source = create_backup(
        kernel,
        tmp_path / "backup",
        requested_at=NOW,
        acknowledge_writers_stopped=True,
    )
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        run_restore_drill(source.backup_dir, existing, requested_at=NOW)
    with pytest.raises(ValueError, match="overlap"):
        run_restore_drill(
            source.backup_dir,
            source.backup_dir / "restore",
            requested_at=NOW,
        )
