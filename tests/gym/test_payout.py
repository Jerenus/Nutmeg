from pathlib import Path

import pytest

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.gym.board import load_jczq_board, load_zucai_issue
from nutmeg.gym.payout import check_jczq_legal, settle_jczq, settle_zucai, zucai_winning_notes
from tests.gym.test_board import DAY, _jczq_day, _zucai_issue


def _jczq_slip(picks, combo=None, multiplier=1):
    legs = [SlipLeg(key=code, name=code, market=market, line=line,
                    selections=tuple(sel), odds=tuple(odds), fair=None)
            for code, market, line, sel, odds in picks]
    return BetSlip(slip_id="t", channel="jczq", placed_at=DAY, legs=legs, multiplier=multiplier,
                   combo_sizes=tuple(combo or ()))


def test_zucai_winning_notes_first_and_second_prize_with_void() -> None:
    faces = {"1": "31", "2": "3", "3": "310"}                      # 2×1×3 = 6 注
    assert zucai_winning_notes(faces, {"1": "3", "2": "3", "3": "0"}, void=set()) == (1, 3)
    assert zucai_winning_notes(faces, {"1": "0", "2": "3", "3": "0"}, void=set()) == (0, 2)
    assert zucai_winning_notes(faces, {"1": "3", "2": "1", "3": "0"}, void=set()) == (0, 1)
    assert zucai_winning_notes(faces, {"1": "0", "2": "1", "3": "0"}, void=set()) == (0, 0)
    assert zucai_winning_notes(faces, {"1": "*", "2": "3", "3": "0"}, void={1}) == (2, 4)


def test_jczq_legality_requires_two_legs_unless_single_open(tmp_path: Path) -> None:
    board = load_jczq_board(_jczq_day(tmp_path), DAY)
    single_ok = _jczq_slip([("周六001", "had", None, ["home"], [1.85])], combo=(1,))
    assert check_jczq_legal(single_ok, board) is None
    single_bad = _jczq_slip([("周六002", "had", None, ["home"], [1.85])], combo=(1,))
    assert check_jczq_legal(single_bad, board) == "single_not_allowed:周六002"
    parlay = _jczq_slip([("周六001", "had", None, ["home"], [1.85]),
                         ("周六002", "had", None, ["home", "draw"], [1.85, 3.4])], combo=(2,))
    assert check_jczq_legal(parlay, board) is None
    assert check_jczq_legal(_jczq_slip([("周六009", "had", None, ["home"], [2.0])]), board) \
        == "unknown_leg:周六009"
    assert check_jczq_legal(_jczq_slip([("周六001", "hafu", None, ["hh"], [5.0])]), board) \
        == "unsupported_market:hafu"


def test_settle_jczq_pays_odds_product_times_two_per_note(tmp_path: Path) -> None:
    board = load_jczq_board(_jczq_day(tmp_path), DAY)
    # 周六001 主胜 2-0 ✓；周六002 无赛果 → 2 串 1 未结；单关结
    single = _jczq_slip([("周六001", "had", None, ["home"], [1.85])], combo=(1,), multiplier=2)
    s = settle_jczq(single, board)
    assert s.combos_won == 1 and s.payout_yuan == pytest.approx(1.85 * 2 * 2)
    hhad = _jczq_slip([("周六001", "hhad", -1.0, ["home"], [5.75])], combo=(1,))
    assert settle_jczq(hhad, board).payout_yuan == pytest.approx(5.75 * 2)   # 让一球 2-0 仍胜
    pending = _jczq_slip([("周六001", "had", None, ["home"], [1.85]),
                          ("周六002", "had", None, ["home"], [1.85])], combo=(2,))
    assert settle_jczq(pending, board).payout_yuan is None


def test_settle_zucai_pays_official_prize_per_winning_note(tmp_path: Path) -> None:
    issue = load_zucai_issue(_zucai_issue(tmp_path), "26127")   # 3 3 0 0 3 3 1 3 3 0 3 0 3 *
    renjiu = BetSlip(slip_id="r", channel="renjiu", placed_at="2026-09-16", legs=[],
                     faces={"1": "3", "2": "3", "3": "0", "4": "0", "5": "3", "6": "3",
                            "7": "1", "8": "3", "9": "3"})
    out = settle_zucai(renjiu, issue)
    assert out["first_notes"] == 1 and out["payout"] == 176.0 and out["stake"] == 2
    sfc = BetSlip(slip_id="s", channel="shengfucai", placed_at="2026-09-16", legs=[],
                  faces={"1": "3", "2": "3", "3": "0", "4": "0", "5": "3", "6": "3", "7": "1",
                         "8": "3", "9": "3", "10": "0", "11": "3", "12": "0", "13": "31",
                         "14": "310"})
    out = settle_zucai(sfc, issue)       # 场13 双选含正解；场14 作废全包 3 面全算中
    assert out["first_notes"] == 3 and out["second_notes"] == 3
    assert out["payout"] == pytest.approx(3 * 17339.0 + 3 * 319.0)
    short = BetSlip(slip_id="x", channel="renjiu", placed_at="2026-09-16", legs=[],
                    faces={"1": "3"})
    assert settle_zucai(short, issue)["skipped_reason"].startswith("renjiu_needs_9")
    assert settle_zucai(renjiu, issue.visible())["skipped_reason"] == "no_official_prize"
