"""Govern immutable exploration policies and prefix-only replay traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import (
    ChangeSurface,
    ReplayStopReason,
    canonical_hash,
    validate_change_surfaces,
)
from nutmeg.ontology.repository.discovery import (
    PolicyParentLinkRow,
    PolicyReplayCompletionRow,
    PolicyReplayRoundRow,
    PolicyReplayRunRow,
    PolicyRevisionRow,
)


@dataclass(frozen=True, slots=True)
class RegisterPolicyRevisionRequest:
    policy: PolicyRevisionRow
    artifact: dict[str, object]
    parent_policy_revision_ids: tuple[str, ...]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class StartPolicyReplayRequest:
    replay: PolicyReplayRunRow
    initial_observation: dict[str, object]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class FinishPolicyReplayRequest:
    replay_run_id: str
    rounds: tuple[PolicyReplayRoundRow, ...]
    completion: PolicyReplayCompletionRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class DiscoveryPolicyActions:
    def __init__(self, action_service: ActionService) -> None:
        self._svc = action_service

    @staticmethod
    def _command(name: str, request, payload: dict) -> ActionCommand:
        return ActionCommand.create(
            action_type=name,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload=payload,
        )

    def register_policy(self, request: RegisterPolicyRevisionRequest) -> ActionOutcome:
        command = self._command(
            "register_policy_revision",
            request,
            {
                "policy": asdict(request.policy),
                "artifact": request.artifact,
                "parents": list(request.parent_policy_revision_ids),
            },
        )

        def handler(uow, cmd):
            from nutmeg.discovery.contracts import BaselinePolicyArtifact

            policy = request.policy
            if canonical_hash(request.artifact) != policy.source_artifact_hash:
                raise ValueError("policy source artifact hash mismatch")
            if not isinstance(request.artifact.get("schema_version"), str):
                raise ValueError("policy artifact requires a schema version")
            allowed = set(BaselinePolicyArtifact.model_fields) | {"configuration", "parameters"}
            if unexpected := set(request.artifact) - allowed:
                raise ValueError(
                    f"unsupported or frozen policy artifact fields: {sorted(unexpected)}"
                )
            if request.artifact.get("generator_family") == "baseline":
                baseline = BaselinePolicyArtifact.model_validate(request.artifact)
                if (
                    baseline.policy_revision_id != policy.policy_revision_id
                    or baseline.family != policy.family
                    or baseline.interface_version != policy.interface_version
                    or baseline.constraints_version != policy.constraints_version
                ):
                    raise ValueError("baseline policy artifact and revision disagree")
            validate_change_surfaces(tuple(ChangeSurface(s) for s in policy.change_surfaces))
            if not policy.validation_result.get("valid"):
                raise ValueError("policy validation did not pass")
            if not policy.compatible_world_families or not isinstance(
                policy.max_resource_permissions, dict
            ):
                raise ValueError(
                    "policy requires compatible worlds and declared resource permissions"
                )
            if len(set(request.parent_policy_revision_ids)) != len(
                request.parent_policy_revision_ids
            ):
                raise ValueError("duplicate policy parent")
            for parent in request.parent_policy_revision_ids:
                existing = uow.discovery.policy(parent)
                if existing is None or existing.family != policy.family:
                    raise ValueError("policy parent must exist in the same family")
            if uow.discovery.policy(policy.policy_revision_id) is not None:
                raise ValueError("policy revision already registered")
            uow.discovery.insert_policy(replace(policy, action_id=cmd.action_id))
            for index, parent in enumerate(request.parent_policy_revision_ids):
                uow.discovery.insert_policy_parent_link(
                    PolicyParentLinkRow(
                        policy_revision_id=policy.policy_revision_id,
                        parent_index=index,
                        parent_policy_revision_id=parent,
                    )
                )
            return (ObjectRef("exploration_policy_revision", policy.policy_revision_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    def start_replay(self, request: StartPolicyReplayRequest) -> ActionOutcome:
        command = self._command(
            "start_policy_replay",
            request,
            {
                "replay": asdict(request.replay),
                "initial_observation": request.initial_observation,
            },
        )

        def handler(uow, cmd):
            replay = request.replay
            world = uow.discovery.world(replay.world_id)
            if world is None or uow.discovery.world_state(replay.world_id) != "sealed":
                raise ValueError("policy replay requires a sealed world")
            policy = uow.discovery.policy(replay.policy_revision_id)
            if policy is None or not policy.validation_result.get("valid"):
                raise ValueError("policy replay requires a valid registered policy")
            if world.task_family not in policy.compatible_world_families:
                raise ValueError("policy replay requires a compatible world")
            if replay.evaluator_revision != world.evaluator_revision:
                raise ValueError("policy replay evaluator differs from sealed world")
            if canonical_hash(request.initial_observation) != replay.initial_observation_hash:
                raise ValueError("initial observation hash mismatch")
            if request.initial_observation.get("visible_node_ids") != [world.root_node_id]:
                raise ValueError("initial observation must expose only the root")
            if set(request.initial_observation) != {"visible_node_ids"}:
                raise ValueError("initial observation contains unfrozen visibility metadata")
            uow.discovery.insert_policy_replay(replace(replay, action_id=cmd.action_id))
            return (ObjectRef("policy_replay_run", replay.policy_replay_run_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    @staticmethod
    def trace_document(
        replay: PolicyReplayRunRow,
        rounds: tuple[PolicyReplayRoundRow, ...],
        completion: PolicyReplayCompletionRow,
    ) -> dict[str, object]:
        return {
            "policy_revision_id": replay.policy_revision_id,
            "world_id": replay.world_id,
            "rounds": [asdict(row) for row in rounds],
            "stop_reason": completion.stop_reason,
            "selected_node_ids": list(completion.selected_node_ids),
        }

    def finish_replay(self, request: FinishPolicyReplayRequest) -> ActionOutcome:
        command = self._command(
            "finish_policy_replay",
            request,
            {
                "replay_run_id": request.replay_run_id,
                "rounds": [asdict(row) for row in request.rounds],
                "completion": asdict(request.completion),
            },
        )

        def handler(uow, cmd):
            replay = uow.discovery.policy_replay(request.replay_run_id)
            if replay is None or uow.discovery.policy_replay_completion(request.replay_run_id):
                raise ValueError("replay missing or already completed")
            world = uow.discovery.world(replay.world_id)
            if uow.discovery.world_state(replay.world_id) != "sealed":
                raise ValueError("replay source world must remain sealed")
            if request.completion.policy_replay_run_id != request.replay_run_id:
                raise ValueError("replay completion belongs to another run")
            ReplayStopReason(request.completion.stop_reason)
            nodes = {node.node_id: node for node in uow.discovery.nodes_for_world(world.world_id)}
            visible = {world.root_node_id}
            for number, item in enumerate(request.rounds, start=1):
                if item.policy_replay_run_id != request.replay_run_id or item.round_no != number:
                    raise ValueError("replay rounds must be contiguous and belong to run")
                revealed = set()
                for node_id in item.revealed_node_ids:
                    node = nodes.get(node_id)
                    if node is None or node.parent_node_id not in visible:
                        raise ValueError("replay revealed a node with an unrevealed parent")
                    if node_id in visible or node_id in revealed:
                        raise ValueError("replay revealed a node twice")
                    revealed.add(node_id)
                visible.update(revealed)
            if any(node_id not in visible for node_id in request.completion.selected_node_ids):
                raise ValueError("replay selected an unrevealed node")
            if (
                canonical_hash(self.trace_document(replay, request.rounds, request.completion))
                != request.completion.trace_hash
            ):
                raise ValueError("policy replay trace hash mismatch")
            for item in request.rounds:
                uow.discovery.insert_policy_replay_round(item)
            uow.discovery.insert_policy_replay_completion(
                replace(request.completion, action_id=cmd.action_id)
            )
            return (ObjectRef("policy_replay_run", request.replay_run_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)
