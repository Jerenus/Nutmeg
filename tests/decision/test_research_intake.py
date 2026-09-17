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
        _research(nondirectional_flags=["information_asymmetry"]), _leg()
    )
    assert result.blocked is False
    assert result.leg["nondirectional_flags"] == []
    assert "information_asymmetry" in result.leg["note"]
    assert ("WARN", "nondirectional_flags") in _levels(result)


def test_narrative_in_a_tag_slot_is_an_error():
    """26125-26128 反复出现：agent 把整段叙述写进 crash_markers。"""
    result = intake(
        _research(crash_markers=["这场的崩塌通道是中卫板凳归零叠加三天轮转" * 3]),
        _leg(),
    )
    assert result.blocked is True
    assert ("ERROR", "crash_markers") in _levels(result)
    assert result.leg["crash_markers"] == []


def test_nested_structure_in_a_tag_slot_is_an_error():
    result = intake(_research(tracking_tags=[["a", "b"]]), _leg())
    assert result.blocked is True
    assert ("ERROR", "tracking_tags") in _levels(result)


def test_lexicon_members_survive_untouched():
    result = intake(
        _research(nondirectional_flags=["two_way_instability"]), _leg()
    )
    assert result.leg["nondirectional_flags"] == ["two_way_instability"]
    assert result.issues == [] or all(i.level == "WARN" for i in result.issues)


def test_bare_directional_flag_gets_the_default_face():
    result = intake(_research(directional_flags=["anchor_shield_out"]), _leg())
    assert result.leg["directional_flags"] == [["anchor_shield_out", "1"]]


def test_directional_flag_pointing_at_a_bogus_face_is_an_error():
    result = intake(
        _research(directional_flags=[["anchor_shield_out", "draw"]]), _leg()
    )
    assert result.blocked is True


# —— 结构自相矛盾 ————————————————————————————————

def test_q4_true_while_flags_present_is_a_contradiction():
    """四问④『无情境旗』与旗行直接矛盾——这是纯机械可判的。"""
    research = _research()
    research["license_questions"]["q4_no_context_flag"] = True
    result = intake(research, _leg())
    assert result.blocked is True
    assert ("ERROR", "license_questions") in _levels(result)


def test_dead_face_without_three_proofs_is_an_error():
    """死面必须三证齐；不齐只能叫「被削弱」。"""
    result = intake(
        _research(
            structurally_dead_face="away",
            death_three_proofs={"away": {"a": True, "b": True, "c": False}},
        ),
        _leg(),
    )
    assert result.blocked is True
    assert ("ERROR", "structurally_dead_face") in _levels(result)


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


def test_bad_anchor_integrity_value_blocks():
    result = intake(_research(anchor_integrity="有洞"), _leg())
    assert result.blocked is True
    assert result.leg["anchor_integrity"] == "unknown"


def test_missing_confidence_blocks():
    research = _research()
    del research["confidence"]
    result = intake(research, _leg())
    assert result.blocked is True


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
        intake(_research(nondirectional_flags=["information_asymmetry"]), _leg())
    ]
    text = format_report(results)
    assert "1 场" in text
    assert "information_asymmetry" in text
