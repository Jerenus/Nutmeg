from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.services.jczq_web import JczqWebCockpitService, JczqWebValidationError
from nutmeg.storage.jczq_web_repository import JczqWebRepository

BRIEF_TEXT = """# JCZQ 每日 Brief — 2026-05-06

官方赔率更新：2026-05-06 11:37:54
全天可售场次：3

## 1. 盘面热度扫描

| 编号 | 联赛 | 对阵 | 热门方向 | 让球线 | 角色 | 强胆 | 舒服盘 | draw | coinflip | hi-vol联赛 |
|---|---|---|---|---|---|---|---|---|---|---|
| 周三001 | 日职 | 广岛三箭 vs 神户胜利 | 主胜低赔(2.05) | -1 | 均衡分歧场 |  | ✓ |  |  |  |
| 周三003 | 日职 | 川崎前锋 vs 东京绿茵 | 主胜低赔(1.88) | -1 | 均衡分歧场 |  | ✓ |  |  |  |
| 周三009 | 解放者杯 | 圣菲独立 vs 科林蒂安 | 客胜低赔(2.60) | -1 | 均衡分歧场 |  |  | ✓ | ⚠ |  |

## 4. Poisson 模型指出的 +EV 腿（edge ≥ +5%）

| 标的 | 池 | 选项 | 市场 | 公允 | edge | 对阵 |
|---|---|---|---|---|---|---|
| 周三003 | crs | 0:0 | 11.00 | 9.03 | **+21.9%** | 川崎前锋 vs 东京绿茵 |
| 周三003 | ttg | 1球 | 4.45 | 4.10 | **+8.5%** | 川崎前锋 vs 东京绿茵 |
| 周三009 | ttg | 1球 | 3.30 | 3.20 | **+3.0%** | 圣菲独立 vs 科林蒂安 |
Poisson 强烈反对腿（edge ≤ -20%）：
- ❌ 周三005 ttg 3球 Poisson edge -24.6%（强烈反对）
"""


def _service(tmp_path: Path) -> JczqWebCockpitService:
    repo = JczqWebRepository(tmp_path / "cockpit.sqlite3")
    repo.initialize()
    return JczqWebCockpitService(output_dir=tmp_path, repository=repo)


def test_load_brief_writes_artifact_and_structured_sqlite_rows(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)

    assert result["status"] == "brief_generated"
    assert (tmp_path / "daily" / "2026-05-06" / "brief.md").exists()
    workspace = service.workspace("2026-05-06")
    assert workspace["day"]["status"] == "brief_generated"
    assert [match["match_no"] for match in workspace["matches"]] == [
        "周三001",
        "周三003",
        "周三009",
    ]
    assert workspace["matches"][2]["flags"]["coinflip"] is True
    assert workspace["candidate_legs"][0]["match_no"] == "周三003"
    assert workspace["candidate_legs"][0]["poisson_edge"] == 0.219


def test_debate_analysis_save_and_compare_updates_artifacts_and_sqlite(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)

    init = service.initialize_debate("2026-05-06")
    assert init["status"] == "initialized"
    service.save_analysis(
        run_date="2026-05-06",
        agent="gpt",
        content="`周三003比分0:0@11.0`\n- 删除 周三005总进球3球：Poisson强反对",
    )
    service.save_analysis(
        run_date="2026-05-06",
        agent="claude",
        content="`周三003 比分 0:0 @ 11.0`",
    )

    result = service.compare_debate("2026-05-06")

    assert result["status"] == "compared"
    assert ["周三003", "crs", "0:0"] in result["structured_consensus"]
    debate_dir = tmp_path / "daily" / "2026-05-06" / "debate"
    assert "| 周三003 | crs | 0:0 |" in (debate_dir / "disagreements.md").read_text(
        encoding="utf-8"
    )
    assert service.workspace("2026-05-06")["analyses"]["gpt"]["brief_hash"]


