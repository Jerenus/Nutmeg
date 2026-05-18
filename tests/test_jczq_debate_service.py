from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_debate import JczqDebateWorkspaceService


def test_debate_workspace_init_creates_shared_brief_and_model_templates(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily" / "2026-05-06"
    run_dir.mkdir(parents=True)
    (run_dir / "brief.md").write_text(
        "# JCZQ 每日 Brief — 2026-05-06\n\n## 4. Poisson 模型指出的 +EV 腿\n",
        encoding="utf-8",
    )

    result = JczqDebateWorkspaceService().initialize_workspace(
        run_date="2026-05-06",
        output_dir=tmp_path,
    )

    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    assert result["run_date"] == "2026-05-06"
    assert result["debate_dir"] == str(debate_dir)
    assert (debate_dir / "shared-brief.md").read_text(encoding="utf-8").startswith(
        "# JCZQ 每日 Brief"
    )
    assert "## 盘面总判断" in (debate_dir / "gpt-analysis.md").read_text(encoding="utf-8")
    assert "## 盘面总判断" in (debate_dir / "claude-analysis.md").read_text(
        encoding="utf-8"
    )
    assert "### C Poisson" not in (debate_dir / "gpt-analysis.md").read_text(
        encoding="utf-8"
    )
    assert "人工裁决" in (debate_dir / "human-notes.md").read_text(encoding="utf-8")
    log = json.loads((debate_dir / "decision-log.json").read_text(encoding="utf-8"))
    assert log["status"] == "initialized"
    assert log["run_date"] == "2026-05-06"


def test_debate_compare_writes_consensus_and_conflict_summary(tmp_path: Path) -> None:
    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-06",
        output_dir=tmp_path,
        brief_text="# brief\n",
    )
    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    (debate_dir / "gpt-analysis.md").write_text(
        """
# GPT

### A 稳健底仓
`周三003比分0:0@11.0 × 周三007胜平负胜@1.53`

## Dropped Legs
- 周三005总进球4球：Poisson强反对
""".strip(),
        encoding="utf-8",
    )
    (debate_dir / "claude-analysis.md").write_text(
        """
# Claude

### C Poisson
`周三003比分0:0@11.0 × 周三007总进球2球@7.0`

## Dropped Legs
- 周三008总进球3球：Poisson强反对
""".strip(),
        encoding="utf-8",
    )

    result = service.compare_workspace(run_date="2026-05-06", output_dir=tmp_path)

    assert "周三003比分0:0" in result["consensus_legs"]
    assert result["conflict_matches"] == ["周三007"]
    assert "周三005总进球4球" in result["dropped_legs"]
    assert "周三008总进球3球" in result["dropped_legs"]
    disagreements = (debate_dir / "disagreements.md").read_text(encoding="utf-8")
    assert "共同认可" in disagreements
    assert "周三007" in disagreements


def test_debate_compare_uses_semantic_alignment_not_string_match(tmp_path: Path) -> None:
    """5/06 regression: when GPT and Claude both pick `周三003比分0:0@11.0` but
    spell it differently (`周三003 比分 0:0` vs `周三003比分0:0`), v1 string
    extraction missed the consensus. Semantic v2 compares (match, pool, pick)
    tuples so spacing/quoting differences don't break the match."""

    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-06", output_dir=tmp_path, brief_text="# brief\n",
    )
    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    (debate_dir / "gpt-analysis.md").write_text(
        "### C Poisson 单核\n`周三003 比分 0:0 @ 11.0`\n", encoding="utf-8",
    )
    (debate_dir / "claude-analysis.md").write_text(
        "### C Poisson 单核\n`周三003比分0:0@11.0`\n", encoding="utf-8",
    )

    result = service.compare_workspace(run_date="2026-05-06", output_dir=tmp_path)

    assert result["structured_consensus"] == [["周三003", "crs", "0:0"]]
    assert result["consensus_legs"] == ["周三003比分0:0"]
    assert result["conflict_matches"] == []


def test_debate_compare_flags_real_互斥_conflict(tmp_path: Path) -> None:
    """If GPT picks 001 had 胜 and Claude picks 001 had 平, that's real互斥
    on the had pool — must surface in `structured_conflicts`."""

    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-06", output_dir=tmp_path, brief_text="# brief\n",
    )
    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    (debate_dir / "gpt-analysis.md").write_text(
        "`周三001胜平负胜@2.05`", encoding="utf-8",
    )
    (debate_dir / "claude-analysis.md").write_text(
        "`周三001胜平负平@3.25`", encoding="utf-8",
    )

    result = service.compare_workspace(run_date="2026-05-06", output_dir=tmp_path)

    assert ["周三001", "had", "胜", "平"] in result["structured_conflicts"]
    assert "周三001" in result["conflict_matches"]


