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
    ZucaiMarketSource,
    ZucaiRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

_AT = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)


def _service(kernel) -> ZucaiIssueIngestService:
    factory = ActionService(lambda: OntologyUnitOfWork(kernel.engine))

    def probe(match_id: str, provider: str, as_of: str) -> bool:
        with OntologyUnitOfWork(kernel.engine) as uow:
            return (
                uow.market.snapshot_id_for_source_at(
                    match_id, "md-had", "read_time", provider, as_of
                )
                is not None
            )

    return ZucaiIssueIngestService(
        artifact_ingest=kernel.artifact_ingest,
        entity_actions=EntityActions(factory),
        match_actions=MatchActions(factory),
        market_actions=MarketActions(factory),
        snapshot_probe=probe,
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


def _market_value(rows: list[ZucaiRow]) -> dict:
    return {
        "issue_id": "26110",
        "captured_at": _AT.isoformat(),
        "matches": [
            {"match_no": row.match_no, **(row.odds or {})}
            for row in rows
        ],
    }


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
    status = kernel.status()
    assert status.match_count == 2
    assert status.snapshot_count == 2      # 计数必须对应真实快照行,不许虚报
    with OntologyUnitOfWork(kernel.engine) as uow:
        for match_id in uow.identity.all_match_ids():
            assert uow.identity.current_match_revision(match_id).competition_edition_id


def test_source_artifacts_link_official_and_international_quotes(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(
            1,
            "曼城",
            "伯恩茅斯",
            "英超",
            "2026-08-23",
            {"home": 1.30, "draw": 5.50, "away": 9.00},
        )
    ]
    official = _market_value(rows)
    international = {
        **official,
        "matches": [{"match_no": 1, "home": 1.35, "draw": 5.40, "away": 8.80}],
    }
    request = ZucaiIssueIngestRequest(
        **{
            field: getattr(_request(rows), field)
            for field in ("issue", "rows", "actor_id", "actor_role", "requested_at")
        },
        market_sources=(
            ZucaiMarketSource(
                provider="zucai",
                value=official,
                retrieved_at=_AT,
            ),
            ZucaiMarketSource(
                provider="intl",
                value=international,
                retrieved_at=_AT,
            ),
        ),
    )

    result = _service(kernel).ingest(request)

    assert result.snapshots == 2
    with kernel.engine.connect() as connection:
        rows = connection.exec_driver_sql(
            """
            SELECT q.provider, r.source_name, r.retrieved_at
            FROM market_quotes AS q
            JOIN artifact_retrievals AS r
              ON r.artifact_retrieval_id = q.artifact_retrieval_id
            ORDER BY q.provider, q.selection_id
            """
        ).all()
    assert {(provider, source_name) for provider, source_name, _ in rows} == {
        ("intl", "intl"),
        ("zucai", "zucai"),
    }
    assert {retrieved_at for _, _, retrieved_at in rows} == {_AT.isoformat()}


def test_identical_source_content_at_later_retrieval_adds_timepoint(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(
            1,
            "曼城",
            "伯恩茅斯",
            "英超",
            "2026-08-23",
            {"home": 1.30, "draw": 5.50, "away": 9.00},
        )
    ]
    value = _market_value(rows)
    service = _service(kernel)
    for retrieved_at in (_AT, _AT.replace(hour=9)):
        service.ingest(
            ZucaiIssueIngestRequest(
                **{
                    field: getattr(_request(rows), field)
                    for field in ("issue", "rows", "actor_id", "actor_role")
                },
                requested_at=retrieved_at,
                market_sources=(
                    ZucaiMarketSource(
                        provider="zucai",
                        value=value,
                        retrieved_at=retrieved_at,
                    ),
                ),
            )
        )

    with kernel.engine.connect() as connection:
        snapshot_times = connection.exec_driver_sql(
            "SELECT as_of FROM market_snapshots ORDER BY as_of"
        ).scalars().all()
        retrieval_times = connection.exec_driver_sql(
            "SELECT retrieved_at FROM artifact_retrievals ORDER BY retrieved_at"
        ).scalars().all()
    assert snapshot_times == [_AT.isoformat(), _AT.replace(hour=9).isoformat()]
    assert retrieval_times == [_AT.isoformat(), _AT.replace(hour=9).isoformat()]


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


def test_noncommitted_snapshot_is_not_counted_as_success(
    tmp_path: Path, monkeypatch
) -> None:
    from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus

    kernel = _kernel(tmp_path)
    rows = [
        ZucaiRow(
            1, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.30, "draw": 5.50, "away": 9.00}
        )
    ]

    def rejected(_self, request) -> ActionOutcome:
        return ActionOutcome(
            action_id="ACT-denied",
            action_type="build_market_snapshot",
            status=ActionStatus.REJECTED,
            error_code="permission_denied",
        )

    monkeypatch.setattr(MarketActions, "build_snapshot", rejected)
    result = _service(kernel).ingest(_request(rows))
    assert result.snapshots == 0                       # 拒绝不是入库
    assert any("snapshot_rejected" in item for item in result.skipped)


def test_second_run_adds_an_immutable_read_time_snapshot(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    service = _service(kernel)
    row1 = ZucaiRow(
        1, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.30, "draw": 5.50, "away": 9.00}
    )
    service.ingest(_request([row1]))
    moved = ZucaiRow(
        1, "曼城", "伯恩茅斯", "英超", "2026-08-23", {"home": 1.25, "draw": 5.80, "away": 10.0}
    )
    later = ZucaiIssueIngestRequest(
        issue="26110",
        rows=(moved,),
        actor_id="source:zucai",
        actor_role=ActorRole.CONNECTOR,
        requested_at=_AT.replace(hour=9),
    )
    again = service.ingest(later)
    assert kernel.status().snapshot_count == 2
    assert again.snapshots == 1
    assert again.skipped == ()
