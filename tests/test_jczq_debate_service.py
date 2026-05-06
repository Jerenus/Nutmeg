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
