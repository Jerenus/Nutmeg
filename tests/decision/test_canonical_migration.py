import json

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-06", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-06", "matchNumStr": "周一093",
    "homeTeamAbbName": "葡萄牙", "awayTeamAbbName": "西班牙",
    "had": {"h": "4.00", "d": "3.35", "a": "1.72"}}]}]}


def test_jczq_sense_uses_canonical_id_and_channel_ref(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-06"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    import nutmeg.decision.sense as sm
    monkeypatch.setattr(sm, "_load_euro_bold_odds", lambda rd, od: {})
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-06", output_dir=tmp_path, taken_at="t", store=store)
    m = store.load(Match)[0]
    assert m.match_id == "M-2026-07-06-葡萄牙-西班牙"           # canonical
    assert m.channel_refs.get("jczq_match_no") == "周一093"     # 竞彩号进 ref
    s = store.load(MarketSnapshot)[0]
    assert s.match_id == "M-2026-07-06-葡萄牙-西班牙"           # snapshot 同 canonical