def test_debate_finalize_writes_final_plan_from_human_notes(tmp_path: Path) -> None:
    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-06",
        output_dir=tmp_path,
        brief_text="# brief\n",
    )
    service.compare_workspace(run_date="2026-05-06", output_dir=tmp_path)
    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    (debate_dir / "human-notes.md").write_text(
        """
# Human Notes

## 人工裁决
- 保留 C：周三003比分0:0@11.0
- 删除 周三008总进球3球

## 最终票
### C Poisson 单核
`周三003比分0:0@11.0`
""".strip(),
        encoding="utf-8",
    )

    result = service.finalize_workspace(run_date="2026-05-06", output_dir=tmp_path)

    final_plan = (debate_dir / "final-plan.md").read_text(encoding="utf-8")
    final_json = json.loads((debate_dir / "final-plan.json").read_text(encoding="utf-8"))
    assert result["status"] == "finalized"
    assert "JCZQ Final Plan — 2026-05-06" in final_plan
    assert "周三003比分0:0@11.0" in final_plan
    assert final_json["run_date"] == "2026-05-06"
    assert final_json["human_notes_path"].endswith("human-notes.md")
    # No final-plan-input.json skeleton → thin-metadata fallback, and the
    # result must say so explicitly so the caller knows the PDF can't render.
    assert result["structured_plan"] is False


def _write_brief_context(daily_dir: Path) -> None:
    """A minimal context.json so the finalize builder can enrich legs."""
    daily_dir.mkdir(parents=True, exist_ok=True)
    context = {
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
                    }
                ],
            }
        ],
    }
    (daily_dir / "context.json").write_text(
        json.dumps(context, ensure_ascii=False), encoding="utf-8"
    )


def test_debate_finalize_builds_structured_plan_from_skeleton(tmp_path: Path) -> None:
    """When a final-plan-input.json skeleton is present, finalize must produce
    the PDF-ready structured final-plan.json — not the thin metadata stub."""

    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-17", output_dir=tmp_path, brief_text="# brief\n",
    )
    daily_dir = tmp_path / "daily" / "2026-05-17"
    _write_brief_context(daily_dir)
    debate_dir = daily_dir / "debate"
    (debate_dir / "final-plan-input.json").write_text(
        json.dumps(
            {
                "budget_total": 100,
                "config_variant": "fcom500-conflict-engine",
                "favorite_ticket_id": "A",
                "tickets": [
                    {
                        "id": "A",
                        "name": "主推",
                        "kind": "anchor",
                        "stake": 100,
                        "legs": [
                            {"match_no": "周日028", "pool": "had", "pick": "胜"}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = service.finalize_workspace(run_date="2026-05-17", output_dir=tmp_path)

    final_json = json.loads((debate_dir / "final-plan.json").read_text(encoding="utf-8"))
    assert result["structured_plan"] is True
    assert result["status"] == "finalized"
    # Structured schema fields the PDF renderer consumes.
    assert final_json["run_date"] == "2026-05-17"
    assert final_json["budget_total"] == 100
    assert final_json["config_variant"] == "fcom500-conflict-engine"
    assert final_json["tickets"][0]["id"] == "A"
    assert final_json["tickets"][0]["total_odds"] == 2.68
    leg = final_json["tickets"][0]["legs"][0]
    assert leg["home"] == "萨索洛"
    assert leg["away"] == "莱切"
    assert "concentration_audit" in final_json


def test_debate_finalize_structured_plan_renders_via_pdf(tmp_path: Path) -> None:
    """The structured plan finalize produces must be directly consumable by
    the final-plan PDF renderer with no hand-editing."""
    from nutmeg.services.jczq_final_plan_pdf import _build_story

    service = JczqDebateWorkspaceService()
    service.initialize_workspace(
        run_date="2026-05-17", output_dir=tmp_path, brief_text="# brief\n",
    )
    daily_dir = tmp_path / "daily" / "2026-05-17"
    _write_brief_context(daily_dir)
    debate_dir = daily_dir / "debate"
    (debate_dir / "final-plan-input.json").write_text(
        json.dumps(
            {
                "budget_total": 100,
                "favorite_ticket_id": "A",
                "tickets": [
                    {
                        "id": "A",
                        "name": "主推",
                        "kind": "anchor",
                        "stake": 100,
                        "hit_probability": 0.28,
                        "expected_value": 42.2,
                        "legs": [
                            {"match_no": "周日028", "pool": "had", "pick": "胜"}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service.finalize_workspace(run_date="2026-05-17", output_dir=tmp_path)
    plan = json.loads((debate_dir / "final-plan.json").read_text(encoding="utf-8"))

    # Must not raise — the renderer accesses many required schema keys.
    story = _build_story(plan)
    assert story
