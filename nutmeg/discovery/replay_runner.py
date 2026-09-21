"""Deterministic registered baseline replay against a sealed D2 world."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from sqlalchemy import Engine

from nutmeg.discovery.baseline_variants import (
    DeterministicBaselineVariantArtifact,
    PolicyArtifact,
)
from nutmeg.discovery.contracts import (
    BaselinePolicyArtifact,
    PilotContract,
)
from nutmeg.discovery.contracts import (
    canonical_hash as contract_hash,
)
from nutmeg.discovery.environment import (
    COST_POLICY_REVISION,
    Continue,
    ContinueBatch,
    Observation,
    Stop,
    policy_state_hash,
)
from nutmeg.discovery.generation_contracts import PolicyProgramArtifact
from nutmeg.discovery.online_inputs import StructuralInputSnapshot
from nutmeg.discovery.online_recorder import OnlineRecordingEnvironment, RecordedWorld
from nutmeg.discovery.replay_environment import ReplayEnvironment
from nutmeg.discovery.sealed_tree import SealedTree
from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    FinishPolicyReplayRequest,
    StartPolicyReplayRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.discovery import (
    PolicyReplayCompletionRow,
    PolicyReplayRoundRow,
    PolicyReplayRunRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


@dataclass(frozen=True, slots=True)
class ReplayResult:
    policy_replay_run_id: str
    trace_hash: str
    selected_node_ids: tuple[str, ...]


def _select(observation: Observation) -> tuple[str, ...]:
    best: dict[str, tuple[Decimal, str]] = {}
    for node in observation.revealed_nodes:
        if node.node_id not in observation.selectable_node_ids:
            continue
        for band, score in node.quality_by_band:
            value = (Decimal(score), node.node_id)
            previous = best.get(band)
            if (
                previous is None
                or value[0] > previous[0]
                or (value[0] == previous[0] and node.node_id < previous[1])
            ):
                best[band] = value
    return tuple(sorted({node_id for _score, node_id in best.values()}))


def baseline_decision(step, observation: Observation) -> ContinueBatch | Stop:
    if step.action == "continue_batch" and step.selector == "all_template_shards":
        return ContinueBatch(
            tuple(
                Continue(observation.visible_node_ids[0], (template,))
                for template in observation.legal_template_ids
            )
        )
    if step.action == "stop" and step.selector == "best_audit_clean_node_per_band":
        return Stop(_select(observation))
    raise ValueError("unsupported baseline policy step")


def policy_decision(
    policy: PolicyArtifact, round_number: int, observation: Observation
) -> ContinueBatch | Stop:
    if isinstance(policy, BaselinePolicyArtifact):
        step = next((item for item in policy.steps if item.round == round_number), None)
        if step is None:
            raise ValueError("baseline policy round is missing")
        return baseline_decision(step, observation)
    if isinstance(policy, DeterministicBaselineVariantArtifact):
        if round_number == 1:
            available = tuple(
                template
                for template in policy.template_order
                if template in observation.legal_template_ids
            )[: policy.batch_limit]
            if available:
                return ContinueBatch(
                    tuple(Continue(observation.frontier_node_ids[0], (item,)) for item in available)
                )
        if round_number == 2:
            return Stop(_select(observation))
        raise ValueError("baseline variant round is missing")
    if isinstance(policy, PolicyProgramArtifact):
        program = policy.program
        selected = _select(observation)
        if selected and any(
            Decimal(score) >= program.stop_quality_threshold
            for node in observation.revealed_nodes
            if node.node_id in selected
            for _band, score in node.quality_by_band
        ):
            return Stop(selected)
        if round_number == 1 and observation.frontier_node_ids:
            frontier = observation.frontier_node_ids[0]
            if program.budget_allocation == "quality_first":
                ranked = sorted(
                    (
                        node
                        for node in observation.revealed_nodes
                        if node.node_id in observation.frontier_node_ids
                    ),
                    key=lambda node: (
                        -max(
                            (Decimal(value) for _, value in node.quality_by_band),
                            default=Decimal(0),
                        ),
                        node.node_id,
                    ),
                )
                if ranked:
                    frontier = ranked[0].node_id
            available = tuple(
                t for t in program.template_order if t in observation.legal_template_ids
            )
            available = available[
                : min(program.batch_limit, observation.max_concurrency, observation.remaining_nodes)
            ]
            if available:
                return ContinueBatch(tuple(Continue(frontier, (t,)) for t in available))
        if round_number in (1, 2):
            return Stop(selected)
        raise ValueError("program policy round is missing")
    raise ValueError("unsupported policy artifact")


def _policy_rounds(policy: PolicyArtifact) -> tuple[int, ...]:
    if isinstance(policy, BaselinePolicyArtifact):
        return tuple(step.round for step in policy.steps)
    return (1, 2)


def _trace(
    tree: SealedTree,
    policy: PolicyArtifact,
    pilot: PilotContract,
    replay: PolicyReplayRunRow,
    requested_at: datetime,
) -> tuple[tuple[PolicyReplayRoundRow, ...], PolicyReplayCompletionRow]:
    environment = ReplayEnvironment(tree, pilot)
    observation = environment.reset()
    rounds = []
    costs = {"attempts": 0, "wall_ms": 0, "candidate_generation_count": 0}
    failures: list[str] = []
    terminal = None
    for round_number in _policy_rounds(policy):
        decision = policy_decision(policy, round_number, observation)
        if isinstance(decision, ContinueBatch):
            actions = decision
            before = observation
            result = environment.continue_batch(actions)
            observation = result.observation
            requested = [
                {
                    "parent_node_id": item.node_id,
                    "continuation_action": {
                        "operator": item.operator,
                        "template_ids": list(item.template_ids),
                    },
                }
                for item in actions.items
            ]
            accepted = []
            rejected = []
            for item in requested:
                children = tree.children_for(item["parent_node_id"], item["continuation_action"])
                if not children:
                    rejected.append({**item, "reason": "branch_unavailable"})
                else:
                    accepted.append(
                        {**item, "revealed_node_ids": [child.node_id for child in children]}
                    )
            rounds.append(
                PolicyReplayRoundRow(
                    policy_replay_run_id=replay.policy_replay_run_id,
                    round_no=len(rounds) + 1,
                    observation_hash=canonical_hash(
                        {"visible_node_ids": list(before.visible_node_ids)}
                    ),
                    policy_state_hash=policy_state_hash(
                        {"schema_version": "1", "round": round_number}
                    ),
                    requested_actions=requested,
                    accepted_actions=accepted,
                    rejected_actions=rejected,
                    revealed_node_ids=list(result.revealed_node_ids),
                    remaining_budget={
                        "rounds": observation.remaining_rounds,
                        "nodes": observation.remaining_nodes,
                    },
                    decided_at=requested_at.isoformat(),
                )
            )
            costs["attempts"] += result.charged_cost["attempts"]
            if costs["wall_ms"] is not None and result.charged_cost["wall_ms"] is not None:
                costs["wall_ms"] += result.charged_cost["wall_ms"]
            else:
                costs["wall_ms"] = None
            if (
                costs["candidate_generation_count"] is not None
                and result.charged_cost["candidate_generation_count"] is not None
            ):
                costs["candidate_generation_count"] += result.charged_cost[
                    "candidate_generation_count"
                ]
            else:
                costs["candidate_generation_count"] = None
            failures.extend(result.failure_codes)
        elif isinstance(decision, Stop):
            terminal = environment.stop(decision)
        else:
            raise ValueError("unsupported baseline policy action")
    if terminal is None:
        raise ValueError("baseline did not stop")
    completion = PolicyReplayCompletionRow(
        policy_replay_run_id=replay.policy_replay_run_id,
        stop_reason=terminal.reason,
        budget_used=costs,
        failure_codes=failures,
        selected_node_ids=list(terminal.selected_node_ids),
        aggregate_outcome={"revealed_nodes": len(observation.visible_node_ids)},
        trace_hash="pending",
        finished_at=requested_at.isoformat(),
        action_id="pending",
    )
    from dataclasses import replace

    completion = replace(
        completion,
        trace_hash=canonical_hash(
            DiscoveryPolicyActions.trace_document(
                replay,
                tuple(rounds),
                completion,
                source_seal_hash=tree.manifest_hash,
            )
        ),
    )
    return tuple(rounds), completion


def run_online_baseline(
    snapshot: StructuralInputSnapshot,
    *,
    engine: Engine,
    shadow_database: Path,
    source_database: Path,
    policy: PolicyArtifact,
    requested_at: datetime,
    fixture_only: bool = False,
    generation_request_id: str | None = None,
    approval: Mapping[str, object] | None = None,
) -> RecordedWorld:
    with OntologyUnitOfWork(engine) as uow:
        registered = uow.discovery.policy(policy.policy_revision_id)
        if registered is None or registered.source_artifact_hash != contract_hash(policy):
            raise ValueError("online policy must have a matching registered artifact")
    environment = OnlineRecordingEnvironment(
        snapshot,
        engine=engine,
        shadow_database=shadow_database,
        source_database=source_database,
        policy_revision_id=policy.policy_revision_id,
        requested_at=requested_at,
        fixture_only=fixture_only,
        generation_request_id=generation_request_id,
        approval=approval,
    )
    observation = environment.reset()
    terminal = None
    for round_number in _policy_rounds(policy):
        decision = policy_decision(policy, round_number, observation)
        if isinstance(decision, ContinueBatch):
            observation = environment.continue_batch(decision).observation
        else:
            terminal = environment.stop(decision)
    if terminal is None:
        raise ValueError("baseline did not stop")
    with OntologyUnitOfWork(engine) as uow:
        seal = uow.discovery.world_events(observation.world_id)[-1]
    return RecordedWorld(observation.world_id, seal.manifest_hash, terminal.selected_node_ids)


def run_registered_replay(
    engine: Engine,
    world_id: str,
    policy: PolicyArtifact,
    pilot: PilotContract,
    *,
    seed: int,
    requested_at: datetime,
) -> ReplayResult:
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.discovery
        registered = repo.policy(policy.policy_revision_id)
        if registered is None or registered.source_artifact_hash != contract_hash(policy):
            raise ValueError("replay requires registered matching policy artifact")
        world = repo.world(world_id)
        if world is None or repo.world_state(world_id) != "sealed":
            raise ValueError("replay requires sealed world")
        nodes = repo.nodes_for_world(world_id)
        tree = SealedTree.from_rows(
            world,
            nodes,
            repo.world_events(world_id),
            {
                node.node_id: evaluation
                for node in nodes
                if (evaluation := repo.latest_node_evaluation(node.node_id)) is not None
            },
        )
    replay_id = f"policy-replay-{canonical_hash([world_id, policy.policy_revision_id, seed])[:24]}"
    replay = PolicyReplayRunRow(
        policy_replay_run_id=replay_id,
        policy_revision_id=policy.policy_revision_id,
        world_id=world_id,
        initial_observation_hash=canonical_hash({"visible_node_ids": [tree.root_id]}),
        evaluator_revision=world.evaluator_revision,
        cost_policy_revision=COST_POLICY_REVISION,
        random_seed=seed,
        started_at=requested_at.isoformat(),
        action_id="pending",
    )
    rounds, completion = _trace(tree, policy, pilot, replay, requested_at)
    reproduced = _trace(tree, policy, pilot, replay, requested_at)
    if reproduced != (rounds, completion):
        raise ValueError("policy replay failed independent reproduction")
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    start = actions.start_replay(
        StartPolicyReplayRequest(
            replay=replay,
            initial_observation={"visible_node_ids": [tree.root_id]},
            actor_id="sys:discovery-replay",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"{replay_id}:start",
            requested_at=requested_at,
        )
    )
    if start.status is not ActionStatus.COMMITTED:
        raise ValueError("policy replay start did not commit")
    finish = actions.finish_replay(
        FinishPolicyReplayRequest(
            replay_run_id=replay_id,
            rounds=rounds,
            completion=completion,
            actor_id="sys:discovery-replay",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"{replay_id}:finish",
            requested_at=requested_at,
        )
    )
    if finish.status is not ActionStatus.COMMITTED:
        raise ValueError("policy replay finish did not commit")
    with OntologyUnitOfWork(engine) as uow:
        persisted = uow.discovery.policy_replay_completion(replay_id)
        if persisted is None or persisted.trace_hash != completion.trace_hash:
            raise ValueError("persisted replay trace differs from reproduction")
    return ReplayResult(replay_id, completion.trace_hash, tuple(completion.selected_node_ids))
