from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.match_actions import MatchActions, MatchSideRef, RecordMatchRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import (
    CompetitionEditionRef,
    MatchSide,
    MatchStatus,
    ResolutionStatus,
    TeamKind,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import TeamRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    # RecordMatch is given already-resolved team ids; seed them so the FK holds.
    with OntologyUnitOfWork(engine) as uow:
        for team_id, name in (("team-home", "Home FC"), ("team-away", "Away FC")):
            uow.identity.insert_team(TeamRow(
                team_id=team_id, team_kind=TeamKind.CLUB, canonical_name=name, country="SE",
                resolution_status=ResolutionStatus.RESOLVED,
                created_at=datetime(2026, 7, 19, tzinfo=UTC).isoformat(),
            ))
    return MatchActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, scheduled_at: str | None) -> RecordMatchRequest:
    return RecordMatchRequest(
        provider="sporttery", external_id="2026071900123",
        scheduled_at=scheduled_at, schedule_status="scheduled" if scheduled_at else "unknown",
        status=MatchStatus.SCHEDULED,
        home=MatchSideRef(team_id="team-home", side=MatchSide.HOME),
        away=MatchSideRef(team_id="team-away", side=MatchSide.AWAY),
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        idempotency_key=key, requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )


def test_record_match_stores_real_schedule_and_two_appearances(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_match(_req("m:1", "2026-07-19T19:00:00+02:00"))
    assert outcome.status is ActionStatus.COMMITTED
    match_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at == "2026-07-19T19:00:00+02:00"
        assert rev.schedule_status == "scheduled"
        sides = uow.identity.appearance_sides(match_id)
        assert sides == {"home": "team-home", "away": "team-away"}
    again = actions.record_match(_req("m:2", "2026-07-19T19:00:00+02:00"))
    assert again.result_refs[0].object_id == match_id


def test_unknown_schedule_is_explicit_never_ingestion_time(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_match(_req("m:unknown", None))
    match_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at is None
        assert rev.schedule_status == "unknown"


def test_existing_match_without_edition_gets_an_immutable_revision(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    first = actions.record_match(_req("m:no-edition", "2026-07-19T19:00:00+02:00"))
    match_id = first.result_refs[0].object_id
    edition = CompetitionEditionRef(
        competition_id="competition-se",
        competition_name="Allsvenskan",
        competition_country="SE",
        competition_kind="football",
        competition_edition_id="competition-edition-se-2026",
        edition_name="Allsvenskan 2026",
        season_label="2026",
    )

    second = actions.record_match(
        replace(
            _req("m:add-edition", "2026-07-19T19:00:00+02:00"),
            competition_edition=edition,
        )
    )

    assert second.status is ActionStatus.COMMITTED
    assert second.result_refs[0].object_id == match_id
    with OntologyUnitOfWork(engine) as uow:
        revision = uow.identity.current_match_revision(match_id)
        assert revision.version == 2
        assert revision.competition_edition_id == edition.competition_edition_id
        assert revision.supersedes_revision_id is not None
