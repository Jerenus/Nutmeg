from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class ValueCandidate:
    fixture_id: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    outcome_key: str
    outcome_name: str
    model_probability: float
    market_probability: float
    edge: float
    best_odds: float
    expected_value: float
    quarter_kelly_fraction: float
    rating: str
    model_name: str
    # Which market this candidate belongs to (match_winner / total_goals /
    # correct_score / handicap_home_*). Defaults to match_winner for backward
    # compatibility with callers built before the multi-market value engine.
    market_key: str = 'match_winner'
    source_notes: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SkippedValueFixture:
    fixture_id: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    reason: str


@dataclass(slots=True, frozen=True)
class ValueBoard:
    league: str
    days: int
    generated_at: datetime
    candidates: list[ValueCandidate]
    skipped: list[SkippedValueFixture]

