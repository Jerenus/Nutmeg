"""传统足彩通道端到端(spec §3 一个信念层两个通道):
sense_zucai(注入 loader)+ 竞彩 sense_day → 手造 divergent Read → 通用结算
settle_reads_for_matches → run_calibrate;断言 zucai 场的 Read 与竞彩场混在
**同一因子校准**,且重叠的同一场真实比赛(阿根廷vs埃及)canonical 去重成一个 Match。
"""
import json

from nutmeg.decision.calibrate import run_calibrate
from nutmeg.decision.ontology import Match, Read
from nutmeg.decision.reconcile import settle_reads_for_matches
from nutmeg.decision.sense import sense_day
from nutmeg.decision.sense_zucai import sense_zucai
from nutmeg.decision.store import DecisionStore

# 竞彩盘:阿根廷vs埃及(与 zucai 重叠) + 葡萄牙vs西班牙(竞彩独有)
_BOARD = {"matchInfoList": [{"businessDate": "2026-07-06", "subMatchList": [
    {"matchStatus": "Selling", "businessDate": "2026-07-06", "matchNumStr": "周一093",
     "homeTeamAbbName": "阿根廷", "awayTeamAbbName": "埃及",
     "had": {"h": "1.30", "d": "4.50", "a": "9.00"}},
    {"matchStatus": "Selling", "businessDate": "2026-07-06", "matchNumStr": "周一094",
     "homeTeamAbbName": "葡萄牙", "awayTeamAbbName": "西班牙",
     "had": {"h": "2.40", "d": "3.30", "a": "2.90"}},
]}]}


class _ZM:
    def __init__(self, no, h, a):
        self.match_no = no
        self.home_team = h
        self.away_team = a


def _zucai_loader(issue, output_dir):
    # 阿根廷vs埃及(与竞彩重叠) + 瑞士vs哥伦比亚(zucai 独有)
    return (
        [_ZM(3, "阿根廷", "埃及"), _ZM(4, "瑞士", "哥伦比亚")],
        {3: {"home": 1.28, "draw": 4.60, "away": 9.50},
         4: {"home": 2.05, "draw": 3.25, "away": 3.70}},
        {3: "2026-07-06", 4: "2026-07-06"},
    )


def test_zucai_and_jczq_reads_share_one_belief_layer(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-06"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    import nutmeg.decision.sense as sm
    monkeypatch.setattr(sm, "_load_euro_bold_odds", lambda rd, od: {})

    store = DecisionStore(tmp_path / "decision")
    # 两个通道感知进**同一 store**(共享信念层)
    assert sense_zucai("26091", output_dir=tmp_path, taken_at="t", store=store,
                       loader=_zucai_loader) == 2
    assert sense_day("2026-07-06", output_dir=tmp_path, taken_at="t",
                     store=store) == 2

    # canonical 去重:重叠的阿根廷vs埃及只 1 个 Match(不是竞彩+zucai 两个),
    # 且 channel_refs 合并两通道号(spec §2 一场多通道)
    matches = {m.match_id: m for m in store.load(Match)}
    assert len(matches) == 3                                   # 4 场 −1 重叠 = 3 canonical
    overlap = matches["M-2026-07-06-阿根廷-埃及"]
    assert overlap.channel_refs.get("jczq_match_no") == "周一093"
    assert overlap.channel_refs.get("zucai") == {"issue": "26091", "index": 3}

    # 手造两条 divergent Read:一条 zucai 独有场、一条竞彩独有场,同一因子
    store.upsert(Read(
        read_id="R-z-swi", match_id="M-2026-07-06-瑞士-哥伦比亚",
        snapshot_id="S-z", made_at="t", judge="claude", market="had",
        prior={"home": 0.45, "draw": 0.30, "away": 0.25},
        belief={"home": 0.56, "draw": 0.26, "away": 0.18},
        factors=[{"factor_id": "seeding_incentive", "direction": "home",
                  "weight_pp": 6}]))
    store.upsert(Read(
        read_id="R-j-por", match_id="M-2026-07-06-葡萄牙-西班牙",
        snapshot_id="S-j", made_at="t", judge="gpt", market="had",
        prior={"home": 0.40, "draw": 0.30, "away": 0.30},
        belief={"home": 0.33, "draw": 0.32, "away": 0.35},
        factors=[{"factor_id": "seeding_incentive", "direction": "away",
                  "weight_pp": 5}]))

    # 通用结算(canonical 键,竞彩/zucai 通用):两条 Read 一并结算
    n = settle_reads_for_matches(store, outcomes={
        "M-2026-07-06-瑞士-哥伦比亚": ("home", "2-1"),
        "M-2026-07-06-葡萄牙-西班牙": ("away", "0-1"),
    }, settled_at="t2")
    assert n == 2
    assert store.settlement_for("read", "R-z-swi").brier is not None
    assert store.settlement_for("read", "R-j-por").brier is not None

    # run_calibrate:zucai 场的 Read 与竞彩场的 Read 进**同一因子**校准
    verdicts = run_calibrate(store, as_of="2026-07-06")
    seeding = [v for v in verdicts if v.factor_id == "seeding_incentive"]
    assert seeding, "seeding_incentive 因子未进校准"
    assert seeding[0].n_reads == 2        # 竞彩场 + zucai 场混在同一因子样本
