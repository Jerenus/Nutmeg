"""Market Actions: de-vig quotes into a fair snapshot through the kernel.

`build_snapshot` is a `deterministic_system` Action: it records each quote, then
computes the fair distribution by reusing `nutmeg.decision.market_data.devig`
(the single source of the de-vig math — no re-implementation, no mental
arithmetic), and stores one versioned snapshot linked to its quotes. It never
chooses a betting direction.
"""
from __future__ import annotations

from uuid import uuid4

from nutmeg.decision.market_data import devig
from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.market.models import SnapshotBuildRequest
from nutmeg.ontology.repository.market import QuoteRow, SnapshotRow

_DEVIG_METHOD = 'proportional'
_DEVIG_METHOD_VERSION = '1'


class MarketActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def build_snapshot(self, request: SnapshotBuildRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'match_id': request.match_id,
            'market_definition_id': request.market_definition_id,
            'snapshot_kind': request.snapshot_kind,
            'as_of': request.as_of,
            'provider': request.provider,
            'artifact_retrieval_id': request.artifact_retrieval_id,
            'quotes': [
                {
                    'market_definition_id': quote.market_definition_id,
                    'selection_id': quote.selection_id,
                    'decimal_odds': quote.decimal_odds,
                    'bookmaker': quote.bookmaker,
                    'settlement_parameter_decimal': (
                        quote.settlement_parameter_decimal
                    ),
                }
                for quote in request.quotes
            ],
        }
        command = ActionCommand.create(
            action_type='build_market_snapshot',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            quote_ids: list[str] = []
            odds_by_outcome: dict[str, float] = {}
            for quote in request.quotes:
                quote_id = f'quote-{uuid4().hex}'
                uow.market.insert_quote(
                    QuoteRow(
                        quote_id=quote_id,
                        match_id=request.match_id,
                        market_definition_id=quote.market_definition_id,
                        selection_id=quote.selection_id,
                        provider=request.provider,
                        bookmaker=quote.bookmaker,
                        decimal_odds=quote.decimal_odds,
                        settlement_parameter_decimal=(
                            quote.settlement_parameter_decimal
                        ),
                        captured_at=request.as_of,
                        artifact_retrieval_id=request.artifact_retrieval_id,
                        quote_status='active',
                    )
                )
                quote_ids.append(quote_id)
                outcome_key = uow.market.selection_outcome_key(quote.selection_id)
                if outcome_key is not None:
                    odds_by_outcome[outcome_key] = quote.decimal_odds

            fair = devig(odds_by_outcome)
            snapshot_id = f'snapshot-{uuid4().hex}'
            uow.market.insert_snapshot(
                SnapshotRow(
                    market_snapshot_id=snapshot_id,
                    match_id=request.match_id,
                    market_definition_id=request.market_definition_id,
                    snapshot_kind=request.snapshot_kind,
                    as_of=request.as_of,
                    fair_distribution=fair,
                    devig_method=_DEVIG_METHOD,
                    method_version=_DEVIG_METHOD_VERSION,
                    source_coverage={'providers': 1, 'quotes': len(quote_ids)},
                    freshness={},
                    disagreement={},
                ),
                quote_ids=tuple(quote_ids),
            )
            return (ObjectRef('market_snapshot', snapshot_id),)

        return self._action_service.execute(command, handler)
