"""Conflict-signal store — the self-validation layer for the value/conflict engine.

The value engine (Phase 3a/3b) produces betting candidates from a
model-vs-odds edge. That edge is *unvalidated* until it has a live track
record. This store persists every conflict signal, grades it against the
next-day result, and exposes a rolling ROI so the stake ladder can keep
real money small until the engine proves itself.

Persistence is a flat JSON list of stable-schema rows at
``.nutmeg-data/jczq/memory/conflict-signals.json``. A missing or corrupt
file is treated as an empty store — the daily flow must never crash on it.
"""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.data.european_odds import CrossCheckSignal

__all__ = ["ConflictStore"]


class ConflictStore:
    """Append-only conflict-signal persistence with next-day grading.

    Each stored row is a simple, stable schema::

        {date, match_no, pool, pick, edge, sporttery_odds,
         hit: bool | None, realized_return: float | None}

    ``edge`` is the model-vs-market delta carried by ``CrossCheckSignal``.
    ``hit`` / ``realized_return`` are ``None`` until graded.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        """Return all stored rows; missing/corrupt JSON → empty list."""

        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return data

    def _save(self, rows: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(
        self,
        date: str,
        signals: list[CrossCheckSignal],
        *,
        sporttery_odds: dict[str, float],
    ) -> None:
        """Append conflict signals for ``date`` as ungraded rows.

        ``sporttery_odds`` maps ``match_no`` → the Sporttery decimal odds
        for that signal's pick; it becomes the row's payout multiplier
        once graded as a hit.
        """

        rows = self.load()
        for signal in signals:
            rows.append(
                {
                    "date": date,
                    "match_no": signal.match_no,
                    "pool": signal.pool,
                    "pick": signal.pick,
                    "edge": signal.delta,
                    "sporttery_odds": sporttery_odds.get(signal.match_no),
                    "hit": None,
                    "realized_return": None,
                }
            )
        self._save(rows)

    def grade(self, date: str, *, results: dict[str, str]) -> None:
        """Grade ``date``'s ungraded rows against ``results``.

        ``results`` maps ``match_no`` → the winning pick for that pool.
        A graded row gets ``hit`` set and ``realized_return`` set to the
        Sporttery odds when hit, else ``0.0``. Already-graded rows and
        rows with no available result are left untouched.
        """

        rows = self.load()
        changed = False
        for row in rows:
            if row.get("date") != date or row.get("hit") is not None:
                continue
            actual = results.get(row.get("match_no"))
            if actual is None:
                continue
            hit = actual == row.get("pick")
            row["hit"] = hit
            odds = row.get("sporttery_odds") or 0.0
            row["realized_return"] = float(odds) if hit else 0.0
            changed = True
        if changed:
            self._save(rows)
