from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.actions.bundle_actions import BundleActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FaceOffsetInput,
    FaceProbabilityInput,
    FactorAdjustmentInput,
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
from nutmeg.ontology.repository import schema, schema_decision
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.market import QuoteRow, SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_workers import EvidenceFreezeRequestWorker, MarketBaselineWorker

AT = datetime(2026, 9, 4, 8, tzinfo=UTC)
WORK_ITEM_ID = "jczq:2026-09-04:wave:current"
PRIOR = (
    FaceProbabilityInput(face_code="3", probability_decimal="0.400000000000"),
    FaceProbabilityInput(face_code="1", probability_decimal="0.300000000000"),
    FaceProbabilityInput(face_code="0", probability_decimal="0.300000000000"),
)


@dataclass
class JudgmentFixture:
    engine: object
    action_service: ActionService
    evidence_actions: EvidenceActions
    decision_actions: OperatorDecisionActions
    task_bundle_revision_id: str
    gate_box: list[EvidenceFreezeGate]


def _seed_sale_market_and_evidence(
    engine,
    *,
    market_state: str,
) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO source_runs "
            "(source_run_id, source_name, source_type, started_at, finished_at, status) "
            "VALUES ('run-1', 'sporttery', 'official_sale_schedule', ?, ?, 'succeeded')",
            (AT.isoformat(), AT.isoformat()),
        )
        connection.exec_driver_sql(
            "INSERT INTO source_artifacts "
            "(artifact_id, first_recorded_at, content_type, storage_path, byte_size, "
            "content_hash) VALUES ('artifact-1', ?, 'application/json', 'judgment/fixture', "
            "2, ?)",
            (AT.isoformat(), "a" * 64),
        )
        connection.exec_driver_sql(
            "INSERT INTO artifact_retrievals "
            "(artifact_retrieval_id, artifact_id, source_run_id, source_name, source_type, "
            "reported_content_type, retrieved_at, status) VALUES "
            "('retrieval-1', 'artifact-1', 'run-1', 'sporttery', "
            "'official_sale_schedule', 'application/json', ?, 'stored')",
            (AT.isoformat(),),
        )
        connection.exec_driver_sql("INSERT INTO matches (match_id) VALUES ('match-1')")
        connection.exec_driver_sql(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-1', 'jczq:2026-09-04', 'jczq', '2026-09-04', 1, 'retrieval-1', "
            "?, ?, ?, NULL, ?)",
            (AT.isoformat(), AT.isoformat(), AT.isoformat(), "b" * 64),
        )
        connection.exec_driver_sql(
            "INSERT INTO official_offer_families "
            "(official_offer_family_id, lane, business_key, official_match_no, match_id, "
            "created_at) VALUES "
            "('offer-family-1', 'jczq', '2026-09-04', '001', 'match-1', ?)",
            (AT.isoformat(),),
        )
        connection.exec_driver_sql(
            "INSERT INTO official_offer_revisions "
            "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
            "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
            "sale_deadline_at, status) VALUES "
            "('offer-revision-1', 'offer-family-1', 'slate-1', 'match-1', '001', "
            "'[\"md-had\"]', ?, ?, 'on_sale')",
            (AT.isoformat(), (AT + timedelta(hours=4)).isoformat()),
        )
    with OntologyUnitOfWork(engine) as uow:
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="obs-anchor",
                observation_type="structural_context",
                subject_type="match",
                subject_id="match-1",
                scope_match_id="match-1",
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
        if market_state != "missing":
            quote_ids = ("quote-3", "quote-1", "quote-0")
            for quote_id, selection_id, decimal_odds in (
                ("quote-3", "sel-had-home", 2.5),
                ("quote-1", "sel-had-draw", 10 / 3),
                ("quote-0", "sel-had-away", 10 / 3),
            ):
                uow.market.insert_quote(
                    QuoteRow(
                        quote_id=quote_id,
                        match_id="match-1",
                        market_definition_id="md-had",
                        selection_id=selection_id,
                        provider="sporttery",
                        bookmaker=None,
                        decimal_odds=decimal_odds,
                        captured_at=AT.isoformat(),
                        artifact_retrieval_id="retrieval-1",
                        quote_status="active",
                    )
                )
            uow.market.insert_snapshot(
                SnapshotRow(
                    market_snapshot_id="snapshot-1",
                    match_id="match-1",
                    market_definition_id="md-had",
                    snapshot_kind="read_time",
                    as_of=AT.isoformat(),
                    fair_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                    devig_method="proportional",
                    method_version="1",
                    source_coverage={"providers": 1, "quotes": 3},
                    freshness={},
                    disagreement=(
                        {"state": "conflict"} if market_state == "conflict" else {}
                    ),
                ),
                quote_ids=quote_ids,
            )
        uow.decision.insert_factor_family(
            FactorFamilyRow(
                factor_family_id="factor-family-1",
                name="fixture factor",
                definition="deterministic test fixture",
            )
        )
        for index in (1, 2):
            uow.decision.insert_factor_definition(
                FactorDefinitionRow(
                    factor_definition_id=f"factor-{index}",
                    factor_family_id="factor-family-1",
                    version=index,
                    name=f"factor {index}",
                    definition="fixture",
                    scope="match",
                    status="active",
                    born_from_refs=["obs-anchor"],
                    valid_from=AT.isoformat(),
                    valid_to=None,
                    policy_version="governance-v1",
                )
            )


