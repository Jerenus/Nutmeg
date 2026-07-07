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
