from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.operator import decision_actions as decision_action_module
from nutmeg.ontology.operator.decision_actions import (
    FreezeJudgmentPrescriptionRequest,
    RequestCandidateGenerationRequest,
    SelectTicketCandidateRequest,
    StaleOperatorDecisionDependencyError,
)
from nutmeg.ontology.operator.result_actions import (
    CandidateAuditFindingInput,
    CandidateBandOutcomeInput,
    CandidateDeadFaceInput,
    CandidateMetricsInput,
    CandidateSetInput,
    CandidateTicketInput,
    CandidateTicketLegInput,
    GenerateTicketCandidateSetRequest,
    OperatorResultActions,
    RegisterZucaiFixedPrizePolicyRequest,
    TicketCandidateInput,
)
from nutmeg.ontology.repository.market import QuoteRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_judgment_actions import (
    AT,
    WORK_ITEM_ID,
    JudgmentFixture,
    _create_baseline_and_envelope,
    _envelope_request,
    _fixture,
    _judgment_request,
)


@dataclass(frozen=True, slots=True)
class CandidateFixture:
    judgment: JudgmentFixture
    result_actions: OperatorResultActions
    baseline_id: str
    envelope_id: str
    prescription_id: str


def _ready_fixture(tmp_path: Path) -> CandidateFixture:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    judgment = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )
    judgment_id = next(
        ref.object_id
        for ref in judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = fixture.decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=WORK_ITEM_ID,
            judgment_revision_ids=(judgment_id,),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="candidate:prescription:1",
            requested_at=AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    return CandidateFixture(
        judgment=fixture,
        result_actions=OperatorResultActions(fixture.action_service),
        baseline_id=baseline_id,
        envelope_id=envelope_id,
        prescription_id=prescription.result_refs[0].object_id,
    )


def test_candidate_request_contracts_are_public_exports() -> None:
    assert {
        "RequestCandidateGenerationRequest",
        "SelectTicketCandidateRequest",
    } <= set(decision_action_module.__all__)


def _generation_request(
    fixture: CandidateFixture,
    *,
    key: str = "candidate:request:1",
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
    expected_revision: int = 0,
) -> RequestCandidateGenerationRequest:
    return RequestCandidateGenerationRequest(
        task_evidence_bundle_revision_id=fixture.judgment.task_bundle_revision_id,
        market_prior_baseline_revision_id=fixture.baseline_id,
        baseline_envelope_revision_id=fixture.envelope_id,
        judgment_prescription_revision_id=fixture.prescription_id,
        work_item_id=WORK_ITEM_ID,
        fixed_prize_policy_revision_id=None,
        actor_id="jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT + timedelta(seconds=6),
        expected_current_revision_no=expected_revision,
    )


def _candidate(
    *,
    set_kind: str,
    content_hash: str,
    selection_code: str = "3",
    quote_id: str = "quote-3",
    booked_odds: str = "2.500000000000",
    odds_band: str | None = None,
    parent_candidate_revision_id: str | None = None,
    delta_reason: str | None = None,
) -> TicketCandidateInput:
    conditional = set_kind == "conditional_market_counterfactual"
    ticket = CandidateTicketInput(
        ticket_kind="jczq_pass",
        structure_code="single-1",
        group_code="001",
        currency="CNY",
        unit_stake_minor=200,
        unit_count=1,
        stake_minor=200,
        composition_hash=f"ticket-{content_hash}",
        fixed_prize_policy_revision_id=None,
        legs=(
            CandidateTicketLegInput(
                official_offer_revision_id="offer-revision-1",
                match_id="match-1",
                market_definition_id="md-had",
                selection_code=selection_code,
                quote_id=quote_id,
                booked_decimal_odds=booked_odds,
                settlement_parameter_decimal=None,
            ),
        ),
    )
    return TicketCandidateInput(
        partition="eligible",
        rank=1,
        deployable=not conditional,
        tickets=(ticket,),
        metrics=CandidateMetricsInput(
            currency="CNY",
            ticket_count=1,
            distinct_note_count=1,
            paid_note_unit_count=1,
            stake_minor=200,
            capital_utilization_decimal="0.010000000000",
            probability_kind="all_required_legs",
            objective_probability_decimal="0.400000000000",
            expected_broken_legs_decimal="0.600000000000",
            break_even_bonus_minor=500,
            break_even_to_official_median_decimal="0.125000000000",
        ),
        common_dead_faces=(
            CandidateDeadFaceInput(official_match_no="001", face_code="1"),
            CandidateDeadFaceInput(official_match_no="001", face_code="0"),
        ),
        audit_findings=(),
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        content_hash=content_hash,
        odds_band=odds_band,
        target_odds_min_decimal=("15.000000000000" if odds_band else None),
        target_odds_max_decimal=("35.000000000000" if odds_band else None),
        combined_decimal_odds=("20.000000000000" if odds_band else None),
        parent_candidate_revision_id=parent_candidate_revision_id,
        delta_reason=delta_reason,
    )


def _band_outcomes() -> tuple[CandidateBandOutcomeInput, ...]:
    return (
        CandidateBandOutcomeInput("10x", "no_feasible_candidate", "empty", 0),
        CandidateBandOutcomeInput("20x", "candidates", None, 1),
        CandidateBandOutcomeInput("50x", "no_feasible_candidate", "empty", 0),
        CandidateBandOutcomeInput("100x", "no_feasible_candidate", "empty", 0),
    )


def _empty_band_outcomes() -> tuple[CandidateBandOutcomeInput, ...]:
    return tuple(
        CandidateBandOutcomeInput(band, "no_feasible_candidate", "empty", 0)
        for band in ("10x", "20x", "50x", "100x")
    )


def _claim_generation_job(
    fixture: CandidateFixture,
    *,
    as_of=AT + timedelta(seconds=7),
):
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="candidate_generation",
            lease_owner="candidate-worker",
            as_of=as_of.isoformat(),
            lease_expires_at=(AT + timedelta(minutes=5)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1
    return claimed[0]


def _generate(
    fixture: CandidateFixture,
    *,
    request_id: str,
    key: str = "candidate:generate:1",
    judgment_candidate: TicketCandidateInput | None = None,
    conditional_candidate: TicketCandidateInput | None = None,
    band_outcomes: tuple[CandidateBandOutcomeInput, ...] = (),
    change_delta: dict[str, object] | None = None,
    rationale: str | None = None,
    as_of=AT + timedelta(seconds=7),
):
    job = _claim_generation_job(fixture, as_of=as_of)
    return fixture.result_actions.generate_ticket_candidate_set(
        GenerateTicketCandidateSetRequest(
            generation_request_id=request_id,
            candidate_sets=(
                CandidateSetInput(
                    set_kind="judgment_bound",
                    candidates=(
                        judgment_candidate
                        or _candidate(
                            set_kind="judgment_bound", content_hash="a" * 64
                        ),
                    ),
                    band_outcomes=band_outcomes,
                    change_delta=change_delta,
                    rationale=rationale,
                ),
                CandidateSetInput(
                    set_kind="conditional_market_counterfactual",
                    candidates=(
                        conditional_candidate
                        or _candidate(
                            set_kind="conditional_market_counterfactual",
                            content_hash="b" * 64,
                        ),
                    ),
                    band_outcomes=band_outcomes,
                    change_delta=change_delta,
                    rationale=rationale,
                ),
            ),
            generator_version="operator-candidate-v1",
            worker_job_id=job.worker_job_id,
            lease_owner="candidate-worker",
            actor_id="system:operator-candidates",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=key,
            requested_at=as_of + timedelta(seconds=1),
        )
    )


def test_generation_persists_odds_band_iteration_and_all_band_outcomes(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    judgment = _candidate(
        set_kind="judgment_bound",
        content_hash="c" * 64,
        odds_band="20x",
        parent_candidate_revision_id="candidate-parent",
        delta_reason="replace stale away leg",
    )
    conditional = _candidate(
        set_kind="conditional_market_counterfactual",
        content_hash="d" * 64,
        odds_band="20x",
    )

    result = _generate(
        fixture,
        request_id=request.result_refs[0].object_id,
        judgment_candidate=judgment,
        conditional_candidate=conditional,
        band_outcomes=_band_outcomes(),
    )

    assert result.status is ActionStatus.COMMITTED
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT odds_band, target_odds_min_decimal, "
                "target_odds_max_decimal, combined_decimal_odds, "
                "parent_candidate_revision_id, delta_reason "
                "FROM operator_candidates WHERE deployable = 1"
            )
        ).one()
        outcomes = connection.execute(
            text(
                "SELECT odds_band, status, candidate_count, reason_code "
                "FROM operator_candidate_band_outcomes "
                "WHERE candidate_set_revision_id = ("
                "SELECT candidate_set_revision_id FROM operator_candidate_set_revisions "
                "WHERE set_kind = 'judgment_bound') ORDER BY odds_band"
            )
        ).all()
    assert candidate == (
        "20x",
        "15.000000000000",
        "35.000000000000",
        "20.000000000000",
        "candidate-parent",
        "replace stale away leg",
    )
    assert outcomes == [
        ("100x", "no_feasible_candidate", 0, "empty"),
        ("10x", "no_feasible_candidate", 0, "empty"),
        ("20x", "candidates", 1, None),
        ("50x", "no_feasible_candidate", 0, "empty"),
    ]


def test_generation_requires_one_outcome_for_every_odds_band(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )

    with pytest.raises(ValueError, match="one outcome for every odds band"):
        _generate(
            fixture,
            request_id=request.result_refs[0].object_id,
            judgment_candidate=_candidate(
                set_kind="judgment_bound",
                content_hash="e" * 64,
                odds_band="20x",
            ),
            conditional_candidate=_candidate(
                set_kind="conditional_market_counterfactual",
                content_hash="f" * 64,
                odds_band="20x",
            ),
            band_outcomes=_band_outcomes()[:-1],
        )


def test_generation_rejects_incomplete_odds_band_metadata(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    candidate = replace(
        _candidate(
            set_kind="judgment_bound",
            content_hash="e" * 64,
            odds_band="20x",
        ),
        combined_decimal_odds=None,
    )

    with pytest.raises(ValueError, match="odds band metadata must be complete"):
        _generate(
            fixture,
            request_id=request.result_refs[0].object_id,
            judgment_candidate=candidate,
        )


def test_generation_requires_parent_and_delta_reason_together(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    candidate = _candidate(
        set_kind="judgment_bound",
        content_hash="e" * 64,
        parent_candidate_revision_id="candidate-parent",
    )

    with pytest.raises(ValueError, match="parent and delta reason must be paired"):
        _generate(
            fixture,
            request_id=request.result_refs[0].object_id,
            judgment_candidate=candidate,
        )


def test_generation_allows_explicitly_empty_four_band_sets(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    job = _claim_generation_job(fixture)

    result = fixture.result_actions.generate_ticket_candidate_set(
        GenerateTicketCandidateSetRequest(
            generation_request_id=requested.result_refs[0].object_id,
            candidate_sets=tuple(
                CandidateSetInput(
                    set_kind=set_kind,
                    candidates=(),
                    band_outcomes=_empty_band_outcomes(),
                )
                for set_kind in (
                    "judgment_bound",
                    "conditional_market_counterfactual",
                )
            ),
            generator_version="operator-candidate-v2-bands",
            worker_job_id=job.worker_job_id,
            lease_owner="candidate-worker",
            actor_id="system:operator-candidates",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="candidate:generate:empty-bands",
            requested_at=AT + timedelta(seconds=8),
        )
    )

    assert result.status is ActionStatus.COMMITTED
    with fixture.judgment.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT candidate_count FROM operator_candidate_set_revisions "
                "ORDER BY set_kind"
            )
        ).scalars().all()
    assert counts == [0, 0]


def test_fixed_prize_policy_registration_is_revisioned_closed_and_role_separated(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = RegisterZucaiFixedPrizePolicyRequest(
        ticket_kind="sfc",
        policy_version="zucai-fixed-prize-v1",
        actor_id="system:fixed-prize-policy",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="fixed-policy:sfc:1",
        requested_at=AT + timedelta(seconds=6),
        expected_current_revision_no=0,
    )

    first = fixture.result_actions.register_zucai_fixed_prize_policy(request)
    replay = fixture.result_actions.register_zucai_fixed_prize_policy(request)
    denied = fixture.result_actions.register_zucai_fixed_prize_policy(
        replace(
            request,
            ticket_kind="renjiu",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="fixed-policy:denied",
        )
    )
    second = fixture.result_actions.register_zucai_fixed_prize_policy(
        replace(
            request,
            policy_version="zucai-fixed-prize-v2",
            idempotency_key="fixed-policy:sfc:2",
            expected_current_revision_no=1,
        )
    )

    assert first == replay
    assert first.status is ActionStatus.COMMITTED
    assert denied.status is ActionStatus.REJECTED
    assert second.status is ActionStatus.COMMITTED
    with fixture.judgment.engine.connect() as connection:
        revisions = connection.execute(
            text(
                "SELECT revision_no, supersedes_revision_id, policy_version "
                "FROM zucai_fixed_prize_policy_revisions ORDER BY revision_no"
            )
        ).all()
        tiers = connection.execute(
            text(
                "SELECT revision_no, tier_code, required_correct_count "
                "FROM zucai_fixed_prize_policy_revisions JOIN "
                "zucai_fixed_prize_policy_tiers USING "
                "(fixed_prize_policy_revision_id) ORDER BY revision_no, tier_index"
            )
        ).all()
    assert revisions[0][1] is None
    assert revisions[1][1] == first.result_refs[0].object_id
    assert tiers == [
        (1, "sfc_first", 14),
        (1, "sfc_second", 13),
        (2, "sfc_first", 14),
        (2, "sfc_second", 13),
    ]


def test_fixed_prize_policy_same_content_with_new_key_reuses_current_revision(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = RegisterZucaiFixedPrizePolicyRequest(
        ticket_kind="renjiu",
        policy_version="zucai-fixed-prize-v1",
        actor_id="system:fixed-prize-policy",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="fixed-policy:renjiu:1",
        requested_at=AT + timedelta(seconds=6),
        expected_current_revision_no=0,
    )

    first = fixture.result_actions.register_zucai_fixed_prize_policy(request)
    same_content = fixture.result_actions.register_zucai_fixed_prize_policy(
        replace(
            request,
            idempotency_key="fixed-policy:renjiu:same-content",
            requested_at=AT + timedelta(seconds=7),
            expected_current_revision_no=1,
        )
    )

    assert same_content.status is ActionStatus.COMMITTED
    assert same_content.result_refs == first.result_refs
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM zucai_fixed_prize_policy_revisions "
                "WHERE ticket_kind = 'renjiu'"
            )
        ) == 1


def test_candidate_request_atomically_queues_exactly_one_job_and_replays(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = _generation_request(fixture)

    first = fixture.judgment.decision_actions.request_candidate_generation(request)
    replay = fixture.judgment.decision_actions.request_candidate_generation(request)

    assert first == replay
    assert first.status is ActionStatus.COMMITTED
    assert first.result_refs[0].object_type == "operator_candidate_generation_request"
    with fixture.judgment.engine.connect() as connection:
        request_row = connection.execute(
            text("SELECT * FROM operator_candidate_generation_requests")
        ).mappings().one()
        job = connection.execute(
            text(
                "SELECT job_kind, source_object_type, source_object_id, state "
                "FROM operator_worker_jobs WHERE job_kind = 'candidate_generation'"
            )
        ).one()
    assert request_row["task_snapshot_hash"]
    assert request_row["judgment_prescription_revision_id"] == fixture.prescription_id
    assert request_row["expected_current_revision_no"] == 0
    assert job == (
        "candidate_generation",
        "operator_candidate_generation_request",
        first.result_refs[0].object_id,
        "queued",
    )


def test_candidate_request_rejects_offer_at_exact_sale_deadline(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)

    with pytest.raises(ValueError, match="deadline|closed"):
        fixture.judgment.decision_actions.request_candidate_generation(
            replace(
                _generation_request(fixture),
                idempotency_key="candidate:request:at-deadline",
                requested_at=AT + timedelta(hours=4),
            )
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_generation_requests")
        ) == 0


def test_candidate_request_rejects_quote_drift_after_baseline_freeze(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    with fixture.judgment.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE market_quotes SET decimal_odds = 9.0 "
                "WHERE quote_id = 'quote-3'"
            )
        )

    with pytest.raises(ValueError, match="Quote|odds|binding"):
        fixture.judgment.decision_actions.request_candidate_generation(
            replace(
                _generation_request(fixture),
                idempotency_key="candidate:request:quote-drift",
            )
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_generation_requests")
        ) == 0


@pytest.mark.parametrize(
    "drift_kind",
    ("captured_at", "selection", "snapshot_membership"),
)
def test_candidate_request_rejects_quote_lineage_drift_after_baseline_freeze(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    fixture = _ready_fixture(tmp_path)
    with fixture.judgment.engine.begin() as connection:
        if drift_kind == "captured_at":
            connection.execute(
                text(
                    "UPDATE market_quotes SET captured_at = :captured_at "
                    "WHERE quote_id = 'quote-3'"
                ),
                {"captured_at": (AT - timedelta(minutes=1)).isoformat()},
            )
        elif drift_kind == "selection":
            connection.execute(
                text(
                    "UPDATE market_quotes SET selection_id = 'sel-had-draw' "
                    "WHERE quote_id = 'quote-3'"
                )
            )
        else:
            connection.execute(
                text(
                    "DELETE FROM market_snapshot_quotes "
                    "WHERE market_snapshot_id = 'snapshot-1' "
                    "AND quote_id = 'quote-3'"
                )
            )

    with pytest.raises(ValueError, match="Quote|snapshot|binding"):
        fixture.judgment.decision_actions.request_candidate_generation(
            replace(
                _generation_request(fixture),
                idempotency_key=f"candidate:request:{drift_kind}-drift",
            )
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_generation_requests")
        ) == 0


def test_candidate_request_rejects_wrong_role_without_starting_work(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)

    denied = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(
            fixture,
            key="candidate:request:denied",
            role=ActorRole.AI_ANALYST,
        )
    )

    assert denied.status is ActionStatus.REJECTED
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_generation_requests")
        ) == 0
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM operator_worker_jobs "
                "WHERE job_kind = 'candidate_generation'"
            )
        ) == 0


