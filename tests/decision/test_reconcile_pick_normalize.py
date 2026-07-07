"""票面 selection 中文可读名规约(7/07 修复:7/06 起 legs 用"让胜·xxx"式 selection,
旧 settle_ticket_leg 只认 home/draw/away → 整票被静默跳过永不入账,违反"没入账=没打")。"""
from nutmeg.decision.ontology import Ticket
from nutmeg.decision.reconcile import normalize_pick, settle_tickets
from nutmeg.decision.store import DecisionStore

_M1 = "M-2026-07-07-阿根廷-埃及"
_M2 = "M-2026-07-07-瑞士-哥伦比亚"


def _ticket(tid, legs, structure="single", stake=60):
    return Ticket(ticket_id=tid, channel="jczq", made_at="t", legs=legs,
                  structure=structure, stake_yuan=stake)


def _leg(mid, selection, odds, market="had", line=None):
    leg = {"match_id": mid, "market": market, "selection": selection,
           "odds": odds, "bucket": "parlay"}
    if line is not None:
        leg["line"] = line
    return leg


def test_normalize_pick_chinese_prefixes():
    assert normalize_pick("主胜·阿根廷90分钟") == "home"
    assert normalize_pick("让胜·瑞士+1不败") == "home"
    assert normalize_pick("让平·西净胜1") == "draw"
    assert normalize_pick("让负·杰尔+1不败") == "away"
    assert normalize_pick("平") == "draw"
    assert normalize_pick("客胜") == "away"
    assert normalize_pick("home") == "home"          # 裸键向后兼容
    assert normalize_pick("随便什么") is None


def test_settle_tickets_chinese_had_selection_hit(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-1", [_leg(_M1, "主胜·阿根廷90分钟", 1.22)]))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    assert n == 1
    s = store.settlement_for("ticket", "T-1")
    assert s.hit is True and s.pnl_yuan == round(60 * 1.22 - 60, 2)


def test_settle_tickets_chinese_hhad_parlay(tmp_path):
    """让胜·瑞士+1(1:1→adj+1→home 中) × 让负·让-1(1:1→adj-1→away 中)→ 整票 hit。"""
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-2", [
        _leg(_M2, "让胜·瑞士+1不败", 1.55, market="hhad", line="+1"),
        _leg(_M1, "让负·杰尔+1不败", 1.50, market="hhad", line="-1"),
    ], structure="parlay"))
    n = settle_tickets(store, outcomes={_M1: ("draw", "1:1"), _M2: ("draw", "1:1")},
                       settled_at="t2")
    assert n == 1
    s = store.settlement_for("ticket", "T-2")
    assert s.hit is True


def test_settle_tickets_chinese_selection_miss(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-3", [_leg(_M1, "主胜·阿根廷90分钟", 1.22)]))
    settle_tickets(store, outcomes={_M1: ("draw", "1:1")}, settled_at="t2")
    s = store.settlement_for("ticket", "T-3")
    assert s.hit is False and s.pnl_yuan == -60.0


def test_settle_tickets_unknown_selection_still_skips(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-4", [_leg(_M1, "谜之玩法", 2.0)]))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0")}, settled_at="t2")
    assert n == 0 and store.settlement_for("ticket", "T-4") is None


# --- ttg/crs 腿结算(2026-07-07:进球轴/比分表达进票面后必须可对账) ---------------


def test_settle_tickets_ttg_leg_hit_and_miss(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-ttg1", [_leg(_M1, "2球", 3.35, market="ttg")]))
    store.upsert(_ticket("T-ttg2", [_leg(_M2, "3球", 3.40, market="ttg")]))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0"),   # 总进球2 → hit
                                        _M2: ("draw", "1:1")},  # 总进球2 → miss
                       settled_at="t2")
    assert n == 2
    assert store.settlement_for("ticket", "T-ttg1").hit is True
    assert store.settlement_for("ticket", "T-ttg2").hit is False


def test_settle_tickets_ttg_seven_plus_cap(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-ttg7", [_leg(_M1, "7+球", 17.0, market="ttg")]))
    settle_tickets(store, outcomes={_M1: ("home", "5:4")}, settled_at="t2")
    assert store.settlement_for("ticket", "T-ttg7").hit is True


def test_settle_tickets_crs_leg(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-crs1", [_leg(_M1, "2:1", 8.0, market="crs")]))
    store.upsert(_ticket("T-crs2", [_leg(_M2, "1:1", 6.0, market="crs")]))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:1"),
                                        _M2: ("home", "2:1")}, settled_at="t2")
    assert n == 2
    assert store.settlement_for("ticket", "T-crs1").hit is True
    assert store.settlement_for("ticket", "T-crs2").hit is False


def test_settle_tickets_mixed_market_parlay(tmp_path):
    """票1 型组合:ttg+crs+hhad 混合 4 串 1 整票可结算。"""
    store = DecisionStore(tmp_path)
    store.upsert(_ticket("T-mix", [
        _leg(_M1, "2球", 3.35, market="ttg"),
        _leg(_M2, "让胜·瑞士+1", 1.55, market="hhad", line="+1"),
    ], structure="parlay"))
    n = settle_tickets(store, outcomes={_M1: ("home", "2:0"),
                                        _M2: ("draw", "1:1")}, settled_at="t2")
    assert n == 1
    s = store.settlement_for("ticket", "T-mix")
    assert s.hit is True and s.pnl_yuan == round(60 * 3.35 * 1.55 - 60, 2)
