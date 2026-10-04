from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.finance.settlement import (
    crs_result_code,
    grade_market_leg,
    jczq_note_grade,
    jczq_note_payout_minor,
    zucai_note_grade,
    zucai_note_payout_minor,
)
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FaceProbabilityInput,
    FreezeJudgmentPrescriptionRequest,
    RecordBaselineEnvelopeRequest,
)
from nutmeg.ontology.operator.result_actions import (
    ImportResultEvidenceRequest,
    OperatorResultActions,
    RegisterZucaiFixedPrizePolicyRequest,
    RequestSettlementRequest,
    SettleTaskRequest,
)
from nutmeg.ontology.operator.result_manifest import ResultEvidenceManifestV1
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_result_ingest import (
    AT,
    _import_request,
    _parsed_manifest,
    _setup_actions,
)
from tests.ontology.operator.zucai_replay_lineage import (
    AT as ZUCAI_AT,
)
from tests.ontology.operator.zucai_replay_lineage import (
    SUPPORT_PRIOR,
)
from tests.ontology.operator.zucai_replay_lineage import (
    WORK_ITEM_ID as ZUCAI_WORK_ITEM_ID,
)


@pytest.mark.parametrize(
    ("market", "selection", "home", "away", "line", "result_code", "grade"),
    (
        ("had", "home", 2, 1, None, "home", "won"),
        ("had", "draw", 2, 1, None, "home", "lost"),
        ("hhad", "draw", 2, 1, "-1.000000000000", "draw", "won"),
        ("hhad", "away", 0, 0, "-1.000000000000", "away", "won"),
        ("ttg", "total_7", 5, 4, None, "total_7", "won"),
        ("ttg", "total_6", 5, 4, None, "total_7", "lost"),
    ),
)
def test_jczq_market_graders_are_closed_and_use_the_persisted_line(
    market: str,
    selection: str,
    home: int,
    away: int,
    line: str | None,
    result_code: str,
    grade: str,
) -> None:
    result = grade_market_leg(
        market_kind=market,
        selection_code=selection,
        result_disposition="played_90",
        home_90=home,
        away_90=away,
        settlement_parameter_decimal=line,
    )

    assert result.market_result_code == result_code
    assert result.leg_grade == grade


@pytest.mark.parametrize(
    ("home", "away", "expected"),
    (
        (1, 0, "1:0"),
        (6, 2, "win_other"),
        (4, 4, "draw_other"),
        (1, 5, "loss_other"),
    ),
)
def test_crs_uses_exact_or_direction_specific_aggregate(
    home: int,
    away: int,
    expected: str,
) -> None:
    assert crs_result_code(home, away, frozenset({"1:0", "0:0"})) == expected


@pytest.mark.parametrize(
    ("selection", "home", "away", "expected_grade"),
    (
        ("1:0", 1, 0, "won"),
        ("win_other", 6, 2, "won"),
        ("draw_other", 4, 4, "won"),
        ("loss_other", 1, 5, "won"),
        ("win_other", 1, 0, "lost"),
    ),
)
def test_crs_grades_exact_and_each_directional_aggregate(
    selection: str,
    home: int,
    away: int,
    expected_grade: str,
) -> None:
    result = grade_market_leg(
        market_kind="crs",
        selection_code=selection,
        result_disposition="played_90",
        home_90=home,
        away_90=away,
        crs_exact_codes=frozenset({"1:0", "0:0"}),
    )

    assert result.leg_grade == expected_grade


def test_crs_rejects_the_legacy_generic_other_selection() -> None:
    with pytest.raises(ValueError, match="unsupported CRS selection"):
        grade_market_leg(
            market_kind="crs",
            selection_code="other",
            result_disposition="played_90",
            home_90=4,
            away_90=1,
            crs_exact_codes=frozenset({"1:0"}),
        )


@pytest.mark.parametrize(
    ("grades", "expected"),
    (
        (("lost", "void"), "lost"),
        (("won", "void"), "won"),
        (("void", "void"), "void"),
    ),
)
def test_jczq_note_state_is_closed(
    grades: tuple[str, ...],
    expected: str,
) -> None:
    assert jczq_note_grade(grades) == expected


