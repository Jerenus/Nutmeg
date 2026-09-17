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


# —— 两段式审计（2026-09-17 新增）——————————————————————————

def _audit_legs_payload():
    """场7 带方向旗 + 锚方 FAIL；场11 只锚方 FAIL；其余干净。"""
    legs = {}
    for i in range(1, 15):
        leg = {
            "name": f"甲{i}-乙{i}",
            "faces": "310",
            "fair": {"home": 0.66, "draw": 0.20, "away": 0.14},
            "confidence": 4,
        }
        if i == 7:
            leg["directional_flags"] = [["self_made_tail", "1"]]
            leg["anchor_integrity"] = "fail"
        if i == 11:
            leg["anchor_integrity"] = "fail"
        legs[str(i)] = leg
    return {"issue": "T", "version": "t", "legs": legs}


def _codes():
    from nutmeg.decision.candidate_builder import leg_face_codes
    from nutmeg.decision.legs_audit import legs_from_dict

    return leg_face_codes(legs_from_dict(_audit_legs_payload()))


def test_leg_face_code_table_covers_every_face_set():
    table = _codes()
    assert {faces for (_, faces) in table} == {"3", "1", "0", "31", "30", "10", "310"}


def test_cheap_table_marks_the_flagged_naked_single():
    """C1 是四票之死那一条：带方向旗还裸单。查表必须看得见它。"""
    table = _codes()
    assert "C1" in table[("7", "3")][0]
    assert "C1" not in table[("7", "31")][0]


def test_candidates_carry_cheap_codes_without_real_audit():
    candidates = enumerate_candidates(
        {**_options(9, ["310"]), "7": ["3"]}, FAIR, leg_codes=_codes()
    )
    assert candidates
    assert "C1" in candidates[0].error_codes
    assert candidates[0].audited is False


def test_real_audit_adds_ticket_level_codes_the_cheap_table_cannot_see():
    """便宜查表只是**腿级码的下界**。C17 这类票级码只有真审计看得见——
    26128 实测：腿级零 ERROR 的候选，真审计后每一个都触发 C17。"""
    from nutmeg.decision.candidate_builder import audit_candidates

    payload = _audit_legs_payload()
    for match_no in ("1", "2", "3", "4"):
        payload["legs"][match_no]["nondirectional_flags"] = ["two_way_instability"]
    options = {str(i): ["31"] for i in range(1, 10)}
    candidates = enumerate_candidates(options, FAIR, leg_codes=_codes())
    assert "C17" not in candidates[0].error_codes
    audited = audit_candidates(candidates, payload, top=1)
    assert audited[0].audited is True
    assert "C17" in audited[0].error_codes


def test_audit_top_leaves_the_rest_cheap():
    from nutmeg.decision.candidate_builder import audit_candidates

    candidates = enumerate_candidates(
        _options(10, ["310", "31"]), FAIR, leg_codes=_codes()
    )
    audited = audit_candidates(candidates, _audit_legs_payload(), top=3)
    assert [c.audited for c in audited[:3]] == [True, True, True]
    assert audited[3].audited is False


def test_audit_never_removes_or_reorders_candidates():
    """ERROR 是 Jun 的行权空间，不是程序的禁区。"""
    from nutmeg.decision.candidate_builder import audit_candidates

    candidates = enumerate_candidates(
        _options(10, ["310", "31"]), FAIR, leg_codes=_codes()
    )
    audited = audit_candidates(candidates, _audit_legs_payload(), top=5)
    assert len(audited) == len(candidates)
    assert [c.signature for c in audited] == [c.signature for c in candidates]


def test_structure_filter_keeps_only_that_shape():
    """26127 用户的 S333 落在我所有声明空间的缝里（没有一个允许
    「锚场降双 × 硬币降双」的交叉）。形状过滤堵这个缝。"""
    candidates = enumerate_candidates(
        _options(9, ["3", "31", "310"]), FAIR, structure=(3, 3, 3)
    )
    assert candidates
    assert all(c.structure == (3, 3, 3) for c in candidates)
    assert all(c.structure_label == "3单3双3包" for c in candidates)


def test_structure_filter_ignores_dropped_matches():
    candidates = enumerate_candidates(
        {**_options(9, ["31"]), "10": ["", "31"]}, FAIR, structure=(0, 9, 0)
    )
    assert candidates
    assert all(len(c.faces) == 9 for c in candidates)


def test_summary_never_calls_cheap_zero_error_clean():
    """伪精确锚定：便宜查表的「零 ERROR」不得被报成「干净票」。"""
    candidates = enumerate_candidates(
        _options(9, ["31"]), FAIR, leg_codes=_codes(), cap_yuan=10_000
    )
    text = format_candidates(candidates, cap_yuan=10_000)
    assert "腿级**零 ERROR 未经真审计" in text or "腿级" in text
    assert "不等于干净" in text
