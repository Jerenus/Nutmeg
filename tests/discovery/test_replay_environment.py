from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.environment import Continue, ContinueBatch, Stop
from nutmeg.discovery.replay_environment import ReplayEnvironment
from nutmeg.discovery.sealed_tree import SealedTree
from nutmeg.ontology.discovery.models import canonical_hash
from tests.discovery.test_sealed_tree import _source

PILOT = load_pilot_contract(
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _replay(*, max_nodes=4):
    world, nodes, event, evaluations = _source()
    manifest = {"references": [], "template_ids": ["T1", "T2"]}
    nodes = (
        replace(
            nodes[0],
            frontier_eligible=True,
            artifact_manifest=manifest,
            artifact_manifest_hash=canonical_hash(manifest),
        ),
        nodes[1],
    )
    world = replace(
        world,
        pilot_contract_hash=contract_hash(PILOT),
        resource_budget={"max_rounds": 2, "max_nodes": max_nodes, "max_concurrency": 2},
        input_manifest=manifest,
        input_manifest_hash=canonical_hash(manifest),
    )
    from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions

    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    return ReplayEnvironment(SealedTree.from_rows(world, nodes, (event,), evaluations), PILOT)


def test_reset_exposes_only_root_and_no_hidden_artifact_or_score():
    replay = _replay(max_nodes=3)
    observation = replay.reset()
    assert observation.visible_node_ids == ("node-root",)
    assert observation.task_family == "structural_candidate_audit"
    assert observation.remaining_candidate_generation_count is not None
    assert observation.remaining_wall_ms is not None
    assert observation.frontier_node_ids == ("node-root",)
    assert "child" not in repr(observation)
    assert observation.revealed_nodes == ()


def test_exact_continuation_reveals_child_and_allows_stop():
    replay = _replay()
    replay.reset()
    step = replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))
    assert step.revealed_node_ids == ("child",)
    assert step.observation.visible_node_ids == ("node-root", "child")
    assert step.observation.revealed_nodes[0].node_id == "child"
    assert step.observation.revealed_nodes[0].artifact_manifest_hash
    assert step.observation.revealed_nodes[0].diagnostic_codes == ()
    assert ("wall_ms", "0") not in step.observation.revealed_nodes[0].resource_cost
    assert replay.stop(Stop(("child",))).selected_node_ids == ("child",)


def test_unknown_branch_is_charged_without_revealing_or_executing():
    replay = _replay(max_nodes=3)
    replay.reset()
    step = replay.continue_batch(ContinueBatch((Continue("node-root", ("T2",)),)))
    assert step.failure_codes == ("branch_unavailable",)
    assert step.charged_cost["wall_ms"] is None
    assert step.revealed_node_ids == ()
    assert step.observation.visible_node_ids == ("node-root",)
    assert step.observation.remaining_nodes == 0


def test_hidden_parent_and_repeated_branch_are_rejected():
    replay = _replay()
    replay.reset()
    with pytest.raises(ValueError, match="frontier"):
        replay.continue_batch(ContinueBatch((Continue("child", ("T1",)),)))
    replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))
    with pytest.raises(ValueError, match="consumed"):
        replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))


def test_budget_exhaustion_never_exposes_more_nodes():
    replay = _replay()
    replay.reset()
    replay.continue_batch(ContinueBatch((Continue("node-root", ("T2",)),)))
    replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))
    with pytest.raises(ValueError, match="round budget"):
        replay.continue_batch(ContinueBatch((Continue("node-root", ("T2",)),)))


def test_failed_recorded_child_is_visible_with_diagnostics():
    from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions

    world, nodes, event, _ = _source()
    nodes = (
        nodes[0],
        replace(
            nodes[1],
            execution_status="failed",
            diagnostic_codes=["timeout"],
            frontier_eligible=False,
        ),
    )
    world = replace(
        world,
        pilot_contract_hash=contract_hash(PILOT),
        resource_budget={"max_rounds": 2, "max_nodes": 3, "max_concurrency": 2},
    )
    nodes = (replace(nodes[0], frontier_eligible=True), nodes[1])
    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    replay = ReplayEnvironment(SealedTree.from_rows(world, nodes, (event,), {}), PILOT)
    replay.reset()
    step = replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))
    assert step.observation.revealed_nodes[0].diagnostic_codes == ("timeout",)


def test_linked_retry_reveals_both_recorded_attempts_and_charges_both():
    from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions

    world, nodes, event, evaluations = _source()
    failed = replace(
        nodes[1], execution_status="failed", diagnostic_codes=["timeout"], frontier_eligible=False
    )
    retry = replace(
        nodes[1],
        node_id="retry",
        creation_sequence=3,
        visibility_sequence=3,
        retry_of_node_id="child",
    )
    nodes = (replace(nodes[0], frontier_eligible=True), failed, retry)
    world = replace(
        world,
        pilot_contract_hash=contract_hash(PILOT),
        resource_budget={"max_rounds": 2, "max_nodes": 4, "max_concurrency": 2},
    )
    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    tree = SealedTree.from_rows(
        world, nodes, (event,), {"retry": replace(evaluations["child"], node_id="retry")}
    )
    replay = ReplayEnvironment(tree, PILOT)
    replay.reset()
    result = replay.continue_batch(ContinueBatch((Continue("node-root", ("T1",)),)))
    assert result.revealed_node_ids == ("child", "retry")
    assert result.charged_cost["attempts"] == 2
    assert result.failure_codes == ("timeout",)


def test_d2_recorded_fixture_is_a_valid_replay_source(tmp_path):
    from nutmeg.discovery.online_recorder import record_shadow_world
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from tests.discovery.test_online_adapter import _snapshot
    from tests.discovery.test_online_recorder import T0, _rig

    engine = _rig(tmp_path)
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=T0,
        fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.discovery
        world = repo.world(recorded.world_id)
        nodes = repo.nodes_for_world(recorded.world_id)
        tree = SealedTree.from_rows(
            world,
            nodes,
            repo.world_events(recorded.world_id),
            {
                node.node_id: evaluation
                for node in nodes
                if (evaluation := repo.latest_node_evaluation(node.node_id)) is not None
            },
        )
    replay = ReplayEnvironment(tree, PILOT)
    assert replay.reset().visible_node_ids == (world.root_node_id,)
    first = next(
        node
        for node in nodes
        if node.continuation_action
        and node.continuation_action.get("operator") == "enumerate_template_shard"
    )
    result = replay.continue_batch(
        ContinueBatch(
            (Continue(world.root_node_id, tuple(first.continuation_action["template_ids"])),)
        )
    )
    assert result.revealed_node_ids == (first.node_id,)
