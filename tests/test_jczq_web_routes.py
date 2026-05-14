from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.interfaces.jczq_web import create_jczq_web_app
from nutmeg.services.jczq_web import JczqWebCockpitService
from nutmeg.storage.jczq_web_repository import JczqWebRepository

BRIEF_TEXT = """# JCZQ 每日 Brief — 2026-05-06

## 1. 盘面热度扫描
| 编号 | 联赛 | 对阵 | 热门方向 | 让球线 | 角色 | 强胆 | 舒服盘 | draw | coinflip | hi-vol联赛 |
|---|---|---|---|---|---|---|---|---|---|---|
| 周三003 | 日职 | 川崎前锋 vs 东京绿茵 | 主胜低赔(1.88) | -1 | 均衡分歧场 |  | ✓ |  |  |  |

## 4. Poisson 模型指出的 +EV 腿（edge ≥ +5%）
| 标的 | 池 | 选项 | 市场 | 公允 | edge | 对阵 |
|---|---|---|---|---|---|---|
| 周三003 | crs | 0:0 | 11.00 | 9.03 | **+21.9%** | 川崎前锋 vs 东京绿茵 |
"""


def _client(tmp_path: Path) -> TestClient:
    repo = JczqWebRepository(tmp_path / "cockpit.sqlite3")
    repo.initialize()
    service = JczqWebCockpitService(output_dir=tmp_path, repository=repo)
    return TestClient(create_jczq_web_app(service=service))


def test_dashboard_and_workspace_pages_render_daily_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/jczq/daily/2026-05-06/brief", data={"brief_text": BRIEF_TEXT})

    dashboard = client.get("/jczq")
    workspace = client.get("/jczq/daily/2026-05-06")

    assert dashboard.status_code == 200
    assert "JCZQ Cockpit" in dashboard.text
    assert "2026-05-06" in dashboard.text
    assert workspace.status_code == 200
    assert "周三003" in workspace.text
    assert "Poisson" in workspace.text


def test_routes_save_analysis_compare_ticket_finalize_and_review(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/jczq/daily/2026-05-06/brief", data={"brief_text": BRIEF_TEXT})
    client.post("/jczq/daily/2026-05-06/debate/init")
    save_response = client.post(
        "/jczq/daily/2026-05-06/analysis/gpt",
        data={"content": "`周三003比分0:0@11.0`"},
        follow_redirects=False,
    )
    client.post(
        "/jczq/daily/2026-05-06/analysis/claude",
        data={"content": "`周三003 比分 0:0 @ 11.0`"},
    )
    compare = client.post("/jczq/daily/2026-05-06/debate/compare", follow_redirects=False)
    draft = client.post(
        "/jczq/daily/2026-05-06/tickets/draft",
        json={
            "source": "human",
            "best_pick": "C",
            "tickets": [
                {
                    "ticket_id": "C",
                    "kind": "poisson_solo",
                    "name": "Poisson 单核",
                    "stake": 25,
                    "is_best_pick": True,
                    "legs": [
                        {
                            "match_no": "周三003",
                            "pool": "crs",
                            "play": "比分",
                            "pick": "0:0",
                            "odds": 11.0,
                        }
                    ],
                }
            ],
        },
    )
    finalize = client.post(
        "/jczq/daily/2026-05-06/tickets/1/finalize",
        follow_redirects=False,
    )
    review = client.post(
        "/jczq/daily/2026-05-06/reviews",
        json={
            "version": 1,
            "ticket_id": "C",
            "status": "hit",
            "actual_return": 275,
            "profit_loss": 250,
            "failed_leg": None,
            "notes": "人工确认",
            "leg_reviews": [
                {
                    "leg_index": 1,
                    "match_no": "周三003",
                    "pool": "crs",
                    "pick": "0:0",
                    "status": "hit",
                    "actual_result": "0:0",
                    "notes": "命中",
                }
            ],
        },
    )

    assert save_response.status_code == 303
    assert compare.status_code == 303
    assert draft.status_code == 200
    assert draft.json()["tickets"][0]["theoretical_return"] == 275.0
    assert finalize.status_code == 303
    assert review.status_code == 200
    assert review.json()["status"] == "reviewed"
    workspace = client.get("/jczq/daily/2026-05-06")
    assert "final-plan.md" in workspace.text
    assert "reviewed" in workspace.text
