from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, insert

from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.product import operator_evidence
from nutmeg.product.operator_evidence import OperatorDependencyLeaves
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)

KEY = b"package-five-evidence-token-key-32-bytes"
AT = datetime(2026, 9, 4, 8, tzinfo=UTC)


def _leaves() -> OperatorDependencyLeaves:
    return OperatorDependencyLeaves(
        slate_revision_ids=("slate-1",),
        offer_state_tokens=("offer-1:open", "offer-2:open"),
        evidence_bundle_revision_ids=("bundle-1", "bundle-2"),
        forecast_revision_ids=("forecast-1", "forecast-2"),
        prescription_revision_ids=("prescription-1",),
        candidate_set_revision_ids=("candidate-set-1",),
        selection_revision_ids=("selection-1",),
        audit_revision_ids=("audit-1",),
    )


def _token(codec: OperatorSnapshotTokenCodec, leaves: OperatorDependencyLeaves) -> str:
    return codec.encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="a" * 64,
            work_item_id="zucai:26116:evidence",
            command_kind=OperatorCommandKind.FREEZE_EVIDENCE,
            dependency_revision_ids=list(leaves.token_revision_ids()),
        )
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("slate_revision_ids", ("slate-2",)),
        ("offer_state_tokens", ("offer-1:closed", "offer-2:open")),
        ("evidence_bundle_revision_ids", ("bundle-1", "bundle-3")),
        ("forecast_revision_ids", ("forecast-1", "forecast-3")),
        ("prescription_revision_ids", ("prescription-2",)),
        ("candidate_set_revision_ids", ("candidate-set-2",)),
        ("selection_revision_ids", ("selection-2",)),
        ("audit_revision_ids", ("audit-2",)),
    ],
)
def test_every_current_leaf_change_invalidates_the_old_command_token(
    field: str,
    replacement: tuple[str, ...],
) -> None:
    codec = OperatorSnapshotTokenCodec(KEY)
    before = _leaves()
    token = _token(codec, before)
    after = replace(before, **{field: replacement})

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        codec.verify(
            token,
            expected_command_kind=OperatorCommandKind.FREEZE_EVIDENCE,
            current_task_snapshot_hash="a" * 64,
            current_work_item_id="zucai:26116:evidence",
            current_dependency_revision_ids=after.token_revision_ids(),
        )

    assert caught.value.code == "task_snapshot_changed"


def test_dependency_leaves_are_typed_sorted_and_duplicate_free() -> None:
    leaves = _leaves()

    assert leaves.token_revision_ids() == tuple(sorted(leaves.token_revision_ids()))
    assert "slate:slate-1" in leaves.token_revision_ids()
    assert "offer_state:offer-1:open" in leaves.token_revision_ids()
    assert len(leaves.token_revision_ids()) == len(set(leaves.token_revision_ids()))

    with pytest.raises(ValueError, match="sorted and unique"):
        replace(leaves, forecast_revision_ids=("forecast-2", "forecast-1"))


def test_new_evidence_changes_current_leaves_without_mutating_frozen_leaves() -> None:
    frozen = _leaves()
    refreshed = replace(
        frozen,
        evidence_bundle_revision_ids=("bundle-1", "bundle-3"),
    )

    assert frozen.evidence_bundle_revision_ids == ("bundle-1", "bundle-2")
    assert refreshed.has_changed_from(frozen)
    assert not frozen.has_changed_from(frozen)


def test_historical_freeze_request_lookup_ignores_future_requests() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        sod.operator_evidence_freeze_requests.create(connection)
        connection.execute(
            insert(sod.operator_evidence_freeze_requests).values(
                evidence_freeze_request_id="request-future",
                action_id="action-future",
                task_family_id="jczq:2026-09-04",
                lane="jczq",
                business_key="2026-09-04",
                slate_revision_id="slate-1",
                task_snapshot_hash="a" * 64,
                requirement_revision_token="requirements-1",
                information_cutoff_at=(AT + timedelta(hours=1)).isoformat(),
                policy_version="governance-v1",
                dependency_fingerprint="b" * 64,
                requested_at=(AT + timedelta(hours=1)).isoformat(),
            )
        )
        row = operator_evidence._freeze_request_for_gate(
            connection,
            task_family_id="jczq:2026-09-04",
            requirement_revision_token="requirements-1",
            as_of=AT,
        )

    assert row is None


@pytest.mark.parametrize(
    ("freeze_state", "new_evidence", "expected"),
    (
        ("not_requested", False, True),
        ("queued", True, False),
        ("linked", False, False),
        ("linked", True, True),
        ("failed", False, False),
        ("failed", True, True),
    ),
)
def test_freeze_command_is_offered_only_for_a_reachable_request(
    freeze_state: str,
    new_evidence: bool,
    expected: bool,
) -> None:
    assert operator_evidence._may_request_freeze(
        gate_ready=True,
        freeze_state=freeze_state,
        new_evidence_available=new_evidence,
    ) is expected
