from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository import schema, schema_market
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.repository import ProductReadRepository

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
        assert rev.competition_edition_id is not None
        assert rev.scheduled_at.startswith("2026-07-19T23:30:00")
        assert rev.schedule_status == "scheduled"
        fair = uow.market.latest_fair(match_id, "md-had")
        assert abs(sum(fair.values()) - 1.0) < 1e-9


def test_unknown_competition_stays_explicitly_unresolved(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    unknown = {
        "matchInfoList": [
            {
                "businessDate": "2026-07-19",
                "subMatchList": [
                    {
                        **SPORTTERY["matchInfoList"][0]["subMatchList"][0],
                        "leagueAbbName": "未登记测试联赛",
                    }
                ],
            }
        ]
    }

    kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date="2026-07-19",
            sporttery_value=unknown,
            actor_id="source:sporttery",
            actor_role=ActorRole.CONNECTOR,
            requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
        )
    )

    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
        assert uow.identity.current_match_revision(match_id).competition_edition_id is None


def test_sporttery_snapshot_as_of_is_retrieval_time_not_kickoff(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    retrieved_at = datetime(2026, 7, 19, 8, tzinfo=UTC)

    kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date="2026-07-19",
            sporttery_value=SPORTTERY,
            actor_id="source:sporttery",
            actor_role=ActorRole.CONNECTOR,
            requested_at=retrieved_at,
        )
    )

    with kernel.engine.connect() as connection:
        snapshot_as_of = connection.scalar(
            select(schema_market.market_snapshots.c.as_of)
        )
    assert snapshot_as_of == retrieved_at.isoformat()
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    [timeline] = ProductReadRepository(kernel.engine).market_timeline(
        match_id,
        "md-had",
        retrieved_at.isoformat(),
    )
    assert timeline["as_of"] == retrieved_at.isoformat()
    assert {lineage["source_name"] for lineage in timeline["quote_lineage"]} == {"sporttery"}


def test_unchanged_market_payload_records_a_new_retrieval_time(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    first_at = datetime(2026, 7, 19, 8, tzinfo=UTC)
    second_at = datetime(2026, 7, 19, 9, tzinfo=UTC)

    for requested_at in (first_at, second_at):
        kernel.market_day_ingest.ingest(
            MarketDayIngestRequest(
                business_date="2026-07-19",
                sporttery_value=SPORTTERY,
                actor_id="source:sporttery",
                actor_role=ActorRole.CONNECTOR,
                requested_at=requested_at,
            )
        )

    with kernel.engine.connect() as connection:
        snapshot_times = tuple(
            connection.execute(
                select(schema_market.market_snapshots.c.as_of).order_by(
                    schema_market.market_snapshots.c.as_of
                )
            ).scalars()
        )
        retrieval_count = connection.scalar(
            select(func.count()).select_from(schema.artifact_retrievals)
        )
    assert snapshot_times == (first_at.isoformat(), second_at.isoformat())
    assert retrieval_count == 2


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


def test_board_matches_windows_by_instant_not_by_offset_string(tmp_path: Path) -> None:
    """竞彩 scheduled_at 存成 +08:00 字符串，窗口边界是 UTC 字符串；字典序比较把北京时间
    16:00 后开球的场挤到第二天（10-06 周二 19:00/19:35/22:00 三场在当天工作台与回放里消失）。"""
    from nutmeg.interfaces.decision_web_kernel import _day_window_utc

    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=SPORTTERY,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    repo = ProductReadRepository(kernel.engine)
    as_of = datetime(2026, 7, 20, tzinfo=UTC).isoformat()
    on_day = repo.board_matches(*_day_window_utc("2026-07-19"), as_of)
    next_day = repo.board_matches(*_day_window_utc("2026-07-20"), as_of)
    assert len(on_day) == 1          # 23:30 北京 = 15:30Z，属于 07-19
    assert next_day == []
