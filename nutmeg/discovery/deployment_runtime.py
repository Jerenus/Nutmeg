"""Resolve scoped authority at a new-run boundary from durable events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.discovery.pilot_scope import validate_control_scope


@dataclass(frozen=True)
class Controller:
    policy_revision_id: str | None
    mode: str
    authoritative: bool
    scope_hash: str | None = None
    deployment_id: str | None = None


def controller_for(deployment, brake, *, boundary: str, board: str | None = None,
                   exposure_used: int = 0, reviewed_hash: str | None = None,
                   approval_ref: str | None = None, scope_review: dict | None = None) -> Controller:
    if deployment is None:
        return Controller(None, "unchanged", False)
    effective = datetime.fromisoformat(deployment.effective_boundary)
    instant = datetime.fromisoformat(boundary)
    if effective.tzinfo is None or instant.tzinfo is None:
        raise ValueError("business boundary must be timezone-aware")
    if brake is not None:
        if instant < datetime.fromisoformat(brake.effective_boundary):
            return Controller(None, "brake_pending", False)
        return Controller(deployment.rollback_policy_revision_id, "braked", False)
    if instant < effective:
        return Controller(None, "pending", False)
    if deployment.decision == "shadow":
        return Controller(deployment.policy_revision_id, "shadow", False)
    if deployment.decision not in {"canary", "deploy"}:
        return Controller(None, deployment.decision, False)
    try:
        refs = deployment.evidence_refs or {}
        contract = validate_control_scope(
            deployment.scope, refs.get("scope_contract", {}),
            reviewed_hash=reviewed_hash, approval_ref=approval_ref,
        )
        if (refs.get("scope_contract_hash") != reviewed_hash
            or refs.get("scope_approval_ref") != approval_ref
            or scope_review is None
            or scope_review.get("scope_contract_hash") != reviewed_hash
            or scope_review.get("approval_ref") != approval_ref
            or scope_review.get("contract") != contract.model_dump(mode="json")
            or refs.get("scope_review_action_id") != scope_review.get("action_id")
            or not scope_review.get("human_actor_id", "").startswith("op:")
            or datetime.fromisoformat(scope_review["approved_at"])
            >= datetime.fromisoformat(deployment.decided_at)
            or contract.effective_boundary != deployment.effective_boundary
            or contract.fallback_policy_revision_id != deployment.rollback_policy_revision_id
            or board != contract.scope.board or exposure_used < 0
            or exposure_used >= contract.exposure_cap):
            raise ValueError("scope or exposure differs from reviewed contract")
    except ValueError:
        return Controller(None, "control_unavailable", False)
    return Controller(deployment.policy_revision_id, deployment.decision, True,
                      reviewed_hash, deployment.policy_deployment_id)


def resolve_controller(repository, family: str, scope: dict, *, boundary: str,
                       board: str, exposure_used: int = 0, reviewed_hash: str | None = None,
                       approval_ref: str | None = None) -> Controller:
    event = repository.latest_deployment_for_scope(family, scope)
    brake = repository.latest_brake(event.policy_deployment_id) if event else None
    scope_review = (
        repository.scope_review(reviewed_hash) if event and reviewed_hash else None
    )
    if event:
        exposure_used = max(exposure_used, repository.scope_exposure(event.policy_deployment_id))
    return controller_for(event, brake, boundary=boundary, board=board,
                          exposure_used=exposure_used, reviewed_hash=reviewed_hash,
                          approval_ref=approval_ref, scope_review=scope_review)


def policy_lineage(controller: Controller) -> dict[str, str]:
    if (not controller.authoritative or not controller.policy_revision_id
        or not controller.scope_hash or not controller.deployment_id):
        raise ValueError("inactive controller cannot bind authoritative lineage")
    return {
        "policy_revision_id": controller.policy_revision_id,
        "scope_contract_hash": controller.scope_hash,
        "policy_deployment_id": controller.deployment_id,
    }
