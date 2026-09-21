"""Policy-visible discovery protocol shared by online and sealed replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from nutmeg.discovery.contracts import PilotContract
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.discovery.models import canonical_hash

COST_POLICY_REVISION = "structural-cost-v1"


@dataclass(frozen=True, slots=True)
class RevealedNode:
    node_id: str
    execution_status: str
    quality_by_band: tuple[tuple[str, str], ...]
    artifact_manifest_hash: str
    diagnostic_codes: tuple[str, ...]
    resource_cost: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class Observation:
    world_id: str
    visible_node_ids: tuple[str, ...]
    frontier_node_ids: tuple[str, ...]
    selectable_node_ids: tuple[str, ...]
    legal_template_ids: tuple[str, ...]
    remaining_rounds: int
    remaining_nodes: int
    max_concurrency: int
    revealed_nodes: tuple[RevealedNode, ...] = ()
    task_family: str = ""
    lane: str = ""
    business_date: str = ""
    remaining_wall_ms: int | None = None
    remaining_candidate_generation_count: int | None = None


@dataclass(frozen=True, slots=True)
class Continue:
    node_id: str
    template_ids: tuple[str, ...]
    operator: str = "enumerate_template_shard"


@dataclass(frozen=True, slots=True)
class ContinueBatch:
    items: tuple[Continue, ...]


@dataclass(frozen=True, slots=True)
class Stop:
    selected_node_ids: tuple[str, ...]
    reason: str = "policy_stop"


@dataclass(frozen=True, slots=True)
class TerminalObservation:
    reason: str
    selected_node_ids: tuple[str, ...]
    failure_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepResult:
    observation: Observation
    revealed_node_ids: tuple[str, ...]
    failure_codes: tuple[str, ...]
    charged_cost: dict[str, object]


class DiscoveryEnvironment(Protocol):
    def reset(self) -> Observation: ...

    def observation(self) -> Observation: ...

    def legal_actions(self) -> tuple[Continue | Stop, ...]: ...

    def continue_batch(self, action: ContinueBatch) -> StepResult: ...

    def stop(self, action: Stop) -> TerminalObservation: ...


def policy_state_hash(state: dict[str, object]) -> str:
    encoded = canonical_json(state).encode("utf-8")
    if state.get("schema_version") != "1" or len(encoded) > 16384:
        raise ValueError("invalid policy state version or size")
    return canonical_hash(state)


def legal_actions(observation: Observation) -> tuple[Continue | Stop, ...]:
    continuations = (
        tuple(
            Continue(parent, (template,))
            for parent in observation.frontier_node_ids
            for template in observation.legal_template_ids
        )
        if observation.remaining_nodes > 0 and observation.remaining_rounds > 0
        else ()
    )
    return (*continuations, Stop(()))


def validate_action(
    observation: Observation,
    action: Continue | ContinueBatch | Stop,
    pilot: PilotContract,
) -> tuple[Continue, ...] | Stop:
    if isinstance(action, Stop):
        if len(set(action.selected_node_ids)) != len(action.selected_node_ids) or any(
            node not in observation.selectable_node_ids for node in action.selected_node_ids
        ):
            raise ValueError("stop must select distinct visible selectable nodes")
        return action
    items = action.items if isinstance(action, ContinueBatch) else (action,)
    if not items:
        raise ValueError("continue batch is empty")
    if observation.remaining_rounds < 1 or pilot.budgets.max_rounds < 1:
        raise ValueError("round budget exhausted")
    if len(items) > observation.remaining_nodes:
        raise ValueError("node budget exhausted")
    if len(items) > min(observation.max_concurrency, pilot.budgets.max_concurrency):
        raise ValueError("concurrency budget exhausted")
    keys: set[tuple[str, tuple[str, ...]]] = set()
    for item in items:
        if item.node_id not in observation.frontier_node_ids:
            raise ValueError("continuation requires a visible frontier node")
        if item.operator not in {
            spec.name for spec in pilot.operator_grammar if spec.name != "stop"
        }:
            raise ValueError("unknown legal operator")
        if not item.template_ids or any(
            template not in observation.legal_template_ids for template in item.template_ids
        ):
            raise ValueError("unknown legal template")
        key = (item.node_id, item.template_ids)
        if key in keys:
            raise ValueError("duplicate continuation")
        keys.add(key)
    return items
