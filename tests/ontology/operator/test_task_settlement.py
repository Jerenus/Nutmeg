from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings, OperatorRuntimeScope, OperatorSurfaceMode
from nutmeg.interfaces.cli import app as cli_app
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import (
    ApproveOperatorTicketBatchRequest,
    ConfirmTicketPlacementRequest,
    CreateOperatorTicketBatchRequest,
    IssueTicketConfirmationRequest,
    ProtectedTicketActions,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.finance.settlement import (
    crs_result_code,
    grade_market_leg,
    jczq_note_grade,
    jczq_note_payout_minor,
    zucai_note_grade,
    zucai_note_payout_minor,
)
from nutmeg.ontology.operator import result_actions as result_action_module
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FaceProbabilityInput,
    FreezeJudgmentPrescriptionRequest,
    OperatorDecisionActions,
    RecordBaselineEnvelopeRequest,
    RequestCandidateGenerationRequest,
    SelectTicketCandidateRequest,
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
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository.finance import CashAccountRow, FinanceRepository
from nutmeg.ontology.repository.operator_result import OperatorResultRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_contracts import OperatorLane
from nutmeg.product.operator_runtime import OperatorRuntimeConfig
from nutmeg.product.operator_workers import CandidateGenerationWorker, TaskSettlementWorker
from nutmeg.product.wiring import build_product_services
from tests.ontology.operator.test_confirmation_cas import (
    _attestation,
    _issue,
    _protected,
)
from tests.ontology.operator.test_judgment_actions import (
    AT as JUDGMENT_AT,
)
from tests.ontology.operator.test_judgment_actions import (
    WORK_ITEM_ID as JCZQ_WORK_ITEM_ID,
)
from tests.ontology.operator.test_judgment_actions import (
    _baseline_request,
    _judgment_request,
)
from tests.ontology.operator.test_judgment_actions import (
    _fixture as _judgment_fixture,
)
from tests.ontology.operator.test_no_ticket_actions import (
    AT as PLACEMENT_AT,
)
from tests.ontology.operator.test_no_ticket_actions import (
    _artifact_fixture,
    _clean_candidate_audit,
)
from tests.ontology.operator.test_result_ingest import (
    AT,
    _import_request,
    _parsed_manifest,
    _setup_actions,
)
from tests.product.operator_v2.test_candidate_replay import (
    AT as ZUCAI_AT,
)
from tests.product.operator_v2.test_candidate_replay import (
    SUPPORT_PRIOR,
    _fixture_document,
    _prepare_decision_lineage,
)
from tests.product.operator_v2.test_candidate_replay import (
    TASK_KEY as ZUCAI_TASK_KEY,
)
from tests.product.operator_v2.test_candidate_replay import (
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


def _place_generated_zucai_ticket(
    tmp_path: Path,
    *,
    ticket_kind: str = "renjiu",
    complete_market_baseline_job: bool = False,
):
    engine, action_service, decision_actions, result_actions, document = (
        _prepare_decision_lineage(tmp_path)
    )
    if ticket_kind == "sfc":
        _replace_with_sfc_decision_lineage(
            engine=engine,
            decision_actions=decision_actions,
            result_actions=result_actions,
            document=document,
        )
    with OntologyUnitOfWork(engine) as uow:
        bundle = uow.connection.execute(
            select(sod.operator_task_evidence_bundle_revisions)
        ).mappings().one()
        baseline = uow.connection.execute(
            select(sod.operator_market_prior_baseline_revisions)
        ).mappings().one()
        envelope = uow.connection.execute(
            select(sod.operator_baseline_envelope_revisions)
            .order_by(sod.operator_baseline_envelope_revisions.c.revision_no.desc())
            .limit(1)
        ).mappings().one()
        prescription = uow.connection.execute(
            select(sod.operator_judgment_prescription_revisions)
            .order_by(
                sod.operator_judgment_prescription_revisions.c.revision_no.desc()
            )
            .limit(1)
        ).mappings().one()
        policy = uow.operator_result.current_fixed_prize_policy(ticket_kind)
        assert policy is not None
        uow.finance.ensure_account(
            CashAccountRow("acct-zucai", "zucai", "CNY", "active")
        )

    generation = decision_actions.request_candidate_generation(
        RequestCandidateGenerationRequest(
            task_evidence_bundle_revision_id=(
                bundle["task_evidence_bundle_revision_id"]
            ),
            market_prior_baseline_revision_id=(
                baseline["market_prior_baseline_revision_id"]
            ),
            baseline_envelope_revision_id=(
                envelope["baseline_envelope_revision_id"]
            ),
            judgment_prescription_revision_id=(
                prescription["judgment_prescription_revision_id"]
            ),
            work_item_id=ZUCAI_WORK_ITEM_ID,
            fixed_prize_policy_revision_id=(
                policy.fixed_prize_policy_revision_id
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:{ticket_kind}:settlement:candidate-request",
            requested_at=ZUCAI_AT + timedelta(minutes=10),
            expected_current_revision_no=0,
        )
    )
    assert generation.status is ActionStatus.COMMITTED
    generated = CandidateGenerationWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id=f"zucai-{ticket_kind}-settlement-candidate-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=ZUCAI_AT + timedelta(minutes=11))
    assert len(generated) == 1
    assert generated[0].status is ActionStatus.COMMITTED

    with OntologyUnitOfWork(engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id=ZUCAI_TASK_KEY,
            work_item_id=ZUCAI_WORK_ITEM_ID,
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        candidates = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )
        candidate = next(item for item in candidates if item.rank == 1)
    selected = decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason=f"Select the persisted {ticket_kind} settlement replay candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:{ticket_kind}:settlement:candidate-select",
            requested_at=ZUCAI_AT + timedelta(minutes=12),
            expected_current_revision_no=0,
        )
    )
    assert selected.status is ActionStatus.COMMITTED

    protected = ProtectedTicketActions(
        action_service,
        ContentAddressedArtifactStore(tmp_path / f"zucai-{ticket_kind}-ticket-artifacts"),
        operator_decisions=decision_actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )
    created = protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selected.result_refs[0].object_id,
            account_id="acct-zucai",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:{ticket_kind}:settlement:create-batch",
            requested_at=ZUCAI_AT + timedelta(minutes=13),
        )
    )
    batch_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:{ticket_kind}:settlement:approve-batch",
            requested_at=ZUCAI_AT + timedelta(minutes=14),
        )
    )
    artifact_ids = tuple(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    assert len(artifact_ids) == 1
    fixture = SimpleNamespace(
        action_service=action_service,
        actions=decision_actions,
        artifact_id=artifact_ids[0],
    )
    issued = _issue(
        protected,
        fixture,
        key=f"zucai:{ticket_kind}:settlement:issue-confirmation",
    )
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_ids[0])
        head = uow.tickets.confirmation_challenge_head(artifact_ids[0])
    assert artifact is not None
    assert head is not None
    placed = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=artifact_ids[0],
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference=f"telegram:zucai-{ticket_kind}-settlement-replay",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type=(
                "application/vnd.nutmeg.telegram-attestation+json"
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:{ticket_kind}:settlement:confirm-placement",
            requested_at=PLACEMENT_AT + timedelta(minutes=3),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id=f"callback-zucai-{ticket_kind}-settlement-replay",
                at=PLACEMENT_AT + timedelta(minutes=3),
            ),
        )
    )
    assert placed.status is ActionStatus.COMMITTED
    if complete_market_baseline_job:
        _complete_pending_fixture_baseline_job(
            engine,
            work_item_id=ZUCAI_WORK_ITEM_ID,
        )
    with OntologyUnitOfWork(engine) as uow:
        ticket = uow.connection.execute(select(sf.tickets)).mappings().one()
        notes = uow.operator_result.ticket_notes(ticket["ticket_id"])
        assert notes
        first_note_legs = uow.operator_result.ticket_note_legs(
            notes[0].ticket_note_id
        )
    return (
        result_actions,
        action_service,
        engine,
        str(bundle["task_snapshot_hash"]),
        ticket,
        notes,
        first_note_legs,
    )


