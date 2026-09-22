from pathlib import Path


def test_today_command_reads_session_and_states_the_rules():
    text = Path(".claude/commands/today.md").read_text(encoding="utf-8")
    for needle in ("session.md", "decisions.json", "不重跑", "剩余", "plan choose", "空仓"):
        assert needle in text
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "## /today" in agents and "daily/<日>/session.md" in agents
