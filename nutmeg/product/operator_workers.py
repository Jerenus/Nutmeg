"""Durable infrastructure workers for governed operator Actions."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from nutmeg.decision.legs_audit import Leg, audit_legs
from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionOutcome, ActorRole, canonical_json
from nutmeg.ontology.actions.protected_ticket_actions import (
    CurrentOperatorCandidateAudit,
    CurrentOperatorCandidateAuditFinding,
    MarkTicketShadowRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError, PermissionDeniedError
from nutmeg.ontology.operator.confirmation import effective_artifact_cutoff
from nutmeg.ontology.operator.decision_actions import (
    FreezeMarketPriorBaselineRequest,
    OperatorDecisionActions,
)
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    LinkTaskEvidenceFreezeRequest,
)
from nutmeg.ontology.operator.result_actions import (
    CandidateAuditFindingInput,
    CandidateDeadFaceInput,
    CandidateMetricsInput,
    CandidateSetInput,
    CandidateTicketInput,
    CandidateTicketLegInput,
    GenerateTicketCandidateSetRequest,
    OperatorResultActions,
    SettleTaskRequest,
    TicketCandidateInput,
)
from nutmeg.ontology.operator.review_actions import (
    CompleteScoreboardReviewRequest,
    MaterializeOperatorReviewItemRequest,
    OperatorReviewActions,
)
from nutmeg.ontology.repository import (
    schema_market,
)
from nutmeg.ontology.repository import (
    schema_operator_decision as sod,
)
from nutmeg.product.operator_candidates import (
    CandidateAuditFinding,
    CandidateComparison,
    CandidateDraft,
    CandidateGenerationInput,
    CandidateStructureTemplate,
    CandidateTicket,
    CandidateTicketLeg,
    FaceBundleOption,
    OfferCandidateInput,
    enumerate_candidates,
)
from nutmeg.product.operator_runtime import OntologyWriterLease

_CANDIDATE_GENERATOR_VERSION = "operator-candidate-v1"
_CANDIDATE_AUDIT_POLICY_VERSION = "operator-candidate-audit-v1"
_DECIMAL_QUANTUM = Decimal("0.000000000001")
_STANDARD_JCZQ_UNIT_STAKE_MINOR = 200
_SUPPORTED_SETTLEMENT_MARKETS = {
    "jczq": frozenset({"md-had", "md-hhad", "md-ttg", "md-crs"}),
    "zucai": frozenset({"md-had"}),
}


class OperatorProjectionSignals:
    """Process-local wakeups backed by durable projection cursors."""

    def __init__(
        self,
        *,
        delivered_sequence: int = 0,
        invalidated_sequence: int = 0,
    ) -> None:
        if delivered_sequence < 0 or invalidated_sequence < 0:
            raise ValueError("projection sequences must be non-negative")
        self._condition = threading.Condition()
        self._delivered_sequence = delivered_sequence
        self._invalidated_sequence = invalidated_sequence

    @property
    def delivered_sequence(self) -> int:
        with self._condition:
            return self._delivered_sequence

    @property
    def invalidated_sequence(self) -> int:
        with self._condition:
            return self._invalidated_sequence

    def deliver(self, event) -> None:
        with self._condition:
            self._delivered_sequence = max(
                self._delivered_sequence,
                int(event.sequence),
            )
            self._condition.notify_all()

    def invalidate(self, event) -> None:
        with self._condition:
            self._invalidated_sequence = max(
                self._invalidated_sequence,
                int(event.sequence),
            )

    def wait_for_delivery(self, *, after: int, timeout_seconds: float) -> bool:
        if after < 0 or timeout_seconds < 0:
            raise ValueError("delivery wait bounds must be non-negative")
        with self._condition:
            return self._condition.wait_for(
                lambda: self._delivered_sequence > after,
                timeout=timeout_seconds,
            )


class OperatorInfrastructureWorkers:
    """Run the bounded operator consumers under one application lifespan."""

    _ORDER = (
        "evidence_freeze",
        "market_baseline",
        "candidate_generation",
        "confirmation_deadlines",
        "task_settlement",
        "review_materialization",
        "scoreboard_review_completion",
        "outbox",
        "read_model",
    )

    def __init__(
        self,
        *,
        data_dir: Path,
        clock,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 100,
        evidence_freeze=None,
        market_baseline=None,
        candidate_generation=None,
        confirmation_deadlines=None,
        task_settlement=None,
        review_materialization=None,
        scoreboard_review_completion=None,
        outbox=None,
        read_model=None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("worker poll interval must be positive")
        if batch_size <= 0:
            raise ValueError("worker batch size must be positive")
        self._data_dir = data_dir.resolve()
        self._clock = clock
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        supplied = locals()
        self._workers = tuple(
            supplied[name] for name in self._ORDER if supplied[name] is not None
        )
        self._accepting = False
        self._workers_stopped = False
        self._workers_closed = False
        self._cycle_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    @property
    def worker_names(self) -> tuple[str, ...]:
        return tuple(type(worker).__name__ for worker in self._workers)

    async def start(self) -> None:
        if self._task is not None:
            return
        if self._workers_closed:
            raise RuntimeError("operator infrastructure workers are closed")
        self._accepting = True
        await self._run_cycle()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="nutmeg-operator-infrastructure",
        )

    def stop_accepting(self) -> None:
        self._accepting = False
        if self._workers_stopped:
            return
        self._workers_stopped = True
        for worker in reversed(self._workers):
            stop = getattr(worker, "stop_accepting", None)
            if stop is not None:
                stop()

    async def drain_current_transactions(self) -> None:
        async with self._cycle_lock:
            return

    async def close(self) -> None:
        self.stop_accepting()
        await self.drain_current_transactions()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._workers_closed:
            return
        self._workers_closed = True
        for worker in reversed(self._workers):
            close = getattr(worker, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result

    @asynccontextmanager
    async def lifespan(self, _app):
        await self.start()
        try:
            yield
        finally:
            self.stop_accepting()
            await self.drain_current_transactions()
            await self.close()

    async def _run_loop(self) -> None:
        while self._accepting:
            await asyncio.sleep(self._poll_interval_seconds)
            if self._accepting:
                await self._run_cycle()

    async def _run_cycle(self) -> None:
        async with self._cycle_lock:
            await asyncio.to_thread(self._run_cycle_sync)

    def _run_cycle_sync(self) -> None:
        if not self._workers:
            return
        as_of = _aware(self._clock(), "worker clock").astimezone(UTC)
        with OntologyWriterLease.shared(self._data_dir):
            for worker in self._workers:
                worker.run_once(limit=self._batch_size, as_of=as_of)


class _OutboxProjectionWorker:
    consumer_name: str

    def __init__(self, *, unit_of_work_factory, project_event=None) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._project_event = project_event or (lambda _event: None)

    def run_once(self, *, limit: int, as_of: datetime):
        at = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._unit_of_work_factory() as uow:
            cursor = uow.outbox.consumer_cursor(self.consumer_name)
            events = tuple(uow.outbox.after(cursor, limit=limit))
        for event in events:
            self._project_event(event)
            with self._unit_of_work_factory() as uow:
                uow.outbox.advance_consumer_cursor(
                    self.consumer_name,
                    expected_sequence=cursor,
                    next_sequence=event.sequence,
                    updated_at=at.isoformat(),
                )
            cursor = event.sequence
        return events


class ProductOutboxWorker(_OutboxProjectionWorker):
    """Advance the durable server-delivery cursor over committed outbox rows."""

    consumer_name = "product_sse_delivery"


class OperatorReadModelInvalidator(_OutboxProjectionWorker):
    """Advance the durable invalidation cursor consumed by fresh operator reads."""

    consumer_name = "operator_read_model_invalidation"


@dataclass(frozen=True, slots=True)
class _CandidateAuditOffer:
    official_match_no: str
    market_definition_id: str
    belief: tuple[tuple[str, str], ...]
    prior: tuple[tuple[str, str], ...]
    prescribed_face_bundles: tuple[frozenset[str], ...]
    rule_ids: tuple[str, ...]
    # 操作员登记的结构事实。C5/C7/C13/C14 只读这两项；缺省的 "unknown"/() 不是
    # "没问题",而是"没登记"——昂贵排除因此仍然亮 WARN。
    anchor_integrity: str = "unknown"
    face_precedents: tuple[tuple[str, str, str], ...] = ()


class ConfirmationDeadlineWorker:
    """Boundedly terminalize protected artifacts whose effective cutoff is due."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        protected_tickets,
        worker_id: str,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self._action_service = action_service
        self._protected_tickets = protected_tickets
        self._worker_id = worker_id

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        at = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            artifact_ids = uow.tickets.open_protected_artifact_ids(
                limit=max(limit * 10, limit)
            )

        outcomes: list[ActionOutcome] = []
        for artifact_id in artifact_ids:
            if len(outcomes) >= limit:
                break
            with self._action_service.unit_of_work() as uow:
                binding = uow.tickets.protected_artifact_binding(artifact_id)
                links = uow.tickets.protected_artifact_offer_revision_links(
                    artifact_id
                )
                current_offers = tuple(
                    current
                    for link in links
                    if (
                        source := uow.operator_sale.offer_revision(
                            link.official_offer_revision_id
                        )
                    )
                    is not None
                    and (
                        current := uow.operator_sale.current_offer_by_family(
                            source.official_offer_family_id
                        )
                    )
                    is not None
                )
                head = uow.tickets.confirmation_challenge_head(artifact_id)
            if binding is None or len(current_offers) != len(links):
                continue
            cutoff = effective_artifact_cutoff(binding, current_offers)
            cancelled = any(offer.status == "cancelled" for offer in current_offers)
            closed = any(offer.status == "sale_closed" for offer in current_offers)
            if not cancelled and not closed and at < cutoff:
                continue
            if cancelled:
                reason = "official_offer_cancelled"
            elif closed and at < cutoff:
                reason = "official_deadline_shortened"
            else:
                reason = (
                    "confirmation_not_requested"
                    if head is None
                    else "deadline_unconfirmed"
                )
            outcome = self._protected_tickets.mark_ticket_shadow(
                MarkTicketShadowRequest(
                    ticket_artifact_id=artifact_id,
                    confirmation_id=(
                        None if head is None else head.challenge_revision_id
                    ),
                    reason=reason,
                    actor_id=f"system:{self._worker_id}",
                    actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                    idempotency_key=(
                        f"operator-confirmation-deadline:{artifact_id}:"
                        f"{cutoff.isoformat()}:{reason}"
                    ),
                    requested_at=at,
                )
            )
            outcomes.append(outcome)
        return tuple(outcomes)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _digest(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _retryable_error_code(error: Exception) -> str | None:
    if getattr(error, "retryable", False):
        return str(getattr(error, "code", "retryable_worker_error"))
    if isinstance(error, OperationalError):
        message = str(error).lower()
        if "database is locked" in message or "database is busy" in message:
            return "sqlite_contention"
    return None


def _terminal_error_code(error: Exception) -> str:
    stable_code = getattr(error, "code", None)
    if isinstance(stable_code, str) and stable_code in {
        "evidence_conflict",
        "evidence_missing",
        "stale_dependency",
    }:
        return stable_code
    if isinstance(error, OptimisticConcurrencyError):
        return "stale_dependency"
    if isinstance(error, PermissionDeniedError):
        return "permission_denied"
    return "invariant_failure"


class EvidenceFreezeRequestWorker:
    """Claim evidence-freeze requests and complete only through typed Actions."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        evidence_actions: EvidenceActions,
        bundle_actions: BundleActions,
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._evidence_actions = evidence_actions
        self._bundle_actions = bundle_actions
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="evidence_freeze",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="evidence_freeze",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self.process_evidence_freeze_request(
                    job.source_object_id,
                    as_of=cutoff,
                )
            except Exception as error:
                with self._action_service.unit_of_work() as uow:
                    retry_code = _retryable_error_code(error)
                    if retry_code is None:
                        uow.operator_decision.fail_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=_terminal_error_code(error),
                            failed_at=cutoff.isoformat(),
                        )
                    else:
                        delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
                        uow.operator_decision.requeue_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=retry_code,
                            available_at=(
                                cutoff + timedelta(seconds=delay_seconds)
                            ).isoformat(),
                            updated_at=cutoff.isoformat(),
                        )
                continue
            completed.append(outcome)
        return tuple(completed)

    def process_evidence_freeze_request(
        self,
        request_id: str,
        *,
        as_of: datetime,
    ) -> ActionOutcome:
        requested_at = _aware(as_of, "as_of").astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            job = uow.operator_decision.worker_job_for_source(
                job_kind="evidence_freeze",
                source_object_type="operator_evidence_freeze_request",
                source_object_id=request_id,
            )
        if (
            job is None
            or job.state != "leased"
            or job.lease_owner != self._worker_id
        ):
            raise ValueError("evidence freeze request is not leased by this worker")

        request, gate = self._evidence_actions.freeze_plan_for_request(
            request_id,
            as_of=requested_at,
        )
        bundle_outcomes = []
        for match in sorted(gate.matches, key=lambda item: item.match_id):
            key = "operator-evidence-bundle:" + _digest(
                {
                    "request_id": request_id,
                    "dependency_fingerprint": request.dependency_fingerprint,
                    "match_id": match.match_id,
                    "candidate_observation_ids": sorted(
                        match.candidate_observation_ids
                    ),
                    "caveat_claim_ids": sorted(match.caveat_claim_ids),
                    "market_snapshot_id": match.market_snapshot_id,
                    "prior_distribution": match.prior_distribution,
                }
            )
            outcome = self._bundle_actions.freeze_bundle(
                FreezeBundleRequest(
                    match_id=match.match_id,
                    decision_session_id=None,
                    cutoff_at=gate.information_cutoff_at.astimezone(UTC).isoformat(),
                    market_snapshot_id=match.market_snapshot_id,
                    prior_distribution=dict(match.prior_distribution),
                    candidate_observation_ids=list(match.candidate_observation_ids),
                    caveat_claim_ids=list(match.caveat_claim_ids),
                    actor_id="system:operator-evidence-freeze",
                    actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                    idempotency_key=key,
                    requested_at=requested_at,
                )
            )
            if not outcome.is_success:
                raise ValueError("freeze_evidence_bundle Action did not commit")
            bundle_outcomes.append(outcome)

        bundle_action_ids = tuple(outcome.action_id for outcome in bundle_outcomes)
        link_outcome = self._evidence_actions.link_operator_task_evidence_freeze(
            LinkTaskEvidenceFreezeRequest(
                evidence_freeze_request_id=request_id,
                freeze_bundle_action_ids=bundle_action_ids,
                required_match_count=gate.required_match_count,
                bundle_count=len(bundle_action_ids),
                item_count=len(bundle_action_ids),
                lease_owner=self._worker_id,
                actor_id="system:operator-evidence-freeze",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=(
                    "operator-evidence-link:"
                    + _digest(
                        {
                            "request_id": request_id,
                            "dependency_fingerprint": request.dependency_fingerprint,
                            "bundle_action_ids": sorted(bundle_action_ids),
                        }
                    )
                ),
                requested_at=requested_at,
                policy_version=request.policy_version,
            )
        )
        if not link_outcome.is_success or len(link_outcome.result_refs) != 1:
            raise ValueError("link_operator_task_evidence_freeze Action did not commit")
        result_ref = link_outcome.result_refs[0]
        if result_ref.object_type != "task_evidence_bundle_revision":
            raise ValueError("task evidence link returned an invalid result type")
        return link_outcome


class MarketBaselineWorker:
    """Claim task evidence revisions and freeze their exact market prior."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        decision_actions: OperatorDecisionActions,
        worker_id: str,
        lease_duration: timedelta,
        work_item_id_resolver,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._decision_actions = decision_actions
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._work_item_id_resolver = work_item_id_resolver

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="market_baseline",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="market_baseline",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self.process_task_evidence_bundle(
                    job.source_object_id,
                    worker_job_id=job.worker_job_id,
                    as_of=cutoff,
                )
            except Exception as error:
                with self._action_service.unit_of_work() as uow:
                    retry_code = _retryable_error_code(error)
                    if retry_code is None:
                        uow.operator_decision.fail_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=_terminal_error_code(error),
                            failed_at=cutoff.isoformat(),
                        )
                    else:
                        delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
                        uow.operator_decision.requeue_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=retry_code,
                            available_at=(
                                cutoff + timedelta(seconds=delay_seconds)
                            ).isoformat(),
                            updated_at=cutoff.isoformat(),
                        )
                continue
            completed.append(outcome)
        return tuple(completed)

    def process_task_evidence_bundle(
        self,
        task_evidence_bundle_revision_id: str,
        *,
        worker_job_id: str,
        as_of: datetime,
    ) -> ActionOutcome:
        requested_at = _aware(as_of, "as_of").astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            job = uow.operator_decision.worker_job(worker_job_id)
            bundle = uow.operator_decision.task_evidence_bundle_revision(
                task_evidence_bundle_revision_id
            )
        if (
            job is None
            or bundle is None
            or job.job_kind != "market_baseline"
            or job.source_object_type != "task_evidence_bundle_revision"
            or job.source_object_id != task_evidence_bundle_revision_id
            or job.state != "leased"
            or job.lease_owner != self._worker_id
        ):
            raise ValueError("market baseline task is not leased by this worker")
        work_item_id = self._work_item_id_resolver(
            task_evidence_bundle_revision_id
        )
        if not isinstance(work_item_id, str) or not work_item_id.strip():
            raise ValueError("market baseline work item could not be resolved")
        idempotency_key = "operator-market-baseline:" + _digest(
            {
                "task_evidence_bundle_revision_id": (
                    task_evidence_bundle_revision_id
                ),
                "task_bundle_content_hash": bundle.content_hash,
                "work_item_id": work_item_id,
            }
        )
        outcome = self._decision_actions.freeze_market_prior_baseline(
            FreezeMarketPriorBaselineRequest(
                task_evidence_bundle_revision_id=(
                    task_evidence_bundle_revision_id
                ),
                work_item_id=work_item_id,
                actor_id="system:operator-market-baseline",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=idempotency_key,
                requested_at=requested_at,
                worker_job_id=worker_job_id,
                lease_owner=self._worker_id,
            )
        )
        if not outcome.is_success or len(outcome.result_refs) != 1:
            raise ValueError("freeze_market_prior_baseline Action did not commit")
        if outcome.result_refs[0].object_type != "market_prior_baseline_revision":
            raise ValueError("market baseline Action returned an invalid result type")
        return outcome


