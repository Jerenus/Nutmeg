"""Typed Actions for deterministic candidate sets and fixed-prize policy."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

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
    CandidateBandOutcomeRow,
    CandidateDeadFaceRow,
    CandidateMetricRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    OperatorWorkerJobRow,
    ReviewEligibilityFactRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.operator.result_manifest import (
    RESULT_SOURCE_KINDS,
    ResultEvidenceManifestV1,
    normalize_match_result,
)
from nutmeg.ontology.operator.task_settlement import (
    SettlementLegInput,
    SettlementNoteInput,
    SettlementOutcomeInput,
    SettlementTicketInput,
    TicketSettlementPlan,
    ZucaiPrizeTierInput,
    grade_ticket_settlement,
    plan_payout_cash_entries,
    validate_settlement_method_version,
)
from nutmeg.ontology.repository import schema, schema_market
from nutmeg.ontology.repository.finance import CashTransactionRow
from nutmeg.ontology.repository.operator_result import (
    OperatorOutcomeRevisionRow,
    ResultMatchRevisionRow,
    ResultSetFamilyRow,
    ResultSetRevisionRow,
    ResultSourceReceiptRow,
    SettlementCashLinkRow,
    SettlementRequestRow,
    TaskSettlementRunRow,
    TaskSettlementSkipRow,
    TicketNoteLegSettlementRow,
    TicketNoteSettlementRow,
    TicketSettlementRevisionRow,
    ZucaiPrizeTableRevisionRow,
    ZucaiPrizeTableTierRow,
)

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
_RESULT_SOURCE_ORDER = (
    "api_football",
    "sporttery_game90",
    "okooo_manual",
)


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
    odds_band: Literal["10x", "20x", "50x", "100x"] | None = None
    target_odds_min_decimal: str | None = None
    target_odds_max_decimal: str | None = None
    combined_decimal_odds: str | None = None
    parent_candidate_revision_id: str | None = None
    delta_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateBandOutcomeInput:
    odds_band: Literal["10x", "20x", "50x", "100x"]
    status: Literal["candidates", "no_feasible_candidate"]
    reason_code: str | None
    candidate_count: int


@dataclass(frozen=True, slots=True)
class CandidateSetInput:
    set_kind: Literal["judgment_bound", "conditional_market_counterfactual"]
    candidates: tuple[TicketCandidateInput, ...]
    band_outcomes: tuple[CandidateBandOutcomeInput, ...] = ()


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


@dataclass(frozen=True, slots=True)
class ImportResultEvidenceRequest:
    manifest: ResultEvidenceManifestV1
    importer_version: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name in ("importer_version", "actor_id", "idempotency_key"):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class RequestSettlementRequest:
    result_set_revision_id: str
    expected_task_snapshot_hash: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "result_set_revision_id",
            "expected_task_snapshot_hash",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        _aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class SettleTaskRequest:
    settlement_request_id: str
    worker_job_id: str
    lease_owner: str
    settlement_method_version: str
    rounding_policy_version: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "settlement_request_id",
            "worker_job_id",
            "lease_owner",
            "settlement_method_version",
            "actor_id",
            "idempotency_key",
        ):
            _required(getattr(self, name), name)
        if self.rounding_policy_version is not None:
            _required(self.rounding_policy_version, "rounding_policy_version")
        _aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class ResultImportCounts:
    match_count: int
    source_receipt_count: int
    outcome_count: int
    agreed_count: int
    conflict_count: int
    missing_count: int
    prize_tier_count: int

    @property
    def agreement_counts(self) -> dict[str, int]:
        return {
            "agreed": self.agreed_count,
            "conflict": self.conflict_count,
            "missing": self.missing_count,
        }


@dataclass(frozen=True, slots=True)
class ResultImportResult:
    outcome: ActionOutcome
    result_set: ResultSetRevisionRow | None
    match_results: tuple[ResultMatchRevisionRow, ...]
    source_receipts: tuple[ResultSourceReceiptRow, ...]
    outcomes: tuple[OperatorOutcomeRevisionRow, ...]
    prize_table: ZucaiPrizeTableRevisionRow | None
    prize_tiers: tuple[ZucaiPrizeTableTierRow, ...]
    counts: ResultImportCounts


@dataclass(frozen=True, slots=True)
class _PreparedTicketSettlement:
    ticket: object
    plan: TicketSettlementPlan
    predecessor: TicketSettlementRevisionRow | None
    settlement_family_id: str
    settlement_revision_id: str
    revision_no: int
    cash_entries: tuple[object, ...]


def _prepare_ticket_settlement(
    uow,
    *,
    ticket_id: str,
    result_set: ResultSetRevisionRow,
    settlement_method_version: str,
    rounding_policy_version: str | None,
) -> tuple[_PreparedTicketSettlement | None, str | None]:
    ticket = uow.finance.ticket(ticket_id)
    placement_cash = uow.operator_result.placement_cash_link(ticket_id)
    if ticket is None or placement_cash is None:
        return None, "placement_integrity_blocked"
    stake_cash = uow.finance.cash_transaction(placement_cash.transaction_id)
    if (
        ticket.status != "approved"
        or ticket.ticket_kind not in {"jczq_pass", "sfc", "renjiu"}
        or ticket.stake_minor is None
        or ticket.stake_minor <= 0
        or placement_cash.stake_minor != ticket.stake_minor
        or placement_cash.currency != ticket.currency
        or stake_cash is None
        or stake_cash.ticket_id != ticket.ticket_id
        or stake_cash.account_id != ticket.account_id
        or stake_cash.kind != "stake"
        or stake_cash.amount_minor != -ticket.stake_minor
        or stake_cash.currency != ticket.currency
    ):
        return None, "placement_integrity_blocked"

    notes = uow.operator_result.ticket_notes(ticket_id)
    if not notes:
        return None, "placement_integrity_blocked"
    outcomes = {
        row.match_id: SettlementOutcomeInput(
            outcome_revision_id=row.outcome_revision_id,
            match_id=row.match_id,
            result_disposition=row.result_disposition,
            home_90=row.home_90,
            away_90=row.away_90,
        )
        for row in uow.operator_result.outcomes_for_result_set(
            result_set.result_set_revision_id
        )
    }
    result_matches = {
        row.match_id: row
        for row in uow.operator_result.result_matches_for_set(
            result_set.result_set_revision_id
        )
    }
    crs_exact_codes = frozenset(
        str(code)
        for code in uow.connection.scalars(
            select(schema_market.selection_definitions.c.outcome_key).where(
                schema_market.selection_definitions.c.market_definition_id
                == "md-crs",
                schema_market.selection_definitions.c.deployable == 1,
            )
        )
        if str(code) not in {"other", "win_other", "draw_other", "loss_other"}
    )
    note_inputs: list[SettlementNoteInput] = []
    for note in notes:
        legs = uow.operator_result.ticket_note_legs(note.ticket_note_id)
        if not legs:
            return None, "placement_integrity_blocked"
        if any(leg.match_id not in outcomes for leg in legs):
            return None, "result_not_ready"
        if any(
            leg.match_id not in result_matches
            or result_matches[leg.match_id].official_offer_revision_id
            != leg.official_offer_revision_id
            for leg in legs
        ):
            return None, "placement_integrity_blocked"
        if any(
            leg.market_definition_id
            not in {"md-had", "md-hhad", "md-ttg", "md-crs"}
            for leg in legs
        ):
            raise ValueError("unsupported settlement market")
        note_inputs.append(
            SettlementNoteInput(
                ticket_note_id=note.ticket_note_id,
                ticket_kind=note.ticket_kind,
                currency=note.currency,
                unit_stake_minor=note.unit_stake_minor,
                unit_count=note.unit_count,
                stake_minor=note.stake_minor,
                fixed_prize_policy_revision_id=(
                    note.fixed_prize_policy_revision_id
                ),
                legs=tuple(
                    SettlementLegInput(
                        ticket_note_leg_id=leg.ticket_note_leg_id,
                        official_offer_revision_id=(
                            leg.official_offer_revision_id
                        ),
                        match_id=leg.match_id,
                        market_definition_id=leg.market_definition_id,
                        selection_code=leg.selection_code,
                        booked_decimal_odds=leg.booked_decimal_odds,
                        settlement_parameter_decimal=(
                            leg.settlement_parameter_decimal
                        ),
                        fixed_prize_policy_revision_id=(
                            leg.fixed_prize_policy_revision_id
                        ),
                        crs_exact_codes=crs_exact_codes,
                    )
                    for leg in legs
                ),
            )
        )

    prize_tiers: tuple[ZucaiPrizeTierInput, ...] = ()
    if ticket.ticket_kind == "jczq_pass":
        if (
            ticket.fixed_prize_policy_revision_id is not None
            or result_set.zucai_prize_table_revision_id is not None
        ):
            return None, "placement_integrity_blocked"
    else:
        if result_set.zucai_prize_table_revision_id is None:
            return None, "prize_not_ready"
        policy_id = ticket.fixed_prize_policy_revision_id
        policy = (
            None
            if policy_id is None
            else uow.operator_result.fixed_prize_policy_revision(policy_id)
        )
        policy_tiers = (
            ()
            if policy_id is None
            else uow.operator_result.fixed_prize_policy_tiers(policy_id)
        )
        if (
            policy is None
            or policy.ticket_kind != ticket.ticket_kind
            or policy.currency != ticket.currency
            or policy.official_void_rule != "all_faces_match"
            or any(
                note.unit_stake_minor != policy.standard_unit_stake_minor
                for note in notes
            )
            or {row.tier_code for row in policy_tiers}
            != {tier[0] for tier in _POLICY_TIERS[ticket.ticket_kind]}
        ):
            raise ValueError("persisted fixed-prize policy invariant mismatch")
        prize_rows = uow.operator_result.prize_table_tiers(
            result_set.zucai_prize_table_revision_id
        )
        prize_tiers = tuple(
            ZucaiPrizeTierInput(
                tier_code=row.tier_code,
                ticket_kind=row.ticket_kind,
                required_correct_count=row.required_correct_count,
                payout_minor_per_winning_note=(
                    row.payout_minor_per_winning_note
                ),
            )
            for row in prize_rows
        )

    try:
        plan = grade_ticket_settlement(
            SettlementTicketInput(
                ticket_id=ticket.ticket_id,
                ticket_kind=ticket.ticket_kind,
                currency=ticket.currency,
                stake_minor=ticket.stake_minor,
                fixed_prize_policy_revision_id=(
                    ticket.fixed_prize_policy_revision_id
                ),
                notes=tuple(note_inputs),
            ),
            settlement_method_version=settlement_method_version,
            outcomes_by_match=outcomes,
            prize_tiers=prize_tiers,
        )
    except ValueError as error:
        raise ValueError(f"persisted settlement invariant mismatch: {error}") from error

    predecessor = uow.operator_result.current_ticket_settlement(ticket_id)
    identity = (
        result_set.result_set_revision_id,
        result_set.zucai_prize_table_revision_id,
        ticket.fixed_prize_policy_revision_id,
        settlement_method_version,
        rounding_policy_version,
    )
    if predecessor is not None and (
        predecessor.result_set_revision_id,
        predecessor.prize_table_revision_id,
        predecessor.fixed_prize_policy_revision_id,
        predecessor.method_version,
        predecessor.rounding_policy_version,
    ) == identity:
        return None, "already_current"
    family_id = _stable_id("operator-ticket-settlement-family", ticket_id)
    if predecessor is not None and predecessor.settlement_family_id != family_id:
        raise ValueError("ticket settlement family has drifted")
    revision_no = 1 if predecessor is None else predecessor.revision_no + 1
    settlement_id = _stable_id(
        "operator-ticket-settlement",
        family_id,
        revision_no,
        identity,
    )
    predecessor_payouts = (
        ()
        if predecessor is None
        else tuple(
            row
            for row in uow.operator_result.settlement_cash_links(
                predecessor.settlement_revision_id
            )
            if row.transaction_kind == "payout"
        )
    )
    prior_payout = 0 if predecessor is None else predecessor.gross_payout_minor
    if (prior_payout > 0 and len(predecessor_payouts) != 1) or (
        prior_payout == 0 and predecessor_payouts
    ):
        raise ValueError("predecessor payout cash does not reconcile")
    cash_entries = plan_payout_cash_entries(
        prior_payout_minor=prior_payout,
        new_payout_minor=plan.gross_payout_minor,
        predecessor_payout_transaction_id=(
            None if not predecessor_payouts else predecessor_payouts[0].transaction_id
        ),
    )
    return (
        _PreparedTicketSettlement(
            ticket=ticket,
            plan=plan,
            predecessor=predecessor,
            settlement_family_id=family_id,
            settlement_revision_id=settlement_id,
            revision_no=revision_no,
            cash_entries=cash_entries,
        ),
        None,
    )


class OperatorResultActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def request_settlement(
        self,
        request: RequestSettlementRequest,
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="request_settlement",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "result_set_revision_id": request.result_set_revision_id,
                "expected_task_snapshot_hash": (
                    request.expected_task_snapshot_hash
                ),
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            result_set = uow.operator_result.result_set_revision(
                request.result_set_revision_id
            )
            if result_set is None:
                raise ValueError("result set does not exist")
            current = uow.operator_result.current_result_set(
                lane=result_set.lane,
                business_key=result_set.business_key,
            )
            if (
                current is None
                or current.result_set_revision_id
                != result_set.result_set_revision_id
            ):
                raise OptimisticConcurrencyError("result set is no longer current")
            if result_set.task_snapshot_hash != request.expected_task_snapshot_hash:
                raise OptimisticConcurrencyError("task snapshot has changed")
            request_id = _stable_id(
                "operator-settlement-request",
                result_set.task_family_id,
                result_set.work_item_id,
                result_set.result_set_revision_id,
            )
            requested_at = _utc(request.requested_at)
            uow.operator_result.insert_settlement_request(
                SettlementRequestRow(
                    settlement_request_id=request_id,
                    action_id=action_command.action_id,
                    task_family_id=result_set.task_family_id,
                    work_item_id=result_set.work_item_id,
                    task_snapshot_hash=result_set.task_snapshot_hash,
                    slate_revision_id=result_set.slate_revision_id,
                    result_set_revision_id=result_set.result_set_revision_id,
                    prize_table_revision_id=(
                        result_set.zucai_prize_table_revision_id
                    ),
                    requested_at=requested_at,
                )
            )
            uow.operator_decision.insert_worker_job(
                OperatorWorkerJobRow(
                    worker_job_id=_stable_id(
                        "operator-worker-job",
                        "task_settlement",
                        request_id,
                    ),
                    job_kind="task_settlement",
                    source_object_type="operator_settlement_request",
                    source_object_id=request_id,
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
            return (ObjectRef("operator_settlement_request", request_id),)

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def settle_task(self, request: SettleTaskRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="settle_task",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "settlement_request_id": request.settlement_request_id,
                "worker_job_id": request.worker_job_id,
                "lease_owner": request.lease_owner,
                "settlement_method_version": request.settlement_method_version,
                "rounding_policy_version": request.rounding_policy_version,
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            settlement_request = uow.operator_result.settlement_request(
                request.settlement_request_id
            )
            job = uow.operator_decision.worker_job(request.worker_job_id)
            if (
                settlement_request is None
                or job is None
                or job.job_kind != "task_settlement"
                or job.source_object_type != "operator_settlement_request"
                or job.source_object_id != request.settlement_request_id
                or job.state != "leased"
                or job.lease_owner != request.lease_owner
            ):
                raise ValueError("settlement request is not leased by this worker")
            result_set = uow.operator_result.result_set_revision(
                settlement_request.result_set_revision_id
            )
            if result_set is None:
                raise ValueError("settlement result set does not exist")
            current = uow.operator_result.current_result_set(
                lane=result_set.lane,
                business_key=result_set.business_key,
            )
            if (
                current is None
                or current.result_set_revision_id
                != result_set.result_set_revision_id
            ):
                raise OptimisticConcurrencyError("settlement result set is stale")
            validate_settlement_method_version(request.settlement_method_version)
            if result_set.lane == "jczq":
                if request.rounding_policy_version != "cn_sporttery_jczq_v1":
                    raise ValueError("JCZQ settlement requires its rounding policy")
            elif request.rounding_policy_version is not None:
                raise ValueError("Zucai settlement forbids an odds rounding policy")

            ticket_ids = uow.operator_result.placed_ticket_ids_for_work_item(
                settlement_request.work_item_id
            )
            prepared: list[_PreparedTicketSettlement] = []
            skips: list[tuple[str, str]] = []
            for ticket_id in ticket_ids:
                ticket_plan, skip_code = _prepare_ticket_settlement(
                    uow,
                    ticket_id=ticket_id,
                    result_set=result_set,
                    settlement_method_version=request.settlement_method_version,
                    rounding_policy_version=request.rounding_policy_version,
                )
                if ticket_plan is None:
                    if skip_code is None:
                        raise ValueError("settlement preparation returned no disposition")
                    skips.append((ticket_id, skip_code))
                else:
                    prepared.append(ticket_plan)
            run_id = _stable_id(
                "operator-task-settlement-run",
                request.settlement_request_id,
                request.settlement_method_version,
            )
            completed_at = _utc(request.requested_at)
            settlement_ids = tuple(
                item.settlement_revision_id for item in prepared
            )
            note_count = sum(len(item.plan.notes) for item in prepared)
            leg_count = sum(
                len(note.legs)
                for item in prepared
                for note in item.plan.notes
            )
            cash_count = sum(len(item.cash_entries) for item in prepared)
            settlement_state = (
                "not_applicable"
                if not ticket_ids
                else (
                    "corrected"
                    if any(item.predecessor is not None for item in prepared)
                    else "settled"
                )
            )
            uow.operator_result.insert_task_settlement_run(
                TaskSettlementRunRow(
                    settlement_run_id=run_id,
                    settlement_request_id=request.settlement_request_id,
                    request_action_id=settlement_request.action_id,
                    settle_action_id=action_command.action_id,
                    task_family_id=settlement_request.task_family_id,
                    work_item_id=settlement_request.work_item_id,
                    work_item_snapshot_hash=(
                        settlement_request.task_snapshot_hash
                    ),
                    result_set_revision_id=(
                        settlement_request.result_set_revision_id
                    ),
                    prize_table_revision_id=(
                        settlement_request.prize_table_revision_id
                    ),
                    settlement_method_version=(
                        request.settlement_method_version
                    ),
                    rounding_policy_version=request.rounding_policy_version,
                    fixed_prize_policy_revision_ids=tuple(
                        sorted(
                            {
                                item.ticket.fixed_prize_policy_revision_id
                                for item in prepared
                                if item.ticket.fixed_prize_policy_revision_id
                                is not None
                            }
                        )
                    ),
                    settlement_state=settlement_state,
                    requested_ticket_count=len(ticket_ids),
                    eligible_ticket_count=len(prepared),
                    settled_ticket_count=len(prepared),
                    skipped_ticket_count=len(skips),
                    persisted_settlement_count=len(prepared),
                    persisted_note_grade_count=note_count,
                    persisted_leg_grade_count=leg_count,
                    persisted_cash_count=cash_count,
                    ticket_settlement_revision_ids=settlement_ids,
                    completed_at=completed_at,
                )
            )
            for skip_index, (ticket_id, reason_code) in enumerate(skips):
                uow.operator_result.insert_task_settlement_skip(
                    TaskSettlementSkipRow(
                        settlement_skip_id=_stable_id(
                            "operator-task-settlement-skip",
                            run_id,
                            ticket_id,
                        ),
                        settlement_run_id=run_id,
                        skip_index=skip_index,
                        ticket_id=ticket_id,
                        reason_code=reason_code,
                    )
                )
            for settlement_index, item in enumerate(prepared):
                plan = item.plan
                uow.operator_result.insert_ticket_settlement_revision(
                    TicketSettlementRevisionRow(
                        settlement_revision_id=item.settlement_revision_id,
                        settlement_family_id=item.settlement_family_id,
                        revision_no=item.revision_no,
                        supersedes_revision_id=(
                            None
                            if item.predecessor is None
                            else item.predecessor.settlement_revision_id
                        ),
                        settlement_index=settlement_index,
                        settlement_run_id=run_id,
                        ticket_id=plan.ticket_id,
                        result_set_revision_id=(
                            result_set.result_set_revision_id
                        ),
                        prize_table_revision_id=(
                            result_set.zucai_prize_table_revision_id
                        ),
                        fixed_prize_policy_revision_id=(
                            item.ticket.fixed_prize_policy_revision_id
                        ),
                        method_version=request.settlement_method_version,
                        rounding_policy_version=request.rounding_policy_version,
                        settlement_state=(
                            "settled"
                            if item.predecessor is None
                            else "corrected"
                        ),
                        currency=plan.currency,
                        stake_minor=plan.stake_minor,
                        distinct_note_count=plan.distinct_note_count,
                        paid_note_unit_count=plan.paid_note_unit_count,
                        winning_note_unit_count=(
                            plan.winning_note_unit_count
                        ),
                        void_note_unit_count=plan.void_note_unit_count,
                        gross_payout_minor=plan.gross_payout_minor,
                        action_id=action_command.action_id,
                        created_at=completed_at,
                    )
                )
                for note in plan.notes:
                    uow.operator_result.insert_ticket_note_settlement(
                        TicketNoteSettlementRow(
                            note_settlement_id=_stable_id(
                                "operator-ticket-note-settlement",
                                item.settlement_revision_id,
                                note.ticket_note_id,
                            ),
                            settlement_revision_id=item.settlement_revision_id,
                            ticket_note_id=note.ticket_note_id,
                            note_grade=note.note_grade,
                            unit_count=note.unit_count,
                            winning_unit_count=note.winning_unit_count,
                            void_unit_count=note.void_unit_count,
                            correct_leg_count=note.correct_leg_count,
                            void_leg_count=note.void_leg_count,
                            prize_tier_code=note.prize_tier_code,
                            payout_minor=note.payout_minor,
                        )
                    )
                    for leg in note.legs:
                        uow.operator_result.insert_ticket_note_leg_settlement(
                            TicketNoteLegSettlementRow(
                                leg_settlement_id=_stable_id(
                                    "operator-ticket-note-leg-settlement",
                                    item.settlement_revision_id,
                                    leg.ticket_note_leg_id,
                                ),
                                settlement_revision_id=(
                                    item.settlement_revision_id
                                ),
                                ticket_note_leg_id=leg.ticket_note_leg_id,
                                outcome_revision_id=leg.outcome_revision_id,
                                result_disposition=leg.result_disposition,
                                market_result_code=leg.market_result_code,
                                leg_grade=leg.leg_grade,
                            )
                        )
                for cash_index, cash_entry in enumerate(item.cash_entries):
                    transaction_id = _stable_id(
                        "operator-settlement-cash-transaction",
                        item.settlement_revision_id,
                        cash_index,
                        cash_entry.transaction_kind,
                    )
                    uow.finance.insert_cash_transaction(
                        CashTransactionRow(
                            transaction_id=transaction_id,
                            account_id=item.ticket.account_id,
                            ticket_id=item.ticket.ticket_id,
                            ticket_settlement_id=item.settlement_revision_id,
                            kind=cash_entry.transaction_kind,
                            amount=cash_entry.amount_minor / 100,
                            occurred_at=completed_at,
                            idempotency_key=(
                                f"{action_command.action_id}:cash:{settlement_index}:"
                                f"{cash_index}"
                            ),
                            amount_minor=cash_entry.amount_minor,
                            currency=item.plan.currency,
                        )
                    )
                    uow.operator_result.insert_settlement_cash_link(
                        SettlementCashLinkRow(
                            settlement_cash_link_id=_stable_id(
                                "operator-settlement-cash-link",
                                item.settlement_revision_id,
                                transaction_id,
                            ),
                            settlement_revision_id=(
                                item.settlement_revision_id
                            ),
                            transaction_id=transaction_id,
                            transaction_kind=cash_entry.transaction_kind,
                            reverses_transaction_id=(
                                cash_entry.reverses_transaction_id
                            ),
                            amount_minor=cash_entry.amount_minor,
                            currency=item.plan.currency,
                        )
                    )
            if uow.operator_result.persisted_settlement_counts(run_id) != (
                len(prepared),
                note_count,
                leg_count,
                cash_count,
            ):
                raise ValueError("settlement child counts do not reconcile")
            persisted_run = uow.operator_result.task_settlement_run(run_id)
            if persisted_run is None or (
                persisted_run.requested_ticket_count,
                persisted_run.eligible_ticket_count,
                persisted_run.settled_ticket_count,
                persisted_run.skipped_ticket_count,
                persisted_run.persisted_settlement_count,
                persisted_run.persisted_note_grade_count,
                persisted_run.persisted_leg_grade_count,
                persisted_run.persisted_cash_count,
                persisted_run.ticket_settlement_revision_ids,
            ) != (
                len(ticket_ids),
                len(prepared),
                len(prepared),
                len(skips),
                len(prepared),
                note_count,
                leg_count,
                cash_count,
                settlement_ids,
            ):
                raise ValueError("settlement run counts do not reconcile")
            if len(uow.operator_result.task_settlement_skips(run_id)) != len(skips):
                raise ValueError("settlement skip counts do not reconcile")
            expected_stake_minor = sum(item.plan.stake_minor for item in prepared)
            expected_payout_minor = sum(
                item.plan.gross_payout_minor for item in prepared
            )
            expected_cash_minor = sum(
                cash_entry.amount_minor
                for item in prepared
                for cash_entry in item.cash_entries
            )
            financials = uow.operator_result.settlement_financial_totals(run_id)
            if (
                financials.settlement_stake_minor,
                financials.note_stake_minor,
                financials.settlement_distinct_note_count,
                financials.settlement_payout_minor,
                financials.note_payout_minor,
                financials.cash_link_count,
                financials.ledger_cash_count,
                financials.cash_link_amount_minor,
                financials.ledger_cash_amount_minor,
                financials.cash_mismatch_count,
            ) != (
                expected_stake_minor,
                expected_stake_minor,
                note_count,
                expected_payout_minor,
                expected_payout_minor,
                cash_count,
                cash_count,
                expected_cash_minor,
                expected_cash_minor,
                0,
            ):
                raise ValueError("settlement financial totals do not reconcile")
            if prepared:
                settled_ticket_ids = tuple(
                    item.ticket.ticket_id for item in prepared
                )
                baseline_id = (
                    uow.operator_result.settlement_baseline_revision_id(
                        task_family_id=settlement_request.task_family_id,
                        work_item_id=settlement_request.work_item_id,
                        task_snapshot_hash=settlement_request.task_snapshot_hash,
                        ticket_ids=settled_ticket_ids,
                    )
                )
                eligibility_document = {
                    "terminal_trigger": "settlement",
                    "task_family_id": settlement_request.task_family_id,
                    "work_item_id": settlement_request.work_item_id,
                    "task_snapshot_hash": settlement_request.task_snapshot_hash,
                    "settlement_run_id": run_id,
                    "market_prior_baseline_revision_id": baseline_id,
                    "review_kind": "forecast_truth",
                    "readiness_condition": "outcomes_required",
                }
                uow.operator_result.insert_review_eligibility_fact(
                    ReviewEligibilityFactRow(
                        review_eligibility_fact_id=_stable_id(
                            "review-eligibility",
                            action_command.action_id,
                            0,
                            eligibility_document,
                        ),
                        action_id=action_command.action_id,
                        fact_index=0,
                        terminal_trigger="settlement",
                        task_family_id=settlement_request.task_family_id,
                        work_item_id=settlement_request.work_item_id,
                        task_snapshot_hash=settlement_request.task_snapshot_hash,
                        no_ticket_revision_id=None,
                        artifact_terminal_receipt_id=None,
                        market_prior_baseline_revision_id=baseline_id,
                        review_kind="forecast_truth",
                        readiness_condition="outcomes_required",
                        content_hash=_content_hash(eligibility_document),
                        created_at=completed_at,
                        settlement_run_id=run_id,
                    )
                )
            uow.operator_decision.complete_worker_job(
                worker_job_id=request.worker_job_id,
                lease_owner=request.lease_owner,
                result_action_id=action_command.action_id,
                result_object_type="operator_task_settlement_run",
                result_object_id=run_id,
                completed_at=completed_at,
            )
            return (ObjectRef("operator_task_settlement_run", run_id),)

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    @staticmethod
    def _validated_result_manifest(
        manifest: ResultEvidenceManifestV1,
    ) -> ResultEvidenceManifestV1:
        return ResultEvidenceManifestV1.model_validate(
            manifest.model_dump(mode="python")
        )

    @staticmethod
    def _assert_result_retrieval(
        uow,
        *,
        retrieval_id: str,
        source_kind: str,
        captured_at: datetime | None,
        published_at: datetime | None = None,
    ) -> None:
        row = (
            uow.connection.execute(
                select(
                    schema.artifact_retrievals.c.source_name,
                    schema.artifact_retrievals.c.source_type,
                    schema.artifact_retrievals.c.reported_content_type,
                    schema.artifact_retrievals.c.canonical_url,
                    schema.artifact_retrievals.c.published_at,
                    schema.artifact_retrievals.c.retrieved_at,
                    schema.artifact_retrievals.c.status,
                    schema.source_runs.c.source_name.label("run_source_name"),
                    schema.source_runs.c.source_type.label("run_source_type"),
                    schema.source_runs.c.status.label("run_status"),
                )
                .select_from(
                    schema.artifact_retrievals.join(
                        schema.source_runs,
                        schema.artifact_retrievals.c.source_run_id
                        == schema.source_runs.c.source_run_id,
                    )
                )
                .where(
                    schema.artifact_retrievals.c.artifact_retrieval_id
                    == retrieval_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ValueError("result source retrieval does not exist")
        if (
            row["source_type"] != source_kind
            or row["run_source_type"] != source_kind
            or row["source_name"] != row["run_source_name"]
        ):
            raise ValueError("result source kind does not match retrieval provenance")
        if (
            row["status"] != "stored"
            or row["run_status"] != "succeeded"
            or row["reported_content_type"] != "application/json"
        ):
            raise ValueError("result source retrieval must be stored by a successful run")
        if captured_at is not None and (
            datetime.fromisoformat(row["retrieved_at"]).astimezone(UTC)
            != captured_at.astimezone(UTC)
        ):
            raise ValueError("result source captured_at does not match retrieval")
        if published_at is not None:
            stored_published_at = row["published_at"]
            if stored_published_at is None or (
                datetime.fromisoformat(stored_published_at).astimezone(UTC)
                != published_at.astimezone(UTC)
            ):
                raise ValueError("prize published_at does not match official retrieval")
        if source_kind == "sporttery_game90":
            hostname = urlsplit(row["canonical_url"] or "").hostname or ""
            if (
                row["source_name"] != "sporttery"
                or (hostname != "sporttery.cn" and not hostname.endswith(".sporttery.cn"))
            ):
                raise ValueError("official Sporttery gameNo=90 retrieval is required")

    @classmethod
    def _preflight_result_import(
        cls,
        uow,
        manifest: ResultEvidenceManifestV1,
        *,
        requested_at: datetime,
    ) -> tuple[dict[tuple[str, str], object], str]:
        if manifest.result_cutoff_at > requested_at:
            raise ValueError("result cutoff cannot be later than the Action request")
        slate = uow.operator_sale.slate_revision(manifest.slate_revision_token)
        if slate is None:
            raise ValueError("result slate revision does not exist")
        if slate.lane != manifest.lane or slate.business_key != manifest.business_key:
            raise ValueError("result manifest task does not match its slate")
        offers = uow.operator_sale.offer_revisions_for_slate(slate.slate_revision_id)
        offers_by_identity = {
            (offer.official_match_no, offer.match_id): offer for offer in offers
        }
        declared_identities = {
            (match.official_match_no, match.canonical_match_id)
            for match in manifest.matches
        }
        if declared_identities != set(offers_by_identity):
            raise ValueError("result manifest match set does not match its slate")

        for match in manifest.matches:
            if {source.source_kind for source in match.sources} != RESULT_SOURCE_KINDS:
                raise ValueError("result manifest source set is incomplete")
            for source in match.sources:
                if source.receipt_state == "missing":
                    continue
                cls._assert_result_retrieval(
                    uow,
                    retrieval_id=source.artifact_retrieval_id or "",
                    source_kind=source.source_kind,
                    captured_at=source.captured_at,
                )

        prize = manifest.zucai_prize_table
        if prize is not None:
            if prize.published_at > requested_at:
                raise ValueError("prize publication cannot be later than the Action request")
            cls._assert_result_retrieval(
                uow,
                retrieval_id=prize.official_artifact_retrieval_id,
                source_kind="sporttery_game90",
                captured_at=None,
                published_at=prize.published_at,
            )

        scope_document = {
            "families": sorted(
                offer.official_offer_family_id for offer in offers_by_identity.values()
            ),
            "revisions": sorted(
                offer.official_offer_revision_id for offer in offers_by_identity.values()
            ),
        }
        scope_key = hashlib.sha256(
            canonical_json(scope_document).encode("utf-8")
        ).hexdigest()[:16]
        task_family_id = f"{manifest.lane}:{manifest.business_key}"
        persisted_work_items = (
            uow.operator_decision.baseline_work_item_ids_for_task_snapshot(
                task_family_id=task_family_id,
                task_snapshot_hash=manifest.task_snapshot_token,
                slate_revision_id=manifest.slate_revision_token,
            )
        )
        if len(persisted_work_items) > 1:
            raise ValueError("result task snapshot maps to multiple work items")
        work_item_id = (
            persisted_work_items[0]
            if persisted_work_items
            else (
                f"{task_family_id}:{manifest.task_snapshot_token}:"
                f"sale_wave:{scope_key}"
            )
        )
        return offers_by_identity, work_item_id

    def import_result_evidence_set(
        self,
        request: ImportResultEvidenceRequest,
    ) -> ResultImportResult:
        manifest = self._validated_result_manifest(request.manifest)
        command = ActionCommand.create(
            action_type="import_result_evidence_set",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "manifest": manifest.model_dump(mode="json"),
                "importer_version": request.importer_version,
            },
        )

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            offers_by_identity, work_item_id = self._preflight_result_import(
                uow,
                manifest,
                requested_at=request.requested_at,
            )
            task_family_id = f"{manifest.lane}:{manifest.business_key}"
            current = uow.operator_result.current_result_set(
                lane=manifest.lane,
                business_key=manifest.business_key,
            )
            expected_parent = (
                None if current is None else current.result_set_revision_id
            )
            if manifest.supersedes_result_set_token != expected_parent:
                raise ValueError("result import must supersede the current result set")
            family = uow.operator_result.result_set_family(
                lane=manifest.lane,
                business_key=manifest.business_key,
            )
            family_id = _stable_id(
                "operator-result-set-family",
                manifest.lane,
                manifest.business_key,
            )
            if family is not None and (
                family.result_set_family_id != family_id
                or family.task_family_id != task_family_id
            ):
                raise ValueError("result set family identity is inconsistent")

            prize_table_id: str | None = None
            prize = manifest.zucai_prize_table
            current_prize = uow.operator_result.current_prize_table(
                manifest.business_key
            )
            if prize is not None:
                expected_prize_parent = (
                    None
                    if current_prize is None
                    else current_prize.prize_table_revision_id
                )
                if prize.supersedes_prize_table_token != expected_prize_parent:
                    raise ValueError(
                        "prize import must supersede the current prize table"
                    )
            elif current_prize is not None:
                raise ValueError("current Zucai prize table must be carried by corrections")

            normalized_matches = tuple(
                (match, normalize_match_result(match.sources))
                for match in manifest.matches
            )
            outcome_count = sum(
                normalized.agreement_state == "agreed"
                and normalized.result_disposition in {"played_90", "official_void"}
                for _match, normalized in normalized_matches
            )
            result_content_hash = _content_hash(
                {
                    "manifest_sha256": manifest.manifest_sha256,
                    "importer_version": request.importer_version,
                }
            )
            revision_no = 1 if current is None else current.revision_no + 1
            result_set_id = _stable_id(
                "operator-result-set",
                family_id,
                revision_no,
                result_content_hash,
            )
            now = _utc(request.requested_at)

            if prize is not None:
                prize_family_id = _stable_id(
                    "zucai-prize-table-family",
                    prize.issue,
                    prize.currency,
                )
                prize_revision_no = (
                    1 if current_prize is None else current_prize.revision_no + 1
                )
                prize_content_hash = _content_hash(
                    prize.model_dump(mode="json", exclude={"supersedes_prize_table_token"})
                )
                prize_table_id = _stable_id(
                    "zucai-prize-table",
                    prize_family_id,
                    prize_revision_no,
                    prize_content_hash,
                )
                uow.operator_result.insert_prize_table_revision(
                    ZucaiPrizeTableRevisionRow(
                        prize_table_revision_id=prize_table_id,
                        prize_table_family_id=prize_family_id,
                        revision_no=prize_revision_no,
                        supersedes_revision_id=(
                            None
                            if current_prize is None
                            else current_prize.prize_table_revision_id
                        ),
                        issue=prize.issue,
                        currency=prize.currency,
                        published_at=_utc(prize.published_at),
                        source_artifact_retrieval_id=(
                            prize.official_artifact_retrieval_id
                        ),
                        tier_count=len(prize.tiers),
                        content_hash=prize_content_hash,
                        action_id=action_command.action_id,
                        created_at=now,
                    )
                )
                for tier_index, tier in enumerate(prize.tiers):
                    uow.operator_result.insert_prize_table_tier(
                        ZucaiPrizeTableTierRow(
                            prize_table_tier_id=_stable_id(
                                "zucai-prize-table-tier",
                                prize_table_id,
                                tier.tier_code,
                            ),
                            prize_table_revision_id=prize_table_id,
                            tier_index=tier_index,
                            tier_code=tier.tier_code,
                            ticket_kind=tier.ticket_kind,
                            required_correct_count=tier.required_correct_count,
                            official_winning_note_count=(
                                tier.official_winning_note_count
                            ),
                            payout_minor_per_winning_note=(
                                tier.payout_minor_per_winning_note
                            ),
                        )
                    )

            if family is None:
                uow.operator_result.insert_result_set_family(
                    ResultSetFamilyRow(
                        result_set_family_id=family_id,
                        task_family_id=task_family_id,
                        lane=manifest.lane,
                        business_key=manifest.business_key,
                        created_at=now,
                    )
                )
            uow.operator_result.insert_result_set_revision(
                ResultSetRevisionRow(
                    result_set_revision_id=result_set_id,
                    result_set_family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=expected_parent,
                    task_family_id=task_family_id,
                    work_item_id=work_item_id,
                    lane=manifest.lane,
                    business_key=manifest.business_key,
                    task_snapshot_hash=manifest.task_snapshot_token,
                    slate_revision_id=manifest.slate_revision_token,
                    result_cutoff_at=_utc(manifest.result_cutoff_at),
                    importer_version=request.importer_version,
                    zucai_prize_table_revision_id=prize_table_id,
                    match_count=len(manifest.matches),
                    source_receipt_count=len(manifest.matches) * 3,
                    outcome_count=outcome_count,
                    content_hash=result_content_hash,
                    action_id=action_command.action_id,
                    created_at=now,
                )
            )

            refs: list[ObjectRef] = [
                ObjectRef("operator_result_set_revision", result_set_id)
            ]
            outcome_index = 0
            for match_index, (match, normalized) in enumerate(normalized_matches):
                offer = offers_by_identity[
                    (match.official_match_no, match.canonical_match_id)
                ]
                match_result_id = _stable_id(
                    "operator-match-result",
                    result_set_id,
                    match_index,
                    match.canonical_match_id,
                )
                uow.operator_result.insert_result_match_revision(
                    ResultMatchRevisionRow(
                        match_result_revision_id=match_result_id,
                        result_set_revision_id=result_set_id,
                        match_index=match_index,
                        official_match_no=match.official_match_no,
                        official_offer_revision_id=offer.official_offer_revision_id,
                        match_id=match.canonical_match_id,
                        normalized_disposition=normalized.result_disposition,
                        normalized_home_90=normalized.home_90,
                        normalized_away_90=normalized.away_90,
                        agreement_state=normalized.agreement_state,
                    )
                )
                sources_by_kind = {
                    source.source_kind: source for source in match.sources
                }
                for source_index, source_kind in enumerate(_RESULT_SOURCE_ORDER):
                    source = sources_by_kind[source_kind]
                    source_receipt_id = _stable_id(
                        "operator-result-source",
                        match_result_id,
                        source_kind,
                    )
                    uow.operator_result.insert_result_source_receipt(
                        ResultSourceReceiptRow(
                            result_source_receipt_id=source_receipt_id,
                            match_result_revision_id=match_result_id,
                            source_index=source_index,
                            source_kind=source.source_kind,
                            source_artifact_retrieval_id=(
                                source.artifact_retrieval_id
                            ),
                            captured_at=(
                                None
                                if source.captured_at is None
                                else _utc(source.captured_at)
                            ),
                            source_disposition=source.source_disposition,
                            home_90=source.home_90,
                            away_90=source.away_90,
                            receipt_state=source.receipt_state,
                            invalid_code=source.invalid_code,
                        )
                    )
                if not (
                    normalized.agreement_state == "agreed"
                    and normalized.result_disposition
                    in {"played_90", "official_void"}
                ):
                    continue
                current_outcome = uow.operator_result.current_outcome_for_match(
                    match.canonical_match_id
                )
                outcome_family_id = _stable_id(
                    "operator-outcome-family",
                    match.canonical_match_id,
                )
                outcome_revision_no = (
                    1 if current_outcome is None else current_outcome.revision_no + 1
                )
                outcome_id = _stable_id(
                    "operator-outcome",
                    outcome_family_id,
                    outcome_revision_no,
                    result_set_id,
                )
                retrieval_ids = tuple(
                    sorted(
                        source.artifact_retrieval_id or ""
                        for source in match.sources
                    )
                )
                uow.operator_result.insert_outcome_revision(
                    OperatorOutcomeRevisionRow(
                        outcome_revision_id=outcome_id,
                        outcome_family_id=outcome_family_id,
                        revision_no=outcome_revision_no,
                        supersedes_revision_id=(
                            None
                            if current_outcome is None
                            else current_outcome.outcome_revision_id
                        ),
                        outcome_index=outcome_index,
                        match_id=match.canonical_match_id,
                        match_result_revision_id=match_result_id,
                        result_set_revision_id=result_set_id,
                        result_disposition=normalized.result_disposition or "",
                        home_90=normalized.home_90,
                        away_90=normalized.away_90,
                        source_artifact_retrieval_ids=retrieval_ids,
                        recorded_at=now,
                        action_id=action_command.action_id,
                    )
                )
                refs.append(ObjectRef("operator_outcome_revision", outcome_id))
                outcome_index += 1

            expected_counts = (
                len(manifest.matches),
                len(manifest.matches) * 3,
                outcome_count,
            )
            if (
                uow.operator_result.persisted_result_counts(result_set_id)
                != expected_counts
            ):
                raise ValueError("result import child counts do not reconcile")
            if prize_table_id is not None:
                tiers = uow.operator_result.prize_table_tiers(prize_table_id)
                if len(tiers) != 3:
                    raise ValueError("prize-table tier counts do not reconcile")
                refs.append(
                    ObjectRef("zucai_prize_table_revision", prize_table_id)
                )
            return tuple(refs)

        outcome = self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )
        return self._hydrate_result_import(outcome)

    def _hydrate_result_import(self, outcome: ActionOutcome) -> ResultImportResult:
        empty_counts = ResultImportCounts(0, 0, 0, 0, 0, 0, 0)
        if not outcome.status.is_success:
            return ResultImportResult(
                outcome=outcome,
                result_set=None,
                match_results=(),
                source_receipts=(),
                outcomes=(),
                prize_table=None,
                prize_tiers=(),
                counts=empty_counts,
            )
        result_ref = next(
            (
                ref
                for ref in outcome.result_refs
                if ref.object_type == "operator_result_set_revision"
            ),
            None,
        )
        if result_ref is None:
            raise ValueError("result import Action has no result-set reference")
        with self._action_service.unit_of_work() as uow:
            result_set = uow.operator_result.result_set_revision(result_ref.object_id)
            matches = uow.operator_result.result_matches_for_set(result_ref.object_id)
            receipts = uow.operator_result.result_source_receipts_for_set(
                result_ref.object_id
            )
            outcomes = uow.operator_result.outcomes_for_result_set(
                result_ref.object_id
            )
            if result_set is None:
                raise ValueError("result import Action references a missing result set")
            prize_table = (
                None
                if result_set.zucai_prize_table_revision_id is None
                else uow.operator_result.prize_table_revision(
                    result_set.zucai_prize_table_revision_id
                )
            )
            prize_tiers = (
                ()
                if prize_table is None
                else uow.operator_result.prize_table_tiers(
                    prize_table.prize_table_revision_id
                )
            )
            persisted_counts = uow.operator_result.persisted_result_counts(
                result_ref.object_id
            )
        agreement_counts = {
            state: sum(match.agreement_state == state for match in matches)
            for state in ("agreed", "conflict", "missing")
        }
        linked_counts = (
            result_set.match_count,
            result_set.source_receipt_count,
            result_set.outcome_count,
        )
        if (
            persisted_counts != linked_counts
            or len(matches) != linked_counts[0]
            or len(receipts) != linked_counts[1]
            or len(outcomes) != linked_counts[2]
            or (result_set.zucai_prize_table_revision_id is not None)
            != (prize_table is not None)
        ):
            raise ValueError("result import cannot be reconciled")
        counts = ResultImportCounts(
            match_count=len(matches),
            source_receipt_count=len(receipts),
            outcome_count=len(outcomes),
            agreed_count=agreement_counts["agreed"],
            conflict_count=agreement_counts["conflict"],
            missing_count=agreement_counts["missing"],
            prize_tier_count=len(prize_tiers),
        )
        return ResultImportResult(
            outcome=outcome,
            result_set=result_set,
            match_results=matches,
            source_receipts=receipts,
            outcomes=outcomes,
            prize_table=prize_table,
            prize_tiers=prize_tiers,
            counts=counts,
        )

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
                self._insert_band_outcomes(
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
            if not candidate_set.candidates and not candidate_set.band_outcomes:
                raise ValueError("candidate sets require candidates or band outcomes")
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
        cls._validate_band_outcomes(candidate_set)

    @staticmethod
    def _validate_band_outcomes(candidate_set) -> None:
        has_band_candidates = any(
            candidate.odds_band is not None for candidate in candidate_set.candidates
        )
        if not has_band_candidates and not candidate_set.band_outcomes:
            return
        expected_bands = {"10x", "20x", "50x", "100x"}
        outcomes = {outcome.odds_band: outcome for outcome in candidate_set.band_outcomes}
        if set(outcomes) != expected_bands or len(outcomes) != len(
            candidate_set.band_outcomes
        ):
            raise ValueError("candidate set requires one outcome for every odds band")
        counts = {
            band: sum(
                candidate.odds_band == band for candidate in candidate_set.candidates
            )
            for band in expected_bands
        }
        for band, outcome in outcomes.items():
            if outcome.candidate_count != counts[band]:
                raise ValueError("candidate band outcome count does not reconcile")
            if counts[band] > 0:
                if outcome.status != "candidates" or outcome.reason_code is not None:
                    raise ValueError("populated odds band must have candidates status")
            elif (
                outcome.status != "no_feasible_candidate"
                or not str(outcome.reason_code or "").strip()
            ):
                raise ValueError("empty odds band requires a reason code")

    @classmethod
    def _validate_candidate(cls, uow, generation, envelope, candidate) -> None:
        if set(candidate.completed_audit_kinds) != _AUDIT_KINDS:
            raise ValueError("every candidate must complete all four audit kinds")
        if len(candidate.completed_audit_kinds) != len(_AUDIT_KINDS):
            raise ValueError("candidate audit completion kinds must be unique")
        _required(candidate.content_hash, "candidate content_hash")
        cls._validate_candidate_band(candidate)
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
    def _validate_candidate_band(candidate) -> None:
        fields = (
            candidate.odds_band,
            candidate.target_odds_min_decimal,
            candidate.target_odds_max_decimal,
            candidate.combined_decimal_odds,
        )
        if all(value is None for value in fields):
            if (candidate.parent_candidate_revision_id is None) != (
                candidate.delta_reason is None
            ):
                raise ValueError("candidate parent and delta reason must be paired")
            return
        if any(value is None for value in fields):
            raise ValueError("candidate odds band metadata must be complete")
        if candidate.odds_band not in {"10x", "20x", "50x", "100x"}:
            raise ValueError("candidate odds band is not registered")
        minimum = _decimal(
            candidate.target_odds_min_decimal,
            name="target_odds_min_decimal",
        )
        maximum = _decimal(
            candidate.target_odds_max_decimal,
            name="target_odds_max_decimal",
        )
        combined = _decimal(
            candidate.combined_decimal_odds,
            name="combined_decimal_odds",
        )
        if minimum <= Decimal("1") or not minimum <= combined <= maximum:
            raise ValueError("candidate combined odds are outside the target interval")
        if (candidate.parent_candidate_revision_id is None) != (
            candidate.delta_reason is None
        ):
            raise ValueError("candidate parent and delta reason must be paired")
        if candidate.delta_reason is not None:
            _required(candidate.delta_reason, "candidate delta_reason")

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
                    odds_band=candidate.odds_band,
                    target_odds_min_decimal=candidate.target_odds_min_decimal,
                    target_odds_max_decimal=candidate.target_odds_max_decimal,
                    combined_decimal_odds=candidate.combined_decimal_odds,
                    parent_candidate_revision_id=(
                        candidate.parent_candidate_revision_id
                    ),
                    delta_reason=candidate.delta_reason,
                )
            )
            cls._insert_candidate_children(uow, candidate_id, candidate)

    @staticmethod
    def _insert_band_outcomes(uow, *, set_id: str, candidate_set) -> None:
        for outcome in candidate_set.band_outcomes:
            uow.operator_result.insert_candidate_band_outcome(
                CandidateBandOutcomeRow(
                    candidate_band_outcome_id=_stable_id(
                        "operator-candidate-band-outcome",
                        set_id,
                        outcome.odds_band,
                    ),
                    candidate_set_revision_id=set_id,
                    odds_band=outcome.odds_band,
                    status=outcome.status,
                    candidate_count=outcome.candidate_count,
                    reason_code=outcome.reason_code,
                )
            )

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
    "CandidateBandOutcomeInput",
    "CandidateDeadFaceInput",
    "CandidateMetricsInput",
    "CandidateSetInput",
    "CandidateTicketInput",
    "CandidateTicketLegInput",
    "GenerateTicketCandidateSetRequest",
    "ImportResultEvidenceRequest",
    "OperatorResultActions",
    "RegisterZucaiFixedPrizePolicyRequest",
    "RequestSettlementRequest",
    "ResultImportCounts",
    "ResultImportResult",
    "SettleTaskRequest",
    "TicketCandidateInput",
]