def test_jczq_payout_uses_decimal_and_rounds_half_up_once_per_note() -> None:
    assert jczq_note_payout_minor(
        stake_minor=101,
        leg_grades=("won", "void", "won"),
        booked_decimal_odds=(
            "1.500000000000",
            None,
            "1.010000000000",
        ),
    ) == 153

    assert jczq_note_payout_minor(
        stake_minor=101,
        leg_grades=("void", "void"),
        booked_decimal_odds=(None, None),
    ) == 101


def test_jczq_lost_note_has_no_payout_and_bad_odds_are_rejected() -> None:
    assert jczq_note_payout_minor(
        stake_minor=200,
        leg_grades=("won", "lost"),
        booked_decimal_odds=("2.000000000000", "8.000000000000"),
    ) == 0
    with pytest.raises(ValueError, match="canonical positive decimal"):
        jczq_note_payout_minor(
            stake_minor=200,
            leg_grades=("won",),
            booked_decimal_odds=(str(Decimal("1.9")),),
        )


def test_jczq_rounds_half_up_once_after_the_complete_note_product() -> None:
    assert jczq_note_payout_minor(
        stake_minor=100,
        leg_grades=("won", "won"),
        booked_decimal_odds=("1.005000000000", "1.000000000000"),
    ) == 101


@pytest.mark.parametrize(
    ("grades", "odds"),
    (
        ((), ()),
        (("won",), ()),
        (("won",), (None,)),
        (("invalid",), ("2.000000000000",)),
    ),
)
def test_jczq_payout_rejects_incomplete_or_invalid_leg_inputs(
    grades: tuple[str, ...],
    odds: tuple[str | None, ...],
) -> None:
    with pytest.raises(ValueError):
        jczq_note_payout_minor(
            stake_minor=200,
            leg_grades=grades,
            booked_decimal_odds=odds,
        )


@pytest.mark.parametrize(
    ("ticket_kind", "correct", "expected_grade", "expected_tier"),
    (
        ("sfc", 14, "won", "sfc_first"),
        ("sfc", 13, "won", "sfc_second"),
        ("sfc", 12, "lost", None),
        ("renjiu", 9, "won", "renjiu_first"),
        ("renjiu", 8, "lost", None),
    ),
)
def test_zucai_tiers_are_exact_and_mutually_exclusive(
    ticket_kind: str,
    correct: int,
    expected_grade: str,
    expected_tier: str | None,
) -> None:
    grade = zucai_note_grade(ticket_kind=ticket_kind, correct_leg_count=correct)

    assert grade.note_grade == expected_grade
    assert grade.prize_tier_code == expected_tier


def test_zucai_payout_is_exact_integer_unit_multiplication() -> None:
    assert zucai_note_payout_minor(
        unit_count=7,
        payout_minor_per_winning_note=12_345,
        won=True,
    ) == 86_415
    assert zucai_note_payout_minor(
        unit_count=7,
        payout_minor_per_winning_note=12_345,
        won=False,
    ) == 0


@pytest.mark.parametrize(
    ("ticket_kind", "correct"),
    (("sfc", -1), ("sfc", 15), ("renjiu", 10), ("unknown", 9)),
)
def test_zucai_grade_rejects_counts_outside_the_bound_ticket_shape(
    ticket_kind: str,
    correct: int,
) -> None:
    with pytest.raises(ValueError):
        zucai_note_grade(ticket_kind=ticket_kind, correct_leg_count=correct)


@pytest.mark.parametrize(
    ("unit_count", "payout", "won"),
    ((0, 100, True), (1, -1, True), (True, 100, True), (1, 100, 1)),
)
def test_zucai_payout_rejects_non_exact_integer_inputs(
    unit_count: int,
    payout: int,
    won: bool,
) -> None:
    with pytest.raises(ValueError):
        zucai_note_payout_minor(
            unit_count=unit_count,
            payout_minor_per_winning_note=payout,
            won=won,
        )


def test_official_void_is_market_void_for_jczq() -> None:
    result = grade_market_leg(
        market_kind="had",
        selection_code="home",
        result_disposition="official_void",
        home_90=None,
        away_90=None,
    )

    assert result.market_result_code == "official_void"
    assert result.leg_grade == "void"


