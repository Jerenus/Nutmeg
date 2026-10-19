from nutmeg.decision.research_prompt import (
    RESEARCH_JSON_CONTRACT,
    render_brief,
    system_prompt,
)


def test_system_prompt_carries_agent_body_and_json_contract():
    prompt = system_prompt()
    assert "反偏置约束" in prompt
    assert "禁嘴算" in prompt
    assert "death_three_proofs" in prompt
    assert "只输出 JSON" in prompt
    assert RESEARCH_JSON_CONTRACT in prompt


def test_research_contract_defines_controlled_hole_location_vocabulary():
    assert '"unit": "attack|creation|spine|defense|goalkeeper|both|none"' in RESEARCH_JSON_CONTRACT
    assert '"side": "home|away|both|none"' in RESEARCH_JSON_CONTRACT
    assert '"priced_in": bool' in RESEARCH_JSON_CONTRACT
    for meaning in (
        "attack = 破门端",
        "creation = 组织端",
        "spine = 后腰屏障格",
        "defense = 中卫对",
        "goalkeeper = 门将",
        "both = 攻防两端同时缺",
        "none = 无结构性洞",
    ):
        assert meaning in RESEARCH_JSON_CONTRACT


def test_brief_contains_fair_line_and_kickoff_only_from_inputs():
    leg = {
        "name": "A-B",
        "competition": "英超",
        "kickoff_bj": "2026-09-20T03:00:00+08:00",
        "fair": {"home": 0.5, "draw": 0.28, "away": 0.22},
        "hhad_line": -1,
    }

    brief = render_brief(
        code="周五001",
        leg=leg,
        profile_notes={"home": "高位逼抢", "away": ""},
    )

    assert "周五001" in brief
    assert "50.0%" in brief
    assert "让球线 -1" in brief
    assert "高位逼抢" in brief


def test_brief_gives_store_ids_so_premise_corrections_can_land():
    """2026-10-08：26136 十四场查出的主帅更替全留在散文里，回写一条都收不到。"""
    leg = {"name": "A-B", "competition": "法甲", "kickoff_bj": "2026-10-10T02:45:00+08:00",
           "fair": {"home": 0.39, "draw": 0.26, "away": 0.35}}
    brief = render_brief(code="足彩26136-06", leg=leg,
                         profile_notes={"home": "", "away": "", "home_id": "fra-lens"})
    assert "主队 store id：fra-lens" in brief and "客队 store id：（store 无此队）" in brief
    assert "premise_corrections" in brief
    for field in ('"premise_corrections"', '"subject"', '"field"', '"correct"', '"evidence"'):
        assert field in RESEARCH_JSON_CONTRACT, field


def test_contract_names_every_field_the_runner_requires():
    from nutmeg.decision.research_runner import _REQUIRED

    for key in _REQUIRED:
        assert f'"{key}"' in RESEARCH_JSON_CONTRACT, key


def test_prompt_moves_belief_only_through_the_rubric():
    """2026-10-08：分析员定义曾一边让「用 tilt/shift 拨多少」一边说 tilt 写 null。"""
    prompt = system_prompt()
    assert '"tilt": null' in RESEARCH_JSON_CONTRACT
    for stale in ("tilt/shift", "五玩法", "双轴表达", "收尾小结", '"expires_if"'):
        assert stale not in prompt, stale


def test_system_prompt_carries_the_rubric_question_table_from_the_registry():
    from nutmeg.decision.research_prompt import rubric_contract, system_prompt
    from nutmeg.decision.rubric_items import ITEMS, RUBRIC_VERSION

    text = rubric_contract()
    assert all(item_id in text for item_id in ITEMS) and f'"version": "{RUBRIC_VERSION}"' in text
    assert "强制改为弃权" in text and text in system_prompt()
    assert "stance.tilt 不用写" in system_prompt()
