"""Market Action request value objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from nutmeg.ontology.actions.models import ActorRole


@dataclass(frozen=True, slots=True)
class QuoteInput:
    market_definition_id: str
    selection_id: str
    decimal_odds: float
    bookmaker: str | None = None
    settlement_parameter_decimal: str | None = None


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
        if any(
            quote.market_definition_id != self.market_definition_id
            for quote in self.quotes
        ):
            raise ValueError('every Quote must belong to the Snapshot market')
        lines = {quote.settlement_parameter_decimal for quote in self.quotes}
        if self.market_definition_id == 'md-hhad':
            if None in lines or len(lines) != 1:
                raise ValueError('HHAD Snapshot requires one exact signed line')
        elif lines != {None}:
            raise ValueError('unlined Snapshot cannot contain a settlement parameter')
        for line in lines - {None}:
            try:
                parsed = Decimal(line)
            except (InvalidOperation, TypeError) as error:
                raise ValueError('settlement parameter must be a canonical decimal') from error
            if not parsed.is_finite() or format(parsed, '.12f') != line:
                raise ValueError('settlement parameter must have twelve decimal places')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')
