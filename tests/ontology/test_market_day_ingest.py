from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

SPORTTERY = {"matchInfoList": [{"businessDate": "2026-07-19", "subMatchList": [
    {"matchStatus": "Selling", "businessDate": "2026-07-19", "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": "2026-07-19", "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def test_ingest_market_day_builds_matches_and_snapshots(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    outcome = kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=SPORTTERY, intl_value=BOLD,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.matches == 1
    assert outcome.snapshots >= 1
    status = kernel.status()
    assert status.match_count == 1
    assert status.team_count >= 2
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at.startswith("2026-07-19T23:30:00")
        assert rev.schedule_status == "scheduled"
        fair = uow.market.latest_fair(match_id, "md-had")
        assert abs(sum(fair.values()) - 1.0) < 1e-9


def test_ingest_is_idempotent_on_rerun(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    req = MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=SPORTTERY, intl_value=BOLD,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )
    kernel.market_day_ingest.ingest(req)
    kernel.market_day_ingest.ingest(req)
    assert kernel.status().match_count == 1
