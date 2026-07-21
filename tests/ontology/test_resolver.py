from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.identity.resolver import ResolutionMethod, resolve_entity
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import TeamRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _seed_team(engine) -> None:
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_team(TeamRow(
            team_id="team-known", team_kind=TeamKind.CLUB, canonical_name="Known FC",
            country="SE", resolution_status=ResolutionStatus.RESOLVED,
            created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
        ))
        uow.identity.link_external_identifier(
            entity_id="team-known", entity_type=EntityType.TEAM,
            provider="sporttery", external_id="SWE-KNOWN",
        )
        uow.identity.add_alias("team-known", EntityType.TEAM, "known fc")


def test_provider_id_wins_over_alias(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_team(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(
            uow.identity, EntityType.TEAM,
            provider="sporttery", external_id="SWE-KNOWN", aliases=("known fc",),
        )
    assert outcome.entity_id == "team-known"
    assert outcome.method is ResolutionMethod.PROVIDER_ID


def test_alias_used_when_no_provider_id(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_team(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(uow.identity, EntityType.TEAM, aliases=("Known FC",))
    assert outcome.entity_id == "team-known"
    assert outcome.method is ResolutionMethod.ALIAS


def test_unresolved_returns_none_never_guesses(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(
            uow.identity, EntityType.TEAM,
            provider="sporttery", external_id="UNKNOWN", aliases=("mystery utd",),
        )
    assert outcome.entity_id is None
    assert outcome.method is None
