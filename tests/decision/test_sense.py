# tests/decision/test_sense.py
import json

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.sense import sense_from_snapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "leagueAbbName": "世界杯", "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"},
    "hhad": {"h": "1.74", "d": "3.55", "a": "4.20", "goalLineValue": "-1.00"},
    "ttg": {}, "crs": {}}]}]}


def test_sense_persists_match_and_snapshot(tmp_path):
    # 造一个已存 sporttery 快照
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    n = sense_from_snapshot("2026-07-08", output_dir=tmp_path,
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
    sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T15:00:00+08:00", store=store)
    sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert len(store.load(MarketSnapshot)) == 1     # 幂等


def test_sense_no_snapshot_returns_zero(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    assert sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                               taken_at="t", store=store) == 0
