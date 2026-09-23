"""Thin test drivers for the governed operator Actions.

The durable background workers that used to claim these jobs
(``nutmeg.product.operator_workers``) were retired with the 8788 web app on
2026-09-23.  The typed Actions they called are live, so these helpers keep
driving them: claim the queued worker job through the repository, then invoke
exactly the Action the worker invoked, with the same deterministic idempotency
key.  No lease bookkeeping, retry backoff or requeue logic lives here —
that was worker mechanics and died with the worker.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from nutmeg.ontology.actions.bundle_actions import FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionOutcome, ActorRole, canonical_json
from nutmeg.ontology.operator.decision_actions import FreezeMarketPriorBaselineRequest
from nutmeg.ontology.operator.evidence_actions import LinkTaskEvidenceFreezeRequest
from nutmeg.ontology.operator.result_actions import SettleTaskRequest

LEASE_DURATION = timedelta(minutes=5)


def digest(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def claim_worker_jobs(
    action_service,
    *,
    job_kind: str,
    lease_owner: str,
    as_of: datetime,
    limit: int = 1,
    recover_expired: bool = True,
):
    cutoff = as_of.astimezone(UTC)
    with action_service.unit_of_work() as uow:
        if recover_expired:
            uow.operator_decision.recover_expired_worker_jobs(
                job_kind=job_kind,
                as_of=cutoff.isoformat(),
            )
        return uow.operator_decision.claim_worker_jobs(
            job_kind=job_kind,
            lease_owner=lease_owner,
            as_of=cutoff.isoformat(),
            lease_expires_at=(cutoff + LEASE_DURATION).isoformat(),
            limit=limit,
        )


def freeze_task_evidence(
    *,
    action_service,
    evidence_actions,
    bundle_actions,
    request_id: str,
    lease_owner: str,
    as_of: datetime,
) -> ActionOutcome:
    """``freeze_evidence_bundle`` per match, then ``link_operator_task_evidence_freeze``."""
    requested_at = as_of.astimezone(UTC)
    request, gate = evidence_actions.freeze_plan_for_request(
        request_id,
        as_of=requested_at,
    )
    bundle_action_ids: list[str] = []
    for match in sorted(gate.matches, key=lambda item: item.match_id):
        key = "operator-evidence-bundle:" + digest(
            {
                "request_id": request_id,
                "dependency_fingerprint": request.dependency_fingerprint,
                "match_id": match.match_id,
                "candidate_observation_ids": sorted(match.candidate_observation_ids),
                "caveat_claim_ids": sorted(match.caveat_claim_ids),
                "market_snapshot_id": match.market_snapshot_id,
                "prior_distribution": match.prior_distribution,
            }
        )
        outcome = bundle_actions.freeze_bundle(
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
        bundle_action_ids.append(outcome.action_id)

    link_outcome = evidence_actions.link_operator_task_evidence_freeze(
        LinkTaskEvidenceFreezeRequest(
            evidence_freeze_request_id=request_id,
            freeze_bundle_action_ids=tuple(bundle_action_ids),
            required_match_count=gate.required_match_count,
            bundle_count=len(bundle_action_ids),
            item_count=len(bundle_action_ids),
            lease_owner=lease_owner,
            actor_id="system:operator-evidence-freeze",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=(
                "operator-evidence-link:"
                + digest(
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
    return link_outcome


def drive_evidence_freeze(
    *,
    action_service,
    evidence_actions,
    bundle_actions,
    lease_owner: str,
    as_of: datetime,
    limit: int = 1,
) -> tuple[ActionOutcome, ...]:
    """Claim every queued ``evidence_freeze`` job and run its Actions."""
    jobs = claim_worker_jobs(
        action_service,
        job_kind="evidence_freeze",
        lease_owner=lease_owner,
        as_of=as_of,
        limit=limit,
    )
    return tuple(
        freeze_task_evidence(
            action_service=action_service,
            evidence_actions=evidence_actions,
            bundle_actions=bundle_actions,
            request_id=job.source_object_id,
            lease_owner=lease_owner,
            as_of=as_of,
        )
        for job in jobs
    )


def freeze_market_baseline(
    *,
    action_service,
    decision_actions,
    task_evidence_bundle_revision_id: str,
    work_item_id: str,
    worker_job_id: str,
    lease_owner: str,
    as_of: datetime,
) -> ActionOutcome:
    requested_at = as_of.astimezone(UTC)
    with action_service.unit_of_work() as uow:
        bundle = uow.operator_decision.task_evidence_bundle_revision(
            task_evidence_bundle_revision_id
        )
    if bundle is None:
        raise ValueError("market baseline task bundle is unavailable")
    return decision_actions.freeze_market_prior_baseline(
        FreezeMarketPriorBaselineRequest(
            task_evidence_bundle_revision_id=task_evidence_bundle_revision_id,
            work_item_id=work_item_id,
            actor_id="system:operator-market-baseline",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=(
                "operator-market-baseline:"
                + digest(
                    {
                        "task_evidence_bundle_revision_id": (
                            task_evidence_bundle_revision_id
                        ),
                        "task_bundle_content_hash": bundle.content_hash,
                        "work_item_id": work_item_id,
                    }
                )
            ),
            requested_at=requested_at,
            worker_job_id=worker_job_id,
            lease_owner=lease_owner,
        )
    )


def drive_market_baseline(
    *,
    action_service,
    decision_actions,
    work_item_id: str,
    lease_owner: str,
    as_of: datetime,
    limit: int = 1,
) -> tuple[ActionOutcome, ...]:
    """Claim every queued ``market_baseline`` job and freeze its exact prior."""
    jobs = claim_worker_jobs(
        action_service,
        job_kind="market_baseline",
        lease_owner=lease_owner,
        as_of=as_of,
        limit=limit,
    )
    return tuple(
        freeze_market_baseline(
            action_service=action_service,
            decision_actions=decision_actions,
            task_evidence_bundle_revision_id=job.source_object_id,
            work_item_id=work_item_id,
            worker_job_id=job.worker_job_id,
            lease_owner=lease_owner,
            as_of=as_of,
        )
        for job in jobs
    )


def settle_task(
    *,
    action_service,
    result_actions,
    settlement_request_id: str,
    worker_job_id: str,
    lease_owner: str,
    as_of: datetime,
) -> ActionOutcome:
    requested_at = as_of.astimezone(UTC)
    with action_service.unit_of_work() as uow:
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
    return result_actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=settlement_request_id,
            worker_job_id=worker_job_id,
            lease_owner=lease_owner,
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version=(
                "cn_sporttery_jczq_v1" if result_set.lane == "jczq" else None
            ),
            actor_id="system:operator-settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=(
                "operator-task-settlement:"
                + digest(
                    {
                        "settlement_request_id": settlement_request_id,
                        "result_set_revision_id": result_set.result_set_revision_id,
                        "method_version": "operator-task-settlement-v1",
                    }
                )
            ),
            requested_at=requested_at,
        )
    )


def drive_task_settlement(
    *,
    action_service,
    result_actions,
    lease_owner: str,
    as_of: datetime,
    limit: int = 1,
) -> tuple[ActionOutcome, ...]:
    """Claim every queued ``task_settlement`` job and run its deterministic Action."""
    jobs = claim_worker_jobs(
        action_service,
        job_kind="task_settlement",
        lease_owner=lease_owner,
        as_of=as_of,
        limit=limit,
    )
    return tuple(
        settle_task(
            action_service=action_service,
            result_actions=result_actions,
            settlement_request_id=job.source_object_id,
            worker_job_id=job.worker_job_id,
            lease_owner=lease_owner,
            as_of=as_of,
        )
        for job in jobs
    )
