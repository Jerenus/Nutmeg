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
    PolicyGenerationRoundRow,
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
class RecordPolicyGenerationRoundRequest:
    round: PolicyGenerationRoundRow
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

    def record_generation_round(self, request: RecordPolicyGenerationRoundRequest) -> ActionOutcome:
        command = self._command(
            "record_policy_generation_round", request, {"round": asdict(request.round)}
        )

        def handler(uow, cmd):
            row = request.round
            if row.generator_family not in {"baseline", "bounded_evolution"}:
                raise ValueError("unsupported generator family")
            if row.status not in {"blocked", "complete", "truncated", "timeout"}:
                raise ValueError("unsupported generation status")
            if row.seed < 0 or min(row.candidate_cap, row.compute_budget, row.timeout_seconds) < 1:
                raise ValueError("generation budget must be positive")
            if row.generator_artifact_hash != canonical_hash({"revision": row.generator_revision}):
                raise ValueError("generator artifact hash mismatch")
            if row.input_manifest_hash != canonical_hash(row.input_manifest):
                raise ValueError("generation input manifest hash mismatch")
            if row.trace_hash != canonical_hash(row.trace):
                raise ValueError("generation trace hash mismatch")
            if row.eligible_parent_ids != row.input_manifest.get("eligible_parent_ids"):
                raise ValueError("generation parent pool differs from frozen manifest")
            if row.generator_revision != row.input_manifest.get("generator_revision"):
                raise ValueError("generator revision differs from frozen manifest")
            proposals = row.trace.get("proposals")
            attempts = row.trace.get("attempts")
            if (
                not isinstance(attempts, list)
                or row.generation_cost != {"attempts": len(attempts)}
                or len(attempts) > row.compute_budget
                or (isinstance(proposals, list) and len(proposals) > row.candidate_cap)
            ):
                raise ValueError("generation cost or attempt budget differs from trace")
            if not isinstance(proposals, list) or row.candidate_hashes != [
                canonical_hash(item) for item in proposals
            ]:
                raise ValueError("candidate hashes differ from trace proposals")
            if len(row.candidate_hashes) != len(set(row.candidate_hashes)):
                raise ValueError("duplicate candidate artifact hash")
            if any(
                not isinstance(item, dict)
                or item.get("policy_revision_id")
                not in {
                    attempt.get("policy_revision_id")
                    for attempt in attempts
                    if isinstance(attempt, dict) and attempt.get("status") == "proposed"
                }
                for item in proposals
            ):
                raise ValueError("proposal has no successful generation attempt")
            if row.status == "blocked" and row.candidate_hashes:
                raise ValueError("blocked generation cannot emit candidates")
            worlds = row.input_manifest.get("development_worlds")
            if not isinstance(worlds, list):
                raise ValueError("development worlds must be frozen")
            if row.eligible_parent_ids != sorted(set(row.eligible_parent_ids)):
                raise ValueError("eligible parents must be sorted and unique")
            for parent_id in row.eligible_parent_ids:
                parent = uow.discovery.policy(parent_id)
                if parent is None or not parent.validation_result.get("valid"):
                    raise ValueError("eligible parent must be a registered valid policy")
            for entry in worlds:
                if not isinstance(entry, dict) or set(entry) != {"world_id", "seal_hash"}:
                    raise ValueError("invalid development world manifest")
                world_id = entry["world_id"]
                world = uow.discovery.world(world_id)
                cutoff = row.input_manifest.get("development_cutoff")
                if world is not None and (not isinstance(cutoff, str) or world.cutoff_at > cutoff):
                    raise ValueError("development cutoff excludes holdout world")
                events = uow.discovery.world_events(world_id)
                if (
                    uow.discovery.world_state(world_id) != "sealed"
                    or not events
                    or events[-1].manifest_hash != entry["seal_hash"]
                ):
                    raise ValueError("sealed development world required")
                from nutmeg.discovery.sealed_tree import SealedTree

                nodes = uow.discovery.nodes_for_world(world_id)
                try:
                    SealedTree.from_rows(
                        world,
                        nodes,
                        events,
                        {
                            node.node_id: evaluation
                            for node in nodes
                            if (evaluation := uow.discovery.latest_node_evaluation(node.node_id))
                            is not None
                        },
                    )
                except ValueError as exc:
                    raise ValueError(f"development seal manifest invalid: {exc}") from exc
            uow.discovery.insert_generation_round(replace(row, action_id=cmd.action_id))
            return (ObjectRef("policy_generation_round", row.generation_round_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

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
            from nutmeg.discovery.baseline_variants import load_policy_artifact

            policy = request.policy
            if canonical_hash(request.artifact) != policy.source_artifact_hash:
                raise ValueError("policy source artifact hash mismatch")
            if not isinstance(request.artifact.get("schema_version"), str):
                raise ValueError("policy artifact requires a schema version")
            if request.artifact.get("generator_family") == "baseline":
                baseline = load_policy_artifact(request.artifact)
                if (
                    baseline.policy_revision_id != policy.policy_revision_id
                    or baseline.family != policy.family
                    or baseline.interface_version != policy.interface_version
                    or baseline.constraints_version != policy.constraints_version
                ):
                    raise ValueError("baseline policy artifact and revision disagree")
            elif request.artifact.get("generator_family") != "bounded_evolution":
                from nutmeg.discovery.contracts import BaselinePolicyArtifact

                allowed = set(BaselinePolicyArtifact.model_fields) | {
                    "configuration",
                    "parameters",
                }
                if unexpected := set(request.artifact) - allowed:
                    raise ValueError(
                        f"unsupported or frozen policy artifact fields: {sorted(unexpected)}"
                    )
            if (
                policy.generator_family == "bounded_evolution"
                or policy.generator_revision == "baseline-v1"
                or policy.generator_descriptors.get("generation_round_id")
            ):
                artifact = load_policy_artifact(request.artifact)
                round_id = policy.generator_descriptors.get("generation_round_id")
                round_row = (
                    uow.discovery.generation_round(round_id) if isinstance(round_id, str) else None
                )
                if round_row is None or round_row.status == "blocked":
                    raise ValueError("generated policy requires a recorded generation round")
                if (
                    canonical_hash(request.artifact) not in round_row.candidate_hashes
                    or request.artifact not in round_row.trace["proposals"]
                    or artifact.policy_revision_id != policy.policy_revision_id
                    or artifact.generator_family != policy.generator_family
                    or policy.generator_revision != round_row.generator_revision
                    or policy.generation_input_manifest_hash != round_row.input_manifest_hash
                    or policy.generation_trace_hash != round_row.trace_hash
                    or policy.generation_cost != round_row.generation_cost
                    or tuple(request.parent_policy_revision_ids)
                    != (
                        tuple(artifact.parent_policy_revision_ids)
                        if hasattr(artifact, "parent_policy_revision_ids")
                        else tuple(round_row.eligible_parent_ids)
                    )
                    or not set(request.parent_policy_revision_ids).issubset(
                        round_row.eligible_parent_ids
                    )
                    or tuple(policy.change_surfaces) != artifact.change_surfaces
                ):
                    raise ValueError("generated policy does not match frozen round receipt")
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
            from nutmeg.discovery.environment import COST_POLICY_REVISION

            if replay.cost_policy_revision != COST_POLICY_REVISION:
                raise ValueError("policy replay cost policy is not frozen")
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
        *,
        source_seal_hash: str | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": "2",
            "policy_revision_id": replay.policy_revision_id,
            "world_id": replay.world_id,
            "source_seal_hash": source_seal_hash,
            "initial_observation_hash": replay.initial_observation_hash,
            "evaluator_revision": replay.evaluator_revision,
            "cost_policy_revision": replay.cost_policy_revision,
            "random_seed": replay.random_seed,
            "rounds": [asdict(row) for row in rounds],
            "stop_reason": completion.stop_reason,
            "selected_node_ids": list(completion.selected_node_ids),
            "budget_used": completion.budget_used,
            "failure_codes": completion.failure_codes,
            "aggregate_outcome": completion.aggregate_outcome,
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
            policy = uow.discovery.policy(replay.policy_revision_id)
            nodes = {node.node_id: node for node in uow.discovery.nodes_for_world(world.world_id)}
            seal_events = uow.discovery.world_events(world.world_id)
            if not seal_events or seal_events[-1].event_kind != "sealed":
                raise ValueError("replay source has no seal event")
            from nutmeg.discovery.sealed_tree import SealedTree

            sealed_nodes = tuple(nodes.values())
            try:
                source = SealedTree.from_rows(
                    world,
                    sealed_nodes,
                    seal_events,
                    {
                        node.node_id: evaluation
                        for node in sealed_nodes
                        if (evaluation := uow.discovery.latest_node_evaluation(node.node_id))
                        is not None
                    },
                )
            except ValueError as exc:
                raise ValueError(f"sealed manifest invalid: {exc}") from exc
            visible = {world.root_node_id}
            visible_order = [world.root_node_id]
            charged_attempts = 0
            charged_wall_ms: int | None = 0
            charged_candidates: int | None = 0
            observed_failures: list[str] = []
            for number, item in enumerate(request.rounds, start=1):
                if item.policy_replay_run_id != request.replay_run_id or item.round_no != number:
                    raise ValueError("replay rounds must be contiguous and belong to run")
                if item.observation_hash != canonical_hash({"visible_node_ids": visible_order}):
                    raise ValueError("policy replay observation hash mismatch")
                if policy.generator_family == "baseline":
                    from nutmeg.discovery.environment import policy_state_hash

                    expected_state = policy_state_hash({"schema_version": "1", "round": number})
                    if item.policy_state_hash != expected_state:
                        raise ValueError("baseline policy state hash mismatch")
                revealed = set()
                accepted_ids = [
                    node_id
                    for action in item.accepted_actions
                    for node_id in action.get("revealed_node_ids", [action.get("revealed_node_id")])
                ]
                if accepted_ids != item.revealed_node_ids:
                    raise ValueError("accepted action and revealed child sequence mismatch")
                if any(
                    {
                        key: value
                        for key, value in action.items()
                        if key not in {"revealed_node_id", "revealed_node_ids"}
                    }
                    not in item.requested_actions
                    for action in item.accepted_actions
                ):
                    raise ValueError("accepted action was not requested")
                for requested in item.requested_actions:
                    if not isinstance(requested, dict):
                        raise ValueError("requested action must be structured")
                    chain = source.children_for(
                        requested.get("parent_node_id", ""),
                        requested.get("continuation_action", {}),
                    )
                    charged_attempts += len(chain) or 1
                    if not chain:
                        charged_wall_ms = None
                        charged_candidates = None
                        observed_failures.append("branch_unavailable")
                    for node in chain:
                        wall_ms = (node.resource_cost or {}).get("wall_ms")
                        if charged_wall_ms is not None and isinstance(wall_ms, int):
                            charged_wall_ms += wall_ms
                        else:
                            charged_wall_ms = None
                        count = (node.resource_cost or {}).get("candidate_generation_count")
                        if charged_candidates is not None and isinstance(count, int):
                            charged_candidates += count
                        else:
                            charged_candidates = None
                        if node.execution_status == "failed":
                            observed_failures.extend(node.diagnostic_codes)
                matched = set()
                for action in item.accepted_actions:
                    if not isinstance(action, dict):
                        raise ValueError("accepted action must be structured")
                    parent_id = action.get("parent_node_id")
                    child_ids = tuple(
                        action.get("revealed_node_ids", [action.get("revealed_node_id")])
                    )
                    if (
                        parent_id not in visible
                        or not nodes[parent_id].frontier_eligible
                        or child_ids
                        != tuple(
                            node.node_id
                            for node in source.children_for(
                                parent_id, action.get("continuation_action", {})
                            )
                        )
                        or any(node_id in matched for node_id in child_ids)
                    ):
                        raise ValueError("accepted action does not match recorded continuation")
                    matched.update(child_ids)
                for node_id in item.revealed_node_ids:
                    node = nodes.get(node_id)
                    if node is None or node.parent_node_id not in visible:
                        raise ValueError("replay revealed a node with an unrevealed parent")
                    if node_id in visible or node_id in revealed:
                        raise ValueError("replay revealed a node twice")
                    revealed.add(node_id)
                visible.update(revealed)
                visible_order.extend(item.revealed_node_ids)
            if any(node_id not in visible for node_id in request.completion.selected_node_ids):
                raise ValueError("replay selected an unrevealed node")
            if any(
                node_id not in source.evaluations or not source.evaluations[node_id].selectable
                for node_id in request.completion.selected_node_ids
            ):
                raise ValueError("replay selected a nonselectable node")
            if (
                request.completion.budget_used.get("attempts") != charged_attempts
                or request.completion.budget_used.get("wall_ms") != charged_wall_ms
                or request.completion.budget_used.get("candidate_generation_count")
                != charged_candidates
                or request.completion.failure_codes != observed_failures
            ):
                raise ValueError("replay budget or failure accounting mismatch")
            if (
                canonical_hash(
                    self.trace_document(
                        replay,
                        request.rounds,
                        request.completion,
                        source_seal_hash=seal_events[-1].manifest_hash,
                    )
                )
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
