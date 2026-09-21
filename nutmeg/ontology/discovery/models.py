from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.ontology.actions.models import canonical_json


class ProvenanceMode(StrEnum):
    PROSPECTIVE_ONLINE = "prospective_online"
    HISTORICAL_REPLAY_SOURCE = "historical_replay_source"


class WorldEventKind(StrEnum):
    CREATED = "created"
    RUN_STARTED = "run_started"
    SEALED = "sealed"
    QUARANTINED = "quarantined"


class ChangeSurface(StrEnum):
    EXPLORATION_POLICY = "exploration_policy"
    CLOSED_OPERATOR = "closed_workflow_operator"
    MODEL_OR_SYSTEM = "model_weights_or_executable_system"


class ArchiveDisposition(StrEnum):
    INCUMBENT = "incumbent"
    CHALLENGER = "challenger"
    STEPPING_STONE = "stepping_stone"
    REJECTED = "rejected"
    RETIRED = "retired"


class DeploymentDecision(StrEnum):
    SHADOW = "shadow"
    CANARY = "canary"
    DEPLOY = "deploy"
    HOLD = "hold"
    ROLLBACK = "rollback"
    RETIRE = "retire"


class ReplayStopReason(StrEnum):
    POLICY_STOP = "policy_stop"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_ACTION = "invalid_action"
    POLICY_CRASH = "policy_crash"
    BRANCH_UNAVAILABLE = "branch_unavailable"


def canonical_hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def validate_change_surfaces(values: tuple[ChangeSurface, ...]) -> None:
    if not values:
        raise ValueError("at least one change surface is required")
    if ChangeSurface.MODEL_OR_SYSTEM in values:
        raise ValueError("model/system change surface is frozen in v1")


def project_world_state(events: tuple[WorldEventKind, ...]) -> str:
    if not events:
        return "missing"
    if events[0] is not WorldEventKind.CREATED:
        raise ValueError("world history must begin with created")
    state = "created"
    for event in events[1:]:
        if state in {"sealed", "quarantined"}:
            raise ValueError("world state is terminal")
        if event is WorldEventKind.RUN_STARTED:
            state = "running"
        elif event is WorldEventKind.SEALED:
            state = "sealed"
        elif event is WorldEventKind.QUARANTINED:
            state = "quarantined"
        else:
            raise ValueError(f"invalid world transition: {event}")
    return state


def project_policy_lifecycle(
    *,
    registered: bool,
    winner: bool,
    deployment: DeploymentDecision | None,
    archive_disposition: ArchiveDisposition | None = None,
) -> str:
    if not registered:
        return "missing"
    if deployment is not None:
        return deployment.value
    if winner:
        return "tournament_winner"
    if archive_disposition is ArchiveDisposition.STEPPING_STONE:
        return "stepping_stone"
    return "validated"


@dataclass(frozen=True, slots=True)
class DiscoveryStatus:
    incumbent_policy_revision_id: str | None
    active_deployment_state: str | None
    latest_tournament_id: str | None
    latest_world_id: str | None
    sealed_world_count: int
    exposed_holdout_count: int
    rollback_policy_revision_id: str | None
