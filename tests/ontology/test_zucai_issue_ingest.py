from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.entity_actions import EntityActions
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.ingest.zucai_issue import (
    ZucaiIssueIngestRequest,
    ZucaiIssueIngestService,
    ZucaiRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

_AT = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)


def _service(kernel) -> ZucaiIssueIngestService:
    factory = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    return ZucaiIssueIngestService(
        entity_actions=EntityActions(factory),
        match_actions=MatchActions(factory),
        market_actions=MarketActions(factory),
    )


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _request(rows) -> ZucaiIssueIngestRequest:
    return ZucaiIssueIngestRequest(
        issue="26110",
        rows=tuple(rows),
        actor_id="source:zucai",
        actor_role=ActorRole.CONNECTOR,
        requested_at=_AT,
    )


def test_ingests_matches_teams_snapshots(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(
            1, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.30, "draw": 5.50, "away": 9.00}
        ),
        ZucaiRow(
            2, "波尔图", "阿罗卡", "葡超", "2026-08-24", {"home": 1.14, "draw": 5.95, "away": 12.0}
        ),
    ]
    result = _service(kernel).ingest(_request(rows))
    assert result.matches == 2 and result.snapshots == 2 and result.teams == 4
    assert result.skipped == ()
    assert kernel.status().match_count == 2


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(
            1, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.30, "draw": 5.50, "away": 9.00}
        )
    ]
    service = _service(kernel)
    service.ingest(_request(rows))
    again = service.ingest(_request(rows))
    assert kernel.status().match_count == 1
    assert again.matches == 1  # resolves to the same match, mints nothing new


def test_missing_odds_or_date_skipped_counted(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(1, "甲", "乙", "英超", "2026-08-23", None),
        ZucaiRow(2, "丙", "丁", "英超", None, {"home": 2.0, "draw": 3.0, "away": 4.0}),
        ZucaiRow(3, "戊", "己", "英超", "2026-08-23", {"home": 2.0, "draw": 3.0, "away": 4.0}),
    ]
    result = _service(kernel).ingest(_request(rows))
    assert result.matches == 1 and len(result.skipped) == 2
    assert any("no_odds" in item for item in result.skipped)
    assert any("no_date" in item for item in result.skipped)


def test_cross_issue_same_match_collapses_to_one(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    service = _service(kernel)
    row = ZucaiRow(
        5, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.30, "draw": 5.50, "away": 9.00}
    )
    service.ingest(_request([row]))
    other_issue = ZucaiIssueIngestRequest(
        issue="26111",
        rows=(
            ZucaiRow(
                9,
                "曼城",
                "伯恩茅斯",
                "英超",
                "2026-08-23",
                {"home": 1.28, "draw": 5.60, "away": 9.50},
            ),
        ),
        actor_id="source:zucai",
        actor_role=ActorRole.CONNECTOR,
        requested_at=_AT,
    )
    service.ingest(other_issue)
    # 同一 canonical(队名+日期) → 同一 kernel match,不复制
    assert kernel.status().match_count == 1


def test_market_day_rerun_with_same_content_is_noop(tmp_path: Path) -> None:
    """同日重跑 am(板面内容未变,requested_at 不同) → 不再报幂等冲突失败。"""
    from nutmeg.ontology.actions.models import ActorRole as _Role
    from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest

    kernel = _kernel(tmp_path)
    sporttery = {
        "matchInfoList": [
            {
                "businessDate": "2026-08-24",
                "subMatchList": [
                    {
                        "matchStatus": "Selling",
                        "businessDate": "2026-08-24",
                        "matchNumStr": "周一001",
                        "matchNum": 7001,
                        "matchId": 2040001,
                        "matchDate": "2026-08-24",
                        "matchTime": "18:00:00",
                        "homeTeamAbbName": "甲",
                        "awayTeamAbbName": "乙",
                        "leagueAbbName": "测试联",
                        "had": {"h": "2.10", "d": "3.30", "a": "3.10"},
                    }
                ],
            }
        ]
    }
    first = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date="2026-08-24",
            sporttery_value=sporttery,
            actor_id="t",
            actor_role=_Role.CONNECTOR,
            requested_at=_AT,
        )
    )
    assert first.matches == 1
    rerun = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date="2026-08-24",
            sporttery_value=sporttery,
            actor_id="t",
            actor_role=_Role.CONNECTOR,
            requested_at=datetime(2026, 8, 24, 7, 0, tzinfo=UTC),
        )
    )
    assert rerun.matches == 1  # 重放解析到同一 match,零冲突异常
