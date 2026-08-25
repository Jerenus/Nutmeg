"""Typed product facade for protected ticket Actions."""
from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from nutmeg.ontology.actions.models import ActionOutcome, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import (
    ApproveTicketBatchRequest,
    ConfirmTicketPlacementRequest,
    CreateTicketBatchRequest,
    IssueTicketConfirmationRequest,
    RemoveTicketLegRequest,
)
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.tickets.models import TicketLegDraft
from nutmeg.product.contracts import (
    ApproveTicketBatchCommand,
    ConfirmPlacementCommand,
    CreateTicketBatchCommand,
    IssueConfirmationCommand,
    IssueConfirmationResponse,
    ObjectRefContract,
    ProductActionResponse,
    RemoveTicketLegCommand,
    TicketLegCommand,
)
from nutmeg.product.errors import ProductNotFoundError, ProductTicketError


@dataclass(frozen=True, slots=True)
class ConnectorPlacementRequest:
    ticket_artifact_id: str
    confirmation_id: str
    ticket_hash: str
    amount: float
    currency: str
    channel: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ConnectorPlacementReceipt:
    external_reference: str
    receipt_content: bytes
    receipt_content_type: str

    def __post_init__(self) -> None:
        if not self.external_reference.strip():
            raise ValueError('connector external_reference is required')
        if not self.receipt_content or not self.receipt_content_type.strip():
            raise ValueError('connector receipt is required')


class TicketPlacementConnector(Protocol):
    def place(self, request: ConnectorPlacementRequest) -> ConnectorPlacementReceipt: ...


