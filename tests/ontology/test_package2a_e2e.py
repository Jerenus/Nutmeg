from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.identity.models import EntityType
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

TWO_MATCHES = {"matchInfoList": [{"businessDate": "2026-07-19", "subMatchList": [
    {"matchStatus": "Selling", "businessDate": "2026-07-19", "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": "2026-07-19", "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}},
    {"matchStatus": "Selling", "businessDate": "2026-07-19", "matchNumStr": "周日104",
     "matchNum": 7104, "matchId": 2040541, "matchDate": "2026-07-20", "matchTime": "03:00:00",
     "homeTeamAbbName": "西班牙", "awayTeamAbbName": "阿根廷", "leagueAbbName": "世界杯",
     "had": {"h": "1.80", "d": "3.60", "a": "4.20"}}]}]}


def test_full_day_has_no_null_identity_and_real_schedule(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=TWO_MATCHES, intl_value=None,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    status = kernel.status()
    assert status.match_count == 2
    assert status.integrity_check == "ok"
    with OntologyUnitOfWork(kernel.engine) as uow:
        for match_id in uow.identity.all_match_ids():
            rev = uow.identity.current_match_revision(match_id)
            assert rev.schedule_status in {"scheduled", "unknown"}
            if rev.schedule_status == "scheduled":
                assert rev.scheduled_at is not None       # never ingestion time
            sides = uow.identity.appearance_sides(match_id)
            assert set(sides) == {"home", "away"}
            for team_id in sides.values():
                assert team_id is not None                 # no silent null identity
        # the early-morning match kept the next calendar day
        wc_match = uow.identity.entity_by_external_id(
            EntityType.MATCH, provider="sporttery", external_id="2040541",
        )
        rev = uow.identity.current_match_revision(wc_match)
        assert rev.scheduled_at.startswith("2026-07-20T03:00")