@pytest.mark.parametrize(
    ("market", "selection", "line", "exact_codes", "message"),
    (
        ("had", "unknown", None, frozenset(), "unsupported HAD selection"),
        ("hhad", "home", None, frozenset(), "requires its persisted settlement line"),
        ("hhad", "home", "-1", frozenset(), "canonical positive decimal"),
        ("ttg", "total_8", None, frozenset(), "unsupported TTG selection"),
        ("crs", "other", None, frozenset({"1:0"}), "unsupported CRS selection"),
        ("crs", "2:0", None, frozenset({"1:0"}), "unsupported CRS selection"),
    ),
)
def test_official_void_still_rejects_unsupported_market_inputs(
    market: str,
    selection: str,
    line: str | None,
    exact_codes: frozenset[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        grade_market_leg(
            market_kind=market,
            selection_code=selection,
            result_disposition="official_void",
            home_90=None,
            away_90=None,
            settlement_parameter_decimal=line,
            crs_exact_codes=exact_codes,
        )


def test_unknown_market_and_invalid_score_shape_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported settlement market"):
        grade_market_leg(
            market_kind="corners",
            selection_code="over",
            result_disposition="played_90",
            home_90=1,
            away_90=0,
        )


@pytest.mark.parametrize(
    ("market", "selection", "line"),
    (
        ("had", "unknown", None),
        ("hhad", "home", None),
        ("hhad", "home", "-1"),
        ("ttg", "total_8", None),
        ("crs", "2:0", None),
    ),
)
def test_market_graders_reject_unregistered_or_unversioned_inputs(
    market: str,
    selection: str,
    line: str | None,
) -> None:
    with pytest.raises(ValueError):
        grade_market_leg(
            market_kind=market,
            selection_code=selection,
            result_disposition="played_90",
            home_90=2,
            away_90=0,
            settlement_parameter_decimal=line,
            crs_exact_codes=frozenset({"1:0", "0:0"}),
        )


def test_postponed_result_is_not_settleable() -> None:
    with pytest.raises(ValueError, match="not settleable"):
        grade_market_leg(
            market_kind="had",
            selection_code="home",
            result_disposition="postponed",
            home_90=None,
            away_90=None,
        )
    with pytest.raises(ValueError, match="played result requires"):
        grade_market_leg(
            market_kind="had",
            selection_code="home",
            result_disposition="played_90",
            home_90=None,
            away_90=0,
        )


def _import_complete_result(tmp_path: Path):
    actions, engine = _setup_actions(tmp_path)
    imported = actions.import_result_evidence_set(
        _import_request(_parsed_manifest())
    )
    assert imported.outcome.status is ActionStatus.COMMITTED
    assert imported.result_set is not None
    return actions, engine, imported.result_set


def _settlement_request(result_set, *, role=ActorRole.JUDGE_OPERATOR):
    return RequestSettlementRequest(
        result_set_revision_id=result_set.result_set_revision_id,
        expected_task_snapshot_hash=result_set.task_snapshot_hash,
        actor_id="jun",
        actor_role=role,
        idempotency_key="settlement:request:1",
        requested_at=AT + timedelta(minutes=1),
    )


def test_request_settlement_is_judge_only_and_replay_queues_one_job(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _import_complete_result(tmp_path)

    denied = actions.request_settlement(
        replace(
            _settlement_request(result_set),
            actor_id="system:worker",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="settlement:request:denied",
        )
    )
    requested = actions.request_settlement(_settlement_request(result_set))
    replayed = actions.request_settlement(_settlement_request(result_set))

    assert denied.status is ActionStatus.REJECTED
    assert requested.status is ActionStatus.COMMITTED
    assert replayed == requested
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_settlement_requests)
        ) == 1
        assert connection.scalar(
            select(func.count())
            .select_from(sod.operator_worker_jobs)
            .where(sod.operator_worker_jobs.c.job_kind == "task_settlement")
        ) == 1


def test_zero_placement_settlement_is_atomic_not_applicable(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _import_complete_result(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))
    request_id = requested.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    assert len(jobs) == 1

    settled = actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=request_id,
            worker_job_id=jobs[0].worker_job_id,
            lease_owner="settlement-worker",
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
            actor_id="system:settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="settlement:run:1",
            requested_at=AT + timedelta(minutes=2),
        )
    )

    assert settled.status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.worker_job_id == jobs[0].worker_job_id
            )
        ).mappings().one()
        child_counts = tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_ticket_settlement_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
            )
        )
    assert run["settlement_state"] == "not_applicable"
    assert run["requested_ticket_count"] == 0
    assert run["eligible_ticket_count"] == 0
    assert run["skipped_ticket_count"] == 0
    assert child_counts == (0, 0, 0, 0)
    assert job["state"] == "completed"
    assert job["result_action_id"] == settled.action_id