def _place_current_zucai_candidate(
    *,
    tmp_path: Path,
    engine,
    action_service: ActionService,
    decision_actions: OperatorDecisionActions,
    candidate_rank: int,
    expected_selection_revision: int,
    requested_at: datetime,
    key: str,
) -> str:
    with OntologyUnitOfWork(engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id=ZUCAI_TASK_KEY,
            work_item_id=ZUCAI_WORK_ITEM_ID,
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        candidate = next(
            item
            for item in uow.operator_result.candidates_for_set(
                candidate_set.candidate_set_revision_id
            )
            if item.rank == candidate_rank
        )
    selected = decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason=f"Select public Zucai settlement candidate rank {candidate_rank}.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"{key}:candidate-select",
            requested_at=requested_at,
            expected_current_revision_no=expected_selection_revision,
        )
    )
    assert selected.status is ActionStatus.COMMITTED
    protected = ProtectedTicketActions(
        action_service,
        ContentAddressedArtifactStore(
            tmp_path / f"{key.replace(':', '-')}-ticket-artifacts"
        ),
        operator_decisions=decision_actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )
    created = protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selected.result_refs[0].object_id,
            account_id="acct-zucai",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"{key}:create-batch",
            requested_at=requested_at + timedelta(seconds=1),
        )
    )
    batch_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"{key}:approve-batch",
            requested_at=requested_at + timedelta(seconds=2),
        )
    )
    artifact_ids = tuple(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    assert len(artifact_ids) == 1
    artifact_id = artifact_ids[0]
    issued = protected.issue_ticket_confirmation(
        IssueTicketConfirmationRequest(
            ticket_artifact_id=artifact_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"{key}:issue-confirmation",
            requested_at=requested_at + timedelta(seconds=3),
        )
    )
    assert issued.confirmation_id is not None and issued.nonce is not None
    with OntologyUnitOfWork(engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_id)
        head = uow.tickets.confirmation_challenge_head(artifact_id)
    assert artifact is not None and head is not None
    fixture = SimpleNamespace(
        action_service=action_service,
        actions=decision_actions,
        artifact_id=artifact_id,
    )
    placed = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=artifact_id,
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference=f"telegram:{key}",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type=(
                "application/vnd.nutmeg.telegram-attestation+json"
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"{key}:confirm-placement",
            requested_at=requested_at + timedelta(seconds=4),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id=f"callback-{key}",
                at=requested_at + timedelta(seconds=4),
            ),
        )
    )
    assert placed.status is ActionStatus.COMMITTED
    return next(
        ref.object_id
        for ref in placed.result_refs
        if ref.object_type == "ticket"
    )


def _place_public_zucai_ticket_set(
    tmp_path: Path,
    *,
    complete_market_baseline_job: bool,
):
    (
        result_actions,
        action_service,
        engine,
        task_snapshot_hash,
        first_ticket,
        _first_notes,
        _first_note_legs,
    ) = _place_generated_zucai_ticket(
        tmp_path,
        complete_market_baseline_job=complete_market_baseline_job,
    )
    assert first_ticket["ticket_kind"] == "renjiu"
    decision_actions = OperatorDecisionActions(action_service)
    _place_current_zucai_candidate(
        tmp_path=tmp_path,
        engine=engine,
        action_service=action_service,
        decision_actions=decision_actions,
        candidate_rank=2,
        expected_selection_revision=1,
        requested_at=PLACEMENT_AT + timedelta(minutes=4),
        key="public-zucai-renjiu-rank-2",
    )

    sfc_base = PLACEMENT_AT + timedelta(minutes=10)
    _replace_with_sfc_decision_lineage(
        engine=engine,
        decision_actions=decision_actions,
        result_actions=result_actions,
        document=_fixture_document(),
        requested_at_base=sfc_base,
    )
    with OntologyUnitOfWork(engine) as uow:
        bundle = uow.connection.execute(
            select(sod.operator_task_evidence_bundle_revisions)
        ).mappings().one()
        baseline = uow.connection.execute(
            select(sod.operator_market_prior_baseline_revisions)
        ).mappings().one()
        envelope = uow.connection.execute(
            select(sod.operator_baseline_envelope_revisions)
            .order_by(sod.operator_baseline_envelope_revisions.c.revision_no.desc())
            .limit(1)
        ).mappings().one()
        prescription = uow.connection.execute(
            select(sod.operator_judgment_prescription_revisions)
            .order_by(
                sod.operator_judgment_prescription_revisions.c.revision_no.desc()
            )
            .limit(1)
        ).mappings().one()
        policy = uow.operator_result.current_fixed_prize_policy("sfc")
        assert policy is not None
    generation = decision_actions.request_candidate_generation(
        RequestCandidateGenerationRequest(
            task_evidence_bundle_revision_id=(
                bundle["task_evidence_bundle_revision_id"]
            ),
            market_prior_baseline_revision_id=(
                baseline["market_prior_baseline_revision_id"]
            ),
            baseline_envelope_revision_id=(
                envelope["baseline_envelope_revision_id"]
            ),
            judgment_prescription_revision_id=(
                prescription["judgment_prescription_revision_id"]
            ),
            work_item_id=ZUCAI_WORK_ITEM_ID,
            fixed_prize_policy_revision_id=policy.fixed_prize_policy_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:zucai:sfc:candidate-request",
            requested_at=sfc_base + timedelta(minutes=3),
            expected_current_revision_no=1,
        )
    )
    assert generation.status is ActionStatus.COMMITTED
    generated = CandidateGenerationWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id="public-zucai-sfc-candidate-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=sfc_base + timedelta(minutes=4))
    assert len(generated) == 1
    sfc_ticket_id = _place_current_zucai_candidate(
        tmp_path=tmp_path,
        engine=engine,
        action_service=action_service,
        decision_actions=decision_actions,
        candidate_rank=1,
        expected_selection_revision=2,
        requested_at=sfc_base + timedelta(minutes=5),
        key="public-zucai-sfc",
    )
    with OntologyUnitOfWork(engine) as uow:
        sfc_notes = uow.operator_result.ticket_notes(sfc_ticket_id)
        assert len(sfc_notes) == 1
        sfc_note_legs = uow.operator_result.ticket_note_legs(
            sfc_notes[0].ticket_note_id
        )
        assert len(sfc_note_legs) == 14
    return engine, task_snapshot_hash, sfc_note_legs


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


def _place_jczq_ticket(
    tmp_path: Path,
    *,
    result_captured_at: str = "2026-09-05T00:00:00+00:00",
    complete_market_baseline_job: bool = False,
):
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="settlement:placement:issue")
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert artifact is not None
    assert head is not None
    placed = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=fixture.artifact_id,
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference="telegram:settlement-fixture",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type=(
                "application/vnd.nutmeg.telegram-attestation+json"
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="settlement:placement:confirm",
            requested_at=PLACEMENT_AT + timedelta(minutes=3),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id="callback-settlement-fixture",
                at=PLACEMENT_AT + timedelta(minutes=3),
            ),
        )
    )
    assert placed.status is ActionStatus.COMMITTED
    if complete_market_baseline_job:
        _complete_pending_fixture_baseline_job(
            fixture.engine,
            work_item_id=fixture.context.work_item_id,
        )
    _seed_result_retrievals(fixture.engine, captured_at=result_captured_at)
    return fixture