def test_generation_atomically_persists_both_sets_full_composition_and_job_result(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )

    result = _generate(fixture, request_id=request.result_refs[0].object_id)

    assert result.status is ActionStatus.COMMITTED
    assert {ref.object_type for ref in result.result_refs} == {
        "ticket_candidate_set_revision"
    }
    assert len(result.result_refs) == 2
    with fixture.judgment.engine.connect() as connection:
        sets = connection.execute(
            text(
                "SELECT set_kind, comparison_only, candidate_count "
                "FROM operator_candidate_set_revisions ORDER BY set_kind"
            )
        ).all()
        candidates = connection.execute(
            text(
                "SELECT partition, rank, deployable, leg_audit_completed, "
                "prescription_audit_completed, budget_check_completed, "
                "deployment_report_completed FROM operator_candidates "
                "ORDER BY partition"
            )
        ).all()
        legs = connection.execute(
            text(
                "SELECT selection_code, quote_id, booked_decimal_odds "
                "FROM operator_candidate_ticket_legs ORDER BY candidate_ticket_leg_id"
            )
        ).all()
        job = connection.execute(
            text(
                "SELECT state, result_action_id, result_object_type, result_object_id "
                "FROM operator_worker_jobs WHERE job_kind = 'candidate_generation'"
            )
        ).one()
    assert sets == [
        ("conditional_market_counterfactual", 1, 1),
        ("judgment_bound", 0, 1),
    ]
    assert candidates == [
        ("eligible", 1, 0, 1, 1, 1, 1),
        ("eligible", 1, 1, 1, 1, 1, 1),
    ]
    assert legs == [
        ("3", "quote-3", "2.500000000000"),
        ("3", "quote-3", "2.500000000000"),
    ]
    assert job[0:3] == ("completed", result.action_id, "ticket_candidate_set_revision")
    assert job[3] in {ref.object_id for ref in result.result_refs}


