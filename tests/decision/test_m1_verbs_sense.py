"""M1 operationalization: decision-sense 走 sense_day,产体彩+欧赔两源快照。"""
import json

from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.verbs import run_sense

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


def test_run_sense_produces_euro_anchor(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")

    class _MO:
        def __init__(self, fair):
            self.fair_probability = fair
            self.line = None

    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(
        sense_mod, "_load_euro_bold_odds",
        lambda rd, od: {"周日092": {"match_winner":
                                    _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}})
    run_sense("2026-07-08", tmp_path, "2026-07-08T15:00:00+08:00")
    sources = {s.source for s in DecisionStore(tmp_path / "decision").load(MarketSnapshot)}
    assert sources == {"sporttery", "apifootball"}   # 两源,含欧赔锚
