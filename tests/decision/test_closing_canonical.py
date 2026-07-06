"""capture_closing 收盘快照须 canonical 身份(否则与 canonical Read 对不上,CLV 断)。"""
import json

from nutmeg.decision.closing import capture_closing
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-06", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-06", "matchNumStr": "周一094",
    "homeTeamAbbName": "美国", "awayTeamAbbName": "比利时",
    "had": {"h": "2.26", "d": "3.38", "a": "2.56"}}]}]}


class _MO:
    def __init__(self, fair):
        self.fair_probability = fair
        self.line = None


def test_closing_snapshot_uses_canonical_match_id(tmp_path):
    daily = tmp_path / "daily" / "2026-07-06"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    def _live(value, *, run_date, settings=None):
        return {"周一094": {"match_winner": _MO({"home": 0.37, "draw": 0.29, "away": 0.34})}}

    n = capture_closing("2026-07-06", output_dir=tmp_path,
                        taken_at="2026-07-06T20:00:00+08:00", store=store,
                        live_fetcher=_live)
    assert n == 1
    s = [x for x in store.load(MarketSnapshot) if x.kind == "closing"][0]
    assert s.match_id == "M-2026-07-06-美国-比利时"        # canonical,可链 canonical Read
