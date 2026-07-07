from nutmeg.decision.ontology import MarketSnapshot, Match, Read, Settlement, Ticket
from nutmeg.decision.reconcile import settle_day, settle_tickets
from nutmeg.decision.store import DecisionStore


def _seed(store, *, with_closing):
    # canonical 迁移后 settle_day 经 Match.channel_refs.jczq_match_no 映射赛果竞彩号。
    store.upsert(Match(match_id="M-2026-07-08-周日092", kickoff_at="t",
                       home="墨", away="英",
                       channel_refs={"jczq_match_no": "周日092"}))
    store.upsert(Read(read_id="R-1", match_id="M-2026-07-08-周日092",
                      snapshot_id="S-r", made_at="t", judge="claude", market="had",
                      prior={"home": 0.42, "draw": 0.28, "away": 0.30},
                      belief={"home": 0.36, "draw": 0.34, "away": 0.30}))
    if with_closing:
        store.upsert(MarketSnapshot(
            snapshot_id="S-c", match_id="M-2026-07-08-周日092", taken_at="t2",
            kind="closing", source="apifootball",
            fair={"had": {"home": 0.34, "draw": 0.37, "away": 0.29}}))


def _results():
    # okooo 赛果口径:{竞彩号: {score, had, ...}}
    return {"周日092": {"score": "1:1", "had": "平"}}


def test_settle_day_scores_brier_and_clv(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    n = settle_day(store, run_date="2026-07-08", results=_results(),
                   settled_at="2026-07-09T08:00:00+08:00")
    assert n == 1
    s = store.settlement_for("read", "R-1")
    assert s is not None and s.outcome_90 == "draw"
    assert s.brier is not None and s.clv_pp is not None    # 双轴齐
    assert s.closing_snapshot_id == "S-c"


def test_settle_day_clv_null_without_closing(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=False)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    s = store.settlement_for("read", "R-1")
    assert s.brier is not None and s.clv_pp is None        # 无收盘→CLV null


def test_settle_day_skips_when_no_result(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    n = settle_day(store, run_date="2026-07-08", results={}, settled_at="t")
    # 统一 skip-no-result(防共享库跨通道 clobber):无赛果→不产 Settlement
    assert n == 0 and store.settlement_for("read", "R-1") is None


def test_settle_day_idempotent(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    assert len([s for s in store.load(Settlement) if s.ref_id == "R-1"]) == 1


def test_settle_day_skips_unfinished_matches(tmp_path):
    """okooo 返回未终局行(had 空)→ settle_day 不产 pending 结算,诚实计数 0。"""
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    # okooo 有该场行但无 had/score(比赛未终局)
    n = settle_day(store, run_date="2026-07-08",
                   results={"周日092": {"score": "", "had": ""}}, settled_at="t")
    assert n == 0 and store.settlement_for("read", "R-1") is None


# --- Ticket 结算(spec §2:Settlement 对 Read 和 Ticket 各一条)------------------

_M1 = "M-2026-07-08-墨西哥-英格兰"
_M2 = "M-2026-07-08-荷兰-法国"


def _ticket(tid, legs, structure, stake):
    return Ticket(ticket_id=tid, channel="jczq", made_at="t", legs=legs,
                  structure=structure, stake_yuan=stake)


def _leg(mid, selection, odds, market="had", line=None):
    leg = {"match_id": mid, "market": market, "selection": selection,
           "odds": odds, "bucket": "main"}
    if line is not None:
        leg["line"] = line
    return leg


def test_settle_tickets_single_hit_pnl(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-1", [_leg(_M1, "home", 1.64)], "single", 100))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    assert n == 1
    s = store.settlement_for("ticket", "T-1")
    assert s.hit is True
    assert abs(s.pnl_yuan - 64.0) < 1e-9          # 100×1.64−100
    assert s.settled_at == "t2"


def test_settle_tickets_single_miss_pnl(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-1", [_leg(_M1, "home", 1.64)], "single", 100))
    settle_tickets(store, outcomes={_M1: ("draw", "1:1")}, settled_at="t2")
    s = store.settlement_for("ticket", "T-1")
    assert s.hit is False and s.pnl_yuan == -100.0


def test_settle_tickets_parlay_all_hit(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-p", [_leg(_M1, "home", 1.64), _leg(_M2, "away", 2.75)],
                         "parlay", 60))
    settle_tickets(store, outcomes={_M1: ("home", "2:0"), _M2: ("away", "0:1")},
                   settled_at="t2")
    s = store.settlement_for("ticket", "T-p")
    assert s.hit is True
    assert abs(s.pnl_yuan - (60 * 1.64 * 2.75 - 60)) < 1e-6   # 连乘赔率


def test_settle_tickets_parlay_one_leg_miss(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-p", [_leg(_M1, "home", 1.64), _leg(_M2, "away", 2.75)],
                         "parlay", 60))
    settle_tickets(store, outcomes={_M1: ("home", "2:0"), _M2: ("draw", "1:1")},
                   settled_at="t2")
    s = store.settlement_for("ticket", "T-p")
    assert s.hit is False and s.pnl_yuan == -60.0


def test_settle_tickets_skips_when_any_leg_missing_result(tmp_path):
    """任一 leg 无赛果 → 整票跳过,不产 pending(未终局跳过纪律)。"""
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-p", [_leg(_M1, "home", 1.64), _leg(_M2, "away", 2.75)],
                         "parlay", 60))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    assert n == 0 and store.settlement_for("ticket", "T-p") is None


def test_settle_tickets_idempotent_and_no_clobber(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-1", [_leg(_M1, "home", 1.64)], "single", 100))
    settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    # 重跑不重复、不覆盖既有结算(settled_at 保持首结时刻)
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t3")
    assert n == 0
    setts = [s for s in store.load(Settlement) if s.ref_id == "T-1"]
    assert len(setts) == 1 and setts[0].settled_at == "t2"


def test_settle_tickets_fushi_skipped_m15(tmp_path):
    """structure=fushi(胜负彩/任九复式)M1.5 先跳过——拆票结算未实现,不产伪结果。"""
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-f", [_leg(_M1, "home", 1.64)], "fushi", 400))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    assert n == 0 and store.settlement_for("ticket", "T-f") is None


def test_settle_tickets_hhad_leg_uses_line_and_score(tmp_path):
    """hhad leg 按 90' 净胜球+让球线判(继承 settle_ticket_leg);line 容忍字符串。"""
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-h", [_leg(_M1, "home", 1.74, market="hhad", line="-1")],
                         "single", 100))
    # 净胜1球,line -1 → 0 → 让平,押让胜(home)不中
    settle_tickets(store, outcomes={_M1: ("home", "2:1")}, settled_at="t2")
    s = store.settlement_for("ticket", "T-h")
    assert s.hit is False and s.pnl_yuan == -100.0


def test_settle_day_settles_tickets_alongside_reads(tmp_path):
    """settle_day 对 Read 和 Ticket 各产一条 Settlement(spec §2),计数合并。"""
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    store.upsert(_ticket(
        "T-1", [_leg("M-2026-07-08-周日092", "draw", 3.30)], "single", 40))
    n = settle_day(store, run_date="2026-07-08", results=_results(),
                   settled_at="2026-07-09T08:00:00+08:00")
    assert n == 2                                 # 1 Read + 1 Ticket
    s = store.settlement_for("ticket", "T-1")
    assert s is not None and s.hit is True        # 赛果 1:1 平,押 draw 中
    assert abs(s.pnl_yuan - (40 * 3.30 - 40)) < 1e-6
