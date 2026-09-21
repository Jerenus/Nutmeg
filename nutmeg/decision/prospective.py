"""Shared tri-state proof that a judgment predates kickoff."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=BJ) if parsed.tzinfo is None else parsed


def prospective_fields(
    *, judged_at: object, kickoff_bj: object, judged_at_source: str | None
) -> dict:
    """Return explicit true/false/unknown provenance without inferring missing times."""
    judged = _parse_timestamp(judged_at)
    kickoff = _parse_timestamp(kickoff_bj)
    if judged is None:
        return {"provably_prospective": None, "judged_at_source": None}
    return {
        "provably_prospective": judged < kickoff if kickoff is not None else None,
        "judged_at_source": judged_at_source,
    }
