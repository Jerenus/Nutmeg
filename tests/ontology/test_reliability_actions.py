from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.reliability_actions import (
    RecordReliabilityEvidenceRequest,
)
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.reliability import ReliabilityRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

NOW = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _request(
    *,
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    key: str = "m6:evidence:one",
) -> RecordReliabilityEvidenceRequest:
    return RecordReliabilityEvidenceRequest(
        evidence_kind="deterministic_suite",
        workflow="system",
        business_date=None,
        observed_from=datetime(2026, 8, 24, 9, tzinfo=UTC),
        observed_to=NOW,
        status="passed",
        report={
            "candidate_commit": "abc123",
            "policy_version": "release-v1",
            "checks": {"pytest": True, "ruff": True},
        },
        source_refs=[ObjectRef("test_run", "run-1")],
        actor_id="system:reliability",
        actor_role=role,
        idempotency_key=key,
        requested_at=NOW,
    )


def test_request_requires_aware_bounds_finite_json_and_exact_kinds() -> None:
    with pytest.raises(ValueError, match="observed_from must be timezone-aware"):
        replace(_request(), observed_from=datetime(2026, 8, 24, 9))
    with pytest.raises(ValueError, match="observed_from cannot be after"):
        replace(_request(), observed_from=NOW, observed_to=NOW.replace(hour=9))
    with pytest.raises(ValueError, match="unknown evidence_kind"):
        replace(_request(), evidence_kind="claimed_green")
    with pytest.raises(ValueError, match="finite JSON number"):
        replace(
            _request(),
            report={
                "candidate_commit": "abc123",
                "policy_version": "release-v1",
                "checks": {"pytest": True},
                "duration": float("inf"),
            },
        )
    with pytest.raises(ValueError, match="source_refs cannot be empty"):
        replace(_request(), source_refs=[])
    with pytest.raises(ValueError, match="status must be failed"):
        replace(
            _request(),
            report={
                "candidate_commit": "abc123",
                "policy_version": "release-v1",
                "checks": {"pytest": False},
            },
        )
    with pytest.raises(ValueError, match="all checks are true"):
        replace(_request(), status="failed")


def test_soak_request_requires_workflow_date_and_non_dispatch_real_report() -> None:
    report = {
        "schema_version": "soak-v1",
        "policy_version": "release-v1",
        "dispatch": False,
        "synthetic": False,
        "divergences": {"identity": 0, "audit": 0, "ledger": 0},
    }
    request = replace(
        _request(),
        evidence_kind="soak_run",
        workflow="jczq",
        business_date="2026-08-24",
        report=report,
    )
    assert request.business_date == "2026-08-24"

    with pytest.raises(ValueError, match="workflow must be jczq or zucai"):
        replace(request, workflow="system")
    with pytest.raises(ValueError, match="business_date"):
        replace(request, business_date=None)
    with pytest.raises(ValueError, match="synthetic soak evidence cannot be recorded"):
        replace(request, report={**report, "synthetic": True})
    with pytest.raises(ValueError, match="synthetic soak evidence cannot be recorded"):
        replace(
            request,
            status="failed",
            report={**report, "synthetic": True},
        )
    with pytest.raises(ValueError, match="dispatch-enabled soak evidence"):
        replace(
            request,
            status="failed",
            report={**report, "dispatch": True},
        )


