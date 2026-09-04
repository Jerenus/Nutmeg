"""Durable infrastructure workers for governed operator Actions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionOutcome, ActorRole, canonical_json
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError, PermissionDeniedError
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    LinkTaskEvidenceFreezeRequest,
)


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


__all__ = ["EvidenceFreezeRequestWorker"]
