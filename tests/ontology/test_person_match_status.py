from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.observation_actions import (
    ObservationActions,
    PersonMatchStatusRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import Availability, StatusKind
from nutmeg.ontology.identity.models import ResolutionStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import PersonRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.identity.insert_person(PersonRow(
            person_id="person-1", canonical_name="X", birth_date=None, nationality=None,
            resolution_status=ResolutionStatus.PROVISIONAL,
            created_at=datetime(2026, 7, 19, tzinfo=UTC).isoformat()))
    return ObservationActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_record_person_match_status_links_observation(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_person_match_status(PersonMatchStatusRequest(
        match_id="match-1", person_id="person-1", team_appearance_id=None,
        availability=Availability.OUT, status_kind=StatusKind.INJURY,
        valid_from="2026-07-19T00:00:00+08:00", observed_at="2026-07-19T12:00:00+08:00",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="pms:1",
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.context.person_match_status_ids("match-1")) == 1
        # a backing observation was recorded and linked
        assert uow.evidence.count_observations() == 1