def test_candidate_set_revision_owns_dream_parent_and_delta(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    first_request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=first_request.result_refs[0].object_id)
    second_request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(
            fixture,
            key="candidate:request:2",
            expected_revision=1,
        )
    )

    _generate(
        fixture,
        request_id=second_request.result_refs[0].object_id,
        key="candidate:generate:2",
        change_delta={"replace_leg": "001"},
        rationale="remove shared exposure",
        as_of=AT + timedelta(seconds=9),
    )

    with fixture.judgment.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT candidate_set_revision_id, revision_no, supersedes_revision_id, "
                "change_delta_json, rationale "
                "FROM operator_candidate_set_revisions "
                "WHERE set_kind = 'judgment_bound' ORDER BY revision_no"
            )
        ).mappings().all()
        candidate_lineage = connection.execute(
            text(
                "SELECT parent_candidate_revision_id, delta_reason "
                "FROM operator_candidates ORDER BY candidate_revision_id"
            )
        ).all()

    assert rows[0]["supersedes_revision_id"] is None
    assert rows[0]["change_delta_json"] is None
    assert rows[0]["rationale"] is None
    assert rows[1]["supersedes_revision_id"] == rows[0]["candidate_set_revision_id"]
    assert rows[1]["change_delta_json"] == '{"replace_leg":"001"}'
    assert rows[1]["rationale"] == "remove shared exposure"
    assert all(row == (None, None) for row in candidate_lineage)


