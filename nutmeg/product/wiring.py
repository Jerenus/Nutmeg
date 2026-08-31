"""Compose the current ontology into headless product services."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.config.settings import AppSettings
from nutmeg.decision.zucai_official import fetch_renjiu_history
from nutmeg.interfaces.bot.telegram import TelegramBotClient
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.copilot import MatchCopilotService, build_copilot_provider
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_artifacts import ZucaiArtifactRepository
from nutmeg.product.operator_queries import OperatorQueryService
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
    operator_queries: OperatorQueryService | None = None
    operator_actions: OperatorActionService | None = None
    copilot: MatchCopilotService | None = None
    tickets: ProductTicketService | None = None


def _telegram_owner(raw: str | None) -> int | None:
    values = {int(item.strip()) for item in (raw or "").split(",") if item.strip()}
    return next(iter(values)) if len(values) == 1 else None


def build_product_services(settings: AppSettings) -> ProductServices:
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
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    queries = ProductQueryService(repository, kernel)
    actions = ProductActionGateway(kernel, repository)
    operator_queries = OperatorQueryService(
        repository=repository,
        product_queries=queries,
        artifacts=ZucaiArtifactRepository(settings.data_dir / "zucai"),
        official_history_provider=fetch_renjiu_history,
        clock=lambda: datetime.now(UTC),
    )
    owner_chat_id = _telegram_owner(settings.telegram_allowed_chat_ids)
    telegram_confirmation = None
    if settings.telegram_bot_token and owner_chat_id is not None:
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
    )
    provider = build_copilot_provider(settings)
    return ProductServices(
        kernel=kernel,
        queries=queries,
        actions=actions,
        settings=settings,
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
