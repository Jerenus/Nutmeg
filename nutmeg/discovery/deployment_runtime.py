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


def controller_for(deployment, brake, *, boundary: str) -> Controller:
    if deployment is None:
        return Controller(None, "unchanged", False)
    effective = datetime.fromisoformat(deployment.effective_boundary)
    instant = datetime.fromisoformat(boundary)
    if effective.tzinfo is None or instant.tzinfo is None:
        raise ValueError("business boundary must be timezone-aware")
    if brake is not None:
        return Controller(deployment.rollback_policy_revision_id, "braked", False)
    if instant < effective:
        return Controller(None, "pending", False)
    if deployment.decision == "shadow":
        return Controller(deployment.policy_revision_id, "shadow", False)
    if deployment.decision not in {"canary", "deploy"}:
        return Controller(None, deployment.decision, False)
    try:
        validate_control_scope(deployment.scope, {"mode": "shadow_only"})
    except ValueError:
        return Controller(None, "control_unavailable", False)
    return Controller(deployment.policy_revision_id, deployment.decision, True)
