from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.observation_actions import ObservationActions, RecordObservationRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return ObservationActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> RecordObservationRequest:
    return RecordObservationRequest(
        observation_type="weather", subject_type="match", subject_id="match-1",
        scope_match_id="match-1", value={"temp_c": 21},
        verification_method=VerificationMethod.OFFICIAL,
        valid_from="2026-07-19T00:00:00+08:00", observed_at="2026-07-19T12:00:00+08:00",
        actor_id="source:open-meteo", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )


def test_record_observation_commits_and_counts(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_observation(_req("obs:1"))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.count_observations() == 1


def test_ai_extractor_cannot_record_observation(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.record_observation(_req("obs:denied", ActorRole.AI_EXTRACTOR))
    assert outcome.status is ActionStatus.REJECTED
