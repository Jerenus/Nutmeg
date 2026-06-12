"""worldcup.calibration — §30 元规则的世界杯分册(spec §3.5)。"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.services.worldcup import _live_update_and_simulate
from nutmeg.services.worldcup.calibration import (
    CalibrationEntry,
    append_entries,
    brier,
    calibration_alert,
    load_entries,
)
from nutmeg.services.worldcup.sim import SimOutput, save_sim
from nutmeg.services.worldcup.tournament import Tournament
from tests.test_wc_injuries import _capture_sim, _seed_ratings
from tests.test_wc_tournament import _mini_tournament_dict


def _entry(brier_model: float, brier_market: float, lam_resid: float) -> CalibrationEntry:
    return CalibrationEntry(
        date="2026-06-12", match_id="M01",
        model_p={"home": 0.5, "draw": 0.3, "away": 0.2},
        market_p={"home": 0.55, "draw": 0.25, "away": 0.2},
        outcome="home", brier_model=brier_model, brier_market=brier_market,
        lambda_pred_total=2.6, goals_actual=3,
    )


def test_brier_three_way() -> None:
    assert abs(brier({"home": 1.0, "draw": 0.0, "away": 0.0}, "home")) < 1e-9
    assert abs(brier({"home": 0.0, "draw": 0.0, "away": 1.0}, "home") - 2.0) < 1e-9


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "calibration-log.jsonl"
    append_entries(p, [_entry(0.5, 0.4, 0.4)])
    append_entries(p, [_entry(0.6, 0.4, 0.4)])
    assert len(load_entries(p)) == 2


def test_no_alert_below_min_n() -> None:
    entries = [_entry(0.9, 0.3, 1.0)] * 14  # 严重跑偏但 n<15
    assert calibration_alert(entries) is None


def test_alert_on_brier_gap() -> None:
    entries = [_entry(0.5, 0.4, 0.0)] * 15  # brier 落后市场 0.1 > 0.05
    alert = calibration_alert(entries)
    assert alert is not None and "Brier" in alert


# ---------- 市场 Brier 入账:赛果日 sim 落盘的 anchor_probs 次日回读(spec §3.5) ----------


ANCHOR_M01 = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _ft_fixture(home: str, away: str, gh: int, ga: int) -> Fixture:
    return Fixture(
        fixture_id="8001", league_code="World Cup", provider_league_id=1, season=2026,
        kickoff_at=datetime(2026, 6, 11, 18, tzinfo=UTC),
        home_team_id=1, away_team_id=2, home_team=home, away_team=away,
        source="api-football", status=FixtureStatus.FINISHED, status_short="FT",
        status_long="Match Finished", home_goals=gh, away_goals=ga,
    )


def _run_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Tournament]:
    """M01(Mexico vs Poland,date_utc=2026-06-11)FT 2:1 → 次日 live 入账。"""
    t = Tournament.from_dict(_mini_tournament_dict())
    wc_dir = tmp_path / "wc2026"
    _seed_ratings(wc_dir, t)
    _capture_sim(monkeypatch)
    fx = _ft_fixture("Mexico", "Poland", 2, 1)
    _live_update_and_simulate(
        run_date="2026-06-12", matches=[], tournament=t, wc_dir=wc_dir,
        fixtures_fetcher=lambda d: [fx] if d == date(2026, 6, 11) else [],
        injuries_fetcher=lambda d: {},
    )
    return wc_dir, t


def test_live_update_reads_market_anchor_from_result_day_sim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wc_dir = tmp_path / "wc2026"
    save_sim(wc_dir / "sim-2026-06-11.json", SimOutput(
        run_date="2026-06-11", seed=1, n_sims=1, probs={},
        anchored=["M01"], anchor_probs={"M01": dict(ANCHOR_M01)},
    ))
    _run_live(tmp_path, monkeypatch)
    entries = load_entries(wc_dir / "calibration-log.jsonl")
    assert len(entries) == 1
    e = entries[0]
    assert e.match_id == "M01" and e.outcome == "home"
    assert e.market_p == ANCHOR_M01
    # 手算:(0.5-1)² + 0.3² + 0.2² = 0.25 + 0.09 + 0.04 = 0.38
    assert e.brier_market == pytest.approx(0.38)
    assert e.brier_model == pytest.approx(brier(e.model_p, "home"))


def test_live_update_market_none_without_result_day_sim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wc_dir, _ = _run_live(tmp_path, monkeypatch)  # 不预置 sim-2026-06-11.json
    entries = load_entries(wc_dir / "calibration-log.jsonl")
    assert len(entries) == 1
    assert entries[0].market_p is None
    assert entries[0].brier_market is None


def test_live_update_market_none_when_match_not_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wc_dir = tmp_path / "wc2026"
    save_sim(wc_dir / "sim-2026-06-11.json", SimOutput(
        run_date="2026-06-11", seed=1, n_sims=1, probs={},
        anchored=[], anchor_probs={},  # 当日 sim 在,但该场没锚定
    ))
    _run_live(tmp_path, monkeypatch)
    entries = load_entries(wc_dir / "calibration-log.jsonl")
    assert len(entries) == 1
    assert entries[0].market_p is None
    assert entries[0].brier_market is None


def test_alert_on_lambda_residual() -> None:
    entries = [
        CalibrationEntry(
            date="2026-06-12", match_id=f"M{i:02d}",
            model_p={"home": 0.4, "draw": 0.3, "away": 0.3}, market_p=None,
            outcome="home", brier_model=0.4, brier_market=None,
            lambda_pred_total=2.0, goals_actual=3,   # 残差 +1.0
        )
        for i in range(15)
    ]
    alert = calibration_alert(entries)
    assert alert is not None and "λ" in alert
