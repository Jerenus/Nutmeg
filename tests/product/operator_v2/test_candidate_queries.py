from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.operator.decision_actions import SelectTicketCandidateRequest
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_contracts import ConstructTicketStep, OperatorTaskState
from nutmeg.product.operator_tokens import OperatorCommandKind, OperatorSnapshotTokenCodec
from tests.ontology.operator.test_candidate_actions import (
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.product.operator_v2.test_judgment_api import (
    KEY,
    NOW,
    _seed_task_identity,
    _task_queries,
)


def _ready_queries(tmp_path: Path):
    fixture = _ready_fixture(tmp_path)
    _seed_task_identity(fixture.judgment)
    return fixture, _task_queries(fixture.judgment)


def _generate_candidates(fixture):
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=request.result_refs[0].object_id)


def test_frozen_prescription_exposes_exact_opaque_generation_context(
    tmp_path: Path,
) -> None:
    fixture, queries = _ready_queries(tmp_path)
    codec = OperatorSnapshotTokenCodec(KEY)

    context = queries.candidate_generation_context(
        "jczq:2026-09-04",
        as_of=NOW,
    )
    task = queries.task("jczq:2026-09-04", as_of=NOW)

    assert context.market_prior_baseline_revision_id == fixture.baseline_id
    assert context.baseline_envelope_revision_id == fixture.envelope_id
    assert context.judgment_prescription_revision_id == fixture.prescription_id
    assert context.fixed_prize_policy_revision_id is None
    assert context.expected_current_revision_no == 0
    expected_tokens = (
        (context.market_prior_baseline_token, f"baseline:{fixture.baseline_id}"),
        (context.baseline_envelope_token, f"envelope:{fixture.envelope_id}"),
        (context.judgment_prescription_token, f"prescription:{fixture.prescription_id}"),
    )
    for token, dependency in expected_tokens:
        assert token not in {
            fixture.baseline_id,
            fixture.envelope_id,
            fixture.prescription_id,
        }
        payload = codec.decode(token)
        assert payload.command_kind is OperatorCommandKind.REQUEST_CANDIDATE_GENERATION
        assert payload.dependency_revision_ids == [dependency]

    assert task.selected.state is OperatorTaskState.CONSTRUCT_TICKET
    assert isinstance(task.step, ConstructTicketStep)
    assert task.step.mode == "candidate_request"
    assert task.step.market_prior_baseline_token == context.market_prior_baseline_token
    assert task.step.baseline_envelope_token == context.baseline_envelope_token
    assert task.step.judgment_prescription_token == context.judgment_prescription_token
    command = codec.decode(task.step.request_generation_token or "")
    assert command.command_kind is OperatorCommandKind.REQUEST_CANDIDATE_GENERATION
    assert list(command.dependency_revision_ids) == list(context.dependency_revision_ids)


def test_generated_sets_render_complete_comparison_and_selection_context(
    tmp_path: Path,
) -> None:
    fixture, queries = _ready_queries(tmp_path)
    _generate_candidates(fixture)
    codec = OperatorSnapshotTokenCodec(KEY)

    task = queries.task("jczq:2026-09-04", as_of=NOW)

    assert task.selected.state is OperatorTaskState.CONSTRUCT_TICKET
    assert isinstance(task.step, ConstructTicketStep)
    assert task.step.mode == "candidate_comparison"
    assert task.step.selection_completed is False
    assert len(task.step.candidate_sets) == 2
    judgment_set = next(
        item for item in task.step.candidate_sets if not item.comparison_only
    )
    conditional_set = next(
        item for item in task.step.candidate_sets if item.comparison_only
    )
    judgment = judgment_set.candidates[0]
    conditional = conditional_set.candidates[0]
    assert (judgment.selectable, judgment.deployable) == (True, True)
    assert (conditional.selectable, conditional.deployable) == (False, False)
    assert judgment.composition.singles == ["场 001 · 3"]
    assert judgment.composition.doubles == []
    assert judgment.composition.full_covers == []
    assert judgment.composition.omissions == []
    assert judgment.composition.pass_groups == ["single-1 · 001 · 场 001"]
    assert judgment.ticket_count == 1
    assert judgment.distinct_note_count == 1
    assert judgment.paid_note_unit_count == 1
    assert judgment.stake_minor == 200
    assert judgment.objective_probability_decimal == "0.400000000000"
    assert judgment.break_even_bonus_minor == 500
    assert judgment.common_dead_faces == ["场 001 · 1", "场 001 · 0"]
    assert judgment.candidate_token is not None

    context = queries.candidate_selection_context(
        "jczq:2026-09-04",
        judgment.candidate_token,
        as_of=NOW,
    )
    assert context.expected_current_revision_no == 0
    assert context.candidate_set_revision_id
    assert context.candidate_revision_id
    candidate_payload = codec.decode(judgment.candidate_token)
    assert candidate_payload.command_kind is OperatorCommandKind.SELECT_CANDIDATE
    assert f"candidate:{context.candidate_revision_id}" in (
        candidate_payload.dependency_revision_ids
    )
    selection_payload = codec.decode(task.step.selection_command_token or "")
    assert selection_payload.command_kind is OperatorCommandKind.SELECT_CANDIDATE
    assert "selection:none" in selection_payload.dependency_revision_ids

    serialized = task.step.model_dump_json()
    assert context.candidate_set_revision_id not in serialized
    assert context.candidate_revision_id not in serialized
    assert "content_hash" not in serialized
    assert "recommended" not in serialized


def test_selection_advances_summary_but_keeps_comparison_read_only_until_package_8(
    tmp_path: Path,
) -> None:
    fixture, queries = _ready_queries(tmp_path)
    _generate_candidates(fixture)
    comparison = queries.task("jczq:2026-09-04", as_of=NOW)
    assert isinstance(comparison.step, ConstructTicketStep)
    judgment_set = next(
        item for item in comparison.step.candidate_sets if not item.comparison_only
    )
    candidate_token = judgment_set.candidates[0].candidate_token
    assert candidate_token is not None
    context = queries.candidate_selection_context(
        "jczq:2026-09-04",
        candidate_token,
        as_of=NOW,
    )
    fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=context.candidate_set_revision_id,
            candidate_revision_id=context.candidate_revision_id,
            reason="Jun selected this candidate for the external audit path.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="candidate:query-selection:1",
            requested_at=NOW + timedelta(seconds=1),
            expected_current_revision_no=context.expected_current_revision_no,
        )
    )

    selected = queries.task(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=2),
    )

    assert selected.selected.state is OperatorTaskState.AUDIT_DEPLOYMENT
    assert isinstance(selected.step, ConstructTicketStep)
    assert selected.step.mode == "candidate_comparison"
    assert selected.step.selection_completed is True
    assert selected.step.selected_candidate_code == "C0001"
    assert selected.step.selection_command_token is None
    assert all(
        not candidate.selectable and candidate.candidate_token is None
        for candidate_set in selected.step.candidate_sets
        for candidate in candidate_set.candidates
    )
    with pytest.raises(ProductActionBlockedError, match="already selected"):
        queries.candidate_selection_context(
            "jczq:2026-09-04",
            candidate_token,
            as_of=NOW + timedelta(seconds=2),
        )