def _place_multimarket_jczq_ticket(
    tmp_path: Path,
    *,
    result_captured_at: str,
    complete_market_baseline_job: bool,
):
    judgment = _judgment_fixture(
        tmp_path,
        match_count=2,
        market_definition_id="md-hhad",
        settlement_parameter_decimal="-1.000000000000",
    )
    with OntologyUnitOfWork(judgment.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
    baseline = judgment.decision_actions.freeze_market_prior_baseline(
        _baseline_request(judgment)
    )
    assert baseline.status is ActionStatus.COMMITTED
    baseline_id = baseline.result_refs[0].object_id
    envelope = judgment.decision_actions.record_baseline_envelope(
        RecordBaselineEnvelopeRequest(
            task_evidence_bundle_revision_id=judgment.task_bundle_revision_id,
            work_item_id=JCZQ_WORK_ITEM_ID,
            ticket_kind="jczq_pass",
            capital_cap_minor=200,
            currency="CNY",
            maximum_ticket_count=1,
            offer_constraints=(
                BaselineEnvelopeOfferConstraint(
                    official_match_no="001",
                    market_code="hhad",
                    allowed_face_bundles=(
                        FaceBundleInput(bundle_code="home", face_codes=("3",)),
                    ),
                    omission_allowed=False,
                ),
                BaselineEnvelopeOfferConstraint(
                    official_match_no="002",
                    market_code="had",
                    allowed_face_bundles=(
                        FaceBundleInput(bundle_code="home", face_codes=("3",)),
                    ),
                    omission_allowed=False,
                ),
            ),
            structure_templates=(
                BaselineEnvelopeStructureTemplate(
                    kind="jczq_pass",
                    structure_code="2x1",
                    eligible_official_match_nos=("001", "002"),
                    pass_size=2,
                    required_offer_count=2,
                    maximum_groups=1,
                ),
            ),
            maximum_exhaustive_candidate_count=1,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:envelope",
            requested_at=JUDGMENT_AT + timedelta(seconds=3),
            expected_current_revision_no=0,
        )
    )
    assert envelope.status is ActionStatus.COMMITTED
    envelope_id = envelope.result_refs[0].object_id
    judgments = []
    for number, match_id, offer_id, market_id in (
        ("001", "match-1", "offer-revision-1", "md-hhad"),
        ("002", "match-2", "offer-revision-2", "md-had"),
    ):
        request = _judgment_request(
            judgment,
            baseline_id,
            envelope_id,
            market_definition_id=market_id,
            match_id=match_id,
            official_offer_revision_id=offer_id,
            key=f"public:jczq:multimarket:judgment:{number}",
        )
        committed = judgment.decision_actions.commit_operator_match_judgment(
            replace(
                request,
                expression_bundles=(
                    FaceBundleInput(bundle_code="home", face_codes=("3",)),
                ),
            )
        )
        assert committed.status is ActionStatus.COMMITTED
        judgments.append(
            next(
                ref.object_id
                for ref in committed.result_refs
                if ref.object_type == "operator_match_judgment_revision"
            )
        )
    prescription = judgment.decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=judgment.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=JCZQ_WORK_ITEM_ID,
            judgment_revision_ids=tuple(judgments),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:prescription",
            requested_at=JUDGMENT_AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    assert prescription.status is ActionStatus.COMMITTED
    generation = judgment.decision_actions.request_candidate_generation(
        RequestCandidateGenerationRequest(
            task_evidence_bundle_revision_id=judgment.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            judgment_prescription_revision_id=prescription.result_refs[0].object_id,
            work_item_id=JCZQ_WORK_ITEM_ID,
            fixed_prize_policy_revision_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:candidate-request",
            requested_at=JUDGMENT_AT + timedelta(seconds=6),
            expected_current_revision_no=0,
        )
    )
    generated = CandidateGenerationWorker(
        action_service=judgment.action_service,
        result_actions=OperatorResultActions(judgment.action_service),
        worker_id="public-jczq-multimarket-candidate-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=JUDGMENT_AT + timedelta(seconds=7))
    assert generation.status is ActionStatus.COMMITTED
    assert len(generated) == 1
    with OntologyUnitOfWork(judgment.engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id="jczq:2026-09-04",
            work_item_id=JCZQ_WORK_ITEM_ID,
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        candidates = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )
        candidate = next(item for item in candidates if item.rank == 1)
    selected = judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Select the two-match public settlement replay candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:candidate-select",
            requested_at=JUDGMENT_AT + timedelta(seconds=9),
            expected_current_revision_no=0,
        )
    )
    protected = ProtectedTicketActions(
        judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "multimarket-ticket-artifacts"),
        operator_decisions=judgment.decision_actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )
    created = protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selected.result_refs[0].object_id,
            account_id="acct-jczq",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:create-batch",
            requested_at=PLACEMENT_AT + timedelta(seconds=2),
        )
    )
    batch_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:approve-batch",
            requested_at=PLACEMENT_AT + timedelta(seconds=3),
        )
    )
    artifact_ids = tuple(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    assert len(artifact_ids) == 1
    fixture = SimpleNamespace(
        engine=judgment.engine,
        action_service=judgment.action_service,
        actions=judgment.decision_actions,
        artifact_id=artifact_ids[0],
        context=SimpleNamespace(task_snapshot_hash="c" * 64),
    )
    issued = _issue(protected, fixture, key="public:jczq:multimarket:issue")
    assert issued.confirmation_id is not None and issued.nonce is not None
    with OntologyUnitOfWork(judgment.engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_ids[0])
        head = uow.tickets.confirmation_challenge_head(artifact_ids[0])
    assert artifact is not None and head is not None
    placed = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=artifact_ids[0],
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference="telegram:jczq-multimarket-public-replay",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type=(
                "application/vnd.nutmeg.telegram-attestation+json"
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="public:jczq:multimarket:confirm-placement",
            requested_at=PLACEMENT_AT + timedelta(minutes=3),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id="callback-jczq-multimarket-public-replay",
                at=PLACEMENT_AT + timedelta(minutes=3),
            ),
        )
    )
    assert placed.status is ActionStatus.COMMITTED
    if complete_market_baseline_job:
        _complete_pending_fixture_baseline_job(
            judgment.engine,
            work_item_id=JCZQ_WORK_ITEM_ID,
        )
    _seed_result_retrievals(
        judgment.engine,
        captured_at=result_captured_at,
    )
    return fixture


def _placed_result_set(tmp_path: Path):
    fixture = _place_jczq_ticket(tmp_path)
    source_rows = [
        {
            "source_kind": kind,
            "receipt_state": "available",
            "artifact_retrieval_id": f"result-retrieval-{kind}",
            "captured_at": "2026-09-05T00:00:00+00:00",
            "source_disposition": "played_90",
            "home_90": 2,
            "away_90": 1,
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
            "task_snapshot_token": fixture.context.task_snapshot_hash,
            "slate_revision_token": "slate-1",
            "result_cutoff_at": "2026-09-05T00:00:00+00:00",
            "supersedes_result_set_token": None,
            "matches": [
                {
                    "official_match_no": "001",
                    "canonical_match_id": "match-1",
                    "sources": source_rows,
                }
            ],
            "zucai_prize_table": None,
        }
    )
    actions = OperatorResultActions(fixture.action_service)
    imported = actions.import_result_evidence_set(
        ImportResultEvidenceRequest(
            manifest=manifest,
            importer_version="three-source-result-v1",
            actor_id="system:result-import",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="settlement:result:import",
            requested_at=AT,
        )
    )
    assert imported.result_set is not None
    return actions, fixture.engine, imported.result_set


def test_placed_jczq_ticket_settles_notes_legs_and_signed_payout(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    settled = actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=requested.result_refs[0].object_id,
            worker_job_id=jobs[0].worker_job_id,
            lease_owner="settlement-worker",
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
            actor_id="system:settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="settlement:placed:run",
            requested_at=AT + timedelta(minutes=2),
        )
    )

    assert settled.status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        ticket = connection.execute(
            select(sor.operator_ticket_settlement_revisions)
        ).mappings().one()
        note = connection.execute(
            select(sor.operator_ticket_note_settlements)
        ).mappings().one()
        leg = connection.execute(
            select(sor.operator_ticket_note_leg_settlements)
        ).mappings().one()
        cash = connection.execute(
            select(sf.cash_transactions).order_by(sf.cash_transactions.c.occurred_at)
        ).mappings().all()
        eligibility = connection.execute(
            select(sor.operator_review_eligibility_facts).where(
                sor.operator_review_eligibility_facts.c.terminal_trigger
                == "settlement"
            )
        ).mappings().one()
        review_job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.job_kind == "review_materialization",
                sod.operator_worker_jobs.c.source_object_id
                == eligibility["review_eligibility_fact_id"],
            )
        ).mappings().one()
    assert run["settlement_state"] == "settled"
    assert (
        run["requested_ticket_count"],
        run["eligible_ticket_count"],
        run["settled_ticket_count"],
        run["persisted_note_grade_count"],
        run["persisted_leg_grade_count"],
        run["persisted_cash_count"],
    ) == (1, 1, 1, 1, 1, 1)
    assert ticket["gross_payout_minor"] == 500
    assert note["note_grade"] == "won"
    assert note["payout_minor"] == 500
    assert leg["market_result_code"] == "home"
    assert leg["leg_grade"] == "won"
    assert [row["amount_minor"] for row in cash] == [-200, 500]
    assert sum(row["amount_minor"] for row in cash) == 300
    assert eligibility["action_id"] == settled.action_id
    assert eligibility["settlement_run_id"] == run["settlement_run_id"]
    assert eligibility["no_ticket_revision_id"] is None
    assert eligibility["artifact_terminal_receipt_id"] is None
    assert eligibility["market_prior_baseline_revision_id"] is not None
    assert eligibility["review_kind"] == "forecast_truth"
    assert eligibility["readiness_condition"] == "outcomes_required"
    assert review_job["state"] == "queued"


