"""ExpressService: turn a committed forecast into an approved ticket.

``approve_for_match`` proposes then approves in one call. An empty legs request is a
legal no-op — an empty slate is always allowed, so it returns without writing a
ticket. Propose and approve derive distinct idempotency keys from one base so a
retried express call replays rather than double-books.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.ticket_actions import (
    ApproveTicketRequest,
    LegInput,
    ProposeTicketRequest,
    TicketActions,
)


@dataclass(frozen=True, slots=True)
class ExpressRequest:
    channel: str
    account_id: str
    decision_session_id: str | None
    legs: list[LegInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ExpressResult:
    approved: bool
    proposal_id: str | None
    ticket_id: str | None


class ExpressService:
    def __init__(self, ticket_actions: TicketActions) -> None:
        self._ticket_actions = ticket_actions

    def approve_for_match(self, request: ExpressRequest) -> ExpressResult:
        if not request.legs:
            return ExpressResult(approved=False, proposal_id=None, ticket_id=None)
        proposal = self._ticket_actions.propose_ticket(
            ProposeTicketRequest(
                channel=request.channel,
                decision_session_id=request.decision_session_id,
                legs=request.legs,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'{request.idempotency_key}:propose',
                requested_at=request.requested_at,
            )
        )
        proposal_id = proposal.result_refs[0].object_id
        approved = self._ticket_actions.approve_ticket(
            ApproveTicketRequest(
                channel=request.channel,
                account_id=request.account_id,
                proposal_id=proposal_id,
                legs=request.legs,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'{request.idempotency_key}:approve',
                requested_at=request.requested_at,
            )
        )
        ticket_id = next(
            (ref.object_id for ref in approved.result_refs if ref.object_type == 'ticket'),
            None,
        )
        return ExpressResult(approved=True, proposal_id=proposal_id, ticket_id=ticket_id)
