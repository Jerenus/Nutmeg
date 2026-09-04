"""Typed Actions for market baselines and human operator judgments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Literal

from nutmeg.decision.legs_audit import DEVIATION_RULE_IDS
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    commit_forecast_in_uow,
)
from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.operator.models import (
    BaselineEnvelopeBundleFaceRow,
    BaselineEnvelopeFaceBundleRow,
    BaselineEnvelopeOfferConstraintRow,
    BaselineEnvelopeRevisionRow,
    BaselineEnvelopeStructureTemplateRow,
    BaselineEnvelopeTemplateOfferRow,
    CandidateGenerationRequestRow,
    CandidateSelectionRow,
    JudgmentPrescriptionItemRow,
    JudgmentPrescriptionRevisionRow,
    MarketPriorBaselineProbabilityRow,
    MarketPriorBaselineRevisionRow,
    OperatorMatchJudgmentRevisionRow,
    OperatorWorkerJobRow,
)

_PROBABILITY_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal("0.000000000000")
_ONE = Decimal("1.000000000000")
_PROBABILITY_PRECISION = 12
_ARITHMETIC_VERSION = "decimal-half-even-v1"
_OUTCOME_FACE_CODES = {"home": "3", "draw": "1", "away": "0"}


class OperatorDecisionDependencyError(ValueError):
    """Stable terminal block surfaced by deterministic operator workers."""

    code = "invariant_failure"


class StaleOperatorDecisionDependencyError(OperatorDecisionDependencyError):
    code = "stale_dependency"


class OperatorEvidenceMissingError(OperatorDecisionDependencyError):
    code = "evidence_missing"


class OperatorEvidenceConflictError(OperatorDecisionDependencyError):
    code = "evidence_conflict"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def _content_hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> str:
    return _aware(value, "datetime").astimezone(UTC).isoformat()


def _decimal(value: str, *, name: str, probability: bool) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal string") from error
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    quantized = number.quantize(_PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if probability and not _ZERO <= quantized <= _ONE:
        raise ValueError(f"{name} must be between zero and one")
    return quantized


def _decimal_text(value: Decimal) -> str:
    return format(_ZERO if value == 0 else value, ".12f")


def _decimal_from_number(value: object, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{name} must be numeric") from error
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    return number.quantize(_PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _unique(values: tuple[str, ...], name: str, *, required: bool = True) -> None:
    if required and not values:
        raise ValueError(f"{name} are required")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")


def _required_revision(value: int | None) -> int:
    if value is None:
        raise ValueError("expected_current_revision_no is required")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(
            "expected_current_revision_no must be a non-negative integer"
        )
    return value


def _validate_revision_type(value: int | None) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(
            "expected_current_revision_no must be a non-negative integer"
        )


def _assert_expected_revision(
    *,
    expected: int | None,
    current_revision_no: int,
    object_label: str,
) -> None:
    expected_revision_no = _required_revision(expected)
    if expected_revision_no != current_revision_no:
        raise OptimisticConcurrencyError(
            f"{object_label} is at revision {current_revision_no}, "
            f"expected {expected_revision_no}"
        )


@dataclass(frozen=True, slots=True)
class FaceProbabilityInput:
    face_code: str
    probability_decimal: str


@dataclass(frozen=True, slots=True)
class FaceOffsetInput:
    face_code: str
    offset_probability_decimal: str


@dataclass(frozen=True, slots=True)
class FactorAdjustmentInput:
    factor_definition_id: str
    scope_key: str
    evidence_ref_tokens: tuple[str, ...]
    offsets: tuple[FaceOffsetInput, ...]


@dataclass(frozen=True, slots=True)
class FaceBundleInput:
    bundle_code: str
    face_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeOfferConstraint:
    official_match_no: str
    market_code: str
    allowed_face_bundles: tuple[FaceBundleInput, ...]
    omission_allowed: bool


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeStructureTemplate:
    kind: Literal["jczq_pass", "zucai_group"]
    structure_code: str
    eligible_official_match_nos: tuple[str, ...]
    pass_size: int | None
    required_offer_count: int
    maximum_groups: int


@dataclass(frozen=True, slots=True)
class FreezeMarketPriorBaselineRequest:
    task_evidence_bundle_revision_id: str
    work_item_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    worker_job_id: str | None = None
    lease_owner: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "task_evidence_bundle_revision_id",
            "work_item_id",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        if (self.worker_job_id is None) != (self.lease_owner is None):
            raise ValueError("worker_job_id and lease_owner must be supplied together")


@dataclass(frozen=True, slots=True)
class RecordBaselineEnvelopeRequest:
    task_evidence_bundle_revision_id: str
    work_item_id: str
    ticket_kind: str
    capital_cap_minor: int
    currency: str
    maximum_ticket_count: int
    offer_constraints: tuple[BaselineEnvelopeOfferConstraint, ...]
    structure_templates: tuple[BaselineEnvelopeStructureTemplate, ...]
    maximum_exhaustive_candidate_count: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "task_evidence_bundle_revision_id",
            "work_item_id",
            "ticket_kind",
            "currency",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        _validate_revision_type(self.expected_current_revision_no)


@dataclass(frozen=True, slots=True)
class CommitOperatorMatchJudgmentRequest:
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    work_item_id: str
    match_id: str
    official_offer_revision_id: str
    market_definition_id: str
    prior: tuple[FaceProbabilityInput, ...]
    belief: tuple[FaceProbabilityInput, ...]
    factors: tuple[FactorAdjustmentInput, ...]
    expression_bundles: tuple[FaceBundleInput, ...]
    rule_ids: tuple[str, ...]
    evidence_ref_tokens: tuple[str, ...]
    falsifier: str
    rationale: str
    commitment_tier: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "task_evidence_bundle_revision_id",
            "market_prior_baseline_revision_id",
            "baseline_envelope_revision_id",
            "work_item_id",
            "match_id",
            "official_offer_revision_id",
            "market_definition_id",
            "falsifier",
            "rationale",
            "commitment_tier",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        _validate_revision_type(self.expected_current_revision_no)


@dataclass(frozen=True, slots=True)
class FreezeJudgmentPrescriptionRequest:
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    work_item_id: str
    judgment_revision_ids: tuple[str, ...]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "task_evidence_bundle_revision_id",
            "market_prior_baseline_revision_id",
            "baseline_envelope_revision_id",
            "work_item_id",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        _unique(self.judgment_revision_ids, "judgment_revision_ids", required=False)
        _validate_revision_type(self.expected_current_revision_no)


@dataclass(frozen=True, slots=True)
class RequestCandidateGenerationRequest:
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    work_item_id: str
    fixed_prize_policy_revision_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "task_evidence_bundle_revision_id",
            "market_prior_baseline_revision_id",
            "baseline_envelope_revision_id",
            "judgment_prescription_revision_id",
            "work_item_id",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        if self.fixed_prize_policy_revision_id is not None:
            _required(
                self.fixed_prize_policy_revision_id,
                "fixed_prize_policy_revision_id",
            )
        _aware(self.requested_at, "requested_at")
        _validate_revision_type(self.expected_current_revision_no)


@dataclass(frozen=True, slots=True)
class SelectTicketCandidateRequest:
    candidate_set_revision_id: str
    candidate_revision_id: str
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "candidate_set_revision_id",
            "candidate_revision_id",
            "reason",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        _validate_revision_type(self.expected_current_revision_no)


class OperatorDecisionActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def freeze_market_prior_baseline(
        self, request: FreezeMarketPriorBaselineRequest
    ) -> ActionOutcome:
        policy_version = self._bundle_policy(request.task_evidence_bundle_revision_id)
        command = ActionCommand.create(
            action_type="freeze_market_prior_baseline",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            payload={
                "task_evidence_bundle_revision_id": (
                    request.task_evidence_bundle_revision_id
                ),
                "work_item_id": request.work_item_id,
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            bundle, items = self._current_bundle(
                uow, request.task_evidence_bundle_revision_id
            )
            if request.worker_job_id is not None:
                self._require_worker_lease(uow, request, bundle)
            source_rows = self._market_baseline_source_rows(uow, bundle, items)
            family_id = _stable_id(
                "market-prior-baseline-family",
                bundle.task_family_id,
                request.work_item_id,
            )
            document = {
                "task_evidence_bundle_revision_id": (
                    bundle.task_evidence_bundle_revision_id
                ),
                "task_snapshot_hash": bundle.task_snapshot_hash,
                "slate_revision_id": bundle.slate_revision_id,
                "information_cutoff_at": bundle.information_cutoff_at,
                "policy_version": bundle.policy_version,
                "arithmetic_version": _ARITHMETIC_VERSION,
                "probability_precision": _PROBABILITY_PRECISION,
                "comparison_only": True,
                "probabilities": source_rows,
            }
            content_hash = _content_hash(document)
            current = uow.operator_decision.current_market_prior_baseline_revision(
                family_id
            )
            if current is not None and current.content_hash == content_hash:
                result_ref = ObjectRef(
                    "market_prior_baseline_revision",
                    current.market_prior_baseline_revision_id,
                )
            else:
                revision_no = 1 if current is None else current.revision_no + 1
                revision_id = _stable_id(
                    "market-prior-baseline", family_id, revision_no, content_hash
                )
                uow.operator_decision.insert_market_prior_baseline_revision(
                    MarketPriorBaselineRevisionRow(
                        market_prior_baseline_revision_id=revision_id,
                        market_prior_baseline_family_id=family_id,
                        revision_no=revision_no,
                        supersedes_revision_id=(
                            None
                            if current is None
                            else current.market_prior_baseline_revision_id
                        ),
                        task_family_id=bundle.task_family_id,
                        work_item_id=request.work_item_id,
                        task_snapshot_hash=bundle.task_snapshot_hash,
                        slate_revision_id=bundle.slate_revision_id,
                        task_evidence_bundle_revision_id=(
                            bundle.task_evidence_bundle_revision_id
                        ),
                        information_cutoff_at=bundle.information_cutoff_at,
                        policy_version=bundle.policy_version,
                        arithmetic_version=_ARITHMETIC_VERSION,
                        probability_precision=_PROBABILITY_PRECISION,
                        comparison_only=1,
                        content_hash=content_hash,
                        action_id=action_command.action_id,
                        created_at=_utc(request.requested_at),
                    )
                )
                for index, source in enumerate(source_rows):
                    uow.operator_decision.insert_market_prior_baseline_probability(
                        MarketPriorBaselineProbabilityRow(
                            market_prior_baseline_probability_id=_stable_id(
                                "market-prior-probability",
                                revision_id,
                                source["match_id"],
                                source["market_definition_id"],
                                source["face_code"],
                            ),
                            market_prior_baseline_revision_id=revision_id,
                            item_index=index,
                            **source,
                        )
                    )
                result_ref = ObjectRef("market_prior_baseline_revision", revision_id)
            if request.worker_job_id is not None:
                uow.operator_decision.complete_worker_job(
                    worker_job_id=request.worker_job_id,
                    lease_owner=request.lease_owner or "",
                    result_action_id=action_command.action_id,
                    result_object_type=result_ref.object_type,
                    result_object_id=result_ref.object_id,
                    completed_at=_utc(request.requested_at),
                )
            return (result_ref,)

        return self._action_service.execute(command, handler)

    def request_candidate_generation(
        self,
        request: RequestCandidateGenerationRequest,
    ) -> ActionOutcome:
        policy_version = self._bundle_policy(request.task_evidence_bundle_revision_id)
        command = ActionCommand.create(
            action_type="request_candidate_generation",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            payload={
                "task_evidence_bundle_revision_id": (
                    request.task_evidence_bundle_revision_id
                ),
                "market_prior_baseline_revision_id": (
                    request.market_prior_baseline_revision_id
                ),
                "baseline_envelope_revision_id": (
                    request.baseline_envelope_revision_id
                ),
                "judgment_prescription_revision_id": (
                    request.judgment_prescription_revision_id
                ),
                "work_item_id": request.work_item_id,
                "fixed_prize_policy_revision_id": (
                    request.fixed_prize_policy_revision_id
                ),
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            bundle, _items = self._current_bundle(
                uow, request.task_evidence_bundle_revision_id
            )
            baseline, envelope = self._same_decision_lineage(
                uow,
                bundle,
                request.work_item_id,
                request.market_prior_baseline_revision_id,
                request.baseline_envelope_revision_id,
            )
            prescription = uow.operator_decision.judgment_prescription_revision(
                request.judgment_prescription_revision_id
            )
            if prescription is None:
                raise ValueError("judgment prescription does not exist")
            current_prescription = (
                uow.operator_decision.current_judgment_prescription_revision(
                    prescription.judgment_prescription_family_id
                )
            )
            expected_lineage = (
                bundle.task_family_id,
                request.work_item_id,
                bundle.task_snapshot_hash,
                bundle.slate_revision_id,
                bundle.task_evidence_bundle_revision_id,
                baseline.market_prior_baseline_revision_id,
                envelope.baseline_envelope_revision_id,
            )
            actual_lineage = (
                prescription.task_family_id,
                prescription.work_item_id,
                prescription.task_snapshot_hash,
                prescription.slate_revision_id,
                prescription.task_evidence_bundle_revision_id,
                prescription.market_prior_baseline_revision_id,
                prescription.baseline_envelope_revision_id,
            )
            if (
                current_prescription is None
                or current_prescription.judgment_prescription_revision_id
                != prescription.judgment_prescription_revision_id
                or actual_lineage != expected_lineage
            ):
                raise StaleOperatorDecisionDependencyError(
                    "candidate request prescription is stale or cross-lineage"
                )
            self._validate_fixed_prize_policy(
                uow,
                envelope.ticket_kind,
                request.fixed_prize_policy_revision_id,
            )
            baseline_rows = (
                uow.operator_decision.market_prior_baseline_probabilities(
                    baseline.market_prior_baseline_revision_id
                )
            )
            self._validate_baseline_quote_bindings(uow, baseline, baseline_rows)
            self._require_open_offer_revisions(
                uow,
                baseline.slate_revision_id,
                {
                    str(row["official_offer_revision_id"])
                    for row in baseline_rows
                },
                request.requested_at,
            )
            current_set = uow.operator_result.current_candidate_set(
                task_family_id=bundle.task_family_id,
                work_item_id=request.work_item_id,
                set_kind="judgment_bound",
            )
            _assert_expected_revision(
                expected=request.expected_current_revision_no,
                current_revision_no=(
                    0 if current_set is None else current_set.revision_no
                ),
                object_label="ticket candidate set",
            )
            dependency_document = {
                "task_snapshot_hash": bundle.task_snapshot_hash,
                "slate_revision_id": bundle.slate_revision_id,
                "task_evidence_bundle_revision_id": (
                    bundle.task_evidence_bundle_revision_id
                ),
                "market_prior_baseline_revision_id": (
                    baseline.market_prior_baseline_revision_id
                ),
                "baseline_envelope_revision_id": (
                    envelope.baseline_envelope_revision_id
                ),
                "judgment_prescription_revision_id": (
                    prescription.judgment_prescription_revision_id
                ),
                "fixed_prize_policy_revision_id": (
                    request.fixed_prize_policy_revision_id
                ),
            }
            dependency_fingerprint = _content_hash(dependency_document)
            request_document = {
                **dependency_document,
                "task_family_id": bundle.task_family_id,
                "work_item_id": request.work_item_id,
                "expected_current_revision_no": _required_revision(
                    request.expected_current_revision_no
                ),
            }
            content_hash = _content_hash(request_document)
            generation_request_id = _stable_id(
                "operator-candidate-generation-request",
                bundle.task_family_id,
                request.work_item_id,
                content_hash,
            )
            requested_at = _utc(request.requested_at)
            uow.operator_decision.insert_candidate_generation_request(
                CandidateGenerationRequestRow(
                    generation_request_id=generation_request_id,
                    action_id=action_command.action_id,
                    task_family_id=bundle.task_family_id,
                    work_item_id=request.work_item_id,
                    task_snapshot_hash=bundle.task_snapshot_hash,
                    slate_revision_id=bundle.slate_revision_id,
                    task_evidence_bundle_revision_id=(
                        bundle.task_evidence_bundle_revision_id
                    ),
                    market_prior_baseline_revision_id=(
                        baseline.market_prior_baseline_revision_id
                    ),
                    baseline_envelope_revision_id=(
                        envelope.baseline_envelope_revision_id
                    ),
                    judgment_prescription_revision_id=(
                        prescription.judgment_prescription_revision_id
                    ),
                    fixed_prize_policy_revision_id=(
                        request.fixed_prize_policy_revision_id
                    ),
                    dependency_fingerprint=dependency_fingerprint,
                    expected_current_revision_no=_required_revision(
                        request.expected_current_revision_no
                    ),
                    content_hash=content_hash,
                    requested_at=requested_at,
                )
            )
            uow.operator_decision.insert_worker_job(
                OperatorWorkerJobRow(
                    worker_job_id=_stable_id(
                        "operator-worker-job",
                        "candidate_generation",
                        generation_request_id,
                    ),
                    job_kind="candidate_generation",
                    source_object_type="operator_candidate_generation_request",
                    source_object_id=generation_request_id,
                    state="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    attempt_count=0,
                    available_at=requested_at,
                    last_error_code=None,
                    result_action_id=None,
                    result_object_type=None,
                    result_object_id=None,
                    created_at=requested_at,
                    updated_at=requested_at,
                )
            )
            return (
                ObjectRef(
                    "operator_candidate_generation_request",
                    generation_request_id,
                ),
            )

        return self._action_service.execute(command, handler)

    def select_ticket_candidate(
        self,
        request: SelectTicketCandidateRequest,
    ) -> ActionOutcome:
        policy_version = self._candidate_set_policy(request.candidate_set_revision_id)
        command = ActionCommand.create(
            action_type="select_ticket_candidate",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            expected_versions={
                "ticket-candidate-selection": _required_revision(
                    request.expected_current_revision_no
                )
            },
            payload={
                "candidate_set_revision_id": request.candidate_set_revision_id,
                "candidate_revision_id": request.candidate_revision_id,
                "reason": request.reason.strip(),
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            candidate_set = uow.operator_result.candidate_set_revision(
                request.candidate_set_revision_id
            )
            candidate = uow.operator_result.candidate(request.candidate_revision_id)
            if candidate_set is None or candidate is None:
                raise ValueError("ticket candidate does not exist")
            current_set = uow.operator_result.current_candidate_set(
                task_family_id=candidate_set.task_family_id,
                work_item_id=candidate_set.work_item_id,
                set_kind=candidate_set.set_kind,
            )
            if (
                current_set is None
                or current_set.candidate_set_revision_id
                != candidate_set.candidate_set_revision_id
            ):
                raise StaleOperatorDecisionDependencyError(
                    "ticket candidate set is stale or superseded"
                )
            if (
                candidate_set.set_kind != "judgment_bound"
                or candidate_set.comparison_only != 0
                or candidate.candidate_set_revision_id
                != candidate_set.candidate_set_revision_id
            ):
                raise ValueError("selection requires a judgment-bound candidate")
            if candidate.partition == "over_cap":
                raise ValueError("over-cap candidates cannot be selected")
            if candidate.partition not in {"eligible", "audit_blocked"}:
                raise ValueError("candidate partition cannot be selected")
            generation = uow.operator_decision.candidate_generation_request(
                candidate_set.generation_request_id
            )
            if generation is None:
                raise ValueError("candidate generation request does not exist")
            candidate_set_lineage = (
                candidate_set.task_family_id,
                candidate_set.work_item_id,
                candidate_set.task_snapshot_hash,
                candidate_set.slate_revision_id,
                candidate_set.market_prior_baseline_revision_id,
                candidate_set.baseline_envelope_revision_id,
                candidate_set.judgment_prescription_revision_id,
            )
            generation_lineage = (
                generation.task_family_id,
                generation.work_item_id,
                generation.task_snapshot_hash,
                generation.slate_revision_id,
                generation.market_prior_baseline_revision_id,
                generation.baseline_envelope_revision_id,
                generation.judgment_prescription_revision_id,
            )
            if candidate_set_lineage != generation_lineage:
                raise StaleOperatorDecisionDependencyError(
                    "candidate set crosses its generation lineage"
                )
            task_bundle, _items = self._current_bundle(
                uow,
                generation.task_evidence_bundle_revision_id,
            )
            _baseline, envelope = self._same_decision_lineage(
                uow,
                task_bundle,
                generation.work_item_id,
                generation.market_prior_baseline_revision_id,
                generation.baseline_envelope_revision_id,
            )
            prescription = uow.operator_decision.judgment_prescription_revision(
                generation.judgment_prescription_revision_id
            )
            if prescription is None:
                raise ValueError("candidate judgment prescription does not exist")
            current_prescription = (
                uow.operator_decision.current_judgment_prescription_revision(
                    prescription.judgment_prescription_family_id
                )
            )
            if (
                current_prescription is None
                or current_prescription.judgment_prescription_revision_id
                != prescription.judgment_prescription_revision_id
            ):
                raise StaleOperatorDecisionDependencyError(
                    "candidate judgment prescription is stale or superseded"
                )
            expected_prescription_lineage = (
                generation.task_family_id,
                generation.work_item_id,
                generation.task_snapshot_hash,
                generation.slate_revision_id,
                generation.task_evidence_bundle_revision_id,
                generation.market_prior_baseline_revision_id,
                generation.baseline_envelope_revision_id,
            )
            prescription_lineage = (
                prescription.task_family_id,
                prescription.work_item_id,
                prescription.task_snapshot_hash,
                prescription.slate_revision_id,
                prescription.task_evidence_bundle_revision_id,
                prescription.market_prior_baseline_revision_id,
                prescription.baseline_envelope_revision_id,
            )
            if prescription_lineage != expected_prescription_lineage:
                raise StaleOperatorDecisionDependencyError(
                    "candidate prescription crosses its generation lineage"
                )
            if not uow.operator_decision.action_is_committed(
                prescription.action_id,
                action_type="freeze_judgment_prescription",
            ):
                raise ValueError("candidate prescription Action is not committed")
            self._validate_fixed_prize_policy(
                uow,
                envelope.ticket_kind,
                generation.fixed_prize_policy_revision_id,
            )
            candidate_offer_ids = {
                leg.official_offer_revision_id
                for ticket in uow.operator_result.candidate_tickets(
                    candidate.candidate_revision_id
                )
                for leg in uow.operator_result.candidate_ticket_legs(
                    ticket.candidate_ticket_id
                )
            }
            self._require_open_offer_revisions(
                uow,
                candidate_set.slate_revision_id,
                candidate_offer_ids,
                request.requested_at,
            )
            current_slate = uow.operator_sale.current_slate(
                task_bundle.lane,
                task_bundle.business_key,
            )
            if (
                current_slate is None
                or current_slate.slate_revision_id != candidate_set.slate_revision_id
            ):
                raise StaleOperatorDecisionDependencyError(
                    "candidate slate is stale or superseded"
                )
            selection_family_id = _stable_id(
                "operator-candidate-selection-family",
                candidate_set.task_family_id,
                candidate_set.work_item_id,
            )
            current_selection = uow.operator_decision.current_candidate_selection(
                task_family_id=candidate_set.task_family_id,
                work_item_id=candidate_set.work_item_id,
            )
            _assert_expected_revision(
                expected=request.expected_current_revision_no,
                current_revision_no=(
                    0 if current_selection is None else current_selection.revision_no
                ),
                object_label="ticket candidate selection",
            )
            selection_document = {
                "candidate_set_revision_id": candidate_set.candidate_set_revision_id,
                "candidate_revision_id": candidate.candidate_revision_id,
                "task_family_id": candidate_set.task_family_id,
                "work_item_id": candidate_set.work_item_id,
                "task_snapshot_hash": candidate_set.task_snapshot_hash,
                "slate_revision_id": candidate_set.slate_revision_id,
                "task_evidence_bundle_revision_id": (
                    generation.task_evidence_bundle_revision_id
                ),
                "market_prior_baseline_revision_id": (
                    candidate_set.market_prior_baseline_revision_id
                ),
                "baseline_envelope_revision_id": (
                    candidate_set.baseline_envelope_revision_id
                ),
                "judgment_prescription_revision_id": (
                    candidate_set.judgment_prescription_revision_id
                ),
                "fixed_prize_policy_revision_id": (
                    generation.fixed_prize_policy_revision_id
                ),
                "reason": request.reason.strip(),
            }
            content_hash = _content_hash(selection_document)
            if (
                current_selection is not None
                and current_selection.content_hash == content_hash
            ):
                return (
                    ObjectRef(
                        "ticket_candidate_selection",
                        current_selection.candidate_selection_id,
                    ),
                )
            revision_no = (
                1 if current_selection is None else current_selection.revision_no + 1
            )
            selection_id = _stable_id(
                "operator-candidate-selection",
                selection_family_id,
                revision_no,
                content_hash,
            )
            uow.operator_decision.insert_candidate_selection(
                CandidateSelectionRow(
                    candidate_selection_id=selection_id,
                    candidate_selection_family_id=selection_family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=(
                        None
                        if current_selection is None
                        else current_selection.candidate_selection_id
                    ),
                    candidate_set_revision_id=candidate_set.candidate_set_revision_id,
                    candidate_revision_id=candidate.candidate_revision_id,
                    task_family_id=candidate_set.task_family_id,
                    work_item_id=candidate_set.work_item_id,
                    task_snapshot_hash=candidate_set.task_snapshot_hash,
                    slate_revision_id=candidate_set.slate_revision_id,
                    reason=request.reason.strip(),
                    content_hash=content_hash,
                    action_id=action_command.action_id,
                    selected_at=_utc(request.requested_at),
                )
            )
            return (ObjectRef("ticket_candidate_selection", selection_id),)

        return self._action_service.execute(command, handler)

    def record_baseline_envelope(
        self, request: RecordBaselineEnvelopeRequest
    ) -> ActionOutcome:
        self._validate_envelope_scalars(request)
        policy_version = self._bundle_policy(request.task_evidence_bundle_revision_id)
        command = ActionCommand.create(
            action_type="record_baseline_envelope",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            payload=self._envelope_document(request),
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            bundle, _items = self._current_bundle(
                uow, request.task_evidence_bundle_revision_id
            )
            self._validate_envelope_structure(uow, bundle, request)
            family_id = _stable_id(
                "baseline-envelope-family",
                bundle.task_family_id,
                request.work_item_id,
            )
            document = {
                **self._envelope_document(request),
                "task_snapshot_hash": bundle.task_snapshot_hash,
                "slate_revision_id": bundle.slate_revision_id,
            }
            content_hash = _content_hash(document)
            current = uow.operator_decision.current_baseline_envelope_revision(
                family_id
            )
            _assert_expected_revision(
                expected=request.expected_current_revision_no,
                current_revision_no=0 if current is None else current.revision_no,
                object_label="baseline envelope",
            )
            if current is not None and current.content_hash == content_hash:
                return (
                    ObjectRef(
                        "baseline_envelope_revision",
                        current.baseline_envelope_revision_id,
                    ),
                )
            revision_no = 1 if current is None else current.revision_no + 1
            revision_id = _stable_id(
                "baseline-envelope", family_id, revision_no, content_hash
            )
            uow.operator_decision.insert_baseline_envelope_revision(
                BaselineEnvelopeRevisionRow(
                    baseline_envelope_revision_id=revision_id,
                    baseline_envelope_family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=(
                        None if current is None else current.baseline_envelope_revision_id
                    ),
                    task_family_id=bundle.task_family_id,
                    work_item_id=request.work_item_id,
                    task_snapshot_hash=bundle.task_snapshot_hash,
                    slate_revision_id=bundle.slate_revision_id,
                    task_evidence_bundle_revision_id=(
                        bundle.task_evidence_bundle_revision_id
                    ),
                    ticket_kind=request.ticket_kind,
                    capital_cap_minor=request.capital_cap_minor,
                    currency=request.currency,
                    maximum_ticket_count=request.maximum_ticket_count,
                    maximum_exhaustive_candidate_count=(
                        request.maximum_exhaustive_candidate_count
                    ),
                    content_hash=content_hash,
                    action_id=action_command.action_id,
                    created_at=_utc(request.requested_at),
                )
            )
            self._insert_envelope_children(uow, revision_id, request)
            return (ObjectRef("baseline_envelope_revision", revision_id),)

        return self._action_service.execute(command, handler)

    def commit_operator_match_judgment(
        self, request: CommitOperatorMatchJudgmentRequest
    ) -> ActionOutcome:
        prior = self._probability_map(request.prior, "prior")
        belief = self._probability_map(request.belief, "belief")
        factors = self._factor_maps(request.factors)
        self._validate_probability_simplexes(prior, belief)
        self._validate_judgment_collections(request)
        policy_version = self._bundle_policy(request.task_evidence_bundle_revision_id)
        command = ActionCommand.create(
            action_type="commit_operator_match_judgment",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            expected_versions=(
                None
                if request.expected_current_revision_no is None
                else {
                    f"forecast:{request.match_id}:{request.market_definition_id}": (
                        request.expected_current_revision_no
                    )
                }
            ),
            payload=self._judgment_document(request, prior, belief, factors),
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            bundle, items = self._current_bundle(
                uow, request.task_evidence_bundle_revision_id
            )
            task_item = next(
                (item for item in items if item.match_id == request.match_id), None
            )
            if task_item is None:
                raise ValueError("judgment match is outside the task evidence bundle")
            baseline, envelope, baseline_rows, market_code = (
                self._validate_judgment_lineage(
                    uow,
                    bundle,
                    task_item,
                    request,
                    prior,
                )
            )
            self._validate_factor_reconstruction(prior, belief, factors)
            self._validate_judgment_refs(
                uow,
                bundle,
                task_item,
                envelope.baseline_envelope_revision_id,
                market_code,
                request,
                factors,
                set(prior),
            )
            family_id = _stable_id(
                "operator-match-judgment-family",
                bundle.task_family_id,
                request.work_item_id,
                request.match_id,
                request.market_definition_id,
            )
            current = uow.operator_decision.current_operator_match_judgment_revision(
                family_id
            )
            _assert_expected_revision(
                expected=request.expected_current_revision_no,
                current_revision_no=0 if current is None else current.revision_no,
                object_label="operator match judgment",
            )
            forecast_request = CommitForecastRequest(
                match_id=request.match_id,
                market_definition_id=request.market_definition_id,
                decision_session_id=None,
                prior_distribution={face: float(value) for face, value in prior.items()},
                belief_distribution={face: float(value) for face, value in belief.items()},
                factors=[
                    FactorInput(
                        factor_definition_id=factor.factor_definition_id,
                        delta={
                            face: float(offset)
                            for face, offset in factor_offsets.items()
                        },
                        scope_entity_ids=[factor.scope_key],
                        supporting_observation_ids=list(factor.evidence_ref_tokens),
                        note=None,
                    )
                    for factor, factor_offsets in factors
                ],
                commitment_tier=request.commitment_tier,
                evidence_bundle_id=task_item.evidence_bundle_id,
                prior_snapshot_id=str(baseline_rows[0]["market_snapshot_id"]),
                falsifier=request.falsifier,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f"{request.idempotency_key}:forecast-child",
                requested_at=request.requested_at,
                information_cutoff_at=bundle.information_cutoff_at,
                expected_current_revision_no=request.expected_current_revision_no,
            )
            forecast_ref = commit_forecast_in_uow(
                uow,
                forecast_request,
                policy_version=action_command.policy_version,
            )
            revision_no = 1 if current is None else current.revision_no + 1
            content_hash = _content_hash(
                self._judgment_document(request, prior, belief, factors)
            )
            revision_id = _stable_id(
                "operator-match-judgment", family_id, revision_no, content_hash
            )
            uow.operator_decision.insert_operator_match_judgment_revision(
                OperatorMatchJudgmentRevisionRow(
                    operator_match_judgment_revision_id=revision_id,
                    operator_match_judgment_family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=(
                        None
                        if current is None
                        else current.operator_match_judgment_revision_id
                    ),
                    task_family_id=bundle.task_family_id,
                    work_item_id=request.work_item_id,
                    task_snapshot_hash=bundle.task_snapshot_hash,
                    slate_revision_id=bundle.slate_revision_id,
                    task_evidence_bundle_revision_id=(
                        bundle.task_evidence_bundle_revision_id
                    ),
                    market_prior_baseline_revision_id=(
                        baseline.market_prior_baseline_revision_id
                    ),
                    baseline_envelope_revision_id=(
                        envelope.baseline_envelope_revision_id
                    ),
                    match_id=request.match_id,
                    official_offer_revision_id=request.official_offer_revision_id,
                    market_definition_id=request.market_definition_id,
                    forecast_revision_id=forecast_ref.object_id,
                    falsifier=request.falsifier.strip(),
                    rationale=request.rationale.strip(),
                    content_hash=content_hash,
                    action_id=action_command.action_id,
                    created_at=_utc(request.requested_at),
                )
            )
            self._insert_judgment_children(
                uow,
                revision_id,
                request,
                prior,
                belief,
                factors,
            )
            return (
                forecast_ref,
                ObjectRef("operator_match_judgment_revision", revision_id),
            )

        return self._action_service.execute(command, handler)

    def freeze_judgment_prescription(
        self, request: FreezeJudgmentPrescriptionRequest
    ) -> ActionOutcome:
        policy_version = self._bundle_policy(request.task_evidence_bundle_revision_id)
        command = ActionCommand.create(
            action_type="freeze_judgment_prescription",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            payload={
                "task_evidence_bundle_revision_id": (
                    request.task_evidence_bundle_revision_id
                ),
                "market_prior_baseline_revision_id": (
                    request.market_prior_baseline_revision_id
                ),
                "baseline_envelope_revision_id": (
                    request.baseline_envelope_revision_id
                ),
                "work_item_id": request.work_item_id,
                "judgment_revision_ids": list(request.judgment_revision_ids),
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            bundle, items = self._current_bundle(
                uow, request.task_evidence_bundle_revision_id
            )
            baseline, envelope = self._same_decision_lineage(
                uow,
                bundle,
                request.work_item_id,
                request.market_prior_baseline_revision_id,
                request.baseline_envelope_revision_id,
            )
            judgments = tuple(
                uow.operator_decision.operator_match_judgment_revision(revision_id)
                for revision_id in request.judgment_revision_ids
            )
            if any(judgment is None for judgment in judgments):
                raise ValueError("prescription references an unknown judgment")
            resolved = tuple(judgment for judgment in judgments if judgment is not None)
            required_matches = {item.match_id for item in items}
            if (
                len(resolved) != bundle.required_match_count
                or {judgment.match_id for judgment in resolved} != required_matches
            ):
                raise ValueError("prescription requires every required match judgment")
            for judgment in resolved:
                self._validate_current_prescription_judgment(
                    uow, bundle, baseline, envelope, request.work_item_id, judgment
                )
            family_id = _stable_id(
                "judgment-prescription-family",
                bundle.task_family_id,
                request.work_item_id,
            )
            document = {
                "task_evidence_bundle_revision_id": (
                    bundle.task_evidence_bundle_revision_id
                ),
                "market_prior_baseline_revision_id": (
                    baseline.market_prior_baseline_revision_id
                ),
                "baseline_envelope_revision_id": (
                    envelope.baseline_envelope_revision_id
                ),
                "judgment_revision_ids": sorted(request.judgment_revision_ids),
            }
            content_hash = _content_hash(document)
            current = uow.operator_decision.current_judgment_prescription_revision(
                family_id
            )
            _assert_expected_revision(
                expected=request.expected_current_revision_no,
                current_revision_no=0 if current is None else current.revision_no,
                object_label="judgment prescription",
            )
            if current is not None and current.content_hash == content_hash:
                return (
                    ObjectRef(
                        "judgment_prescription_revision",
                        current.judgment_prescription_revision_id,
                    ),
                )
            revision_no = 1 if current is None else current.revision_no + 1
            revision_id = _stable_id(
                "judgment-prescription", family_id, revision_no, content_hash
            )
            uow.operator_decision.insert_judgment_prescription_revision(
                JudgmentPrescriptionRevisionRow(
                    judgment_prescription_revision_id=revision_id,
                    judgment_prescription_family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=(
                        None
                        if current is None
                        else current.judgment_prescription_revision_id
                    ),
                    task_family_id=bundle.task_family_id,
                    work_item_id=request.work_item_id,
                    task_snapshot_hash=bundle.task_snapshot_hash,
                    slate_revision_id=bundle.slate_revision_id,
                    task_evidence_bundle_revision_id=(
                        bundle.task_evidence_bundle_revision_id
                    ),
                    market_prior_baseline_revision_id=(
                        baseline.market_prior_baseline_revision_id
                    ),
                    baseline_envelope_revision_id=(
                        envelope.baseline_envelope_revision_id
                    ),
                    required_match_count=bundle.required_match_count,
                    judgment_count=len(resolved),
                    content_hash=content_hash,
                    action_id=action_command.action_id,
                    created_at=_utc(request.requested_at),
                )
            )
            for index, judgment in enumerate(
                sorted(resolved, key=lambda item: item.match_id)
            ):
                uow.operator_decision.insert_judgment_prescription_item(
                    JudgmentPrescriptionItemRow(
                        operator_judgment_prescription_item_id=_stable_id(
                            "judgment-prescription-item",
                            revision_id,
                            judgment.match_id,
                        ),
                        judgment_prescription_revision_id=revision_id,
                        item_index=index,
                        match_id=judgment.match_id,
                        operator_match_judgment_revision_id=(
                            judgment.operator_match_judgment_revision_id
                        ),
                    )
                )
            return (ObjectRef("judgment_prescription_revision", revision_id),)

        return self._action_service.execute(command, handler)

    def committed_judgment_progress(
        self, task_evidence_bundle_revision_id: str
    ) -> tuple[int, int]:
        with self._action_service.unit_of_work() as uow:
            bundle = uow.operator_decision.task_evidence_bundle_revision(
                task_evidence_bundle_revision_id
            )
            if bundle is None:
                raise ValueError("task evidence bundle does not exist")
            return (
                uow.operator_decision.current_judgment_count(
                    task_evidence_bundle_revision_id
                ),
                bundle.required_match_count,
            )

    def _bundle_policy(self, revision_id: str) -> str:
        with self._action_service.unit_of_work() as uow:
            bundle = uow.operator_decision.task_evidence_bundle_revision(revision_id)
            if bundle is None:
                raise ValueError("task evidence bundle does not exist")
            return bundle.policy_version

    def _candidate_set_policy(self, candidate_set_revision_id: str) -> str:
        with self._action_service.unit_of_work() as uow:
            candidate_set = uow.operator_result.candidate_set_revision(
                candidate_set_revision_id
            )
            if candidate_set is None:
                raise ValueError("ticket candidate set does not exist")
            generation = uow.operator_decision.candidate_generation_request(
                candidate_set.generation_request_id
            )
            if generation is None:
                raise ValueError("candidate generation request does not exist")
            bundle = uow.operator_decision.task_evidence_bundle_revision(
                generation.task_evidence_bundle_revision_id
            )
            if bundle is None:
                raise ValueError("candidate evidence bundle does not exist")
            return bundle.policy_version

    @staticmethod
    def _validate_fixed_prize_policy(uow, ticket_kind: str, revision_id: str | None) -> None:
        if ticket_kind == "jczq_pass":
            if revision_id is not None:
                raise ValueError("JCZQ candidate generation cannot bind fixed-prize policy")
            return
        if ticket_kind not in {"sfc", "renjiu"} or revision_id is None:
            raise ValueError("Zucai candidate generation requires fixed-prize policy")
        policy = uow.operator_result.fixed_prize_policy_revision(revision_id)
        current = uow.operator_result.current_fixed_prize_policy(ticket_kind)
        if (
            policy is None
            or current is None
            or policy.fixed_prize_policy_revision_id
            != current.fixed_prize_policy_revision_id
            or policy.ticket_kind != ticket_kind
            or policy.currency != "CNY"
            or policy.standard_unit_stake_minor != 200
            or policy.official_void_rule != "all_faces_match"
        ):
            raise ValueError("fixed-prize policy is missing, stale, or incompatible")

    @staticmethod
    def _validate_baseline_quote_bindings(uow, baseline, baseline_rows) -> None:
        snapshot_quote_ids: dict[str, set[str]] = {}
        snapshots: dict[str, dict[str, object]] = {}
        for row in baseline_rows:
            quote = uow.market.quote(str(row["quote_id"]))
            if quote is None:
                raise ValueError("baseline Quote binding is unavailable")
            snapshot_id = str(row["market_snapshot_id"])
            if snapshot_id not in snapshot_quote_ids:
                snapshot_quote_ids[snapshot_id] = set(
                    uow.market.snapshot_quote_ids(snapshot_id)
                )
                snapshot = uow.operator_decision.market_snapshot(snapshot_id)
                if snapshot is None:
                    raise ValueError("baseline market snapshot is unavailable")
                snapshots[snapshot_id] = snapshot
            snapshot = snapshots[snapshot_id]
            outcome_key = uow.market.selection_outcome_key(quote.selection_id)
            face_code = _OUTCOME_FACE_CODES.get(str(outcome_key), str(outcome_key))
            current_odds = _decimal_text(
                _decimal_from_number(quote.decimal_odds, name="booked decimal odds")
            )
            current_line = (
                None
                if quote.settlement_parameter_decimal is None
                else _decimal_text(
                    _decimal_from_number(
                        quote.settlement_parameter_decimal,
                        name="settlement parameter",
                    )
                )
            )
            if (
                quote.match_id != row["match_id"]
                or quote.market_definition_id != row["market_definition_id"]
                or quote.quote_status != "active"
                or face_code != row["face_code"]
                or quote.quote_id not in snapshot_quote_ids[snapshot_id]
                or quote.captured_at != row["quote_captured_at"]
                or snapshot["match_id"] != row["match_id"]
                or snapshot["market_definition_id"]
                != row["market_definition_id"]
                or datetime.fromisoformat(quote.captured_at)
                > datetime.fromisoformat(baseline.information_cutoff_at)
                or current_odds != row["booked_decimal_odds"]
                or current_line != row["settlement_parameter_decimal"]
            ):
                raise ValueError("baseline Quote odds or settlement binding has drifted")

    @staticmethod
    def _require_open_offer_revisions(
        uow,
        slate_revision_id: str,
        revision_ids,
        receipt_time: datetime,
    ) -> None:
        requested_at = _aware(receipt_time, "receipt_time").astimezone(UTC)
        pending = set(revision_ids)
        if not pending:
            raise ValueError("candidate lineage contains no official offers")
        offers_by_id = {
            offer.official_offer_revision_id: offer
            for offer in uow.operator_sale.offer_revisions_for_slate(slate_revision_id)
        }
        if not pending <= set(offers_by_id):
            raise ValueError("candidate official offer does not exist in its slate")
        rows = [offers_by_id[revision_id] for revision_id in sorted(pending)]
        for offer in rows:
            current = uow.operator_sale.current_offer_by_family(
                offer.official_offer_family_id
            )
            opens_at = datetime.fromisoformat(offer.sale_opens_at).astimezone(UTC)
            deadline_at = datetime.fromisoformat(offer.sale_deadline_at).astimezone(UTC)
            if (
                current is None
                or current.official_offer_revision_id
                != offer.official_offer_revision_id
                or offer.status != "on_sale"
                or requested_at < opens_at
                or requested_at >= deadline_at
            ):
                raise StaleOperatorDecisionDependencyError(
                    "candidate official offer is closed, stale, or at its deadline"
                )

    @staticmethod
    def _current_bundle(uow, revision_id: str):
        bundle = uow.operator_decision.task_evidence_bundle_revision(revision_id)
        if bundle is None:
            raise ValueError("task evidence bundle does not exist")
        current = uow.operator_decision.latest_task_evidence_bundle_revision(
            bundle.task_family_id
        )
        if current is None or current.task_evidence_bundle_revision_id != revision_id:
            raise StaleOperatorDecisionDependencyError(
                "task evidence bundle is stale or superseded"
            )
        current_slate = uow.operator_sale.current_slate(bundle.lane, bundle.business_key)
        if (
            current_slate is None
            or current_slate.slate_revision_id != bundle.slate_revision_id
        ):
            raise StaleOperatorDecisionDependencyError(
                "task evidence bundle slate is stale"
            )
        if not uow.operator_decision.action_is_committed(
            bundle.link_action_id,
            action_type="link_operator_task_evidence_freeze",
        ):
            raise ValueError("task evidence bundle link Action is not committed")
        items = uow.operator_decision.task_evidence_bundle_items(revision_id)
        if (
            len(items) != bundle.item_count
            or bundle.item_count != bundle.required_match_count
        ):
            raise ValueError("task evidence bundle counts do not reconcile")
        for item in items:
            if not uow.operator_decision.action_is_committed(
                item.freeze_bundle_action_id,
                action_type="freeze_evidence_bundle",
            ):
                raise ValueError("match evidence bundle Action is not committed")
        offers_by_match: dict[str, list[object]] = {}
        for offer in uow.operator_sale.offer_revisions_for_slate(
            current_slate.slate_revision_id
        ):
            offers_by_match.setdefault(offer.match_id, []).append(offer)
        for item in items:
            matching_offers = offers_by_match.get(item.match_id, [])
            if len(matching_offers) != 1:
                raise ValueError("task evidence bundle has no unique current offer")
            offer = matching_offers[0]
            current_offer = uow.operator_sale.current_offer_by_family(
                offer.official_offer_family_id
            )
            if (
                offer.status != "on_sale"
                or current_offer is None
                or current_offer.official_offer_revision_id
                != offer.official_offer_revision_id
            ):
                raise StaleOperatorDecisionDependencyError(
                    "task evidence bundle offer is cancelled or stale"
                )
        return bundle, items

    @staticmethod
    def _require_worker_lease(uow, request, bundle) -> None:
        job = uow.operator_decision.worker_job(request.worker_job_id or "")
        if (
            job is None
            or job.job_kind != "market_baseline"
            or job.source_object_type != "task_evidence_bundle_revision"
            or job.source_object_id != bundle.task_evidence_bundle_revision_id
            or job.state != "leased"
            or job.lease_owner != request.lease_owner
            or job.lease_expires_at is None
            or datetime.fromisoformat(job.lease_expires_at) <= request.requested_at
        ):
            raise ValueError("market baseline job is not held by this worker lease")

    @staticmethod
    def _market_baseline_source_rows(uow, bundle, items):
        offers = uow.operator_sale.offer_revisions_for_slate(bundle.slate_revision_id)
        rows: list[dict[str, str]] = []
        for item in items:
            frozen = uow.operator_decision.freeze_bundle_for_action(
                item.freeze_bundle_action_id
            )
            if frozen is None or frozen.market_snapshot_id is None:
                raise OperatorEvidenceMissingError(
                    "market Snapshot is missing from frozen evidence"
                )
            snapshot = uow.operator_decision.market_snapshot(frozen.market_snapshot_id)
            if snapshot is None:
                raise OperatorEvidenceMissingError("market Snapshot does not exist")
            disagreement = json.loads(str(snapshot["disagreement_json"]))
            if disagreement.get("state") == "conflict" or disagreement.get("conflict"):
                raise OperatorEvidenceConflictError(
                    "market Snapshot has an unresolved conflict"
                )
            if (
                str(snapshot["match_id"]) != item.match_id
                or datetime.fromisoformat(str(snapshot["as_of"]))
                > datetime.fromisoformat(bundle.information_cutoff_at)
            ):
                raise ValueError("market Snapshot does not match the frozen cutoff")
            market_id = str(snapshot["market_definition_id"])
            fair = {
                _OUTCOME_FACE_CODES.get(str(face), str(face)): _decimal_from_number(
                    probability,
                    name="market probability",
                )
                for face, probability in json.loads(
                    str(snapshot["fair_distribution_json"])
                ).items()
            }
            frozen_prior = {
                _OUTCOME_FACE_CODES.get(str(face), str(face)): _decimal_from_number(
                    probability,
                    name="frozen prior probability",
                )
                for face, probability in frozen.prior_distribution.items()
            }
            if fair != frozen_prior or not fair or sum(fair.values()) != _ONE:
                raise ValueError("market prior differs from the frozen Snapshot")
            registered_faces = set(
                uow.operator_decision.market_face_codes(market_id)
            )
            if set(fair) != registered_faces:
                raise ValueError(
                    "market Snapshot does not contain the complete registered face set"
                )
            offer_matches = [
                offer
                for offer in offers
                if offer.match_id == item.match_id
                and market_id in offer.market_definition_ids
                and offer.status == "on_sale"
            ]
            if len(offer_matches) != 1:
                raise ValueError("market Snapshot has no exact official offer")
            quotes = uow.operator_decision.market_snapshot_quotes(
                frozen.market_snapshot_id
            )
            quote_by_face: dict[str, dict[str, object]] = {}
            for quote in quotes:
                face_code = _OUTCOME_FACE_CODES.get(
                    str(quote["outcome_key"]), str(quote["outcome_key"])
                )
                if (
                    quote["match_id"] != item.match_id
                    or quote["market_definition_id"] != market_id
                    or quote["quote_status"] != "active"
                    or datetime.fromisoformat(str(quote["captured_at"]))
                    > datetime.fromisoformat(bundle.information_cutoff_at)
                    or face_code in quote_by_face
                ):
                    raise ValueError("market Snapshot Quote lineage is conflicting")
                quote_by_face[face_code] = quote
            if set(quote_by_face) != set(fair):
                raise ValueError("market Snapshot is missing an exact Quote")
            quote_lines = {
                quote["settlement_parameter_decimal"]
                for quote in quote_by_face.values()
            }
            line_schema = uow.market.market_line_schema(market_id)
            if line_schema is None:
                if quote_lines != {None}:
                    raise ValueError(
                        "unlined market contains an unexpected settlement parameter"
                    )
            elif None in quote_lines or len(quote_lines) != 1:
                raise ValueError("lined market requires one exact signed line")
            if frozen.market_snapshot_id not in item.market_prior_ref_tokens:
                raise ValueError("market Snapshot is not anchored by the task freeze")
            for face_code in sorted(fair, key=_face_sort_key):
                rows.append(
                    {
                        "match_id": item.match_id,
                        "official_offer_revision_id": (
                            offer_matches[0].official_offer_revision_id
                        ),
                        "market_definition_id": market_id,
                        "face_code": face_code,
                        "probability_decimal": _decimal_text(fair[face_code]),
                        "market_snapshot_id": frozen.market_snapshot_id,
                        "quote_id": str(quote_by_face[face_code]["quote_id"]),
                        "booked_decimal_odds": _decimal_text(
                            _decimal_from_number(
                                quote_by_face[face_code]["decimal_odds"],
                                name="booked decimal odds",
                            )
                        ),
                        "quote_captured_at": str(
                            quote_by_face[face_code]["captured_at"]
                        ),
                        "settlement_parameter_decimal": (
                            None
                            if quote_by_face[face_code][
                                "settlement_parameter_decimal"
                            ]
                            is None
                            else _decimal_text(
                                _decimal_from_number(
                                    quote_by_face[face_code][
                                        "settlement_parameter_decimal"
                                    ],
                                    name="settlement parameter",
                                )
                            )
                        ),
                    }
                )
        return tuple(rows)

    @staticmethod
    def _validate_envelope_scalars(request: RecordBaselineEnvelopeRequest) -> None:
        for name in (
            "capital_cap_minor",
            "maximum_ticket_count",
            "maximum_exhaustive_candidate_count",
        ):
            value = getattr(request, name)
            minimum = 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}")
        if len(request.currency) != 3 or request.currency != request.currency.upper():
            raise ValueError("currency must be a three-letter uppercase code")
        if not request.offer_constraints or not request.structure_templates:
            raise ValueError("envelope constraints and structure templates are required")

    @staticmethod
    def _validate_envelope_structure(uow, bundle, request) -> None:
        offers = uow.operator_sale.offer_revisions_for_slate(bundle.slate_revision_id)
        offers_by_number = {offer.official_match_no: offer for offer in offers}
        constraint_keys = tuple(
            (item.official_match_no, item.market_code)
            for item in request.offer_constraints
        )
        if len(set(constraint_keys)) != len(constraint_keys):
            raise ValueError("offer and market constraints must be unique")
        constrained_numbers = {number for number, _market in constraint_keys}
        for constraint in request.offer_constraints:
            _required(constraint.official_match_no, "official_match_no")
            _required(constraint.market_code, "market_code")
            if not isinstance(constraint.omission_allowed, bool):
                raise ValueError("omission_allowed must be boolean")
            offer = offers_by_number.get(constraint.official_match_no)
            if offer is None:
                raise ValueError("envelope references an unknown official offer")
            matching_market_ids = tuple(
                market_id
                for market_id in offer.market_definition_ids
                if uow.market.market_kind(market_id) == constraint.market_code
            )
            if len(matching_market_ids) != 1:
                raise ValueError("envelope references an unknown or ambiguous market")
            allowed_faces = set(
                uow.operator_decision.market_face_codes(matching_market_ids[0])
            )
            bundle_codes = tuple(
                bundle_input.bundle_code
                for bundle_input in constraint.allowed_face_bundles
            )
            _unique(bundle_codes, "face bundle codes")
            for bundle_input in constraint.allowed_face_bundles:
                _unique(bundle_input.face_codes, "face codes")
                if not set(bundle_input.face_codes) <= allowed_faces:
                    raise ValueError("face bundle contains an unknown face")
        template_codes = tuple(
            template.structure_code for template in request.structure_templates
        )
        _unique(template_codes, "structure template codes")
        for template in request.structure_templates:
            _unique(
                template.eligible_official_match_nos,
                "eligible official match numbers",
            )
            if not set(template.eligible_official_match_nos) <= constrained_numbers:
                raise ValueError("structure template references an unconstrained offer")
            if (
                isinstance(template.required_offer_count, bool)
                or template.required_offer_count < 1
                or isinstance(template.maximum_groups, bool)
                or template.maximum_groups < 1
                or template.required_offer_count
                > len(template.eligible_official_match_nos)
            ):
                raise ValueError("structure template counts are invalid")
        if bundle.lane == "jczq":
            if request.ticket_kind != "jczq_pass":
                raise ValueError("JCZQ requires the jczq_pass ticket kind")
            for template in request.structure_templates:
                if (
                    template.kind != "jczq_pass"
                    or template.pass_size is None
                    or template.pass_size != template.required_offer_count
                ):
                    raise ValueError("JCZQ pass template is invalid")
        elif bundle.lane == "zucai":
            if request.ticket_kind not in {"sfc", "renjiu"}:
                raise ValueError("Zucai ticket kind must be sfc or renjiu")
            if len(offers) != 14 or constrained_numbers != set(offers_by_number):
                raise ValueError("Zucai envelope must constrain all fourteen offers")
            required = 14 if request.ticket_kind == "sfc" else 9
            for template in request.structure_templates:
                if (
                    template.kind != "zucai_group"
                    or template.pass_size is not None
                    or template.required_offer_count != required
                ):
                    raise ValueError("Zucai group template is invalid")
            if request.ticket_kind == "sfc" and any(
                constraint.omission_allowed
                for constraint in request.offer_constraints
            ):
                raise ValueError("SFC does not allow omitted offers")
        else:
            raise ValueError("unknown operator lane")

    @staticmethod
    def _envelope_document(request: RecordBaselineEnvelopeRequest) -> dict[str, object]:
        return {
            "task_evidence_bundle_revision_id": (
                request.task_evidence_bundle_revision_id
            ),
            "work_item_id": request.work_item_id,
            "ticket_kind": request.ticket_kind,
            "capital_cap_minor": request.capital_cap_minor,
            "currency": request.currency,
            "maximum_ticket_count": request.maximum_ticket_count,
            "maximum_exhaustive_candidate_count": (
                request.maximum_exhaustive_candidate_count
            ),
            "offer_constraints": [
                {
                    "official_match_no": constraint.official_match_no,
                    "market_code": constraint.market_code,
                    "omission_allowed": constraint.omission_allowed,
                    "allowed_face_bundles": [
                        {
                            "bundle_code": bundle.bundle_code,
                            "face_codes": list(bundle.face_codes),
                        }
                        for bundle in constraint.allowed_face_bundles
                    ],
                }
                for constraint in request.offer_constraints
            ],
            "structure_templates": [
                {
                    "kind": template.kind,
                    "structure_code": template.structure_code,
                    "eligible_official_match_nos": list(
                        template.eligible_official_match_nos
                    ),
                    "pass_size": template.pass_size,
                    "required_offer_count": template.required_offer_count,
                    "maximum_groups": template.maximum_groups,
                }
                for template in request.structure_templates
            ],
        }

    @staticmethod
    def _insert_envelope_children(uow, revision_id: str, request) -> None:
        for constraint_index, constraint in enumerate(request.offer_constraints):
            constraint_id = _stable_id(
                "baseline-envelope-constraint",
                revision_id,
                constraint.official_match_no,
                constraint.market_code,
            )
            uow.operator_decision.insert_baseline_envelope_offer_constraint(
                BaselineEnvelopeOfferConstraintRow(
                    baseline_envelope_offer_constraint_id=constraint_id,
                    baseline_envelope_revision_id=revision_id,
                    constraint_index=constraint_index,
                    official_match_no=constraint.official_match_no,
                    market_code=constraint.market_code,
                    omission_allowed=int(constraint.omission_allowed),
                )
            )
            for bundle_index, bundle in enumerate(constraint.allowed_face_bundles):
                bundle_id = _stable_id(
                    "baseline-envelope-bundle",
                    constraint_id,
                    bundle.bundle_code,
                )
                uow.operator_decision.insert_baseline_envelope_face_bundle(
                    BaselineEnvelopeFaceBundleRow(
                        baseline_envelope_face_bundle_id=bundle_id,
                        baseline_envelope_offer_constraint_id=constraint_id,
                        bundle_index=bundle_index,
                        bundle_code=bundle.bundle_code,
                    )
                )
                for face_index, face_code in enumerate(bundle.face_codes):
                    uow.operator_decision.insert_baseline_envelope_bundle_face(
                        BaselineEnvelopeBundleFaceRow(
                            baseline_envelope_bundle_face_id=_stable_id(
                                "baseline-envelope-face",
                                bundle_id,
                                face_code,
                            ),
                            baseline_envelope_face_bundle_id=bundle_id,
                            face_index=face_index,
                            face_code=face_code,
                        )
                    )
        for template_index, template in enumerate(request.structure_templates):
            template_id = _stable_id(
                "baseline-envelope-template",
                revision_id,
                template.structure_code,
            )
            uow.operator_decision.insert_baseline_envelope_structure_template(
                BaselineEnvelopeStructureTemplateRow(
                    baseline_envelope_structure_template_id=template_id,
                    baseline_envelope_revision_id=revision_id,
                    template_index=template_index,
                    kind=template.kind,
                    structure_code=template.structure_code,
                    pass_size=template.pass_size,
                    required_offer_count=template.required_offer_count,
                    maximum_groups=template.maximum_groups,
                )
            )
            for offer_index, match_no in enumerate(
                template.eligible_official_match_nos
            ):
                uow.operator_decision.insert_baseline_envelope_template_offer(
                    BaselineEnvelopeTemplateOfferRow(
                        baseline_envelope_template_offer_id=_stable_id(
                            "baseline-envelope-template-offer",
                            template_id,
                            match_no,
                        ),
                        baseline_envelope_structure_template_id=template_id,
                        offer_index=offer_index,
                        official_match_no=match_no,
                    )
                )

    @staticmethod
    def _probability_map(
        values: tuple[FaceProbabilityInput, ...], name: str
    ) -> dict[str, Decimal]:
        if not values:
            raise ValueError(f"{name} probabilities are required")
        faces = tuple(value.face_code for value in values)
        _unique(faces, f"{name} face codes")
        return {
            value.face_code: _decimal(
                value.probability_decimal,
                name=f"{name} probability",
                probability=True,
            )
            for value in values
        }

    @staticmethod
    def _factor_maps(
        factors: tuple[FactorAdjustmentInput, ...]
    ) -> tuple[tuple[FactorAdjustmentInput, dict[str, Decimal]], ...]:
        keys = tuple(
            f"{factor.factor_definition_id}:{factor.scope_key}"
            for factor in factors
        )
        _unique(keys, "Factor scope keys", required=False)
        normalized = []
        for factor in factors:
            _required(factor.factor_definition_id, "factor_definition_id")
            _required(factor.scope_key, "scope_key")
            _unique(factor.evidence_ref_tokens, "Factor evidence refs")
            if not factor.offsets:
                raise ValueError("Factor offsets are required")
            face_codes = tuple(offset.face_code for offset in factor.offsets)
            _unique(face_codes, "Factor offset face codes")
            normalized.append(
                (
                    factor,
                    {
                        offset.face_code: _decimal(
                            offset.offset_probability_decimal,
                            name="Factor offset",
                            probability=False,
                        )
                        for offset in factor.offsets
                    },
                )
            )
        return tuple(normalized)

    @staticmethod
    def _validate_probability_simplexes(prior, belief) -> None:
        if set(prior) != set(belief):
            raise ValueError("prior and belief face sets must match")
        if sum(prior.values()) != _ONE:
            raise ValueError("prior probabilities must sum exactly to one")
        if sum(belief.values()) != _ONE:
            raise ValueError("belief probabilities must sum exactly to one")

    @staticmethod
    def _validate_factor_reconstruction(prior, belief, factors) -> None:
        deltas = {face: belief[face] - prior[face] for face in prior}
        if any(delta != _ZERO for delta in deltas.values()) and not factors:
            raise ValueError("non-zero belief delta requires a named Factor")
        for _factor, offsets in factors:
            if set(offsets) != set(prior):
                raise ValueError("Factor offsets must cover every face")
            if sum(offsets.values()) != _ZERO:
                raise ValueError("Factor offsets must sum exactly to zero")
        for face, delta in deltas.items():
            reconstructed = sum(
                (offsets[face] for _factor, offsets in factors),
                start=_ZERO,
            )
            if reconstructed != delta:
                raise ValueError("Factor offsets must reconstruct belief exactly")

    @staticmethod
    def _validate_judgment_collections(request) -> None:
        _unique(request.rule_ids, "Rule IDs")
        unknown_rules = set(request.rule_ids) - DEVIATION_RULE_IDS
        if unknown_rules:
            raise ValueError(f"unknown Rule ID: {sorted(unknown_rules)[0]}")
        _unique(request.evidence_ref_tokens, "judgment evidence refs")
        if not request.expression_bundles:
            raise ValueError("expression face bundles are required")
        bundle_codes = tuple(bundle.bundle_code for bundle in request.expression_bundles)
        _unique(bundle_codes, "expression bundle codes")
        for bundle in request.expression_bundles:
            _unique(bundle.face_codes, "expression face codes")

    @staticmethod
    def _judgment_document(request, prior, belief, factors) -> dict[str, object]:
        return {
            "task_evidence_bundle_revision_id": (
                request.task_evidence_bundle_revision_id
            ),
            "market_prior_baseline_revision_id": (
                request.market_prior_baseline_revision_id
            ),
            "baseline_envelope_revision_id": (
                request.baseline_envelope_revision_id
            ),
            "work_item_id": request.work_item_id,
            "match_id": request.match_id,
            "official_offer_revision_id": request.official_offer_revision_id,
            "market_definition_id": request.market_definition_id,
            "prior": [
                {
                    "face_code": face,
                    "probability_decimal": _decimal_text(prior[face]),
                }
                for face in prior
            ],
            "belief": [
                {
                    "face_code": face,
                    "probability_decimal": _decimal_text(belief[face]),
                }
                for face in belief
            ],
            "factors": [
                {
                    "factor_definition_id": factor.factor_definition_id,
                    "scope_key": factor.scope_key,
                    "evidence_ref_tokens": list(factor.evidence_ref_tokens),
                    "offsets": [
                        {
                            "face_code": face,
                            "offset_probability_decimal": _decimal_text(offsets[face]),
                        }
                        for face in offsets
                    ],
                }
                for factor, offsets in factors
            ],
            "expression_bundles": [
                {
                    "bundle_code": bundle.bundle_code,
                    "face_codes": list(bundle.face_codes),
                }
                for bundle in request.expression_bundles
            ],
            "rule_ids": list(request.rule_ids),
            "evidence_ref_tokens": list(request.evidence_ref_tokens),
            "falsifier": request.falsifier.strip(),
            "rationale": request.rationale.strip(),
            "commitment_tier": request.commitment_tier,
        }

    @staticmethod
    def _same_decision_lineage(
        uow,
        bundle,
        work_item_id: str,
        baseline_revision_id: str,
        envelope_revision_id: str,
    ):
        baseline = uow.operator_decision.market_prior_baseline_revision(
            baseline_revision_id
        )
        envelope = uow.operator_decision.baseline_envelope_revision(
            envelope_revision_id
        )
        if baseline is None:
            raise ValueError("market prior baseline does not exist")
        if envelope is None:
            raise ValueError("baseline envelope does not exist")
        expected = (
            bundle.task_family_id,
            work_item_id,
            bundle.task_snapshot_hash,
            bundle.slate_revision_id,
            bundle.task_evidence_bundle_revision_id,
        )
        if (
            (
                baseline.task_family_id,
                baseline.work_item_id,
                baseline.task_snapshot_hash,
                baseline.slate_revision_id,
                baseline.task_evidence_bundle_revision_id,
            )
            != expected
            or (
                envelope.task_family_id,
                envelope.work_item_id,
                envelope.task_snapshot_hash,
                envelope.slate_revision_id,
                envelope.task_evidence_bundle_revision_id,
            )
            != expected
        ):
            raise ValueError("decision lineage crosses a task or work item")
        current_baseline = (
            uow.operator_decision.current_market_prior_baseline_revision(
                baseline.market_prior_baseline_family_id
            )
        )
        current_envelope = uow.operator_decision.current_baseline_envelope_revision(
            envelope.baseline_envelope_family_id
        )
        if (
            current_baseline is None
            or current_baseline.market_prior_baseline_revision_id
            != baseline.market_prior_baseline_revision_id
            or current_envelope is None
            or current_envelope.baseline_envelope_revision_id
            != envelope.baseline_envelope_revision_id
        ):
            raise StaleOperatorDecisionDependencyError(
                "decision lineage contains a stale dependency"
            )
        return baseline, envelope

    @classmethod
    def _validate_judgment_lineage(
        cls,
        uow,
        bundle,
        task_item,
        request,
        prior,
    ):
        baseline, envelope = cls._same_decision_lineage(
            uow,
            bundle,
            request.work_item_id,
            request.market_prior_baseline_revision_id,
            request.baseline_envelope_revision_id,
        )
        offers = uow.operator_sale.offer_revisions_for_slate(bundle.slate_revision_id)
        offer = next(
            (
                item
                for item in offers
                if item.official_offer_revision_id
                == request.official_offer_revision_id
            ),
            None,
        )
        if (
            offer is None
            or offer.match_id != request.match_id
            or request.market_definition_id not in offer.market_definition_ids
        ):
            raise ValueError("judgment references an unknown official offer or market")
        market_code = uow.market.market_kind(request.market_definition_id)
        if market_code is None:
            raise ValueError("judgment references an unknown market")
        baseline_rows = tuple(
            row
            for row in uow.operator_decision.market_prior_baseline_probabilities(
                baseline.market_prior_baseline_revision_id
            )
            if row["match_id"] == request.match_id
            and row["official_offer_revision_id"]
            == request.official_offer_revision_id
            and row["market_definition_id"] == request.market_definition_id
        )
        baseline_prior = {
            str(row["face_code"]): _decimal(
                str(row["probability_decimal"]),
                name="baseline probability",
                probability=True,
            )
            for row in baseline_rows
        }
        if not baseline_rows or baseline_prior != prior:
            raise ValueError("judgment prior must equal the exact market baseline prior")
        if task_item.match_id != request.match_id:
            raise ValueError("judgment task item does not match")
        return baseline, envelope, baseline_rows, market_code

    @staticmethod
    def _validate_judgment_refs(
        uow,
        bundle,
        task_item,
        envelope_revision_id: str,
        market_code: str,
        request,
        factors,
        allowed_faces: set[str],
    ) -> None:
        frozen = uow.operator_decision.freeze_bundle_for_action(
            task_item.freeze_bundle_action_id
        )
        if frozen is None:
            raise ValueError("judgment evidence bundle is unavailable")
        allowed_evidence = {
            *task_item.requirement_ref_tokens,
            *task_item.market_prior_ref_tokens,
            *task_item.conflicts_cleared_ref_tokens,
            *frozen.evidence_ref_tokens,
        }
        if not set(request.evidence_ref_tokens) <= allowed_evidence:
            raise ValueError("judgment evidence anchor is outside the frozen bundle")
        for factor, _offsets in factors:
            definition = uow.decision.factor_definition(factor.factor_definition_id)
            if definition is None or definition.status == "retired":
                raise ValueError("unknown or inactive Factor definition")
            if definition.scope not in {"match", "pairing", "team", "league"}:
                raise ValueError("Factor definition has an unsupported scope")
            if (
                definition.scope in {"match", "pairing"}
                and factor.scope_key != request.match_id
            ):
                raise ValueError("Factor scope does not match the judgment match")
            if not set(factor.evidence_ref_tokens) <= allowed_evidence:
                raise ValueError("Factor evidence anchor is outside the frozen bundle")
            valid_from = datetime.fromisoformat(definition.valid_from)
            valid_to = (
                None
                if definition.valid_to is None
                else datetime.fromisoformat(definition.valid_to)
            )
            if (
                definition.policy_version != bundle.policy_version
                or valid_from > request.requested_at
                or (valid_to is not None and valid_to <= request.requested_at)
            ):
                raise ValueError("Factor definition is stale for this judgment")
        allowed_bundles = uow.operator_decision.baseline_envelope_allowed_bundles(
            envelope_revision_id,
            official_match_no=next(
                offer.official_match_no
                for offer in uow.operator_sale.offer_revisions_for_slate(
                    bundle.slate_revision_id
                )
                if offer.official_offer_revision_id
                == request.official_offer_revision_id
            ),
            market_code=market_code,
        )
        if not allowed_bundles:
            raise ValueError("judgment market is absent from the baseline envelope")
        for expression in request.expression_bundles:
            if not set(expression.face_codes) <= allowed_faces:
                raise ValueError("expression contains an unknown face")
            if allowed_bundles.get(expression.bundle_code) != expression.face_codes:
                raise ValueError("expression bundle is not allowed by the envelope")

    @staticmethod
    def _insert_judgment_children(
        uow,
        revision_id: str,
        request,
        prior,
        belief,
        factors,
    ) -> None:
        probabilities = tuple(
            {
                "operator_match_judgment_probability_id": _stable_id(
                    "judgment-probability", revision_id, face
                ),
                "operator_match_judgment_revision_id": revision_id,
                "face_index": index,
                "face_code": face,
                "prior_probability_decimal": _decimal_text(prior[face]),
                "belief_probability_decimal": _decimal_text(belief[face]),
                "delta_probability_decimal": _decimal_text(
                    belief[face] - prior[face]
                ),
            }
            for index, face in enumerate(prior)
        )
        factor_adjustments: list[dict[str, object]] = []
        factor_offsets: list[dict[str, object]] = []
        factor_evidence_refs: list[dict[str, object]] = []
        for factor_index, (factor, offsets) in enumerate(factors):
            adjustment_id = _stable_id(
                "judgment-factor",
                revision_id,
                factor.factor_definition_id,
                factor.scope_key,
            )
            factor_adjustments.append(
                {
                    "operator_match_judgment_factor_adjustment_id": adjustment_id,
                    "operator_match_judgment_revision_id": revision_id,
                    "factor_index": factor_index,
                    "factor_definition_id": factor.factor_definition_id,
                    "scope_entity_id": factor.scope_key,
                }
            )
            factor_offsets.extend(
                {
                    "operator_match_judgment_factor_offset_id": _stable_id(
                        "judgment-factor-offset", adjustment_id, face
                    ),
                    "operator_match_judgment_factor_adjustment_id": adjustment_id,
                    "face_index": face_index,
                    "face_code": face,
                    "offset_probability_decimal": _decimal_text(offsets[face]),
                }
                for face_index, face in enumerate(offsets)
            )
            factor_evidence_refs.extend(
                {
                    "operator_match_judgment_factor_evidence_ref_id": _stable_id(
                        "judgment-factor-evidence", adjustment_id, evidence_ref
                    ),
                    "operator_match_judgment_factor_adjustment_id": adjustment_id,
                    "evidence_index": evidence_index,
                    "evidence_ref_token": evidence_ref,
                }
                for evidence_index, evidence_ref in enumerate(
                    factor.evidence_ref_tokens
                )
            )
        face_bundles: list[dict[str, object]] = []
        bundle_faces: list[dict[str, object]] = []
        for bundle_index, bundle in enumerate(request.expression_bundles):
            bundle_id = _stable_id(
                "judgment-face-bundle", revision_id, bundle.bundle_code
            )
            face_bundles.append(
                {
                    "operator_match_judgment_face_bundle_id": bundle_id,
                    "operator_match_judgment_revision_id": revision_id,
                    "bundle_index": bundle_index,
                    "bundle_code": bundle.bundle_code,
                }
            )
            bundle_faces.extend(
                {
                    "operator_match_judgment_bundle_face_id": _stable_id(
                        "judgment-bundle-face", bundle_id, face
                    ),
                    "operator_match_judgment_face_bundle_id": bundle_id,
                    "face_index": face_index,
                    "face_code": face,
                }
                for face_index, face in enumerate(bundle.face_codes)
            )
        rule_refs = tuple(
            {
                "operator_match_judgment_rule_ref_id": _stable_id(
                    "judgment-rule", revision_id, rule_id
                ),
                "operator_match_judgment_revision_id": revision_id,
                "rule_index": index,
                "rule_id": rule_id,
            }
            for index, rule_id in enumerate(request.rule_ids)
        )
        evidence_refs = tuple(
            {
                "operator_match_judgment_evidence_ref_id": _stable_id(
                    "judgment-evidence", revision_id, evidence_ref
                ),
                "operator_match_judgment_revision_id": revision_id,
                "evidence_index": index,
                "evidence_ref_token": evidence_ref,
            }
            for index, evidence_ref in enumerate(request.evidence_ref_tokens)
        )
        uow.operator_decision.insert_operator_match_judgment_children(
            probabilities=probabilities,
            factor_adjustments=tuple(factor_adjustments),
            factor_offsets=tuple(factor_offsets),
            factor_evidence_refs=tuple(factor_evidence_refs),
            face_bundles=tuple(face_bundles),
            bundle_faces=tuple(bundle_faces),
            rule_refs=rule_refs,
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _validate_current_prescription_judgment(
        uow,
        bundle,
        baseline,
        envelope,
        work_item_id: str,
        judgment,
    ) -> None:
        if (
            judgment.task_family_id != bundle.task_family_id
            or judgment.work_item_id != work_item_id
            or judgment.task_snapshot_hash != bundle.task_snapshot_hash
            or judgment.slate_revision_id != bundle.slate_revision_id
            or judgment.task_evidence_bundle_revision_id
            != bundle.task_evidence_bundle_revision_id
            or judgment.market_prior_baseline_revision_id
            != baseline.market_prior_baseline_revision_id
            or judgment.baseline_envelope_revision_id
            != envelope.baseline_envelope_revision_id
        ):
            raise ValueError("prescription judgment lineage is stale or cross-task")
        current = uow.operator_decision.current_operator_match_judgment_revision(
            judgment.operator_match_judgment_family_id
        )
        if (
            current is None
            or current.operator_match_judgment_revision_id
            != judgment.operator_match_judgment_revision_id
        ):
            raise ValueError("prescription requires current judgments")
        series_id = uow.decision.ensure_series(
            judgment.match_id, judgment.market_definition_id
        )
        current_forecast = uow.decision.current_committed_revision(series_id)
        if (
            current_forecast is None
            or current_forecast.forecast_revision_id != judgment.forecast_revision_id
        ):
            raise ValueError("prescription requires current committed Forecasts")


def _face_sort_key(face_code: str) -> tuple[int, str]:
    preferred = {"3": 0, "1": 1, "0": 2}
    return preferred.get(face_code, 3), face_code


__all__ = [
    "BaselineEnvelopeOfferConstraint",
    "BaselineEnvelopeStructureTemplate",
    "CommitOperatorMatchJudgmentRequest",
    "FaceBundleInput",
    "FaceOffsetInput",
    "FaceProbabilityInput",
    "FactorAdjustmentInput",
    "FreezeJudgmentPrescriptionRequest",
    "FreezeMarketPriorBaselineRequest",
    "OperatorDecisionActions",
    "RecordBaselineEnvelopeRequest",
    "RequestCandidateGenerationRequest",
    "SelectTicketCandidateRequest",
]
