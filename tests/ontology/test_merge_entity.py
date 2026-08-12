from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.entity_actions import (
    EntityActions,
    MergeEntityRequest,
    UpsertTeamRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _two_teams(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = EntityActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    a = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK", team_kind=TeamKind.CLUB, country="SE",
        provider="sporttery", external_id="SWE-AIK-A",
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:a",
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    b = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK Stockholm", team_kind=TeamKind.CLUB, country="SE",
        provider="api-football", external_id="INT-AIK-B",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:b",
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    return actions, engine, a, b


def test_merge_redirects_and_is_reversible(tmp_path: Path) -> None:
    actions, engine, survivor, duplicate = _two_teams(tmp_path)
    outcome = actions.merge_entity(MergeEntityRequest(
        entity_type=EntityType.TEAM, from_id=duplicate, into_id=survivor,
        reason="same club two providers", actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="merge:1", requested_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.identity.redirect(duplicate, EntityType.TEAM) == survivor
        assert uow.identity.redirect(survivor, EntityType.TEAM) == survivor
        row = uow.identity.get_team(duplicate)
        assert row.resolution_status is ResolutionStatus.MERGED
        merged_from = uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="INT-AIK-B"
        )
        assert uow.identity.redirect(merged_from, EntityType.TEAM) == survivor


def test_connector_cannot_merge(tmp_path: Path) -> None:
    actions, _engine, survivor, duplicate = _two_teams(tmp_path)
    outcome = actions.merge_entity(MergeEntityRequest(
        entity_type=EntityType.TEAM, from_id=duplicate, into_id=survivor, reason="x",
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        idempotency_key="merge:denied", requested_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED


def test_upsert_links_external_id_when_resolved_by_curated_alias(tmp_path: Path) -> None:
    """回归 2026-08-05:别名种子命中时曾直接 return,provider 的 external_id 永不登记。

    俱乐部别名表扩到 ~400 条后,这条'命中已有实体'路径从罕见变成常态。
    """
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = EntityActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    team_id = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK Stockholm", team_kind=TeamKind.CLUB, country="SE",
        provider="api-football", external_id="AF-377",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:seeded",
        requested_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        assert uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="AF-377") == team_id
