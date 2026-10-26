# tests/decision/test_research_intake.py
"""研究 JSON 入库桥 —— 只转录与校验，绝不产生判断。"""

from nutmeg.decision.research_intake import (
    format_report,
    intake,
    normalize_proofs,
    proof_count,
)


def _leg():
    return {
        "name": "甲-乙",
        "faces": "310",
        "fair": {"home": 0.66, "draw": 0.20, "away": 0.14},
    }


def _research(**overrides):
    base = {
        "match_no": 7,
        "anchor_integrity": "fail",
        "confidence": 4,
        "directional_flags": [["anchor_shield_out", "1"]],
        "nondirectional_flags": [],
        "crash_markers": [],
        "tracking_tags": [],
        "team_tags": {"home": [], "away": []},
        "license_questions": {
            "q1_spine": False,
            "q2_route": True,
            "q3a_opponent_scores": True,
            "q3b_opponent_takes_points": False,
            "q4_no_context_flag": False,
        },
        "summary": "锚方中轴双后腰长期缺阵。",
        "stance": {"face": "3", "structure": "single", "confidence": 4},
    }
    base.update(overrides)
    return base


def _levels(result):
    return [(i.level, i.field) for i in result.issues]


# —— 键名归一 ————————————————————————————————————————

def test_proof_keys_normalise_across_both_agent_conventions():
    """两套键名并存；按裸键读会把带后缀的那套静默读成 None，
    于是「三证 0/3」与「三证没填」长得一模一样。"""
    long_form = normalize_proofs({
        "draw": {
            "a_no_scoring_mechanism": False,
            "b_precedent_carrier_gone": True,
            "c_anchor_pass": False,
            "detail": "…",
        }
    })
    short_form = normalize_proofs({"draw": {"a": False, "b": True, "c": False}})
    assert long_form["draw"]["b"] is True
    assert long_form["draw"]["detail"] == "…"
    assert proof_count(long_form["draw"]) == proof_count(short_form["draw"]) == 1


def test_unknown_faces_are_ignored():
    assert normalize_proofs({"nonsense": {"a": True}}) == {}
    assert normalize_proofs("not a dict") == {}


# —— 封闭词典：剥离但留痕 ————————————————————————————

def test_off_lexicon_flag_is_stripped_not_blocking():
    """agent 自命名的旗若能堵死出票，那不是纪律是瘫痪（26103 一次冒出三个）。
    但剥离必须留痕，否则等于静默丢证据。"""
    result = intake(
        _research(nondirectional_flags=["agent_自命名的旗"]), _leg()
    )
    assert result.blocked is False
    assert result.leg["nondirectional_flags"] == []
    assert "agent_自命名的旗" in result.leg["note"]
    assert ("WARN", "nondirectional_flags") in _levels(result)


def test_information_asymmetry_survives_since_it_entered_the_lexicon():
    """2026-09-17 Jun 裁定入词典。此前四期 agent 每期照写而每期被剥离——
    证据一直在产生却一直被丢掉。"""
    result = intake(
        _research(nondirectional_flags=["information_asymmetry"]), _leg()
    )
    assert result.leg["nondirectional_flags"] == ["information_asymmetry"]
    assert "【入库剥离】" not in result.leg["note"]


def test_narrative_in_a_tag_slot_is_stripped_not_blocking():
    """26125-26128 反复出现：agent 把整段叙述写进 crash_markers。
    strength-v2（2026-09-26）起剥离进 note 记 WARN，不再整份驳回。"""
    result = intake(
        _research(crash_markers=["这场的崩塌通道是中卫板凳归零叠加三天轮转" * 3]),
        _leg(),
    )
    assert ("WARN", "crash_markers") in _levels(result)
    assert ("ERROR", "crash_markers") not in _levels(result)
    assert result.leg["crash_markers"] == []


def test_nested_structure_in_a_tag_slot_warns_and_is_stripped():
    """2026-10-26 起形式类不拒收：剥离进 note、打 `tag_slot_nested` 标。"""
    result = intake(_research(tracking_tags=[["a", "b"]]), _leg())
    assert result.blocked is False
    assert ("WARN", "tracking_tags") in _levels(result)
    assert "tag_slot_nested" in result.leg["intake_warn"]
    assert result.leg["tracking_tags"] == []


def test_lexicon_members_survive_untouched():
    result = intake(
        _research(nondirectional_flags=["two_way_instability"]), _leg()
    )
    assert result.leg["nondirectional_flags"] == ["two_way_instability"]
    assert result.issues == [] or all(i.level == "WARN" for i in result.issues)


