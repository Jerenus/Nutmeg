"""Governed Actions for scoreboard observations and authority changes."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.scoreboard.models import (
    ScoreboardObservationRow,
    ScoreboardShadowReviewRow,
)

_CLASSIFICATIONS = {
    "matched",
    "formal_manual",
    "source_correction",
    "unexplained",
}


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} is required")


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class RecordScoreboardObservationRequest:
    group_key: str
    metric_key: str
    tally: str
    detail: str
    status: str
    numerator: float | None
    denominator: float | None
    value: float | None
    unit: str | None
    evidence_refs: list[ObjectRef]
    effective_at: datetime
    supersedes_observation_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.effective_at, "effective_at")
        _require_aware(self.requested_at, "requested_at")
        for name in ("group_key", "metric_key", "tally", "detail", "status"):
            _required(getattr(self, name), name)
        if not self.evidence_refs:
            raise ValueError("evidence_refs cannot be empty")
        if any(
            not ref.object_type.strip() or not ref.object_id.strip()
            for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must contain non-blank object refs")
        for number, name in (
            (self.numerator, "numerator"),
            (self.denominator, "denominator"),
            (self.value, "value"),
        ):
            if number is not None and not math.isfinite(float(number)):
                raise ValueError(f"{name} must be finite")
        if self.denominator is not None and self.denominator < 0:
            raise ValueError("denominator cannot be negative")
        if (
            self.numerator is not None
            and self.denominator is not None
            and self.numerator > self.denominator
        ):
            raise ValueError("numerator cannot exceed denominator")


@dataclass(frozen=True, slots=True)
class RecordScoreboardShadowReviewRequest:
    legacy_source_artifact_id: str
    legacy_sha256: str
    projection_version: str
    source_high_watermark: int
    classification: list[dict[str, object]]
    matched_count: int
    manual_count: int
    corrected_count: int
    unexplained_count: int
    status: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _required(self.legacy_source_artifact_id, "legacy_source_artifact_id")
        _required(self.projection_version, "projection_version")
        _required(self.status, "status")
        _sha256(self.legacy_sha256, "legacy_sha256")
        if self.source_high_watermark < 0:
            raise ValueError("source_high_watermark cannot be negative")
        expected = {name: 0 for name in _CLASSIFICATIONS}
        for item in self.classification:
            classification = item.get("classification")
            if classification not in _CLASSIFICATIONS:
                raise ValueError(f"unknown scoreboard classification {classification}")
            expected[str(classification)] += 1
        supplied = {
            "matched": self.matched_count,
            "formal_manual": self.manual_count,
            "source_correction": self.corrected_count,
            "unexplained": self.unexplained_count,
        }
        if any(value < 0 for value in supplied.values()) or supplied != expected:
            raise ValueError("classification counts do not match classification rows")


@dataclass(frozen=True, slots=True)
class ApproveScoreboardCutoverRequest:
    shadow_review_id: str
    legacy_sha256: str
    projection_version: str
    source_high_watermark: int
    expected_authority_version: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _required(self.shadow_review_id, "shadow_review_id")
        _required(self.projection_version, "projection_version")
        _sha256(self.legacy_sha256, "legacy_sha256")
        if self.source_high_watermark < 0:
            raise ValueError("source_high_watermark cannot be negative")
        if self.expected_authority_version < 1:
            raise ValueError("expected_authority_version must be positive")


@dataclass(frozen=True, slots=True)
class RecordScoreboardExportRequest:
    export_sha256: str
    expected_authority_version: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _sha256(self.export_sha256, "export_sha256")
        if self.expected_authority_version < 1:
            raise ValueError("expected_authority_version must be positive")


class ScoreboardActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_observation(
        self, request: RecordScoreboardObservationRequest
    ) -> ActionOutcome:
        evidence_refs = [ref.to_dict() for ref in request.evidence_refs]
        command = ActionCommand.create(
            action_type="record_scoreboard_observation",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "group_key": request.group_key,
                "metric_key": request.metric_key,
                "tally": request.tally,
                "detail": request.detail,
                "status": request.status,
                "numerator": request.numerator,
                "denominator": request.denominator,
                "value": request.value,
                "unit": request.unit,
                "evidence_refs": evidence_refs,
                "effective_at": request.effective_at.astimezone(UTC).isoformat(),
                "supersedes_observation_id": request.supersedes_observation_id,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            if request.supersedes_observation_id is not None:
                superseded = uow.scoreboard.observation(
                    request.supersedes_observation_id
                )
                if superseded is None:
                    raise ValueError(
                        f"scoreboard observation {request.supersedes_observation_id} "
                        "does not exist"
                    )
                if (superseded.group_key, superseded.metric_key) != (
                    request.group_key,
                    request.metric_key,
                ):
                    raise ValueError("a revision must keep the same group and metric keys")
            observation_id = f"sbo-{uuid4().hex}"
            uow.scoreboard.insert_observation(
                ScoreboardObservationRow(
                    scoreboard_observation_id=observation_id,
                    group_key=request.group_key,
                    metric_key=request.metric_key,
                    tally=request.tally,
                    detail=request.detail,
                    status=request.status,
                    numerator=request.numerator,
                    denominator=request.denominator,
                    value=request.value,
                    unit=request.unit,
                    evidence_refs=evidence_refs,
                    effective_at=request.effective_at.astimezone(UTC).isoformat(),
                    recorded_at=action.requested_at,
                    supersedes_observation_id=request.supersedes_observation_id,
                    action_id=action.action_id,
                )
            )
            return (ObjectRef("scoreboard_observation", observation_id),)

        return self._action_service.execute(command, handler)

    def record_shadow_review(
        self, request: RecordScoreboardShadowReviewRequest
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="record_scoreboard_shadow_review",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "legacy_source_artifact_id": request.legacy_source_artifact_id,
                "legacy_sha256": request.legacy_sha256,
                "projection_version": request.projection_version,
                "source_high_watermark": request.source_high_watermark,
                "classification": request.classification,
                "matched_count": request.matched_count,
                "manual_count": request.manual_count,
                "corrected_count": request.corrected_count,
                "unexplained_count": request.unexplained_count,
                "status": request.status,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            review_id = f"sbr-{uuid4().hex}"
            uow.scoreboard.insert_shadow_review(
                ScoreboardShadowReviewRow(
                    scoreboard_shadow_review_id=review_id,
                    legacy_source_artifact_id=request.legacy_source_artifact_id,
                    legacy_sha256=request.legacy_sha256,
                    projection_version=request.projection_version,
                    source_high_watermark=request.source_high_watermark,
                    classification=[dict(item) for item in request.classification],
                    matched_count=request.matched_count,
                    manual_count=request.manual_count,
                    corrected_count=request.corrected_count,
                    unexplained_count=request.unexplained_count,
                    status=request.status,
                    reviewed_at=action.requested_at,
                    action_id=action.action_id,
                )
            )
            return (ObjectRef("scoreboard_shadow_review", review_id),)

        return self._action_service.execute(command, handler)

    def approve_cutover(
        self, request: ApproveScoreboardCutoverRequest
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="approve_scoreboard_cutover",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "shadow_review_id": request.shadow_review_id,
                "legacy_sha256": request.legacy_sha256,
                "projection_version": request.projection_version,
                "source_high_watermark": request.source_high_watermark,
            },
            expected_versions={
                "scoreboard_authority:primary": request.expected_authority_version
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            authority = uow.scoreboard.authority()
            if authority.version != request.expected_authority_version:
                raise OptimisticConcurrencyError(
                    f"scoreboard authority is at version {authority.version}, "
                    f"expected {request.expected_authority_version}"
                )
            review = uow.scoreboard.shadow_review(request.shadow_review_id)
            latest = uow.scoreboard.latest_shadow_review()
            if review is None:
                raise ValueError(f"shadow review {request.shadow_review_id} does not exist")
            if latest is None or latest.scoreboard_shadow_review_id != request.shadow_review_id:
                raise ValueError("scoreboard shadow review is not current")
            if review.status != "succeeded":
                raise ValueError("scoreboard shadow review did not succeed")
            if review.unexplained_count:
                raise ValueError("scoreboard shadow review has unexplained differences")
            if review.legacy_sha256 != request.legacy_sha256:
                raise ValueError("legacy scoreboard hash does not match shadow review")
            if review.projection_version != request.projection_version:
                raise ValueError("projection version does not match shadow review")
            if review.source_high_watermark != request.source_high_watermark:
                raise ValueError("projection watermark does not match shadow review")
            uow.scoreboard.approve_authority(
                expected_version=request.expected_authority_version,
                review_id=request.shadow_review_id,
                projection_version=request.projection_version,
                source_high_watermark=request.source_high_watermark,
                legacy_sha256=request.legacy_sha256,
                approved_at=action.requested_at,
                action_id=action.action_id,
            )
            return (ObjectRef("scoreboard_authority", "primary"),)

        return self._action_service.execute(command, handler)

    def record_export(
        self,
        request: RecordScoreboardExportRequest,
        *,
        action_id: str | None = None,
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="record_scoreboard_export",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={"export_sha256": request.export_sha256},
            expected_versions={
                "scoreboard_authority:primary": request.expected_authority_version
            },
            requested_at=request.requested_at,
            action_id=action_id,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            uow.scoreboard.record_export(
                expected_version=request.expected_authority_version,
                export_sha256=request.export_sha256,
                action_id=action.action_id,
            )
            return (ObjectRef("scoreboard_authority", "primary"),)

        return self._action_service.execute(command, handler)
