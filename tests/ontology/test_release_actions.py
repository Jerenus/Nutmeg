from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.reliability_actions import ApproveReleaseRequest
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.reliability.release import ReleaseEvaluator
from tests.reliability.test_release_policy import (
    COMMIT,
    NOW,
    _record_system,
    _seed_soak,
    _seed_system,
)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _evaluation(kernel):
    with OntologyUnitOfWork(kernel.engine) as uow:
        return ReleaseEvaluator(uow.reliability).evaluate(
            "v1.0.0", candidate_commit=COMMIT, evaluated_at=NOW
        )


def _approval(snapshot: str, *, role=ActorRole.JUDGE_OPERATOR, key="m6:approve"):
    return ApproveReleaseRequest(
        release_version="v1.0.0",
        candidate_commit=COMMIT,
        expected_snapshot_sha256=snapshot,
        reason="all release-v1 evidence reviewed by Jun",
        actor_id="operator:jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=NOW,
    )


def test_ai_is_denied_and_judge_cannot_approve_blocked_release(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    evaluation = _evaluation(kernel)

    denied = kernel.reliability_actions.approve_release(
        _approval(
            evaluation.evidence_snapshot_sha256,
            role=ActorRole.AI_ANALYST,
            key="m6:approve:ai",
        )
    )
    assert denied.status is ActionStatus.REJECTED

    with pytest.raises(ValueError, match="release gates are blocked"):
        kernel.reliability_actions.approve_release(
            _approval(evaluation.evidence_snapshot_sha256)
        )
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.reliability.count_approvals() == 0


def test_approval_rechecks_snapshot_and_becomes_superseded(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    _seed_system(kernel)
    _seed_soak(kernel)
    original = _evaluation(kernel)
    assert original.ready is True

    _record_system(kernel, "scheduler_authority", suffix="new-current")
    changed = _evaluation(kernel)
    assert changed.ready is True
    assert changed.evidence_snapshot_sha256 != original.evidence_snapshot_sha256
    with pytest.raises(OptimisticConcurrencyError, match="snapshot"):
        kernel.reliability_actions.approve_release(
            _approval(original.evidence_snapshot_sha256, key="m6:approve:stale")
        )

    approved = kernel.reliability_actions.approve_release(
        _approval(changed.evidence_snapshot_sha256)
    )
    replay = kernel.reliability_actions.approve_release(
        _approval(changed.evidence_snapshot_sha256)
    )
    assert approved.status is ActionStatus.COMMITTED
    assert replay.action_id == approved.action_id
    assert _evaluation(kernel).approval_status == "current"

    _record_system(kernel, "observability", suffix="after-approval")
    superseded = _evaluation(kernel)
    assert superseded.ready is True
    assert superseded.approval_status == "superseded"
    with OntologyUnitOfWork(kernel.engine) as uow:
        approval = uow.reliability.approval_for_release("v1.0.0")
        assert approval is not None
        assert approval.evidence_snapshot_sha256 == changed.evidence_snapshot_sha256
        assert uow.reliability.count_approvals() == 1


def test_approval_request_requires_aware_time_hash_and_reason() -> None:
    with pytest.raises(ValueError, match="requested_at must be timezone-aware"):
        replace(_approval("a" * 64), requested_at=datetime(2026, 8, 24, 12))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _approval("bad")
    with pytest.raises(ValueError, match="reason is required"):
        replace(_approval("a" * 64), reason=" ")
