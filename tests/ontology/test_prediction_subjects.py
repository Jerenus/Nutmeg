from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RegisterPredictionRequest,
    WorkflowActions,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.workflow.models import PredictionRow, PredictionStatus

AT = "2026-08-27T10:00:00+00:00"
NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


def _engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_issue_scoped_prediction_row_roundtrip(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.workflow.insert_prediction(
            PredictionRow(
                prediction_id="pred-1",
                match_id=None,
                subject_type="issue",
                subject_id="26111",
                claim="悬置持平4场至少2平",
                falsifier="≤1场平→o条降级",
                status=PredictionStatus.PENDING,
                outcome=None,
                registered_at=AT,
                settled_at=None,
            )
        )
        row = uow.workflow.get_prediction("pred-1")
    assert row.subject_type == "issue" and row.subject_id == "26111"
    assert row.match_id is None


def test_migration_15_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run_migrations(engine)  # 二跑无 drift、无异常
    with engine.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(predictions)")}
    assert {"subject_type", "subject_id", "match_id"} <= cols


def test_grade_permission_granted_to_judge_and_replay_adjudicator(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT actor_role FROM action_permissions WHERE action_type='grade_prediction'"
        ).fetchall()
    assert {r[0] for r in rows} == {"judge_operator", "replay_adjudicator"}


def _actions(tmp_path: Path):
    engine = _engine(tmp_path)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    return WorkflowActions(service), engine


def test_register_issue_prediction_and_grade(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    reg = actions.register_prediction(
        RegisterPredictionRequest(
            match_id=None,
            subject_type="issue",
            subject_id="26111",
            claim="悬置持平4场至少2平",
            falsifier="≤1场平→o条降级",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:P1",
            requested_at=NOW,
        )
    )
    assert reg.status is ActionStatus.COMMITTED
    pred_id = reg.result_refs[0].object_id
    graded = actions.grade_prediction(
        GradePredictionRequest(
            prediction_id=pred_id,
            outcome="miss",
            reason="夜二仅1平(3胜/4负/5平/6胜),falsifier触发",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:P1:grade",
            requested_at=NOW,
        )
    )
    assert graded.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_prediction(pred_id)
    assert row.outcome == "miss" and row.settled_at is not None
    assert row.status is PredictionStatus.REFUTED


def test_ai_cannot_grade(tmp_path: Path) -> None:
    actions, _ = _actions(tmp_path)
    reg = actions.register_prediction(
        RegisterPredictionRequest(
            match_id=None,
            subject_type="issue",
            subject_id="26111",
            claim="c",
            falsifier="f",
            actor_id="ai:claude",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="rx:26111:Px",
            requested_at=NOW,
        )
    )
    out = actions.grade_prediction(
        GradePredictionRequest(
            prediction_id=reg.result_refs[0].object_id,
            outcome="hit",
            reason="r",
            actor_id="ai:claude",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="rx:26111:Px:grade",
            requested_at=NOW,
        )
    )
    assert out.status is ActionStatus.REJECTED


def test_grade_twice_is_rejected(tmp_path: Path) -> None:
    actions, _ = _actions(tmp_path)
    reg = actions.register_prediction(
        RegisterPredictionRequest(
            match_id=None,
            subject_type="issue",
            subject_id="26111",
            claim="c",
            falsifier="f",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:Py",
            requested_at=NOW,
        )
    )
    pid = reg.result_refs[0].object_id
    first = actions.grade_prediction(
        GradePredictionRequest(
            prediction_id=pid,
            outcome="hit",
            reason="r",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"grade:{pid}:1",
            requested_at=NOW,
        )
    )
    assert first.status is ActionStatus.COMMITTED
    with pytest.raises(ValueError, match="already graded"):
        actions.grade_prediction(
            GradePredictionRequest(
                prediction_id=pid,
                outcome="miss",
                reason="改判",
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"grade:{pid}:2",
                requested_at=NOW,
            )
        )


def test_register_prediction_subject_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="subject_type"):
        RegisterPredictionRequest(
            match_id=None,
            subject_type="ticket",
            subject_id="26111",
            claim="c",
            falsifier="f",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:Pz",
            requested_at=NOW,
        )
    with pytest.raises(ValueError, match="subject_id == match_id"):
        RegisterPredictionRequest(
            match_id="match-1",
            subject_type="match",
            subject_id="match-2",
            claim="c",
            falsifier="f",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:Pz",
            requested_at=NOW,
        )
    with pytest.raises(ValueError, match="must not carry match_id"):
        RegisterPredictionRequest(
            match_id="match-1",
            subject_type="issue",
            subject_id="26111",
            claim="c",
            falsifier="f",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26111:Pz",
            requested_at=NOW,
        )
