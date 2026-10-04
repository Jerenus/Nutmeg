"""票面 selection 中文可读名规约(7/07 修复:7/06 起 legs 用"让胜·xxx"式 selection,
旧 settle_ticket_leg 只认 home/draw/away → 整票被静默跳过永不入账,违反"没入账=没打")。"""
from nutmeg.decision.ontology import Ticket
from nutmeg.decision.reconcile import normalize_pick

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


# --- ttg/crs 腿结算(2026-07-07:进球轴/比分表达进票面后必须可对账) ---------------


def test_hafu_selection_normalizes_chinese_pairs_and_codes():
    from nutmeg.decision.reconcile import normalize_selection, settle_ticket_leg

    assert normalize_selection("hafu", "胜胜") == "hh"
    assert normalize_selection("hafu", "负胜·逆转") == "ah"
    assert normalize_selection("hafu", "DH") == "dh"
    assert normalize_selection("hafu", "胜") is None
    assert settle_ticket_leg(market="hafu", pick="dh", line=None, outcome_90="home", goals_h=2,
                             goals_a=0, ht_h=0, ht_a=0) == "dh"
    assert settle_ticket_leg(market="hafu", pick="dh", line=None, outcome_90="home", goals_h=2,
                             goals_a=0) is None                      # 缺半场比分 → pending