def test_uncontrolled_hole_location_warns_without_blocking_or_rewriting():
    hole = {
        "unit": "midfield",
        "side": "hosts",
        "priced_in": False,
        "detail": "原样保留",
    }
    result = intake(_research(hole_location=hole), _leg())

    assert result.blocked is False
    assert result.leg["_hole"] == hole
    assert [
        (issue.level, issue.field)
        for issue in result.issues
        if issue.field == "hole_location_uncontrolled"
    ] == [
        ("WARN", "hole_location_uncontrolled"),
        ("WARN", "hole_location_uncontrolled"),
    ]


def test_controlled_hole_location_is_silent():
    result = intake(
        _research(
            hole_location={
                "unit": "creation",
                "side": "away",
                "priced_in": True,
                "detail": "组织核缺阵",
            }
        ),
        _leg(),
    )

    assert not any(
        issue.field == "hole_location_uncontrolled" for issue in result.issues
    )


def test_bare_directional_flag_gets_the_default_face():
    result = intake(_research(directional_flags=["anchor_shield_out"]), _leg())
    assert result.leg["directional_flags"] == [["anchor_shield_out", "1"]]


def test_directional_flag_pointing_at_a_bogus_face_is_stripped():
    result = intake(
        _research(directional_flags=[["anchor_shield_out", "draw"]]), _leg()
    )
    assert result.blocked is False
    assert result.leg["directional_flags"] == []
    assert "directional_face_bogus" in result.leg["intake_warn"]


# —— 结构自相矛盾 ————————————————————————————————

def test_q4_true_with_only_a_directional_flag_is_legal():
    """④ 只数**情境旗**：方向性旗归 C1/C2/C10 管，不进四问④。

    2026-09-18 之前这里断言的是「挂任何旗 + ④=true 即 ERROR」，
    于是 26129 场5（只挂 anchor_shield_out）与场9（只挂 league_draw_regime）
    两份合规研究被拒收，而同期场6 的**真矛盾**混在这两条误报里一起被无视。
    RULEBOOK m-四问 的条文是「情境旗（无方向旗）与 crash_markers 同样封牌照」。
    """
    research = _research()                       # 只带一条方向性旗
    research["license_questions"]["q4_no_context_flag"] = True
    result = intake(research, _leg())
    assert result.blocked is False
    assert ("ERROR", "license_questions") not in _levels(result)


def test_q4_true_while_a_context_flag_is_present_is_a_contradiction():
    """挂着**无方向**情境旗却判 ④=true —— 这才是纯机械可判的矛盾。"""
    research = _research(nondirectional_flags=["two_way_instability"])
    research["license_questions"]["q4_no_context_flag"] = True
    result = intake(research, _leg())
    # 2026-10-26：矛盾仍被点名，但入库并打标（26143/26147/26148 三期为此手工绕行）
    assert result.blocked is False
    assert ("WARN", "license_questions") in _levels(result)
    assert "q4_context_conflict" in result.leg["intake_warn"]
    assert result.leg["license_questions"]["q4_no_context_flag"] is True


def test_q4_true_while_a_crash_marker_is_present_is_a_contradiction():
    """crash_markers 与情境旗同样封牌照（26129 场6 的真错）。"""
    research = _research(crash_markers=["opening_promoted_vs_paper"])
    research["license_questions"]["q4_no_context_flag"] = True
    result = intake(research, _leg())
    assert result.blocked is False
    assert "q4_context_conflict" in result.leg["intake_warn"]


def test_dead_precedent_with_a_real_match_survives_its_carrier_reason():
    """先例里有**真发生过的比赛**（年月+比分）→ `dead` 合法，哪怕理由里写了「不可得」。

    26129 场9 的真实样本：载体死亡的理由文本里出现「跨季同口径名单不可得/无可用
    跨季球员统计」，旧判据按措辞把整条先例误判成「查无先例」。
    """
    research = _research(precedents=[[
        "3",
        "2022-08-30 法乙 第戎 0-2 阿纳西（第戎主场）。载体判定：前提卡明确"
        "「跨季同口径名单不可得/无可用跨季球员统计」，承载该结果的球员已全部不在",
        "dead",
    ]])
    result = intake(research, _leg())
    assert ("ERROR", "precedents") not in _levels(result)


def test_dead_precedent_without_any_real_match_is_still_caught():
    """真正的「查无先例」记成 dead 仍然要拦（26128 场14 的原始事故）。"""
    research = _research(precedents=[[
        "1", "无——马拉卡纳同型对独立谷不存在 90' 平局先例", "dead",
    ]])
    result = intake(research, _leg())
    assert "precedents_absent_as_dead" in result.leg["intake_warn"]
    assert result.leg["precedents"] == []


def test_dead_face_without_three_proofs_warns():
    """死面必须三证齐；不齐只能叫「被削弱」。"""
    result = intake(
        _research(
            structurally_dead_face="away",
            death_three_proofs={"away": {"a": True, "b": True, "c": False}},
        ),
        _leg(),
    )
    assert result.blocked is False
    assert ("WARN", "structurally_dead_face") in _levels(result)
    assert "dead_face_proofs_short" in result.leg["intake_warn"]