def test_generation_rejects_an_active_quote_not_frozen_in_the_baseline(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        uow.market.insert_quote(
            QuoteRow(
                quote_id="quote-active-substitute",
                match_id="match-1",
                market_definition_id="md-had",
                selection_id="sel-had-home",
                provider="sporttery",
                bookmaker=None,
                decimal_odds=2.5,
                captured_at=AT.isoformat(),
                artifact_retrieval_id="retrieval-1",
                quote_status="active",
            )
        )

    with pytest.raises(ValueError, match="baseline|Quote|binding"):
        _generate(
            fixture,
            request_id=request.result_refs[0].object_id,
            judgment_candidate=_candidate(
                set_kind="judgment_bound",
                content_hash="c" * 64,
                quote_id="quote-active-substitute",
            ),
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_set_revisions")
        ) == 0


def test_failure_between_candidate_sets_rolls_back_both_halves(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    with fixture.judgment.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_conditional_candidate_set BEFORE INSERT ON "
            "operator_candidate_set_revisions WHEN NEW.set_kind = "
            "'conditional_market_counterfactual' BEGIN "
            "SELECT RAISE(ABORT, 'forced conditional failure'); END"
        )

    with pytest.raises(IntegrityError, match="forced conditional failure"):
        _generate(fixture, request_id=request.result_refs[0].object_id)

    with fixture.judgment.engine.connect() as connection:
        counts = tuple(
            connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in (
                "operator_candidate_set_revisions",
                "operator_candidates",
                "operator_candidate_tickets",
                "operator_candidate_ticket_legs",
            )
        )
    assert counts == (0, 0, 0, 0)


def test_generation_rejects_legacy_generic_crs_selection_before_first_write(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    job = _claim_generation_job(fixture)
    generic = _candidate(
        set_kind="judgment_bound",
        content_hash="c" * 64,
        selection_code="other",
        quote_id="quote-3",
    )

    with pytest.raises(ValueError, match="non-deployable.*selection"):
        fixture.result_actions.generate_ticket_candidate_set(
            GenerateTicketCandidateSetRequest(
                generation_request_id=request.result_refs[0].object_id,
                candidate_sets=(
                    CandidateSetInput("judgment_bound", (generic,)),
                    CandidateSetInput(
                        "conditional_market_counterfactual",
                        (
                            _candidate(
                                set_kind="conditional_market_counterfactual",
                                content_hash="d" * 64,
                            ),
                        ),
                    ),
                ),
                generator_version="operator-candidate-v1",
                worker_job_id=job.worker_job_id,
                lease_owner="candidate-worker",
                actor_id="system:operator-candidates",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="candidate:generate:generic-crs",
                requested_at=AT + timedelta(seconds=8),
            )
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_set_revisions")
        ) == 0


def test_selection_requires_current_eligible_judgment_candidate_and_cas(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=request.result_refs[0].object_id)
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) WHERE partition = 'eligible' "
                "AND set_kind = 'judgment_bound'"
            )
        ).one()
        conditional = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) WHERE "
                "set_kind = 'conditional_market_counterfactual'"
            )
        ).one()
    selection = SelectTicketCandidateRequest(
        candidate_set_revision_id=candidate.candidate_set_revision_id,
        candidate_revision_id=candidate.candidate_revision_id,
        reason="This is Jun's explicit comparison choice.",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="candidate:select:1",
        requested_at=AT + timedelta(seconds=9),
        expected_current_revision_no=0,
    )

    selected = fixture.judgment.decision_actions.select_ticket_candidate(selection)
    replay = fixture.judgment.decision_actions.select_ticket_candidate(selection)
    changed = fixture.judgment.decision_actions.select_ticket_candidate(
        replace(
            selection,
            reason="Jun changed the explicit rationale after reviewing the comparison.",
            idempotency_key="candidate:select:2",
            requested_at=AT + timedelta(seconds=10),
            expected_current_revision_no=1,
        )
    )
    same_content = fixture.judgment.decision_actions.select_ticket_candidate(
        replace(
            selection,
            reason="Jun changed the explicit rationale after reviewing the comparison.",
            idempotency_key="candidate:select:2:same-content",
            requested_at=AT + timedelta(seconds=11),
            expected_current_revision_no=2,
        )
    )

    assert selected == replay
    assert selected.status is ActionStatus.COMMITTED
    assert changed.status is ActionStatus.COMMITTED
    assert same_content.result_refs == changed.result_refs
    with fixture.judgment.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT candidate_selection_id, candidate_selection_family_id, "
                "revision_no, supersedes_revision_id, candidate_set_revision_id, "
                "candidate_revision_id, content_hash FROM operator_candidate_selections "
                "ORDER BY revision_no"
            )
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["candidate_selection_family_id"] == rows[1][
        "candidate_selection_family_id"
    ]
    assert rows[0]["revision_no"] == 1
    assert rows[0]["supersedes_revision_id"] is None
    assert rows[1]["revision_no"] == 2
    assert rows[1]["supersedes_revision_id"] == rows[0]["candidate_selection_id"]
    assert rows[1]["candidate_set_revision_id"] == candidate.candidate_set_revision_id
    assert rows[1]["candidate_revision_id"] == candidate.candidate_revision_id
    assert len(rows[1]["content_hash"]) == 64
    with pytest.raises(ValueError, match="judgment-bound"):
        fixture.judgment.decision_actions.select_ticket_candidate(
            replace(
                selection,
                candidate_set_revision_id=conditional.candidate_set_revision_id,
                candidate_revision_id=conditional.candidate_revision_id,
                idempotency_key="candidate:select:conditional",
                expected_current_revision_no=2,
            )
        )
    with pytest.raises(OptimisticConcurrencyError):
        fixture.judgment.decision_actions.select_ticket_candidate(
            replace(
                selection,
                idempotency_key="candidate:select:stale",
                expected_current_revision_no=1,
            )
        )
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_selections")
        ) == 2


