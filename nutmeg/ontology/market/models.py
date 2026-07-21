"""Market Action request value objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import ActorRole


@dataclass(frozen=True, slots=True)
class QuoteInput:
    market_definition_id: str
    selection_id: str
    decimal_odds: float
    bookmaker: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotBuildRequest:
    match_id: str
    market_definition_id: str
    snapshot_kind: str
    as_of: str
    provider: str
    quotes: list[QuoteInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    artifact_retrieval_id: str | None = None

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.match_id.strip() or not self.market_definition_id.strip():
            raise ValueError('match_id and market_definition_id are required')
        if not self.quotes:
            raise ValueError('at least one quote is required')
        if any(quote.decimal_odds <= 1.0 for quote in self.quotes):
            raise ValueError('decimal_odds must be greater than 1.0')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')
