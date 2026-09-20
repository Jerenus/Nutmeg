"""Resolve the match population for RSI match-scoped duties."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def _jczq_matches(*, day: str, data_dir: Path) -> list[dict]:
    path = data_dir / "jczq" / "daily" / day / "jczq-legs-base.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    legs = payload.get("legs") or {}
    entries = legs.items() if isinstance(legs, Mapping) else enumerate(legs, start=1)
    return [
        {
            "match_id": str(leg["match_id"]),
            "code": str(code),
            "match_no": None,
            "source": "jczq",
        }
        for code, leg in entries
    ]


def _zucai_matches(*, issue: str, data_dir: Path) -> list[dict]:
    path = data_dir / "zucai" / f"{issue}-store-ids.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.values() if isinstance(payload, Mapping) else payload
    return [
        {
            "match_id": str(row["match_id"]),
            "code": None,
            "match_no": int(row["match_no"]),
            "source": "zucai",
        }
        for row in rows
    ]


def matches_for_population(
    population: str,
    *,
    day: str,
    issue: str | None,
    data_dir: Path,
) -> list[dict]:
    """Return the business day's matches for one frozen experiment population."""
    data_dir = Path(data_dir)
    if population == "jczq":
        return _jczq_matches(day=day, data_dir=data_dir)
    if population == "zucai":
        if issue is None:
            return []
        return _zucai_matches(issue=issue, data_dir=data_dir)
    if population != "both":
        raise ValueError(f"未知 population: {population}")

    jczq = _jczq_matches(day=day, data_dir=data_dir)
    if issue is None:
        return jczq
    zucai = _zucai_matches(issue=issue, data_dir=data_dir)
    by_match_id = {row["match_id"]: row for row in jczq}
    for row in zucai:
        existing = by_match_id.get(row["match_id"])
        if existing is None:
            by_match_id[row["match_id"]] = row
        else:
            existing["match_no"] = row["match_no"]
            existing["source"] = "both"
    return list(by_match_id.values())