def test_settlement_rejects_an_unregistered_method_version(tmp_path: Path) -> None:
    actions, engine, result_set = _import_complete_result(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )

    with pytest.raises(ValueError, match="unsupported settlement method version"):
        actions.settle_task(
            SettleTaskRequest(
                settlement_request_id=requested.result_refs[0].object_id,
                worker_job_id=jobs[0].worker_job_id,
                lease_owner="settlement-worker",
                settlement_method_version="invented-settlement-v99",
                rounding_policy_version="cn_sporttery_jczq_v1",
                actor_id="system:settlement",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="settlement:unknown-method",
                requested_at=AT + timedelta(minutes=2),
            )
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_task_settlement_runs)
        ) == 0
        failed = connection.execute(
            select(schema.actions).where(
                schema.actions.c.idempotency_key == "settlement:unknown-method"
            )
        ).mappings().one()
    assert failed["status"] == "failed"


def _seed_result_retrievals(
    engine,
    *,
    suffix: str = "",
    captured_at: str = "2026-09-05T00:00:00+00:00",
) -> None:
    sources = (
        (
            "api_football",
            "api-football",
            "https://v3.football.api-sports.io/fixtures?id=1",
            "b",
        ),
        (
            "sporttery_game90",
            "sporttery",
            "https://webapi.sporttery.cn/results/game90.json",
            "c",
        ),
        (
            "okooo_manual",
            "okooo-manual",
            "https://m.okooo.com/kaijiang/sport.php",
            "d",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs),
            [
                {
                    "source_run_id": f"result-run-{kind}{suffix}",
                    "source_name": source_name,
                    "source_type": kind,
                    "started_at": captured_at,
                    "finished_at": captured_at,
                    "status": "succeeded",
                }
                for kind, source_name, _url, _character in sources
            ],
        )
        connection.execute(
            insert(schema.source_artifacts),
            [
                {
                    "artifact_id": f"result-artifact-{kind}{suffix}",
                    "first_recorded_at": captured_at,
                    "content_type": "application/json",
                    "storage_path": f"sha256/result-{kind}{suffix}",
                    "byte_size": 2,
                    "content_hash": hashlib.sha256(
                        f"{kind}:{suffix}:{character}".encode("utf-8")
                    ).hexdigest(),
                }
                for kind, _source_name, _url, character in sources
            ],
        )
        connection.execute(
            insert(schema.artifact_retrievals),
            [
                {
                    "artifact_retrieval_id": f"result-retrieval-{kind}{suffix}",
                    "artifact_id": f"result-artifact-{kind}{suffix}",
                    "source_run_id": f"result-run-{kind}{suffix}",
                    "source_name": source_name,
                    "source_type": kind,
                    "reported_content_type": "application/json",
                    "canonical_url": url,
                    "requested_url": url,
                    "published_at": captured_at,
                    "retrieved_at": captured_at,
                    "status": "stored",
                }
                for kind, source_name, url, _character in sources
            ],
        )


def _complete_pending_fixture_baseline_job(engine, *, work_item_id: str) -> None:
    completed_at = datetime.now(UTC)
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="market_baseline",
            lease_owner="public-replay-fixture",
            as_of=completed_at.isoformat(),
            lease_expires_at=(completed_at + timedelta(minutes=5)).isoformat(),
            limit=1,
        )
        assert len(jobs) == 1
        baseline = uow.connection.execute(
            select(sod.operator_market_prior_baseline_revisions).where(
                sod.operator_market_prior_baseline_revisions.c.work_item_id
                == work_item_id
            )
        ).mappings().one()
        uow.operator_decision.complete_worker_job(
            worker_job_id=jobs[0].worker_job_id,
            lease_owner="public-replay-fixture",
            result_action_id=str(baseline["action_id"]),
            result_object_type="market_prior_baseline_revision",
            result_object_id=str(baseline["market_prior_baseline_revision_id"]),
            completed_at=completed_at.isoformat(),
        )


