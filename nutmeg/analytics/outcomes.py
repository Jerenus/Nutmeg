"""Map a final score to a one-hot outcome distribution for scoring.

Package 4A ships the had 3-way mapping (home/draw/away from the 90' result). Other
markets (ttg RPS buckets, etc.) return ``None`` — a documented 4B follow-on — so a
non-had revision is scored only where a mapping exists, never on a fabricated outcome.
"""
from __future__ import annotations


def _score_parts(score_90: str) -> tuple[int, int]:
    home, away = score_90.split('-')
    return int(home), int(away)


def outcome_one_hot(
    market_kind: str, belief_keys: list[str], score_90: str
) -> dict[str, float] | None:
    if market_kind != 'had':
        return None
    home, away = _score_parts(score_90)
    result = 'home' if home > away else 'away' if home < away else 'draw'
    return {key: (1.0 if key == result else 0.0) for key in belief_keys}
