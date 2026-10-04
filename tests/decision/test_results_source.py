
from nutmeg.decision.ontology_adapter import _normalize_score

DATE = "2026-07-19"
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周三001",
     "matchNum": 7001, "matchId": 2050001, "matchDate": DATE, "matchTime": "19:30:00",
     "homeTeamAbbName": "光州FC", "awayTeamAbbName": "金泉尚武", "leagueAbbName": "K联赛",
     "had": {"h": "3.60", "d": "3.20", "a": "1.85"}}]}]}


def test_normalize_score_variants() -> None:
    assert _normalize_score("2-1") == "2-1"
    assert _normalize_score("2:1") == "2-1"
    assert _normalize_score("2：1") == "2-1"
    assert _normalize_score("home") == "1-0"
    assert _normalize_score("") is None
    assert _normalize_score(None) is None
    assert _normalize_score("abandoned") is None


