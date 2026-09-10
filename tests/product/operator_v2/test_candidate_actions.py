from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from nutmeg.config.settings import AppSettings, OperatorRuntimeScope, OperatorSurfaceMode
from nutmeg.ontology.actions.models import (
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.operator.decision_actions import (
    RequestCandidateGenerationRequest,
    SelectTicketCandidateRequest,
)
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_runtime import OperatorRuntimeConfig
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)
from nutmeg.product.wiring import build_product_services

KEY = b"package-seven-product-action-key-long-enough"
SNAPSHOT_HASH = "c" * 64
TASK_KEY = "zucai:26111"
WORK_ITEM_ID = "zucai:26111:issue:current"
DEPENDENCIES = (
    "baseline:baseline-1",
    "bundle:bundle-1",
    "candidate-set-revision:3",
    "envelope:envelope-1",
    "prescription:prescription-1",
)
NOW = "2026-09-04T08:00:00+00:00"


def _command_token(kind: OperatorCommandKind) -> str:
    return OperatorSnapshotTokenCodec(KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash=SNAPSHOT_HASH,
            work_item_id=WORK_ITEM_ID,
            command_kind=kind,
            dependency_revision_ids=list(DEPENDENCIES),
        )
    )


class _Queries:
    @staticmethod
    def now():
        return NOW

    def candidate_generation_context(self, task_key: str, *, as_of):
        assert (task_key, as_of.isoformat()) == (TASK_KEY, NOW)
        return SimpleNamespace(
            task_key=TASK_KEY,
            task_snapshot_hash=SNAPSHOT_HASH,
            work_item_id=WORK_ITEM_ID,
            dependency_revision_ids=DEPENDENCIES,
            task_evidence_bundle_revision_id="bundle-1",
            market_prior_baseline_revision_id="baseline-1",
            baseline_envelope_revision_id="envelope-1",
            judgment_prescription_revision_id="prescription-1",
            fixed_prize_policy_revision_id="policy-1",
            expected_current_revision_no=3,
            market_prior_baseline_token="opaque.baseline",
            baseline_envelope_token="opaque.envelope",
            judgment_prescription_token="opaque.prescription",
        )

    def candidate_selection_context(self, task_key: str, candidate_token: str, *, as_of):
        assert (task_key, as_of.isoformat()) == (TASK_KEY, NOW)
        candidate_refs = {
            "opaque.candidate-1": (
                "opaque.candidate-1",
                "candidate-set-1",
                "candidate-1",
            ),
            "opaque.blocked-2": (
                "opaque.blocked-2",
                "candidate-set-1",
                "candidate-2",
            ),
        }
        return SimpleNamespace(
            task_key=TASK_KEY,
            task_snapshot_hash=SNAPSHOT_HASH,
            work_item_id=WORK_ITEM_ID,
            dependency_revision_ids=DEPENDENCIES,
            expected_current_revision_no=3,
            candidate_refs_by_token=(
                (candidate_refs[candidate_token],)
                if candidate_token in candidate_refs
                else ()
            ),
        )


class _DecisionActions:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def request_candidate_generation(self, request) -> ActionOutcome:
        self.requests.append(request)
        return ActionOutcome(
            action_id="action-generation-1",
            action_type="request_candidate_generation",
            status=ActionStatus.COMMITTED,
            result_refs=(
                ObjectRef("operator_candidate_generation_request", "request-1"),
            ),
        )

    def select_ticket_candidate(self, request) -> ActionOutcome:
        self.requests.append(request)
        return ActionOutcome(
            action_id="action-selection-1",
            action_type="select_ticket_candidate",
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("ticket_candidate_selection", "selection-1"),),
        )


def _service() -> tuple[OperatorActionService, _DecisionActions]:
    decision_actions = _DecisionActions()
    return (
        OperatorActionService(
            queries=_Queries(),
            action_gateway=SimpleNamespace(),
            decision_actions=decision_actions,
            snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
            clock=lambda: NOW,
        ),
        decision_actions,
    )


