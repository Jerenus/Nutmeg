from __future__ import annotations

from sqlalchemy import create_engine

from nutmeg.ontology.operator.models import (
    CandidateAuditFindingRow,
    CandidateDeadFaceRow,
    CandidateGenerationRequestRow,
    CandidateMetricRow,
    CandidateSelectionRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    JudgmentPrescriptionItemRow,
    JudgmentPrescriptionRevisionRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.operator_decision import OperatorDecisionRepository
from nutmeg.ontology.repository.operator_result import OperatorResultRepository

AT = "2026-09-04T08:00:00+00:00"


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    schema.metadata.create_all(engine)
    return engine


def _request(request_id: str = "request-1") -> CandidateGenerationRequestRow:
    return CandidateGenerationRequestRow(
        generation_request_id=request_id,
        action_id=f"action-{request_id}",
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash="snapshot-1",
        slate_revision_id="slate-1",
        task_evidence_bundle_revision_id="bundle-1",
        market_prior_baseline_revision_id="baseline-1",
        baseline_envelope_revision_id="envelope-1",
        judgment_prescription_revision_id="prescription-1",
        fixed_prize_policy_revision_id=None,
        dependency_fingerprint=f"fingerprint-{request_id}",
        expected_current_revision_no=0,
        content_hash=f"hash-{request_id}",
        requested_at=AT,
    )


def _candidate_set(
    revision_id: str,
    *,
    revision_no: int,
    request_id: str,
    supersedes: str | None,
) -> TicketCandidateSetRevisionRow:
    return TicketCandidateSetRevisionRow(
        candidate_set_revision_id=revision_id,
        candidate_set_family_id="candidate-family-1",
        revision_no=revision_no,
        supersedes_revision_id=supersedes,
        generation_request_id=request_id,
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash=f"snapshot-{revision_no}",
        slate_revision_id="slate-1",
        market_prior_baseline_revision_id="baseline-1",
        baseline_envelope_revision_id="envelope-1",
        judgment_prescription_revision_id="prescription-1",
        set_kind="judgment_bound",
        comparison_only=0,
        generator_version="operator-candidate-v1",
        audit_policy_version="legs-audit-v1",
        candidate_count=1,
        eligible_count=1,
        audit_blocked_count=0,
        over_cap_count=0,
        content_hash=f"hash-{revision_id}",
        action_id=f"action-{revision_id}",
        created_at=AT,
    )


def test_generation_request_and_selection_round_trip() -> None:
    engine = _engine()
    request = _request()
    selection = CandidateSelectionRow(
        candidate_selection_id="selection-1",
        candidate_selection_family_id="selection-family-1",
        revision_no=1,
        supersedes_revision_id=None,
        candidate_set_revision_id="set-1",
        candidate_revision_id="candidate-1",
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash="snapshot-1",
        slate_revision_id="slate-1",
        reason="Jun selected this comparison row.",
        content_hash="hash-selection-1",
        action_id="action-selection-1",
        selected_at=AT,
    )

    with engine.begin() as connection:
        results = OperatorResultRepository(connection)
        repository = OperatorDecisionRepository(connection)
        results.insert_candidate_set_revision(
            _candidate_set(
                "set-1", revision_no=1, request_id="request-1", supersedes=None
            )
        )
        repository.insert_candidate_generation_request(request)
        repository.insert_candidate_selection(selection)

        assert repository.candidate_generation_request("request-1") == request
        assert repository.candidate_selection_revision("selection-1") == selection
        assert repository.candidate_selection_for_set("set-1") == selection
        assert repository.current_candidate_selection(
            task_family_id="task-family-1",
            work_item_id="work-item-1",
        ) == selection


def test_current_selection_follows_revision_chain_not_wall_clock() -> None:
    engine = _engine()
    first_set = _candidate_set(
        "set-1", revision_no=1, request_id="request-1", supersedes=None
    )
    second_set = _candidate_set(
        "set-2", revision_no=2, request_id="request-2", supersedes="set-1"
    )
    first_candidate = TicketCandidateRow(
        candidate_revision_id="candidate-1",
        candidate_set_revision_id="set-1",
        candidate_index=0,
        candidate_code="C0001",
        partition="eligible",
        rank=1,
        eligible=1,
        deployable=1,
        leg_audit_completed=1,
        prescription_audit_completed=1,
        budget_check_completed=1,
        deployment_report_completed=1,
        content_hash="hash-candidate-1",
    )
    second_candidate = TicketCandidateRow(
        **{
            **{
                name: getattr(first_candidate, name)
                for name in first_candidate.__dataclass_fields__
            },
            "candidate_revision_id": "candidate-2",
            "candidate_set_revision_id": "set-2",
            "content_hash": "hash-candidate-2",
        }
    )
    old_selection = CandidateSelectionRow(
        candidate_selection_id="selection-old",
        candidate_selection_family_id="selection-family-1",
        revision_no=1,
        supersedes_revision_id=None,
        candidate_set_revision_id="set-1",
        candidate_revision_id="candidate-1",
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash="snapshot-1",
        slate_revision_id="slate-1",
        reason="Old set selected with a later wall-clock timestamp.",
        content_hash="hash-selection-old",
        action_id="action-selection-old",
        selected_at="2026-09-04T10:00:00+00:00",
    )
    current_selection = CandidateSelectionRow(
        candidate_selection_id="selection-current",
        candidate_selection_family_id="selection-family-1",
        revision_no=2,
        supersedes_revision_id="selection-old",
        candidate_set_revision_id="set-2",
        candidate_revision_id="candidate-2",
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash="snapshot-2",
        slate_revision_id="slate-1",
        reason="Current set selected despite an earlier wall-clock timestamp.",
        content_hash="hash-selection-current",
        action_id="action-selection-current",
        selected_at="2026-09-04T09:00:00+00:00",
    )

    with engine.begin() as connection:
        results = OperatorResultRepository(connection)
        decisions = OperatorDecisionRepository(connection)
        results.insert_candidate_set_revision(first_set)
        results.insert_candidate_set_revision(second_set)
        results.insert_candidate(first_candidate)
        results.insert_candidate(second_candidate)
        decisions.insert_candidate_selection(old_selection)
        decisions.insert_candidate_selection(current_selection)

        assert decisions.candidate_selection_revision("selection-old") == old_selection
        assert decisions.candidate_selection_for_set("set-2") == current_selection
        assert decisions.current_candidate_selection(
            task_family_id="task-family-1",
            work_item_id="work-item-1",
        ) == current_selection


def test_fixed_policy_round_trip_and_current_leaf() -> None:
    engine = _engine()
    first = ZucaiFixedPrizePolicyRevisionRow(
        fixed_prize_policy_revision_id="policy-1",
        fixed_prize_policy_family_id="policy-family-sfc",
        revision_no=1,
        supersedes_revision_id=None,
        policy_version="zucai-fixed-prize-v1",
        ticket_kind="sfc",
        currency="CNY",
        standard_unit_stake_minor=200,
        official_void_rule="all_faces_match",
        effective_at=AT,
        content_hash="hash-policy-1",
        action_id="action-policy-1",
        created_at=AT,
    )
    second = ZucaiFixedPrizePolicyRevisionRow(
        **{
            **{name: getattr(first, name) for name in first.__dataclass_fields__},
            "fixed_prize_policy_revision_id": "policy-2",
            "revision_no": 2,
            "supersedes_revision_id": "policy-1",
            "policy_version": "zucai-fixed-prize-v2",
            "content_hash": "hash-policy-2",
            "action_id": "action-policy-2",
        }
    )
    tiers = (
        ZucaiFixedPrizePolicyTierRow(
            fixed_prize_policy_tier_id="tier-1",
            fixed_prize_policy_revision_id="policy-2",
            tier_index=0,
            tier_code="sfc_first",
            required_correct_count=14,
        ),
        ZucaiFixedPrizePolicyTierRow(
            fixed_prize_policy_tier_id="tier-2",
            fixed_prize_policy_revision_id="policy-2",
            tier_index=1,
            tier_code="sfc_second",
            required_correct_count=13,
        ),
    )

    with engine.begin() as connection:
        repository = OperatorResultRepository(connection)
        repository.insert_fixed_prize_policy_revision(first)
        repository.insert_fixed_prize_policy_revision(second)
        for tier in tiers:
            repository.insert_fixed_prize_policy_tier(tier)

        assert repository.current_fixed_prize_policy("sfc") == second
        assert repository.fixed_prize_policy_revision("policy-1") == first
        assert repository.fixed_prize_policy_tiers("policy-2") == tiers


def test_candidate_graph_round_trip_and_current_leaf() -> None:
    engine = _engine()
    first_set = _candidate_set(
        "set-1", revision_no=1, request_id="request-1", supersedes=None
    )
    second_set = _candidate_set(
        "set-2", revision_no=2, request_id="request-2", supersedes="set-1"
    )
    candidate = TicketCandidateRow(
        candidate_revision_id="candidate-1",
        candidate_set_revision_id="set-2",
        candidate_index=0,
        candidate_code="U1",
        partition="eligible",
        rank=1,
        eligible=1,
        deployable=1,
        leg_audit_completed=1,
        prescription_audit_completed=1,
        budget_check_completed=1,
        deployment_report_completed=1,
        content_hash="hash-candidate-1",
    )
    ticket = CandidateTicketRow(
        candidate_ticket_id="ticket-1",
        candidate_revision_id="candidate-1",
        ticket_index=0,
        ticket_kind="jczq_pass",
        structure_code="1x1",
        group_code="001",
        currency="CNY",
        unit_stake_minor=200,
        unit_count=1,
        stake_minor=200,
        composition_hash="hash-ticket-1",
        fixed_prize_policy_revision_id=None,
    )
    leg = CandidateTicketLegRow(
        candidate_ticket_leg_id="leg-1",
        candidate_ticket_id="ticket-1",
        leg_index=0,
        official_offer_revision_id="offer-1",
        match_id="match-1",
        market_definition_id="md-had",
        selection_code="3",
        quote_id="quote-1",
        booked_decimal_odds="2.500000000000",
        settlement_parameter_decimal=None,
    )
    metric = CandidateMetricRow(
        candidate_metric_id="metric-1",
        candidate_revision_id="candidate-1",
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
    )
    dead_face = CandidateDeadFaceRow(
        candidate_dead_face_id="dead-face-1",
        candidate_revision_id="candidate-1",
        dead_face_index=0,
        official_match_no="001",
        face_code="0",
    )
    finding = CandidateAuditFindingRow(
        candidate_audit_finding_id="finding-1",
        candidate_revision_id="candidate-1",
        finding_index=0,
        audit_kind="legs",
        finding_code="C8",
        severity="WARN",
        message="fixture warning",
        official_match_no="001",
        rule_id="q",
    )

    with engine.begin() as connection:
        repository = OperatorResultRepository(connection)
        repository.insert_candidate_set_revision(first_set)
        repository.insert_candidate_set_revision(second_set)
        repository.insert_candidate(candidate)
        repository.insert_candidate_ticket(ticket)
        repository.insert_candidate_ticket_leg(leg)
        repository.insert_candidate_metric(metric)
        repository.insert_candidate_dead_face(dead_face)
        repository.insert_candidate_audit_finding(finding)

        assert repository.current_candidate_set(
            task_family_id="task-family-1",
            work_item_id="work-item-1",
            set_kind="judgment_bound",
        ) == second_set
        assert repository.candidate_set_revision("set-1") == first_set
        assert repository.candidates_for_set("set-2") == (candidate,)
        assert repository.candidate("candidate-1") == candidate
        assert repository.candidate_tickets("candidate-1") == (ticket,)
        assert repository.candidate_ticket_legs("ticket-1") == (leg,)
        assert repository.candidate_metric("candidate-1") == metric
        assert repository.candidate_dead_faces("candidate-1") == (dead_face,)
        assert repository.candidate_audit_findings("candidate-1") == (finding,)


def test_judgment_prescription_exact_revision_and_items_round_trip() -> None:
    engine = _engine()
    revision = JudgmentPrescriptionRevisionRow(
        judgment_prescription_revision_id="prescription-1",
        judgment_prescription_family_id="prescription-family-1",
        revision_no=1,
        supersedes_revision_id=None,
        task_family_id="task-family-1",
        work_item_id="work-item-1",
        task_snapshot_hash="snapshot-1",
        slate_revision_id="slate-1",
        task_evidence_bundle_revision_id="bundle-1",
        market_prior_baseline_revision_id="baseline-1",
        baseline_envelope_revision_id="envelope-1",
        required_match_count=1,
        judgment_count=1,
        content_hash="hash-prescription-1",
        action_id="action-prescription-1",
        created_at=AT,
    )
    item = JudgmentPrescriptionItemRow(
        operator_judgment_prescription_item_id="prescription-item-1",
        judgment_prescription_revision_id="prescription-1",
        item_index=0,
        match_id="match-1",
        operator_match_judgment_revision_id="judgment-1",
    )

    with engine.begin() as connection:
        repository = OperatorDecisionRepository(connection)
        repository.insert_judgment_prescription_revision(revision)
        repository.insert_judgment_prescription_item(item)

        assert repository.judgment_prescription_revision("prescription-1") == revision
        assert repository.judgment_prescription_items("prescription-1") == (item,)