def _seed_second_match(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO matches (match_id) VALUES ('match-2')")
        connection.exec_driver_sql(
            "INSERT INTO official_offer_families "
            "(official_offer_family_id, lane, business_key, official_match_no, match_id, "
            "created_at) VALUES "
            "('offer-family-2', 'jczq', '2026-09-04', '002', 'match-2', ?)",
            (AT.isoformat(),),
        )
        connection.exec_driver_sql(
            "INSERT INTO official_offer_revisions "
            "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
            "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
            "sale_deadline_at, status) VALUES "
            "('offer-revision-2', 'offer-family-2', 'slate-1', 'match-2', '002', "
            "'[\"md-had\"]', ?, ?, 'on_sale')",
            (AT.isoformat(), (AT + timedelta(hours=4)).isoformat()),
        )
    with OntologyUnitOfWork(engine) as uow:
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="obs-anchor-2",
                observation_type="structural_context",
                subject_type="match",
                subject_id="match-2",
                scope_match_id="match-2",
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
        quote_ids = ("quote-2-3", "quote-2-1", "quote-2-0")
        for quote_id, selection_id, decimal_odds in (
            ("quote-2-3", "sel-had-home", 2.5),
            ("quote-2-1", "sel-had-draw", 10 / 3),
            ("quote-2-0", "sel-had-away", 10 / 3),
        ):
            uow.market.insert_quote(
                QuoteRow(
                    quote_id=quote_id,
                    match_id="match-2",
                    market_definition_id="md-had",
                    selection_id=selection_id,
                    provider="sporttery",
                    bookmaker=None,
                    decimal_odds=decimal_odds,
                    captured_at=AT.isoformat(),
                    artifact_retrieval_id="retrieval-1",
                    quote_status="active",
                )
            )
        uow.market.insert_snapshot(
            SnapshotRow(
                market_snapshot_id="snapshot-2",
                match_id="match-2",
                market_definition_id="md-had",
                snapshot_kind="read_time",
                as_of=AT.isoformat(),
                fair_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                devig_method="proportional",
                method_version="1",
                source_coverage={"providers": 1, "quotes": 3},
                freshness={},
                disagreement={},
            ),
            quote_ids=quote_ids,
        )


def _fixture(
    tmp_path: Path,
    *,
    market_state: str = "complete",
    match_count: int = 1,
) -> JudgmentFixture:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_sale_market_and_evidence(engine, market_state=market_state)
    if match_count == 2:
        if market_state != "complete":
            raise ValueError("two-match fixture requires complete markets")
        _seed_second_match(engine)
    elif match_count != 1:
        raise ValueError("test fixture supports one or two matches")
    snapshot_id = None if market_state == "missing" else "snapshot-1"
    match_plans = [
        EvidenceFreezeMatchPlan(
            match_id="match-1",
            market_snapshot_id=snapshot_id,
            prior_distribution=(
                {} if snapshot_id is None else {"home": 0.4, "draw": 0.3, "away": 0.3}
            ),
            candidate_observation_ids=("obs-anchor",),
            caveat_claim_ids=(),
            requirement_states=tuple(
                (requirement, "complete")
                for requirement in ("E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC")
            ),
            requirement_ref_tokens=("obs-anchor",),
            market_prior_ref_tokens=(
                ()
                if snapshot_id is None
                else ("snapshot-1", "quote-3", "quote-1", "quote-0")
            ),
            conflicts_cleared_ref_tokens=(),
        )
    ]
    if match_count == 2:
        match_plans.append(
            EvidenceFreezeMatchPlan(
                match_id="match-2",
                market_snapshot_id="snapshot-2",
                prior_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                candidate_observation_ids=("obs-anchor-2",),
                caveat_claim_ids=(),
                requirement_states=tuple(
                    (requirement, "complete")
                    for requirement in (
                        "E1",
                        "E2",
                        "E3",
                        "E4",
                        "E5",
                        "E6a",
                        "E6b",
                        "EC",
                    )
                ),
                requirement_ref_tokens=("obs-anchor-2",),
                market_prior_ref_tokens=(
                    "snapshot-2",
                    "quote-2-3",
                    "quote-2-1",
                    "quote-2-0",
                ),
                conflicts_cleared_ref_tokens=(),
            )
        )
    gate = EvidenceFreezeGate(
        task_family_id="jczq:2026-09-04",
        lane="jczq",
        business_key="2026-09-04",
        slate_revision_id="slate-1",
        task_snapshot_hash="c" * 64,
        requirement_revision_token="requirements-1",
        information_cutoff_at=AT,
        policy_version="governance-v1",
        ready=True,
        required_match_count=match_count,
        matches=tuple(match_plans),
    )
    gate_box = [gate]

    def resolve_gate(_uow, _lane: str, _business_key: str, _as_of: datetime):
        return gate_box[0]

    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    evidence_actions = EvidenceActions(
        action_service,
        freeze_gate_resolver=resolve_gate,
    )
    requested = evidence_actions.request_evidence_freeze(
        RequestEvidenceFreezeRequest(
            task_family_id=gate.task_family_id,
            lane="jczq",
            business_key=gate.business_key,
            requirement_revision_token=gate.requirement_revision_token,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="request-freeze:1",
            requested_at=AT,
        )
    )
    worker = EvidenceFreezeRequestWorker(
        action_service=action_service,
        evidence_actions=evidence_actions,
        bundle_actions=BundleActions(action_service),
        worker_id="evidence-worker",
        lease_duration=timedelta(minutes=5),
    )
    linked = worker.run_once(limit=1, as_of=AT + timedelta(seconds=1))
    assert requested.status is ActionStatus.COMMITTED
    assert len(linked) == 1
    task_bundle_revision_id = linked[0].result_refs[0].object_id
    return JudgmentFixture(
        engine=engine,
        action_service=action_service,
        evidence_actions=evidence_actions,
        decision_actions=OperatorDecisionActions(action_service),
        task_bundle_revision_id=task_bundle_revision_id,
        gate_box=gate_box,
    )


def _baseline_request(
    fixture: JudgmentFixture,
    key: str = "baseline:1",
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
) -> FreezeMarketPriorBaselineRequest:
    return FreezeMarketPriorBaselineRequest(
        task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
        work_item_id=WORK_ITEM_ID,
        actor_id="system:market-baseline",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT + timedelta(seconds=2),
    )


def _envelope_request(
    fixture: JudgmentFixture,
    key: str = "envelope:1",
) -> RecordBaselineEnvelopeRequest:
    return RecordBaselineEnvelopeRequest(
        task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
        work_item_id=WORK_ITEM_ID,
        ticket_kind="jczq_pass",
        capital_cap_minor=20000,
        currency="CNY",
        maximum_ticket_count=2,
        offer_constraints=(
            BaselineEnvelopeOfferConstraint(
                official_match_no="001",
                market_code="had",
                allowed_face_bundles=(
                    FaceBundleInput(bundle_code="home", face_codes=("3",)),
                    FaceBundleInput(bundle_code="home_draw", face_codes=("3", "1")),
                ),
                omission_allowed=False,
            ),
        ),
        structure_templates=(
            BaselineEnvelopeStructureTemplate(
                kind="jczq_pass",
                structure_code="single-1",
                eligible_official_match_nos=("001",),
                pass_size=1,
                required_offer_count=1,
                maximum_groups=1,
            ),
        ),
        maximum_exhaustive_candidate_count=100,
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=key,
        requested_at=AT + timedelta(seconds=3),
        expected_current_revision_no=0,
    )


def _create_baseline_and_envelope(fixture: JudgmentFixture) -> tuple[str, str]:
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    envelope = fixture.decision_actions.record_baseline_envelope(
        _envelope_request(fixture)
    )
    assert baseline.status is ActionStatus.COMMITTED
    assert envelope.status is ActionStatus.COMMITTED
    return baseline.result_refs[0].object_id, envelope.result_refs[0].object_id


def _judgment_request(
    fixture: JudgmentFixture,
    baseline_id: str,
    envelope_id: str,
    *,
    belief: tuple[FaceProbabilityInput, ...] = PRIOR,
    factors: tuple[FactorAdjustmentInput, ...] = (),
    rule_ids: tuple[str, ...] = ("k",),
    evidence_refs: tuple[str, ...] | None = None,
    market_definition_id: str = "md-had",
    match_id: str = "match-1",
    official_offer_revision_id: str = "offer-revision-1",
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
    key: str = "judgment:1",
) -> CommitOperatorMatchJudgmentRequest:
    return CommitOperatorMatchJudgmentRequest(
        task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
        market_prior_baseline_revision_id=baseline_id,
        baseline_envelope_revision_id=envelope_id,
        work_item_id=WORK_ITEM_ID,
        match_id=match_id,
        official_offer_revision_id=official_offer_revision_id,
        market_definition_id=market_definition_id,
        prior=PRIOR,
        belief=belief,
        factors=factors,
        expression_bundles=(
            FaceBundleInput(bundle_code="home_draw", face_codes=("3", "1")),
        ),
        rule_ids=rule_ids,
        evidence_ref_tokens=(
            evidence_refs
            if evidence_refs is not None
            else (("obs-anchor",) if match_id == "match-1" else ("obs-anchor-2",))
        ),
        falsifier="Starting lineup removes the registered structural premise.",
        rationale="Human judgment fixture.",
        commitment_tier="commit",
        actor_id="jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT + timedelta(seconds=4),
        expected_current_revision_no=0,
    )


def test_baseline_copies_exact_snapshot_quotes_and_decimal_probabilities(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    first = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    replay = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )

    assert first == replay
    assert first.status is ActionStatus.COMMITTED
    assert first.result_refs[0].object_type == "market_prior_baseline_revision"
    with fixture.engine.connect() as connection:
        parent = connection.execute(
            text(
                "SELECT comparison_only, probability_precision, arithmetic_version, "
                "task_evidence_bundle_revision_id FROM "
                "operator_market_prior_baseline_revisions"
            )
        ).mappings().one()
        rows = connection.execute(
            text(
                "SELECT face_code, probability_decimal, market_snapshot_id, quote_id "
                "FROM operator_market_prior_baseline_probabilities ORDER BY face_code"
            )
        ).mappings().all()
    assert parent["comparison_only"] == 1
    assert parent["probability_precision"] == 12
    assert parent["arithmetic_version"]
    assert parent["task_evidence_bundle_revision_id"] == fixture.task_bundle_revision_id
    assert {row["probability_decimal"] for row in rows} == {
        "0.400000000000",
        "0.300000000000",
    }
    assert {row["market_snapshot_id"] for row in rows} == {"snapshot-1"}
    assert {row["quote_id"] for row in rows} == {"quote-3", "quote-1", "quote-0"}


@pytest.mark.parametrize("market_state", ["missing", "conflict"])
def test_baseline_rejects_missing_or_conflicting_exact_market(
    tmp_path: Path,
    market_state: str,
) -> None:
    fixture = _fixture(tmp_path, market_state=market_state)

    with pytest.raises(ValueError, match="market"):
        fixture.decision_actions.freeze_market_prior_baseline(
            _baseline_request(fixture, key=f"baseline:{market_state}")
        )

    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_market_prior_baseline_revisions")
        ) == 0


