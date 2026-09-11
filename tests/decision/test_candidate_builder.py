# tests/decision/test_candidate_builder.py
"""候选穷举与替换报告。只做确定性算术——不推荐、不排除、不发明面。"""
import pytest

from nutmeg.decision.betslip import BetslipError
from nutmeg.decision.candidate_builder import (
    MAX_SEARCH_SPACE,
    enumerate_candidates,
    expected_broken_legs,
    format_candidates,
    format_swaps,
    swap_report,
    ticket_probability,
)

FAIR = {str(i): {"home": 0.5, "draw": 0.3, "away": 0.2} for i in range(1, 15)}


def _options(n: int, choices: list[str]) -> dict[str, list[str]]:
    return {str(i): list(choices) for i in range(1, n + 1)}


def test_probability_is_product_of_coverage():
    faces = {"1": "3", "2": "31", "3": "310"}
    assert ticket_probability(faces, FAIR) == pytest.approx(0.5 * 0.8 * 1.0)
    assert expected_broken_legs(faces, FAIR) == pytest.approx(0.5 + 0.2 + 0.0)


def test_enumeration_ranks_in_cap_by_probability_then_price():
    """排序是「帽内 P 降序 → 票价升序」——这是比较顺序，不是推荐。"""
    options = {str(i): ["3"] for i in range(1, 10)}
    options["9"] = ["3", "31"]
    cands = enumerate_candidates(options, FAIR, cap_yuan=20)
    assert [c.notes for c in cands] == [2, 1]          # 双选 P 更高排前
    assert cands[0].p_all > cands[1].p_all
    assert all(c.in_cap for c in cands)


def test_over_cap_candidates_are_returned_but_ranked_last():
    """超帽候选仍然返回——超帽是 Jun 的行权空间，不是程序的禁区（宪法第 4 条）。"""
    options = {str(i): ["3"] for i in range(1, 10)}
    options["9"] = ["310"]
    cands = enumerate_candidates(options, FAIR, cap_yuan=2)
    assert cands and not cands[0].in_cap


def test_renjiu_requires_nine_matches():
    cands = enumerate_candidates(_options(8, ["3"]), FAIR, channel="renjiu")
    assert cands == []


def test_renjiu_complex_probability_is_at_least_nine_not_all_ten():
    """任九选 10 场是复式：P 是"至少中 9 场"，比"十场全中"高。"""
    options = {str(i): ["3"] for i in range(1, 11)}
    cands = enumerate_candidates(options, FAIR, channel="renjiu")
    ten_all_hit = 0.5 ** 10
    assert cands[0].p_all > ten_all_hit


def test_search_space_guard_raises_instead_of_truncating():
    """静默截断会把「帽内第一」变成「搜到的第一」——必须抛错。"""
    with pytest.raises(BetslipError) as exc:
        enumerate_candidates(_options(14, ["3", "31", "310", ""]), FAIR)
    assert str(MAX_SEARCH_SPACE) in str(exc.value).replace(",", "")


def test_two_point_swap_is_enumerable_for_renjiu():
    """"9 换 12" 在任九里只能成对发生（丢一场补一场），单点替换枚举不出它。"""
    base = {str(i): "3" for i in range(1, 10)}
    rows = swap_report(base, {"12": ["31"]}, FAIR)
    labels = [label for label, _ in rows]
    assert any("丢场1(3)" in lbl and "场12·31" in lbl for lbl in labels)
    assert all(c.notes == 2 for _, c in rows)         # 仍是 9 场、其中一场双选


def test_swap_report_orders_by_probability():
    base = {str(i): "3" for i in range(1, 10)}
    rows = swap_report(base, {"10": ["31"], "11": ["310"]}, FAIR)
    assert rows[0][1].p_all >= rows[-1][1].p_all


def test_format_marks_comparison_not_recommendation():
    """格式化输出必须写明「不是推荐」——部署门反复被误读成建议空仓。"""
    options = {str(i): ["3"] for i in range(1, 10)}
    out = format_candidates(enumerate_candidates(options, FAIR, cap_yuan=100),
                            cap_yuan=100)
    assert "不是推荐" in out
    base = {str(i): "3" for i in range(1, 10)}
    swaps = format_swaps(swap_report(base, {"10": ["31"]}, FAIR),
                         ticket_probability(base, FAIR))
    assert "同价行之间才可比" in swaps