class ProductTicketService:
    def __init__(
        self,
        protected_actions,
        *,
        actor_id: str,
        clock: Callable[[], datetime] | None = None,
        connector: TicketPlacementConnector | None = None,
    ) -> None:
        self._actions = protected_actions
        self._actor_id = actor_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connector = connector

    def create_batch(
        self, command: CreateTicketBatchCommand
    ) -> ProductActionResponse:
        outcome = self._execute(
            lambda: self._actions.create_ticket_batch(
                CreateTicketBatchRequest(
                    run_date=command.run_date.isoformat(),
                    channel=command.channel,
                    account_id=command.account_id,
                    currency=command.currency,
                    deadline_at=command.deadline_at,
                    legs=[_ticket_leg(leg) for leg in command.legs],
                    actor_id=self._actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=command.idempotency_key,
                    requested_at=self._requested_at(),
                )
            )
        )
        return _response(outcome)

    def remove_leg(
        self, ticket_batch_id: str, command: RemoveTicketLegCommand
    ) -> ProductActionResponse:
        outcome = self._execute(
            lambda: self._actions.remove_ticket_leg(
                RemoveTicketLegRequest(
                    ticket_batch_id=ticket_batch_id,
                    leg_key=command.leg_key,
                    expected_revision_no=command.expected_revision_no,
                    actor_id=self._actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=command.idempotency_key,
                    requested_at=self._requested_at(),
                )
            )
        )
        return _response(outcome)

    def approve_batch(
        self, ticket_batch_id: str, command: ApproveTicketBatchCommand
    ) -> ProductActionResponse:
        outcome = self._execute(
            lambda: self._actions.approve_ticket_batch(
                ApproveTicketBatchRequest(
                    ticket_batch_id=ticket_batch_id,
                    expected_revision_no=command.expected_revision_no,
                    actor_id=self._actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=command.idempotency_key,
                    requested_at=self._requested_at(),
                )
            )
        )
        return _response(outcome)

    def issue_confirmation(
        self, ticket_artifact_id: str, command: IssueConfirmationCommand
    ) -> IssueConfirmationResponse:
        result = self._execute(
            lambda: self._actions.issue_ticket_confirmation(
                IssueTicketConfirmationRequest(
                    ticket_artifact_id=ticket_artifact_id,
                    actor_id=self._actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=command.idempotency_key,
                    requested_at=self._requested_at(),
                )
            ),
            confirmation=True,
        )
        response = _response(result.outcome)
        return IssueConfirmationResponse(
            **response.model_dump(mode='python'),
            confirmation_id=result.confirmation_id,
            nonce=result.nonce,
            expires_at=result.expires_at,
        )

    def confirm_placement(
        self, ticket_artifact_id: str, command: ConfirmPlacementCommand
    ) -> ProductActionResponse:
        if command.placement_mode == 'connector':
            if self._connector is None:
                raise ProductTicketError(
                    'connector_unavailable',
                    'connector placement is unavailable',
                    status_code=503,
                )
            connector_receipt = self._connector.place(
                ConnectorPlacementRequest(
                    ticket_artifact_id=ticket_artifact_id,
                    confirmation_id=command.confirmation_id,
                    ticket_hash=command.ticket_hash,
                    amount=command.amount,
                    currency=command.currency,
                    channel=command.channel,
                    idempotency_key=command.idempotency_key,
                )
            )
            external_reference = connector_receipt.external_reference
            receipt = connector_receipt.receipt_content
            receipt_content_type = connector_receipt.receipt_content_type
        else:
            if command.receipt_base64 is None or command.receipt_content_type is None:
                raise ProductTicketError(
                    'receipt_required',
                    'manual receipt and content type are required',
                    status_code=422,
                )
            external_reference = command.external_reference
            receipt = base64.b64decode(command.receipt_base64, validate=True)
            receipt_content_type = command.receipt_content_type
        outcome = self._execute(
            lambda: self._actions.confirm_ticket_placement(
                ConfirmTicketPlacementRequest(
                    ticket_artifact_id=ticket_artifact_id,
                    confirmation_id=command.confirmation_id,
                    nonce=command.nonce,
                    ticket_hash=command.ticket_hash,
                    amount=command.amount,
                    currency=command.currency,
                    channel=command.channel,
                    placement_mode=command.placement_mode,
                    external_reference=external_reference,
                    receipt_content=receipt,
                    receipt_content_type=receipt_content_type,
                    actor_id=self._actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=command.idempotency_key,
                    requested_at=self._requested_at(),
                )
            ),
            confirmation=True,
        )
        return _response(outcome)

    def _requested_at(self) -> datetime:
        requested_at = self._clock()
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError('product ticket clock must be timezone-aware')
        return requested_at.astimezone(UTC)

    @staticmethod
    def _execute(operation, *, confirmation: bool = False):
        try:
            return operation()
        except OptimisticConcurrencyError as error:
            raise ProductTicketError(
                'ticket_revision_conflict', str(error), status_code=409
            ) from error
        except ValueError as error:
            message = str(error)
            lowered = message.casefold()
            if 'does not exist' in lowered:
                raise ProductNotFoundError(message) from error
            mappings = (
                ('audit error', 'ticket_audit_blocked', 409),
                ('unadjudicated warn', 'ticket_warning_unadjudicated', 409),
                ('deadline has passed', 'ticket_deadline_passed', 409),
                ('already placed', 'ticket_already_placed', 409),
                ('already consumed', 'confirmation_reused', 409),
                ('confirmation has expired', 'confirmation_stale', 409),
                ('binding mismatch', 'confirmation_binding_mismatch', 409),
                ('nonce mismatch', 'confirmation_binding_mismatch', 409),
                ('connector placement is unavailable', 'connector_unavailable', 503),
                ('manual receipt is required', 'receipt_required', 422),
            )
            for fragment, code, status_code in mappings:
                if fragment in lowered:
                    raise ProductTicketError(
                        code, message, status_code=status_code
                    ) from error
            if confirmation and 'committed revision' in lowered:
                raise ProductTicketError(
                    'confirmation_stale', message, status_code=409
                ) from error
            raise


def _ticket_leg(leg: TicketLegCommand) -> TicketLegDraft:
    return TicketLegDraft(
        leg_key=leg.leg_key,
        match_id=leg.match_id,
        match_no=leg.match_no,
        name=leg.name,
        market_definition_id=leg.market_definition_id,
        selection_id=leg.selection_id,
        outcome_key=leg.outcome_key,
        faces=leg.faces,
        forecast_revision_id=leg.forecast_revision_id,
        entry_quote_id=leg.entry_quote_id,
        odds=leg.odds,
        line=leg.line,
        bucket=leg.bucket,
        fair=dict(leg.fair),
        confidence=leg.confidence,
        directional_flags=tuple(leg.directional_flags),
        nondirectional_flags=tuple(leg.nondirectional_flags),
        anchor_integrity=leg.anchor_integrity,
        precedents=tuple(leg.precedents),
    )


def _response(outcome: ActionOutcome) -> ProductActionResponse:
    return ProductActionResponse(
        action_id=outcome.action_id,
        action_type=outcome.action_type,
        status=outcome.status.value,
        result_refs=[
            ObjectRefContract(**reference.to_dict())
            for reference in outcome.result_refs
        ],
        error_code=outcome.error_code,
        error_detail=outcome.error_detail,
        committed_at=outcome.committed_at,
    )
