from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return EntityActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> UpsertTeamRequest:
    return UpsertTeamRequest(
        canonical_name="Djurgarden", team_kind=TeamKind.CLUB, country="SE",
        provider="sporttery", external_id="SWE-DIF",
        actor_id="source:sporttery", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def test_upsert_creates_provisional_then_resolves_same_entity(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    first = actions.upsert_team(_req("dif:1"))
    second = actions.upsert_team(_req("dif:2"))   # same provider id, different key
    assert first.status is ActionStatus.COMMITTED
    team_id = first.result_refs[0].object_id
    assert second.result_refs[0].object_id == team_id   # provider id resolved to the same team


def test_analyst_cannot_upsert(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.upsert_team(_req("dif:analyst", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
    assert outcome.error_code == "permission_denied"


def test_upsert_links_external_id_when_resolved_by_curated_alias(tmp_path: Path) -> None:
    """回归 2026-08-05:别名种子命中时曾直接 return,provider 的 external_id 永不登记。

    俱乐部别名表扩到 ~400 条后,这条'命中已有实体'路径从罕见变成常态。
    """
    actions, engine = _actions(tmp_path)
    team_id = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK Stockholm", team_kind=TeamKind.CLUB, country="SE",
        provider="api-football", external_id="AF-377",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:seeded",
        requested_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        assert uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="AF-377") == team_id
