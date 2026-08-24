from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.reliability.models import (
    ReleaseApprovalRow,
    ReliabilityEvidenceRow,
)
from nutmeg.ontology.repository import schema, schema_reliability
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = "2026-08-24T10:00:00+00:00"
RELIABILITY_PERMISSIONS = {
    ("record_reliability_evidence", "deterministic_system"),
    ("record_reliability_evidence", "judge_operator"),
    ("approve_release", "judge_operator"),
}
SCOREBOARD_PERMISSIONS = {
    ("record_scoreboard_observation", "judge_operator"),
    ("approve_scoreboard_cutover", "judge_operator"),
    ("record_scoreboard_shadow_review", "deterministic_system"),
    ("record_scoreboard_export", "deterministic_system"),
}


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    report = kernel.initialize()
    return kernel, report


def _action(kernel, key: str) -> str:
    outcome = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=f'{{"key":"{key}"}}'.encode(),
            content_type="application/json",
            source_name="m6-test",
            source_type="fixture",
            actor_id="source:m6-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key=f"m6:artifact:{key}",
            retrieved_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
        )
    )
    return outcome.action_id


def _evidence(
    evidence_id: str,
    action_id: str,
    *,
    content_hash: str,
    kind: str = "fault_matrix",
    recorded_at: str = AT,
) -> ReliabilityEvidenceRow:
    return ReliabilityEvidenceRow(
        reliability_evidence_id=evidence_id,
        evidence_kind=kind,
        workflow="system",
        business_date=None,
        observed_from="2026-08-24T09:00:00+00:00",
        observed_to=AT,
        status="passed",
        report={"candidate_commit": "abc123", "checks": {"safe": True}},
        source_refs=[
            {"object_type": "test_run", "object_id": f"run-{evidence_id}"}
        ],
        content_hash=content_hash,
        recorded_at=recorded_at,
        action_id=action_id,
    )


def test_migration_14_creates_tables_and_exact_permissions(tmp_path: Path) -> None:
    kernel, report = _kernel(tmp_path)

    assert report.applied_versions[-1] == 14
    assert {"reliability_evidence", "release_approvals"} <= set(
        inspect(kernel.engine).get_table_names()
    )
    with kernel.engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {
        (row["action_type"], row["actor_role"])
        for row in rows
        if row["action_type"]
        in {"record_reliability_evidence", "approve_release"}
    }
    assert seeded == RELIABILITY_PERMISSIONS
    assert schema_reliability.reliability_evidence.c.action_id.unique is True
    assert schema_reliability.release_approvals.c.release_version.unique is True


def test_migration_14_upgrades_an_existing_schema_13_store(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.sqlite3")
    assert run_migrations(engine, migrations=MIGRATIONS[:13]).applied_versions[-1] == 13
    with engine.connect() as connection:
        before = connection.execute(select(schema.action_permissions)).mappings().all()
    assert SCOREBOARD_PERMISSIONS <= {
        (row["action_type"], row["actor_role"]) for row in before
    }

    report = run_migrations(engine)

    assert report.applied_versions == (14,)
    with engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {
        (row["action_type"], row["actor_role"])
        for row in rows
        if row["action_type"]
        in {"record_reliability_evidence", "approve_release"}
    }
    assert seeded == RELIABILITY_PERMISSIONS


def test_repository_round_trips_json_and_orders_evidence_deterministically(
    tmp_path: Path,
) -> None:
    kernel, _report = _kernel(tmp_path)
    later_action = _action(kernel, "later")
    earlier_action = _action(kernel, "earlier")
    later = _evidence(
        "rel-later",
        later_action,
        content_hash="b" * 64,
        recorded_at="2026-08-24T11:00:00+00:00",
    )
    earlier = _evidence(
        "rel-earlier",
        earlier_action,
        content_hash="a" * 64,
        recorded_at="2026-08-24T10:00:00+00:00",
    )

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.reliability.insert_evidence(later)
        uow.reliability.insert_evidence(earlier)
        assert uow.reliability.evidence("rel-earlier") == earlier
        assert uow.reliability.evidence_by_hash("a" * 64) == earlier

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.reliability.list_evidence() == [later, earlier]
        assert uow.reliability.list_evidence(kind="fault_matrix") == [later, earlier]
        assert uow.reliability.list_evidence(
            recorded_to="2026-08-24T10:30:00+00:00"
        ) == [earlier]
        assert uow.reliability.latest_by_kind("fault_matrix") == later


def test_repository_rejects_duplicate_hash_and_release_version(tmp_path: Path) -> None:
    kernel, _report = _kernel(tmp_path)
    first_action = _action(kernel, "first")
    duplicate_action = _action(kernel, "duplicate")
    approval_action = _action(kernel, "approval")
    duplicate_approval_action = _action(kernel, "duplicate-approval")
    first = _evidence("rel-first", first_action, content_hash="c" * 64)
    duplicate = _evidence("rel-duplicate", duplicate_action, content_hash="c" * 64)

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.reliability.insert_evidence(first)
    with pytest.raises(IntegrityError):
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.reliability.insert_evidence(duplicate)

    approval = ReleaseApprovalRow(
        release_approval_id="rap-one",
        release_version="v1.0.0",
        evidence_snapshot_sha256="d" * 64,
        policy_version="release-v1",
        reason="all governed gates passed",
        approved_at=AT,
        action_id=approval_action,
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.reliability.insert_approval(approval)
        assert uow.reliability.approval_for_release("v1.0.0") == approval
    with pytest.raises(IntegrityError):
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.reliability.insert_approval(
                ReleaseApprovalRow(
                    release_approval_id="rap-two",
                    release_version="v1.0.0",
                    evidence_snapshot_sha256="e" * 64,
                    policy_version="release-v1",
                    reason="duplicate release",
                    approved_at=AT,
                    action_id=duplicate_approval_action,
                )
            )


def test_kernel_status_counts_reliability_rows(tmp_path: Path) -> None:
    kernel, _report = _kernel(tmp_path)
    action_id = _action(kernel, "status")
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.reliability.insert_evidence(
            _evidence("rel-status", action_id, content_hash="f" * 64)
        )

    status = kernel.status()

    assert status.reliability_evidence_count == 1
    assert status.release_approval_count == 0
    assert status.to_dict()["reliability_evidence_count"] == 1
