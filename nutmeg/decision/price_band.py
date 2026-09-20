"""Mechanical opening-to-current price-band observations."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.market_data import devig, load_bold_odds_snapshot
from nutmeg.decision.microstructure import market_microstructure

_FACES = ("home", "draw", "away")


def _load_match_ids(day_dir: Path) -> dict[str, str | None]:
    path = day_dir / "jczq-legs-base.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    legs = doc.get("legs") if isinstance(doc, dict) else None
    if not isinstance(legs, dict):
        return {}
    return {
        str(code): (str(leg["match_id"]) if leg.get("match_id") is not None else None)
        for code, leg in legs.items()
        if isinstance(leg, dict)
    }


def write_price_band_artifacts(
    *, day: str, data_dir: Path, captured_at: str
) -> dict[str, int]:
    """Write one artifact per captured match; unavailable measurements remain null."""
    jczq_dir = Path(data_dir) / "jczq"
    day_dir = jczq_dir / "daily" / day
    snapshots = load_bold_odds_snapshot(day, jczq_dir)
    if not snapshots:
        raise ValueError(f"bold_odds 不存在或为空：{day_dir / 'bold_odds.json'}")
    match_ids = _load_match_ids(day_dir)
    written = 0
    missing_opening = 0
    for code, markets in sorted(snapshots.items()):
        market = markets.get("match_winner")
        if market is None:
            continue
        fair_now = dict(market.fair_probability or {}) or devig(dict(market.odds or {}))
        fair_open = devig(dict(market.opening_odds or {}))
        complete = all(face in fair_now and face in fair_open for face in _FACES)
        if not complete:
            missing_opening += 1
        micro = market_microstructure(market)
        payload = {
            "match_id": match_ids.get(code),
            "fair_now": fair_now or None,
            "fair_open": fair_open or None,
            "drift_pp": (
                {
                    face: round((fair_now[face] - fair_open[face]) * 100, 6)
                    for face in _FACES
                }
                if complete
                else {face: None for face in _FACES}
            ),
            "book_disagreement_pp": micro.get("dispersion_pp"),
            "books": micro.get("books"),
            "captured_at": captured_at,
        }
        (day_dir / f"price-band-{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
    return {"written": written, "missing_opening": missing_opening}
