"""Typed Actions for deterministic review materialization and completion."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository.operator_review import (
    ReviewItemRow,
    ScoreboardEffectDispositionRevisionRow,
    ScoreboardReviewCompletionReceiptRow,
    ScoreboardReviewCompletionRequestRow,
    ScoreboardReviewObservationLinkRow,
)
from nutmeg.ontology.scoreboard.models import ScoreboardObservationRow

_TOKEN_FRAME = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN_CONTEXT = b"nutmeg-shadow-review-v1\0"


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} is required")


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


class ReviewNotReadyError(ValueError):
    """The eligibility fact is valid but its exact Outcomes do not exist yet."""

    code = "review_not_ready"
    retryable = True


class ShadowReviewTokenError(ValueError):
    """Opaque error for malformed or unsigned shadow-review selections."""

    def __init__(self) -> None:
        super().__init__("invalid signed shadow review token")


class ShadowReviewTokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shadow_review_id: str = Field(min_length=1, max_length=500)
    source_high_watermark: int = Field(ge=0)
    compared_legacy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=500)

    @field_validator("metric_keys")
    @classmethod
    def _metric_keys_are_a_sorted_set(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("metric keys must be non-empty and bounded")
        if tuple(sorted(set(value))) != value:
            raise ValueError("metric keys must be sorted and unique")
        return value


class ShadowReviewTokenCodec:
    def __init__(self, signing_key: bytes | str) -> None:
        key = signing_key.encode("utf-8") if isinstance(signing_key, str) else signing_key
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("shadow review token signing key must contain at least 32 bytes")
        self._key = key

    def __repr__(self) -> str:
        return "ShadowReviewTokenCodec(<redacted>)"

    @staticmethod
    def _encode_frame(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_frame(value: str) -> bytes:
        if _TOKEN_FRAME.fullmatch(value) is None:
            raise ShadowReviewTokenError
        padding = "=" * ((4 - len(value) % 4) % 4)
        try:
            decoded = base64.b64decode(
                value + padding,
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, binascii.Error) as error:
            raise ShadowReviewTokenError from error
        if ShadowReviewTokenCodec._encode_frame(decoded) != value:
            raise ShadowReviewTokenError
        return decoded

    def encode(self, payload: ShadowReviewTokenPayload) -> str:
        if not isinstance(payload, ShadowReviewTokenPayload):
            raise TypeError("payload must be ShadowReviewTokenPayload")
        payload_bytes = canonical_json(payload.model_dump(mode="json")).encode("utf-8")
        signature = hmac.new(
            self._key,
            _TOKEN_CONTEXT + payload_bytes,
            hashlib.sha256,
        ).digest()
        return f"{self._encode_frame(payload_bytes)}.{self._encode_frame(signature)}"

    def decode(self, token: str) -> ShadowReviewTokenPayload:
        if not isinstance(token, str) or token.count(".") != 1:
            raise ShadowReviewTokenError
        payload_frame, signature_frame = token.split(".")
        payload_bytes = self._decode_frame(payload_frame)
        signature = self._decode_frame(signature_frame)
        expected = hmac.new(
            self._key,
            _TOKEN_CONTEXT + payload_bytes,
            hashlib.sha256,
        ).digest()
        if len(signature) != hashlib.sha256().digest_size or not hmac.compare_digest(
            signature,
            expected,
        ):
            raise ShadowReviewTokenError
        try:
            document = json.loads(payload_bytes.decode("utf-8"))
            payload = ShadowReviewTokenPayload.model_validate(document)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ShadowReviewTokenError from error
        canonical = canonical_json(payload.model_dump(mode="json")).encode("utf-8")
        if canonical != payload_bytes or self._encode_frame(canonical) != payload_frame:
            raise ShadowReviewTokenError
        return payload


@dataclass(frozen=True, slots=True)
class MaterializeOperatorReviewItemRequest:
    review_eligibility_fact_id: str
    worker_job_id: str
    lease_owner: str
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        for name in (
            "review_eligibility_fact_id",
            "worker_job_id",
            "lease_owner",
            "actor_id",
        ):
            _required(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class RecordScoreboardEffectDispositionRequest:
    review_id: str
    expected_disposition_revision_id: str | None
    disposition: Literal["effect_required", "no_effect"]
    required_metric_keys: Sequence[str]
    reason: str
    pre_update_legacy_sha256: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        for name in ("review_id", "reason", "actor_id", "idempotency_key"):
            _required(getattr(self, name), name)
        _sha256(self.pre_update_legacy_sha256, "pre_update_legacy_sha256")
        keys = tuple(self.required_metric_keys)
        if any(not key.strip() for key in keys):
            raise ValueError("required metric keys must be non-empty")
        if len(keys) != len(set(keys)):
            raise ValueError("required metric keys must be unique")
        if self.disposition == "effect_required" and not keys:
            raise ValueError("effect_required needs a non-empty metric-key set")
        if self.disposition == "no_effect" and keys:
            raise ValueError("no_effect cannot name metric keys")


@dataclass(frozen=True, slots=True)
class RecordScoreboardReviewObservationRequest:
    review_id: str
    expected_disposition_revision_id: str
    observed_legacy_sha256: str
    observation: RecordScoreboardObservationRequest

    def __post_init__(self) -> None:
        _required(self.review_id, "review_id")
        _required(
            self.expected_disposition_revision_id,
            "expected_disposition_revision_id",
        )
        _sha256(self.observed_legacy_sha256, "observed_legacy_sha256")


@dataclass(frozen=True, slots=True)
class RequestScoreboardReviewCompletionRequest:
    review_id: str
    expected_disposition_revision_id: str
    shadow_review_token: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        for name in (
            "review_id",
            "expected_disposition_revision_id",
            "shadow_review_token",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CompleteScoreboardReviewRequest:
    completion_request_id: str
    worker_job_id: str
    lease_owner: str
    current_legacy_sha256: str
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        for name in (
            "completion_request_id",
            "worker_job_id",
            "lease_owner",
            "actor_id",
        ):
            _required(getattr(self, name), name)
        _sha256(self.current_legacy_sha256, "current_legacy_sha256")


class OperatorReviewActions:
    def __init__(
        self,
        action_service: ActionService,
        *,
        shadow_token_signing_key: bytes | str | None = None,
    ) -> None:
        self._action_service = action_service
        self._shadow_tokens = (
            None
            if shadow_token_signing_key is None
            else ShadowReviewTokenCodec(shadow_token_signing_key)
        )

    def materialize_operator_review_item(
        self,
        request: MaterializeOperatorReviewItemRequest,
    ) -> ActionOutcome:
        with self._action_service.unit_of_work() as uow:
            fact = uow.operator_review.eligibility_fact(
                request.review_eligibility_fact_id
            )
            if fact is None:
                raise ValueError("review eligibility fact does not exist")
            outcome_ids = uow.operator_review.bound_outcome_revision_ids(fact)
        if outcome_ids is None:
            raise ReviewNotReadyError("bound Outcomes are not complete")
        binding_hash = hashlib.sha256(
            canonical_json(list(outcome_ids)).encode("utf-8")
        ).hexdigest()
        command = ActionCommand.create(
            action_type="materialize_operator_review_item",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=(
                f"review-materialization:{request.review_eligibility_fact_id}:"
                f"{binding_hash}:{request.actor_role.value}"
            ),
            requested_at=request.requested_at,
            payload={
                "review_eligibility_fact_id": request.review_eligibility_fact_id,
                "outcome_revision_ids": list(outcome_ids),
                "worker_job_id": request.worker_job_id,
            },
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            self._validate_worker_lease(
                uow,
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                job_kind="review_materialization",
                source_object_type="operator_review_eligibility_fact",
                source_object_id=request.review_eligibility_fact_id,
            )
            current_fact = uow.operator_review.eligibility_fact(
                request.review_eligibility_fact_id
            )
            if current_fact is None:
                raise ValueError("review eligibility fact does not exist")
            current_outcome_ids = uow.operator_review.bound_outcome_revision_ids(
                current_fact
            )
            if current_outcome_ids is None:
                raise ReviewNotReadyError("bound Outcomes are not complete")
            if current_outcome_ids != outcome_ids:
                raise OptimisticConcurrencyError(
                    "review Outcome revisions changed during materialization"
                )
            existing = uow.operator_review.review_for_eligibility_fact(
                current_fact.review_eligibility_fact_id
            )
            if existing is not None:
                if existing.outcome_revision_ids != outcome_ids:
                    raise OptimisticConcurrencyError(
                        "eligibility fact is already bound to different Outcomes"
                    )
                return (ObjectRef("operator_review_item", existing.review_id),)
            lane, business_key = uow.operator_review.eligibility_lane_business_key(
                current_fact
            )
            review_id = _stable_id(
                "operator-review",
                current_fact.review_eligibility_fact_id,
                outcome_ids,
            )
            uow.operator_review.insert_review_item(
                ReviewItemRow(
                    review_id=review_id,
                    review_eligibility_fact_id=(
                        current_fact.review_eligibility_fact_id
                    ),
                    task_family_id=current_fact.task_family_id,
                    work_item_id=current_fact.work_item_id,
                    task_snapshot_hash=current_fact.task_snapshot_hash,
                    lane=lane,
                    business_key=business_key,
                    review_kind=current_fact.review_kind,
                    market_prior_baseline_revision_id=(
                        current_fact.market_prior_baseline_revision_id
                    ),
                    outcome_revision_ids=outcome_ids,
                    materialized_by_action_id=action.action_id,
                    materialized_at=_utc(request.requested_at),
                )
            )
            uow.operator_decision.complete_worker_job(
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                result_action_id=action.action_id,
                result_object_type="operator_review_item",
                result_object_id=review_id,
                completed_at=_utc(request.requested_at),
            )
            return (ObjectRef("operator_review_item", review_id),)

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def record_scoreboard_effect_disposition(
        self,
        request: RecordScoreboardEffectDispositionRequest,
    ) -> ActionOutcome:
        metric_keys = tuple(sorted(request.required_metric_keys))
        command = ActionCommand.create(
            action_type="record_scoreboard_effect_disposition",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "review_id": request.review_id,
                "expected_disposition_revision_id": (
                    request.expected_disposition_revision_id
                ),
                "disposition": request.disposition,
                "required_metric_keys": list(metric_keys),
                "reason": request.reason.strip(),
                "pre_update_legacy_sha256": request.pre_update_legacy_sha256,
            },
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            review = uow.operator_review.review_item(request.review_id)
            if review is None:
                raise ValueError("operator review does not exist")
            if uow.operator_review.completion_receipt_for_review(review.review_id):
                raise ValueError("operator review is already complete")
            current = uow.operator_review.current_disposition(review.review_id)
            current_id = None if current is None else current.disposition_revision_id
            if current_id != request.expected_disposition_revision_id:
                raise OptimisticConcurrencyError(
                    f"current disposition is {current_id!r}, expected "
                    f"{request.expected_disposition_revision_id!r}"
                )
            if request.disposition == "effect_required":
                unknown = set(metric_keys) - uow.operator_review.registered_metric_keys()
                if unknown:
                    raise ValueError(
                        "required metric keys are not registered: "
                        + ", ".join(sorted(unknown))
                    )
            family_id = _stable_id("scoreboard-effect-disposition-family", review.review_id)
            revision_no = 1 if current is None else current.revision_no + 1
            disposition_id = _stable_id(
                "scoreboard-effect-disposition",
                family_id,
                revision_no,
                request.disposition,
                metric_keys,
                request.reason.strip(),
                request.pre_update_legacy_sha256,
            )
            row = ScoreboardEffectDispositionRevisionRow(
                disposition_revision_id=disposition_id,
                family_id=family_id,
                revision_no=revision_no,
                supersedes_revision_id=current_id,
                review_id=review.review_id,
                disposition=request.disposition,
                reason=request.reason.strip(),
                pre_update_legacy_sha256=request.pre_update_legacy_sha256,
                required_metric_keys=metric_keys,
                created_by_action_id=action.action_id,
                created_at=_utc(request.requested_at),
            )
            uow.operator_review.insert_disposition(row)
            refs = [ObjectRef("scoreboard_effect_disposition_revision", disposition_id)]
            if request.disposition == "no_effect":
                receipt_id = _stable_id(
                    "scoreboard-review-completion",
                    review.review_id,
                    disposition_id,
                    "no-effect",
                )
                uow.operator_review.insert_completion_receipt(
                    ScoreboardReviewCompletionReceiptRow(
                        completion_receipt_id=receipt_id,
                        review_id=review.review_id,
                        disposition_revision_id=disposition_id,
                        completion_request_id=None,
                        post_update_legacy_sha256=None,
                        observation_action_ids=(),
                        shadow_review_id=None,
                        shadow_source_high_watermark=None,
                        completed_by_action_id=action.action_id,
                        completed_at=_utc(request.requested_at),
                    )
                )
                refs.append(
                    ObjectRef("scoreboard_review_completion_receipt", receipt_id)
                )
            return tuple(refs)

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def record_scoreboard_review_observation(
        self,
        request: RecordScoreboardReviewObservationRequest,
    ) -> ActionOutcome:
        observation = request.observation
        evidence_refs = [ref.to_dict() for ref in observation.evidence_refs]
        command = ActionCommand.create(
            action_type="record_scoreboard_observation",
            actor_id=observation.actor_id,
            actor_role=observation.actor_role,
            idempotency_key=observation.idempotency_key,
            requested_at=observation.requested_at,
            payload={
                "group_key": observation.group_key,
                "metric_key": observation.metric_key,
                "tally": observation.tally,
                "detail": observation.detail,
                "status": observation.status,
                "numerator": observation.numerator,
                "denominator": observation.denominator,
                "value": observation.value,
                "unit": observation.unit,
                "evidence_refs": evidence_refs,
                "effective_at": _utc(observation.effective_at),
                "supersedes_observation_id": observation.supersedes_observation_id,
                "operator_review_id": request.review_id,
                "disposition_revision_id": request.expected_disposition_revision_id,
                "observed_legacy_sha256": request.observed_legacy_sha256,
            },
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            disposition = self._current_effect_disposition(
                uow,
                review_id=request.review_id,
                expected_disposition_revision_id=(
                    request.expected_disposition_revision_id
                ),
            )
            if observation.metric_key not in disposition.required_metric_keys:
                raise ValueError("observation does not name a required metric")
            links = uow.operator_review.observation_links_for_disposition(
                disposition.disposition_revision_id
            )
            if any(link.metric_key == observation.metric_key for link in links):
                raise ValueError("required metric is already linked")
            if links and any(
                link.observed_legacy_sha256 != request.observed_legacy_sha256
                for link in links
            ):
                raise ValueError("all observations must use the same post-update hash")
            current = uow.scoreboard.current_observation(
                observation.group_key,
                observation.metric_key,
            )
            if observation.supersedes_observation_id is not None:
                superseded = uow.scoreboard.observation(
                    observation.supersedes_observation_id
                )
                if superseded is None:
                    raise ValueError("scoreboard observation to supersede does not exist")
            if (
                current is not None
                and current.scoreboard_observation_id
                != observation.supersedes_observation_id
            ) or (
                current is None and observation.supersedes_observation_id is not None
            ):
                raise ValueError(
                    "a scoreboard observation revision must supersede the current leaf"
                )
            observation_id = f"sbo-{uuid4().hex}"
            uow.scoreboard.insert_observation(
                ScoreboardObservationRow(
                    scoreboard_observation_id=observation_id,
                    group_key=observation.group_key,
                    metric_key=observation.metric_key,
                    tally=observation.tally,
                    detail=observation.detail,
                    status=observation.status,
                    numerator=observation.numerator,
                    denominator=observation.denominator,
                    value=observation.value,
                    unit=observation.unit,
                    evidence_refs=evidence_refs,
                    effective_at=_utc(observation.effective_at),
                    recorded_at=action.requested_at,
                    supersedes_observation_id=observation.supersedes_observation_id,
                    action_id=action.action_id,
                )
            )
            link_id = _stable_id(
                "scoreboard-review-observation-link",
                disposition.disposition_revision_id,
                observation.metric_key,
                action.action_id,
            )
            uow.operator_review.insert_observation_link(
                ScoreboardReviewObservationLinkRow(
                    observation_link_id=link_id,
                    review_id=request.review_id,
                    disposition_revision_id=disposition.disposition_revision_id,
                    metric_key=observation.metric_key,
                    scoreboard_observation_id=observation_id,
                    observation_action_id=action.action_id,
                    observed_legacy_sha256=request.observed_legacy_sha256,
                    created_at=action.requested_at,
                )
            )
            return (
                ObjectRef("scoreboard_observation", observation_id),
                ObjectRef("scoreboard_review_observation_link", link_id),
            )

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def request_scoreboard_review_completion(
        self,
        request: RequestScoreboardReviewCompletionRequest,
    ) -> ActionOutcome:
        token_payload = self._shadow_token_codec().decode(
            request.shadow_review_token
        )
        command = ActionCommand.create(
            action_type="request_scoreboard_review_completion",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "review_id": request.review_id,
                "expected_disposition_revision_id": (
                    request.expected_disposition_revision_id
                ),
                "shadow_review_token_sha256": hashlib.sha256(
                    request.shadow_review_token.encode("utf-8")
                ).hexdigest(),
                "shadow_review_id": token_payload.shadow_review_id,
                "shadow_source_high_watermark": (
                    token_payload.source_high_watermark
                ),
                "compared_legacy_sha256": token_payload.compared_legacy_sha256,
                "metric_keys": list(token_payload.metric_keys),
            },
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            disposition = self._current_effect_disposition(
                uow,
                review_id=request.review_id,
                expected_disposition_revision_id=(
                    request.expected_disposition_revision_id
                ),
            )
            links = uow.operator_review.observation_links_for_disposition(
                disposition.disposition_revision_id
            )
            required = set(disposition.required_metric_keys)
            linked = {link.metric_key for link in links}
            if linked != required:
                raise ValueError("every required metric needs one linked observation")
            hashes = {link.observed_legacy_sha256 for link in links}
            if len(hashes) != 1:
                raise ValueError("linked observations do not share one post-update hash")
            observation_action_ids = tuple(
                link.observation_action_id for link in links
            )
            request_id = _stable_id(
                "scoreboard-review-completion-request",
                action.action_id,
                request.review_id,
                request.expected_disposition_revision_id,
                request.shadow_review_token,
                observation_action_ids,
            )
            uow.operator_review.insert_completion_request(
                ScoreboardReviewCompletionRequestRow(
                    completion_request_id=request_id,
                    action_id=action.action_id,
                    review_id=request.review_id,
                    disposition_revision_id=disposition.disposition_revision_id,
                    shadow_review_token=request.shadow_review_token,
                    shadow_review_id=token_payload.shadow_review_id,
                    shadow_source_high_watermark=(
                        token_payload.source_high_watermark
                    ),
                    compared_legacy_sha256=(
                        token_payload.compared_legacy_sha256
                    ),
                    metric_keys=token_payload.metric_keys,
                    observation_action_ids=observation_action_ids,
                    requested_at=action.requested_at,
                )
            )
            return (
                ObjectRef("scoreboard_review_completion_request", request_id),
                ObjectRef(
                    "operator_worker_job",
                    f"scoreboard-review-completion:{request_id}",
                ),
            )

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def complete_scoreboard_review(
        self,
        request: CompleteScoreboardReviewRequest,
    ) -> ActionOutcome:
        with self._action_service.unit_of_work() as uow:
            completion_request = uow.operator_review.completion_request(
                request.completion_request_id
            )
        if completion_request is None:
            raise ValueError("scoreboard review completion request does not exist")
        token_hash = hashlib.sha256(
            completion_request.shadow_review_token.encode("utf-8")
        ).hexdigest()
        command = ActionCommand.create(
            action_type="complete_scoreboard_review",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=(
                f"scoreboard-review-completion:{request.completion_request_id}:"
                f"{token_hash}:{request.current_legacy_sha256}:"
                f"{request.actor_role.value}"
            ),
            requested_at=request.requested_at,
            payload={
                "completion_request_id": request.completion_request_id,
                "worker_job_id": request.worker_job_id,
                "current_legacy_sha256": request.current_legacy_sha256,
                "shadow_review_token_sha256": token_hash,
            },
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            self._validate_worker_lease(
                uow,
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                job_kind="scoreboard_review_completion",
                source_object_type=(
                    "operator_scoreboard_review_completion_request"
                ),
                source_object_id=request.completion_request_id,
            )
            current_request = uow.operator_review.completion_request(
                request.completion_request_id
            )
            if current_request is None:
                raise ValueError("scoreboard review completion request does not exist")
            disposition = self._current_effect_disposition(
                uow,
                review_id=current_request.review_id,
                expected_disposition_revision_id=(
                    current_request.disposition_revision_id
                ),
            )
            payload = self._shadow_token_codec().decode(
                current_request.shadow_review_token
            )
            if payload.shadow_review_id != current_request.shadow_review_id:
                raise ValueError("selected shadow review token ID changed")
            if (
                payload.compared_legacy_sha256
                != current_request.compared_legacy_sha256
            ):
                raise ValueError("selected shadow legacy hash changed")
            if (
                payload.source_high_watermark
                != current_request.shadow_source_high_watermark
            ):
                raise ValueError("selected shadow high water changed")
            if payload.metric_keys != current_request.metric_keys:
                raise ValueError("selected shadow metric set changed")
            shadow = uow.scoreboard.shadow_review(payload.shadow_review_id)
            if shadow is None:
                raise ValueError("selected shadow review does not exist")
            if shadow.status != "succeeded":
                raise ValueError("selected shadow review did not succeed")
            if shadow.legacy_sha256 != payload.compared_legacy_sha256:
                raise ValueError("selected shadow legacy hash does not match")
            if shadow.source_high_watermark != payload.source_high_watermark:
                raise ValueError("selected shadow high water does not match")
            if request.current_legacy_sha256 != payload.compared_legacy_sha256:
                raise ValueError("current legacy hash does not match selected shadow")
            if payload.metric_keys != disposition.required_metric_keys:
                raise ValueError("selected shadow metric set does not match disposition")
            links = uow.operator_review.observation_links_for_disposition(
                disposition.disposition_revision_id
            )
            if tuple(link.observation_action_id for link in links) != (
                current_request.observation_action_ids
            ):
                raise ValueError("selected observation Action set changed")
            if tuple(link.metric_key for link in links) != disposition.required_metric_keys:
                raise ValueError("linked observation metric set changed")
            for link in links:
                if link.observed_legacy_sha256 != payload.compared_legacy_sha256:
                    raise ValueError("linked observation legacy hash does not match")
                action_rowid = uow.operator_review.action_rowid(
                    link.observation_action_id
                )
                if action_rowid is None or action_rowid > payload.source_high_watermark:
                    raise ValueError(
                        "selected shadow high water does not include observation Action"
                    )
                target_ref = f"scoreboard_observation:{link.scoreboard_observation_id}"
                matching = [
                    item
                    for item in shadow.classification
                    if item.get("metric_key") == link.metric_key
                    and item.get("target_ref") == target_ref
                ]
                if not matching:
                    raise ValueError(
                        "selected shadow review does not include observation Action"
                    )
                if any(
                    item.get("classification") == "unexplained"
                    for item in matching
                ):
                    raise ValueError(
                        "selected shadow review has an unexplained relevant difference"
                    )
            receipt_id = _stable_id(
                "scoreboard-review-completion",
                current_request.review_id,
                current_request.disposition_revision_id,
                current_request.completion_request_id,
            )
            uow.operator_review.insert_completion_receipt(
                ScoreboardReviewCompletionReceiptRow(
                    completion_receipt_id=receipt_id,
                    review_id=current_request.review_id,
                    disposition_revision_id=(
                        current_request.disposition_revision_id
                    ),
                    completion_request_id=(
                        current_request.completion_request_id
                    ),
                    post_update_legacy_sha256=(
                        payload.compared_legacy_sha256
                    ),
                    observation_action_ids=(
                        current_request.observation_action_ids
                    ),
                    shadow_review_id=payload.shadow_review_id,
                    shadow_source_high_watermark=(
                        payload.source_high_watermark
                    ),
                    completed_by_action_id=action.action_id,
                    completed_at=_utc(request.requested_at),
                )
            )
            uow.operator_decision.complete_worker_job(
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                result_action_id=action.action_id,
                result_object_type="scoreboard_review_completion_receipt",
                result_object_id=receipt_id,
                completed_at=_utc(request.requested_at),
            )
            return (
                ObjectRef("scoreboard_review_completion_receipt", receipt_id),
            )

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    @staticmethod
    def _validate_worker_lease(
        uow,
        *,
        worker_job_id: str,
        lease_owner: str,
        job_kind: str,
        source_object_type: str,
        source_object_id: str,
    ) -> None:
        job = uow.operator_decision.worker_job(worker_job_id)
        if job is None:
            raise ValueError("operator worker job does not exist")
        if (
            job.job_kind != job_kind
            or job.source_object_type != source_object_type
            or job.source_object_id != source_object_id
        ):
            raise ValueError("operator worker job source does not match request")
        if job.state != "leased" or job.lease_owner != lease_owner:
            raise ValueError("operator worker lease no longer belongs to this worker")

    def _shadow_token_codec(self) -> ShadowReviewTokenCodec:
        if self._shadow_tokens is None:
            raise ShadowReviewTokenError
        return self._shadow_tokens

    @staticmethod
    def _current_effect_disposition(
        uow,
        *,
        review_id: str,
        expected_disposition_revision_id: str,
    ) -> ScoreboardEffectDispositionRevisionRow:
        if uow.operator_review.completion_receipt_for_review(review_id):
            raise ValueError("operator review is already complete")
        disposition = uow.operator_review.current_disposition(review_id)
        if (
            disposition is None
            or disposition.disposition_revision_id
            != expected_disposition_revision_id
        ):
            raise OptimisticConcurrencyError(
                "current disposition does not match the submitted review"
            )
        if disposition.disposition != "effect_required":
            raise ValueError("scoreboard effect disposition does not require an update")
        return disposition


__all__ = [
    "CompleteScoreboardReviewRequest",
    "MaterializeOperatorReviewItemRequest",
    "OperatorReviewActions",
    "RecordScoreboardEffectDispositionRequest",
    "RecordScoreboardReviewObservationRequest",
    "RequestScoreboardReviewCompletionRequest",
    "ReviewNotReadyError",
    "ShadowReviewTokenCodec",
    "ShadowReviewTokenError",
    "ShadowReviewTokenPayload",
]
