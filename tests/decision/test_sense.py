# tests/decision/test_sense.py
import json

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "leagueAbbName": "世界杯", "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"},
    "hhad": {"h": "1.74", "d": "3.55", "a": "4.20", "goalLineValue": "-1.00"},
    "ttg": {}, "crs": {}}]}]}


def test_sense_persists_match_and_snapshot(tmp_path):
    # 造一个已存 sporttery 快照(无 bold_odds.json → 欧赔优雅降级只落体彩)
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    n = sense_day("2026-07-08", output_dir=tmp_path,
                  taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1
    assert len(store.load(Match)) == 1
    assert len(store.load(MarketSnapshot)) == 1
    assert store.load(MarketSnapshot)[0].kind == "read_time"


def test_sense_idempotent_on_rerun(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-08", output_dir=tmp_path,
              taken_at="2026-07-08T15:00:00+08:00", store=store)
    sense_day("2026-07-08", output_dir=tmp_path,
              taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert len(store.load(MarketSnapshot)) == 1     # 幂等


def test_sense_no_snapshot_returns_zero(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    assert sense_day("2026-07-08", output_dir=tmp_path,
                     taken_at="t", store=store) == 0


def test_upsert_match_merged_preserves_resolved_ids_and_competition(tmp_path):
    """第二通道(zucai)的未解析 Match 不得抹掉第一通道已解析的 id/联赛名。"""
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    upsert_match_merged(store, Match(
        match_id="M-1", kickoff_at="t", home="h", away="a", competition="瑞超",
        home_team_id="swe-hammarby", away_team_id="swe-kalmar",
        competition_id="swe-allsvenskan",
        channel_refs={"jczq_match_no": "周三001"}))
    upsert_match_merged(store, Match(
        match_id="M-1", kickoff_at="t", home="h", away="a", competition="",
        channel_refs={"zucai": {"issue": "26100", "index": 3}}))
    merged = store.get(Match, "M-1")
    assert merged.competition == "瑞超"
    assert merged.home_team_id == "swe-hammarby"
    assert merged.competition_id == "swe-allsvenskan"
    assert merged.channel_refs["jczq_match_no"] == "周三001"
    assert merged.channel_refs["zucai"]["issue"] == "26100"


def test_match_for_snapshot_fills_competition_and_resolved_ids():
    """修 sense 丢 competition 的既有数据丢失 + 策展 resolve(未命中 None 不伪造)。"""
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import MarketSnapshot
    from nutmeg.decision.sense import _match_for_snapshot
    run_date = "2026-07-08"
    mid = canonical_match_id("荷兰", "法国", run_date)
    snap = MarketSnapshot(snapshot_id="S-1", match_id=mid, taken_at="t",
                          kind="read_time", source="sporttery")
    value = {"matchInfoList": [{"subMatchList": [{
        "matchNumStr": "周三001", "leagueAbbName": "世界杯",
        "homeTeamAbbName": "荷兰", "awayTeamAbbName": "法国"}]}]}
    m = _match_for_snapshot(snap, value, run_date)
    assert m.competition == "世界杯"                  # 之前被硬编码 "" 丢掉
    assert m.home_team_id == "netherlands"           # 国家队别名表命中
    assert m.away_team_id == "france"
    assert m.competition_id is None                  # 世界杯无联赛实体:未命中→None+log