def test_baseline_child_failure_rolls_back_parent_and_action_business_rows(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_baseline_child BEFORE INSERT ON "
            "operator_market_prior_baseline_probabilities BEGIN "
            "SELECT RAISE(ABORT, 'forced baseline child failure'); END"
        )

    with pytest.raises(IntegrityError, match="forced baseline child failure"):
        fixture.decision_actions.freeze_market_prior_baseline(
            _baseline_request(fixture, key="baseline:forced-failure")
        )

    with fixture.engine.connect() as connection:
        counts = (
            connection.scalar(
                text("SELECT COUNT(*) FROM operator_market_prior_baseline_revisions")
            ),
            connection.scalar(
                text("SELECT COUNT(*) FROM operator_market_prior_baseline_probabilities")
            ),
        )
    assert counts == (0, 0)


def test_envelope_preserves_only_explicit_judge_constraints(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    outcome = fixture.decision_actions.record_baseline_envelope(
        _envelope_request(fixture)
    )

    assert outcome.status is ActionStatus.COMMITTED
    with fixture.engine.connect() as connection:
        parent = connection.execute(
            text("SELECT * FROM operator_baseline_envelope_revisions")
        ).mappings().one()
        bundles = connection.execute(
            text(
                "SELECT bundle_code, face_code FROM "
                "operator_baseline_envelope_face_bundles AS bundle "
                "JOIN operator_baseline_envelope_bundle_faces AS face "
                "USING (baseline_envelope_face_bundle_id) "
                "ORDER BY bundle_code, face_code"
            )
        ).all()
        templates = connection.execute(
            text("SELECT * FROM operator_baseline_envelope_structure_templates")
        ).mappings().one()
    assert parent["capital_cap_minor"] == 20000
    assert parent["currency"] == "CNY"
    assert parent["maximum_ticket_count"] == 2
    assert parent["maximum_exhaustive_candidate_count"] == 100
    assert bundles == [("home", "3"), ("home_draw", "1"), ("home_draw", "3")]
    assert templates["structure_code"] == "single-1"


def test_market_baseline_worker_waits_for_committed_link_then_binds_result(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE actions SET status = 'accepted', committed_at = NULL "
                "WHERE action_id = (SELECT link_action_id FROM "
                "operator_task_evidence_bundle_revisions WHERE "
                "task_evidence_bundle_revision_id = :revision_id)"
            ),
            {"revision_id": fixture.task_bundle_revision_id},
        )
    worker = MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id="baseline-worker",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: WORK_ITEM_ID,
    )

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=5)) == ()
    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM operator_market_prior_baseline_revisions"
            )
        ) == 0


