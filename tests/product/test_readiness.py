from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import ProductActionRequest, ReadinessLevel, ReadinessState
from nutmeg.product.readiness import evaluate_readiness


def _at() -> datetime:
    return datetime(2026, 8, 24, 10, tzinfo=UTC)


def test_unresolved_identity_blocks_next_action() -> None:
    state = evaluate_readiness(
        identity_resolved=False,
        snapshot_at=None,
        as_of=_at(),
        evidence_count=4,
    )
    assert state.level is ReadinessLevel.BLOCKED
    assert [issue.code for issue in state.issues] == [
        "identity_unresolved",
        "market_anchor_missing",
    ]


def test_no_evidence_is_degraded_but_not_hidden() -> None:
    state = evaluate_readiness(
        identity_resolved=True,
        snapshot_at=_at(),
        as_of=_at(),
        evidence_count=0,
    )
    assert state.level is ReadinessLevel.DEGRADED
    assert [issue.code for issue in state.issues] == ["evidence_empty"]


def test_absent_market_anchor_blocks_forecast() -> None:
    state = evaluate_readiness(
        identity_resolved=True,
        snapshot_at=None,
        as_of=_at(),
        evidence_count=2,
    )
    assert state.level is ReadinessLevel.BLOCKED
    assert [issue.code for issue in state.issues] == ["market_anchor_missing"]


def test_stale_market_anchor_is_degraded_after_six_hours() -> None:
    state = evaluate_readiness(
        identity_resolved=True,
        snapshot_at=_at() - timedelta(hours=6, microseconds=1),
        as_of=_at(),
        evidence_count=2,
    )
    assert state.level is ReadinessLevel.DEGRADED
    assert [issue.code for issue in state.issues] == ["market_anchor_stale"]
    assert state.issues[0].observed_at == _at() - timedelta(hours=6, microseconds=1)


def test_ready_state_has_no_implicit_warning() -> None:
    state = evaluate_readiness(
        identity_resolved=True,
        snapshot_at=_at() - timedelta(hours=1),
        as_of=_at(),
        evidence_count=2,
    )
    assert state == ReadinessState(level=ReadinessLevel.READY)


def test_product_contracts_are_versioned_and_forbid_unknown_fields() -> None:
    request = ProductActionRequest(
        action_type="record_adjudication",
        idempotency_key="action:1",
        payload={"decision": "hold"},
        expected_versions={"claim:c1": 2},
    )
    assert request.schema_version == "1"
    assert request.model_dump(mode="json")["schema_version"] == "1"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ProductActionRequest(
            action_type="record_adjudication",
            idempotency_key="action:2",
            payload={},
            expected_versions={},
            actor_role="judge_operator",
        )