def test_draft_ticket_version_calculates_odds_and_soft_warnings(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)

    result = service.draft_ticket_version(
        run_date="2026-05-06",
        source="human",
        best_pick="C",
        tickets=[
            {
                "ticket_id": "C",
                "kind": "poisson_solo",
                "name": "Poisson 单核",
                "stake": 25,
                "is_best_pick": True,
                "is_extra_budget": False,
                "rationale": "尝试串关放大",
                "legs": [
                    {
                        "match_no": "周三003",
                        "pool": "crs",
                        "play": "比分",
                        "pick": "0:0",
                        "odds": 11.0,
                    },
                    {
                        "match_no": "周三009",
                        "pool": "ttg",
                        "play": "总进球",
                        "pick": "1球",
                        "odds": 3.3,
                    },
                ],
            }
        ],
    )

    assert result["version"] == 1
    ticket = result["tickets"][0]
    assert ticket["total_odds"] == 36.3
    assert ticket["theoretical_return"] == 907.5
    assert any(finding["code"] == "poisson_solo_dilution" for finding in result["findings"])
    assert not any(finding["blocks_finalization"] for finding in result["findings"])


def test_hard_rule_blocks_ticket_save(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)

    with pytest.raises(JczqWebValidationError) as excinfo:
        service.draft_ticket_version(
            run_date="2026-05-06",
            source="human",
            tickets=[
                {
                    "ticket_id": "A",
                    "kind": "stable_base",
                    "name": "违规底仓",
                    "stake": 25,
                    "legs": [
                        {
                            "match_no": "周三009",
                            "pool": "had",
                            "play": "胜平负",
                            "pick": "胜",
                            "odds": 2.6,
                        }
                    ],
                }
            ],
        )

    assert excinfo.value.findings[0]["code"] == "coinflip_had"
    assert service.workspace("2026-05-06")["versions"] == []


def test_finalize_version_exports_markdown_and_json(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)
    draft = service.draft_ticket_version(
        run_date="2026-05-06",
        source="human",
        best_pick="C",
        tickets=[
            {
                "ticket_id": "C",
                "kind": "poisson_solo",
                "name": "Poisson 单核",
                "stake": 25,
                "is_best_pick": True,
                "legs": [
                    {
                        "match_no": "周三003",
                        "league": "日职",
                        "home_team": "川崎前锋",
                        "away_team": "东京绿茵",
                        "pool": "crs",
                        "play": "比分",
                        "pick": "0:0",
                        "odds": 11.0,
                        "poisson_edge": 0.219,
                    }
                ],
            }
        ],
    )

    result = service.finalize_version("2026-05-06", draft["version"])

    final_plan = Path(result["final_plan_path"]).read_text(encoding="utf-8")
    final_json = json.loads(Path(result["final_plan_json_path"]).read_text(encoding="utf-8"))
    assert "JCZQ Final Plan — 2026-05-06" in final_plan
    assert "周三003 比分0:0 @ 11.00" in final_plan
    assert final_json["tickets"][0]["total_odds"] == 11.0
    assert service.workspace("2026-05-06")["day"]["status"] == "finalized"


def test_record_review_persists_manual_ticket_and_leg_corrections(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.load_brief(run_date="2026-05-06", brief_text=BRIEF_TEXT)
    draft = service.draft_ticket_version(
        run_date="2026-05-06",
        source="human",
        tickets=[
            {
                "ticket_id": "C",
                "kind": "poisson_solo",
                "stake": 25,
                "legs": [
                    {"match_no": "周三003", "pool": "crs", "pick": "0:0", "odds": 11.0}
                ],
            }
        ],
    )

    result = service.record_review(
        run_date="2026-05-06",
        version=draft["version"],
        ticket_id="C",
        status="miss",
        actual_return=0,
        profit_loss=-25,
        failed_leg="周三003 比分0:0",
        notes="人工修正赛果为 1:0",
        leg_reviews=[
            {
                "leg_index": 1,
                "match_no": "周三003",
                "pool": "crs",
                "pick": "0:0",
                "status": "miss",
                "actual_result": "1:0",
                "notes": "手动录入",
            }
        ],
    )

    assert result["status"] == "reviewed"
    assert service.workspace("2026-05-06")["reviews"][0]["leg_reviews"][0]["actual_result"] == "1:0"