def test_market_baseline_worker_completes_job_with_exact_action_result(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    worker = MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id="baseline-worker",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: WORK_ITEM_ID,
    )

    completed = worker.run_once(limit=1, as_of=AT + timedelta(seconds=5))

    assert len(completed) == 1
    result = completed[0]
    with OntologyUnitOfWork(fixture.engine) as uow:
        job = uow.operator_decision.worker_job_for_source(
            job_kind="market_baseline",
            source_object_type="task_evidence_bundle_revision",
            source_object_id=fixture.task_bundle_revision_id,
        )
    assert job is not None
    assert job.state == "completed"
    assert job.result_action_id == result.action_id
    assert job.result_object_type == "market_prior_baseline_revision"
    assert job.result_object_id == result.result_refs[0].object_id


def test_market_baseline_worker_takeover_is_idempotent_across_worker_ids(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with OntologyUnitOfWork(fixture.engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="market_baseline",
            lease_owner="dead-worker",
            as_of=(AT + timedelta(seconds=2)).isoformat(),
            lease_expires_at=(AT + timedelta(seconds=3)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1
    worker = MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id="replacement-worker",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: WORK_ITEM_ID,
    )

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=5)) == ()
    completed = worker.run_once(limit=1, as_of=AT + timedelta(seconds=7))

    assert len(completed) == 1
    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_market_prior_baseline_revisions")
        ) == 1
        actor_ids = connection.execute(
            text(
                "SELECT actor_id FROM actions "
                "WHERE action_type = 'freeze_market_prior_baseline'"
            )
        ).scalars().all()
    assert actor_ids == ["system:operator-market-baseline"]