def _generation_command(**updates: object):
    values = {
        "task_key": TASK_KEY,
        "expected_snapshot_token": _command_token(
            OperatorCommandKind.REQUEST_CANDIDATE_GENERATION
        ),
        "market_prior_baseline_token": "opaque.baseline",
        "baseline_envelope_token": "opaque.envelope",
        "judgment_prescription_token": "opaque.prescription",
        "idempotency_key": "browser:candidate-generation:1",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _selection_command(**updates: object):
    values = {
        "task_key": TASK_KEY,
        "expected_snapshot_token": _command_token(OperatorCommandKind.SELECT_CANDIDATE),
        "candidate_token": "opaque.candidate-1",
        "reason": "采用该候选作为出票草稿。",
        "idempotency_key": "browser:candidate-selection:1",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_request_candidate_generation_delegates_exact_server_lineage() -> None:
    service, decision_actions = _service()

    receipt = service.request_candidate_generation(
        _generation_command(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "request_candidate_generation"
    assert receipt.status == "queued"
    request = decision_actions.requests[0]
    assert isinstance(request, RequestCandidateGenerationRequest)
    assert (
        request.task_evidence_bundle_revision_id,
        request.market_prior_baseline_revision_id,
        request.baseline_envelope_revision_id,
        request.judgment_prescription_revision_id,
        request.fixed_prize_policy_revision_id,
        request.work_item_id,
        request.expected_current_revision_no,
    ) == (
        "bundle-1",
        "baseline-1",
        "envelope-1",
        "prescription-1",
        "policy-1",
        WORK_ITEM_ID,
        3,
    )


def test_request_candidate_generation_rejects_one_changed_lineage_token() -> None:
    service, decision_actions = _service()

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        service.request_candidate_generation(
            _generation_command(baseline_envelope_token="opaque.stale-envelope"),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    assert caught.value.code == "task_snapshot_changed"
    assert decision_actions.requests == []


def test_select_ticket_candidate_uses_independent_command_and_candidate_tokens() -> None:
    service, decision_actions = _service()

    receipt = service.select_ticket_candidate(
        _selection_command(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "select_candidate"
    assert receipt.status == "completed"
    request = decision_actions.requests[0]
    assert isinstance(request, SelectTicketCandidateRequest)
    assert (
        request.candidate_set_revision_id,
        request.candidate_revision_id,
        request.reason,
        request.expected_current_revision_no,
    ) == (
        "candidate-set-1",
        "candidate-1",
        "采用该候选作为出票草稿。",
        3,
    )


def test_select_ticket_candidate_rejects_unknown_candidate_token() -> None:
    service, decision_actions = _service()

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        service.select_ticket_candidate(
            _selection_command(candidate_token="opaque.other-candidate"),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    assert caught.value.code == "invalid_request"
    assert decision_actions.requests == []


def test_active_application_bootstraps_both_zucai_fixed_prize_policies(
    tmp_path: Path,
) -> None:
    data_dir = (tmp_path / "candidate").resolve()
    production_dir = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production_dir,
        operator_runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        operator_surface_mode=OperatorSurfaceMode.ACTIVE,
        operator_token_signing_key="candidate-policy-signing-key-32-bytes",
    )
    build_ontology_kernel(settings).initialize()
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit="a" * 40,
    )

    first = build_product_services(settings, runtime_config=runtime)
    second = build_product_services(settings, runtime_config=runtime)

    with first.kernel.engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT ticket_kind, policy_version, currency, "
                "standard_unit_stake_minor, official_void_rule "
                "FROM zucai_fixed_prize_policy_revisions ORDER BY ticket_kind"
            )
        ).all()
        actions = connection.execute(
            text(
                "SELECT actor_role, status, COUNT(*) FROM actions "
                "WHERE action_type = 'register_zucai_fixed_prize_policy' "
                "GROUP BY actor_role, status"
            )
        ).all()
    second.kernel.engine.dispose()
    assert policies == [
        ("renjiu", "zucai-fixed-prize-v1", "CNY", 200, "all_faces_match"),
        ("sfc", "zucai-fixed-prize-v1", "CNY", 200, "all_faces_match"),
    ]
    assert actions == [("deterministic_system", "committed", 2)]