def test_dead_face_with_three_proofs_passes():
    result = intake(
        _research(
            anchor_integrity="pass",
            structurally_dead_face="away",
            death_three_proofs={"away": {"a": True, "b": True, "c": True}},
        ),
        _leg(),
    )
    assert result.blocked is False


def test_none_dead_face_is_not_checked():
    result = intake(_research(structurally_dead_face="none"), _leg())
    assert result.blocked is False


def test_bad_anchor_integrity_value_normalises_with_a_warn_code():
    result = intake(_research(anchor_integrity="有洞"), _leg())
    assert result.blocked is False
    assert result.leg["anchor_integrity"] == "unknown"
    assert "anchor_integrity_enum" in result.leg["intake_warn"]


def test_missing_confidence_defaults_with_a_warn_code():
    research = _research()
    del research["confidence"]
    result = intake(research, _leg())
    assert result.blocked is False
    assert result.leg["confidence"] == 3
    assert "confidence_missing" in result.leg["intake_warn"]


# —— 只有缺核心才拒收（2026-10-26）————————————————————

def test_missing_stance_face_is_the_only_core_rejection():
    research = _research()
    del research["stance"]
    result = intake(research, _leg())
    assert result.blocked is True
    assert [i.code for i in result.issues if i.level == "ERROR"] == ["missing_core"]


def test_non_object_research_is_rejected():
    result = intake("not json", _leg(), match_no=3)
    assert result.blocked is True
    assert result.issues[0].code == "research_not_object"


def test_clean_research_has_only_core_shape_warns():
    """夹具没有天平与三证 → core_* 只打形式码，不拒。"""
    result = intake(_research(), _leg())
    assert result.blocked is False
    assert {"core_proofs_incomplete", "core_verdict_missing"} <= set(result.leg["intake_warn"])
    assert not any(i.level == "ERROR" for i in result.issues)


# —— 定义漂移与编码/正文相反 ————————————————————

def test_third_proof_differing_across_faces_is_flagged():
    """26128 场2：(c) 在 home/draw 为 true 而 away 为 false。
    (c) 的宪法口径是「正路完整度 PASS」，一条腿只有一个值。"""
    result = intake(
        _research(
            anchor_integrity="pass",
            death_three_proofs={
                "home": {"a": False, "b": False, "c": True},
                "draw": {"a": False, "b": False, "c": True},
                "away": {"a": False, "b": False, "c": False},
            },
        ),
        _leg(),
    )
    assert result.blocked is False
    assert ("WARN", "death_three_proofs") in _levels(result)


def test_third_proof_contradicting_anchor_integrity_is_flagged():
    result = intake(
        _research(
            anchor_integrity="fail",
            death_three_proofs={"draw": {"a": False, "b": False, "c": True}},
        ),
        _leg(),
    )
    assert any(
        i.field == "death_three_proofs" and "定义漂移" in i.message
        for i in result.issues
    )


def test_coding_opposite_to_prose_is_flagged_for_review():
    """26128 场7：q3b 编码 false，同一份 summary 写「③b 的答案是『在』」。"""
    result = intake(
        _research(summary="4) ③b 的答案是『在』: 攻端载体全部健康并进预测首发。"),
        _leg(),
    )
    assert result.blocked is False
    assert any(
        i.field == "license_questions" and "正文" in i.message for i in result.issues
    )


def test_prose_agreeing_with_the_coding_is_silent():
    result = intake(
        _research(summary="③b 不成立：对手队史欧战客场从未赢过五大联赛球队。"),
        _leg(),
    )
    assert not any("正文" in i.message for i in result.issues)


def test_prose_scan_never_blocks():
    """编码/正文分歧是人工复核项，不是机器可裁的事实。"""
    result = intake(_research(summary="③b 成立，对手能取分。"), _leg())
    assert result.blocked is False


# —— 转录 ————————————————————————————————————————

def test_faces_are_never_touched():
    """判断不在这里：入库桥不改任何一场买什么。"""
    result = intake(_research(), _leg())
    assert result.leg["faces"] == "310"
    assert result.leg["fair"] == _leg()["fair"]


def test_report_lists_every_issue_without_folding():
    results = [
        intake(_research(nondirectional_flags=["agent_自命名的旗"]), _leg())
    ]
    text = format_report(results)
    assert "1 场" in text
    assert "agent_自命名的旗" in text


# —— 先例状态：查无先例必须记 none（2026-09-17）——————————

