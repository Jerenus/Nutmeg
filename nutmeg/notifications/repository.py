from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from nutmeg.notifications.models import (
    AttemptOutcome,
    AttemptView,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryView,
    NotificationBundle,
    NotificationRequest,
    NotificationStatus,
    NotificationView,
    ProviderResult,
    StoredArtifact,
)
from nutmeg.storage.state_models import (
    NotificationArtifactRecord,
    NotificationAttemptRecord,
    NotificationDeliveryRecord,
    NotificationRecord,
)


class SqlAlchemyNotificationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_notification(
        self,
        request: NotificationRequest,
        *,
        targets: tuple[DeliveryTarget, ...],
        artifacts: tuple[StoredArtifact, ...],
        notification_id: str | None = None,
        created_at: datetime | None = None,
    ) -> NotificationView:
        now = created_at or datetime.now(UTC)
        with self._session() as session:
            existing = session.scalar(
                select(NotificationRecord).where(
                    NotificationRecord.dedupe_key == request.dedupe_key
                )
            )
            if existing is not None:
                return _notification_view(existing)
            max_revision = session.scalar(
                select(func.max(NotificationRecord.revision)).where(
                    NotificationRecord.kind == request.kind,
                    NotificationRecord.business_key == request.business_key,
                    NotificationRecord.stage == request.stage,
                )
            )
            resolved_id = notification_id or f"N-{uuid4().hex}"
            record = NotificationRecord(
                notification_id=resolved_id,
                dedupe_key=request.dedupe_key,
                kind=request.kind,
                business_key=request.business_key,
                stage=request.stage,
                semantic_fingerprint=request.semantic_fingerprint,
                revision=int(max_revision or 0) + 1,
                subject=request.subject,
                caption=request.caption,
                body=request.body,
                metadata_json=_json(dict(request.metadata)),
                status=NotificationStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            for target in targets:
                session.add(
                    NotificationDeliveryRecord(
                        delivery_id=f"D-{uuid4().hex}",
                        notification_id=resolved_id,
                        channel=target.channel,
                        recipient_key=target.recipient_key,
                        destination=target.destination,
                        required=target.required,
                        status=DeliveryStatus.PENDING.value,
                        attempt_count=0,
                        updated_at=now,
                    )
                )
            for artifact in artifacts:
                session.add(_artifact_record(artifact, now))
            session.commit()
            return _notification_view(record)

    def get_by_dedupe_key(self, dedupe_key: str) -> NotificationView | None:
        with self._session() as session:
            record = session.scalar(
                select(NotificationRecord).where(NotificationRecord.dedupe_key == dedupe_key)
            )
            return None if record is None else _notification_view(record)

    def get_notification(self, notification_id: str) -> NotificationView | None:
        with self._session() as session:
            record = session.get(NotificationRecord, notification_id)
            return None if record is None else _notification_view(record)

    def list_deliveries(self, notification_id: str) -> tuple[DeliveryView, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(NotificationDeliveryRecord)
                .where(NotificationDeliveryRecord.notification_id == notification_id)
                .order_by(
                    NotificationDeliveryRecord.recipient_key,
                    NotificationDeliveryRecord.destination,
                )
            ).all()
            return tuple(_delivery_view(row) for row in rows)

    def list_artifacts(self, notification_id: str) -> tuple[StoredArtifact, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(NotificationArtifactRecord)
                .where(NotificationArtifactRecord.notification_id == notification_id)
                .order_by(NotificationArtifactRecord.artifact_id)
            ).all()
            return tuple(_stored_artifact(row) for row in rows)

    def add_artifacts(
        self, notification_id: str, artifacts: tuple[StoredArtifact, ...]
    ) -> None:
        now = datetime.now(UTC)
        with self._session() as session:
            for artifact in artifacts:
                session.add(_artifact_record(artifact, now))
            session.commit()

    def start_attempt(
        self,
        delivery_id: str,
        *,
        started_at: datetime,
        possible_duplicate: bool = False,
    ) -> AttemptView:
        with self._session() as session:
            delivery = session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is None:
                raise KeyError(f"notification delivery not found: {delivery_id}")
            delivery.attempt_count += 1
            delivery.status = DeliveryStatus.SENDING.value
            delivery.first_attempted_at = delivery.first_attempted_at or started_at
            delivery.updated_at = started_at
            notification = session.get(NotificationRecord, delivery.notification_id)
            if notification is not None:
                notification.status = NotificationStatus.DELIVERING.value
                notification.updated_at = started_at
            attempt = NotificationAttemptRecord(
                attempt_id=f"AT-{uuid4().hex}",
                delivery_id=delivery_id,
                attempt_number=delivery.attempt_count,
                started_at=started_at,
                outcome=AttemptOutcome.STARTED.value,
                possible_duplicate=possible_duplicate,
                response_metadata_json="{}",
            )
            session.add(attempt)
            session.commit()
            return _attempt_view(attempt)

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        delivered_at: datetime,
        provider_message_id: str | None,
    ) -> None:
        with self._session() as session:
            attempt = session.get(NotificationAttemptRecord, attempt_id)
            if attempt is None:
                raise KeyError(f"notification attempt not found: {attempt_id}")
            delivery = session.get(NotificationDeliveryRecord, attempt.delivery_id)
            if delivery is None:
                raise KeyError(f"notification delivery not found: {attempt.delivery_id}")
            attempt.completed_at = delivered_at
            attempt.outcome = AttemptOutcome.SENT.value
            attempt.provider_message_id = provider_message_id
            delivery.status = DeliveryStatus.SENT.value
            delivery.provider_message_id = provider_message_id
            delivery.last_error_code = None
            delivery.last_error_message = None
            delivery.next_retry_at = None
            delivery.delivered_at = delivered_at
            delivery.updated_at = delivered_at
            self._aggregate_in_session(session, delivery.notification_id, delivered_at)
            session.commit()

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        failed_at: datetime,
        result: ProviderResult,
    ) -> None:
        with self._session() as session:
            attempt = session.get(NotificationAttemptRecord, attempt_id)
            if attempt is None:
                raise KeyError(f"notification attempt not found: {attempt_id}")
            delivery = session.get(NotificationDeliveryRecord, attempt.delivery_id)
            if delivery is None:
                raise KeyError(f"notification delivery not found: {attempt.delivery_id}")
            attempt.completed_at = failed_at
            attempt.outcome = AttemptOutcome.FAILED.value
            attempt.error_code = result.error_code
            attempt.error_message = result.error_message
            attempt.retryable = result.retryable
            attempt.retry_after_seconds = result.retry_after_seconds
            attempt.response_metadata_json = _json(dict(result.metadata))
            delivery.status = result.status.value
            delivery.last_error_code = result.error_code
            delivery.last_error_message = result.error_message
            delivery.next_retry_at = (
                failed_at + timedelta(seconds=result.retry_after_seconds)
                if result.retry_after_seconds is not None
                else None
            )
            delivery.updated_at = failed_at
            self._aggregate_in_session(session, delivery.notification_id, failed_at)
            session.commit()

    def aggregate_notification(self, notification_id: str) -> NotificationView:
        now = datetime.now(UTC)
        with self._session() as session:
            self._aggregate_in_session(session, notification_id, now)
            record = session.get(NotificationRecord, notification_id)
            if record is None:
                raise KeyError(f"notification not found: {notification_id}")
            session.commit()
            return _notification_view(record)

    def mark_stale_sending_uncertain(self, *, stale_before: datetime) -> int:
        with self._session() as session:
            deliveries = session.scalars(
                select(NotificationDeliveryRecord).where(
                    NotificationDeliveryRecord.status == DeliveryStatus.SENDING.value,
                    NotificationDeliveryRecord.updated_at < stale_before,
                )
            ).all()
            affected: set[str] = set()
            for delivery in deliveries:
                delivery.status = DeliveryStatus.UNCERTAIN.value
                delivery.last_error_code = "stale_sending"
                delivery.last_error_message = "delivery outcome is unknown after interrupted send"
                delivery.updated_at = datetime.now(UTC)
                affected.add(delivery.notification_id)
                attempt = session.scalar(
                    select(NotificationAttemptRecord)
                    .where(
                        NotificationAttemptRecord.delivery_id == delivery.delivery_id,
                        NotificationAttemptRecord.outcome == AttemptOutcome.STARTED.value,
                    )
                    .order_by(NotificationAttemptRecord.attempt_number.desc())
                )
                if attempt is not None:
                    attempt.completed_at = delivery.updated_at
                    attempt.outcome = AttemptOutcome.FAILED.value
                    attempt.error_code = "stale_sending"
                    attempt.error_message = delivery.last_error_message
            for notification_id in affected:
                self._aggregate_in_session(session, notification_id, datetime.now(UTC))
            session.commit()
            return len(deliveries)

    def list_recent(self, since: datetime) -> tuple[NotificationView, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(NotificationRecord)
                .where(NotificationRecord.created_at >= since)
                .order_by(NotificationRecord.created_at.desc())
            ).all()
            return tuple(_notification_view(row) for row in rows)

    def list_retryable_required(self) -> tuple[NotificationView, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(NotificationRecord)
                .join(
                    NotificationDeliveryRecord,
                    NotificationDeliveryRecord.notification_id
                    == NotificationRecord.notification_id,
                )
                .where(
                    NotificationDeliveryRecord.required.is_(True),
                    NotificationDeliveryRecord.status.in_(
                        [
                            DeliveryStatus.RETRYABLE_FAILED.value,
                            DeliveryStatus.UNCERTAIN.value,
                        ]
                    ),
                )
                .distinct()
                .order_by(NotificationRecord.created_at.desc())
            ).all()
            return tuple(_notification_view(row) for row in rows)

    def get_bundle(self, notification_id: str) -> NotificationBundle:
        with self._session() as session:
            notification = session.get(NotificationRecord, notification_id)
            if notification is None:
                raise KeyError(f"notification not found: {notification_id}")
            artifacts = session.scalars(
                select(NotificationArtifactRecord)
                .where(NotificationArtifactRecord.notification_id == notification_id)
                .order_by(NotificationArtifactRecord.artifact_id)
            ).all()
            deliveries = session.scalars(
                select(NotificationDeliveryRecord)
                .where(NotificationDeliveryRecord.notification_id == notification_id)
                .order_by(
                    NotificationDeliveryRecord.recipient_key,
                    NotificationDeliveryRecord.destination,
                )
            ).all()
            delivery_ids = [row.delivery_id for row in deliveries]
            attempts = (
                session.scalars(
                    select(NotificationAttemptRecord)
                    .where(NotificationAttemptRecord.delivery_id.in_(delivery_ids))
                    .order_by(
                        NotificationAttemptRecord.delivery_id,
                        NotificationAttemptRecord.attempt_number,
                    )
                ).all()
                if delivery_ids
                else []
            )
            return NotificationBundle(
                notification=_notification_view(notification),
                artifacts=tuple(_stored_artifact(row) for row in artifacts),
                deliveries=tuple(_delivery_view(row) for row in deliveries),
                attempts=tuple(_attempt_view(row) for row in attempts),
            )

    def _aggregate_in_session(
        self, session: Session, notification_id: str, updated_at: datetime
    ) -> None:
        notification = session.get(NotificationRecord, notification_id)
        if notification is None:
            raise KeyError(f"notification not found: {notification_id}")
        deliveries = session.scalars(
            select(NotificationDeliveryRecord).where(
                NotificationDeliveryRecord.notification_id == notification_id,
                NotificationDeliveryRecord.required.is_(True),
            )
        ).all()
        statuses = {DeliveryStatus(row.status) for row in deliveries}
        if deliveries and statuses == {DeliveryStatus.SENT}:
            status = NotificationStatus.SENT
        elif DeliveryStatus.UNCERTAIN in statuses:
            status = NotificationStatus.UNCERTAIN
        elif statuses & {
            DeliveryStatus.PENDING,
            DeliveryStatus.SENDING,
            DeliveryStatus.RETRYABLE_FAILED,
        }:
            status = NotificationStatus.DELIVERING
        elif DeliveryStatus.SENT in statuses:
            status = NotificationStatus.PARTIAL
        else:
            status = NotificationStatus.FAILED
        notification.status = status.value
        notification.updated_at = updated_at

    def _session(self) -> Session:
        return Session(self._engine, expire_on_commit=False)


