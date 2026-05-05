"""Tests for the odds-drift snapshot infrastructure."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nutmeg.services.jczq_drift import (
    OddsDriftStore,
    drift_between,
    drift_provider_from_signals,
)


def _payload(home_odd: float, draw_odd: float, away_odd: float) -> dict:
    return {
        "lastUpdateTime": "2026-05-04 14:00:00",
        "matchInfoList": [
            {
                "businessDate": "2026-05-04",
                "subMatchList": [
                    {
                        "matchNumStr": "周一001",
                        "had": {"h": str(home_odd), "d": str(draw_odd), "a": str(away_odd)},
                    }
                ],
            }
        ],
    }


def test_drift_between_flags_steam_moves_above_threshold() -> None:
    base = _payload(2.20, 3.30, 3.10)
    later = _payload(1.80, 3.40, 4.00)

    signals = drift_between(base, later, steam_threshold=0.05)
    by_pick = {(s.pool, s.pick): s.delta for s in signals}

    assert by_pick[("had", "胜")] > 0.04
    assert by_pick[("had", "负")] < -0.04


def test_odds_drift_store_persists_and_computes_drift(tmp_path: Path) -> None:
    store = OddsDriftStore(tmp_path)
    store.persist(
        run_date="2026-05-04",
        payload=_payload(2.20, 3.30, 3.10),
        captured_at=datetime(2026, 5, 4, 9, 0, 0),
    )
    store.persist(
        run_date="2026-05-04",
        payload=_payload(1.80, 3.40, 4.00),
        captured_at=datetime(2026, 5, 4, 14, 0, 0),
    )

    snapshots = store.list_snapshots("2026-05-04")
    assert len(snapshots) == 2

    signals = store.compute_drift("2026-05-04", steam_threshold=0.05)
    assert any(
        signal.pool == "had" and signal.pick == "胜" and signal.delta > 0
        for signal in signals
    )


def test_drift_provider_from_signals_groups_by_match() -> None:
    base = _payload(2.20, 3.30, 3.10)
    later = _payload(1.80, 3.40, 4.00)
    signals = drift_between(base, later, steam_threshold=0.05)
    grouped = drift_provider_from_signals(signals)

    assert "周一001" in grouped
    assert ("had", "胜") in grouped["周一001"]


def test_compute_drift_returns_empty_when_only_one_snapshot(tmp_path: Path) -> None:
    store = OddsDriftStore(tmp_path)
    store.persist(run_date="2026-05-04", payload=_payload(2.20, 3.30, 3.10))
    assert store.compute_drift("2026-05-04") == []


def test_drift_between_skips_unknown_picks_gracefully() -> None:
    base = {"matchInfoList": [{"subMatchList": [{"matchNumStr": "周一001", "had": {}}]}]}
    later = _payload(1.80, 3.40, 4.00)
    assert drift_between(base, later) == []


@pytest.mark.parametrize("threshold,min_delta", [(0.10, 0.10), (0.20, 0.20)])
def test_drift_between_respects_threshold(threshold: float, min_delta: float) -> None:
    base = _payload(2.20, 3.30, 3.10)
    later = _payload(1.20, 3.40, 8.00)
    signals = drift_between(base, later, steam_threshold=threshold)
    for signal in signals:
        assert abs(signal.delta) >= min_delta
