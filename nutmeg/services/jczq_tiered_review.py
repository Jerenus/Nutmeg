"""JCZQ tiered-plan v2 review — spec §6.

The next-day backtest: replays the v2 plan from snapshots, grades each tier
independently against okooo results, appends to history. Cross-version §24:
``retired_themes`` accumulator reads BOTH ``bold-review-history`` (v1) and
``tiered-plan-history`` (v2)."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_bold_combos import (
    RetiredTheme,
    retired_themes_with_stats,
)


def _merge_cross_version_by_theme(
    v1: dict[str, dict], v2: dict[str, dict]
) -> dict[str, dict[str, int]]:
    """Sum tickets/ticket_hits/legs/leg_hits across v1 + v2 by_theme."""
    merged: dict[str, dict[str, int]] = {}
    for src in (v1, v2):
        for theme, slot in (src or {}).items():
            agg = merged.setdefault(
                theme,
                {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
            )
            for k in ("tickets", "ticket_hits", "legs", "leg_hits"):
                agg[k] += int(slot.get(k, 0))
    return merged


def _load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _cumulative_by_theme(history: list[dict], key: str) -> dict[str, dict]:
    """Walk history records, sum by_theme slots from the given key."""
    agg: dict[str, dict[str, int]] = {}
    for rec in history:
        for theme, slot in (rec.get(key) or {}).items():
            a = agg.setdefault(
                theme,
                {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
            )
            for k in ("tickets", "ticket_hits", "legs", "leg_hits"):
                a[k] += int(slot.get(k, 0))
    return agg


def load_cross_version_retired_themes(output_dir) -> tuple[RetiredTheme, ...]:
    """spec §6.3 — read v1 ``bold-review-history.json`` + v2
    ``tiered-plan-history.json`` histories, sum by_theme, return the
    retired-themes set passed to the new engine. Missing files / parse
    errors / no themes past the 30-leg gate → empty tuple."""
    output = Path(output_dir)
    v1_hist = _load_history(output / "bold-review-history.json")
    v2_hist = _load_history(output / "tiered-plan-history.json")
    v1_by_theme = _cumulative_by_theme(v1_hist, "by_theme")
    v2_by_theme = _cumulative_by_theme(v2_hist, "by_theme")
    merged = _merge_cross_version_by_theme(v1_by_theme, v2_by_theme)
    return retired_themes_with_stats(merged)


def load_cross_version_history_dict(output_dir) -> dict:
    """Convenience for the CLI: returns the dict shape expected by
    ``select_tiered_plan(history=…)``."""
    output = Path(output_dir)
    v1_hist = _load_history(output / "bold-review-history.json")
    v2_hist = _load_history(output / "tiered-plan-history.json")
    merged = _merge_cross_version_by_theme(
        _cumulative_by_theme(v1_hist, "by_theme"),
        _cumulative_by_theme(v2_hist, "by_theme"),
    )
    return {"by_theme": merged}