def _notification_view(row: NotificationRecord) -> NotificationView:
    return NotificationView(
        notification_id=row.notification_id,
        dedupe_key=row.dedupe_key,
        kind=row.kind,
        business_key=row.business_key,
        stage=row.stage,
        semantic_fingerprint=row.semantic_fingerprint,
        revision=row.revision,
        subject=row.subject,
        caption=row.caption,
        body=row.body,
        metadata=json.loads(row.metadata_json or "{}"),
        status=NotificationStatus(row.status),
        created_at=_from_storage_datetime(row.created_at),
        updated_at=_from_storage_datetime(row.updated_at),
    )


def _delivery_view(row: NotificationDeliveryRecord) -> DeliveryView:
    return DeliveryView(
        delivery_id=row.delivery_id,
        notification_id=row.notification_id,
        channel=row.channel,
        recipient_key=row.recipient_key,
        destination=row.destination,
        required=row.required,
        status=DeliveryStatus(row.status),
        attempt_count=row.attempt_count,
        provider_message_id=row.provider_message_id,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        next_retry_at=_from_storage_datetime(row.next_retry_at),
        first_attempted_at=_from_storage_datetime(row.first_attempted_at),
        delivered_at=_from_storage_datetime(row.delivered_at),
        updated_at=_from_storage_datetime(row.updated_at),
    )