class CandidateGenerationWorker:
    """Claim frozen candidate requests and persist both comparison sets atomically."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        result_actions: OperatorResultActions,
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._result_actions = result_actions
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="candidate_generation",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="candidate_generation",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self.process_candidate_generation_request(
                    job.source_object_id,
                    worker_job_id=job.worker_job_id,
                    as_of=cutoff,
                )
            except Exception as error:
                with self._action_service.unit_of_work() as uow:
                    retry_code = _retryable_error_code(error)
                    if retry_code is None:
                        uow.operator_decision.fail_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=_terminal_error_code(error),
                            failed_at=cutoff.isoformat(),
                        )
                    else:
                        delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
                        uow.operator_decision.requeue_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=retry_code,
                            available_at=(
                                cutoff + timedelta(seconds=delay_seconds)
                            ).isoformat(),
                            updated_at=cutoff.isoformat(),
                        )
                continue
            completed.append(outcome)
        return tuple(completed)

    def process_candidate_generation_request(
        self,
        generation_request_id: str,
        *,
        worker_job_id: str,
        as_of: datetime,
    ) -> ActionOutcome:
        requested_at = _aware(as_of, "as_of").astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            generation = uow.operator_decision.candidate_generation_request(
                generation_request_id
            )
            job = uow.operator_decision.worker_job(worker_job_id)
            if (
                generation is None
                or job is None
                or job.job_kind != "candidate_generation"
                or job.source_object_type != "operator_candidate_generation_request"
                or job.source_object_id != generation_request_id
                or job.state != "leased"
                or job.lease_owner != self._worker_id
            ):
                raise ValueError("candidate generation request is not leased by this worker")
            _require_generation_offers_open(uow, generation, requested_at)
            (
                judgment_inputs,
                conditional_inputs,
                judgment_audit_offers,
                conditional_audit_offers,
            ) = _candidate_generation_inputs(
                uow,
                generation,
            )

        candidate_sets = tuple(
            _candidate_set_input(
                enumerate_candidates(
                    inputs,
                    set_kind=set_kind,
                    generator_version=_CANDIDATE_GENERATOR_VERSION,
                    audit_candidate=(
                        lambda draft,
                        lane=inputs.lane,
                        offers=audit_offers,
                        capital_cap_minor=inputs.capital_cap_minor: _audit_candidate(
                            draft,
                            lane=lane,
                            offers=offers,
                            capital_cap_minor=capital_cap_minor,
                        )
                    ),
                )
            )
            for set_kind, inputs, audit_offers in (
                ("judgment_bound", judgment_inputs, judgment_audit_offers),
                (
                    "conditional_market_counterfactual",
                    conditional_inputs,
                    conditional_audit_offers,
                ),
            )
        )
        outcome = self._result_actions.generate_ticket_candidate_set(
            GenerateTicketCandidateSetRequest(
                generation_request_id=generation_request_id,
                candidate_sets=candidate_sets,
                generator_version=_CANDIDATE_GENERATOR_VERSION,
                worker_job_id=worker_job_id,
                lease_owner=self._worker_id,
                actor_id="system:operator-candidates",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=(
                    "operator-candidate-generation:"
                    + _digest(
                        {
                            "generation_request_id": generation_request_id,
                            "request_content_hash": generation.content_hash,
                            "generator_version": _CANDIDATE_GENERATOR_VERSION,
                        }
                    )
                ),
                requested_at=requested_at,
            )
        )
        if not outcome.is_success or len(outcome.result_refs) != 2:
            raise ValueError("generate_ticket_candidate_set Action did not commit")
        if {ref.object_type for ref in outcome.result_refs} != {
            "ticket_candidate_set_revision"
        }:
            raise ValueError("candidate generation Action returned an invalid result type")
        return outcome


def _require_generation_offers_open(uow, generation, as_of: datetime) -> None:
    offer_ids = {
        str(row["official_offer_revision_id"])
        for row in uow.operator_decision.market_prior_baseline_probabilities(
            generation.market_prior_baseline_revision_id
        )
    }
    offers = {
        row.official_offer_revision_id: row
        for row in uow.operator_sale.offer_revisions_for_slate(
            generation.slate_revision_id
        )
    }
    if not offer_ids or not offer_ids <= set(offers):
        raise ValueError("candidate generation offer lineage is incomplete")
    for offer_id in sorted(offer_ids):
        offer = offers[offer_id]
        current = uow.operator_sale.current_offer_by_family(
            offer.official_offer_family_id
        )
        if (
            current is None
            or current.official_offer_revision_id != offer_id
            or offer.status != "on_sale"
            or as_of < datetime.fromisoformat(offer.sale_opens_at).astimezone(UTC)
            or as_of >= datetime.fromisoformat(offer.sale_deadline_at).astimezone(UTC)
        ):
            raise ValueError("candidate generation offer is closed or stale")


def _candidate_generation_inputs(uow, generation):
    bundle = uow.operator_decision.task_evidence_bundle_revision(
        generation.task_evidence_bundle_revision_id
    )
    envelope = uow.operator_decision.baseline_envelope_revision(
        generation.baseline_envelope_revision_id
    )
    prescription = uow.operator_decision.judgment_prescription_revision(
        generation.judgment_prescription_revision_id
    )
    if bundle is None or envelope is None or prescription is None:
        raise ValueError("candidate generation frozen lineage is incomplete")

    offers_by_revision = {
        offer.official_offer_revision_id: offer
        for offer in uow.operator_sale.offer_revisions_for_slate(
            generation.slate_revision_id
        )
    }
    constraints = _envelope_constraints(
        uow.connection,
        generation.baseline_envelope_revision_id,
    )
    baseline_rows = uow.operator_decision.market_prior_baseline_probabilities(
        generation.market_prior_baseline_revision_id
    )
    prescription_items = uow.operator_decision.judgment_prescription_items(
        generation.judgment_prescription_revision_id
    )
    if len(prescription_items) != prescription.required_match_count:
        raise ValueError("candidate prescription item count does not reconcile")

    judgment_offers: list[OfferCandidateInput] = []
    conditional_offers: list[OfferCandidateInput] = []
    judgment_audit_offers: list[_CandidateAuditOffer] = []
    conditional_audit_offers: list[_CandidateAuditOffer] = []
    for item in prescription_items:
        judgment = uow.operator_decision.operator_match_judgment_revision(
            item.operator_match_judgment_revision_id
        )
        if judgment is None or judgment.match_id != item.match_id:
            raise ValueError("candidate prescription judgment is unavailable")
        offer = offers_by_revision.get(judgment.official_offer_revision_id)
        market_code = uow.market.market_kind(judgment.market_definition_id)
        constraint = constraints.get((offer.official_match_no, market_code)) if offer else None
        if (
            offer is None
            or offer.match_id != judgment.match_id
            or market_code is None
            or constraint is None
        ):
            raise ValueError("candidate judgment is outside its frozen envelope")

        exact_baseline = tuple(
            row
            for row in baseline_rows
            if row["match_id"] == judgment.match_id
            and row["official_offer_revision_id"] == offer.official_offer_revision_id
            and row["market_definition_id"] == judgment.market_definition_id
        )
        if not exact_baseline:
            raise ValueError("candidate market baseline is incomplete")
        quote_ids, booked_odds, settlement_parameter = _market_bindings(
            uow,
            lane=bundle.lane,
            market_definition_id=judgment.market_definition_id,
            baseline_rows=exact_baseline,
        )
        common = {
            "official_match_no": offer.official_match_no,
            "official_offer_revision_id": offer.official_offer_revision_id,
            "match_id": offer.match_id,
            "market_definition_id": judgment.market_definition_id,
            "omission_allowed": bool(constraint["omission_allowed"]),
            "quote_ids_by_face": quote_ids,
            "booked_decimal_odds_by_face": booked_odds,
            "settlement_parameter_decimal": settlement_parameter,
        }
        judgment_probabilities = _judgment_probabilities(
            uow.connection,
            judgment.operator_match_judgment_revision_id,
        )
        baseline_probabilities = tuple(
            (str(row["face_code"]), str(row["probability_decimal"]))
            for row in exact_baseline
        )
        judgment_bundles = _judgment_face_bundles(
            uow.connection,
            judgment.operator_match_judgment_revision_id,
        )
        prescribed_face_bundles = tuple(
            frozenset(bundle.face_codes) for bundle in judgment_bundles
        )
        rule_ids = _judgment_rule_ids(
            uow.connection,
            judgment.operator_match_judgment_revision_id,
        )
        structure_facts = uow.operator_decision.operator_match_judgment_structure_facts(
            judgment.operator_match_judgment_revision_id
        )
        judgment_offers.append(
            OfferCandidateInput(
                **common,
                probabilities=judgment_probabilities,
                allowed_face_bundles=judgment_bundles,
            )
        )
        conditional_offers.append(
            OfferCandidateInput(
                **common,
                probabilities=baseline_probabilities,
                allowed_face_bundles=tuple(constraint["bundles"]),
            )
        )
        judgment_audit_offers.append(
            _CandidateAuditOffer(
                official_match_no=offer.official_match_no,
                market_definition_id=judgment.market_definition_id,
                belief=judgment_probabilities,
                prior=baseline_probabilities,
                prescribed_face_bundles=prescribed_face_bundles,
                rule_ids=rule_ids,
                anchor_integrity=structure_facts.anchor_integrity,
                face_precedents=structure_facts.face_precedents,
            )
        )
        conditional_audit_offers.append(
            _CandidateAuditOffer(
                official_match_no=offer.official_match_no,
                market_definition_id=judgment.market_definition_id,
                belief=baseline_probabilities,
                prior=baseline_probabilities,
                prescribed_face_bundles=prescribed_face_bundles,
                rule_ids=rule_ids,
                anchor_integrity=structure_facts.anchor_integrity,
                face_precedents=structure_facts.face_precedents,
            )
        )

    templates = _structure_templates(
        uow.connection,
        generation.baseline_envelope_revision_id,
    )
    unit_stake_minor = _unit_stake_minor(uow, generation, envelope.ticket_kind)
    common_input = {
        "lane": bundle.lane,
        "ticket_kind": envelope.ticket_kind,
        "currency": envelope.currency,
        "capital_cap_minor": envelope.capital_cap_minor,
        "unit_stake_minor": unit_stake_minor,
        "maximum_ticket_count": envelope.maximum_ticket_count,
        "maximum_exhaustive_candidate_count": (
            envelope.maximum_exhaustive_candidate_count
        ),
        "templates": templates,
        "fixed_prize_policy_revision_id": generation.fixed_prize_policy_revision_id,
    }
    return (
        CandidateGenerationInput(**common_input, offers=tuple(judgment_offers)),
        CandidateGenerationInput(**common_input, offers=tuple(conditional_offers)),
        tuple(judgment_audit_offers),
        tuple(conditional_audit_offers),
    )


def audit_current_candidate(uow, selected) -> CurrentOperatorCandidateAudit:
    """Rerun all deterministic audits against one current frozen candidate."""
    if (
        selected.candidate_set.set_kind != "judgment_bound"
        or selected.candidate_set.comparison_only != 0
        or selected.candidate.candidate_set_revision_id
        != selected.candidate_set.candidate_set_revision_id
    ):
        raise ValueError("current audit requires a judgment-bound candidate")
    if selected.candidate_set.audit_policy_version != _CANDIDATE_AUDIT_POLICY_VERSION:
        raise ValueError("candidate audit policy is stale; regenerate candidates")
    judgment_inputs, _conditional_inputs, audit_offers, _conditional_audit = (
        _candidate_generation_inputs(uow, selected.generation)
    )
    draft = _stored_candidate_draft(uow, selected, judgment_inputs)
    findings = _audit_candidate(
        draft,
        lane=judgment_inputs.lane,
        offers=audit_offers,
        capital_cap_minor=judgment_inputs.capital_cap_minor,
    )
    return CurrentOperatorCandidateAudit(
        policy_version=_CANDIDATE_AUDIT_POLICY_VERSION,
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        findings=tuple(
            CurrentOperatorCandidateAuditFinding(
                candidate_audit_finding_id=(
                    "operator-candidate-finding-"
                    + _digest(
                        [
                            selected.candidate.candidate_revision_id,
                            finding.finding_id,
                        ]
                    )
                ),
                audit_kind=finding.audit_kind,
                finding_code=finding.code,
                severity=finding.severity,
                message=finding.message,
                official_match_no=finding.official_match_no,
                rule_id=finding.rule_id,
            )
            for finding in findings
        ),
    )


def _stored_candidate_draft(uow, selected, inputs) -> CandidateDraft:
    rows = uow.operator_result.candidate_tickets(
        selected.candidate.candidate_revision_id
    )
    metric = uow.operator_result.candidate_metric(
        selected.candidate.candidate_revision_id
    )
    if metric is None or not rows:
        raise ValueError("current candidate composition is incomplete")
    offers = {
        offer.official_offer_revision_id: offer
        for offer in inputs.offers
    }
    tickets = tuple(
        _stored_candidate_ticket(uow, row, offers=offers, lane=inputs.lane)
        for row in rows
    )
    ordered = tuple(sorted(tickets, key=lambda item: item.composition_hash))
    stake_minor = sum(ticket.stake_minor for ticket in ordered)
    draft = CandidateDraft(
        tickets=ordered,
        stake_minor=stake_minor,
        composition_hash=_digest(
            {
                "ticket_hashes": [ticket.composition_hash for ticket in ordered],
                "stake_minor": stake_minor,
            }
        ),
    )
    if (
        metric.ticket_count != len(tickets)
        or metric.stake_minor != draft.stake_minor
        or any(ticket.currency != metric.currency for ticket in tickets)
    ):
        raise ValueError("current candidate ticket count, stake, or currency has drifted")
    return draft


def _stored_candidate_ticket(uow, row, *, offers, lane: str) -> CandidateTicket:
    stored_legs = uow.operator_result.candidate_ticket_legs(row.candidate_ticket_id)
    if not stored_legs:
        raise ValueError("current candidate ticket has no normalized legs")
    grouped: dict[str, list[object]] = {}
    for leg in stored_legs:
        grouped.setdefault(leg.official_offer_revision_id, []).append(leg)
    rebuilt_legs: list[CandidateTicketLeg] = []
    for offer_revision_id, legs in grouped.items():
        offer = offers.get(offer_revision_id)
        if offer is None:
            raise ValueError("current candidate ticket references an unknown offer")
        first = legs[0]
        if any(
            (
                leg.match_id,
                leg.market_definition_id,
                leg.settlement_parameter_decimal,
            )
            != (
                first.match_id,
                first.market_definition_id,
                first.settlement_parameter_decimal,
            )
            for leg in legs
        ):
            raise ValueError("current candidate ticket leg grouping is inconsistent")
        if (
            first.match_id != offer.match_id
            or first.market_definition_id != offer.market_definition_id
        ):
            raise ValueError("current candidate ticket crosses its frozen offer")
        if lane == "jczq" and any(
            leg.quote_id is None or leg.booked_decimal_odds is None for leg in legs
        ):
            raise ValueError("current JCZQ candidate lacks exact Quote bindings")
        rebuilt_legs.append(
            CandidateTicketLeg(
                official_match_no=offer.official_match_no,
                official_offer_revision_id=offer_revision_id,
                match_id=first.match_id,
                market_definition_id=first.market_definition_id,
                selection_codes=tuple(leg.selection_code for leg in legs),
                quote_ids=(
                    tuple(str(leg.quote_id) for leg in legs)
                    if lane == "jczq"
                    else ()
                ),
                booked_decimal_odds=(
                    tuple(str(leg.booked_decimal_odds) for leg in legs)
                    if lane == "jczq"
                    else ()
                ),
                settlement_parameter_decimal=first.settlement_parameter_decimal,
            )
        )
    if row.group_code is None:
        raise ValueError("current candidate ticket group code is missing")
    return CandidateTicket(
        ticket_kind=row.ticket_kind,
        structure_code=row.structure_code,
        group_code=row.group_code,
        currency=row.currency,
        unit_stake_minor=row.unit_stake_minor,
        unit_count=row.unit_count,
        stake_minor=row.stake_minor,
        fixed_prize_policy_revision_id=row.fixed_prize_policy_revision_id,
        legs=tuple(rebuilt_legs),
        composition_hash=row.composition_hash,
    )


def _envelope_constraints(connection, envelope_revision_id: str):
    rows = connection.execute(
        select(sod.operator_baseline_envelope_offer_constraints)
        .where(
            sod.operator_baseline_envelope_offer_constraints.c.
            baseline_envelope_revision_id
            == envelope_revision_id
        )
        .order_by(
            sod.operator_baseline_envelope_offer_constraints.c.constraint_index
        )
    ).mappings()
    constraints = {}
    for row in rows:
        bundles = connection.execute(
            select(
                sod.operator_baseline_envelope_face_bundles.c.bundle_code,
                sod.operator_baseline_envelope_bundle_faces.c.face_code,
                sod.operator_baseline_envelope_face_bundles.c.bundle_index,
                sod.operator_baseline_envelope_bundle_faces.c.face_index,
            )
            .select_from(
                sod.operator_baseline_envelope_face_bundles.join(
                    sod.operator_baseline_envelope_bundle_faces
                )
            )
            .where(
                sod.operator_baseline_envelope_face_bundles.c.
                baseline_envelope_offer_constraint_id
                == row["baseline_envelope_offer_constraint_id"]
            )
            .order_by(
                sod.operator_baseline_envelope_face_bundles.c.bundle_index,
                sod.operator_baseline_envelope_bundle_faces.c.face_index,
            )
        ).all()
        grouped: dict[str, list[str]] = {}
        for bundle_code, face_code, _bundle_index, _face_index in bundles:
            grouped.setdefault(str(bundle_code), []).append(str(face_code))
        constraints[(str(row["official_match_no"]), str(row["market_code"]))] = {
            "omission_allowed": int(row["omission_allowed"]),
            "bundles": tuple(
                FaceBundleOption(bundle_code=code, face_codes=tuple(faces))
                for code, faces in grouped.items()
            ),
        }
    return constraints


def _structure_templates(connection, envelope_revision_id: str):
    rows = connection.execute(
        select(sod.operator_baseline_envelope_structure_templates)
        .where(
            sod.operator_baseline_envelope_structure_templates.c.
            baseline_envelope_revision_id
            == envelope_revision_id
        )
        .order_by(sod.operator_baseline_envelope_structure_templates.c.template_index)
    ).mappings()
    templates = []
    for row in rows:
        offer_numbers = tuple(
            connection.execute(
                select(
                    sod.operator_baseline_envelope_template_offers.c.official_match_no
                )
                .where(
                    sod.operator_baseline_envelope_template_offers.c.
                    baseline_envelope_structure_template_id
                    == row["baseline_envelope_structure_template_id"]
                )
                .order_by(
                    sod.operator_baseline_envelope_template_offers.c.offer_index
                )
            ).scalars()
        )
        templates.append(
            CandidateStructureTemplate(
                kind=str(row["kind"]),
                structure_code=str(row["structure_code"]),
                eligible_official_match_nos=offer_numbers,
                pass_size=row["pass_size"],
                required_offer_count=int(row["required_offer_count"]),
                maximum_groups=int(row["maximum_groups"]),
            )
        )
    return tuple(templates)


def _judgment_probabilities(connection, judgment_revision_id: str):
    rows = connection.execute(
        select(
            sod.operator_match_judgment_probabilities.c.face_code,
            sod.operator_match_judgment_probabilities.c.belief_probability_decimal,
        )
        .where(
            sod.operator_match_judgment_probabilities.c.
            operator_match_judgment_revision_id
            == judgment_revision_id
        )
        .order_by(sod.operator_match_judgment_probabilities.c.face_index)
    )
    return tuple((str(face), str(probability)) for face, probability in rows)


def _judgment_face_bundles(connection, judgment_revision_id: str):
    rows = connection.execute(
        select(
            sod.operator_match_judgment_face_bundles.c.bundle_code,
            sod.operator_match_judgment_bundle_faces.c.face_code,
            sod.operator_match_judgment_face_bundles.c.bundle_index,
            sod.operator_match_judgment_bundle_faces.c.face_index,
        )
        .select_from(
            sod.operator_match_judgment_face_bundles.join(
                sod.operator_match_judgment_bundle_faces
            )
        )
        .where(
            sod.operator_match_judgment_face_bundles.c.
            operator_match_judgment_revision_id
            == judgment_revision_id
        )
        .order_by(
            sod.operator_match_judgment_face_bundles.c.bundle_index,
            sod.operator_match_judgment_bundle_faces.c.face_index,
        )
    )
    grouped: dict[str, list[str]] = {}
    for bundle_code, face_code, _bundle_index, _face_index in rows:
        grouped.setdefault(str(bundle_code), []).append(str(face_code))
    return tuple(
        FaceBundleOption(bundle_code=code, face_codes=tuple(faces))
        for code, faces in grouped.items()
    )


def _judgment_rule_ids(connection, judgment_revision_id: str) -> tuple[str, ...]:
    rows = connection.execute(
        select(sod.operator_match_judgment_rule_refs.c.rule_id)
        .where(
            sod.operator_match_judgment_rule_refs.c.operator_match_judgment_revision_id
            == judgment_revision_id
        )
        .order_by(sod.operator_match_judgment_rule_refs.c.rule_index)
    ).scalars()
    return tuple(str(rule_id) for rule_id in rows)


def _market_bindings(uow, *, lane: str, market_definition_id: str, baseline_rows):
    if lane == "zucai":
        return (), (), None
    quote_pairs = []
    odds_pairs = []
    lines = set()
    for row in baseline_rows:
        face_code = str(row["face_code"])
        quote = uow.market.quote(str(row["quote_id"]))
        if quote is None:
            raise ValueError("candidate baseline Quote is unavailable")
        snapshot_quote_ids = set(
            uow.market.snapshot_quote_ids(str(row["market_snapshot_id"]))
        )
        outcome_key = uow.market.selection_outcome_key(quote.selection_id)
        quote_face = {"home": "3", "draw": "1", "away": "0"}.get(
            outcome_key or "",
            outcome_key,
        )
        booked_odds = _canonical_decimal(quote.decimal_odds)
        booked_line = (
            None
            if quote.settlement_parameter_decimal is None
            else _canonical_decimal(quote.settlement_parameter_decimal)
        )
        if (
            quote.match_id != row["match_id"]
            or quote.market_definition_id != market_definition_id
            or quote.quote_status != "active"
            or quote.quote_id not in snapshot_quote_ids
            or quote_face != face_code
            or quote.captured_at != row["quote_captured_at"]
            or booked_odds != row["booked_decimal_odds"]
            or booked_line != row["settlement_parameter_decimal"]
        ):
            raise ValueError("candidate baseline Quote binding has drifted")
        quote_pairs.append((face_code, quote.quote_id))
        odds_pairs.append((face_code, booked_odds))
        line = row["settlement_parameter_decimal"]
        if line is not None:
            lines.add(_canonical_decimal(line))
    line_schema = uow.connection.scalar(
        select(schema_market.market_definitions.c.line_schema).where(
            schema_market.market_definitions.c.market_definition_id
            == market_definition_id
        )
    )
    if line_schema is None:
        settlement_parameter = None
    elif len(lines) == 1:
        settlement_parameter = next(iter(lines))
    else:
        raise ValueError("lined candidate market lacks one exact settlement parameter")
    return tuple(quote_pairs), tuple(odds_pairs), settlement_parameter


def _canonical_decimal(value: object) -> str:
    number = Decimal(str(value)).quantize(_DECIMAL_QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(number, ".12f")


def _unit_stake_minor(uow, generation, ticket_kind: str) -> int:
    if ticket_kind == "jczq_pass":
        return _STANDARD_JCZQ_UNIT_STAKE_MINOR
    policy = uow.operator_result.fixed_prize_policy_revision(
        generation.fixed_prize_policy_revision_id or ""
    )
    if policy is None:
        raise ValueError("candidate fixed-prize policy is unavailable")
    return policy.standard_unit_stake_minor


def _audit_candidate(
    draft: CandidateDraft,
    *,
    lane: str,
    offers: tuple[_CandidateAuditOffer, ...],
    capital_cap_minor: int,
):
    by_match_no = {offer.official_match_no: offer for offer in offers}
    findings: list[CandidateAuditFinding] = []
    supported = _SUPPORTED_SETTLEMENT_MARKETS.get(lane, frozenset())
    unsupported = {
        (leg.official_match_no, leg.market_definition_id)
        for ticket in draft.tickets
        for leg in ticket.legs
        if leg.market_definition_id not in supported
    }
    findings.extend(
        CandidateAuditFinding(
            finding_id="unsupported-settlement-" + _digest([match_no, market_id]),
            code="unsupported_settlement_market",
            severity="ERROR",
            message=(
                f"{match_no} {market_id} has no registered deterministic settlement grader"
            ),
            audit_kind="deployment",
            official_match_no=match_no,
        )
        for match_no, market_id in sorted(unsupported)
    )
    if draft.stake_minor > capital_cap_minor:
        findings.append(
            CandidateAuditFinding(
                finding_id="candidate-budget-"
                + _digest(
                    [draft.composition_hash, draft.stake_minor, capital_cap_minor]
                ),
                code="capital_cap_exceeded",
                severity="ERROR",
                message=(
                    f"candidate stake {draft.stake_minor} exceeds capital cap "
                    f"{capital_cap_minor}"
                ),
                audit_kind="budget",
            )
        )
    for ticket in draft.tickets:
        ticket_legs = {leg.official_match_no: leg for leg in ticket.legs}
        for audit_offer in offers:
            leg = ticket_legs.get(audit_offer.official_match_no)
            candidate_faces = (
                frozenset() if leg is None else frozenset(leg.selection_codes)
            )
            if candidate_faces in audit_offer.prescribed_face_bundles:
                continue
            if not audit_offer.rule_ids:
                raise ValueError(
                    "candidate prescription deviation has no named Rule ID"
                )
            findings.append(
                CandidateAuditFinding(
                    finding_id="prescription-difference-"
                    + _digest(
                        [
                            ticket.composition_hash,
                            audit_offer.official_match_no,
                            sorted(candidate_faces),
                            audit_offer.rule_ids[0],
                        ]
                    ),
                    code="candidate_differs_from_prescription",
                    severity="WARN",
                    message=(
                        f"{audit_offer.official_match_no} candidate faces differ from "
                        "the committed prescription"
                    ),
                    audit_kind="prescription_difference",
                    official_match_no=audit_offer.official_match_no,
                    rule_id=audit_offer.rule_ids[0],
                )
            )
    for ticket in draft.tickets:
        audit_legs_input: list[Leg] = []
        official_numbers: list[str] = []
        for leg_index, ticket_leg in enumerate(ticket.legs):
            context = by_match_no.get(ticket_leg.official_match_no)
            if (
                context is None
                or context.market_definition_id not in {"md-had", "md-hhad"}
                or {face for face, _value in context.belief} != {"3", "1", "0"}
            ):
                continue
            belief = dict(context.belief)
            prior = dict(context.prior)
            audit_legs_input.append(
                Leg(
                    match_no=leg_index + 1,
                    name=f"场 {context.official_match_no}",
                    faces="".join(ticket_leg.selection_codes),
                    fair={
                        "home": float(Decimal(belief["3"])),
                        "draw": float(Decimal(belief["1"])),
                        "away": float(Decimal(belief["0"])),
                    },
                    confidence=5,
                    prior={
                        "home": float(Decimal(prior["3"])),
                        "draw": float(Decimal(prior["1"])),
                        "away": float(Decimal(prior["0"])),
                    },
                    anchor_integrity=context.anchor_integrity,
                    precedents=context.face_precedents,
                )
            )
            official_numbers.append(context.official_match_no)
        for finding in audit_legs(audit_legs_input):
            # INFO 是随票打印的参考表（对位机制 / 排面分级 / ttg 锚），不是治理级 finding：
            # 候选审计契约只登记 WARN 与 ERROR。把 INFO 也塞进去会让每一张带双选的候选
            # 都因"severity 未注册"而整条动作失败——参考信息不该有阻断能力。
            if finding.level == "INFO":
                continue
            official_match_no = (
                None
                if finding.match_no is None
                else official_numbers[finding.match_no - 1]
            )
            findings.append(
                CandidateAuditFinding(
                    finding_id="leg-audit-"
                    + _digest(
                        [
                            ticket.composition_hash,
                            finding.code,
                            official_match_no,
                            finding.message,
                        ]
                    ),
                    code=finding.code,
                    severity=finding.level,
                    message=finding.message,
                    audit_kind="legs",
                    official_match_no=official_match_no,
                )
            )
    return tuple(findings)


def _candidate_set_input(result) -> CandidateSetInput:
    return CandidateSetInput(
        set_kind=result.set_kind,
        candidates=tuple(_ticket_candidate_input(item) for item in result.candidates),
    )


def _ticket_candidate_input(candidate: CandidateComparison) -> TicketCandidateInput:
    return TicketCandidateInput(
        partition=candidate.partition,
        rank=candidate.rank,
        deployable=candidate.deployable,
        tickets=tuple(_candidate_ticket_input(ticket) for ticket in candidate.tickets),
        metrics=CandidateMetricsInput(
            currency=candidate.tickets[0].currency,
            ticket_count=candidate.ticket_count,
            distinct_note_count=candidate.distinct_note_count,
            paid_note_unit_count=candidate.paid_note_unit_count,
            stake_minor=candidate.stake_minor,
            capital_utilization_decimal=candidate.cap_utilization_decimal,
            probability_kind=candidate.probability_kind,
            objective_probability_decimal=candidate.objective_probability_decimal,
            expected_broken_legs_decimal=candidate.expected_broken_legs_decimal,
            break_even_bonus_minor=candidate.break_even_bonus_minor,
            break_even_to_official_median_decimal=(
                candidate.break_even_to_median_decimal
            ),
        ),
        common_dead_faces=tuple(
            CandidateDeadFaceInput(official_match_no=match_no, face_code=face)
            for match_no, faces in candidate.common_dead_faces
            for face in faces
        ),
        audit_findings=tuple(
            CandidateAuditFindingInput(
                finding_id=finding.finding_id,
                audit_kind=finding.audit_kind,
                code=finding.code,
                severity=finding.severity,
                message=finding.message,
                official_match_no=finding.official_match_no,
                rule_id=finding.rule_id,
            )
            for finding in candidate.audit_findings
        ),
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        content_hash=candidate.content_hash,
    )


def _candidate_ticket_input(ticket) -> CandidateTicketInput:
    legs = []
    for leg in ticket.legs:
        for index, selection_code in enumerate(leg.selection_codes):
            legs.append(
                CandidateTicketLegInput(
                    official_offer_revision_id=leg.official_offer_revision_id,
                    match_id=leg.match_id,
                    market_definition_id=leg.market_definition_id,
                    selection_code=selection_code,
                    quote_id=(leg.quote_ids[index] if leg.quote_ids else None),
                    booked_decimal_odds=(
                        leg.booked_decimal_odds[index]
                        if leg.booked_decimal_odds
                        else None
                    ),
                    settlement_parameter_decimal=leg.settlement_parameter_decimal,
                )
            )
    return CandidateTicketInput(
        ticket_kind=ticket.ticket_kind,
        structure_code=ticket.structure_code,
        group_code=ticket.group_code,
        currency=ticket.currency,
        unit_stake_minor=ticket.unit_stake_minor,
        unit_count=ticket.unit_count,
        stake_minor=ticket.stake_minor,
        composition_hash=ticket.composition_hash,
        fixed_prize_policy_revision_id=ticket.fixed_prize_policy_revision_id,
        legs=tuple(legs),
    )


class TaskSettlementWorker:
    """Claim immutable settlement requests and execute their deterministic Action."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        result_actions: OperatorResultActions,
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._result_actions = result_actions
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="task_settlement",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="task_settlement",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self.process_settlement_request(
                    job.source_object_id,
                    worker_job_id=job.worker_job_id,
                    as_of=cutoff,
                )
            except Exception as error:
                with self._action_service.unit_of_work() as uow:
                    retry_code = _retryable_error_code(error)
                    if retry_code is None:
                        uow.operator_decision.fail_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=_terminal_error_code(error),
                            failed_at=cutoff.isoformat(),
                        )
                    else:
                        delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
                        uow.operator_decision.requeue_worker_job(
                            worker_job_id=job.worker_job_id,
                            lease_owner=self._worker_id,
                            error_code=retry_code,
                            available_at=(
                                cutoff + timedelta(seconds=delay_seconds)
                            ).isoformat(),
                            updated_at=cutoff.isoformat(),
                        )
                continue
            completed.append(outcome)
        return tuple(completed)

    def process_settlement_request(
        self,
        settlement_request_id: str,
        *,
        worker_job_id: str,
        as_of: datetime,
    ) -> ActionOutcome:
        requested_at = _aware(as_of, "as_of").astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            settlement_request = uow.operator_result.settlement_request(
                settlement_request_id
            )
            result_set = (
                None
                if settlement_request is None
                else uow.operator_result.result_set_revision(
                    settlement_request.result_set_revision_id
                )
            )
        if settlement_request is None or result_set is None:
            raise ValueError("settlement request lineage is incomplete")
        outcome = self._result_actions.settle_task(
            SettleTaskRequest(
                settlement_request_id=settlement_request_id,
                worker_job_id=worker_job_id,
                lease_owner=self._worker_id,
                settlement_method_version="operator-task-settlement-v1",
                rounding_policy_version=(
                    "cn_sporttery_jczq_v1"
                    if result_set.lane == "jczq"
                    else None
                ),
                actor_id="system:operator-settlement",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=(
                    "operator-task-settlement:"
                    + _digest(
                        {
                            "settlement_request_id": settlement_request_id,
                            "result_set_revision_id": (
                                result_set.result_set_revision_id
                            ),
                            "method_version": "operator-task-settlement-v1",
                        }
                    )
                ),
                requested_at=requested_at,
            )
        )
        if (
            not outcome.is_success
            or len(outcome.result_refs) != 1
            or outcome.result_refs[0].object_type
            != "operator_task_settlement_run"
        ):
            raise ValueError("settle_task Action did not commit one task run")
        return outcome


