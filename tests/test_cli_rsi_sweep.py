import json
import sqlite3
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import rsi as rsi_cli


def _prepare_duty(tmp_path: Path, *, instrument: list[str]) -> tuple[Path, str, CliRunner]:
    day = "2099-09-19"
    data_dir = tmp_path / "data"
    zucai_dir = data_dir / "zucai"
    zucai_dir.mkdir(parents=True)
    zucai_dir.joinpath("99199-issue.json").write_text(
        json.dumps(
            {
                "matches": [
                    {"match_no": 1, "kickoff_bj": "2099-09-19T20:00:00+08:00"}
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = {
        "exp_id": "S1",
        "claim": "sweep test",
        "mechanism": "test",
        "tier": "observation",
        "layer": "judgment",
        "population": "zucai",
        "min_tier": "price_only",
        "window": {"date_from": day, "n_min": 1},
        "falsifier": {
            "metric": "home_resid_pp",
            "stratum": "zucai",
            "n_min": 1,
            "bound": "ci_upper",
            "threshold_pp": 2.0,
            "direction": "lt_means_falsified",
        },
        "stop_rule": "n>=1",
        "quota_slot": False,
        "buckets": [],
        "rule_ids": [],
        "source_doc": "test",
        "registered_at": "2099-09-18",
        "duties": [
            {
                "name": "sample",
                "scope": "day",
                "deadline_rule": "earliest_kickoff",
                "instrument": instrument,
                "artifact_glob": str(tmp_path / "artifact.json"),
            }
        ],
    }
    registry = tmp_path / "S1.json"
    registry.write_text(json.dumps(doc), encoding="utf-8")
    runner = CliRunner()
    registered = runner.invoke(
        app,
        ["rsi", "register", "--by", "Jun", str(registry), "--data-dir", str(data_dir)],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "99199",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert scheduled.exit_code == 0, scheduled.output
    return data_dir, day, runner


def test_business_day_uses_previous_date_before_0700():
    assert rsi_cli._business_day(
        datetime.fromisoformat("2026-09-21T06:59:59+08:00")
    ) == "2026-09-20"
    assert rsi_cli._business_day(
        datetime.fromisoformat("2026-09-21T07:00:00+08:00")
    ) == "2026-09-21"


def test_sweep_does_not_execute_expired_duty(tmp_path: Path):
    data_dir, day, runner = _prepare_duty(
        tmp_path, instrument=["uv", "run", "false", "--day", "{day}"]
    )

    result = runner.invoke(
        app,
        [
            "rsi",
            "sweep",
            "--day",
            day,
            "--issue",
            "99199",
            "--now",
            "2099-09-19T21:00:00+08:00",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DUTY_EXPIRED: S1:sample 1" in result.stderr
    assert "ran=0" in result.output and "expired=1" in result.output


def test_sweep_rejects_non_uv_instrument(tmp_path: Path):
    data_dir, day, runner = _prepare_duty(
        tmp_path, instrument=["bash", "-lc", "true", "{day}"]
    )

    result = runner.invoke(
        app,
        [
            "rsi",
            "sweep",
            "--day",
            day,
            "--issue",
            "99199",
            "--now",
            "2099-09-19T12:00:00+08:00",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 1
    assert "UNSAFE_INSTRUMENT" in result.output
    assert "failed=1" in result.output


def test_sweep_skips_pending_instrument(tmp_path: Path):
    data_dir, day, runner = _prepare_duty(
        tmp_path, instrument=["uv", "run", "false", "--day", "{day}"]
    )
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        connection.execute(
            "UPDATE rsi_duties SET status='pending_instrument' WHERE duty_id='S1:sample'"
        )

    result = runner.invoke(
        app,
        [
            "rsi",
            "sweep",
            "--day",
            day,
            "--issue",
            "99199",
            "--now",
            "2099-09-19T12:00:00+08:00",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "ran=0" in result.output and "skipped_pending=1" in result.output


def test_sweep_defaults_to_business_day(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        rsi_cli,
        "_now",
        lambda: datetime.fromisoformat("2026-09-21T06:30:00+08:00"),
    )

    result = CliRunner().invoke(
        app, ["rsi", "sweep", "--data-dir", str(tmp_path / "data")]
    )

    assert result.exit_code == 0, result.output
    assert result.output.startswith("2026-09-20 sweep:")


def test_sweep_runs_once_then_skips_fulfilled_duty(tmp_path: Path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "data"
    command = [
        "uv",
        "run",
        "nutmeg",
        "rsi",
        "fulfill",
        "--exp",
        "S1",
        "--duty",
        "sample",
        "--day",
        "{day}",
        "--issue",
        "{issue}",
        "--artifact",
        str(artifact),
        "--n-rows",
        "1",
        "--data-dir",
        str(data_dir),
    ]
    data_dir, day, runner = _prepare_duty(tmp_path, instrument=command)
    args = [
        "rsi",
        "sweep",
        "--day",
        day,
        "--issue",
        "99199",
        "--now",
        "2099-09-19T12:00:00+08:00",
        "--data-dir",
        str(data_dir),
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert "ran=1" in first.output
    assert second.exit_code == 0, second.output
    assert "ran=0" in second.output and "skipped_fulfilled=1" in second.output
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM rsi_observations WHERE exp_id='S1'"
        ).fetchone() == (1,)


def test_sweep_reports_successful_command_that_did_not_fulfill_as_failed(
    tmp_path: Path,
):
    data_dir, day, runner = _prepare_duty(
        tmp_path, instrument=["uv", "run", "true", "--day", "{day}"]
    )

    result = runner.invoke(
        app,
        [
            "rsi",
            "sweep",
            "--day",
            day,
            "--issue",
            "99199",
            "--now",
            "2099-09-19T12:00:00+08:00",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 1
    assert "DUTY_NOT_FULFILLED: S1:sample 1" in result.output
    assert "ran=0" in result.output and "failed=1" in result.output
