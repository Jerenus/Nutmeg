# tests/decision/test_legs_audit.py
import pytest

from nutmeg.decision.legs_audit import (
    Leg,
    audit_full_cover_allocation,
    audit_legs,
    audit_prescription_deviations,
    audit_read_ticket_consistency,
    audit_shared_exclusions,
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


# ── C13/C14: 死亡三证与昂贵排除（2026-09-06 立规则，26118 场8 不来梅 3:1 莱比锡） ──

def test_broken_anchor_double_warns_but_does_not_block():
    # 26118 场8 形态：莱比锡完整度 fail，01 双选排掉不来梅主胜
    leg = _leg(faces="01", fair={"home": 0.227, "draw": 0.229, "away": 0.543},
               anchor_integrity="fail")
    findings = audit_legs([leg])
    assert "broken_anchor_double" in {f.code for f in findings}
    assert not has_blocking(findings)


def test_broken_anchor_double_silent_when_anchor_passes_or_full_cover():
    assert "broken_anchor_double" not in _codes([_leg(faces="31", anchor_integrity="pass")])
    assert "broken_anchor_double" not in _codes([_leg(faces="310", anchor_integrity="fail")])


def test_expensive_exclusion_warns_above_twenty_percent():
    # 被排面 22.7% 且锚方 FAIL → 昂贵排除
    leg = _leg(faces="01", fair={"home": 0.227, "draw": 0.229, "away": 0.543},
               anchor_integrity="fail")
    assert "expensive_exclusion" in _codes([leg])


def test_expensive_exclusion_silent_when_three_proofs_or_cheap_face():
    # 锚方 PASS 且该面先例 dead → 三证可核部分齐，不告警
    proven = _leg(faces="31", fair={"home": 0.55, "draw": 0.24, "away": 0.21},
                  anchor_integrity="pass",
                  precedents=(("0", "载体全离队", "dead"),))
    assert "expensive_exclusion" not in _codes([proven])
    # 被排面 ≤20% → 不告警（柏林联 13.9 形态）
    cheap = _leg(faces="31", fair={"home": 0.681, "draw": 0.181, "away": 0.139},
                 anchor_integrity="fail")
    assert "expensive_exclusion" not in _codes([cheap])
    # 全包无被排面
    assert "expensive_exclusion" not in _codes([_leg(faces="310", fair=FAIR_AWAY)])


def test_expensive_exclusion_applies_to_naked_single_faces():
    # 裸单 55.7 的两个被排面 24.4/19.9：只有 24.4 那一面超线
    leg = _leg(faces="3", fair={"home": 0.557, "draw": 0.244, "away": 0.199},
               anchor_integrity="pass")
    findings = [f for f in audit_legs([leg]) if f.code == "expensive_exclusion"]
    assert len(findings) == 1
    assert "平" in findings[0].message and "客胜" not in findings[0].message


# ── 追踪标签（2026-09-07 立：只入记分牌，不改审计动作） ──

def test_tracking_tags_parse_and_do_not_change_audit():
    payload = {"issue": "26119", "legs": {"11": {
        "name": "马拉加-莱万特", "faces": "310",
        "fair": {"home": 0.394, "draw": 0.29, "away": 0.316}, "confidence": 2,
        "directional_flags": [], "nondirectional_flags": [], "anchor_integrity": "fail",
        "precedents": [], "crash_markers": [],
        "tracking_tags": ["promoted_side", "new_spine_pairing"]}}}
    legs = legs_from_dict(payload)
    assert legs[0].tracking_tags == ("promoted_side", "new_spine_pairing")
    codes = {f.code for f in audit_legs(legs)}
    assert "tracking_tag_off_lexicon" not in codes
    assert not has_blocking(audit_legs(legs))


def test_tracking_tag_off_lexicon_warns_only():
    leg = _leg(faces="310", fair=FAIR_AWAY, tracking_tags=("cold_streak",))
    findings = audit_legs([leg])
    assert "tracking_tag_off_lexicon" in {f.code for f in findings}
    assert not has_blocking(findings)


# ── 球队影响因子标签与对位机制（2026-09-07 立） ──

def test_team_tags_parse_and_pairing_info():
    payload = {"issue": "26119", "legs": {"4": {
        "name": "法兰克福-奥格斯", "faces": "310",
        "fair": {"home": 0.505, "draw": 0.236, "away": 0.258}, "confidence": 3,
        "directional_flags": [["anchor_shield_out", "1"]], "nondirectional_flags": [],
        "anchor_integrity": "fail", "precedents": [], "crash_markers": [],
        "team_tags": {"home": ["new_gk", "new_cb_pairing", "pivot_absent"],
                      "away": ["set_piece_strong"]}}}}
    legs = legs_from_dict(payload)
    assert ("away", "set_piece_strong") in legs[0].team_tags
    findings = audit_legs(legs)
    info = [f for f in findings if f.code == "pairing_mechanism"]
    assert info and info[0].level == "INFO"
    assert "set_piece_strong" in info[0].message and "客队" in info[0].message
    assert not has_blocking(findings)


def test_team_tag_counter_and_off_lexicon():
    leg = _leg(faces="310", fair=FAIR_AWAY,
               team_tags=(("home", "low_block_home"), ("away", "low_block_breaker_weak"),
                          ("away", "hot_streak")))
    findings = audit_legs([leg])
    codes = {f.code for f in findings}
    assert "team_tag_off_lexicon" in codes
    msg = next(f.message for f in findings if f.code == "pairing_mechanism")
    assert "low_block_breaker_weak" in msg
    assert not has_blocking(findings)


# ── 2026-09-11 审计器纠偏与规则层入码 ──

def test_flat_band_modal_drop_is_warning_not_blocking():
    """top1−top2 < 1pp 时「模态面」是浮点排序的产物，不是市场判断。

    26122 场4 纽伦堡 37.0 / 汉诺威 37.8（差 0.8pp）：深研自己的结论是"任何自称能分辨
    的叙事都是在讲故事"，代码却把其中一面叫模态并据此阻断出票——那是让校验器假装
    市场给了方向。该带内记 WARN（仍入账以便复盘），不阻断。
    """
    flat = {"home": 0.370, "draw": 0.252, "away": 0.378}
    findings = audit_legs([_leg(faces="31", fair=flat, confidence=2)])
    codes = {f.code for f in findings}
    assert "modal_face_dropped_flat" in codes
    assert "modal_face_dropped" not in codes
    assert not has_blocking(findings)


def test_real_modal_drop_still_blocks():
    """真正的弃模态（gap ≥ 1pp）仍是 ERROR——翻面实证 0/42，分级不是放行。"""
    findings = audit_legs([_leg(faces="31", fair=FAIR_AWAY, confidence=4)])
    assert "modal_face_dropped" in {f.code for f in findings}
    assert has_blocking(findings)


def test_exclusion_ladder_grades_faces():
    """排面分级 INFO：省钱 / 灰带 / 买方差 / 翻面 —— 免得预算花在 30% 的面上。"""
    fair = {"home": 0.55, "draw": 0.26, "away": 0.19}
    msg = next(f.message for f in audit_legs([_leg(faces="31", fair=fair)])
               if f.code == "exclusion_ladder")
    assert "客胜 19.0%=灰带" in msg


def test_directional_flags_accept_bare_string():
    """旗写成裸字符串不得让校验器崩溃。

    出生事故 26122：`directional_flags: ["anchor_shield_out"]` 让 audit_legs 抛
    `too many values to unpack`，审计门退出码 1 却零 findings——**校验器自己崩掉
    比不校验更危险**，因为它看起来像"通过了"。裸名默认指平（词典五面旗机理皆指平）。
    """
    payload = {"legs": {"1": {"name": "甲-乙", "faces": "3", "fair": FAIR_HOME,
                              "confidence": 4,
                              "directional_flags": ["self_made_tail"]}}}
    legs = legs_from_dict(payload)
    assert legs[0].directional_flags == (("self_made_tail", "1"),)
    assert "flagged_naked_single" in {f.code for f in audit_legs(legs)}


def test_deviation_rule_aliases_are_accepted():
    """条文改名不得让判据静默失效。

    26122 按 RULEBOOK 现行条名（砍腿序/独立面效率表/m-四问）登记偏离，审计因名字不在
    frozenset 里判为「无名偏离」——规则改了名字，校验就失效了。别名表把人读条名
    规约到 canonical ID。
    """
    payload = {
        "prescription": {"1": "310"},
        "legs": {"1": {"name": "甲-乙", "faces": "31", "fair": FAIR_HOME,
                       "confidence": 4}},
        "deviation_registry": [{"match_no": 1, "rule_ids": ["砍腿序", "m-四问"],
                                "reason": "帽内压缩"}],
    }
    assert audit_prescription_deviations(payload) == []


def test_license_q3_split_only_q3b_blocks():
    """四问③拆分：③a（对手会进球）不封牌照，③b（对手会取分）才封。

    26121 巴萨/巴黎/拜仁三条牌照裸单的③全部失分在"对手会进球"（三场对手合计进 2 球）
    却 3/3 兑现；26122 场13 AZ 同型。③a 杀的是零封/让胜腿，不是胜负腿。
    """
    q3a_only = _leg(license_questions={"q3a_opponent_scores": True,
                                       "q3b_opponent_takes_points": False})
    codes = {f.code for f in audit_legs([q3a_only])}
    assert "license_q3a_only" in codes
    assert "license_q3b_opponent_takes_points" not in codes

    q3b = _leg(license_questions={"q3a_opponent_scores": True,
                                  "q3b_opponent_takes_points": True})
    assert "license_q3b_opponent_takes_points" in {f.code for f in audit_legs([q3b])}


def test_ttg_shape_degraded_is_info():
    """无体彩板面的场次（法乙五场）DC 只有固定 ρ，进球带精度下降，须在票面上标出来。"""
    findings = audit_legs([_leg(ttg_shape_anchor=False)])
    assert "ttg_shape_degraded" in {f.code for f in findings}
    assert not has_blocking(findings)


def test_shared_exclusion_flags_common_death_point():
    """C15：多票共享同一个 >20% 被排面 = 分散注金没有分散死点。

    26118 三票共享不来梅主胜 23.2%，该面开出三票同死；26122 四张票共享达姆施塔特
    主胜 34.9%。票面不同但被排面相同时，组合的真实自由度是 1。
    """
    fair = {"home": 0.349, "draw": 0.257, "away": 0.394}
    a = [_leg(match_no=3, faces="10", fair=fair, confidence=2)]
    b = [_leg(match_no=3, faces="0", fair=fair, confidence=2)]
    findings = audit_shared_exclusions({"T1": a, "T2": b})
    assert [f.code for f in findings] == ["shared_exclusion"]
    assert "34.9%" in findings[0].message and "T1/T2" in findings[0].message

    # 单票不触发；被排面 ≤20% 也不触发（那是"省钱"不是共享死点）
    assert audit_shared_exclusions({"T1": a}) == []
    cheap = {"home": 0.60, "draw": 0.25, "away": 0.15}
    assert audit_shared_exclusions({
        "T1": [_leg(match_no=5, faces="31", fair=cheap)],
        "T2": [_leg(match_no=5, faces="31", fair=cheap)]}) == []


def test_shared_naked_single_is_flagged_regardless_of_price():
    """C15b：多票共享同一条裸单 = 全日资金只有一件事的自由度。

    26122 四张票在场13 AZ 上都是裸 3；被排掉的平+客合计 17.8%，低于 C15 的 20% 价格
    门槛，所以 C15 看不见它——然后 1-1 一场杀四票。该报的不是"这个面贵不贵"，
    而是"全部票同时死于此的概率"。
    """
    fair = {"home": 0.822, "draw": 0.112, "away": 0.066}
    a = [_leg(match_no=13, faces="3", fair=fair, confidence=5)]
    b = [_leg(match_no=13, faces="3", fair=fair, confidence=5)]
    findings = audit_shared_exclusions({"T1": a, "T2": b})
    codes = [f.code for f in findings]
    assert "shared_naked_single" in codes
    assert "shared_exclusion" not in codes          # 价格门槛下的旧 C15 确实看不见
    msg = next(f.message for f in findings if f.code == "shared_naked_single")
    assert "17.8%" in msg and "T1/T2" in msg
    # 单票不报；两票在同一场上一裸一双不算"共享裸单"
    assert audit_shared_exclusions({"T1": a}) == []
    assert "shared_naked_single" not in {
        f.code for f in audit_shared_exclusions(
            {"T1": a, "T2": [_leg(match_no=13, faces="31", fair=fair)]})}


# --- 2026-09-13 26123 复盘三条（I1/I2/I4，用户批准入码）---

def test_naked_single_ladder_grades_total_exposure_not_single_face():
    """I2 —— 裸单排的是两个面。26122 AZ 平 11.1% 被判「省钱」，
    实际暴露 11.1+6.2=17.3%，一场杀四张票。"""
    fair = {"home": 0.827, "draw": 0.111, "away": 0.062}
    ladder = [f for f in audit_legs([_leg(faces="3", fair=fair, confidence=5)])
              if f.code == "exclusion_ladder"]
    assert ladder and "裸单总暴露 17.3%=灰带" in ladder[0].message
    # 双选只排一个面，不打总暴露那一行
    double = [f for f in audit_legs([_leg(faces="31", fair=fair, confidence=5)])
              if f.code == "exclusion_ladder"]
    assert double and "裸单总暴露" not in double[0].message


def test_excluded_face_contradicts_pairing_mechanism():
    """I4 —— 对位机制判出某方破门机制缺席时，受益的是对方取胜面；把它排掉＝与读判相反。
    26123 场13：米兰 low_block_breaker_weak × 拉齐奥 low_block_home ＝客队机制缺席，
    构票仍排掉拉齐奥主胜 29.1%。"""
    fair = {"home": 0.291, "draw": 0.297, "away": 0.412}
    tags = (("away", "low_block_breaker_weak"), ("home", "low_block_home"))
    hit = [f for f in audit_legs([_leg(faces="10", fair=fair, team_tags=tags, confidence=3)])
           if f.code == "excluded_face_contradicts_read"]
    assert hit and "主胜" in hit[0].message
    # 盖住受益面就不该报
    assert not [f for f in audit_legs(
        [_leg(faces="310", fair=fair, team_tags=tags, confidence=3)])
        if f.code == "excluded_face_contradicts_read"]


def test_read_ticket_inconsistency_blocks_when_four_doubles_defy_the_read():
    """I1 —— C10/C6 单看都只是 WARN，攒到 4 处就是 8/08 铁律被系统性绕开。
    26123 F 票六个双选全落在自判「全包或丢」的场次上，17 个 WARN 照样出票。"""
    legs = [_leg(match_no=i, faces="31",
                 directional_flags=(("anchor_shield_out", "1"),))
            for i in range(1, 5)]
    findings = audit_legs(legs)
    extra = audit_read_ticket_consistency(findings)
    assert [f.code for f in extra] == ["read_ticket_inconsistency"]
    assert extra[0].level == "ERROR"
    assert has_blocking(findings + extra)
    # 三处以下不阻断
    assert not audit_read_ticket_consistency(audit_legs(legs[:3]))


def test_full_cover_slots_follow_excluded_face_not_lowest_top1():
    """全包名额按被排面 fair 降序，不按 top1 升序。
    26123：F 票把名额按 top1 最低给了场2(38.2)/场10(40.9)，而场10 最小面 23.9%
    低于场13 被排面 29.1%——同价换过去 P 更高，实际赛果也证明换了就是 9/9。"""
    full = _leg(match_no=10, faces="310",
                fair={"home": 0.409, "draw": 0.239, "away": 0.352})
    double = _leg(match_no=13, faces="10",
                  fair={"home": 0.291, "draw": 0.297, "away": 0.412})
    hit = audit_full_cover_allocation([full, double])
    assert [f.code for f in hit] == ["full_cover_allocation_dominated"]
    assert "+5.2pp" in hit[0].message and hit[0].level == "WARN"


def test_full_cover_allocation_is_quiet_when_already_optimal():
    """全包给了最小面更大的那一场 → 无支配交换，不报。"""
    full = _leg(match_no=2, faces="310",
                fair={"home": 0.382, "draw": 0.264, "away": 0.354})
    double = _leg(match_no=3, faces="31",
                  fair={"home": 0.771, "draw": 0.150, "away": 0.080})
    assert audit_full_cover_allocation([full, double]) == []