def test_candidate_selection_rejects_offer_at_exact_sale_deadline(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=requested.result_refs[0].object_id)
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) "
                "WHERE set_kind = 'judgment_bound'"
            )
        ).one()

    with pytest.raises(ValueError, match="deadline|closed"):
        fixture.judgment.decision_actions.select_ticket_candidate(
            SelectTicketCandidateRequest(
                candidate_set_revision_id=candidate.candidate_set_revision_id,
                candidate_revision_id=candidate.candidate_revision_id,
                reason="Deadline equality must not remain selectable.",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="candidate:select:at-deadline",
                requested_at=AT + timedelta(hours=4),
                expected_current_revision_no=0,
            )
        )

    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_selections")
        ) == 0


def test_candidate_selection_rejects_a_superseded_envelope_without_writing(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=requested.result_refs[0].object_id)
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) WHERE set_kind = 'judgment_bound'"
            )
        ).one()

    superseded = fixture.judgment.decision_actions.record_baseline_envelope(
        replace(
            _envelope_request(fixture.judgment, key="envelope:selection-stale"),
            capital_cap_minor=18000,
            expected_current_revision_no=1,
            requested_at=AT + timedelta(seconds=9),
        )
    )
    assert superseded.status is ActionStatus.COMMITTED

    with pytest.raises(
        StaleOperatorDecisionDependencyError,
        match="envelope|lineage|stale",
    ):
        fixture.judgment.decision_actions.select_ticket_candidate(
            SelectTicketCandidateRequest(
                candidate_set_revision_id=candidate.candidate_set_revision_id,
                candidate_revision_id=candidate.candidate_revision_id,
                reason="Old candidate must not cross an envelope revision.",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="candidate:select:stale-envelope",
                requested_at=AT + timedelta(seconds=10),
                expected_current_revision_no=0,
            )
        )
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_selections")
        ) == 0