def _replace_with_sfc_decision_lineage(
    *,
    engine,
    decision_actions,
    result_actions,
    document: dict[str, object],
    requested_at_base: datetime | None = None,
) -> None:
    base = requested_at_base or (ZUCAI_AT + timedelta(minutes=6))
    with OntologyUnitOfWork(engine) as uow:
        bundle = uow.connection.execute(
            select(sod.operator_task_evidence_bundle_revisions)
        ).mappings().one()
        baseline = uow.connection.execute(
            select(sod.operator_market_prior_baseline_revisions)
        ).mappings().one()
    numbers = tuple(str(number) for number in range(1, 15))
    probabilities = document["probabilities"]
    assert isinstance(probabilities, dict)
    modal_face_by_number = {
        number: max(
            probabilities.get(number, SUPPORT_PRIOR),
            key=lambda face: Decimal(probabilities.get(number, SUPPORT_PRIOR)[face]),
        )
        for number in numbers
    }
    envelope = decision_actions.record_baseline_envelope(
        RecordBaselineEnvelopeRequest(
            task_evidence_bundle_revision_id=(
                bundle["task_evidence_bundle_revision_id"]
            ),
            work_item_id=ZUCAI_WORK_ITEM_ID,
            ticket_kind="sfc",
            capital_cap_minor=200,
            currency="CNY",
            maximum_ticket_count=1,
            offer_constraints=tuple(
                BaselineEnvelopeOfferConstraint(
                    official_match_no=number,
                    market_code="had",
                    allowed_face_bundles=(
                        FaceBundleInput(
                            bundle_code=f"faces-{modal_face_by_number[number]}",
                            face_codes=(modal_face_by_number[number],),
                        ),
                    ),
                    omission_allowed=False,
                )
                for number in numbers
            ),
            structure_templates=(
                BaselineEnvelopeStructureTemplate(
                    kind="zucai_group",
                    structure_code="sfc-14",
                    eligible_official_match_nos=numbers,
                    pass_size=None,
                    required_offer_count=14,
                    maximum_groups=1,
                ),
            ),
            maximum_exhaustive_candidate_count=1,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="26111:sfc-envelope",
            requested_at=base,
            expected_current_revision_no=1,
        )
    )
    assert envelope.status is ActionStatus.COMMITTED
    envelope_id = envelope.result_refs[0].object_id
    policy = result_actions.register_zucai_fixed_prize_policy(
        RegisterZucaiFixedPrizePolicyRequest(
            ticket_kind="sfc",
            policy_version="zucai-fixed-prize-v1",
            actor_id="system:fixed-prize-policy",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="26111:sfc-fixed-prize",
            requested_at=base,
            expected_current_revision_no=0,
        )
    )
    assert policy.status is ActionStatus.COMMITTED

    judgment_ids = []
    for number in numbers:
        prior = probabilities.get(number, SUPPORT_PRIOR)
        assert isinstance(prior, dict)
        face_inputs = tuple(
            FaceProbabilityInput(face_code=face, probability_decimal=value)
            for face, value in prior.items()
        )
        judgment = decision_actions.commit_operator_match_judgment(
            CommitOperatorMatchJudgmentRequest(
                task_evidence_bundle_revision_id=(
                    bundle["task_evidence_bundle_revision_id"]
                ),
                market_prior_baseline_revision_id=(
                    baseline["market_prior_baseline_revision_id"]
                ),
                baseline_envelope_revision_id=envelope_id,
                work_item_id=ZUCAI_WORK_ITEM_ID,
                match_id=f"match-{number}",
                official_offer_revision_id=f"offer-{number}",
                market_definition_id="md-had",
                prior=face_inputs,
                belief=face_inputs,
                factors=(),
                expression_bundles=(
                    FaceBundleInput(
                        bundle_code=f"faces-{modal_face_by_number[number]}",
                        face_codes=(modal_face_by_number[number],),
                    ),
                ),
                rule_ids=("k",),
                evidence_ref_tokens=(f"obs-{number}",),
                falsifier="The registered structural premise no longer holds.",
                rationale="SFC settlement replay judgment.",
                commitment_tier="commit",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"26111:sfc-judgment:{number}",
                requested_at=base + timedelta(minutes=1),
                expected_current_revision_no=1,
            )
        )
        assert judgment.status is ActionStatus.COMMITTED
        judgment_ids.append(
            next(
                ref.object_id
                for ref in judgment.result_refs
                if ref.object_type == "operator_match_judgment_revision"
            )
        )
    prescription = decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=(
                bundle["task_evidence_bundle_revision_id"]
            ),
            market_prior_baseline_revision_id=(
                baseline["market_prior_baseline_revision_id"]
            ),
            baseline_envelope_revision_id=envelope_id,
            work_item_id=ZUCAI_WORK_ITEM_ID,
            judgment_revision_ids=tuple(judgment_ids),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="26111:sfc-prescription",
            requested_at=base + timedelta(minutes=2),
            expected_current_revision_no=1,
        )
    )
    assert prescription.status is ActionStatus.COMMITTED


