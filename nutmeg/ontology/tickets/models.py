"""Immutable values used by the protected ticket workbench."""
from __future__ import annotations

import math
from dataclasses import dataclass

from nutmeg.decision.legs_audit import Leg

_FACE_FOR_OUTCOME = {"home": "3", "draw": "1", "away": "0"}
_ANCHOR_STATES = {"pass", "fail", "symmetric_damage", "unknown"}


@dataclass(frozen=True, slots=True)
class TicketLegDraft:
    """One priced selection plus the operator-authored facts used by C0-C7."""

    leg_key: str
    match_id: str
    match_no: int
    name: str
    market_definition_id: str
    selection_id: str
    outcome_key: str
    faces: str
    forecast_revision_id: str
    entry_quote_id: str | None
    odds: float
    line: str | None
    bucket: str
    fair: dict[str, float]
    confidence: int
    directional_flags: tuple[tuple[str, str], ...] = ()
    nondirectional_flags: tuple[str, ...] = ()
    anchor_integrity: str = "unknown"
    precedents: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "leg_key",
            "match_id",
            "name",
            "market_definition_id",
            "selection_id",
            "outcome_key",
            "forecast_revision_id",
            "bucket",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        if self.match_no <= 0:
            raise ValueError("match_no must be positive")
        if not self.faces or len(set(self.faces)) != len(self.faces):
            raise ValueError("faces must contain unique 3/1/0 values")
        if not set(self.faces) <= {"3", "1", "0"}:
            raise ValueError("faces must contain only 3/1/0 values")
        expected_face = _FACE_FOR_OUTCOME.get(self.outcome_key)
        if expected_face is None or expected_face not in self.faces:
            raise ValueError("outcome_key must be covered by faces")
        if not math.isfinite(float(self.odds)) or float(self.odds) <= 1.0:
            raise ValueError("odds must be decimal odds > 1.0")
        if set(self.fair) != set(_FACE_FOR_OUTCOME):
            raise ValueError("fair must contain home, draw, and away")
        if any(
            not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0
            for value in self.fair.values()
        ):
            raise ValueError("fair probabilities must be between zero and one")
        if not math.isclose(sum(self.fair.values()), 1.0, abs_tol=1e-6):
            raise ValueError("fair probabilities must sum to one")
        if not 0 <= self.confidence <= 5:
            raise ValueError("confidence must be between zero and five")
        if self.anchor_integrity not in _ANCHOR_STATES:
            raise ValueError("anchor_integrity is invalid")

    def express_dict(self) -> dict[str, object]:
        return {
            "leg_key": self.leg_key,
            "match_id": self.match_id,
            "market": self.market_definition_id,
            "selection": self.outcome_key,
            "selection_id": self.selection_id,
            "forecast_revision_id": self.forecast_revision_id,
            "entry_quote_id": self.entry_quote_id,
            "odds": float(self.odds),
            "line": self.line,
            "bucket": self.bucket,
            "prob": float(self.fair[self.outcome_key]),
        }

    def audit_leg(self) -> Leg:
        return Leg(
            match_no=self.match_no,
            name=self.name,
            faces=self.faces,
            fair=dict(self.fair),
            confidence=self.confidence,
            directional_flags=self.directional_flags,
            nondirectional_flags=self.nondirectional_flags,
            anchor_integrity=self.anchor_integrity,
            precedents=self.precedents,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "leg_key": self.leg_key,
            "match_id": self.match_id,
            "match_no": self.match_no,
            "name": self.name,
            "market_definition_id": self.market_definition_id,
            "selection_id": self.selection_id,
            "outcome_key": self.outcome_key,
            "faces": self.faces,
            "forecast_revision_id": self.forecast_revision_id,
            "entry_quote_id": self.entry_quote_id,
            "odds": float(self.odds),
            "line": self.line,
            "bucket": self.bucket,
            "fair": dict(self.fair),
            "confidence": self.confidence,
            "directional_flags": [list(item) for item in self.directional_flags],
            "nondirectional_flags": list(self.nondirectional_flags),
            "anchor_integrity": self.anchor_integrity,
            "precedents": [list(item) for item in self.precedents],
        }


@dataclass(frozen=True, slots=True)
class AuditFindingRecord:
    level: str
    code: str
    match_no: int | None
    message: str
    since: str

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "code": self.code,
            "match_no": self.match_no,
            "message": self.message,
            "since": self.since,
        }


@dataclass(frozen=True, slots=True)
class ComposedTicket:
    ticket_id: str
    bucket: str
    budget_bucket: str
    structure: str
    stake_yuan: int
    combined_odds: float
    n_legs: int
    computed_hit_prob: float | None
    legs: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ticket_id": self.ticket_id,
            "bucket": self.bucket,
            "budget_bucket": self.budget_bucket,
            "structure": self.structure,
            "stake_yuan": self.stake_yuan,
            "combined_odds": self.combined_odds,
            "n_legs": self.n_legs,
            "computed_hit_prob": self.computed_hit_prob,
            "legs": [dict(leg) for leg in self.legs],
        }


@dataclass(frozen=True, slots=True)
class BatchComposition:
    channel: str
    period_cap_yuan: int | None
    total_stake_yuan: int
    scaled: bool
    tickets: tuple[ComposedTicket, ...]
    by_bucket: dict[str, dict[str, int]]
    findings: tuple[AuditFindingRecord, ...]

    @property
    def is_empty(self) -> bool:
        return not self.tickets

    @property
    def has_blocking(self) -> bool:
        return any(finding.level == "ERROR" for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "period_cap_yuan": self.period_cap_yuan,
            "total_stake_yuan": self.total_stake_yuan,
            "scaled": self.scaled,
            "n_tickets": len(self.tickets),
            "tickets": [ticket.to_dict() for ticket in self.tickets],
            "by_bucket": {
                bucket: dict(values) for bucket, values in self.by_bucket.items()
            },
            "findings": [finding.to_dict() for finding in self.findings],
        }