def test_placed_renjiu_ticket_settles_only_nine_bound_legs_and_counts_void(
    tmp_path: Path,
) -> None:
    (
        result_actions,
        action_service,
        engine,
        task_snapshot_hash,
        ticket,
        placed_notes,
        first_note_legs,
    ) = _place_generated_zucai_ticket(tmp_path)
    assert ticket["ticket_kind"] == "renjiu"
    assert all(
        len(
            tuple(
                leg
                for leg in first_note_legs
                if leg.ticket_note_id == placed_notes[0].ticket_note_id
            )
        )
        == 9
        for _note in (placed_notes[0],)
    )
    result_set, void_match_id = _import_zucai_results_for_bound_note(
        result_actions=result_actions,
        engine=engine,
        task_snapshot_hash=task_snapshot_hash,
        first_note_legs=first_note_legs,
    )
    requested = result_actions.request_settlement(
        RequestSettlementRequest(
            result_set_revision_id=result_set.result_set_revision_id,
            expected_task_snapshot_hash=task_snapshot_hash,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="zucai:settlement:request",
            requested_at=AT + timedelta(minutes=1),
        )
    )
    completed = TaskSettlementWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id="zucai-settlement-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(minutes=2))

    assert requested.status is ActionStatus.COMMITTED
    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        settlement = connection.execute(
            select(sor.operator_ticket_settlement_revisions)
        ).mappings().one()
        note_rows = connection.execute(
            select(sor.operator_ticket_note_settlements)
        ).mappings().all()
        leg_rows = connection.execute(
            select(sor.operator_ticket_note_leg_settlements)
        ).mappings().all()
        void_outcome_id = connection.scalar(
            select(sor.operator_outcome_revisions.c.outcome_revision_id).where(
                sor.operator_outcome_revisions.c.match_id == void_match_id
            )
        )
        cash_rows = connection.execute(
            select(sor.operator_settlement_cash_links)
        ).mappings().all()
        eligibility_count = connection.scalar(
            select(func.count()).select_from(
                sor.operator_review_eligibility_facts
            )
        )

    assert run["settlement_state"] == "settled"
    assert run["persisted_note_grade_count"] == len(placed_notes)
    assert run["persisted_leg_grade_count"] == len(placed_notes) * 9
    assert len(note_rows) == len(placed_notes)
    assert len(leg_rows) == len(placed_notes) * 9
    assert all(row["void_leg_count"] == 1 for row in note_rows)
    assert all(row["note_grade"] in {"won", "lost"} for row in note_rows)
    assert any(row["note_grade"] == "won" for row in note_rows)
    assert all(
        row["prize_tier_code"] == "renjiu_first"
        for row in note_rows
        if row["note_grade"] == "won"
    )
    assert all(
        row["prize_tier_code"] is None
        for row in note_rows
        if row["note_grade"] == "lost"
    )
    assert sum(row["outcome_revision_id"] == void_outcome_id for row in leg_rows) == len(
        placed_notes
    )
    assert all(
        row["leg_grade"] == "void"
        for row in leg_rows
        if row["outcome_revision_id"] == void_outcome_id
    )
    expected_payout = (
        sum(row["winning_unit_count"] for row in note_rows) * 14_800
    )
    assert settlement["gross_payout_minor"] == expected_payout
    assert [row["amount_minor"] for row in cash_rows] == [expected_payout]
    assert eligibility_count == 1


@pytest.mark.parametrize(
    ("losing_leg_count", "expected_correct", "expected_tier", "expected_payout"),
    (
        (0, 14, "sfc_first", 1_000_000),
        (1, 13, "sfc_second", 20_000),
        (2, 12, None, 0),
    ),
)
def test_placed_sfc_ticket_uses_exact_first_second_or_lost_tier(
    tmp_path: Path,
    losing_leg_count: int,
    expected_correct: int,
    expected_tier: str | None,
    expected_payout: int,
) -> None:
    (
        result_actions,
        action_service,
        engine,
        task_snapshot_hash,
        ticket,
        placed_notes,
        first_note_legs,
    ) = _place_generated_zucai_ticket(tmp_path, ticket_kind="sfc")
    assert ticket["ticket_kind"] == "sfc"
    assert len(placed_notes) == 1
    assert len(first_note_legs) == 14
    result_set, void_match_id = _import_zucai_results_for_bound_note(
        result_actions=result_actions,
        engine=engine,
        task_snapshot_hash=task_snapshot_hash,
        first_note_legs=first_note_legs,
        losing_leg_count=losing_leg_count,
    )
    requested = result_actions.request_settlement(
        RequestSettlementRequest(
            result_set_revision_id=result_set.result_set_revision_id,
            expected_task_snapshot_hash=task_snapshot_hash,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:sfc:settlement:request:{losing_leg_count}",
            requested_at=AT + timedelta(minutes=1),
        )
    )
    completed = TaskSettlementWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id="zucai-sfc-settlement-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(minutes=2))

    assert requested.status is ActionStatus.COMMITTED
    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        settlement = connection.execute(
            select(sor.operator_ticket_settlement_revisions)
        ).mappings().one()
        note = connection.execute(
            select(sor.operator_ticket_note_settlements)
        ).mappings().one()
        legs = connection.execute(
            select(sor.operator_ticket_note_leg_settlements)
        ).mappings().all()
        cash = connection.execute(
            select(sor.operator_settlement_cash_links)
        ).mappings().all()
        eligibility_count = connection.scalar(
            select(func.count()).select_from(sor.operator_review_eligibility_facts)
        )

    assert run["settlement_state"] == "settled"
    assert run["persisted_note_grade_count"] == 1
    assert run["persisted_leg_grade_count"] == 14
    assert note["correct_leg_count"] == expected_correct
    assert note["void_leg_count"] == 1
    assert note["note_grade"] == ("won" if expected_tier is not None else "lost")
    assert note["prize_tier_code"] == expected_tier
    assert note["payout_minor"] == expected_payout
    assert settlement["gross_payout_minor"] == expected_payout
    assert len(legs) == 14
    assert sum(row["result_disposition"] == "official_void" for row in legs) == 1
    assert void_match_id is not None
    assert [row["amount_minor"] for row in cash] == (
        [] if expected_payout == 0 else [expected_payout]
    )
    assert eligibility_count == 1


@pytest.mark.parametrize(
    "mismatch",
    ("policy", "currency", "unit_stake", "tier"),
)
def test_zucai_persisted_invariant_mismatch_aborts_the_complete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    (
        result_actions,
        action_service,
        engine,
        task_snapshot_hash,
        _ticket,
        _placed_notes,
        first_note_legs,
    ) = _place_generated_zucai_ticket(tmp_path, ticket_kind="sfc")
    result_set, _void_match_id = _import_zucai_results_for_bound_note(
        result_actions=result_actions,
        engine=engine,
        task_snapshot_hash=task_snapshot_hash,
        first_note_legs=first_note_legs,
    )

    if mismatch in {"policy", "unit_stake"}:
        original_policy = OperatorResultRepository.fixed_prize_policy_revision

        def drifted_policy(repository, revision_id):
            policy = original_policy(repository, revision_id)
            assert policy is not None
            return replace(
                policy,
                **(
                    {"ticket_kind": "renjiu"}
                    if mismatch == "policy"
                    else {"standard_unit_stake_minor": 400}
                ),
            )

        monkeypatch.setattr(
            OperatorResultRepository,
            "fixed_prize_policy_revision",
            drifted_policy,
        )
    elif mismatch == "currency":
        original_notes = OperatorResultRepository.ticket_notes

        def drifted_notes(repository, ticket_id):
            notes = original_notes(repository, ticket_id)
            return tuple(replace(note, currency="USD") for note in notes)

        monkeypatch.setattr(
            OperatorResultRepository,
            "ticket_notes",
            drifted_notes,
        )
    else:
        original_tiers = OperatorResultRepository.fixed_prize_policy_tiers

        def incomplete_tiers(repository, revision_id):
            return original_tiers(repository, revision_id)[:-1]

        monkeypatch.setattr(
            OperatorResultRepository,
            "fixed_prize_policy_tiers",
            incomplete_tiers,
        )

    requested = result_actions.request_settlement(
        RequestSettlementRequest(
            result_set_revision_id=result_set.result_set_revision_id,
            expected_task_snapshot_hash=task_snapshot_hash,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zucai:sfc:invariant-request:{mismatch}",
            requested_at=AT + timedelta(minutes=1),
        )
    )
    completed = TaskSettlementWorker(
        action_service=action_service,
        result_actions=result_actions,
        worker_id="zucai-sfc-invariant-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(minutes=2))

    assert requested.status is ActionStatus.COMMITTED
    assert completed == ()
    with engine.connect() as connection:
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.job_kind == "task_settlement"
            )
        ).mappings().one()
        business_counts = tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_task_settlement_runs,
                sor.operator_task_settlement_skips,
                sor.operator_ticket_settlement_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
                sor.operator_review_eligibility_facts,
            )
        )
        non_stake_cash = connection.scalar(
            select(func.count())
            .select_from(sf.cash_transactions)
            .where(sf.cash_transactions.c.kind != "stake")
        )
    assert (job["state"], job["last_error_code"]) == (
        "failed",
        "invariant_failure",
    )
    assert business_counts == (0, 0, 0, 0, 0, 0, 0)
    assert non_stake_cash == 0


