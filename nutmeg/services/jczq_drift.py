"""Odds-drift snapshot infrastructure for JCZQ.

The Sporttery calculator only exposes a single "current" snapshot, so the daily
advisor has historically been blind to mid-day money movement. This module
persists every fetched payload to disk and exposes a small API to compute
drift between any two snapshots and flag steam moves that deserve attention.

The drift values are vig-normalized implied-probability deltas (current minus
baseline). Positive deltas mean the market is buying the outcome between the
two snapshots — i.e., the implied probability has risen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DRIFT_RELATIVE_PATH = Path("snapshots")
DEFAULT_STEAM_THRESHOLD = 0.05  # 5pp implied-prob shift between snapshots


@dataclass(frozen=True, slots=True)
class DriftSignal:
    match_no: str
    pool: str
    pick: str
    delta: float  # implied-prob shift (current - baseline)


class OddsDriftStore:
    """Persists Sporttery payloads and computes inter-snapshot deltas."""

    def __init__(self, output_dir: Path | str) -> None:
        self._root = Path(output_dir) / DRIFT_RELATIVE_PATH

    def persist(
        self,
        *,
        run_date: str,
        payload: dict[str, Any],
        captured_at: datetime | None = None,
    ) -> Path:
        captured = captured_at or datetime.now(ZoneInfo("Asia/Shanghai"))
        folder = self._root / run_date
        folder.mkdir(parents=True, exist_ok=True)
        filename = folder / f"{captured.strftime('%H%M%S')}.json"
        envelope = {
            "captured_at": captured.replace(microsecond=0).isoformat(),
            "official_last_update": payload.get("lastUpdateTime"),
            "payload": payload,
        }
        filename.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return filename

    def list_snapshots(self, run_date: str) -> list[Path]:
        folder = self._root / run_date
        if not folder.exists():
            return []
        return sorted(folder.glob("*.json"))

    def latest(self, run_date: str) -> dict[str, Any] | None:
        snapshots = self.list_snapshots(run_date)
        if not snapshots:
            return None
        return _load_envelope(snapshots[-1])

    def baseline(self, run_date: str) -> dict[str, Any] | None:
        snapshots = self.list_snapshots(run_date)
        if not snapshots:
            return None
        return _load_envelope(snapshots[0])

    def compute_drift(
        self,
        run_date: str,
        *,
        steam_threshold: float = DEFAULT_STEAM_THRESHOLD,
    ) -> list[DriftSignal]:
        snapshots = self.list_snapshots(run_date)
        if len(snapshots) < 2:
            return []
        baseline = _load_envelope(snapshots[0])["payload"]
        latest = _load_envelope(snapshots[-1])["payload"]
        return drift_between(baseline, latest, steam_threshold=steam_threshold)


def drift_between(
    baseline: dict[str, Any],
    latest: dict[str, Any],
    *,
    steam_threshold: float = DEFAULT_STEAM_THRESHOLD,
) -> list[DriftSignal]:
    """Compare two Sporttery payloads and return steam signals."""

    base_implied = _implied_grid(baseline)
    new_implied = _implied_grid(latest)
    signals: list[DriftSignal] = []
    for (match_no, pool, pick), prob_now in new_implied.items():
        prob_then = base_implied.get((match_no, pool, pick))
        if prob_then is None:
            continue
        delta = prob_now - prob_then
        if abs(delta) >= steam_threshold:
            signals.append(DriftSignal(match_no=match_no, pool=pool, pick=pick, delta=delta))
    signals.sort(key=lambda item: abs(item.delta), reverse=True)
    return signals


def drift_provider_from_signals(
    signals: list[DriftSignal],
) -> dict[str, dict[tuple[str, str], float]]:
    """Group signals by match_no for the analytics drift provider."""

    out: dict[str, dict[tuple[str, str], float]] = {}
    for signal in signals:
        out.setdefault(signal.match_no, {})[(signal.pool, signal.pick)] = signal.delta
    return out


def _load_envelope(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_HAD_PICKS = {"h": "胜", "d": "平", "a": "负"}
_HHAD_PICKS = {"h": "让胜", "d": "让平", "a": "让负"}
_HAFU_PICKS = {
    "hh": "胜/胜",
    "hd": "胜/平",
    "ha": "胜/负",
    "dh": "平/胜",
    "dd": "平/平",
    "da": "平/负",
    "ah": "负/胜",
    "ad": "负/平",
    "aa": "负/负",
}
_TTG_PICKS = {"s0": "0球", "s1": "1球", "s2": "2球", "s3": "3球", "s4": "4球", "s5": "5球"}
_CRS_PICKS = {
    "s01s00": "1:0",
    "s02s00": "2:0",
    "s02s01": "2:1",
    "s03s01": "3:1",
    "s00s00": "0:0",
    "s01s01": "1:1",
    "s02s02": "2:2",
    "s00s01": "0:1",
    "s00s02": "0:2",
    "s01s02": "1:2",
}


def _implied_grid(payload: dict[str, Any]) -> dict[tuple[str, str, str], float]:
    grid: dict[tuple[str, str, str], float] = {}
    for day in payload.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            match_no = str(raw.get("matchNumStr") or "")
            if not match_no:
                continue
            for pool, mapping in (
                ("had", _HAD_PICKS),
                ("hhad", _HHAD_PICKS),
                ("hafu", _HAFU_PICKS),
                ("ttg", _TTG_PICKS),
                ("crs", _CRS_PICKS),
            ):
                pool_data = raw.get(pool) or {}
                raw_implied: dict[str, float] = {}
                for key, label in mapping.items():
                    odd_str = pool_data.get(key)
                    try:
                        odd = float(odd_str) if odd_str not in (None, "") else 0.0
                    except (TypeError, ValueError):
                        odd = 0.0
                    if odd > 0:
                        raw_implied[label] = 1.0 / odd
                if not raw_implied:
                    continue
                total = sum(raw_implied.values())
                if total <= 0:
                    continue
                for label, prob in raw_implied.items():
                    grid[(match_no, pool, label)] = prob / total
    return grid
