# tests/decision/test_reconcile.py
from nutmeg.decision.reconcile import settle_ticket_leg


def test_settle_had_leg_win_and_loss():
    win = settle_ticket_leg(market="had", pick="home", line=None,
                            outcome_90="home", goals_h=2, goals_a=0)
    assert win == "home"                      # had 直接方向
    lose = settle_ticket_leg(market="had", pick="home", line=None,
                             outcome_90="draw", goals_h=1, goals_a=1)
    assert lose == "draw"


def test_settle_hhad_leg_with_line():
    # 净胜1,让球线-1 → 1+(-1)=0 → 让平
    r = settle_ticket_leg(market="hhad", pick="home", line=-1.0,
                          outcome_90="home", goals_h=2, goals_a=1)
    assert r == "draw"


def test_settle_hhad_aet_is_draw_margin_zero():
    # AET 90' 必平,margin=0,+line
    r = settle_ticket_leg(market="hhad", pick="away", line=-2.0,
                          outcome_90="draw", goals_h=None, goals_a=None)
    assert r == "away"                        # 0+(-2)<0 → 让负


def test_settle_hhad_without_line_pending():
    assert settle_ticket_leg(market="hhad", pick="home", line=None,
                             outcome_90="home", goals_h=2, goals_a=0) is None


def test_settle_unknown_pick_pending_not_loss():
    assert settle_ticket_leg(market="hhad", pick="受让平未知", line=-1.0,
                             outcome_90="home", goals_h=2, goals_a=0) is None


def test_settle_had_leg_accepts_sfc_outcome_codes():
    """day.results 的 results-90.json 用 3/1/0 写 outcome_90;had 腿按 home/draw/away 判。
    2026-09-28 出生事故:9/26 J1 五条 had 主胜腿全开主胜却被判 ✗(实际键 "3" ≠ pick "home")。"""
    assert settle_ticket_leg(market="had", pick="home", line=None,
                             outcome_90="3", goals_h=2, goals_a=0) == "home"
    assert settle_ticket_leg(market="had", pick="draw", line=None,
                             outcome_90="1", goals_h=1, goals_a=1) == "draw"
    assert settle_ticket_leg(market="hhad", pick="away", line=1.0,
                             outcome_90="1", goals_h=0, goals_a=0) == "home"