def test_settlement_review_eligibility_requires_one_exact_typed_source(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    settled = _settle_result_revision(
        actions,
        engine,
        result_set,
        revision=0,
    )
    assert settled.status is ActionStatus.COMMITTED

    with engine.connect() as connection:
        eligibility = dict(
            connection.execute(
                select(sor.operator_review_eligibility_facts)
            ).mappings().one()
        )
        terminal_id = connection.scalar(
            select(
                st.operator_artifact_terminal_receipts.c.artifact_terminal_receipt_id
            )
        )
        wrong_action_id = connection.scalar(
            select(schema.actions.c.action_id).where(
                schema.actions.c.action_type == "request_settlement"
            )
        )
    assert terminal_id is not None
    assert wrong_action_id is not None

    mixed_source = {
        **eligibility,
        "review_eligibility_fact_id": "eligibility:mixed-source",
        "fact_index": eligibility["fact_index"] + 1,
        "artifact_terminal_receipt_id": terminal_id,
        "content_hash": "1" * 64,
    }
    with pytest.raises(IntegrityError, match="ck_operator_review_eligibility_source"):
        with engine.begin() as connection:
            connection.execute(
                insert(sor.operator_review_eligibility_facts).values(**mixed_source)
            )

    wrong_action = {
        **eligibility,
        "review_eligibility_fact_id": "eligibility:wrong-action",
        "action_id": wrong_action_id,
        "fact_index": eligibility["fact_index"] + 1,
        "content_hash": "2" * 64,
    }
    with pytest.raises(IntegrityError, match="exact creating Action and terminal source"):
        with engine.begin() as connection:
            connection.execute(
                insert(sor.operator_review_eligibility_facts).values(**wrong_action)
            )

    duplicate_settlement_source = {
        **eligibility,
        "review_eligibility_fact_id": "eligibility:duplicate-settlement-source",
        "fact_index": eligibility["fact_index"] + 1,
        "content_hash": "3" * 64,
    }
    with pytest.raises(IntegrityError, match="settlement_run_id"):
        with engine.begin() as connection:
            connection.execute(
                insert(sor.operator_review_eligibility_facts).values(
                    **duplicate_settlement_source
                )
            )


@pytest.mark.parametrize(
    "reason_code",
    (
        "result_not_ready",
        "prize_not_ready",
        "placement_integrity_blocked",
    ),
)
def test_unready_or_integrity_blocked_ticket_records_only_closed_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    if reason_code == "result_not_ready":
        monkeypatch.setattr(
            OperatorResultRepository,
            "outcomes_for_result_set",
            lambda _repository, _result_set_id: (),
        )
    elif reason_code == "placement_integrity_blocked":
        monkeypatch.setattr(
            OperatorResultRepository,
            "placement_cash_link",
            lambda _repository, _ticket_id: None,
        )
    else:
        original_ticket = FinanceRepository.ticket

        def fixed_prize_ticket(repository, ticket_id):
            ticket = original_ticket(repository, ticket_id)
            assert ticket is not None
            return replace(
                ticket,
                ticket_kind="sfc",
                fixed_prize_policy_revision_id="policy-not-yet-relevant",
            )

        monkeypatch.setattr(FinanceRepository, "ticket", fixed_prize_ticket)

    requested = actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    settled = actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=requested.result_refs[0].object_id,
            worker_job_id=jobs[0].worker_job_id,
            lease_owner="settlement-worker",
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
            actor_id="system:settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"settlement:skip:{reason_code}",
            requested_at=AT + timedelta(minutes=2),
        )
    )

    assert settled.status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        skip = connection.execute(
            select(sor.operator_task_settlement_skips)
        ).mappings().one()
        child_counts = tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_ticket_settlement_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
                sor.operator_review_eligibility_facts,
            )
        )
    assert (
        run["requested_ticket_count"],
        run["eligible_ticket_count"],
        run["skipped_ticket_count"],
        run["settled_ticket_count"],
    ) == (1, 0, 1, 0)
    assert skip["reason_code"] == reason_code
    assert child_counts == (0, 0, 0, 0, 0)


def test_partially_settled_task_still_appends_one_settlement_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    original_ticket_ids = OperatorResultRepository.placed_ticket_ids_for_work_item
    with engine.begin() as connection:
        broken_ticket = dict(
            connection.execute(select(sf.tickets)).mappings().one()
        )
        broken_ticket["ticket_id"] = "ticket-broken"
        connection.execute(insert(sf.tickets).values(**broken_ticket))

    def one_placed_and_one_broken(repository, work_item_id):
        return original_ticket_ids(repository, work_item_id) + ("ticket-broken",)

    monkeypatch.setattr(
        OperatorResultRepository,
        "placed_ticket_ids_for_work_item",
        one_placed_and_one_broken,
    )
    requested = actions.request_settlement(_settlement_request(result_set))
    completed = TaskSettlementWorker(
        action_service=ActionService(lambda: OntologyUnitOfWork(engine)),
        result_actions=actions,
        worker_id="settlement-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(minutes=2))

    assert requested.status is ActionStatus.COMMITTED
    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        skip = connection.execute(
            select(sor.operator_task_settlement_skips)
        ).mappings().one()
        eligibility = connection.execute(
            select(sor.operator_review_eligibility_facts)
        ).mappings().one()
    assert (
        run["requested_ticket_count"],
        run["eligible_ticket_count"],
        run["settled_ticket_count"],
        run["skipped_ticket_count"],
    ) == (2, 1, 1, 1)
    assert skip["reason_code"] == "placement_integrity_blocked"
    assert eligibility["settlement_run_id"] == run["settlement_run_id"]


@pytest.mark.parametrize(
    "method_name",
    (
        "insert_task_settlement_run",
        "insert_ticket_settlement_revision",
        "insert_ticket_note_settlement",
        "insert_ticket_note_leg_settlement",
        "insert_settlement_cash_link",
        "insert_review_eligibility_fact",
    ),
)
def test_settlement_child_failure_rolls_back_the_complete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    original = getattr(OperatorResultRepository, method_name)

    def insert_then_fail(repository, row):
        original(repository, row)
        raise RuntimeError(f"injected settlement failure after {method_name}")

    monkeypatch.setattr(OperatorResultRepository, method_name, insert_then_fail)
    with pytest.raises(RuntimeError, match="injected settlement failure"):
        actions.settle_task(
            SettleTaskRequest(
                settlement_request_id=requested.result_refs[0].object_id,
                worker_job_id=jobs[0].worker_job_id,
                lease_owner="settlement-worker",
                settlement_method_version="operator-task-settlement-v1",
                rounding_policy_version="cn_sporttery_jczq_v1",
                actor_id="system:settlement",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"settlement:rollback:{method_name}",
                requested_at=AT + timedelta(minutes=2),
            )
        )

    with engine.connect() as connection:
        business_counts = tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_task_settlement_runs,
                sor.operator_task_settlement_skips,
                sor.operator_ticket_settlement_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
                sor.operator_review_eligibility_facts,
            )
        )
        non_stake_cash = connection.scalar(
            select(func.count())
            .select_from(sf.cash_transactions)
            .where(sf.cash_transactions.c.kind != "stake")
        )
        review_jobs = connection.scalar(
            select(func.count())
            .select_from(sod.operator_worker_jobs)
            .where(sod.operator_worker_jobs.c.job_kind == "review_materialization")
        )
    assert business_counts == (0, 0, 0, 0, 0, 0, 0)
    assert non_stake_cash == 0
    assert review_jobs == 0


