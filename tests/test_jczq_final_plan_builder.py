"""Tests for the structured final-plan builder.

`jczq-debate-finalize` enriches a thin hand-authored ticket skeleton
(`final-plan-input.json`) into the PDF-ready `final-plan.json` consumed by
`jczq_final_plan_pdf`. Leg detail (league/home/away/odds/goal_line/logic) is
joined from the day's `context.json`; odds math and the concentration audit
are computed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.services.jczq_final_plan_builder import (
    FinalPlanBuilderError,
    build_structured_final_plan,
)


def _context() -> dict:
    """A minimal brief context.json with two matches and candidates."""
    return {
        "run_date": "2026-05-17",
        "matches": [
            {
                "match_no": "周日028",
                "match_date": "2026-05-17",
                "match_time": "21:00:00",
                "league": "意甲",
                "home_team": "萨索洛",
                "away_team": "莱切",
                "status": "Selling",
                "hot_direction": "主胜",
                "role": "favorite",
                "confidence_note": "",
                "candidates": [
                    {
                        "match_no": "周日028",
                        "league": "意甲",
                        "home_team": "萨索洛",
                        "away_team": "莱切",
                        "pool": "had",
                        "play": "胜平负",
                        "pick": "胜",
                        "odds": 2.68,
                        "goal_line": "",
                        "logic": "主场 favorite",
                    },
                ],
            },
            {
                "match_no": "周日029",
                "match_date": "2026-05-17",
                "match_time": "21:00:00",
                "league": "意甲",
                "home_team": "乌迪内斯",
                "away_team": "克雷莫纳",
                "status": "Selling",
                "hot_direction": "主胜",
                "role": "favorite",
                "confidence_note": "",
                "candidates": [
                    {
                        "match_no": "周日029",
                        "league": "意甲",
                        "home_team": "乌迪内斯",
                        "away_team": "克雷莫纳",
                        "pool": "hhad",
                        "play": "让球胜平负",
                        "pick": "让胜",
                        "odds": 1.80,
                        "goal_line": "+1",
                        "logic": "让球不败 cover",
                    },
                ],
            },
        ],
    }


def _input_skeleton() -> dict:
    """A thin hand-authored ticket skeleton: which legs, what stakes."""
    return {
        "budget_total": 100,
        "config_variant": "fcom500-conflict-engine",
        "config_variant_note": "500.com 欧赔",
        "rule_environment": ["胜平负聚焦版"],
        "human_decision_summary": "校准后冲突引擎首份方案。",
        "favorite_ticket_id": "A",
        "tickets": [
            {
                "id": "A",
                "name": "主推 · 双意甲主场",
                "kind": "anchor",
                "stake": 60,
                "favorite_reason": "两腿均 strong edge",
                "legs": [
                    {"match_no": "周日028", "pool": "had", "pick": "胜"},
                    {"match_no": "周日029", "pool": "hhad", "pick": "让胜"},
                ],
            },
            {
                "id": "B",
                "name": "单腿底仓",
                "kind": "main",
                "stake": 40,
                "legs": [
                    {"match_no": "周日028", "pool": "had", "pick": "胜"},
                ],
            },
        ],
    }


def _write(tmp_path: Path, *, context: dict, skeleton: dict) -> tuple[Path, Path]:
    daily = tmp_path / "daily" / "2026-05-17"
    debate = daily / "debate"
    debate.mkdir(parents=True)
    (daily / "context.json").write_text(
        json.dumps(context, ensure_ascii=False), encoding="utf-8"
    )
    skeleton_path = debate / "final-plan-input.json"
    skeleton_path.write_text(json.dumps(skeleton, ensure_ascii=False), encoding="utf-8")
    return daily / "context.json", skeleton_path


def test_builder_enriches_legs_from_context(tmp_path: Path) -> None:
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    leg = plan["tickets"][0]["legs"][0]
    assert leg["match_no"] == "周日028"
    assert leg["league"] == "意甲"
    assert leg["home"] == "萨索洛"
    assert leg["away"] == "莱切"
    assert leg["pool"] == "had"
    assert leg["pick"] == "胜"
    assert leg["odds"] == 2.68
    assert leg["logic"] == "主场 favorite"


def test_builder_carries_goal_line_for_handicap_legs(tmp_path: Path) -> None:
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    hhad_leg = plan["tickets"][0]["legs"][1]
    assert hhad_leg["pool"] == "hhad"
    assert hhad_leg["goal_line"] == "+1"


def test_builder_computes_ticket_odds_and_payout(tmp_path: Path) -> None:
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    ticket_a = plan["tickets"][0]
    # 2.68 * 1.80 = 4.824 → rounded to 4.82 for display.
    assert ticket_a["total_odds"] == pytest.approx(4.82, abs=0.01)
    # payout = stake * displayed total_odds = 60 * 4.82 (matches the
    # reference 5/17 sample, which rounds odds before computing payout).
    assert ticket_a["theoretical_payout"] == pytest.approx(289.2, abs=0.1)


def test_builder_computes_portfolio_total_stake(tmp_path: Path) -> None:
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    assert plan["portfolio_metrics"]["total_stake"] == 100
    assert plan["budget_total"] == 100
    assert plan["run_date"] == "2026-05-17"


def test_builder_runs_concentration_audit_for_shared_match(tmp_path: Path) -> None:
    # 周日028 appears in both ticket A and ticket B → shared match.
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    audit = plan["concentration_audit"]
    shared = audit["shared_matches"]
    assert len(shared) == 1
    assert shared[0]["match_no"] == "周日028"
    assert sorted(shared[0]["tickets"]) == ["A", "B"]
    assert shared[0]["stake_at_risk"] == 100
    assert audit["rule_o_violations"] == 0


def test_builder_flags_rule_o_violation_same_match_diff_pool(tmp_path: Path) -> None:
    # Rule O: one ticket must not bet the same match on two different pools.
    skeleton = _input_skeleton()
    skeleton["tickets"][0]["legs"] = [
        {"match_no": "周日028", "pool": "had", "pick": "胜"},
        {"match_no": "周日028", "pool": "hhad", "pick": "让胜"},
    ]
    context = _context()
    context["matches"][0]["candidates"].append(
        {
            "match_no": "周日028",
            "league": "意甲",
            "home_team": "萨索洛",
            "away_team": "莱切",
            "pool": "hhad",
            "play": "让球胜平负",
            "pick": "让胜",
            "odds": 1.55,
            "goal_line": "+1",
            "logic": "",
        }
    )
    ctx_path, skel_path = _write(tmp_path, context=context, skeleton=skeleton)

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    assert plan["concentration_audit"]["rule_o_violations"] == 1


def test_builder_raises_when_leg_not_found_in_context(tmp_path: Path) -> None:
    skeleton = _input_skeleton()
    skeleton["tickets"][0]["legs"] = [
        {"match_no": "周日999", "pool": "had", "pick": "胜"},
    ]
    ctx_path, skel_path = _write(tmp_path, context=_context(), skeleton=skeleton)

    with pytest.raises(FinalPlanBuilderError, match="周日999"):
        build_structured_final_plan(
            run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
        )


def test_builder_preserves_skeleton_metadata_passthrough(tmp_path: Path) -> None:
    ctx_path, skel_path = _write(
        tmp_path, context=_context(), skeleton=_input_skeleton()
    )

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    assert plan["config_variant"] == "fcom500-conflict-engine"
    assert plan["config_variant_note"] == "500.com 欧赔"
    assert plan["rule_environment"] == ["胜平负聚焦版"]
    assert plan["human_decision_summary"] == "校准后冲突引擎首份方案。"
    assert plan["favorite_ticket_id"] == "A"
    # The favorite ticket gets favorite=True; others favorite=False.
    assert plan["tickets"][0]["favorite"] is True
    assert plan["tickets"][1]["favorite"] is False


def test_builder_per_leg_odds_override_wins_over_context(tmp_path: Path) -> None:
    # The human may pin an odds value in the skeleton leg (brief-confirmed
    # number that differs from the stale context candidate); it must win.
    skeleton = _input_skeleton()
    skeleton["tickets"][0]["legs"][0]["odds"] = 2.75
    ctx_path, skel_path = _write(tmp_path, context=_context(), skeleton=skeleton)

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    assert plan["tickets"][0]["legs"][0]["odds"] == 2.75


def test_builder_carries_excluded_matches_passthrough(tmp_path: Path) -> None:
    skeleton = _input_skeleton()
    skeleton["excluded_matches"] = [
        {"match_no": "周日030", "reason": "逆向强 edge，不入主推"}
    ]
    ctx_path, skel_path = _write(tmp_path, context=_context(), skeleton=skeleton)

    plan = build_structured_final_plan(
        run_date="2026-05-17", context_path=ctx_path, skeleton_path=skel_path
    )

    assert plan["excluded_matches"] == [
        {"match_no": "周日030", "reason": "逆向强 edge，不入主推"}
    ]
