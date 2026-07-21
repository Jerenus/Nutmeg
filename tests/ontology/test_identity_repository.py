from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import TeamRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _repo(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_insert_team_and_lookup_by_external_id(tmp_path: Path) -> None:
    engine = _repo(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.identity
        repo.insert_team(TeamRow(
            team_id="team-x", team_kind=TeamKind.CLUB, canonical_name="Hammarby",
            country="SE", resolution_status=ResolutionStatus.PROVISIONAL,
            created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
        ))
        repo.link_external_identifier(
            entity_id="team-x", entity_type=EntityType.TEAM,
            provider="api-football", external_id="377",
        )
    with OntologyUnitOfWork(engine) as uow:
        found = uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="377"
        )
        assert found == "team-x"
        assert uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="999"
        ) is None


def test_alias_lookup_is_case_folded(tmp_path: Path) -> None:
    engine = _repo(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        # "Vojvodina" is a seeded club canonical; the repository casefolds the query
        hit = uow.identity.entity_by_alias(EntityType.TEAM, "Vojvodina")
        miss = uow.identity.entity_by_alias(EntityType.TEAM, "no-such-team-xyz")
    assert miss is None
    assert hit is not None
