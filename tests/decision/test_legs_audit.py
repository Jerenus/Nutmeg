# tests/decision/test_legs_audit.py
from nutmeg.decision.legs_audit import (
    Leg,
    audit_legs,
    format_findings,
    has_blocking,
    legs_from_dict,
)

FAIR_HOME = {"home": 0.66, "draw": 0.20, "away": 0.14}     # 模态 = 主
FAIR_AWAY = {"home": 0.25, "draw": 0.30, "away": 0.45}     # 模态 = 客


def _leg(**kw):
    base = dict(match_no=1, name="甲-乙", faces="3", fair=FAIR_HOME, confidence=4)
    base.update(kw)
    return Leg(**base)


def _codes(legs):
    return {f.code for f in audit_legs(legs)}


def test_flagged_naked_single_is_blocking():
    """四次亏损换来的那一条:带方向性旗还裸单,必须是 ERROR 且阻断出票。

    每次的理由都不同且一次比一次讲究(免费期权 / 已定价 / 幅度已实测 / 不追盖率),
    所以判据只能看结构、不能看论证。
    """
    legs = [_leg(directional_flags=(("self_made_tail", "1"),))]
    findings = audit_legs(legs)
    assert "flagged_naked_single" in {f.code for f in findings}
    assert has_blocking(findings)


def test_fair_height_does_not_excuse_a_flag():
    """fair 高低不得覆盖旗 —— 26102 本菲卡 85.8% 就是这么死的。

    ⚠️那场我当时把旗记成"空场"（词典外），真正的旗是 `anchor_shield_out`
    （中轴四人卖空）。挂错名字本身就是那次失手的一部分。
    """
    huge = {"home": 0.86, "draw": 0.10, "away": 0.04}
    legs = [_leg(fair=huge, directional_flags=(("anchor_shield_out", "1"),))]
    assert "flagged_naked_single" in _codes(legs)


def test_off_lexicon_flag_warns_but_does_not_block():
    """agent 自命名的旗**不阻断单选**,只记 WARN 待裁决。

    否则任何 agent 凭空造一个旗名就能把单选堵死——那不是纪律,是瘫痪。
    26103 实际出现过三个自命名旗(away_side_draw_utility / leader_draw_sufficient /
    chaser_creator_out),其中"领先方可接受平"这一机理 26097 判读层已裁定是机理不是旗。
    """
    legs = [_leg(directional_flags=(("away_side_draw_utility", "1"),))]
    findings = audit_legs(legs)
    assert "flag_off_lexicon" in {f.code for f in findings}
    assert "flagged_naked_single" not in {f.code for f in findings}
    assert not has_blocking(findings)


def test_mixed_flags_block_only_on_lexicon_one():
    legs = [_leg(directional_flags=(("leader_draw_sufficient", "1"),
                                    ("self_made_tail", "1")))]
    assert has_blocking(audit_legs(legs))          # self_made_tail 在词典内


def test_double_must_cover_the_flag_face():
    """盖不住旗面的双选不是保险:旗指平却买主+客 → ERROR。"""
    legs = [_leg(faces="30", directional_flags=(("self_made_tail", "1"),))]
    assert "flag_face_uncovered" in _codes(legs)
    # 盖住旗面就干净
    assert "flag_face_uncovered" not in _codes(
        [_leg(faces="31", directional_flags=(("self_made_tail", "1"),))])


def test_modal_face_must_be_kept():
    legs = [_leg(faces="10")]                    # 模态是主,却只买平+客
    assert "modal_face_dropped" in _codes(legs)


def test_conf3_single_blocked():
    """conf3 是"有理由但不够硬"的自我说服黑洞,实证比 conf2 还差。"""
    assert "low_conf_single" in _codes([_leg(confidence=3)])
    assert "low_conf_single" not in _codes([_leg(confidence=4)])


def test_broken_anchor_single_blocked():
    assert "broken_anchor_single" in _codes([_leg(anchor_integrity="fail")])
    assert "broken_anchor_single" not in _codes([_leg(anchor_integrity="pass")])


def test_nondirectional_flag_wants_full_cover_but_only_warns():
    """无方向性旗=判不动往哪碎 → 该全包;但这是 WARN 不是 ERROR,
    因为「整场丢掉」也是合法应对,不该被硬拦。"""
    findings = audit_legs([_leg(faces="31", nondirectional_flags=("two_way_instability",))])
    assert [f.level for f in findings if f.code == "undecidable_not_full"] == ["WARN"]
    assert not has_blocking(findings)


def test_modal_stack_mismatch_reports_the_arithmetic():
    """「每条腿各自最可能」≠「它们同时发生也最可能」。

    5 条 45% 的模态裸单,期望只中 2.25 条 —— 这正是 26103 我一边论证板面结构性
    偏平、一边堆模态裸单的自相矛盾。
    """
    legs = [_leg(match_no=i, fair=FAIR_AWAY, faces="0") for i in range(1, 6)]
    findings = audit_legs(legs)
    hit = [f for f in findings if f.code == "modal_stack_mismatch"]
    assert hit and hit[0].level == "WARN"
    assert "2.25" in hit[0].message


def test_clean_ticket_passes():
    legs = [
        _leg(match_no=1, faces="31", directional_flags=(("self_made_tail", "1"),)),
        _leg(match_no=2, faces="3", confidence=4, anchor_integrity="pass"),
        _leg(match_no=3, faces="310", nondirectional_flags=("dressing_room_turmoil",),
             anchor_integrity="fail"),
    ]
    findings = audit_legs(legs)
    assert not has_blocking(findings)
    assert "通过" in format_findings(findings)


def test_legs_from_dict_roundtrip():
    payload = {"issue": "26103", "legs": {"7": {
        "name": "里昂-斯巴达", "faces": "3", "fair": FAIR_HOME, "confidence": 4,
        "directional_flags": [["away_side_draw_utility", "1"]],
        "nondirectional_flags": [], "anchor_integrity": "symmetric_damage"}}}
    legs = legs_from_dict(payload)
    assert legs[0].match_no == 7 and legs[0].modal == "3"
    assert abs(legs[0].coverage - 0.66) < 1e-9
    # away_side_draw_utility 是词典外自命名 → 只 WARN,不阻断（26103 场7 的真实形态）
    assert not has_blocking(audit_legs(legs))
