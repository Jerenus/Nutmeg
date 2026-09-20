import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.decision.price_band import write_price_band_artifacts
from nutmeg.interfaces.cli import app


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