def test_action_is_role_guarded_content_addressed_and_idempotent(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    denied = kernel.reliability_actions.record_evidence(
        _request(role=ActorRole.AI_ANALYST, key="m6:evidence:denied")
    )
    first = kernel.reliability_actions.record_evidence(_request())
    replay = kernel.reliability_actions.record_evidence(_request())
    same_content = kernel.reliability_actions.record_evidence(
        _request(key="m6:evidence:same-content")
    )

    assert denied.status is ActionStatus.REJECTED
    assert first.status is ActionStatus.COMMITTED
    assert replay.action_id == first.action_id
    assert same_content.action_id != first.action_id
    assert same_content.result_refs == first.result_refs
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.reliability.count_evidence() == 1
        evidence = uow.reliability.evidence(first.result_refs[0].object_id)
        assert evidence is not None
        assert evidence.content_hash == _request().content_hash
        assert evidence.source_refs == [
            {"object_type": "test_run", "object_id": "run-1"}
        ]


def test_request_snapshots_inputs_and_rejects_post_validation_mutation(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    report = {
        "candidate_commit": "abc123",
        "policy_version": "release-v1",
        "checks": {"pytest": True},
    }
    refs = [ObjectRef("test_run", "snapshot-run")]
    request = replace(
        _request(),
        report=report,
        source_refs=refs,
        idempotency_key="m6:evidence:snapshot-input",
    )
    report["checks"]["pytest"] = False
    refs.append(ObjectRef("test_run", "late-ref"))

    outcome = kernel.reliability_actions.record_evidence(request)

    with OntologyUnitOfWork(kernel.engine) as uow:
        evidence = uow.reliability.evidence(outcome.result_refs[0].object_id)
        assert evidence is not None
        assert evidence.report["checks"] == {"pytest": True}
        assert evidence.source_refs == [
            {"object_type": "test_run", "object_id": "snapshot-run"}
        ]

    mutated = _request(key="m6:evidence:mutated-after-validation")
    mutated.report["checks"]["pytest"] = False
    with pytest.raises(ValueError, match="changed after validation"):
        kernel.reliability_actions.record_evidence(mutated)


def test_action_detects_reused_key_with_different_content(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    kernel.reliability_actions.record_evidence(_request())

    with pytest.raises(IdempotencyConflictError, match="m6:evidence:one"):
        kernel.reliability_actions.record_evidence(
            replace(
                _request(),
                report={
                    "candidate_commit": "def456",
                    "policy_version": "release-v1",
                    "checks": {"pytest": True},
                },
            )
        )


def test_handler_failure_rolls_back_evidence_and_audits_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel = _kernel(tmp_path)

    def fail_insert(_repository, _row) -> None:
        raise RuntimeError("injected evidence failure")

    monkeypatch.setattr(ReliabilityRepository, "insert_evidence", fail_insert)
    with pytest.raises(RuntimeError, match="injected evidence failure"):
        kernel.reliability_actions.record_evidence(_request())

    with kernel.engine.connect() as connection:
        record = ActionRepository(connection).get_by_idempotency_key(
            "m6:evidence:one"
        )
        assert record is not None
        assert record.status is ActionStatus.FAILED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.reliability.count_evidence() == 0


def test_failed_attempt_does_not_poison_idempotency_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel = _kernel(tmp_path)
    real_insert = ReliabilityRepository.insert_evidence
    calls = {"n": 0}

    def fail_once(repository, row) -> None:
        if calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("transient evidence failure")
        return real_insert(repository, row)

    monkeypatch.setattr(ReliabilityRepository, "insert_evidence", fail_once)
    with pytest.raises(RuntimeError, match="transient evidence failure"):
        kernel.reliability_actions.record_evidence(_request())

    retried = kernel.reliability_actions.record_evidence(_request())
    assert retried.status is ActionStatus.COMMITTED

    from sqlalchemy import select

    from nutmeg.ontology.repository import schema

    with kernel.engine.connect() as connection:
        current = ActionRepository(connection).get_by_idempotency_key(
            "m6:evidence:one"
        )
        assert current is not None
        assert current.status is ActionStatus.COMMITTED
        rows = connection.execute(
            select(
                schema.actions.c.idempotency_key, schema.actions.c.status
            ).where(schema.actions.c.action_type == "record_reliability_evidence")
        ).all()
    failed_rows = [row for row in rows if row.status == "failed"]
    assert len(failed_rows) == 1                      # audit row survives …
    assert failed_rows[0].idempotency_key.startswith(
        "m6:evidence:one#failed-"
    )                                                 # … under a released key
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.reliability.count_evidence() == 1
