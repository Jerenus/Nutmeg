from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.person_actions import PersonActions, UpsertPersonRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return PersonActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> UpsertPersonRequest:
    return UpsertPersonRequest(
        canonical_name="Lionel Messi", provider="api-football", external_id="P-154",
        actor_id="source:api", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def test_upsert_person_resolves_same_entity_on_provider_id(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    first = actions.upsert_person(_req("p:1"))
    second = actions.upsert_person(_req("p:2"))
    assert first.status is ActionStatus.COMMITTED
    person_id = first.result_refs[0].object_id
    assert person_id.startswith("person-")
    assert second.result_refs[0].object_id == person_id


def test_ai_analyst_cannot_upsert_person(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.upsert_person(_req("p:denied", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