@pytest.mark.parametrize(
    "method_name",
    (
        "insert_ticket_note_settlement",
        "insert_settlement_cash_link",
    ),
)
def test_settlement_persistence_reconciliation_rejects_amount_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        jobs = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    original = getattr(OperatorResultRepository, method_name)

    def insert_corrupted_amount(repository, row):
        original(repository, replace(row, amount_minor=row.amount_minor + 1))

    if method_name == "insert_ticket_note_settlement":

        def insert_corrupted_amount(repository, row):
            original(repository, replace(row, payout_minor=row.payout_minor + 1))

    monkeypatch.setattr(
        OperatorResultRepository,
        method_name,
        insert_corrupted_amount,
    )

    with pytest.raises(ValueError, match="settlement financial totals do not reconcile"):
        actions.settle_task(
            SettleTaskRequest(
                settlement_request_id=requested.result_refs[0].object_id,
                worker_job_id=jobs[0].worker_job_id,
                lease_owner="settlement-worker",
                settlement_method_version="operator-task-settlement-v1",
                rounding_policy_version="cn_sporttery_jczq_v1",
                actor_id="system:settlement",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"settlement:amount-drift:{method_name}",
                requested_at=AT + timedelta(minutes=2),
            )
        )

    with engine.connect() as connection:
        business_count = sum(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_task_settlement_runs,
                sor.operator_ticket_settlement_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
            )
        )
        non_stake_cash = connection.scalar(
            select(func.count())
            .select_from(sf.cash_transactions)
            .where(sf.cash_transactions.c.kind != "stake")
        )
    assert business_count == 0
    assert non_stake_cash == 0


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


def test_exact_current_settlement_is_classified_without_new_business_rows(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    first = _settle_result_revision(
        actions,
        engine,
        result_set,
        revision=0,
    )
    assert first.status is ActionStatus.COMMITTED

    with OntologyUnitOfWork(engine) as uow:
        ticket_ids = uow.operator_result.placed_ticket_ids_for_work_item(
            result_set.work_item_id
        )
        assert len(ticket_ids) == 1
        prepared, skip_code = result_action_module._prepare_ticket_settlement(
            uow,
            ticket_id=ticket_ids[0],
            result_set=result_set,
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
        )

    assert prepared is None
    assert skip_code == "already_current"
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(
                sor.operator_ticket_settlement_revisions
            )
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(sf.cash_transactions)
        ) == 2
        assert connection.scalar(
            select(func.count()).select_from(
                sor.operator_review_eligibility_facts
            )
        ) == 1


def test_real_corrections_reverse_only_the_direct_predecessor_payout(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    assert _settle_result_revision(
        actions,
        engine,
        result_set,
        revision=0,
    ).status is ActionStatus.COMMITTED
    for revision, score in enumerate(((0, 1), (3, 1), (4, 1)), start=1):
        result_set = _correct_result_set(
            actions,
            engine,
            result_set,
            home_90=score[0],
            away_90=score[1],
            revision=revision,
        )
        assert _settle_result_revision(
            actions,
            engine,
            result_set,
            revision=revision,
        ).status is ActionStatus.COMMITTED

    with engine.connect() as connection:
        settlements = connection.execute(
            select(sor.operator_ticket_settlement_revisions).order_by(
                sor.operator_ticket_settlement_revisions.c.revision_no
            )
        ).mappings().all()
        links = connection.execute(
            text("SELECT * FROM operator_settlement_cash_links ORDER BY rowid")
        ).mappings().all()
        stake_count = connection.scalar(
            select(func.count())
            .select_from(sf.cash_transactions)
            .where(sf.cash_transactions.c.kind == "stake")
        )
    assert [row["gross_payout_minor"] for row in settlements] == [500, 0, 500, 500]
    assert [row["amount_minor"] for row in links] == [500, -500, 500, -500, 500]
    payout_ids = [
        row["transaction_id"]
        for row in links
        if row["transaction_kind"] == "payout"
    ]
    reversal_targets = [
        row["reverses_transaction_id"]
        for row in links
        if row["transaction_kind"] == "payout_reversal"
    ]
    assert reversal_targets == [payout_ids[0], payout_ids[1]]
    assert stake_count == 1


def test_settlement_worker_claims_request_and_commits_exactly_one_run(
    tmp_path: Path,
) -> None:
    actions, engine, result_set = _placed_result_set(tmp_path)
    requested = actions.request_settlement(_settlement_request(result_set))

    completed = TaskSettlementWorker(
        action_service=ActionService(lambda: OntologyUnitOfWork(engine)),
        result_actions=actions,
        worker_id="settlement-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=AT + timedelta(minutes=2))

    assert requested.status is ActionStatus.COMMITTED
    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_task_settlement_runs)
        ) == 1
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.job_kind == "task_settlement"
            )
        ).mappings().one()
    assert job["state"] == "completed"
    assert job["result_action_id"] == completed[0].action_id


def _public_replay_workspace(tmp_path: Path) -> tuple[Path, Path]:
    configured = os.environ.get("NUTMEG_P10_REPLAY_ROOT")
    root = (tmp_path if configured is None else Path(configured)).resolve()
    workspace = root / "data" / "ontology"
    workspace.mkdir(parents=True, exist_ok=True)
    return root, workspace


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


def test_public_replay_boundary_uses_cli_api_worker_and_checked_in_fixtures() -> None:
    result_boundary = inspect.getsource(_invoke_public_result_ingest)
    settlement_boundary = inspect.getsource(_request_public_settlement)
    jczq_fixture_boundary = inspect.getsource(_jczq_result_manifest_document)
    zucai_fixture_boundary = inspect.getsource(_zucai_result_manifest_document)

    assert "CliRunner" in result_boundary
    assert "ingest-results" in result_boundary
    assert "TestClient" in settlement_boundary
    assert "/api/v2/operator" in settlement_boundary
    assert "jczq-complete.json" in jczq_fixture_boundary
    assert "zucai-complete.json" in zucai_fixture_boundary
    for forbidden in (
        "OperatorResultActions",
        "TaskSettlementWorker",
        ".run_once(",
        ".insert_",
    ):
        assert forbidden not in result_boundary
        assert forbidden not in settlement_boundary


def _jczq_result_manifest_document(
    *,
    task_snapshot_hash: str,
    captured_at: str,
) -> dict[str, object]:
    document = _checked_in_result_document("jczq-complete.json")
    document.update(
        {
            "business_key": "2026-09-04",
            "task_snapshot_token": task_snapshot_hash,
            "slate_revision_token": "slate-1",
            "result_cutoff_at": captured_at,
            "supersedes_result_set_token": None,
        }
    )
    matches = document["matches"]
    assert isinstance(matches, list) and len(matches) == 1
    match = matches[0]
    assert isinstance(match, dict)
    match.update(
        {
            "official_match_no": "001",
            "canonical_match_id": "match-1",
        }
    )
    sources = match["sources"]
    assert isinstance(sources, list) and len(sources) == 3
    for source in sources:
        assert isinstance(source, dict)
        source_kind = source["source_kind"]
        source.update(
            {
                "receipt_state": "available",
                "artifact_retrieval_id": f"result-retrieval-{source_kind}",
                "captured_at": captured_at,
                "source_disposition": "played_90",
                "home_90": 2,
                "away_90": 1,
                "invalid_code": None,
            }
        )
    return document


