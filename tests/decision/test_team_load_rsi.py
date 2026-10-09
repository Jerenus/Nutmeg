"""F16（2026-10-09 登记）：`rsi team-load` 写台账并为已排的逐场义务履约。

与 F5 price-band 同一模式。"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import rsi as rsi_cli

DAY = "2026-10-10"


def _board(data: Path) -> None:
    day_dir = data / "jczq" / "daily" / DAY
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周六001": {"match_id": "M-1", "home_team": "甲", "away_team": "乙",
                    "kickoff_bj": f"{DAY}T20:00:00+08:00"},
        "周六002": {"match_id": "M-2", "home_team": "丙", "away_team": "丁",
                    "kickoff_bj": f"{DAY}T11:00:00+08:00"},      # 已开球：不履约
    }}, ensure_ascii=False), encoding="utf-8")


def _fulfilled(data: Path) -> int:
    with sqlite3.connect(data / "ontology" / "ontology.db") as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM rsi_duty_instances "
            "WHERE duty_id='F16:team-load-ledger' AND fulfilled_at IS NOT NULL").fetchone()[0]


def test_team_load_fulfils_unstarted_scheduled_matches(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    _board(tmp_path)
    monkeypatch.setattr(rsi_cli, "_now",
                        lambda: datetime.fromisoformat(f"{DAY}T12:30:00+08:00"))
    runner = CliRunner()
    reg = runner.invoke(app, ["rsi", "register", "--by", "Jun", "experiments/registry/F16.json",
                              "--data-dir", str(tmp_path)])
    assert reg.exit_code == 0, reg.output
    sch = runner.invoke(app, ["rsi", "schedule", "--day", DAY, "--data-dir", str(tmp_path)])
    assert sch.exit_code == 0, sch.output

    out = runner.invoke(app, ["rsi", "team-load", "--day", DAY, "--data-dir", str(tmp_path)])

    assert out.exit_code == 0, out.output
    assert "履约 1 场" in out.output
    assert _fulfilled(tmp_path) == 1
    assert (tmp_path / "jczq" / "daily" / DAY / "team-load.json").exists()


def test_team_load_only_writes_when_f16_is_not_registered(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    _board(tmp_path)
    monkeypatch.setattr(rsi_cli, "_now",
                        lambda: datetime.fromisoformat(f"{DAY}T12:30:00+08:00"))
    out = CliRunner().invoke(app, ["rsi", "team-load", "--day", DAY,
                                   "--data-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "履约 0 场" in out.output
