# tests/decision/test_market_data.py
from nutmeg.decision.market_data import devig


def test_devig_normalizes_to_one():
    fair = devig({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert abs(sum(fair.values()) - 1.0) < 1e-9
    assert fair["home"] > fair["draw"]          # 短赔=高概率


def test_devig_empty_input():
    assert devig({}) == {}
    assert devig({"home": 0.0}) == {}


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


