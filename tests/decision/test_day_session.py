from pathlib import Path

from nutmeg.decision.day_session import (
    append_discussion,
    read_discussion,
    render_session_md,
    write_session,
)


def test_render_session_md_is_compact_and_starts_from_decisions():
    brief = {
        "date": "2026-09-23",
        "generated_at": "2026-09-23T12:00:00+08:00",
        "jczq": {
            "matches": [
                {
                    "code": "周三001",
                    "name": "A vs B",
                    "kickoff_bj": "2026-09-23T19:30:00+08:00",
                    "ladder": "偏移",
                    "research": {"status": "done"},
                    "read": {"judge": "ai:jczq-analyst", "status": "draft", "moved_pp": 6.0},
                    "labels": {"judgment_tier": "deep_research"},
                }
            ],
            "counts": {"matches": 1, "deep_research": 1, "price_only": 0, "drafts": 1},
        },
        "zucai": {
            "issue": "26132",
            "sale_deadline": "2026-09-23T21:00:00+08:00",
            "tiers": None,
            "frontier": {},
            "prep": {},
            "plan": None,
        },
        "rsi": {"human_actions": [], "failed_steps": []},
        "factors": [],
        "errors": [],
    }
    decisions = [
        {
            "id": "read:周三001",
            "kind": "approve_read",
            "subject": "周三001 A vs B",
            "status": "open",
            "deadline": "2026-09-23T19:30:00+08:00",
            "default_action": "草稿不入库＝跟市场",
        }
    ]
    timeline = [
        {"job": "brief", "exit": 0, "finished_at": "2026-09-23T12:00:10+08:00", "summary": "ok"}
    ]
    md = render_session_md(brief, decisions, timeline)
    assert md.startswith("# 会话入口 · 2026-09-23")
    assert "## 待人决定（从这里开始）" in md and "read:周三001" in md and "19:30" in md
    assert "brief ✓" in md and "周三001 A vs B · 偏移 · 6.0pp" in md
    assert "不重跑已完成作业" in md
    assert len(md) < 4000


def test_discussion_is_append_only_jsonl(tmp_path: Path):
    p1 = append_discussion(
        tmp_path, "2026-09-23", who="jun", text="场1 我想双选", obj="周三001",
        at="2026-09-23T13:00:00+08:00",
    )
    append_discussion(
        tmp_path, "2026-09-23", who="claude", text="双选要过 C6", obj="周三001",
        at="2026-09-23T13:01:00+08:00",
    )
    rows = read_discussion(tmp_path, "2026-09-23")
    assert p1.name == "discussion.jsonl" and [r["who"] for r in rows] == ["jun", "claude"]
    assert rows[0]["seq"] == 1 and rows[1]["seq"] == 2


def test_write_session(tmp_path: Path):
    path = write_session(tmp_path, "2026-09-23", "# 会话入口 · 2026-09-23\n")
    assert path.name == "session.md" and path.read_text(encoding="utf-8").startswith("# 会话入口")