class ReviewMaterializationWorker:
    """Materialize durable review eligibility through the typed system Action."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        review_actions: OperatorReviewActions,
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._review_actions = review_actions
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="review_materialization",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="review_materialization",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self._review_actions.materialize_operator_review_item(
                    MaterializeOperatorReviewItemRequest(
                        review_eligibility_fact_id=job.source_object_id,
                        worker_job_id=job.worker_job_id,
                        lease_owner=self._worker_id,
                        actor_id="system:operator-review-materialization",
                        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                        requested_at=cutoff,
                    )
                )
                if (
                    not outcome.is_success
                    or len(outcome.result_refs) != 1
                    or outcome.result_refs[0].object_type != "operator_review_item"
                ):
                    raise ValueError(
                        "materialize_operator_review_item Action did not commit one review"
                    )
            except Exception as error:
                self._record_failure(job, error, cutoff=cutoff)
                continue
            completed.append(outcome)
        return tuple(completed)

    def _record_failure(self, job, error: Exception, *, cutoff: datetime) -> None:
        with self._action_service.unit_of_work() as uow:
            retry_code = _retryable_error_code(error)
            if retry_code is None:
                uow.operator_decision.fail_worker_job(
                    worker_job_id=job.worker_job_id,
                    lease_owner=self._worker_id,
                    error_code=_terminal_error_code(error),
                    failed_at=cutoff.isoformat(),
                )
                return
            delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
            uow.operator_decision.requeue_worker_job(
                worker_job_id=job.worker_job_id,
                lease_owner=self._worker_id,
                error_code=retry_code,
                available_at=(cutoff + timedelta(seconds=delay_seconds)).isoformat(),
                updated_at=cutoff.isoformat(),
            )


class ScoreboardReviewCompletionWorker:
    """Complete explicit review requests against the current legacy authority bytes."""

    def __init__(
        self,
        *,
        action_service: ActionService,
        review_actions: OperatorReviewActions,
        scoreboard_path: Path,
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._action_service = action_service
        self._review_actions = review_actions
        self._scoreboard_path = Path(scoreboard_path).resolve()
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self, *, limit: int, as_of: datetime) -> tuple[ActionOutcome, ...]:
        cutoff = _aware(as_of, "as_of").astimezone(UTC)
        if limit < 1:
            return ()
        with self._action_service.unit_of_work() as uow:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind="scoreboard_review_completion",
                as_of=cutoff.isoformat(),
            )
            jobs = uow.operator_decision.claim_worker_jobs(
                job_kind="scoreboard_review_completion",
                lease_owner=self._worker_id,
                as_of=cutoff.isoformat(),
                lease_expires_at=(cutoff + self._lease_duration).isoformat(),
                limit=limit,
            )

        completed: list[ActionOutcome] = []
        for job in jobs:
            try:
                outcome = self._review_actions.complete_scoreboard_review(
                    CompleteScoreboardReviewRequest(
                        completion_request_id=job.source_object_id,
                        worker_job_id=job.worker_job_id,
                        lease_owner=self._worker_id,
                        current_legacy_sha256=self._current_legacy_sha256(),
                        actor_id="system:operator-scoreboard-review-completion",
                        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                        requested_at=cutoff,
                    )
                )
                if (
                    not outcome.is_success
                    or len(outcome.result_refs) != 1
                    or outcome.result_refs[0].object_type
                    != "scoreboard_review_completion_receipt"
                ):
                    raise ValueError(
                        "complete_scoreboard_review Action did not commit one receipt"
                    )
            except Exception as error:
                self._record_failure(job, error, cutoff=cutoff)
                continue
            completed.append(outcome)
        return tuple(completed)

    def _current_legacy_sha256(self) -> str:
        if not self._scoreboard_path.is_file():
            raise ValueError("scoreboard authority file does not exist")
        return hashlib.sha256(self._scoreboard_path.read_bytes()).hexdigest()

    def _record_failure(self, job, error: Exception, *, cutoff: datetime) -> None:
        with self._action_service.unit_of_work() as uow:
            retry_code = _retryable_error_code(error)
            if retry_code is None:
                uow.operator_decision.fail_worker_job(
                    worker_job_id=job.worker_job_id,
                    lease_owner=self._worker_id,
                    error_code=_terminal_error_code(error),
                    failed_at=cutoff.isoformat(),
                )
                return
            delay_seconds = min(2 ** max(job.attempt_count - 1, 0), 300)
            uow.operator_decision.requeue_worker_job(
                worker_job_id=job.worker_job_id,
                lease_owner=self._worker_id,
                error_code=retry_code,
                available_at=(cutoff + timedelta(seconds=delay_seconds)).isoformat(),
                updated_at=cutoff.isoformat(),
            )


__all__ = [
    "CandidateGenerationWorker",
    "ConfirmationDeadlineWorker",
    "EvidenceFreezeRequestWorker",
    "MarketBaselineWorker",
    "OperatorInfrastructureWorkers",
    "OperatorProjectionSignals",
    "OperatorReadModelInvalidator",
    "ProductOutboxWorker",
    "ReviewMaterializationWorker",
    "ScoreboardReviewCompletionWorker",
    "TaskSettlementWorker",
    "audit_current_candidate",
]
