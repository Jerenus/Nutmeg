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


def _zucai_issue(data_dir: Path, *, with_intl: bool = True) -> None:
    zucai_dir = data_dir / "zucai"
    zucai_dir.mkdir(parents=True, exist_ok=True)
    zucai_dir.joinpath("99001-issue.json").write_text(
        json.dumps(
            {
                "issue_id": "99001",
                "sale_deadline": "2026-09-20 19:00",
                "matches": [
                    {"match_no": 1, "kickoff_bj": "2026-09-20 21:00"},
                    {"match_no": 2, "kickoff_bj": "2026-09-20 22:00"},
                ],
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("99001-store-ids.json").write_text(
        json.dumps(
            {
                "1": {"match_no": 1, "match_id": "Z-1"},
                "2": {"match_no": 2, "match_id": "Z-2"},
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("99001-odds.json").write_text(
        json.dumps(
            {
                "issue_id": "99001",
                "captured_at": "2026-09-20T11:00:00",
                "matches": [
                    {"match_no": 1, "home": 2.0, "draw": 3.4, "away": 4.2},
                    {"match_no": 2, "home": 1.9, "draw": 3.5, "away": 4.4},
                ],
            }
        ),
        encoding="utf-8",
    )
    if with_intl:
        zucai_dir.joinpath("99001-odds-intl.json").write_text(
            json.dumps(
                {
                    "issue_id": "99001",
                    "source": "titan007",
                    "captured_at": "2026-09-20T11:00:01",
                    "matches": [
                        {
                            "match_no": 1,
                            "odds": {"home": 1.8, "draw": 3.6, "away": 4.5},
                            "opening_odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                            "books": 9,
                            "micro": {"dispersion_pp": 1.5, "books": 9},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )


def test_zucai_price_band_uses_intl_opening_and_falls_back_to_the_sale_page(tmp_path: Path):
    from nutmeg.decision.market_data import devig
    from nutmeg.decision.price_band import write_zucai_price_band_artifacts

    _zucai_issue(tmp_path)

    report = write_zucai_price_band_artifacts(
        issue="99001",
        day="2026-09-20",
        data_dir=tmp_path,
        captured_at="2026-09-20T12:00:00+08:00",
    )

    assert report == {"written": 2, "missing_opening": 1}
    day_dir = tmp_path / "jczq" / "daily" / "2026-09-20"
    first = json.loads(day_dir.joinpath("price-band-z99001-01.json").read_text("utf-8"))
    assert first["match_id"] == "Z-1" and first["issue"] == "99001"
    assert first["source"] == "titan007"
    now = devig({"home": 1.8, "draw": 3.6, "away": 4.5})
    opening = devig({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert first["drift_pp"]["home"] == pytest.approx(
        (now["home"] - opening["home"]) * 100, abs=1e-6
    )
    assert (first["book_disagreement_pp"], first["books"]) == (1.5, 9)
    second = json.loads(day_dir.joinpath("price-band-z99001-02.json").read_text("utf-8"))
    assert second["match_id"] == "Z-2" and second["source"] == "sale_page"
    assert sum(second["fair_now"].values()) == pytest.approx(1.0)
    assert second["fair_open"] is None
    assert second["drift_pp"] == {"home": None, "draw": None, "away": None}
    assert second["books"] is None


def test_cli_price_band_fulfills_zucai_match_duties_of_the_scheduled_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # 2026-09-24：F5 按 both 排了 26132 的 14 场，price-band 只写竞彩 → 每小时 failed=14。
    day = "2026-09-20"
    _snapshot(tmp_path / "jczq" / "daily" / day)
    _zucai_issue(tmp_path)
    monkeypatch.setattr(
        rsi_cli,
        "_now",
        lambda: datetime.fromisoformat("2026-09-20T12:00:00+08:00"),
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        ["rsi", "register", "--by", "Jun", "experiments/registry/F5.json",
         "--data-dir", str(tmp_path)],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app,
        ["rsi", "schedule", "--day", day, "--issue", "99001", "--data-dir", str(tmp_path)],
    )
    assert scheduled.exit_code == 0, scheduled.output

    result = runner.invoke(
        app, ["rsi", "price-band", "--day", day, "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert "price-band 99001: written=2 missing_opening=1" in result.output
    with sqlite3.connect(tmp_path / "ontology" / "ontology.db") as connection:
        rows = connection.execute(
            "SELECT match_id FROM rsi_duty_instances "
            "WHERE duty_id='F5:price-band-observation' AND fulfilled_at IS NOT NULL "
            "ORDER BY match_id"
        ).fetchall()
    assert rows == [("M-1",), ("Z-1",), ("Z-2",)]


def test_cli_price_band_runs_zucai_when_the_day_has_no_jczq_snapshot(tmp_path: Path):
    _zucai_issue(tmp_path, with_intl=False)

    result = CliRunner().invoke(
        app,
        ["rsi", "price-band", "--day", "2026-09-20", "--issue", "99001",
         "--data-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "price-band 99001: written=2 missing_opening=2" in result.output