def test_market_baseline_job_completion_failure_rolls_back_action_and_rows(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_baseline_completion BEFORE UPDATE OF state ON "
            "operator_worker_jobs WHEN NEW.state = 'completed' BEGIN "
            "SELECT RAISE(ABORT, 'forced baseline completion failure'); END"
        )
    worker = MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id="baseline-worker",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: WORK_ITEM_ID,
    )

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=5)) == ()

    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_market_prior_baseline_revisions")
        ) == 0
        job = connection.execute(
            text(
                "SELECT state, last_error_code FROM operator_worker_jobs "
                "WHERE job_kind = 'market_baseline'"
            )
        ).one()
    assert job == ("failed", "invariant_failure")


def test_zero_delta_judgment_atomically_commits_forecast_and_link(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)

    outcome = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )

    assert outcome.status is ActionStatus.COMMITTED
    assert {ref.object_type for ref in outcome.result_refs} == {
        "forecast_revision",
        "operator_match_judgment_revision",
    }
    with fixture.engine.connect() as connection:
        probability_rows = connection.execute(
            text(
                "SELECT prior_probability_decimal, belief_probability_decimal, "
                "delta_probability_decimal FROM operator_match_judgment_probabilities"
            )
        ).all()
    assert probability_rows == [
        ("0.400000000000", "0.400000000000", "0.000000000000"),
        ("0.300000000000", "0.300000000000", "0.000000000000"),
        ("0.300000000000", "0.300000000000", "0.000000000000"),
    ]
    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (1, 1)


