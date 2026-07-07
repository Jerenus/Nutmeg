"""M0 端到端冒烟:一场比赛走完 sense→(手造 Read)→校验→结算→因子判决。"""
import json

from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.read_validate import validate_read
from nutmeg.decision.reconcile import settle_read
from nutmeg.decision.scoring import brier
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "leagueAbbName": "世界杯", "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}, "hhad": {}, "ttg": {}, "crs": {}}]}]}


def test_full_chain_on_snapshot(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    # sense(无 bold_odds.json → 欧赔优雅降级只落体彩)
    assert sense_day("2026-07-08", output_dir=tmp_path,
                     taken_at="2026-07-08T15:00:00+08:00", store=store) == 1
    snap = store.load(MarketSnapshot)[0]
    prior = snap.fair["had"]

    # read(手造一个市场锚定+签位激励偏移的 Read,模拟 Claude 产出)
    belief = {"home": prior["home"] - 0.06,
              "draw": prior["draw"] + 0.06, "away": prior["away"]}
    read = Read(read_id="R-092", match_id=snap.match_id, snapshot_id=snap.id,
                made_at="2026-07-08T15:00:00+08:00", judge="claude", market="had",
                prior=prior, belief=belief,
                factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6,
                          "evidence": [{"url": "x", "quote": "y", "at": "z"}]}],
                confidence=3, shadow=False)
    assert validate_read(read, allowed_factors={"seeding_incentive"}) == []
    store.upsert(read)

    # settle(赛果 draw)
    s = settle_read(read, outcome_90="draw", score="1-1", closing=None)
    store.upsert(s)
    assert s.brier == brier(belief, "draw")
    # belief 更看好 draw → 应优于 prior
    assert s.brier < brier(prior, "draw")
