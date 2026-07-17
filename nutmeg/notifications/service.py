from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import (
    DeliveryOutcome,
    DeliveryStatus,
    DeliveryTarget,
    NotificationAttachment,
    NotificationOutcome,
    NotificationRequest,
    NotificationStatus,
    ProviderResult,
    StoredArtifact,
)
from nutmeg.notifications.repository import SqlAlchemyNotificationRepository


class NotificationProvider(Protocol):
    channel: str

    def send(
        self,
        *,
        target: DeliveryTarget,
        request: NotificationRequest,
        artifacts: tuple[StoredArtifact, ...],
    ) -> ProviderResult: ...

    def send_fallback(
        self,
        *,
        target: DeliveryTarget,
        request: NotificationRequest,
        error: ProviderResult,
    ) -> ProviderResult: ...


class NotificationService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyNotificationRepository,
        artifact_store: ArtifactStore,
        providers: Mapping[str, NotificationProvider],
        targets: tuple[DeliveryTarget, ...],
        sleep_fn: Callable[[float], None],
        now_fn: Callable[[], datetime] | None = None,
        max_attempts: int = 3,
        stale_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self.repository = repository
        self._artifact_store = artifact_store
        self._providers = dict(providers)
        self._targets = tuple(targets)
        self._sleep = sleep_fn
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._max_attempts = max_attempts
        self._stale_after = stale_after

    def publish(
        self, request: NotificationRequest, *, dry_run: bool = False
    ) -> NotificationOutcome:
        targets = self._targets_for(request)
        if dry_run:
            return NotificationOutcome(
                notification_id=None,
                dedupe_key=request.dedupe_key,
                status=NotificationStatus.DRY_RUN,
                deliveries=tuple(
                    DeliveryOutcome(
                        delivery_id=None,
                        channel=target.channel,
                        recipient_key=target.recipient_key,
                        destination=target.destination,
                        required=target.required,
                        status=DeliveryStatus.DRY_RUN,
                    )
                    for target in targets
                ),
            )

        self.repository.mark_stale_sending_uncertain(
            stale_before=self._now() - self._stale_after
        )
        existing = self.repository.get_by_dedupe_key(request.dedupe_key)
        if existing is not None and existing.status == NotificationStatus.SENT:
            return self._outcome(existing.notification_id, NotificationStatus.DEDUPLICATED)

        if existing is None:
            notification_id = f"N-{uuid4().hex}"
            artifacts = self._snapshot_attachments(notification_id, request)
            effective_targets = targets or (
                DeliveryTarget("telegram", request.audience, "", request.required),
            )
            try:
                existing = self.repository.create_notification(
                    request,
                    targets=effective_targets,
                    artifacts=artifacts,
                    notification_id=notification_id,
                    created_at=self._now(),
                )
            except Exception:
                self._artifact_store.remove_notification(notification_id)
                raise
        elif targets:
            self.repository.reconcile_targets(existing.notification_id, targets)

        self._deliver(existing.notification_id, request)
        return self._outcome(existing.notification_id)

    def retry(
        self, notification_id: str, *, include_permanent: bool = False
    ) -> NotificationOutcome:
        self.repository.reconcile_targets(notification_id, self._targets)
        bundle = self.repository.get_bundle(notification_id)
        request = NotificationRequest(
            kind=bundle.notification.kind,
            business_key=bundle.notification.business_key,
            stage=bundle.notification.stage,
            semantic_fingerprint=bundle.notification.semantic_fingerprint,
            subject=bundle.notification.subject,
            caption=bundle.notification.caption,
            body=bundle.notification.body,
            attachments=tuple(
                NotificationAttachment(
                    artifact.path,
                    artifact.media_type,
                    filename=artifact.original_name,
                )
                for artifact in bundle.artifacts
            ),
            metadata=bundle.notification.metadata,
        )
        self._deliver(
            notification_id,
            request,
            include_permanent=include_permanent,
        )
        return self._outcome(notification_id)

    def retry_failed_required(self) -> tuple[NotificationOutcome, ...]:
        return tuple(
            self.retry(item.notification_id)
            for item in self.repository.list_retryable_required()
        )

    def _snapshot_attachments(
        self, notification_id: str, request: NotificationRequest
    ) -> tuple[StoredArtifact, ...]:
        artifacts: list[StoredArtifact] = []
        try:
            for attachment in request.attachments:
                artifacts.append(self._artifact_store.snapshot(notification_id, attachment))
        except Exception:
            self._artifact_store.remove_notification(notification_id)
            raise
        return tuple(artifacts)

    def _deliver(
        self,
        notification_id: str,
        request: NotificationRequest,
        *,
        include_permanent: bool = False,
    ) -> None:
        artifacts = self.repository.list_artifacts(notification_id)
        for delivery in self.repository.list_deliveries(notification_id):
            if delivery.status == DeliveryStatus.SENT:
                continue
            if delivery.status == DeliveryStatus.PERMANENT_FAILED and not include_permanent:
                continue
            target = DeliveryTarget(
                delivery.channel,
                delivery.recipient_key,
                delivery.destination,
                delivery.required,
                request.audience,
            )
            if not target.destination:
                self._record_configuration_failure(delivery.delivery_id, "missing_recipient")
                continue
            provider = self._providers.get(target.channel)
            if provider is None:
                self._record_configuration_failure(delivery.delivery_id, "missing_provider")
                continue
            possible_duplicate = delivery.status == DeliveryStatus.UNCERTAIN
            attempt_limit = delivery.attempt_count + self._max_attempts
            while delivery.attempt_count < attempt_limit:
                attempt = self.repository.start_attempt(
                    delivery.delivery_id,
                    started_at=self._now(),
                    possible_duplicate=possible_duplicate,
                )
                result = provider.send(target=target, request=request, artifacts=artifacts)
                if result.status == DeliveryStatus.SENT:
                    self.repository.finish_attempt(
                        attempt.attempt_id,
                        delivered_at=self._now(),
                        provider_message_id=result.provider_message_id,
                    )
                    break
                self.repository.fail_attempt(
                    attempt.attempt_id,
                    failed_at=self._now(),
                    result=result,
                )
                delivery = self._delivery(notification_id, delivery.delivery_id)
                if not result.retryable or delivery.attempt_count >= attempt_limit:
                    self._try_fallback(
                        provider,
                        target,
                        request,
                        artifacts,
                        result,
                        notification_id=notification_id,
                        delivery_id=delivery.delivery_id,
                    )
                    break
                self._sleep(
                    result.retry_after_seconds
                    if result.retry_after_seconds is not None
                    else min(2 ** (delivery.attempt_count - 1), 4)
                )
                possible_duplicate = False
        self.repository.aggregate_notification(notification_id)

    def _record_configuration_failure(self, delivery_id: str, error_code: str) -> None:
        attempt = self.repository.start_attempt(delivery_id, started_at=self._now())
        self.repository.fail_attempt(
            attempt.attempt_id,
            failed_at=self._now(),
            result=ProviderResult.permanent_failure(
                error_code,
                "notification provider or recipient is not configured",
            ),
        )

    def _try_fallback(
        self,
        provider: NotificationProvider,
        target: DeliveryTarget,
        request: NotificationRequest,
        artifacts: tuple[StoredArtifact, ...],
        result: ProviderResult,
        *,
        notification_id: str,
        delivery_id: str,
    ) -> None:
        if not artifacts or result.error_code not in {
            "caption_too_long",
            "file_not_found",
            "invalid_attachment",
        }:
            return
        started_at = self._now()
        fallback_request = replace(
            request,
            metadata={**request.metadata, "notification_id": notification_id},
        )
        fallback_result = provider.send_fallback(
            target=target, request=fallback_request, error=result
        )
        self.repository.record_fallback_attempt(
            delivery_id,
            started_at=started_at,
            completed_at=self._now(),
            result=fallback_result,
        )

    def _targets_for(self, request: NotificationRequest) -> tuple[DeliveryTarget, ...]:
        return tuple(
            target
            for target in self._targets
            if target.audience == request.audience or request.audience == "all"
        )

    def _delivery(self, notification_id: str, delivery_id: str):
        for item in self.repository.list_deliveries(notification_id):
            if item.delivery_id == delivery_id:
                return item
        raise KeyError(f"notification delivery not found: {delivery_id}")

    def _outcome(
        self,
        notification_id: str,
        override_status: NotificationStatus | None = None,
    ) -> NotificationOutcome:
        bundle = self.repository.get_bundle(notification_id)
        deliveries = tuple(
            DeliveryOutcome(
                delivery_id=item.delivery_id,
                channel=item.channel,
                recipient_key=item.recipient_key,
                destination=item.destination,
                required=item.required,
                status=item.status,
                attempt_count=item.attempt_count,
                provider_message_id=item.provider_message_id,
                error_code=item.last_error_code,
                error_message=item.last_error_message,
                possible_duplicate=any(
                    attempt.delivery_id == item.delivery_id and attempt.possible_duplicate
                    for attempt in bundle.attempts
                ),
            )
            for item in bundle.deliveries
        )
        return NotificationOutcome(
            notification_id=notification_id,
            dedupe_key=bundle.notification.dedupe_key,
            status=override_status or bundle.notification.status,
            revision=bundle.notification.revision,
            deliveries=deliveries,
            artifacts=bundle.artifacts,
            possible_duplicate=any(item.possible_duplicate for item in deliveries),
        )