def test_judgment_quantizes_half_even_boundaries_to_canonical_twelve_places(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    rounded_prior = (
        FaceProbabilityInput("3", "0.4000000000005"),
        FaceProbabilityInput("1", "0.2999999999995"),
        FaceProbabilityInput("0", "0.3000000000000"),
    )

    outcome = fixture.decision_actions.commit_operator_match_judgment(
        replace(
            _judgment_request(fixture, baseline_id, envelope_id),
            prior=rounded_prior,
            belief=rounded_prior,
        )
    )

    assert outcome.status is ActionStatus.COMMITTED
    with fixture.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT prior_probability_decimal FROM "
                "operator_match_judgment_probabilities ORDER BY face_index"
            )
        ).scalars().all()
    assert rows == ["0.400000000000", "0.300000000000", "0.300000000000"]


def test_multi_match_progress_counts_only_each_committed_current_judgment(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, match_count=2)
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    envelope_request = replace(
        _envelope_request(fixture),
        offer_constraints=(
            *_envelope_request(fixture).offer_constraints,
            BaselineEnvelopeOfferConstraint(
                official_match_no="002",
                market_code="had",
                allowed_face_bundles=(
                    FaceBundleInput(bundle_code="home", face_codes=("3",)),
                    FaceBundleInput(
                        bundle_code="home_draw", face_codes=("3", "1")
                    ),
                ),
                omission_allowed=False,
            ),
        ),
        structure_templates=(
            BaselineEnvelopeStructureTemplate(
                kind="jczq_pass",
                structure_code="single-1",
                eligible_official_match_nos=("001", "002"),
                pass_size=1,
                required_offer_count=1,
                maximum_groups=2,
            ),
        ),
    )
    envelope = fixture.decision_actions.record_baseline_envelope(envelope_request)
    baseline_id = baseline.result_refs[0].object_id
    envelope_id = envelope.result_refs[0].object_id

    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (0, 2)
    fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )
    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (1, 2)
    fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            match_id="match-2",
            official_offer_revision_id="offer-revision-2",
            key="judgment:2",
        )
    )
    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (2, 2)


def test_decimal_storage_canonicalizes_quantized_negative_zero(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    factors = (
        FactorAdjustmentInput(
            factor_definition_id="factor-1",
            scope_key="match-1",
            evidence_ref_tokens=("obs-anchor",),
            offsets=(
                FaceOffsetInput("3", "-0.0000000000004"),
                FaceOffsetInput("1", "0.0000000000004"),
                FaceOffsetInput("0", "0.0000000000000"),
            ),
        ),
    )

    fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            factors=factors,
        )
    )

    with fixture.engine.connect() as connection:
        values = connection.execute(
            text(
                "SELECT offset_probability_decimal FROM "
                "operator_match_judgment_factor_offsets ORDER BY face_index"
            )
        ).scalars().all()
    assert values == ["0.000000000000", "0.000000000000", "0.000000000000"]


def test_nonzero_belief_requires_exact_factor_reconstruction(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    belief = (
        FaceProbabilityInput(face_code="3", probability_decimal="0.450000000000"),
        FaceProbabilityInput(face_code="1", probability_decimal="0.280000000000"),
        FaceProbabilityInput(face_code="0", probability_decimal="0.270000000000"),
    )

    with pytest.raises(ValueError, match="non-zero.*Factor"):
        fixture.decision_actions.commit_operator_match_judgment(
            _judgment_request(
                fixture,
                baseline_id,
                envelope_id,
                belief=belief,
                factors=(),
            )
        )


def test_multiple_factors_reconstruct_exact_belief_with_zero_sum_offsets(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    belief = (
        FaceProbabilityInput(face_code="3", probability_decimal="0.450000000000"),
        FaceProbabilityInput(face_code="1", probability_decimal="0.280000000000"),
        FaceProbabilityInput(face_code="0", probability_decimal="0.270000000000"),
    )
    factors = (
        FactorAdjustmentInput(
            factor_definition_id="factor-1",
            scope_key="match-1",
            evidence_ref_tokens=("obs-anchor",),
            offsets=(
                FaceOffsetInput("3", "0.030000000000"),
                FaceOffsetInput("1", "-0.010000000000"),
                FaceOffsetInput("0", "-0.020000000000"),
            ),
        ),
        FactorAdjustmentInput(
            factor_definition_id="factor-2",
            scope_key="match-1",
            evidence_ref_tokens=("obs-anchor",),
            offsets=(
                FaceOffsetInput("3", "0.020000000000"),
                FaceOffsetInput("1", "-0.010000000000"),
                FaceOffsetInput("0", "-0.010000000000"),
            ),
        ),
    )

    outcome = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            belief=belief,
            factors=factors,
        )
    )

    assert outcome.status is ActionStatus.COMMITTED
    with fixture.engine.connect() as connection:
        offsets = connection.execute(
            text(
                "SELECT offset_probability_decimal FROM "
                "operator_match_judgment_factor_offsets"
            )
        ).scalars().all()
    assert offsets == [
        "0.030000000000",
        "-0.010000000000",
        "-0.020000000000",
        "0.020000000000",
        "-0.010000000000",
        "-0.010000000000",
    ]
    with fixture.engine.connect() as connection:
        counts = {
            table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in (
                "operator_match_judgment_factor_adjustments",
                "operator_match_judgment_factor_evidence_refs",
                "operator_match_judgment_face_bundles",
                "operator_match_judgment_bundle_faces",
                "operator_match_judgment_rule_refs",
                "operator_match_judgment_evidence_refs",
            )
        }
    assert counts == {
        "operator_match_judgment_factor_adjustments": 2,
        "operator_match_judgment_factor_evidence_refs": 2,
        "operator_match_judgment_face_bundles": 1,
        "operator_match_judgment_bundle_faces": 2,
        "operator_match_judgment_rule_refs": 1,
        "operator_match_judgment_evidence_refs": 1,
    }