def _jczq_multimarket_result_manifest_document(
    *,
    task_snapshot_hash: str,
    captured_at: str,
) -> dict[str, object]:
    document = _jczq_result_manifest_document(
        task_snapshot_hash=task_snapshot_hash,
        captured_at=captured_at,
    )
    first = document["matches"][0]
    assert isinstance(first, dict)
    first["sources"] = [
        {
            **source,
            "home_90": 3,
            "away_90": 1,
        }
        for source in first["sources"]
    ]
    second_sources = [
        {
            **source,
            "home_90": 2,
            "away_90": 1,
        }
        for source in first["sources"]
    ]
    document["matches"].append(
        {
            "official_match_no": "002",
            "canonical_match_id": "match-2",
            "sources": second_sources,
        }
    )
    return document


def _invoke_public_result_ingest(
    *,
    root: Path,
    manifest_name: str,
    document: dict[str, object],
) -> dict[str, object]:
    manifest_path = root / manifest_name
    manifest_path.write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli_app,
        [
            "workflow",
            "ingest-results",
            "--manifest",
            str(manifest_path),
            "--data-dir",
            str(root / "data"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "committed"
    return receipt


def _public_replay_services(root: Path, *, clock_at):
    production_dir = Path(
        os.environ.get("NUTMEG_PRODUCTION_DATA_DIR", root / "production")
    ).resolve()
    signing_key = os.environ.get(
        "NUTMEG_OPERATOR_TOKEN_SIGNING_KEY",
        "isolated-p10-signing-key-32-bytes-min",
    )
    settings = AppSettings(
        _env_file=None,
        data_dir=root / "data",
        production_data_dir=production_dir,
        default_user_id="jun",
        operator_runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        operator_surface_mode=OperatorSurfaceMode.ACTIVE,
        operator_token_signing_key=signing_key,
        operator_scheduler_enabled=False,
        telegram_bot_token=None,
    )
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=(root / "data").resolve(),
        production_data_dir=production_dir,
        running_commit="isolated-p10-replay",
    )
    services = build_product_services(settings, runtime_config=runtime)
    assert services.infrastructure_workers is not None
    services.infrastructure_workers._clock = lambda: clock_at
    return services, runtime


def _request_public_settlement(
    *,
    root: Path,
    lane: str,
    business_key: str,
    clock_at,
    idempotency_key: str,
) -> dict[str, object]:
    services, runtime = _public_replay_services(root, clock_at=clock_at)
    app = create_product_app(
        services,
        session_secret="isolated-p10-session",
        csrf_secret="isolated-p10-csrf",
        clock=lambda: clock_at,
        runtime_config=runtime,
    )
    with TestClient(app) as client:
        task_response = client.get(
            f"/api/v2/operator/tasks/{lane}/{business_key}",
            params={"as_of": clock_at.isoformat()},
        )
        assert task_response.status_code == 200, task_response.text
        task = task_response.json()
        settlement_items = [
            item
            for item in task["work_items"]
            if item["scope_kind"] == "ticket"
            and item["phase"] == "await_result"
            and item["next_action"] is not None
            and item["next_action"]["action_code"] == "request_settlement"
        ]
        assert settlement_items
        work_item = task["active_work_item"]
        assert work_item in settlement_items
        assert work_item["phase"] == "await_result"
        assert work_item["next_action"]["action_code"] == "request_settlement"
        assert work_item["next_action"]["enabled"] is True
        session = client.get("/api/v1/session")
        assert session.status_code == 200
        requested = client.post(
            "/api/v2/operator",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": session.json()["csrf_token"],
            },
            json={
                "schema_version": "2",
                "kind": "request_settlement",
                "expected_snapshot_token": work_item["snapshot_token"],
                "idempotency_key": idempotency_key,
                "task_key": f"{lane}:{business_key}",
            },
        )
        assert requested.status_code == 202, requested.text

    restarted_at = clock_at + timedelta(seconds=1)
    restarted_services, restarted_runtime = _public_replay_services(
        root,
        clock_at=restarted_at,
    )
    restarted_app = create_product_app(
        restarted_services,
        session_secret="isolated-p10-session-restarted",
        csrf_secret="isolated-p10-csrf-restarted",
        clock=lambda: restarted_at,
        runtime_config=restarted_runtime,
    )
    with TestClient(restarted_app) as restarted_client:
        assert restarted_client.get("/api/v1/session").status_code == 200
        settled_response = restarted_client.get(
            f"/api/v2/operator/tasks/{lane}/{business_key}",
            params={"as_of": restarted_at.isoformat()},
        )
        assert settled_response.status_code == 200, settled_response.text
        settled_task = settled_response.json()
        assert any(
            item["scope_kind"] == "ticket"
            for item in settled_task["work_items"]
        )
        settled_work_item = restarted_services.operator_queries.work_item_v2(
            OperatorLane(lane),
            business_key,
            work_item["work_item_key"],
            as_of=restarted_at,
        ).model_dump(mode="json")
        rendered = restarted_client.get(work_item["next_action"]["recovery_link"])
        assert rendered.status_code == 200, rendered.text
        assert "开始结算" not in rendered.text
        return settled_work_item


def test_isolated_jczq_public_replay(tmp_path: Path) -> None:
    root, workspace = _public_replay_workspace(tmp_path)
    captured_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    fixture = _place_multimarket_jczq_ticket(
        workspace,
        result_captured_at=captured_at,
        complete_market_baseline_job=True,
    )
    receipt = _invoke_public_result_ingest(
        root=root,
        manifest_name="jczq-result.json",
        document=_jczq_multimarket_result_manifest_document(
            task_snapshot_hash=fixture.context.task_snapshot_hash,
            captured_at=captured_at,
        ),
    )

    assert receipt["agreement_counts"] == {
        "agreed": 2,
        "conflict": 0,
        "missing": 0,
    }
    assert receipt["outcome_count"] == 2
    settled_work_item = _request_public_settlement(
        root=root,
        lane="jczq",
        business_key="2026-09-04",
        clock_at=datetime.now(UTC),
        idempotency_key="public:jczq:settlement:1",
    )

    with fixture.engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        ticket = connection.execute(
            select(sor.operator_ticket_settlement_revisions)
        ).mappings().one()
        action_roles = connection.execute(
            select(schema.actions.c.action_type, schema.actions.c.actor_role).where(
                schema.actions.c.action_type.in_(
                    ("import_result_evidence_set", "request_settlement", "settle_task")
                )
            )
        ).all()
        counts = tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (
                sor.operator_result_source_receipts,
                sor.operator_outcome_revisions,
                sor.operator_ticket_note_settlements,
                sor.operator_ticket_note_leg_settlements,
                sor.operator_settlement_cash_links,
                sor.operator_review_eligibility_facts,
            )
        )
        payout_total = connection.scalar(
            select(func.sum(sor.operator_settlement_cash_links.c.amount_minor))
        )
        settled_markets = set(
            connection.scalars(
                select(
                    sor.operator_ticket_note_legs.c.market_definition_id
                ).select_from(
                    sor.operator_ticket_note_leg_settlements.join(
                        sor.operator_ticket_note_legs,
                        sor.operator_ticket_note_leg_settlements.c.ticket_note_leg_id
                        == sor.operator_ticket_note_legs.c.ticket_note_leg_id,
                    )
                )
            )
        )

    assert run.settlement_state == "settled"
    assert ticket.gross_payout_minor == 1250
    assert counts == (6, 2, 1, 2, 1, 1)
    assert settled_markets == {"md-had", "md-hhad"}
    assert payout_total == ticket.gross_payout_minor
    assert settled_work_item["step"]["settlement_state"] == "settled"
    assert settled_work_item["step"]["settlement_command_token"] is None
    assert settled_work_item["step"]["currency"] == "CNY"
    assert settled_work_item["step"]["total_stake_minor"] == 200
    assert settled_work_item["step"]["total_payout_minor"] == 1250
    assert len(settled_work_item["step"]["tickets"]) == 1
    assert settled_work_item["step"]["request_state"] == "completed"
    assert settled_work_item["step"]["placed_ticket_count"] == 1
    assert settled_work_item["step"]["settled_ticket_count"] == 1
    assert settled_work_item["step"]["blocking_codes"] == []
    assert settled_work_item["step"]["last_run"] == {
        "requested_ticket_count": 1,
        "eligible_ticket_count": 1,
        "settled_ticket_count": 1,
        "skipped_ticket_count": 0,
        "persisted_settlement_count": 1,
        "skips": [],
    }
    first_result = settled_work_item["step"]["result_matches"][0]
    assert first_result["outcome_state"] == "committed"
    assert first_result["sources"][0] == {
        "source_label": "API-Football",
        "state": "available",
        "result_label": "3 - 1",
        "captured_at": first_result["sources"][0]["captured_at"],
        "source_kind": "api_football",
        "source_disposition": "played_90",
        "home_90": 3,
        "away_90": 1,
        "invalid_code": None,
    }
    projected_ticket = settled_work_item["step"]["tickets"][0]
    assert projected_ticket["revision_no"] == 1
    assert projected_ticket["corrected"] is False
    assert projected_ticket["settlement_method_label"] == "确定性整单结算 v1"
    assert projected_ticket["rounding_policy_label"] == "竞彩逐注四舍五入 v1"
    assert projected_ticket["distinct_note_count"] == 1
    assert projected_ticket["cash_entries"] == [
        {
            "transaction_kind": "payout",
            "amount_minor": 1250,
            "currency": "CNY",
            "replaces_prior_payout": False,
        }
    ]
    assert len(projected_ticket["notes"]) == 1
    projected_note = projected_ticket["notes"][0]
    assert projected_note["note_index"] == 0
    assert projected_note["group_label"] is None
    assert projected_note["winning_unit_count"] == 1
    assert projected_note["void_unit_count"] == 0
    assert projected_note["stake_minor"] == 200
    assert projected_note["prize_tier_code"] is None
    assert len(projected_note["legs"]) == 2
    assert projected_note["legs"][0]["leg_index"] == 0
    assert projected_note["legs"][0]["official_match_no"] == "001"
    assert projected_note["legs"][0]["market_code"] == "hhad"
    assert projected_note["legs"][0]["selection_code"] == "3"
    assert projected_note["legs"][0]["result_disposition"] == "played_90"
    assert projected_note["legs"][0]["market_result_code"] == "home"
    assert projected_note["legs"][0]["booked_decimal_odds"] == "2.500000000000"
    assert projected_note["legs"][0]["settlement_parameter_decimal"] == (
        "-1.000000000000"
    )
    assert set(action_roles) == {
        ("import_result_evidence_set", "deterministic_system"),
        ("request_settlement", "judge_operator"),
        ("settle_task", "deterministic_system"),
    }