def _zucai_result_manifest_document(
    *,
    task_snapshot_hash: str,
    first_note_legs,
    losing_leg_count: int = 0,
    include_official_void: bool = True,
    captured_at: str = "2026-09-05T00:00:00+00:00",
) -> tuple[dict[str, object], str | None]:
    suffix = "-zucai"
    document = _checked_in_result_document("zucai-complete.json")
    winning_face_by_match = {
        leg.match_id: leg.selection_code for leg in first_note_legs
    }
    void_match_id = first_note_legs[0].match_id if include_official_void else None
    losing_candidates = tuple(
        leg.match_id
        for leg in first_note_legs
        if leg.match_id != void_match_id
    )
    losing_match_ids = set(losing_candidates[:losing_leg_count])
    scores_by_face = {"3": (2, 1), "1": (1, 1), "0": (0, 1)}
    matches = document["matches"]
    assert isinstance(matches, list) and len(matches) == 14
    for number, match in enumerate(matches, start=1):
        assert isinstance(match, dict)
        match_id = f"match-{number}"
        disposition = "official_void" if match_id == void_match_id else "played_90"
        selected_face = winning_face_by_match.get(match_id, "3")
        result_face = selected_face
        if match_id in losing_match_ids:
            result_face = {"3": "1", "1": "3", "0": "3"}[selected_face]
        score = scores_by_face.get(
            result_face,
            (2, 1),
        )
        sources = [
            {
                "source_kind": kind,
                "receipt_state": "available",
                "artifact_retrieval_id": f"result-retrieval-{kind}{suffix}",
                "captured_at": captured_at,
                "source_disposition": disposition,
                "home_90": None if disposition == "official_void" else score[0],
                "away_90": None if disposition == "official_void" else score[1],
                "invalid_code": None,
            }
            for kind in (
                "api_football",
                "sporttery_game90",
                "okooo_manual",
            )
        ]
        match.update(
            {
                "official_match_no": str(number),
                "canonical_match_id": match_id,
                "sources": sources,
            }
        )
    document.update(
        {
            "business_key": "26111",
            "task_snapshot_token": task_snapshot_hash,
            "slate_revision_token": "slate-26111",
            "result_cutoff_at": captured_at,
            "supersedes_result_set_token": None,
        }
    )
    prize_table = document["zucai_prize_table"]
    assert isinstance(prize_table, dict)
    prize_table.update(
        {
            "issue": "26111",
            "currency": "CNY",
            "published_at": captured_at,
            "official_artifact_retrieval_id": (
                f"result-retrieval-sporttery_game90{suffix}"
            ),
            "supersedes_prize_table_token": None,
        }
    )
    tiers = prize_table["tiers"]
    assert isinstance(tiers, list) and len(tiers) == 3
    payout_by_tier = {
        "sfc_first": (1, 1_000_000),
        "sfc_second": (10, 20_000),
        "renjiu_first": (100, 14_800),
    }
    for tier in tiers:
        assert isinstance(tier, dict)
        winners, payout = payout_by_tier[str(tier["tier_code"])]
        tier["official_winning_note_count"] = winners
        tier["payout_minor_per_winning_note"] = payout
    return document, void_match_id


