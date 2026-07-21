from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.session_actions import OpenSessionRequest, SessionActions
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return SessionActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.JUDGE_OPERATOR) -> OpenSessionRequest:
    return OpenSessionRequest(
        operator_id="op:owner", cutoff_at="2026-07-19T15:00:00+08:00", scope={"matches": ["m1"]},
        actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC))


def test_open_session_commits(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.open_session(_req("s:1"))
    assert outcome.status is ActionStatus.COMMITTED
    assert outcome.result_refs[0].object_id.startswith("sess-")


def test_ai_analyst_cannot_open_session(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    assert actions.open_session(_req("s:d", ActorRole.AI_ANALYST)).status is ActionStatus.REJECTED