def _attempt_view(row: NotificationAttemptRecord) -> AttemptView:
    return AttemptView(
        attempt_id=row.attempt_id,
        delivery_id=row.delivery_id,
        attempt_number=row.attempt_number,
        started_at=_from_storage_datetime(row.started_at),
        completed_at=_from_storage_datetime(row.completed_at),
        outcome=AttemptOutcome(row.outcome),
        provider_message_id=row.provider_message_id,
        error_code=row.error_code,
        error_message=row.error_message,
        retryable=row.retryable,
        retry_after_seconds=row.retry_after_seconds,
        response_metadata=json.loads(row.response_metadata_json or "{}"),
        possible_duplicate=row.possible_duplicate,
    )


def _stored_artifact(row: NotificationArtifactRecord) -> StoredArtifact:
    from pathlib import Path

    return StoredArtifact(
        artifact_id=row.artifact_id,
        notification_id=row.notification_id,
        path=Path(row.file_path),
        original_name=row.original_name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
    )


def _artifact_record(
    artifact: StoredArtifact, created_at: datetime
) -> NotificationArtifactRecord:
    return NotificationArtifactRecord(
        artifact_id=artifact.artifact_id,
        notification_id=artifact.notification_id,
        file_path=str(artifact.path),
        original_name=artifact.original_name,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        created_at=created_at,
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _from_storage_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