def test_isolated_zucai_public_replay(tmp_path: Path) -> None:
    root, workspace = _public_replay_workspace(tmp_path)
    captured_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    engine, task_snapshot_hash, first_note_legs = _place_public_zucai_ticket_set(
        workspace,
        complete_market_baseline_job=True,
    )
    with engine.connect() as connection:
        placed_ticket_kinds = dict(
            connection.execute(
                select(sf.tickets.c.ticket_kind, func.count())
                .group_by(sf.tickets.c.ticket_kind)
            ).all()
        )
        placed_note_count = connection.scalar(
            select(func.count()).select_from(sor.operator_ticket_notes)
        )
        placed_leg_count = connection.scalar(
            select(func.count()).select_from(sor.operator_ticket_note_legs)
        )
    _seed_result_retrievals(
        engine,
        suffix="-zucai",
        captured_at=captured_at,
    )
    document, void_match_id = _zucai_result_manifest_document(
        task_snapshot_hash=task_snapshot_hash,
        first_note_legs=first_note_legs,
        captured_at=captured_at,
    )
    receipt = _invoke_public_result_ingest(
        root=root,
        manifest_name="zucai-result.json",
        document=document,
    )

    assert receipt["agreement_counts"] == {
        "agreed": 14,
        "conflict": 0,
        "missing": 0,
    }
    assert receipt["outcome_count"] == 14
    assert receipt["prize_table_state"] == "available"
    settled_work_item = _request_public_settlement(
        root=root,
        lane="zucai",
        business_key="26111",
        clock_at=datetime.now(UTC),
        idempotency_key="public:zucai:settlement:1",
    )

    with engine.connect() as connection:
        run = connection.execute(
            select(sor.operator_task_settlement_runs)
        ).mappings().one()
        settlements = connection.execute(
            select(sor.operator_ticket_settlement_revisions).order_by(
                sor.operator_ticket_settlement_revisions.c.settlement_index
            )
        ).mappings().all()
        ticket_kinds_by_id = dict(
            connection.execute(
                select(sf.tickets.c.ticket_id, sf.tickets.c.ticket_kind)
            ).all()
        )
        note_count = connection.scalar(
            select(func.count()).select_from(sor.operator_ticket_note_settlements)
        )
        leg_count = connection.scalar(
            select(func.count()).select_from(
                sor.operator_ticket_note_leg_settlements
            )
        )
        receipt_count = connection.scalar(
            select(func.count()).select_from(sor.operator_result_source_receipts)
        )
        outcome_count = connection.scalar(
            select(func.count()).select_from(sor.operator_outcome_revisions)
        )
        prize_count = connection.scalar(
            select(func.count()).select_from(sor.zucai_prize_table_revisions)
        )
        payout_total = connection.scalar(
            select(func.sum(sor.operator_settlement_cash_links.c.amount_minor))
        )
        winning_tiers = set(
            connection.scalars(
                select(sor.operator_ticket_note_settlements.c.prize_tier_code).where(
                    sor.operator_ticket_note_settlements.c.prize_tier_code.is_not(None)
                )
            )
        )
        cash_amounts = sorted(
            connection.scalars(
                select(sor.operator_settlement_cash_links.c.amount_minor)
            )
        )
        void_grades = set(
            connection.execute(
                select(
                    sor.operator_ticket_note_leg_settlements.c.result_disposition,
                    sor.operator_ticket_note_leg_settlements.c.market_result_code,
                    sor.operator_ticket_note_leg_settlements.c.leg_grade,
                )
                .select_from(
                    sor.operator_ticket_note_leg_settlements.join(
                        sor.operator_ticket_note_legs,
                        sor.operator_ticket_note_leg_settlements.c.ticket_note_leg_id
                        == sor.operator_ticket_note_legs.c.ticket_note_leg_id,
                    )
                )
                .where(sor.operator_ticket_note_legs.c.match_id == void_match_id)
            ).all()
        )

    assert placed_ticket_kinds == {"renjiu": 2, "sfc": 1}
    assert run.settlement_state == "settled"
    assert (placed_note_count, placed_leg_count) == (1297, 11678)
    assert note_count == placed_note_count
    assert leg_count == placed_leg_count
    assert (receipt_count, outcome_count, prize_count) == (42, 14, 1)
    assert len(settlements) == 3
    assert winning_tiers == {"renjiu_first", "sfc_first"}
    settlement_kind_payouts = [
        (ticket_kinds_by_id[row.ticket_id], row.gross_payout_minor)
        for row in settlements
    ]
    assert sorted(settlement_kind_payouts) == [
        ("renjiu", 44_400),
        ("renjiu", 44_400),
        ("sfc", 1_000_000),
    ]
    assert cash_amounts == [44_400, 44_400, 1_000_000]
    assert payout_total == 1_088_800
    assert payout_total == sum(row.gross_payout_minor for row in settlements)
    assert void_grades == {("official_void", "official_void", "void")}
    assert (
        run.requested_ticket_count,
        run.eligible_ticket_count,
        run.settled_ticket_count,
        run.skipped_ticket_count,
        run.persisted_settlement_count,
        run.persisted_note_grade_count,
        run.persisted_leg_grade_count,
        run.persisted_cash_count,
    ) == (3, 3, 3, 0, 3, 1297, 11678, 3)
    step = settled_work_item["step"]
    assert step["request_state"] == "completed"
    assert step["settlement_state"] == "settled"
    assert step["placed_ticket_count"] == step["settled_ticket_count"] == 3
    assert step["total_stake_minor"] == 259_400
    assert step["total_payout_minor"] == 1_088_800
    ticket_kind_labels = {"renjiu": "任九", "sfc": "胜负彩"}
    assert [
        (ticket["ticket_kind_label"], ticket["payout_minor"])
        for ticket in step["tickets"]
    ] == [
        (ticket_kind_labels[ticket_kind], payout_minor)
        for ticket_kind, payout_minor in settlement_kind_payouts
    ]
    assert all(
        ticket["settlement_method_label"] == "确定性整单结算 v1"
        and ticket["rounding_policy_label"] == "足彩固定奖金整数结算"
        for ticket in step["tickets"]
    )
