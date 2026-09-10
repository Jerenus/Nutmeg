from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

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
    OperatorResultActions,
    RegisterZucaiFixedPrizePolicyRequest,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.market import QuoteRow, SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import ConstructTicketStep
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import (
    CandidateGenerationWorker,
    EvidenceFreezeRequestWorker,
)
from nutmeg.product.repository import ProductReadRepository

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
        Path(__file__).parents[1]
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
    worker = EvidenceFreezeRequestWorker(
        action_service=action_service,
        evidence_actions=evidence_actions,
        bundle_actions=BundleActions(action_service),
        worker_id="26111-evidence-worker",
        lease_duration=timedelta(minutes=5),
    )
    linked = worker.run_once(limit=1, as_of=AT + timedelta(seconds=1))
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


def _candidate_faces(candidate) -> dict[str, str]:
    labels = (
        candidate.composition.singles
        + candidate.composition.doubles
        + candidate.composition.full_covers
    )
    return {
        label.split(" · ", 1)[0].removeprefix("场 "): label.split(" · ", 1)[1]
        for label in labels
    }


def test_26111_public_request_worker_persistence_and_query_replay(tmp_path: Path) -> None:
    engine, action_service, decision_actions, result_actions, document = (
        _prepare_decision_lineage(tmp_path)
    )
    queries = OperatorQueryService(
        repository=ProductReadRepository(engine),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
    )
    product_actions = OperatorActionService(
        queries=queries,
        action_gateway=SimpleNamespace(),
        decision_actions=decision_actions,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    before = queries.task(TASK_KEY, as_of=NOW)
    assert isinstance(before.step, ConstructTicketStep)
    assert before.step.mode == "candidate_request"

    receipt = product_actions.request_candidate_generation(
        SimpleNamespace(
            task_key=TASK_KEY,
            expected_snapshot_token=before.step.request_generation_token,
            market_prior_baseline_token=before.step.market_prior_baseline_token,
            baseline_envelope_token=before.step.baseline_envelope_token,
            judgment_prescription_token=before.step.judgment_prescription_token,
            idempotency_key="26111:public-candidate-request",
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert receipt.status == "queued"

    completed = CandidateGenerationWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id="26111-candidate-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=NOW + timedelta(seconds=1))
    assert len(completed) == 1

    after = queries.task(TASK_KEY, as_of=NOW + timedelta(seconds=2))
    assert isinstance(after.step, ConstructTicketStep)
    assert after.step.mode == "candidate_comparison"
    judgment_set = next(
        candidate_set
        for candidate_set in after.step.candidate_sets
        if not candidate_set.comparison_only
    )
    by_faces = {
        frozenset(_candidate_faces(candidate).items()): candidate
        for candidate in judgment_set.candidates
    }
    for version in document["versions"]:
        candidate = by_faces[frozenset(version["faces"].items())]
        assert candidate.stake_minor == version["stake_minor"]
        assert (
            candidate.objective_probability_decimal
            == version["objective_probability_decimal"]
        )
    assert after.step.selection_completed is False
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT set_kind, candidate_count FROM "
                "operator_candidate_set_revisions ORDER BY set_kind"
            )
        ).all() == [
            ("conditional_market_counterfactual", 8),
            ("judgment_bound", 8),
        ]
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM actions WHERE action_type = "
                "'request_candidate_generation' AND status = 'committed'"
            )
        ) == 1
        assert connection.execute(
            text(
                "SELECT state, result_object_type FROM operator_worker_jobs "
                "WHERE job_kind = 'candidate_generation'"
            )
        ).one() == ("completed", "ticket_candidate_set_revision")
