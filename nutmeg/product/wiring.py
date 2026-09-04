"""Compose the current ontology into headless product services."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nutmeg.config.settings import AppSettings
from nutmeg.decision.zucai_official import fetch_renjiu_history
from nutmeg.interfaces.bot.telegram import TelegramBotClient
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.operator.result_actions import RegisterZucaiFixedPrizePolicyRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.copilot import MatchCopilotService, build_copilot_provider
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_evidence import OperatorEvidenceService
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
)
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.tickets import ProductTicketService
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramTicketConfirmationService,
)


@dataclass(frozen=True, slots=True)
class ProductServices:
    kernel: OntologyKernel
    queries: ProductQueryService
    actions: ProductActionGateway
    settings: AppSettings
    runtime: OperatorRuntimeConfig | None = None
    confirmation_transport_kind: str = "unavailable"
    operator_queries: OperatorQueryService | None = None
    operator_actions: OperatorActionService | None = None
    copilot: MatchCopilotService | None = None
    tickets: ProductTicketService | None = None


def _telegram_owner(raw: str | None) -> int | None:
    values = {int(item.strip()) for item in (raw or "").split(",") if item.strip()}
    return next(iter(values)) if len(values) == 1 else None


def _ensure_initial_zucai_fixed_prize_policies(kernel: OntologyKernel) -> None:
    with OntologyUnitOfWork(kernel.engine) as uow:
        missing = tuple(
            ticket_kind
            for ticket_kind in ("sfc", "renjiu")
            if uow.operator_result.current_fixed_prize_policy(ticket_kind) is None
        )
    requested_at = datetime.now(UTC)
    for ticket_kind in missing:
        outcome = kernel.result_actions.register_zucai_fixed_prize_policy(
            RegisterZucaiFixedPrizePolicyRequest(
                ticket_kind=ticket_kind,
                policy_version="zucai-fixed-prize-v1",
                actor_id="system:fixed-prize-policy",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=(
                    f"operator-bootstrap:fixed-prize:{ticket_kind}:v1"
                ),
                requested_at=requested_at,
                expected_current_revision_no=0,
            )
        )
        if not outcome.is_success:
            raise ProductNotReadyError(
                f"initial {ticket_kind} fixed-prize policy was not registered"
            )


class SimulatedTelegramClient:
    """In-memory outbound confirmation transport for isolated acceptance runs."""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        message = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        self.sent_messages.append(message)
        return {"ok": True, "result": message}


def build_product_services(
    settings: AppSettings,
    *,
    runtime_config: OperatorRuntimeConfig | None = None,
) -> ProductServices:
    if runtime_config is not None and runtime_config.data_dir != settings.data_dir.resolve():
        raise ValueError("operator runtime and service data directories must match")
    isolated = (
        runtime_config is not None
        and runtime_config.runtime_scope is OperatorRuntimeScope.ISOLATED_CANDIDATE
    )
    if isolated and (settings.telegram_bot_token or settings.operator_scheduler_enabled):
        raise ValueError("isolated candidate side effects must be disabled")

    kernel = build_ontology_kernel(settings)
    status = kernel.status()
    if (
        not status.initialized
        or status.integrity_check != 'ok'
        or status.pending_migrations
    ):
        raise ProductNotReadyError(
            'ontology is not initialized, healthy, and current; run `nutmeg ontology init`'
        )
    if runtime_config is not None and runtime_config.mutations_enabled:
        _ensure_initial_zucai_fixed_prize_policies(kernel)
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    queries = ProductQueryService(repository, kernel)
    actions = ProductActionGateway(kernel, repository)
    snapshot_tokens = (
        OperatorSnapshotTokenCodec(settings.operator_token_signing_key)
        if settings.operator_token_signing_key is not None
        else None
    )
    operator_evidence = OperatorEvidenceService(
        repository=repository,
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
        snapshot_tokens=snapshot_tokens,
    )
    kernel.evidence_actions.bind_freeze_gate_resolver(
        operator_evidence.freeze_gate_for_uow
    )
    operator_queries = OperatorQueryService(
        repository=repository,
        product_queries=queries,
        official_history_provider=fetch_renjiu_history,
        clock=lambda: datetime.now(UTC),
        operator_evidence=operator_evidence,
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
        snapshot_tokens=snapshot_tokens,
    )
    owner_chat_id = _telegram_owner(settings.telegram_allowed_chat_ids)
    telegram_confirmation = None
    confirmation_transport_kind = "unavailable"
    if isolated:
        owner_chat_id = 0
        confirmation_transport_kind = "simulated"
        telegram_confirmation = TelegramTicketConfirmationService(
            kernel=kernel,
            telegram_client=SimulatedTelegramClient(),
            allowed_chat_ids={owner_chat_id},
            now_fn=lambda: datetime.now(UTC),
        )
    elif settings.telegram_bot_token and owner_chat_id is not None:
        confirmation_transport_kind = "telegram"
        telegram_confirmation = TelegramTicketConfirmationService(
            kernel=kernel,
            telegram_client=TelegramBotClient(
                token=settings.telegram_bot_token,
                base_url=settings.telegram_api_base_url,
            ),
            allowed_chat_ids={owner_chat_id},
            now_fn=lambda: datetime.now(UTC),
        )
    operator_actions = OperatorActionService(
        queries=operator_queries,
        action_gateway=actions,
        telegram_confirmation=telegram_confirmation,
        telegram_owner_chat_id=owner_chat_id,
        evidence_actions=kernel.evidence_actions,
        decision_actions=kernel.decision_actions,
        snapshot_tokens=snapshot_tokens,
        calibrate=kernel.calibrate,
        repository=repository,
        scoreboard_path=settings.data_dir / "scoreboard.json",
    )
    provider = build_copilot_provider(settings)
    return ProductServices(
        kernel=kernel,
        queries=queries,
        actions=actions,
        settings=settings,
        runtime=runtime_config,
        confirmation_transport_kind=confirmation_transport_kind,
        operator_queries=operator_queries,
        operator_actions=operator_actions,
        copilot=(
            MatchCopilotService(
                queries=queries,
                actions=actions,
                provider=provider,
            )
            if provider is not None
            else None
        ),
        tickets=ProductTicketService(
            kernel.protected_tickets,
            actor_id=settings.default_user_id,
        ),
    )


__all__ = [
    "ProductServices",
    "SimulatedTelegramClient",
    "build_product_services",
]
