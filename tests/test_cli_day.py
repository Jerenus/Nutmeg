import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "jczq" / "daily" / "2026-09-23").mkdir(parents=True)
    (data / "jczq" / "daily" / "2026-09-23" / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-23", "legs": {}}), encoding="utf-8")
    return data


def test_day_run_brief_then_status_and_note(tmp_path: Path):
    data = _data(tmp_path)
    result = runner.invoke(
        app, ["day", "run", "--job", "brief", "--date", "2026-09-23", "--data-dir", str(data)]
    )
    assert result.exit_code == 0, result.output
    assert "brief 0 场" in result.output
    status = runner.invoke(app, ["day", "status", "--date", "2026-09-23", "--data-dir", str(data)])
    assert status.exit_code == 0 and "brief" in status.output and "exit=0" in status.output
    note = runner.invoke(app, ["day", "note", "--date", "2026-09-23", "--data-dir", str(data),
                               "--text", "场1 想双选", "--obj", "周三001"])
    assert note.exit_code == 0
    discussion_path = data / "daily" / "2026-09-23" / "discussion.jsonl"
    rows = discussion_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["text"] == "场1 想双选"


def test_day_run_dry_run_prints_settle_commands(tmp_path: Path):
    data = _data(tmp_path)
    result = runner.invoke(app, ["day", "run", "--job", "settle", "--date", "2026-09-23",
                                 "--data-dir", str(data), "--dry-run"])
    assert result.exit_code == 0 and "workbench-export" in result.output
    assert not (data / "daily" / "2026-09-23" / "timeline.json").exists()


def test_day_run_rejects_unknown_job(tmp_path: Path):
    result = runner.invoke(
        app, ["day", "run", "--job", "deploy", "--data-dir", str(_data(tmp_path))]
    )
    assert result.exit_code == 1 and "未知作业" in result.output


def test_day_broadcast_dry_run_prints_text_without_sending(tmp_path: Path):
    data = _data(tmp_path)
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    (out / "decisions.json").write_text(json.dumps([{
        "id": "plan:26132", "kind": "plan_choose_commit", "subject": "定案", "status": "open",
        "deadline": "2099-01-01T21:00:00+08:00", "default_action": "空仓"}]), encoding="utf-8")
    r = runner.invoke(app, ["day", "run", "--job", "broadcast", "--date", "2026-09-23",
                            "--data-dir", str(data), "--dry-run", "--now",
                            "2099-01-01T20:45:00+08:00"])
    assert r.exit_code == 0 and "剩 15 分" in r.output and "空仓" in r.output
    assert not (out / "broadcasts.jsonl").exists()


def test_day_run_brief_with_logic_flag_is_accepted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nutmeg.decision.brief_writer._claude_cli", lambda p, s: (1, ""))
    data = _data(tmp_path)
    r = runner.invoke(app, ["day", "run", "--job", "brief", "--date", "2026-09-23",
                            "--data-dir", str(data), "--with-logic"])
    assert r.exit_code == 0, r.output
