"""Typed Actions for deterministic candidate sets and fixed-prize policy."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import select

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
    CandidateAuditFindingRow,
    CandidateDeadFaceRow,
    CandidateMetricRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.repository import schema_market

_DECIMAL_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal("0.000000000000")
_AUDIT_KINDS = frozenset({"legs", "prescription_difference", "budget", "deployment"})
_SET_KINDS = frozenset({"judgment_bound", "conditional_market_counterfactual"})
_PARTITIONS = frozenset({"eligible", "audit_blocked", "over_cap"})
_FACE_TO_OUTCOME = {"3": "home", "1": "draw", "0": "away"}
_POLICY_TIERS = {
    "sfc": (("sfc_first", 14), ("sfc_second", 13)),
    "renjiu": (("renjiu_first", 9),),
}


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc(value: datetime) -> str:
    return _aware(value, "datetime").astimezone(UTC).isoformat()


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def _content_hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _decimal(
    value: str,
    *,
    name: str,
    probability: bool = False,
    allow_negative: bool = False,
) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a canonical decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a canonical decimal string") from error
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    quantized = number.quantize(_DECIMAL_QUANTUM, rounding=ROUND_HALF_EVEN)
    if format(quantized, ".12f") != value:
        raise ValueError(f"{name} must have exactly twelve decimal places")
    if (not allow_negative and number < _ZERO) or (
        probability and number > Decimal("1")
    ):
        raise ValueError(f"{name} is outside its allowed range")
    return quantized


def _revision(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_current_revision_no must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class CandidateTicketLegInput:
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    quote_id: str | None
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None


@dataclass(frozen=True, slots=True)
class CandidateTicketInput:
    ticket_kind: Literal["jczq_pass", "sfc", "renjiu"]
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    composition_hash: str
    fixed_prize_policy_revision_id: str | None
    legs: tuple[CandidateTicketLegInput, ...]


@dataclass(frozen=True, slots=True)
class CandidateMetricsInput:
    currency: str
    ticket_count: int
    distinct_note_count: int
    paid_note_unit_count: int
    stake_minor: int
    capital_utilization_decimal: str
    probability_kind: Literal["all_required_legs", "any_ticket_all_required_legs"]
    objective_probability_decimal: str
    expected_broken_legs_decimal: str
    break_even_bonus_minor: int | None
    break_even_to_official_median_decimal: str | None


@dataclass(frozen=True, slots=True)
class CandidateDeadFaceInput:
    official_match_no: str
    face_code: str


@dataclass(frozen=True, slots=True)
class CandidateAuditFindingInput:
    finding_id: str
    audit_kind: Literal["legs", "prescription_difference", "budget", "deployment"]
    code: str
    severity: Literal["WARN", "ERROR"]
    message: str
    official_match_no: str | None
    rule_id: str | None


@dataclass(frozen=True, slots=True)
class TicketCandidateInput:
    partition: Literal["eligible", "audit_blocked", "over_cap"]
    rank: int | None
    deployable: bool
    tickets: tuple[CandidateTicketInput, ...]
    metrics: CandidateMetricsInput
    common_dead_faces: tuple[CandidateDeadFaceInput, ...]
    audit_findings: tuple[CandidateAuditFindingInput, ...]
    completed_audit_kinds: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class CandidateSetInput:
    set_kind: Literal["judgment_bound", "conditional_market_counterfactual"]
    candidates: tuple[TicketCandidateInput, ...]


@dataclass(frozen=True, slots=True)
class RegisterZucaiFixedPrizePolicyRequest:
    ticket_kind: Literal["sfc", "renjiu"]
    policy_version: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_revision_no: int | None

    def __post_init__(self) -> None:
        if self.ticket_kind not in _POLICY_TIERS:
            raise ValueError("ticket_kind must be sfc or renjiu")
        for name in ("policy_version", "actor_id", "idempotency_key"):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")
        _revision(self.expected_current_revision_no)


@dataclass(frozen=True, slots=True)
class GenerateTicketCandidateSetRequest:
    generation_request_id: str
    candidate_sets: tuple[CandidateSetInput, ...]
    generator_version: str
    worker_job_id: str
    lease_owner: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "generation_request_id",
            "generator_version",
            "worker_job_id",
            "lease_owner",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")


class OperatorResultActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def register_zucai_fixed_prize_policy(
        self,
        request: RegisterZucaiFixedPrizePolicyRequest,
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="register_zucai_fixed_prize_policy",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "ticket_kind": request.ticket_kind,
                "policy_version": request.policy_version,
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            current = uow.operator_result.current_fixed_prize_policy(
                request.ticket_kind
            )
            current_revision = 0 if current is None else current.revision_no
            if _revision(request.expected_current_revision_no) != current_revision:
                raise OptimisticConcurrencyError(
                    "fixed-prize policy revision changed before registration"
                )
            family_id = _stable_id("zucai-fixed-policy-family", request.ticket_kind)
            tiers = _POLICY_TIERS[request.ticket_kind]
            document = {
                "ticket_kind": request.ticket_kind,
                "policy_version": request.policy_version,
                "currency": "CNY",
                "standard_unit_stake_minor": 200,
                "official_void_rule": "all_faces_match",
                "tiers": tiers,
            }
            content_hash = _content_hash(document)
            if current is not None and current.content_hash == content_hash:
                return (
                    ObjectRef(
                        "zucai_fixed_prize_policy_revision",
                        current.fixed_prize_policy_revision_id,
                    ),
                )
            revision_no = current_revision + 1
            revision_id = _stable_id(
                "zucai-fixed-policy", family_id, revision_no, content_hash
            )
            uow.operator_result.insert_fixed_prize_policy_revision(
                ZucaiFixedPrizePolicyRevisionRow(
                    fixed_prize_policy_revision_id=revision_id,
                    fixed_prize_policy_family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=(
                        None
                        if current is None
                        else current.fixed_prize_policy_revision_id
                    ),
                    policy_version=request.policy_version,
                    ticket_kind=request.ticket_kind,
                    currency="CNY",
                    standard_unit_stake_minor=200,
                    official_void_rule="all_faces_match",
                    effective_at=_utc(request.requested_at),
                    content_hash=content_hash,
                    action_id=action_command.action_id,
                    created_at=_utc(request.requested_at),
                )
            )
            for index, (tier_code, required_correct_count) in enumerate(tiers):
                uow.operator_result.insert_fixed_prize_policy_tier(
                    ZucaiFixedPrizePolicyTierRow(
                        fixed_prize_policy_tier_id=_stable_id(
                            "zucai-fixed-policy-tier", revision_id, tier_code
                        ),
                        fixed_prize_policy_revision_id=revision_id,
                        tier_index=index,
                        tier_code=tier_code,
                        required_correct_count=required_correct_count,
                    )
                )
            return (ObjectRef("zucai_fixed_prize_policy_revision", revision_id),)

        return self._action_service.execute(command, handler)

    def generate_ticket_candidate_set(
        self,
        request: GenerateTicketCandidateSetRequest,
    ) -> ActionOutcome:
        policy_version = self._generation_policy(request.generation_request_id)
        command = ActionCommand.create(
            action_type="generate_ticket_candidate_set",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            policy_version=policy_version,
            payload={
                "generation_request_id": request.generation_request_id,
                "candidate_sets": [asdict(item) for item in request.candidate_sets],
                "generator_version": request.generator_version,
                "worker_job_id": request.worker_job_id,
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            generation = uow.operator_decision.candidate_generation_request(
                request.generation_request_id
            )
            if generation is None:
                raise ValueError("candidate generation request does not exist")
            self._validate_worker_lease(uow, request)
            envelope = self._validate_generation_lineage(
                uow,
                generation,
                receipt_time=request.requested_at,
            )
            self._validate_candidate_sets(uow, generation, envelope, request)

            refs_by_kind: list[tuple[str, ObjectRef]] = []
            for candidate_set in sorted(
                request.candidate_sets,
                key=lambda item: item.set_kind,
            ):
                current = uow.operator_result.current_candidate_set(
                    task_family_id=generation.task_family_id,
                    work_item_id=generation.work_item_id,
                    set_kind=candidate_set.set_kind,
                )
                revision_no = 1 if current is None else current.revision_no + 1
                family_id = _stable_id(
                    "operator-candidate-set-family",
                    generation.task_family_id,
                    generation.work_item_id,
                    candidate_set.set_kind,
                )
                set_document = {
                    "generation_request_id": generation.generation_request_id,
                    "dependency_fingerprint": generation.dependency_fingerprint,
                    "set_kind": candidate_set.set_kind,
                    "generator_version": request.generator_version,
                    "candidates": [asdict(item) for item in candidate_set.candidates],
                }
                set_hash = _content_hash(set_document)
                set_id = _stable_id(
                    "operator-candidate-set", family_id, revision_no, set_hash
                )
                counts = {
                    name: sum(
                        candidate.partition == name
                        for candidate in candidate_set.candidates
                    )
                    for name in _PARTITIONS
                }
                uow.operator_result.insert_candidate_set_revision(
                    TicketCandidateSetRevisionRow(
                        candidate_set_revision_id=set_id,
                        candidate_set_family_id=family_id,
                        revision_no=revision_no,
                        supersedes_revision_id=(
                            None if current is None else current.candidate_set_revision_id
                        ),
                        generation_request_id=generation.generation_request_id,
                        task_family_id=generation.task_family_id,
                        work_item_id=generation.work_item_id,
                        task_snapshot_hash=generation.task_snapshot_hash,
                        slate_revision_id=generation.slate_revision_id,
                        market_prior_baseline_revision_id=(
                            generation.market_prior_baseline_revision_id
                        ),
                        baseline_envelope_revision_id=(
                            generation.baseline_envelope_revision_id
                        ),
                        judgment_prescription_revision_id=(
                            generation.judgment_prescription_revision_id
                        ),
                        set_kind=candidate_set.set_kind,
                        comparison_only=int(
                            candidate_set.set_kind
                            == "conditional_market_counterfactual"
                        ),
                        generator_version=request.generator_version,
                        audit_policy_version="operator-candidate-audit-v1",
                        candidate_count=len(candidate_set.candidates),
                        eligible_count=counts["eligible"],
                        audit_blocked_count=counts["audit_blocked"],
                        over_cap_count=counts["over_cap"],
                        content_hash=set_hash,
                        action_id=action_command.action_id,
                        created_at=_utc(request.requested_at),
                    )
                )
                self._insert_candidates(
                    uow,
                    set_id=set_id,
                    candidate_set=candidate_set,
                )
                refs_by_kind.append(
                    (
                        candidate_set.set_kind,
                        ObjectRef("ticket_candidate_set_revision", set_id),
                    )
                )

            judgment_ref = next(
                ref
                for set_kind, ref in refs_by_kind
                if set_kind == "judgment_bound"
            )
            uow.operator_decision.complete_worker_job(
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                result_action_id=action_command.action_id,
                result_object_type=judgment_ref.object_type,
                result_object_id=judgment_ref.object_id,
                completed_at=_utc(request.requested_at),
            )
            return tuple(ref for _set_kind, ref in refs_by_kind)

        return self._action_service.execute(command, handler)

    def _generation_policy(self, generation_request_id: str) -> str:
        with self._action_service.unit_of_work() as uow:
            generation = uow.operator_decision.candidate_generation_request(
                generation_request_id
            )
            if generation is None:
                raise ValueError("candidate generation request does not exist")
            bundle = uow.operator_decision.task_evidence_bundle_revision(
                generation.task_evidence_bundle_revision_id
            )
            if bundle is None:
                raise ValueError("candidate generation evidence bundle does not exist")
            return bundle.policy_version

    @staticmethod
    def _validate_worker_lease(uow, request: GenerateTicketCandidateSetRequest) -> None:
        job = uow.operator_decision.worker_job(request.worker_job_id)
        if (
            job is None
            or job.job_kind != "candidate_generation"
            or job.source_object_type != "operator_candidate_generation_request"
            or job.source_object_id != request.generation_request_id
            or job.state != "leased"
            or job.lease_owner != request.lease_owner
            or job.lease_expires_at is None
            or datetime.fromisoformat(job.lease_expires_at) <= request.requested_at
        ):
            raise ValueError("candidate generation job is not held by this worker")

    @staticmethod
    def _validate_generation_lineage(uow, generation, *, receipt_time: datetime):
        bundle = uow.operator_decision.task_evidence_bundle_revision(
            generation.task_evidence_bundle_revision_id
        )
        baseline = uow.operator_decision.market_prior_baseline_revision(
            generation.market_prior_baseline_revision_id
        )
        envelope = uow.operator_decision.baseline_envelope_revision(
            generation.baseline_envelope_revision_id
        )
        prescription = uow.operator_decision.judgment_prescription_revision(
            generation.judgment_prescription_revision_id
        )
        if None in (bundle, baseline, envelope, prescription):
            raise ValueError("candidate generation lineage is incomplete")
        current_bundle = uow.operator_decision.latest_task_evidence_bundle_revision(
            generation.task_family_id
        )
        current_baseline = uow.operator_decision.current_market_prior_baseline_revision(
            baseline.market_prior_baseline_family_id
        )
        current_envelope = uow.operator_decision.current_baseline_envelope_revision(
            envelope.baseline_envelope_family_id
        )
        current_prescription = (
            uow.operator_decision.current_judgment_prescription_revision(
                prescription.judgment_prescription_family_id
            )
        )
        current_slate = uow.operator_sale.current_slate(bundle.lane, bundle.business_key)
        expected = (
            generation.task_family_id,
            generation.work_item_id,
            generation.task_snapshot_hash,
            generation.slate_revision_id,
            generation.task_evidence_bundle_revision_id,
            generation.market_prior_baseline_revision_id,
            generation.baseline_envelope_revision_id,
        )
        if (
            current_bundle is None
            or current_baseline is None
            or current_envelope is None
            or current_prescription is None
            or current_slate is None
            or current_bundle.task_evidence_bundle_revision_id != expected[4]
            or current_baseline.market_prior_baseline_revision_id != expected[5]
            or current_envelope.baseline_envelope_revision_id != expected[6]
            or current_prescription.judgment_prescription_revision_id
            != generation.judgment_prescription_revision_id
            or current_slate.slate_revision_id != expected[3]
        ):
            raise ValueError("candidate generation lineage is stale")
        baseline_lineage = (
            baseline.task_family_id,
            baseline.work_item_id,
            baseline.task_snapshot_hash,
            baseline.slate_revision_id,
            baseline.task_evidence_bundle_revision_id,
        )
        envelope_lineage = (
            envelope.task_family_id,
            envelope.work_item_id,
            envelope.task_snapshot_hash,
            envelope.slate_revision_id,
            envelope.task_evidence_bundle_revision_id,
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
        if (
            baseline_lineage != expected[:5]
            or envelope_lineage != expected[:5]
            or prescription_lineage != expected
        ):
            raise ValueError("candidate generation lineage crosses dependencies")
        receipt_at = _aware(receipt_time, "receipt_time").astimezone(UTC)
        baseline_rows = uow.operator_decision.market_prior_baseline_probabilities(
            generation.market_prior_baseline_revision_id
        )
        required_offer_ids = {
            str(row["official_offer_revision_id"]) for row in baseline_rows
        }
        offers = {
            offer.official_offer_revision_id: offer
            for offer in uow.operator_sale.offer_revisions_for_slate(
                generation.slate_revision_id
            )
        }
        if not required_offer_ids or not required_offer_ids <= set(offers):
            raise ValueError("candidate generation official offers are incomplete")
        for offer_id in sorted(required_offer_ids):
            offer = offers[offer_id]
            current_offer = uow.operator_sale.current_offer_by_family(
                offer.official_offer_family_id
            )
            if (
                current_offer is None
                or current_offer.official_offer_revision_id != offer_id
                or offer.status != "on_sale"
                or receipt_at < datetime.fromisoformat(offer.sale_opens_at).astimezone(UTC)
                or receipt_at
                >= datetime.fromisoformat(offer.sale_deadline_at).astimezone(UTC)
            ):
                raise ValueError(
                    "candidate generation offer is closed, stale, or at its deadline"
                )
        return envelope

    @classmethod
    def _validate_candidate_sets(cls, uow, generation, envelope, request) -> None:
        if len(request.candidate_sets) != 2:
            raise ValueError("generation requires both candidate set kinds")
        set_kinds = {candidate_set.set_kind for candidate_set in request.candidate_sets}
        if set_kinds != _SET_KINDS:
            raise ValueError("generation requires one set of each candidate kind")
        current = uow.operator_result.current_candidate_set(
            task_family_id=generation.task_family_id,
            work_item_id=generation.work_item_id,
            set_kind="judgment_bound",
        )
        current_revision = 0 if current is None else current.revision_no
        if generation.expected_current_revision_no != current_revision:
            raise OptimisticConcurrencyError(
                "candidate set changed after generation was requested"
            )
        for candidate_set in request.candidate_sets:
            if not candidate_set.candidates:
                raise ValueError("candidate sets cannot be empty")
            cls._validate_candidate_set(uow, generation, envelope, candidate_set)

    @classmethod
    def _validate_candidate_set(cls, uow, generation, envelope, candidate_set) -> None:
        eligible = [
            item for item in candidate_set.candidates if item.partition == "eligible"
        ]
        ordered = sorted(
            eligible,
            key=lambda item: (
                -_decimal(
                    item.metrics.objective_probability_decimal,
                    name="objective_probability_decimal",
                    probability=True,
                ),
                item.metrics.stake_minor,
                item.content_hash,
            ),
        )
        expected_ranks = {item.content_hash: index + 1 for index, item in enumerate(ordered)}
        if len(expected_ranks) != len(candidate_set.candidates):
            hashes = [item.content_hash for item in candidate_set.candidates]
            if len(set(hashes)) != len(hashes):
                raise ValueError("candidate content hashes must be unique within a set")
        for candidate in candidate_set.candidates:
            if candidate.partition not in _PARTITIONS:
                raise ValueError("candidate partition is not registered")
            expected_deployable = (
                candidate_set.set_kind == "judgment_bound"
                and candidate.partition == "eligible"
            )
            if candidate.deployable != expected_deployable:
                raise ValueError("candidate deployability does not match its set and partition")
            expected_rank = expected_ranks.get(candidate.content_hash)
            if candidate.rank != expected_rank:
                raise ValueError("candidate rank does not match deterministic ordering")
            cls._validate_candidate(uow, generation, envelope, candidate)

    @classmethod
    def _validate_candidate(cls, uow, generation, envelope, candidate) -> None:
        if set(candidate.completed_audit_kinds) != _AUDIT_KINDS:
            raise ValueError("every candidate must complete all four audit kinds")
        if len(candidate.completed_audit_kinds) != len(_AUDIT_KINDS):
            raise ValueError("candidate audit completion kinds must be unique")
        _required(candidate.content_hash, "candidate content_hash")
        metrics = candidate.metrics
        for name in (
            "ticket_count",
            "distinct_note_count",
            "paid_note_unit_count",
            "stake_minor",
        ):
            value = getattr(metrics, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"candidate {name} must be a positive integer")
        _decimal(
            metrics.capital_utilization_decimal,
            name="capital_utilization_decimal",
        )
        _decimal(
            metrics.objective_probability_decimal,
            name="objective_probability_decimal",
            probability=True,
        )
        _decimal(
            metrics.expected_broken_legs_decimal,
            name="expected_broken_legs_decimal",
        )
        if metrics.break_even_to_official_median_decimal is not None:
            _decimal(
                metrics.break_even_to_official_median_decimal,
                name="break_even_to_official_median_decimal",
            )
        if metrics.break_even_bonus_minor is not None and metrics.break_even_bonus_minor < 0:
            raise ValueError("break_even_bonus_minor cannot be negative")
        if not candidate.tickets or len(candidate.tickets) != metrics.ticket_count:
            raise ValueError("candidate ticket count does not reconcile")
        if sum(ticket.stake_minor for ticket in candidate.tickets) != metrics.stake_minor:
            raise ValueError("candidate ticket stakes do not reconcile")
        expected_partition = (
            "over_cap"
            if metrics.stake_minor > envelope.capital_cap_minor
            else "audit_blocked"
            if any(finding.severity == "ERROR" for finding in candidate.audit_findings)
            else "eligible"
        )
        if candidate.partition != expected_partition:
            raise ValueError("candidate partition does not match audit and budget results")
        for finding in candidate.audit_findings:
            cls._validate_finding(finding)
        if metrics.currency != envelope.currency:
            raise ValueError("candidate currency differs from the envelope")
        if len(candidate.tickets) > envelope.maximum_ticket_count:
            raise ValueError("candidate exceeds the maximum ticket count")
        for ticket in candidate.tickets:
            cls._validate_ticket(uow, generation, envelope, ticket)

    @staticmethod
    def _validate_finding(finding: CandidateAuditFindingInput) -> None:
        for name in ("finding_id", "code", "message"):
            _required(getattr(finding, name), name)
        if finding.audit_kind not in _AUDIT_KINDS:
            raise ValueError("candidate audit kind is not registered")
        if finding.severity not in {"WARN", "ERROR"}:
            raise ValueError("candidate audit severity is not registered")
        if finding.audit_kind == "prescription_difference" and not (
            isinstance(finding.rule_id, str) and finding.rule_id.strip()
        ):
            raise ValueError("every prescription deviation requires a named Rule ID")

    @classmethod
    def _validate_ticket(cls, uow, generation, envelope, ticket) -> None:
        if ticket.ticket_kind != envelope.ticket_kind:
            raise ValueError("candidate ticket kind differs from the envelope")
        if ticket.currency != envelope.currency:
            raise ValueError("candidate ticket currency differs from the envelope")
        for name in ("unit_stake_minor", "unit_count", "stake_minor"):
            value = getattr(ticket, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"ticket {name} must be a positive integer")
        if ticket.stake_minor != ticket.unit_stake_minor * ticket.unit_count:
            raise ValueError("candidate ticket stake does not reconcile")
        if not ticket.legs:
            raise ValueError("candidate ticket legs are required")
        if ticket.ticket_kind == "jczq_pass":
            if ticket.fixed_prize_policy_revision_id is not None:
                raise ValueError("JCZQ candidate tickets cannot bind fixed-prize policy")
        else:
            if ticket.fixed_prize_policy_revision_id != (
                generation.fixed_prize_policy_revision_id
            ):
                raise ValueError("Zucai candidate ticket policy differs from its request")
            policy = uow.operator_result.fixed_prize_policy_revision(
                ticket.fixed_prize_policy_revision_id or ""
            )
            if (
                policy is None
                or policy.ticket_kind != ticket.ticket_kind
                or policy.currency != ticket.currency
                or policy.standard_unit_stake_minor != ticket.unit_stake_minor
            ):
                raise ValueError("Zucai fixed-prize policy is invalid for the ticket")
            expected_legs = 14 if ticket.ticket_kind == "sfc" else 9
            if len({leg.official_offer_revision_id for leg in ticket.legs}) != expected_legs:
                raise ValueError(
                    f"{ticket.ticket_kind} candidate requires exactly {expected_legs} offers"
                )
        for leg in ticket.legs:
            cls._validate_leg(uow, generation, ticket.ticket_kind, leg)

    @staticmethod
    def _validate_leg(uow, generation, ticket_kind: str, leg) -> None:
        offers = uow.operator_sale.offer_revisions_for_slate(generation.slate_revision_id)
        offer = next(
            (
                item
                for item in offers
                if item.official_offer_revision_id == leg.official_offer_revision_id
            ),
            None,
        )
        if (
            offer is None
            or offer.match_id != leg.match_id
            or leg.market_definition_id not in offer.market_definition_ids
            or offer.status != "on_sale"
        ):
            raise ValueError("candidate leg does not reference a current offered market")
        outcome_key = _FACE_TO_OUTCOME.get(leg.selection_code, leg.selection_code)
        selection = (
            uow.connection.execute(
                select(schema_market.selection_definitions).where(
                    schema_market.selection_definitions.c.market_definition_id
                    == leg.market_definition_id,
                    schema_market.selection_definitions.c.outcome_key == outcome_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if selection is None or int(selection["deployable"]) != 1:
            raise ValueError("candidate leg references a non-deployable selection")
        if ticket_kind == "jczq_pass":
            if leg.quote_id is None or leg.booked_decimal_odds is None:
                raise ValueError("JCZQ candidate legs require an exact Quote and odds")
            baseline_rows = tuple(
                row
                for row in uow.operator_decision.market_prior_baseline_probabilities(
                    generation.market_prior_baseline_revision_id
                )
                if row["official_offer_revision_id"]
                == leg.official_offer_revision_id
                and row["match_id"] == leg.match_id
                and row["market_definition_id"] == leg.market_definition_id
                and row["face_code"] == leg.selection_code
            )
            if len(baseline_rows) != 1:
                raise ValueError("JCZQ candidate leg has no exact baseline binding")
            baseline_row = baseline_rows[0]
            if (
                baseline_row["quote_id"] != leg.quote_id
                or baseline_row["booked_decimal_odds"]
                != leg.booked_decimal_odds
                or baseline_row["settlement_parameter_decimal"]
                != leg.settlement_parameter_decimal
            ):
                raise ValueError("JCZQ candidate Quote differs from its baseline binding")
            quote = uow.market.quote(leg.quote_id)
            if (
                quote is None
                or quote.match_id != leg.match_id
                or quote.market_definition_id != leg.market_definition_id
                or quote.selection_id != selection["selection_id"]
                or quote.quote_status != "active"
                or quote.captured_at != baseline_row["quote_captured_at"]
                or quote.quote_id
                not in uow.market.snapshot_quote_ids(
                    str(baseline_row["market_snapshot_id"])
                )
            ):
                raise ValueError("JCZQ candidate Quote does not match its selection")
            booked = _decimal(
                leg.booked_decimal_odds,
                name="booked_decimal_odds",
            )
            if booked <= Decimal("1") or booked != Decimal(str(quote.decimal_odds)).quantize(
                _DECIMAL_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            ):
                raise ValueError("JCZQ booked odds differ from the exact Quote")
            market = uow.connection.execute(
                select(schema_market.market_definitions).where(
                    schema_market.market_definitions.c.market_definition_id
                    == leg.market_definition_id
                )
            ).mappings().one()
            if market["line_schema"] is not None:
                if leg.settlement_parameter_decimal is None:
                    raise ValueError("lined JCZQ market requires a settlement parameter")
                candidate_line = _decimal(
                    leg.settlement_parameter_decimal,
                    name="settlement_parameter_decimal",
                    allow_negative=True,
                )
                if (
                    quote.settlement_parameter_decimal is None
                    or candidate_line
                    != _decimal(
                        quote.settlement_parameter_decimal,
                        name="Quote settlement_parameter_decimal",
                        allow_negative=True,
                    )
                ):
                    raise ValueError(
                        "JCZQ settlement parameter differs from the exact Quote"
                    )
            elif leg.settlement_parameter_decimal is not None:
                raise ValueError("unlined JCZQ market cannot contain a settlement parameter")
        elif any(
            value is not None
            for value in (
                leg.quote_id,
                leg.booked_decimal_odds,
                leg.settlement_parameter_decimal,
            )
        ):
            raise ValueError("Zucai candidate legs cannot contain Quote, odds, or line")

    @classmethod
    def _insert_candidates(cls, uow, *, set_id: str, candidate_set) -> None:
        for candidate_index, candidate in enumerate(candidate_set.candidates):
            candidate_id = _stable_id(
                "operator-candidate", set_id, candidate.content_hash
            )
            uow.operator_result.insert_candidate(
                TicketCandidateRow(
                    candidate_revision_id=candidate_id,
                    candidate_set_revision_id=set_id,
                    candidate_index=candidate_index,
                    candidate_code=f"C{candidate_index + 1:04d}",
                    partition=candidate.partition,
                    rank=candidate.rank,
                    eligible=int(candidate.partition == "eligible"),
                    deployable=int(candidate.deployable),
                    leg_audit_completed=1,
                    prescription_audit_completed=1,
                    budget_check_completed=1,
                    deployment_report_completed=1,
                    content_hash=candidate.content_hash,
                )
            )
            cls._insert_candidate_children(uow, candidate_id, candidate)

    @classmethod
    def _insert_candidate_children(cls, uow, candidate_id: str, candidate) -> None:
        for ticket_index, ticket in enumerate(candidate.tickets):
            ticket_id = _stable_id(
                "operator-candidate-ticket",
                candidate_id,
                ticket_index,
                ticket.composition_hash,
            )
            uow.operator_result.insert_candidate_ticket(
                CandidateTicketRow(
                    candidate_ticket_id=ticket_id,
                    candidate_revision_id=candidate_id,
                    ticket_index=ticket_index,
                    ticket_kind=ticket.ticket_kind,
                    structure_code=ticket.structure_code,
                    group_code=ticket.group_code,
                    currency=ticket.currency,
                    unit_stake_minor=ticket.unit_stake_minor,
                    unit_count=ticket.unit_count,
                    stake_minor=ticket.stake_minor,
                    composition_hash=ticket.composition_hash,
                    fixed_prize_policy_revision_id=(
                        ticket.fixed_prize_policy_revision_id
                    ),
                )
            )
            for leg_index, leg in enumerate(ticket.legs):
                uow.operator_result.insert_candidate_ticket_leg(
                    CandidateTicketLegRow(
                        candidate_ticket_leg_id=_stable_id(
                            "operator-candidate-ticket-leg",
                            ticket_id,
                            leg_index,
                            asdict(leg),
                        ),
                        candidate_ticket_id=ticket_id,
                        leg_index=leg_index,
                        official_offer_revision_id=leg.official_offer_revision_id,
                        match_id=leg.match_id,
                        market_definition_id=leg.market_definition_id,
                        selection_code=leg.selection_code,
                        quote_id=leg.quote_id,
                        booked_decimal_odds=leg.booked_decimal_odds,
                        settlement_parameter_decimal=(
                            leg.settlement_parameter_decimal
                        ),
                    )
                )
        metrics = candidate.metrics
        uow.operator_result.insert_candidate_metric(
            CandidateMetricRow(
                candidate_metric_id=_stable_id("operator-candidate-metric", candidate_id),
                candidate_revision_id=candidate_id,
                currency=metrics.currency,
                ticket_count=metrics.ticket_count,
                distinct_note_count=metrics.distinct_note_count,
                paid_note_unit_count=metrics.paid_note_unit_count,
                stake_minor=metrics.stake_minor,
                capital_utilization_decimal=metrics.capital_utilization_decimal,
                probability_kind=metrics.probability_kind,
                objective_probability_decimal=metrics.objective_probability_decimal,
                expected_broken_legs_decimal=metrics.expected_broken_legs_decimal,
                break_even_bonus_minor=metrics.break_even_bonus_minor,
                break_even_to_official_median_decimal=(
                    metrics.break_even_to_official_median_decimal
                ),
            )
        )
        for index, dead_face in enumerate(candidate.common_dead_faces):
            uow.operator_result.insert_candidate_dead_face(
                CandidateDeadFaceRow(
                    candidate_dead_face_id=_stable_id(
                        "operator-candidate-dead-face",
                        candidate_id,
                        dead_face.official_match_no,
                        dead_face.face_code,
                    ),
                    candidate_revision_id=candidate_id,
                    dead_face_index=index,
                    official_match_no=dead_face.official_match_no,
                    face_code=dead_face.face_code,
                )
            )
        for index, finding in enumerate(candidate.audit_findings):
            uow.operator_result.insert_candidate_audit_finding(
                CandidateAuditFindingRow(
                    candidate_audit_finding_id=_stable_id(
                        "operator-candidate-finding",
                        candidate_id,
                        finding.finding_id,
                    ),
                    candidate_revision_id=candidate_id,
                    finding_index=index,
                    audit_kind=finding.audit_kind,
                    finding_code=finding.code,
                    severity=finding.severity,
                    message=finding.message,
                    official_match_no=finding.official_match_no,
                    rule_id=finding.rule_id,
                )
            )


__all__ = [
    "CandidateAuditFindingInput",
    "CandidateDeadFaceInput",
    "CandidateMetricsInput",
    "CandidateSetInput",
    "CandidateTicketInput",
    "CandidateTicketLegInput",
    "GenerateTicketCandidateSetRequest",
    "OperatorResultActions",
    "RegisterZucaiFixedPrizePolicyRequest",
    "TicketCandidateInput",
]
