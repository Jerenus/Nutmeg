from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
    WorkflowActions,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.workflow.models import PredictionStatus

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    return WorkflowActions(service), engine


def test_ai_cannot_record_operator_adjudication(tmp_path: Path) -> None:
    workflow, _engine = _setup(tmp_path)
    request = RecordAdjudicationRequest(
        subject_type="claim",
        subject_id="claim-1",
        decision="approve",
        reason="unsupported by verified evidence",
        evidence_rejected=[{"object_type": "claim", "object_id": "claim-2"}],
        alternative={"decision": "hold"},
        supersedes_adjudication_id=None,
        actor_id="model:analyst",
        actor_role=ActorRole.AI_ANALYST,
        idempotency_key="adjudication:denied",
        requested_at=AT,
    )

    outcome = workflow.record_adjudication(request)

    assert outcome.status is ActionStatus.REJECTED


def test_operator_records_adjudication_with_rejected_evidence(tmp_path: Path) -> None:
    workflow, engine = _setup(tmp_path)
    request = RecordAdjudicationRequest(
        subject_type="claim",
        subject_id="claim-1",
        decision="reject",
        reason="source is superseded",
        evidence_rejected=[{"object_type": "claim", "object_id": "claim-2"}],
        alternative={"use": "claim-3"},
        supersedes_adjudication_id=None,
        actor_id="operator:owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="adjudication:1",
        requested_at=AT,
    )

    outcome = workflow.record_adjudication(request)

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_adjudication(outcome.result_refs[0].object_id)
        assert row.reason == "source is superseded"
        assert row.evidence_rejected == [
            {"object_id": "claim-2", "object_type": "claim"}
        ]
        assert row.alternative == {"use": "claim-3"}


def test_prediction_is_typed_and_governed(tmp_path: Path) -> None:
    """flag/precedent 入账 2026-10-01 随内核瘦身退役（记分牌是唯一事实源）；预测登记仍是活路径。"""
    workflow, engine = _setup(tmp_path)

    prediction = workflow.register_prediction(
        RegisterPredictionRequest(
            match_id="match-1",
            subject_type="match",
            subject_id="match-1",
            claim="away price shortens before close",
            falsifier="away price stays flat or lengthens",
            actor_id="model:analyst",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="prediction:1",
            requested_at=AT,
        )
    )

    assert prediction.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        prediction_row = uow.workflow.get_prediction(prediction.result_refs[0].object_id)
        assert prediction_row.status is PredictionStatus.PENDING
        assert prediction_row.outcome is None