def test_judgment_rejects_cross_work_item_dependency(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    other_envelope = fixture.decision_actions.record_baseline_envelope(
        replace(
            _envelope_request(fixture),
            work_item_id="jczq:2026-09-04:wave:other",
            idempotency_key="envelope:other-work-item",
        )
    )

    with pytest.raises(ValueError, match="work item|lineage"):
        fixture.decision_actions.commit_operator_match_judgment(
            _judgment_request(
                fixture,
                baseline.result_refs[0].object_id,
                other_envelope.result_refs[0].object_id,
                key="judgment:cross-work-item",
            )
        )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("prior_mismatch", "prior"),
        ("belief_not_normalized", "sum"),
        ("factor_not_zero_sum", "zero"),
        ("missing_anchor", "evidence"),
        ("unknown_rule", "Rule"),
        ("unknown_factor", "Factor"),
        ("unknown_face", "face"),
        ("unknown_market", "market"),
    ],
)
def test_judgment_rejects_invalid_exact_inputs(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    request = _judgment_request(fixture, baseline_id, envelope_id, key=f"judgment:{case}")
    if case == "prior_mismatch":
        request = replace(
            request,
            prior=(
                FaceProbabilityInput("3", "0.410000000000"),
                FaceProbabilityInput("1", "0.290000000000"),
                FaceProbabilityInput("0", "0.300000000000"),
            ),
        )
    elif case == "belief_not_normalized":
        request = replace(
            request,
            belief=(
                FaceProbabilityInput("3", "0.500000000000"),
                FaceProbabilityInput("1", "0.300000000000"),
                FaceProbabilityInput("0", "0.300000000000"),
            ),
        )
    elif case == "factor_not_zero_sum":
        request = replace(
            request,
            factors=(
                FactorAdjustmentInput(
                    "factor-1",
                    "match-1",
                    ("obs-anchor",),
                    (
                        FaceOffsetInput("3", "0.010000000000"),
                        FaceOffsetInput("1", "0.000000000000"),
                        FaceOffsetInput("0", "0.000000000000"),
                    ),
                ),
            ),
        )
    elif case == "missing_anchor":
        request = replace(request, evidence_ref_tokens=("unknown-evidence",))
    elif case == "unknown_rule":
        request = replace(request, rule_ids=("invented-rule",))
    elif case == "unknown_factor":
        request = replace(
            request,
            factors=(
                FactorAdjustmentInput(
                    "unknown-factor",
                    "match-1",
                    ("obs-anchor",),
                    (
                        FaceOffsetInput("3", "0.000000000000"),
                        FaceOffsetInput("1", "0.000000000000"),
                        FaceOffsetInput("0", "0.000000000000"),
                    ),
                ),
            ),
        )
    elif case == "unknown_face":
        request = replace(
            request,
            expression_bundles=(FaceBundleInput("bad", ("X",)),),
        )
    else:
        request = replace(request, market_definition_id="md-unknown")

    with pytest.raises(ValueError, match=message):
        fixture.decision_actions.commit_operator_match_judgment(request)


def test_ai_cannot_commit_judgment_and_rejected_action_does_not_count_progress(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    outcome = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            role=ActorRole.AI_ANALYST,
            key="judgment:ai",
        )
    )

    assert outcome.status is ActionStatus.REJECTED
    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (0, 1)