def _import_zucai_results_for_bound_note(
    *,
    result_actions: OperatorResultActions,
    engine,
    task_snapshot_hash: str,
    first_note_legs,
    losing_leg_count: int = 0,
    include_official_void: bool = True,
):
    captured_at = "2026-09-05T00:00:00+00:00"
    suffix = "-zucai"
    _seed_result_retrievals(
        engine,
        suffix=suffix,
        captured_at=captured_at,
    )
    document, void_match_id = _zucai_result_manifest_document(
        task_snapshot_hash=task_snapshot_hash,
        first_note_legs=first_note_legs,
        losing_leg_count=losing_leg_count,
        include_official_void=include_official_void,
    )
    manifest = ResultEvidenceManifestV1.model_validate(document)
    imported = result_actions.import_result_evidence_set(
        ImportResultEvidenceRequest(
            manifest=manifest,
            importer_version="three-source-result-v1",
            actor_id="system:result-import",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="zucai:settlement:result-import",
            requested_at=AT,
        )
    )
    assert imported.outcome.status is ActionStatus.COMMITTED
    assert imported.result_set is not None
    return imported.result_set, void_match_id


def _correct_result_set(
    actions: OperatorResultActions,
    engine,
    prior,
    *,
    home_90: int,
    away_90: int,
    revision: int,
):
    suffix = f"-correction-{revision}"
    captured_at = f"2026-09-05T0{revision}:00:00+00:00"
    _seed_result_retrievals(
        engine,
        suffix=suffix,
        captured_at=captured_at,
    )
    sources = [
        {
            "source_kind": kind,
            "receipt_state": "available",
            "artifact_retrieval_id": f"result-retrieval-{kind}{suffix}",
            "captured_at": captured_at,
            "source_disposition": "played_90",
            "home_90": home_90,
            "away_90": away_90,
            "invalid_code": None,
        }
        for kind in (
            "api_football",
            "sporttery_game90",
            "okooo_manual",
        )
    ]
    manifest = ResultEvidenceManifestV1.model_validate(
        {
            "schema_version": "result-evidence-v1",
            "lane": "jczq",
            "business_key": "2026-09-04",
            "task_snapshot_token": prior.task_snapshot_hash,
            "slate_revision_token": "slate-1",
            "result_cutoff_at": captured_at,
            "supersedes_result_set_token": prior.result_set_revision_id,
            "matches": [
                {
                    "official_match_no": "001",
                    "canonical_match_id": "match-1",
                    "sources": sources,
                }
            ],
            "zucai_prize_table": None,
        }
    )
    imported = actions.import_result_evidence_set(
        ImportResultEvidenceRequest(
            manifest=manifest,
            importer_version="three-source-result-v1",
            actor_id="system:result-import",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"settlement:result:correction:{revision}",
            requested_at=AT + timedelta(hours=revision),
        )
    )
    assert imported.result_set is not None
    return imported.result_set


def _settle_result_revision(
    actions: OperatorResultActions,
    engine,
    result_set,
    *,
    revision: int,
):
    requested = actions.request_settlement(
        replace(
            _settlement_request(result_set),
            idempotency_key=f"settlement:request:{revision}",
            requested_at=AT + timedelta(hours=revision, minutes=1),
        )
    )
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(hours=revision, minutes=2)).isoformat(),
            lease_expires_at=(
                AT + timedelta(hours=revision, minutes=7)
            ).isoformat(),
            limit=1,
        )
    assert len(jobs) == 1
    return actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=requested.result_refs[0].object_id,
            worker_job_id=jobs[0].worker_job_id,
            lease_owner="settlement-worker",
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
            actor_id="system:settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"settlement:run:{revision}",
            requested_at=AT + timedelta(hours=revision, minutes=2),
        )
    )


def _checked_in_result_document(filename: str) -> dict[str, object]:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "product"
        / "fixtures"
        / "operator"
        / "results"
        / filename
    )
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document
