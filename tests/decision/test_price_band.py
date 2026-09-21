import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.decision.price_band import write_price_band_artifacts
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import rsi as rsi_cli


def _snapshot(day_dir: Path) -> None:
    day_dir.mkdir(parents=True)
    day_dir.joinpath("bold_odds.json").write_text(
        json.dumps(
            {
                "周日001": {
                    "match_winner": {
                        "odds": {"home": 1.8, "draw": 3.6, "away": 4.5},
                        "fair_probability": {"home": 0.5, "draw": 0.3, "away": 0.2},
                        "independent": True,
                        "bookmaker_count": 2,
                        "opening_odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                        "per_book_odds": {
                            "home": [1.7, 1.9],
                            "draw": [3.5, 3.7],
                            "away": [4.4, 4.6],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周日001": {
                        "match_id": "M-1",
                        "kickoff_bj": "2026-09-20T20:00:00+08:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_writes_price_band_from_opening_and_current_market_data(tmp_path: Path):
    day_dir = tmp_path / "jczq" / "daily" / "2026-09-20"
    _snapshot(day_dir)

    report = write_price_band_artifacts(
        day="2026-09-20",
        data_dir=tmp_path,
        captured_at="2026-09-20T12:00:00+08:00",
    )

    assert report == {"written": 1, "missing_opening": 0}
    artifact = json.loads(
        day_dir.joinpath("price-band-周日001.json").read_text(encoding="utf-8")
    )
    assert artifact["match_id"] == "M-1"
    assert artifact["fair_now"] == {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert sum(artifact["fair_open"].values()) == pytest.approx(1.0)
    assert artifact["drift_pp"]["home"] == pytest.approx(1.724138, abs=1e-6)
    assert artifact["book_disagreement_pp"] is not None
    assert artifact["books"] == 2
    assert artifact["captured_at"] == "2026-09-20T12:00:00+08:00"


def test_cli_price_band_reports_written_artifacts(tmp_path: Path):
    day_dir = tmp_path / "jczq" / "daily" / "2026-09-20"
    _snapshot(day_dir)

    result = CliRunner().invoke(
        app,
        ["rsi", "price-band", "--day", "2026-09-20", "--data-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "price-band 2026-09-20: written=1 missing_opening=0" in result.output


def test_cli_price_band_fulfills_scheduled_match_duty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    day = "2026-09-20"
    day_dir = tmp_path / "jczq" / "daily" / day
    _snapshot(day_dir)
    monkeypatch.setattr(
        rsi_cli,
        "_now",
        lambda: datetime.fromisoformat("2026-09-20T12:00:00+08:00"),
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "rsi",
            "register",
            "--by",
            "Jun",
            "experiments/registry/F5.json",
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(tmp_path)]
    )
    assert scheduled.exit_code == 0, scheduled.output

    result = runner.invoke(
        app,
        ["rsi", "price-band", "--day", day, "--data-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM rsi_duty_instances "
            "WHERE duty_id='F5:price-band-observation' AND fulfilled_at IS NOT NULL"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*), SUM(n_rows), MIN(population_stratum) "
            "FROM rsi_observations WHERE exp_id='F5'"
        ).fetchone() == (1, 1, "pooled")
