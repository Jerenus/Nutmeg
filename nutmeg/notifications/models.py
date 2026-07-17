from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class NotificationStatus(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    DEDUPLICATED = "deduplicated"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"

    @property
    def is_success(self) -> bool:
        return self in {
            NotificationStatus.SENT,
            NotificationStatus.DEDUPLICATED,
            NotificationStatus.DRY_RUN,
            NotificationStatus.SKIPPED,
        }


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    RETRYABLE_FAILED = "retryable_failed"
    PERMANENT_FAILED = "permanent_failed"
    UNCERTAIN = "uncertain"
    DRY_RUN = "dry_run"


class AttemptOutcome(StrEnum):
    STARTED = "started"
    SENT = "sent"
    FAILED = "failed"
    FALLBACK_SENT = "fallback_sent"


@dataclass(slots=True, frozen=True)
class NotificationAttachment:
    path: Path
    media_type: str
    filename: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.media_type.strip():
            raise ValueError("attachment media_type is required")
        if self.filename is not None:
            safe_name = Path(self.filename).name
            if safe_name != self.filename or not safe_name:
                raise ValueError("attachment filename must be a basename")

    @property
    def resolved_filename(self) -> str:
        return self.filename or self.path.name


@dataclass(slots=True, frozen=True)
class StoredArtifact:
    artifact_id: str
    notification_id: str
    path: Path
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(slots=True, frozen=True)
class DeliveryTarget:
    channel: str
    recipient_key: str
    destination: str
    required: bool = True


@dataclass(slots=True, frozen=True)
class NotificationRequest:
    kind: str
    business_key: str
    stage: str
    semantic_fingerprint: str
    subject: str
    caption: str | None = None
    body: str | None = None
    attachments: tuple[NotificationAttachment, ...] = ()
    audience: str = "owner"
    required: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("kind", "business_key", "stage", "semantic_fingerprint", "subject"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        object.__setattr__(self, "attachments", tuple(self.attachments))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not (self.body and self.body.strip()) and not self.attachments:
            raise ValueError("notification requires text or attachment")

    @property
    def dedupe_key(self) -> str:
        return ":".join(
            (self.kind, self.business_key, self.stage, self.semantic_fingerprint)
        )

    @classmethod
    def text(
        cls,
        *,
        kind: str,
        business_key: str,
        stage: str,
        semantic_fingerprint: str,
        subject: str,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> NotificationRequest:
        return cls(
            kind=kind,
            business_key=business_key,
            stage=stage,
            semantic_fingerprint=semantic_fingerprint,
            subject=subject,
            body=text,
            metadata=metadata or {},
        )


@dataclass(slots=True, frozen=True)
class ProviderResult:
    status: DeliveryStatus
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def sent(cls, provider_message_id: str | int | None) -> ProviderResult:
        return cls(
            status=DeliveryStatus.SENT,
            provider_message_id=None
            if provider_message_id is None
            else str(provider_message_id),
        )

    @classmethod
    def retryable_failure(
        cls,
        error_code: str,
        error_message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> ProviderResult:
        return cls(
            status=DeliveryStatus.RETRYABLE_FAILED,
            error_code=error_code,
            error_message=error_message,
            retryable=True,
            retry_after_seconds=retry_after_seconds,
        )

    @classmethod
    def permanent_failure(cls, error_code: str, error_message: str) -> ProviderResult:
        return cls(
            status=DeliveryStatus.PERMANENT_FAILED,
            error_code=error_code,
            error_message=error_message,
        )


@dataclass(slots=True, frozen=True)
class DeliveryOutcome:
    delivery_id: str | None
    channel: str
    recipient_key: str
    destination: str
    required: bool
    status: DeliveryStatus
    attempt_count: int = 0
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    possible_duplicate: bool = False

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        if redact:
            data["destination"] = redact_destination(self.destination)
        return data


@dataclass(slots=True, frozen=True)
class NotificationOutcome:
    notification_id: str | None
    dedupe_key: str
    status: NotificationStatus
    revision: int | None = None
    deliveries: tuple[DeliveryOutcome, ...] = ()
    artifacts: tuple[StoredArtifact, ...] = ()
    possible_duplicate: bool = False

    @property
    def is_success(self) -> bool:
        return self.status.is_success

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "dedupe_key": self.dedupe_key,
            "status": self.status.value,
            "revision": self.revision,
            "deliveries": [item.to_dict(redact=redact) for item in self.deliveries],
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "path": str(item.path),
                    "original_name": item.original_name,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in self.artifacts
            ],
            "possible_duplicate": self.possible_duplicate,
        }

    @classmethod
    def sent_for_test(
        cls, notification_id: str, provider_message_id: str
    ) -> NotificationOutcome:
        return cls(
            notification_id=notification_id,
            dedupe_key=f"test:{notification_id}",
            status=NotificationStatus.SENT,
            revision=1,
            deliveries=(
                DeliveryOutcome(
                    delivery_id=f"D-{notification_id}",
                    channel="telegram",
                    recipient_key="owner",
                    destination="1",
                    required=True,
                    status=DeliveryStatus.SENT,
                    attempt_count=1,
                    provider_message_id=provider_message_id,
                ),
            ),
        )


@dataclass(slots=True, frozen=True)
class NotificationView:
    notification_id: str
    dedupe_key: str
    kind: str
    business_key: str
    stage: str
    semantic_fingerprint: str
    revision: int
    subject: str
    caption: str | None
    body: str | None
    metadata: Mapping[str, Any]
    status: NotificationStatus
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class DeliveryView:
    delivery_id: str
    notification_id: str
    channel: str
    recipient_key: str
    destination: str
    required: bool
    status: DeliveryStatus
    attempt_count: int
    provider_message_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    next_retry_at: datetime | None
    first_attempted_at: datetime | None
    delivered_at: datetime | None
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class AttemptView:
    attempt_id: str
    delivery_id: str
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None
    outcome: AttemptOutcome
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    retry_after_seconds: float | None
    response_metadata: Mapping[str, Any]
    possible_duplicate: bool


@dataclass(slots=True, frozen=True)
class NotificationBundle:
    notification: NotificationView
    artifacts: tuple[StoredArtifact, ...]
    deliveries: tuple[DeliveryView, ...]
    attempts: tuple[AttemptView, ...]


def semantic_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def redact_destination(destination: str) -> str:
    if not destination:
        return "(missing)"
    return f"***{destination[-4:]}"
