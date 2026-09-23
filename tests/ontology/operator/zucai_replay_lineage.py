"""The checked-in 26111 zucai decision lineage, replayed for settlement tests.

Inlined from the retired ``tests/product/operator_v2/test_candidate_replay``
helper on 2026-09-23 when ``nutmeg.product.operator_workers`` was deleted; the
evidence freeze and candidate generation now drive their typed Actions
directly instead of going through a background worker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from sqlalchemy import text

from nutmeg.discovery.audit import _audit_candidate, _CandidateAuditOffer
from nutmeg.discovery.candidates import (
    CandidateGenerationInput,
    CandidateStructureTemplate,
    FaceBundleOption,
    OfferCandidateInput,
    enumerate_candidates,
)
from nutmeg.ontology.actions.bundle_actions import BundleActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FaceProbabilityInput,
    FreezeJudgmentPrescriptionRequest,
    FreezeMarketPriorBaselineRequest,
    OperatorDecisionActions,
    RecordBaselineEnvelopeRequest,
)
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    EvidenceFreezeGate,
    EvidenceFreezeMatchPlan,
    RequestEvidenceFreezeRequest,
)
from nutmeg.ontology.operator.result_actions import (
    CandidateAuditFindingInput,
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
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.market import QuoteRow, SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.action_drivers import (
    claim_worker_jobs,
    drive_evidence_freeze,
)

AT = datetime(2026, 9, 4, 8, tzinfo=UTC)
NOW = AT + timedelta(hours=1)
TASK_KEY = "zucai:26111"
WORK_ITEM_ID = "zucai:26111:issue:current"
TOKEN_KEY = b"package-seven-26111-replay-signing-key"
REQUIREMENTS = ("E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC")
SUPPORT_PRIOR = {
    "3": "0.340000000000",
    "1": "0.330000000000",
    "0": "0.330000000000",
}


def _fixture_document() -> dict[str, object]:
    path = (
        Path(__file__).parents[2]
        / "product"
        / "fixtures"
        / "operator"
        / "26111-u864-candidates.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_sale_and_market(engine, probabilities: dict[str, dict[str, str]]) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO source_runs "
            "(source_run_id, source_name, source_type, started_at, finished_at, status) "
            "VALUES ('run-26111', 'sporttery', 'official_sale_schedule', ?, ?, "
            "'succeeded')",
            (AT.isoformat(), AT.isoformat()),
        )
        connection.exec_driver_sql(
            "INSERT INTO source_artifacts "
            "(artifact_id, first_recorded_at, content_type, storage_path, byte_size, "
            "content_hash) VALUES ('artifact-26111', ?, 'application/json', "
            "'operator/26111', 2, ?)",
            (AT.isoformat(), "a" * 64),
        )
        connection.exec_driver_sql(
            "INSERT INTO artifact_retrievals "
            "(artifact_retrieval_id, artifact_id, source_run_id, source_name, source_type, "
            "reported_content_type, retrieved_at, status) VALUES "
            "('retrieval-26111', 'artifact-26111', 'run-26111', 'sporttery', "
            "'official_sale_schedule', 'application/json', ?, 'stored')",
            (AT.isoformat(),),
        )
        connection.exec_driver_sql(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-26111', 'zucai:26111', 'zucai', '26111', 1, "
            "'retrieval-26111', ?, ?, ?, NULL, ?)",
            (AT.isoformat(), AT.isoformat(), AT.isoformat(), "b" * 64),
        )

    with OntologyUnitOfWork(engine) as uow:
        for number in range(1, 15):
            match_id = f"match-{number}"
            offer_id = f"offer-{number}"
            family_id = f"offer-family-{number}"
            observation_id = f"obs-{number}"
            snapshot_id = f"snapshot-{number}"
            prior = probabilities.get(str(number), SUPPORT_PRIOR)
            uow.identity.insert_match_minimal(match_id)
            uow.evidence.insert_observation(
                ObservationRow(
                    observation_id=observation_id,
                    observation_type="structural_context",
                    subject_type="match",
                    subject_id=match_id,
                    scope_match_id=match_id,
                    value={"state": "present"},
                    schema_version="1",
                    valid_from=AT.isoformat(),
                    valid_to=None,
                    observed_at=AT.isoformat(),
                    recorded_at=AT.isoformat(),
                    verification_method="official",
                    quality={},
                )
            )
            quote_ids = []
            for face, outcome, odds in (
                ("3", "home", 2.5),
                ("1", "draw", 3.2),
                ("0", "away", 3.4),
            ):
                quote_id = f"quote-{number}-{face}"
                quote_ids.append(quote_id)
                uow.market.insert_quote(
                    QuoteRow(
                        quote_id=quote_id,
                        match_id=match_id,
                        market_definition_id="md-had",
                        selection_id=f"sel-had-{outcome}",
                        provider="sporttery",
                        bookmaker=None,
                        decimal_odds=odds,
                        captured_at=AT.isoformat(),
                        artifact_retrieval_id="retrieval-26111",
                        quote_status="active",
                    )
                )
            uow.market.insert_snapshot(
                SnapshotRow(
                    market_snapshot_id=snapshot_id,
                    match_id=match_id,
                    market_definition_id="md-had",
                    snapshot_kind="read_time",
                    as_of=AT.isoformat(),
                    fair_distribution={
                        "home": float(prior["3"]),
                        "draw": float(prior["1"]),
                        "away": float(prior["0"]),
                    },
                    devig_method="proportional",
                    method_version="1",
                    source_coverage={"providers": 1, "quotes": 3},
                    freshness={},
                    disagreement={},
                ),
                quote_ids=tuple(quote_ids),
            )
            uow.connection.execute(
                text(
                    "INSERT INTO official_offer_families "
                    "(official_offer_family_id, lane, business_key, official_match_no, "
                    "match_id, created_at) VALUES (:family_id, 'zucai', '26111', "
                    ":number, :match_id, :created_at)"
                ),
                {
                    "family_id": family_id,
                    "number": str(number),
                    "match_id": match_id,
                    "created_at": AT.isoformat(),
                },
            )
            uow.connection.execute(
                text(
                    "INSERT INTO official_offer_revisions "
                    "(official_offer_revision_id, official_offer_family_id, "
                    "slate_revision_id, match_id, official_match_no, "
                    "market_definition_ids_json, sale_opens_at, sale_deadline_at, status) "
                    "VALUES (:offer_id, :family_id, 'slate-26111', :match_id, :number, "
                    "'[\"md-had\"]', :opens_at, :deadline_at, 'on_sale')"
                ),
                {
                    "offer_id": offer_id,
                    "family_id": family_id,
                    "match_id": match_id,
                    "number": str(number),
                    "opens_at": AT.isoformat(),
                    "deadline_at": (AT + timedelta(hours=4)).isoformat(),
                },
            )


def _freeze_task(engine, probabilities: dict[str, dict[str, str]]):
    plans = tuple(
        EvidenceFreezeMatchPlan(
            match_id=f"match-{number}",
            market_snapshot_id=f"snapshot-{number}",
            prior_distribution={
                outcome: float(probabilities.get(str(number), SUPPORT_PRIOR)[face])
                for face, outcome in (("3", "home"), ("1", "draw"), ("0", "away"))
            },
            candidate_observation_ids=(f"obs-{number}",),
            caveat_claim_ids=(),
            requirement_states=tuple((item, "complete") for item in REQUIREMENTS),
            requirement_ref_tokens=(f"obs-{number}",),
            market_prior_ref_tokens=(
                f"snapshot-{number}",
                f"quote-{number}-3",
                f"quote-{number}-1",
                f"quote-{number}-0",
            ),
            conflicts_cleared_ref_tokens=(),
        )
        for number in range(1, 15)
    )
    gate = EvidenceFreezeGate(
        task_family_id=TASK_KEY,
        lane="zucai",
        business_key="26111",
        slate_revision_id="slate-26111",
        task_snapshot_hash="c" * 64,
        requirement_revision_token="requirements-26111",
        information_cutoff_at=AT,
        policy_version="governance-v1",
        ready=True,
        required_match_count=14,
        matches=plans,
    )
    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    evidence_actions = EvidenceActions(
        action_service,
        freeze_gate_resolver=lambda _uow, _lane, _key, _as_of: gate,
    )
    requested = evidence_actions.request_evidence_freeze(
        RequestEvidenceFreezeRequest(
            task_family_id=TASK_KEY,
            lane="zucai",
            business_key="26111",
            requirement_revision_token=gate.requirement_revision_token,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="26111:freeze-request",
            requested_at=AT,
        )
    )
    linked = drive_evidence_freeze(
        action_service=action_service,
        evidence_actions=evidence_actions,
        bundle_actions=BundleActions(action_service),
        lease_owner="26111-evidence-worker",
        as_of=AT + timedelta(seconds=1),
    )
    assert requested.status is ActionStatus.COMMITTED
    assert len(linked) == 1
    return action_service, linked[0].result_refs[0].object_id


def _prepare_decision_lineage(tmp_path: Path):
    document = _fixture_document()
    probabilities = document["probabilities"]
    assert isinstance(probabilities, dict)
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_sale_and_market(engine, probabilities)
    action_service, bundle_id = _freeze_task(engine, probabilities)
    decision_actions = OperatorDecisionActions(action_service)
    result_actions = OperatorResultActions(action_service)

    baseline = decision_actions.freeze_market_prior_baseline(
        FreezeMarketPriorBaselineRequest(
            task_evidence_bundle_revision_id=bundle_id,
            work_item_id=WORK_ITEM_ID,
            actor_id="system:market-baseline",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="26111:baseline",
            requested_at=AT + timedelta(seconds=2),
        )
    )
    versions = document["versions"]
    assert isinstance(versions, list)
    version_faces = {
        str(number): tuple(
            dict.fromkeys(
                version["faces"][str(number)]
                for version in versions
                if str(number) in version["faces"]
            )
        )
        for number in range(1, 15)
    }
    selected_numbers = tuple(probabilities)
    constraints = tuple(
        BaselineEnvelopeOfferConstraint(
            official_match_no=str(number),
            market_code="had",
            allowed_face_bundles=tuple(
                FaceBundleInput(
                    bundle_code=f"faces-{faces}",
                    face_codes=tuple(faces),
                )
                for faces in (version_faces[str(number)] or ("3",))
            ),
            omission_allowed=str(number) not in selected_numbers,
        )
        for number in range(1, 15)
    )
    envelope = decision_actions.record_baseline_envelope(
        RecordBaselineEnvelopeRequest(
            task_evidence_bundle_revision_id=bundle_id,
            work_item_id=WORK_ITEM_ID,
            ticket_kind="renjiu",
            capital_cap_minor=int(document["capital_cap_minor"]),
            currency="CNY",
            maximum_ticket_count=1,
            offer_constraints=constraints,
            structure_templates=(
                BaselineEnvelopeStructureTemplate(
                    kind="zucai_group",
                    structure_code="renjiu-u864-family",
                    eligible_official_match_nos=selected_numbers,
                    pass_size=None,
                    required_offer_count=9,
                    maximum_groups=1,
                ),
            ),
            maximum_exhaustive_candidate_count=8,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="26111:envelope",
            requested_at=AT + timedelta(seconds=3),
            expected_current_revision_no=0,
        )
    )
    policy = result_actions.register_zucai_fixed_prize_policy(
        RegisterZucaiFixedPrizePolicyRequest(
            ticket_kind="renjiu",
            policy_version="zucai-fixed-prize-v1",
            actor_id="system:fixed-prize-policy",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="26111:fixed-prize",
            requested_at=AT + timedelta(seconds=3),
            expected_current_revision_no=0,
        )
    )
    baseline_id = baseline.result_refs[0].object_id
    envelope_id = envelope.result_refs[0].object_id
    judgment_ids = []
    for number in range(1, 15):
        prior = probabilities.get(str(number), SUPPORT_PRIOR)
        face_inputs = tuple(
            FaceProbabilityInput(face_code=face, probability_decimal=value)
            for face, value in prior.items()
        )
        bundles = tuple(
            FaceBundleInput(
                bundle_code=f"faces-{faces}",
                face_codes=tuple(faces),
            )
            for faces in (version_faces[str(number)] or ("3",))
        )
        judgment = decision_actions.commit_operator_match_judgment(
            CommitOperatorMatchJudgmentRequest(
                task_evidence_bundle_revision_id=bundle_id,
                market_prior_baseline_revision_id=baseline_id,
                baseline_envelope_revision_id=envelope_id,
                work_item_id=WORK_ITEM_ID,
                match_id=f"match-{number}",
                official_offer_revision_id=f"offer-{number}",
                market_definition_id="md-had",
                prior=face_inputs,
                belief=face_inputs,
                factors=(),
                expression_bundles=bundles,
                rule_ids=("k",),
                evidence_ref_tokens=(f"obs-{number}",),
                falsifier="The registered structural premise no longer holds.",
                rationale="26111 checked-in replay judgment.",
                commitment_tier="commit",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"26111:judgment:{number}",
                requested_at=AT + timedelta(seconds=4),
                expected_current_revision_no=0,
            )
        )
        judgment_ids.append(
            next(
                ref.object_id
                for ref in judgment.result_refs
                if ref.object_type == "operator_match_judgment_revision"
            )
        )
    prescription = decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=bundle_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=WORK_ITEM_ID,
            judgment_revision_ids=tuple(judgment_ids),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="26111:prescription",
            requested_at=AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    assert policy.status is ActionStatus.COMMITTED
    assert prescription.status is ActionStatus.COMMITTED
    return engine, action_service, decision_actions, result_actions, document


def _canonical_probability(value: object) -> str:
    return format(
        Decimal(str(value)).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN),
        ".12f",
    )


def _offer_probabilities(document, number: str) -> tuple[tuple[str, str], ...]:
    probabilities = document["probabilities"]
    prior = probabilities.get(number, SUPPORT_PRIOR)
    return tuple(
        (face, _canonical_probability(value)) for face, value in prior.items()
    )


def _renjiu_offer_shape(document):
    """Faces and omission flags exactly as `_prepare_decision_lineage` froze them."""
    versions = document["versions"]
    selected = tuple(document["probabilities"])
    shape = {}
    for number in range(1, 15):
        key = str(number)
        faces = tuple(
            dict.fromkeys(
                version["faces"][key] for version in versions if key in version["faces"]
            )
        ) or ("3",)
        shape[key] = (faces, key not in selected)
    return shape, selected


def _sfc_offer_shape(document):
    """The single modal face per match `_replace_with_sfc_decision_lineage` froze."""
    probabilities = document["probabilities"]
    shape = {}
    for number in range(1, 15):
        key = str(number)
        prior = probabilities.get(key, SUPPORT_PRIOR)
        modal = max(prior, key=lambda face: Decimal(prior[face]))
        shape[key] = ((modal,), False)
    return shape, tuple(str(number) for number in range(1, 15))


def _candidate_generation_input(
    document,
    *,
    ticket_kind: str,
    unit_stake_minor: int,
    fixed_prize_policy_revision_id: str,
):
    if ticket_kind == "renjiu":
        shape, selected = _renjiu_offer_shape(document)
        template = CandidateStructureTemplate(
            kind="zucai_group",
            structure_code="renjiu-u864-family",
            eligible_official_match_nos=selected,
            pass_size=None,
            required_offer_count=9,
            maximum_groups=1,
        )
        capital_cap_minor = int(document["capital_cap_minor"])
        maximum_exhaustive_candidate_count = 8
    elif ticket_kind == "sfc":
        shape, numbers = _sfc_offer_shape(document)
        template = CandidateStructureTemplate(
            kind="zucai_group",
            structure_code="sfc-14",
            eligible_official_match_nos=numbers,
            pass_size=None,
            required_offer_count=14,
            maximum_groups=1,
        )
        capital_cap_minor = 200
        maximum_exhaustive_candidate_count = 1
    else:
        raise ValueError(f"unsupported zucai replay ticket kind: {ticket_kind}")

    offers = []
    audit_offers = []
    for number in range(1, 15):
        key = str(number)
        faces, omission_allowed = shape[key]
        bundles = tuple(
            FaceBundleOption(bundle_code=f"faces-{item}", face_codes=tuple(item))
            for item in faces
        )
        probabilities = _offer_probabilities(document, key)
        offers.append(
            OfferCandidateInput(
                official_match_no=key,
                official_offer_revision_id=f"offer-{number}",
                match_id=f"match-{number}",
                market_definition_id="md-had",
                probabilities=probabilities,
                allowed_face_bundles=bundles,
                omission_allowed=omission_allowed,
                quote_ids_by_face=(),
                booked_decimal_odds_by_face=(),
                settlement_parameter_decimal=None,
            )
        )
        audit_offers.append(
            _CandidateAuditOffer(
                official_match_no=key,
                market_definition_id="md-had",
                belief=probabilities,
                prior=probabilities,
                prescribed_face_bundles=tuple(
                    frozenset(bundle.face_codes) for bundle in bundles
                ),
                rule_ids=("k",),
                anchor_integrity="unknown",
                face_precedents=(),
            )
        )
    return (
        CandidateGenerationInput(
            lane="zucai",
            ticket_kind=ticket_kind,
            currency="CNY",
            capital_cap_minor=capital_cap_minor,
            unit_stake_minor=unit_stake_minor,
            maximum_ticket_count=1,
            maximum_exhaustive_candidate_count=maximum_exhaustive_candidate_count,
            offers=tuple(offers),
            templates=(template,),
            fixed_prize_policy_revision_id=fixed_prize_policy_revision_id,
        ),
        tuple(audit_offers),
    )


def _candidate_ticket_input(ticket) -> CandidateTicketInput:
    legs = []
    for leg in ticket.legs:
        for index, selection_code in enumerate(leg.selection_codes):
            legs.append(
                CandidateTicketLegInput(
                    official_offer_revision_id=leg.official_offer_revision_id,
                    match_id=leg.match_id,
                    market_definition_id=leg.market_definition_id,
                    selection_code=selection_code,
                    quote_id=(leg.quote_ids[index] if leg.quote_ids else None),
                    booked_decimal_odds=(
                        leg.booked_decimal_odds[index]
                        if leg.booked_decimal_odds
                        else None
                    ),
                    settlement_parameter_decimal=leg.settlement_parameter_decimal,
                )
            )
    return CandidateTicketInput(
        ticket_kind=ticket.ticket_kind,
        structure_code=ticket.structure_code,
        group_code=ticket.group_code,
        currency=ticket.currency,
        unit_stake_minor=ticket.unit_stake_minor,
        unit_count=ticket.unit_count,
        stake_minor=ticket.stake_minor,
        composition_hash=ticket.composition_hash,
        fixed_prize_policy_revision_id=ticket.fixed_prize_policy_revision_id,
        legs=tuple(legs),
    )


def _ticket_candidate_input(candidate) -> TicketCandidateInput:
    return TicketCandidateInput(
        partition=candidate.partition,
        rank=candidate.rank,
        deployable=candidate.deployable,
        tickets=tuple(_candidate_ticket_input(ticket) for ticket in candidate.tickets),
        metrics=CandidateMetricsInput(
            currency=candidate.tickets[0].currency,
            ticket_count=candidate.ticket_count,
            distinct_note_count=candidate.distinct_note_count,
            paid_note_unit_count=candidate.paid_note_unit_count,
            stake_minor=candidate.stake_minor,
            capital_utilization_decimal=candidate.cap_utilization_decimal,
            probability_kind=candidate.probability_kind,
            objective_probability_decimal=candidate.objective_probability_decimal,
            expected_broken_legs_decimal=candidate.expected_broken_legs_decimal,
            break_even_bonus_minor=candidate.break_even_bonus_minor,
            break_even_to_official_median_decimal=(
                candidate.break_even_to_median_decimal
            ),
        ),
        common_dead_faces=tuple(
            CandidateDeadFaceInput(official_match_no=match_no, face_code=face)
            for match_no, faces in candidate.common_dead_faces
            for face in faces
        ),
        audit_findings=tuple(
            CandidateAuditFindingInput(
                finding_id=finding.finding_id,
                audit_kind=finding.audit_kind,
                code=finding.code,
                severity=finding.severity,
                message=finding.message,
                official_match_no=finding.official_match_no,
                rule_id=finding.rule_id,
            )
            for finding in candidate.audit_findings
        ),
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        content_hash=candidate.content_hash,
        odds_band=candidate.odds_band,
        target_odds_min_decimal=candidate.target_odds_min_decimal,
        target_odds_max_decimal=candidate.target_odds_max_decimal,
        combined_decimal_odds=candidate.combined_decimal_odds,
        parent_candidate_revision_id=candidate.parent_candidate_revision_id,
        delta_reason=candidate.delta_reason,
    )


def generate_zucai_candidate_sets(
    *,
    action_service,
    result_actions,
    document,
    generation_request_id: str,
    fixed_prize_policy_revision_id: str,
    ticket_kind: str,
    lease_owner: str,
    as_of: datetime,
):
    """Enumerate both comparison sets and commit them through the typed Action.

    Replaces `CandidateGenerationWorker`: the enumeration and audit are the live
    `nutmeg.discovery` code, and `generate_ticket_candidate_set` is the live
    Action; only the worker's lease bookkeeping is gone.
    """
    job = claim_worker_jobs(
        action_service,
        job_kind="candidate_generation",
        lease_owner=lease_owner,
        as_of=as_of,
    )[0]
    with action_service.unit_of_work() as uow:
        policy = uow.operator_result.fixed_prize_policy_revision(
            fixed_prize_policy_revision_id
        )
    assert policy is not None
    inputs, audit_offers = _candidate_generation_input(
        document,
        ticket_kind=ticket_kind,
        unit_stake_minor=policy.standard_unit_stake_minor,
        fixed_prize_policy_revision_id=fixed_prize_policy_revision_id,
    )
    candidate_sets = tuple(
        CandidateSetInput(
            set_kind=set_kind,
            candidates=tuple(
                _ticket_candidate_input(candidate)
                for candidate in enumerate_candidates(
                    inputs,
                    set_kind=set_kind,
                    generator_version="operator-candidate-v1",
                    audit_candidate=lambda draft: _audit_candidate(
                        draft,
                        lane=inputs.lane,
                        offers=audit_offers,
                        capital_cap_minor=inputs.capital_cap_minor,
                    ),
                ).candidates
            ),
            band_outcomes=(),
            change_delta=None,
            rationale=None,
        )
        for set_kind in ("judgment_bound", "conditional_market_counterfactual")
    )
    outcome = result_actions.generate_ticket_candidate_set(
        GenerateTicketCandidateSetRequest(
            generation_request_id=generation_request_id,
            candidate_sets=candidate_sets,
            generator_version="operator-candidate-v1",
            worker_job_id=job.worker_job_id,
            lease_owner=lease_owner,
            actor_id="system:operator-candidates",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"26111:{ticket_kind}:candidate-generation",
            requested_at=as_of,
        )
    )
    assert outcome.status is ActionStatus.COMMITTED
    return outcome