def test_judgment_and_forecast_roll_back_together_on_link_failure(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_judgment_link BEFORE INSERT ON "
            "operator_match_judgment_revisions BEGIN "
            "SELECT RAISE(ABORT, 'forced judgment link failure'); END"
        )

    with pytest.raises(IntegrityError, match="forced judgment link failure"):
        fixture.decision_actions.commit_operator_match_judgment(
            _judgment_request(
                fixture,
                baseline_id,
                envelope_id,
                key="judgment:forced-failure",
            )
        )

    with fixture.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(schema_decision.forecast_revisions)
        ) == 0
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_match_judgment_revisions")
        ) == 0


def test_superseded_task_bundle_blocks_old_judgment_dependencies(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    fixture.gate_box[0] = replace(
        fixture.gate_box[0],
        requirement_revision_token="requirements-2",
    )
    fixture.evidence_actions.request_evidence_freeze(
        RequestEvidenceFreezeRequest(
            task_family_id="jczq:2026-09-04",
            lane="jczq",
            business_key="2026-09-04",
            requirement_revision_token="requirements-2",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="request-freeze:2",
            requested_at=AT + timedelta(seconds=5),
        )
    )
    EvidenceFreezeRequestWorker(
        action_service=fixture.action_service,
        evidence_actions=fixture.evidence_actions,
        bundle_actions=BundleActions(fixture.action_service),
        worker_id="evidence-worker-2",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(seconds=6))

    with pytest.raises(ValueError, match="stale|superseded"):
        fixture.decision_actions.commit_operator_match_judgment(
            _judgment_request(
                fixture,
                baseline_id,
                envelope_id,
                key="judgment:stale",
            )
        )


def test_new_official_slate_invalidates_old_task_bundle_before_baseline(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-2', 'jczq:2026-09-04', 'jczq', '2026-09-04', 2, "
            "'retrieval-1', ?, ?, ?, 'slate-1', ?)",
            (
                (AT + timedelta(seconds=5)).isoformat(),
                (AT + timedelta(seconds=5)).isoformat(),
                (AT + timedelta(seconds=5)).isoformat(),
                "c" * 64,
            ),
        )

    with pytest.raises(ValueError, match="slate.*stale|stale.*slate"):
        fixture.decision_actions.freeze_market_prior_baseline(
            _baseline_request(fixture)
        )


@pytest.mark.parametrize("invalid_revision", (0.0, "0", Decimal("0")))
def test_judgment_forecast_cas_revision_requires_a_strict_integer(
    tmp_path: Path,
    invalid_revision: object,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)

    with pytest.raises(ValueError, match="expected_current_revision_no.*integer"):
        replace(
            _judgment_request(fixture, baseline_id, envelope_id),
            expected_current_revision_no=invalid_revision,
        )


def test_prescription_requires_every_current_committed_match_judgment(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    request = FreezeJudgmentPrescriptionRequest(
        task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
        market_prior_baseline_revision_id=baseline_id,
        baseline_envelope_revision_id=envelope_id,
        work_item_id=WORK_ITEM_ID,
        judgment_revision_ids=(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="prescription:incomplete",
        requested_at=AT + timedelta(seconds=5),
        expected_current_revision_no=0,
    )

    with pytest.raises(ValueError, match="every required match"):
        fixture.decision_actions.freeze_judgment_prescription(request)

    judgment = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )
    judgment_id = next(
        ref.object_id
        for ref in judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    outcome = fixture.decision_actions.freeze_judgment_prescription(
        replace(
            request,
            judgment_revision_ids=(judgment_id,),
            idempotency_key="prescription:complete",
        )
    )
    assert outcome.status is ActionStatus.COMMITTED
    assert outcome.result_refs[0].object_type == "judgment_prescription_revision"


def test_baseline_role_is_system_only_and_human_actions_are_judge_only(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(
            fixture,
            key="baseline:judge-denied",
            role=ActorRole.JUDGE_OPERATOR,
        )
    )
    envelope = fixture.decision_actions.record_baseline_envelope(
        replace(
            _envelope_request(fixture, key="envelope:ai-denied"),
            actor_role=ActorRole.AI_ANALYST,
        )
    )

    assert baseline.status is ActionStatus.REJECTED
    assert envelope.status is ActionStatus.REJECTED
    with fixture.engine.connect() as connection:
        denied = connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.status == "rejected")
        )
    assert denied == 2
