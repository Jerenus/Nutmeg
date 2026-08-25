"""Market persistence: quotes and de-vigged snapshots.

Quotes are raw prices; a snapshot is the fair distribution plus its de-vig method
version and coverage/freshness/disagreement metadata. JSON columns round-trip
through the canonical serializer. `latest_fair` reads the newest snapshot's fair
distribution for a match/market.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_market as sm


@dataclass(frozen=True, slots=True)
class QuoteRow:
    quote_id: str
    match_id: str
    market_definition_id: str
    selection_id: str
    provider: str
    bookmaker: str | None
    decimal_odds: float
    captured_at: str
    artifact_retrieval_id: str | None
    quote_status: str


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    market_snapshot_id: str
    match_id: str
    market_definition_id: str
    snapshot_kind: str
    as_of: str
    fair_distribution: dict[str, float]
    devig_method: str
    method_version: str
    source_coverage: dict[str, object]
    freshness: dict[str, object]
    disagreement: dict[str, object]


class MarketRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_quote(self, row: QuoteRow) -> None:
        self._connection.execute(
            insert(sm.market_quotes).values(
                quote_id=row.quote_id,
                match_id=row.match_id,
                market_definition_id=row.market_definition_id,
                selection_id=row.selection_id,
                provider=row.provider,
                bookmaker=row.bookmaker,
                decimal_odds=row.decimal_odds,
                captured_at=row.captured_at,
                artifact_retrieval_id=row.artifact_retrieval_id,
                quote_status=row.quote_status,
            )
        )

    def quote(self, quote_id: str) -> QuoteRow | None:
        row = (
            self._connection.execute(
                select(sm.market_quotes).where(sm.market_quotes.c.quote_id == quote_id)
            )
            .mappings()
            .first()
        )
        return None if row is None else QuoteRow(**dict(row))

    def insert_snapshot(self, row: SnapshotRow, quote_ids: tuple[str, ...] = ()) -> None:
        self._connection.execute(
            insert(sm.market_snapshots).values(
                market_snapshot_id=row.market_snapshot_id,
                match_id=row.match_id,
                market_definition_id=row.market_definition_id,
                snapshot_kind=row.snapshot_kind,
                as_of=row.as_of,
                fair_distribution_json=canonical_json(row.fair_distribution),
                devig_method=row.devig_method,
                method_version=row.method_version,
                source_coverage_json=canonical_json(row.source_coverage),
                freshness_json=canonical_json(row.freshness),
                disagreement_json=canonical_json(row.disagreement),
            )
        )
        if quote_ids:
            self._connection.execute(
                insert(sm.market_snapshot_quotes),
                [
                    {'market_snapshot_id': row.market_snapshot_id, 'quote_id': quote_id}
                    for quote_id in quote_ids
                ],
            )

    def count_quotes(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sm.market_quotes)
        ).scalar_one()

    def count_snapshots(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sm.market_snapshots)
        ).scalar_one()

    def selection_outcome_key(self, selection_id: str) -> str | None:
        return self._connection.execute(
            select(sm.selection_definitions.c.outcome_key).where(
                sm.selection_definitions.c.selection_id == selection_id
            )
        ).scalar_one_or_none()

    def selection_id_for(
        self, market_definition_id: str, outcome_key: str, line: str | None = None
    ) -> str | None:
        conditions = [
            sm.selection_definitions.c.market_definition_id == market_definition_id,
            sm.selection_definitions.c.outcome_key == outcome_key,
        ]
        if line is not None:
            conditions.append(sm.selection_definitions.c.line == line)
        return self._connection.execute(
            select(sm.selection_definitions.c.selection_id).where(*conditions).limit(1)
        ).scalar_one_or_none()

    def snapshot_quote_ids(self, market_snapshot_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sm.market_snapshot_quotes.c.quote_id).where(
                sm.market_snapshot_quotes.c.market_snapshot_id == market_snapshot_id
            )
        ).scalars().all()
        return tuple(rows)

    def snapshot_exists_for(
        self,
        market_snapshot_id: str,
        match_id: str,
        market_definition_id: str,
    ) -> bool:
        snapshot = self._connection.execute(
            select(sm.market_snapshots.c.market_snapshot_id).where(
                sm.market_snapshots.c.market_snapshot_id == market_snapshot_id,
                sm.market_snapshots.c.match_id == match_id,
                sm.market_snapshots.c.market_definition_id == market_definition_id,
            )
        ).scalar_one_or_none()
        return snapshot is not None

    def snapshot_id_for_source(
        self,
        match_id: str,
        market_definition_id: str,
        snapshot_kind: str,
        provider: str,
    ) -> str | None:
        return self._connection.execute(
            select(sm.market_snapshots.c.market_snapshot_id)
            .select_from(
                sm.market_snapshots.join(
                    sm.market_snapshot_quotes,
                    sm.market_snapshot_quotes.c.market_snapshot_id
                    == sm.market_snapshots.c.market_snapshot_id,
                ).join(
                    sm.market_quotes,
                    sm.market_quotes.c.quote_id == sm.market_snapshot_quotes.c.quote_id,
                )
            )
            .where(
                sm.market_snapshots.c.match_id == match_id,
                sm.market_snapshots.c.market_definition_id == market_definition_id,
                sm.market_snapshots.c.snapshot_kind == snapshot_kind,
                sm.market_quotes.c.provider == provider,
            )
            .order_by(
                sm.market_snapshots.c.as_of.desc(),
                sm.market_snapshots.c.market_snapshot_id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()

    def closing_fair(
        self, match_id: str, market_definition_id: str
    ) -> dict[str, float] | None:
        fair_json = self._connection.execute(
            select(sm.market_snapshots.c.fair_distribution_json)
            .where(
                sm.market_snapshots.c.match_id == match_id,
                sm.market_snapshots.c.market_definition_id == market_definition_id,
                sm.market_snapshots.c.snapshot_kind == 'closing',
            )
            .order_by(sm.market_snapshots.c.as_of.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if fair_json is None else json.loads(fair_json)

    def market_kind(self, market_definition_id: str) -> str | None:
        return self._connection.execute(
            select(sm.market_definitions.c.market_kind).where(
                sm.market_definitions.c.market_definition_id == market_definition_id
            )
        ).scalar_one_or_none()

    def latest_fair(self, match_id: str, market_definition_id: str) -> dict[str, float]:
        fair_json = self._connection.execute(
            select(sm.market_snapshots.c.fair_distribution_json)
            .where(
                sm.market_snapshots.c.match_id == match_id,
                sm.market_snapshots.c.market_definition_id == market_definition_id,
            )
            .order_by(sm.market_snapshots.c.as_of.desc())
            .limit(1)
        ).scalar_one_or_none()
        if fair_json is None:
            return {}
        return json.loads(fair_json)
