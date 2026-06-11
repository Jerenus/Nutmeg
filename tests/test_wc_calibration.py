"""worldcup.calibration — §30 元规则的世界杯分册(spec §3.5)。"""
from __future__ import annotations

from pathlib import Path

from nutmeg.services.worldcup.calibration import (
    CalibrationEntry,
    append_entries,
    brier,
    calibration_alert,
    load_entries,
)


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
