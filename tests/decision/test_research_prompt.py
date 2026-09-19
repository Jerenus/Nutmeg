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
