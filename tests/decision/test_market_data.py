# tests/decision/test_market_data.py
from nutmeg.decision.market_data import (
    devig,
    fair_1x2,
    snapshots_from_sporttery,
)
from nutmeg.decision.ontology import MarketSnapshot


def test_devig_normalizes_to_one():
    fair = devig({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert abs(sum(fair.values()) - 1.0) < 1e-9
    assert fair["home"] > fair["draw"]          # 短赔=高概率


def test_devig_empty_input():
    assert devig({}) == {}
    assert devig({"home": 0.0}) == {}


def test_fair_1x2_hard_keyed():
    fair = fair_1x2({"home": 2.03, "draw": 3.30, "away": 3.55})
    assert set(fair) == {"home", "draw", "away"}
    assert abs(sum(fair.values()) - 1.0) < 1e-6


_SELLING = {
    "matchInfoList": [{
        "businessDate": "2026-07-08",
        "subMatchList": [{
            "matchStatus": "Selling", "businessDate": "2026-07-08",
            "matchNumStr": "周日092", "leagueAbbName": "世界杯",
            "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
            "had": {"h": "2.03", "d": "3.30", "a": "3.55"},
            "hhad": {"h": "1.74", "d": "3.55", "a": "4.20",
                     "goalLineValue": "-1.00"},
            "ttg": {}, "crs": {},
        }],
    }]
}


def test_snapshots_from_sporttery_produces_marketsnapshot(tmp_path):
    snaps = snapshots_from_sporttery(
        _SELLING, run_date="2026-07-08", taken_at="2026-07-08T15:00:00+08:00",
        source="sporttery", kind="read_time",
    )
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.snapshot_id.startswith("S-")
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6
    assert s.lines["hhad_line"] == -1.0
    # 净化断言:结构上没有 tags / 信号字段
    assert not hasattr(s, "tags")
    assert "tags" not in s.to_dict()


def test_snapshots_skip_non_selling(tmp_path):
    board = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [
        {"matchStatus": "Closed", "businessDate": "2026-07-08",
         "matchNumStr": "周日091", "had": {"h": "1.5", "d": "4", "a": "6"}}]}]}
    assert snapshots_from_sporttery(board, run_date="2026-07-08",
                                    taken_at="t", source="sporttery",
                                    kind="read_time") == []
