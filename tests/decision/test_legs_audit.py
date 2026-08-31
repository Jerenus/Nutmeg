# tests/decision/test_legs_audit.py
import pytest

from nutmeg.decision.legs_audit import (
    Leg,
    audit_legs,
    audit_prescription_deviations,
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
    # 2026-08-30 旗响应改革(C10)后:方向性旗场的干净表达=全包,双选降为 WARN
    legs = [
        _leg(match_no=1, faces="310", directional_flags=(("self_made_tail", "1"),)),
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


def test_decision_audit_accepts_canonical_empty_jczq_array(tmp_path):
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    legs_file = tmp_path / "legs.json"
    legs_file.write_text("[]\n", encoding="utf-8")
    result = CliRunner().invoke(app, [
        "decision-audit-legs", "--legs-file", str(legs_file),
    ])
    assert result.exit_code == 0
    assert "通过" in result.stdout


# ── C7: 被排面活先例（2026-08-23 立规则，26105西布罗/26109场10 两死换来） ──

def test_excluded_face_live_precedent_warns_on_double():
    # 26109 场10 形态：31 双选排掉客面，而客队有同场地同型活先例
    leg = _leg(faces="31", fair={"home": 0.552, "draw": 0.264, "away": 0.184},
               precedents=(("0", "2023-04-27 圣马梅斯 ATH 0:1 SEV", "alive"),))
    findings = audit_legs([leg])
    codes = [f.code for f in findings]
    assert "excluded_face_live_precedent" in codes
    assert not has_blocking(findings)  # WARN 级，点名不拦票


def test_excluded_face_dead_precedent_silent():
    # 26109 场13 形态：0-4 先例已被载体清算否决（dead）→ 不告警
    leg = _leg(faces="31", fair={"home": 0.607, "draw": 0.221, "away": 0.172},
               precedents=(("0", "上季 0-4 但四条进球载体全离队", "dead"),))
    assert "excluded_face_live_precedent" not in [f.code for f in audit_legs([leg])]


def test_covered_face_precedent_silent():
    # 先例面已被盖住（全包或双选含该面）→ 不告警
    full = _leg(faces="310", precedents=(("0", "同场地客胜先例", "alive"),))
    double_covering = _leg(faces="30", fair=FAIR_HOME,
                           precedents=(("0", "同场地客胜先例", "alive"),))
    assert "excluded_face_live_precedent" not in [f.code for f in audit_legs([full])]
    assert "excluded_face_live_precedent" not in [
        f.code for f in audit_legs([double_covering])]


def test_naked_single_with_live_precedent_warns():
    # 裸单的两个被排面之一有活先例 → 同样点名
    leg = _leg(faces="3", precedents=(("1", "同场地对阵近3次2平", "alive"),))
    assert "excluded_face_live_precedent" in [f.code for f in audit_legs([leg])]


def test_legs_from_dict_parses_precedents():
    payload = {"issue": "26110", "legs": {"10": {
        "name": "毕尔巴-塞维利", "faces": "31",
        "fair": {"home": 0.552, "draw": 0.264, "away": 0.184}, "confidence": 3,
        "directional_flags": [["self_made_tail", "1"]],
        "nondirectional_flags": [], "anchor_integrity": "pass",
        "precedents": [["0", "2023-04-27 圣马梅斯 0:1", "alive"]]}}}
    legs = legs_from_dict(payload)
    assert legs[0].precedents == (("0", "2023-04-27 圣马梅斯 0:1", "alive"),)
    assert "excluded_face_live_precedent" in [f.code for f in audit_legs(legs)]


# ── C8: 伪精确锚定（2026-08-26 立规则） ──

def test_pseudo_precision_warns_for_six_pp_inference_only_shift():
    leg = _leg(
        prior={"home": 0.60, "draw": 0.25, "away": 0.15},
        fair={"home": 0.66, "draw": 0.20, "away": 0.14},
        adjustment_evidence_tiers=("inference", "motivation"),
    )

    finding = next(
        item for item in audit_legs([leg]) if item.code == "pseudo_precision_anchor"
    )

    assert finding.level == "WARN"
    assert "6.0pp" in finding.message
    assert not has_blocking([finding])


def test_pseudo_precision_accepts_official_or_confirmed_structural_anchor():
    common = {
        "prior": {"home": 0.60, "draw": 0.25, "away": 0.15},
        "fair": {"home": 0.66, "draw": 0.20, "away": 0.14},
    }

    for tier in ("official", "confirmed_structural"):
        leg = _leg(**common, adjustment_evidence_tiers=("inference", tier))
        assert "pseudo_precision_anchor" not in _codes([leg])


def test_pseudo_precision_boundary_is_exactly_five_pp():
    prior = {"home": 0.60, "draw": 0.25, "away": 0.15}
    below = _leg(
        prior=prior,
        fair={"home": 0.6499, "draw": 0.2001, "away": 0.15},
        adjustment_evidence_tiers=("inference",),
    )
    boundary = _leg(
        prior=prior,
        fair={"home": 0.65, "draw": 0.20, "away": 0.15},
        adjustment_evidence_tiers=("inference",),
    )

    assert "pseudo_precision_anchor" not in _codes([below])
    assert "pseudo_precision_anchor" in _codes([boundary])


def test_pseudo_precision_ignores_legacy_leg_without_authored_prior():
    leg = _leg(adjustment_evidence_tiers=("inference", "motivation"))
    assert "pseudo_precision_anchor" not in _codes([leg])


def test_legs_from_dict_parses_c8_inputs():
    payload = {"legs": {"1": {
        "name": "甲-乙",
        "faces": "3",
        "fair": {"home": 0.66, "draw": 0.20, "away": 0.14},
        "prior": {"home": 0.60, "draw": 0.25, "away": 0.15},
        "confidence": 4,
        "adjustment_evidence_tiers": ["inference", "motivation"],
    }}}

    leg = legs_from_dict(payload)[0]

    assert leg.prior == {"home": 0.60, "draw": 0.25, "away": 0.15}
    assert leg.adjustment_evidence_tiers == ("inference", "motivation")
    assert "pseudo_precision_anchor" in _codes([leg])


# ── 偏离登记（2026-08-26 立规则） ──

def _deviation_codes(payload):
    return {finding.code for finding in audit_prescription_deviations(payload)}


def test_unnamed_prescription_deviation_warns():
    payload = {
        "prescription": {"1": "31"},
        "legs": {"1": {"faces": "3"}},
        "deviation_registry": [],
    }

    findings = audit_prescription_deviations(payload)

    finding = next(item for item in findings if item.match_no == 1)
    assert finding.code == "unnamed_prescription_deviation"
    assert finding.level == "WARN"
    assert "31" in finding.message and "3" in finding.message


def test_known_rule_names_prescription_deviation():
    payload = {
        "prescription": {"1": "31"},
        "legs": {"1": {"faces": "3"}},
        "deviation_registry": [{
            "match_no": 1,
            "rule_ids": ["m-单选"],
            "reason": "operator-authored reason",
        }],
    }
    assert "unnamed_prescription_deviation" not in _deviation_codes(payload)


def test_unknown_rule_does_not_name_prescription_deviation():
    payload = {
        "prescription": {"1": "31"},
        "legs": {"1": {"faces": "3"}},
        "deviation_registry": [{
            "match_no": 1,
            "rule_ids": ["a-fifth-better-reason"],
            "reason": "not a registered rule",
        }],
    }
    assert "unnamed_prescription_deviation" in _deviation_codes(payload)


def test_equal_prescription_and_ticket_faces_need_no_registration():
    payload = {
        "prescription": {"1": "31"},
        "legs": {"1": {"faces": "13"}},
        "deviation_registry": [],
    }
    assert audit_prescription_deviations(payload) == []


def test_dropped_prescribed_match_is_a_deviation():
    payload = {
        "prescription": {"1": "31"},
        "legs": {},
        "deviation_registry": [],
    }
    findings = audit_prescription_deviations(payload)
    assert findings[0].match_no == 1
    assert "丢整场" in findings[0].message


def test_legacy_payload_without_prescription_has_no_deviation_findings():
    payload = {"legs": {"1": {"faces": "3"}}}
    assert audit_prescription_deviations(payload) == []


def test_c9_opening_upset_double_warns_and_full_cover_passes():
    warn = audit_legs([_leg(faces="31", confidence=3,
                            crash_markers=("opening_promoted_vs_paper",))])
    assert any(f.code == "opening_upset_double" and f.level == "WARN" for f in warn)
    ok = audit_legs([_leg(faces="310", confidence=3,
                          crash_markers=("opening_new_coach_debut",))])
    assert not any(f.code == "opening_upset_double" for f in ok)
    # 词典外标记不触发(封闭词典)
    off = audit_legs([_leg(faces="31", confidence=3, crash_markers=("made_up_marker",))])
    assert not any(f.code == "opening_upset_double" for f in off)


def test_c10_flagged_double_warns_naked_still_error_full_passes():
    flagged = dict(directional_flags=(("anchor_shield_out", "1"),))
    warn = audit_legs([_leg(faces="31", confidence=3, **flagged)])
    assert any(f.code == "flagged_double_not_full" and f.level == "WARN" for f in warn)
    naked = audit_legs([_leg(faces="3", confidence=4, **flagged)])
    assert any(f.code == "flagged_naked_single" and f.level == "ERROR" for f in naked)
    full = audit_legs([_leg(faces="310", confidence=3, **flagged)])
    assert not any(f.code in ("flagged_double_not_full", "flagged_naked_single")
                   for f in full)


def test_c11_false_direction_band_warns_only_in_5_to_10pp():
    # gap12 = 6.6pp 落带内,双选 → WARN
    inband = {"home": 0.377, "draw": 0.311, "away": 0.312}
    hit = audit_legs([_leg(faces="31", confidence=3, fair=inband)])
    assert any(f.code == "false_direction_band" for f in hit)
    # 同一场全包 → 不触发
    full = audit_legs([_leg(faces="310", confidence=3, fair=inband)])
    assert not any(f.code == "false_direction_band" for f in full)
    # gap12 = 1.8pp 在带外(<5pp) → 不触发
    below = {"home": 0.367, "draw": 0.284, "away": 0.349}
    assert not any(f.code == "false_direction_band"
                   for f in audit_legs([_leg(faces="30", confidence=3, fair=below)]))
    # gap12 = 49.2pp 在带外(>10pp) → 不触发
    above = {"home": 0.682, "draw": 0.190, "away": 0.128}
    assert not any(f.code == "false_direction_band"
                   for f in audit_legs([_leg(faces="31", confidence=3, fair=above)]))


def test_c12_draw_underpriced_band_only_when_draw_not_bought():
    band = {"home": 0.375, "draw": 0.313, "away": 0.312}   # 平 31.3% 落 29-32 带
    # 未买平 → WARN
    assert any(f.code == "draw_underpriced_band"
               for f in audit_legs([_leg(faces="30", confidence=3, fair=band)]))
    # 买了平 → 不触发
    assert not any(f.code == "draw_underpriced_band"
                   for f in audit_legs([_leg(faces="31", confidence=3, fair=band)]))
    # 平局 fair 低于带(20.9%) 且未买平 → 不触发(市场反而高估平)
    low = {"home": 0.121, "draw": 0.209, "away": 0.670}
    assert not any(f.code == "draw_underpriced_band"
                   for f in audit_legs([_leg(faces="0", confidence=4, fair=low,
                                             anchor_integrity="pass")]))


def test_unknown_crash_marker_warns_without_triggering_c9():
    findings = audit_legs([
        _leg(faces="31", confidence=3, crash_markers=("invented_opening_story",))
    ])
    assert "crash_marker_off_lexicon" in {item.code for item in findings}
    assert "opening_upset_double" not in {item.code for item in findings}


@pytest.mark.parametrize(
    ("fair", "warns"),
    [
        ({"home": 0.40, "draw": 0.35, "away": 0.25}, True),
        ({"home": 0.4499, "draw": 0.35, "away": 0.2001}, True),
        ({"home": 0.45, "draw": 0.35, "away": 0.20}, False),
    ],
)
def test_c11_exact_half_open_boundaries(fair, warns):
    codes = _codes([_leg(faces="31", confidence=3, fair=fair)])
    assert ("false_direction_band" in codes) is warns


@pytest.mark.parametrize(("draw", "warns"), [(0.29, True), (0.3199, True), (0.32, False)])
def test_c12_exact_half_open_boundaries(draw, warns):
    home = 0.40
    codes = _codes([_leg(faces="30", confidence=3, fair={
        "home": home, "draw": draw, "away": 1 - home - draw,
    })])
    assert ("draw_underpriced_band" in codes) is warns


def test_legs_from_dict_defaults_and_parses_crash_markers():
    with_marker = legs_from_dict({"legs": {"1": {
        "faces": "31", "fair": FAIR_HOME, "confidence": 3,
        "crash_markers": ["opening_promoted_vs_paper"],
    }}})[0]
    legacy = legs_from_dict({"legs": {"1": {
        "faces": "31", "fair": FAIR_HOME, "confidence": 3,
    }}})[0]
    assert with_marker.crash_markers == ("opening_promoted_vs_paper",)
    assert legacy.crash_markers == ()