def test_candidate_selection_rejects_a_superseded_prescription_without_writing(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=requested.result_refs[0].object_id)
    revised_judgment = fixture.judgment.decision_actions.commit_operator_match_judgment(
        replace(
            _judgment_request(
                fixture.judgment,
                fixture.baseline_id,
                fixture.envelope_id,
                key="judgment:selection-stale-prescription",
            ),
            rationale="A revised human judgment creates a new prescription input.",
            expected_current_revision_no=1,
            requested_at=AT + timedelta(seconds=9),
        )
    )
    revised_judgment_id = next(
        ref.object_id
        for ref in revised_judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    revised_prescription = (
        fixture.judgment.decision_actions.freeze_judgment_prescription(
            FreezeJudgmentPrescriptionRequest(
                task_evidence_bundle_revision_id=(
                    fixture.judgment.task_bundle_revision_id
                ),
                market_prior_baseline_revision_id=fixture.baseline_id,
                baseline_envelope_revision_id=fixture.envelope_id,
                work_item_id=WORK_ITEM_ID,
                judgment_revision_ids=(revised_judgment_id,),
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="candidate:prescription:2",
                requested_at=AT + timedelta(seconds=10),
                expected_current_revision_no=1,
            )
        )
    )
    assert revised_prescription.status is ActionStatus.COMMITTED
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) WHERE set_kind = 'judgment_bound'"
            )
        ).one()

    with pytest.raises(
        StaleOperatorDecisionDependencyError,
        match="prescription|lineage|stale",
    ):
        fixture.judgment.decision_actions.select_ticket_candidate(
            SelectTicketCandidateRequest(
                candidate_set_revision_id=candidate.candidate_set_revision_id,
                candidate_revision_id=candidate.candidate_revision_id,
                reason="Old candidate must not cross a prescription revision.",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="candidate:select:stale-prescription",
                requested_at=AT + timedelta(seconds=11),
                expected_current_revision_no=0,
            )
        )
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_selections")
        ) == 0