def test_no_precedent_prose_tagged_dead_is_refused():
    """26128 场14 原文：`["1","无——马拉卡纳同型对独立谷不存在 90' 平局先例","dead"]`。
    记错会让 C14 的昂贵排除豁免凭空成立。"""
    result = intake(
        _research(precedents=[["1", "无——同型对该队不存在 90' 平局先例", "dead"]]),
        _leg(),
    )
    assert result.blocked is False
    assert ("WARN", "precedents") in _levels(result)
    assert result.leg["precedents"] == []


def test_the_same_prose_tagged_none_is_accepted():
    result = intake(
        _research(precedents=[["1", "无——同型对该队不存在 90' 平局先例", "none"]]),
        _leg(),
    )
    assert result.blocked is False
    assert result.leg["precedents"] == [
        ["1", "无——同型对该队不存在 90' 平局先例", "none"]
    ]


def test_a_real_dead_precedent_still_passes():
    result = intake(
        _research(precedents=[["1", "2020 同型平局，载体已全部离队", "dead"]]),
        _leg(),
    )
    assert result.blocked is False
    assert result.leg["precedents"][0][2] == "dead"


def test_off_lexicon_precedent_status_is_dropped_with_a_warn_code():
    result = intake(_research(precedents=[["1", "同型平局", "maybe"]]), _leg())
    assert result.blocked is False
    assert result.leg["precedents"] == []
    assert "precedents_status" in result.leg["intake_warn"]


def test_malformed_precedent_tuple_is_dropped_with_a_warn_code():
    result = intake(_research(precedents=[["1", "只有两项"]]), _leg())
    assert result.blocked is False
    assert "precedents_shape" in result.leg["intake_warn"]


def test_intake_transcribes_research_stance_and_strength_balance():
    balance = {"verdict": "home_edge", "underdog_path": {"side": "away", "exists": True,
                                                        "routes": ["定位球"], "strength": "weak"}}
    research = _research(
        stance={"face": "3", "structure": "double", "cover": "1", "confidence": 3,
                "falsifier": "客队 90 分钟赢球则作废"},
        strength_balance=balance,
    )
    leg = intake(research, _leg()).leg
    assert leg["research_stance"] == {"face": "3", "structure": "double", "cover": "1",
                                      "confidence": 3}
    assert leg["strength_balance"] == balance


def _underdog_warns(result):
    return [i for i in result.issues if i.field == "underdog_path"]


def test_missing_underdog_path_warns_without_blocking():
    """2026-10-19 Jun 定 side/strength 必填（决策树样本的翻车面标签）。缺了只 WARN：
    拒收会烧 40 场/日预算并在 R0/R1 覆盖上留缺口（与 rubric 漏写同一纪律）。"""
    result = intake(_research(strength_balance={"verdict": "home_edge"}), _leg())
    assert result.blocked is False
    assert [i.level for i in _underdog_warns(result)] == ["WARN"]


def test_off_lexicon_underdog_side_or_strength_warns_and_is_kept_verbatim():
    balance = {"verdict": "home_edge",
               "underdog_path": {"side": "visitors", "strength": "moderate", "routes": []}}
    result = intake(_research(strength_balance=balance), _leg())
    assert result.blocked is False
    assert len(_underdog_warns(result)) == 2
    assert result.leg["strength_balance"] == balance                 # 只报不改


def test_controlled_underdog_path_is_silent():
    balance = {"verdict": "away_edge",
               "underdog_path": {"side": "home", "exists": True, "routes": ["定位球"],
                                 "strength": "real"}}
    assert _underdog_warns(intake(_research(strength_balance=balance), _leg())) == []


def test_pre_strength_v2_research_without_balance_is_not_flagged():
    """09-26 前的旧 schema 没有 strength_balance 整块，不追溯报缺。"""
    assert _underdog_warns(intake(_research(), _leg())) == []


def test_overlong_crash_marker_is_stripped_into_note_as_a_warning():
    """标签位写叙述：内容已剥离进 note，不再整份驳回（周六006/013 2026-09-26）。"""
    long = ("观察项（不挂旗）：大分7轮4平、除4-1那场外6场只进2球。"
            "这是n=7的产出统计，没到挂旗的证据等级")
    result = intake(_research(crash_markers=[long]), _leg())
    assert ("WARN", "crash_markers") in _levels(result)
    assert ("ERROR", "crash_markers") not in _levels(result)
    assert "大分7轮4平" in result.leg["note"]


def test_match_no_falls_back_to_the_file_key_when_research_omits_it():
    """2026-09-28 出生事故：并集池 headless 研究不写 match_no，入库桥把 13 场全记成场0，
    写回时一个覆盖一个，legs-base 多出一条「场0」，其余 13 场的 research_stance 全丢。"""
    research = _research()
    research.pop("match_no")
    assert intake(research, _leg(), match_no=8).match_no == 8
    assert intake(_research(), _leg(), match_no=8).match_no == 7   # 研究自带的优先
