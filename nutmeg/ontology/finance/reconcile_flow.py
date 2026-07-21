"""ReconcileService: record a match outcome, then settle its tickets.

``settle_match`` records the outcome once and settles every ticket that has a leg on
the match. Settlement never fabricates a pending row: a ticket whose match still has
no outcome simply stays unsettled. Each ticket settles under its own idempotency key
so a re-run replays instead of double-settling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.outcome_actions import (
    OutcomeActions,
    RecordOutcomeRequest,
    SettleTicketRequest,
)
from nutmeg.ontology.actions.service import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class ReconcileRequest:
    match_id: str
    account_id: str
    score_90: str
    status: str
    source_artifact_retrieval_ids: list[str]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    outcome_id: str | None
    settled_ticket_ids: tuple[str, ...]


class ReconcileService:
    def __init__(
        self, outcome_actions: OutcomeActions, unit_of_work_factory: UnitOfWorkFactory
    ) -> None:
        self._outcome_actions = outcome_actions
        self._unit_of_work_factory = unit_of_work_factory

    def settle_match(self, request: ReconcileRequest) -> ReconcileResult:
        recorded = self._outcome_actions.record_outcome(
            RecordOutcomeRequest(
                match_id=request.match_id,
                score_90=request.score_90,
                status=request.status,
                source_artifact_retrieval_ids=request.source_artifact_retrieval_ids,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'{request.idempotency_key}:outcome',
                requested_at=request.requested_at,
            )
        )
        outcome_id = recorded.result_refs[0].object_id if recorded.result_refs else None
        with self._unit_of_work_factory() as uow:
            ticket_ids = uow.finance.tickets_for_match(request.match_id)
        settled: list[str] = []
        for ticket_id in ticket_ids:
            result = self._outcome_actions.settle_ticket(
                SettleTicketRequest(
                    ticket_id=ticket_id,
                    match_id=request.match_id,
                    account_id=request.account_id,
                    actor_id=request.actor_id,
                    actor_role=request.actor_role,
                    idempotency_key=f'{request.idempotency_key}:settle:{ticket_id}',
                    requested_at=request.requested_at,
                )
            )
            if result.settled:
                settled.append(ticket_id)
        return ReconcileResult(outcome_id=outcome_id, settled_ticket_ids=tuple(settled))
