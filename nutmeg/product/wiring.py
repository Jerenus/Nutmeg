"""Compose the current ontology into headless product services."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from nutmeg.config.settings import AppSettings
from nutmeg.decision.zucai_official import fetch_renjiu_history
from nutmeg.interfaces.bot.telegram import TelegramBotClient
from nutmeg.ontology.actions.bundle_actions import BundleActions
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.operator.result_actions import RegisterZucaiFixedPrizePolicyRequest
from nutmeg.ontology.operator.review_actions import ShadowReviewTokenCodec
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.copilot import MatchCopilotService, build_copilot_provider
from nutmeg.product.errors import ProductNotReadyError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_evidence import OperatorEvidenceService
from nutmeg.product.operator_maintenance import OperatorMaintenanceProbe
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import (
    CandidateGenerationWorker,
    ConfirmationDeadlineWorker,
    EvidenceFreezeRequestWorker,
    MarketBaselineWorker,
    OperatorInfrastructureWorkers,
    OperatorProjectionSignals,
    OperatorReadModelInvalidator,
    ProductOutboxWorker,
    ReviewMaterializationWorker,
    ScoreboardReviewCompletionWorker,
    TaskSettlementWorker,
    audit_current_candidate,
)
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.tickets import ProductTicketService
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramOwnerHeartbeatService,
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
    infrastructure_workers: OperatorInfrastructureWorkers | None = None
    projection_signals: OperatorProjectionSignals | None = None


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


def _operator_work_item_id(engine, task_evidence_bundle_revision_id: str) -> str:
    """Recreate the frozen sale-wave identity before a baseline exists."""
    with OntologyUnitOfWork(engine) as uow:
        bundle = uow.operator_decision.task_evidence_bundle_revision(
            task_evidence_bundle_revision_id
        )
        if bundle is None:
            raise ValueError("task evidence bundle does not exist")
        current_slate = uow.operator_sale.current_slate(
            bundle.lane,
            bundle.business_key,
        )
        items = uow.operator_decision.task_evidence_bundle_items(
            task_evidence_bundle_revision_id
        )
        item_matches = {item.match_id for item in items}
        offers = tuple(
            offer
            for offer in uow.operator_sale.offer_revisions_for_slate(
                bundle.slate_revision_id
            )
            if offer.match_id in item_matches
        )
    if (
        current_slate is None
        or current_slate.slate_revision_id != bundle.slate_revision_id
        or len(items) != bundle.required_match_count
        or len(offers) != bundle.required_match_count
    ):
        raise ValueError("task evidence bundle sale wave is stale")
    scope_key = hashlib.sha256(
        canonical_json(
            {
                "families": sorted(
                    offer.official_offer_family_id for offer in offers
                ),
                "revisions": sorted(
                    offer.official_offer_revision_id for offer in offers
                ),
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return (
        f"{bundle.task_family_id}:{bundle.task_snapshot_hash}:"
        f"sale_wave:{scope_key}"
    )


def _build_operator_infrastructure_workers(
    *,
    kernel: OntologyKernel,
    operator_queries: OperatorQueryService,
    runtime_config: OperatorRuntimeConfig | None,
    data_dir,
    projection_signals: OperatorProjectionSignals,
) -> OperatorInfrastructureWorkers | None:
    if runtime_config is None:
        return None
    action_service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    confirmation = ConfirmationDeadlineWorker(
        action_service=action_service,
        protected_tickets=kernel.protected_tickets,
        worker_id="operator-confirmation-deadline",
    )
    common = {
        "data_dir": data_dir,
        "clock": lambda: datetime.now(UTC),
        "outbox": ProductOutboxWorker(
            unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
            project_event=projection_signals.deliver,
        ),
        "read_model": OperatorReadModelInvalidator(
            unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
            project_event=projection_signals.invalidate,
        ),
    }
    if runtime_config.surface_mode is not OperatorSurfaceMode.ACTIVE:
        return OperatorInfrastructureWorkers(
            confirmation_deadlines=confirmation,
            **common,
        )

    return OperatorInfrastructureWorkers(
        evidence_freeze=EvidenceFreezeRequestWorker(
            action_service=action_service,
            evidence_actions=kernel.evidence_actions,
            bundle_actions=BundleActions(action_service),
            worker_id="operator-evidence-freeze",
            lease_duration=timedelta(minutes=5),
        ),
        market_baseline=MarketBaselineWorker(
            action_service=action_service,
            decision_actions=kernel.decision_actions,
            worker_id="operator-market-baseline",
            lease_duration=timedelta(minutes=5),
            work_item_id_resolver=lambda revision_id: _operator_work_item_id(
                kernel.engine,
                revision_id,
            ),
        ),
        candidate_generation=CandidateGenerationWorker(
            action_service=action_service,
            result_actions=kernel.result_actions,
            worker_id="operator-candidate-generation",
            lease_duration=timedelta(minutes=5),
            banded_jczq=True,
        ),
        confirmation_deadlines=confirmation,
        task_settlement=TaskSettlementWorker(
            action_service=action_service,
            result_actions=kernel.result_actions,
            worker_id="operator-task-settlement",
            lease_duration=timedelta(minutes=5),
        ),
        review_materialization=ReviewMaterializationWorker(
            action_service=action_service,
            review_actions=kernel.review_actions,
            worker_id="operator-review-materialization",
            lease_duration=timedelta(minutes=5),
        ),
        scoreboard_review_completion=ScoreboardReviewCompletionWorker(
            action_service=action_service,
            review_actions=kernel.review_actions,
            scoreboard_path=data_dir / "scoreboard.json",
            worker_id="operator-scoreboard-review-completion",
            lease_duration=timedelta(minutes=5),
        ),
        **common,
    )


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
    kernel.protected_tickets.bind_operator_candidate_auditor(audit_current_candidate)
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
    owner_chat_id = _telegram_owner(settings.telegram_allowed_chat_ids)
    maintenance_owner_health = TelegramOwnerHeartbeatService(
        action_service=ActionService(lambda: OntologyUnitOfWork(kernel.engine)),
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    telegram_owner_health = None
    if not isolated and settings.telegram_bot_token and owner_chat_id is not None:
        telegram_owner_health = maintenance_owner_health
    operator_queries = OperatorQueryService(
        repository=repository,
        product_queries=queries,
        official_history_provider=fetch_renjiu_history,
        clock=lambda: datetime.now(UTC),
        operator_evidence=operator_evidence,
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
        snapshot_tokens=snapshot_tokens,
        operator_decisions=kernel.decision_actions,
        operator_candidate_auditor=audit_current_candidate,
        maintenance_probe=OperatorMaintenanceProbe(
            heartbeat_service=maintenance_owner_health,
        ),
        shadow_review_tokens=(
            ShadowReviewTokenCodec(settings.operator_token_signing_key)
            if settings.operator_token_signing_key is not None
            else None
        ),
    )
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
        telegram_owner_health=telegram_owner_health,
        evidence_actions=kernel.evidence_actions,
        decision_actions=kernel.decision_actions,
        result_actions=kernel.result_actions,
        review_actions=kernel.review_actions,
        workflow_actions=kernel.workflow,
        protected_tickets=kernel.protected_tickets,
        snapshot_tokens=snapshot_tokens,
        calibrate=kernel.calibrate,
        repository=repository,
        scoreboard_path=settings.data_dir / "scoreboard.json",
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        projection_signals = OperatorProjectionSignals(
            delivered_sequence=uow.outbox.consumer_cursor("product_sse_delivery"),
            invalidated_sequence=uow.outbox.consumer_cursor(
                "operator_read_model_invalidation"
            ),
        )
    infrastructure_workers = _build_operator_infrastructure_workers(
        kernel=kernel,
        operator_queries=operator_queries,
        runtime_config=runtime_config,
        data_dir=settings.data_dir,
        projection_signals=projection_signals,
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
        infrastructure_workers=infrastructure_workers,
        projection_signals=projection_signals,
    )


__all__ = [
    "ProductServices",
    "SimulatedTelegramClient",
    "build_product_services",
]
