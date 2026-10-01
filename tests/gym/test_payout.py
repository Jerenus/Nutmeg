import json
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
        == "single_not_allowed:周六001"                    # 夹具没有 HAFU 池
    assert check_jczq_legal(_jczq_slip([("周六001", "foo", None, ["x"], [5.0])]), board) \
        == "unsupported_market:foo"


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


def test_settle_jczq_hafu_uses_half_time_score(tmp_path: Path) -> None:
    data = _jczq_day(tmp_path)
    results = json.loads((data / "jczq" / "jc-results.json").read_text(encoding="utf-8"))
    results[DAY]["周六001"] = {"match_id": "1", "ft_home": 2, "ft_away": 0, "ht_home": 0,
                              "ht_away": 0}
    (data / "jczq" / "jc-results.json").write_text(json.dumps(results), encoding="utf-8")
    board = load_jczq_board(data, DAY)
    hit = _jczq_slip([("周六001", "hafu", None, ["平胜", "胜胜"], [4.0, 1.9]),
                      ("周六002", "had", None, ["home"], [1.85])], combo=(2,))
    results_only = {**board.results, "周六002": {"outcome_90": "home", "goals_h": 1,
                                                 "goals_a": 0}}
    from nutmeg.decision.betslip import settle_slip

    s = settle_slip(hit, results_only)
    # 半场平全场胜 → "dh"，命中第一个选项（赔率 4.0）
    assert s.won_legs == 2 and s.payout_yuan == pytest.approx(4.0 * 1.85 * 2)


def test_history_board_settles_by_draw_sp_and_rejects_singles(tmp_path: Path) -> None:
    from tests.gym.test_board import _history_data

    board = load_jczq_board(_history_data(tmp_path), "2025-12-14", allow_history=True)
    single = _jczq_slip([("周日001", "had", None, ["home"], [])], combo=(1,))
    assert check_jczq_legal(single, board) == "single_not_allowed:history"
    pair = _jczq_slip([("周日001", "had", None, ["home"], []),
                       ("周日002", "had", None, ["draw"], [])], combo=(2,))
    assert check_jczq_legal(pair, board) is None
    s = settle_jczq(pair, board)
    assert s.pending_legs == 1 and s.payout_yuan is None          # 周日002 无 SP → 未结
    both = _jczq_slip([("周日001", "had", None, ["home", "draw"], []),
                       ("周日003", "had", None, ["home"], [])], combo=(2,))
    s2 = settle_jczq(both, board)
    assert s2.won_legs == 2 and s2.payout_yuan == pytest.approx(1.45 * 1.3 * 2)
    miss = _jczq_slip([("周日001", "had", None, ["draw"], []),
                       ("周日003", "had", None, ["home"], [])], combo=(2,))
    assert settle_jczq(miss, board).payout_yuan == 0.0
