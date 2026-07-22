import copy
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-22"


def _sub(no, mid, home, away, h, d, a):
    return {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": no,
            "matchNum": 7000, "matchId": mid, "matchDate": DATE, "matchTime": "19:30:00",
            "homeTeamAbbName": home, "awayTeamAbbName": away, "leagueAbbName": "K联赛",
            "had": {"h": h, "d": d, "a": a}}


MORNING = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    _sub("周三001", 2050001, "光州FC", "金泉尚武", "3.60", "3.20", "1.85")]}]}


def test_intraday_board_update_adds_new_and_keeps_morning_anchor(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()

    def _req(value):
        return MarketDayIngestRequest(
            business_date=DATE, sporttery_value=value, intl_value=None,
            actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
            requested_at=datetime(2026, 7, 22, 2, tzinfo=UTC))

    kernel.market_day_ingest.ingest(_req(MORNING))
    with OntologyUnitOfWork(kernel.engine) as uow:
        [m1] = uow.identity.all_match_ids()
        morning_fair = uow.market.latest_fair(m1, "md-had")

    # 午盘补挂一场,且原场赔率已动 —— 重抓入库必须不崩
    noon = copy.deepcopy(MORNING)
    noon["matchInfoList"][0]["subMatchList"][0]["had"] = {"h": "3.40", "d": "3.25", "a": "1.92"}
    noon["matchInfoList"][0]["subMatchList"].append(
        _sub("周三002", 2050002, "富川FC", "安养FC", "3.20", "3.05", "2.35"))
    result = kernel.market_day_ingest.ingest(_req(noon))
    assert result.matches == 2                        # 全盘可见

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.identity.count_matches() == 2      # 新场入库
        assert uow.market.latest_fair(m1, "md-had") == morning_fair   # 早盘锚保留

    # 三跑同内容 → 纯 replay 不崩不重复
    kernel.market_day_ingest.ingest(_req(noon))
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.identity.count_matches() == 2