def test_prescription_deviation_requires_a_named_rule_id(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    job = _claim_generation_job(fixture)
    candidate = replace(
        _candidate(set_kind="judgment_bound", content_hash="e" * 64),
        partition="audit_blocked",
        rank=None,
        deployable=False,
        audit_findings=(
            CandidateAuditFindingInput(
                finding_id="deviation:001",
                audit_kind="prescription_difference",
                code="unnamed_prescription_deviation",
                severity="ERROR",
                message="fixture deviation",
                official_match_no="001",
                rule_id=None,
            ),
        ),
    )

    with pytest.raises(ValueError, match="named Rule ID"):
        fixture.result_actions.generate_ticket_candidate_set(
            GenerateTicketCandidateSetRequest(
                generation_request_id=request.result_refs[0].object_id,
                candidate_sets=(
                    CandidateSetInput("judgment_bound", (candidate,)),
                    CandidateSetInput(
                        "conditional_market_counterfactual",
                        (
                            _candidate(
                                set_kind="conditional_market_counterfactual",
                                content_hash="f" * 64,
                            ),
                        ),
                    ),
                ),
                generator_version="operator-candidate-v1",
                worker_job_id=job.worker_job_id,
                lease_owner="candidate-worker",
                actor_id="system:operator-candidates",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="candidate:generate:unnamed-deviation",
                requested_at=AT + timedelta(seconds=8),
            )
        )
