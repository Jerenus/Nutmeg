"""Pure arithmetic for the per-period belief-vs-market balance ledger."""

from __future__ import annotations

import statistics

from nutmeg.decision.scoring import brier_delta_vs_prior

BALANCE_MOVE_EPS_PP = 0.05


def balance_row(read: dict) -> dict:
    """Return one Read's shift magnitude, movement flag, and upward-moved face."""
    prior = read.get("prior")
    belief = read.get("belief")
    if not isinstance(prior, dict) or not isinstance(belief, dict):
        return {"shift_pp": 0.0, "moved": False, "moved_face": None}
    faces = set(prior) | set(belief)
    if not faces:
        return {"shift_pp": 0.0, "moved": False, "moved_face": None}
    deltas = {
        face: (float(belief.get(face, 0.0)) - float(prior.get(face, 0.0))) * 100
        for face in faces
    }
    shift_pp = max(abs(delta) for delta in deltas.values())
    moved = shift_pp > BALANCE_MOVE_EPS_PP
    moved_face = max(deltas, key=lambda face: (deltas[face], face)) if moved else None
    return {
        "shift_pp": round(shift_pp, 10),
        "moved": moved,
        "moved_face": moved_face,
    }


def _actual(read: dict, outcomes: dict, index: int) -> str | None:
    for key in (read.get("match_id"), read.get("read_id"), read.get("match_no"), str(index + 1)):
        if key is not None and key in outcomes:
            value = outcomes[key]
            if isinstance(value, (tuple, list)):
                value = value[0] if value else None
            return str(value) if value is not None else None
    return None


def balance_ledger(reads: list[dict], outcomes: dict | None = None) -> dict:
    """Aggregate movement and, when settled, Brier delta versus market."""
    rows = [balance_row(read) for read in reads]
    moved_rows = [row for row in rows if row["moved"]]
    n_matches = len(reads)
    ledger = {
        "n_matches": n_matches,
        "n_moved": len(moved_rows),
        "moved_pct": (len(moved_rows) / n_matches * 100) if n_matches else 0.0,
        "mean_abs_shift_pp": (
            statistics.fmean(row["shift_pp"] for row in moved_rows)
            if moved_rows
            else 0.0
        ),
        "max_shift_pp": max((row["shift_pp"] for row in rows), default=0.0),
        "brier_vs_market_moved": None,
        "brier_vs_market_all": None,
        "direction_right_n": None,
        "direction_wrong_n": None,
    }
    if outcomes is None:
        return ledger

    all_deltas: list[float] = []
    moved_deltas: list[float] = []
    direction_right = 0
    direction_wrong = 0
    for index, (read, row) in enumerate(zip(reads, rows, strict=True)):
        actual = _actual(read, outcomes, index)
        if actual is None or not isinstance(read.get("prior"), dict) or not isinstance(
            read.get("belief"), dict
        ):
            continue
        delta_pp = brier_delta_vs_prior(read["belief"], read["prior"], actual) * 100
        all_deltas.append(delta_pp)
        if row["moved"]:
            moved_deltas.append(delta_pp)
            if row["moved_face"] == actual:
                direction_right += 1
            else:
                direction_wrong += 1
    ledger.update(
        {
            "brier_vs_market_moved": (
                statistics.fmean(moved_deltas) if moved_deltas else None
            ),
            "brier_vs_market_all": statistics.fmean(all_deltas) if all_deltas else None,
            "direction_right_n": direction_right,
            "direction_wrong_n": direction_wrong,
        }
    )
    return ledger
