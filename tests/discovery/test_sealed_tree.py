from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from nutmeg.discovery.sealed_tree import SealedTree
from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.discovery import NodeEvaluationRow
from tests.ontology.test_discovery_repository import _event, _node, _record, _world


def _source():
    manifest = {"references": [], "template_ids": ["T1"]}
    world = replace(_world(), input_manifest=manifest, input_manifest_hash=canonical_hash(manifest))
    root = replace(
        _node("node-root", 1),
        parent_node_id=None,
        artifact_manifest=manifest,
        artifact_manifest_hash=canonical_hash(manifest),
        finished_at="2026-09-21T07:00:00+00:00",
    )
    child = replace(
        _node("child", 2),
        parent_node_id="node-root",
        continuation_action={"operator": "enumerate_template_shard", "template_ids": ["T1"]},
        artifact_manifest={"child": True},
        artifact_manifest_hash=canonical_hash({"child": True}),
        execution_status="complete",
        finished_at="2026-09-21T07:00:00+00:00",
    )
    nodes = (root, child)
    event = replace(
        _event(3, "sealed"), manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes)
    )
    evaluation = _record(NodeEvaluationRow, node_id="child", selectable=True, result={})
    return world, nodes, event, {"child": evaluation}


def test_sealed_tree_verifies_complete_source_before_index():
    world, nodes, event, evaluations = _source()
    tree = SealedTree.from_rows(world, nodes, (event,), evaluations)
    assert tree.root_id == "node-root"
    assert (
        tree.child_for(
            "node-root", {"operator": "enumerate_template_shard", "template_ids": ["T1"]}
        ).node_id
        == "child"
    )


@pytest.mark.parametrize(
    "mutation",
    ["manifest", "root", "order", "artifact", "future", "duplicate", "evaluation", "event"],
)
def test_invalid_sealed_world_is_rejected(mutation):
    world, nodes, event, evaluations = _source()
    if mutation == "manifest":
        nodes = (nodes[0], replace(nodes[1], diagnostic_codes=["tampered"]))
    elif mutation == "root":
        world = replace(world, root_node_id="missing")
    elif mutation == "order":
        nodes = (nodes[0], replace(nodes[1], visibility_sequence=3))
    elif mutation == "artifact":
        nodes = (nodes[0], replace(nodes[1], artifact_manifest_hash="wrong"))
    elif mutation == "future":
        nodes = (nodes[0], replace(nodes[1], finished_at="2026-09-22T00:00:00+00:00"))
    elif mutation == "duplicate":
        duplicate = replace(nodes[1], node_id="other", creation_sequence=3, visibility_sequence=3)
        nodes = (*nodes, duplicate)
        event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    elif mutation == "evaluation":
        evaluations = {}
    elif mutation == "event":
        event = replace(event, event_kind="quarantined")
    with pytest.raises(ValueError):
        SealedTree.from_rows(world, nodes, (event,), evaluations)


def test_seal_event_timestamp_is_timezone_aware():
    world, nodes, event, evaluations = _source()
    assert datetime.fromisoformat(event.occurred_at).tzinfo is not None
    with pytest.raises(ValueError):
        SealedTree.from_rows(
            world, nodes, (replace(event, occurred_at="2026-09-21T07:03:00"),), evaluations
        )


def test_linked_retry_is_one_unambiguous_recorded_continuation():
    world, nodes, event, evaluations = _source()
    failed = replace(nodes[1], execution_status="failed", diagnostic_codes=["timeout"])
    retry = replace(
        nodes[1],
        node_id="retry",
        creation_sequence=3,
        visibility_sequence=3,
        retry_of_node_id="child",
    )
    nodes = (nodes[0], failed, retry)
    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    tree = SealedTree.from_rows(
        world, nodes, (event,), {"retry": replace(evaluations["child"], node_id="retry")}
    )
    assert tuple(
        node.node_id
        for node in tree.children_for(
            "node-root", {"operator": "enumerate_template_shard", "template_ids": ["T1"]}
        )
    ) == ("child", "retry")


def test_reference_after_cutoff_rejected_even_when_seal_is_recomputed():
    world, nodes, event, evaluations = _source()
    nodes = (
        nodes[0],
        replace(
            nodes[1],
            business_refs=[
                {
                    "kind": "candidate_request",
                    "id": "late",
                    "source_revision": "1",
                    "captured_at": "2026-09-22T00:00:00+00:00",
                }
            ],
        ),
    )
    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    with pytest.raises(ValueError, match="cutoff"):
        SealedTree.from_rows(world, nodes, (event,), evaluations)


def test_changed_frozen_input_rejected_even_when_seal_is_recomputed():
    world, nodes, event, evaluations = _source()
    world = replace(world, input_manifest={**world.input_manifest, "template_ids": ["late"]})
    event = replace(event, manifest_hash=DiscoveryWorldActions.seal_manifest(world, nodes))
    with pytest.raises(ValueError, match="input manifest"):
        SealedTree.from_rows(world, nodes, (event,), evaluations)
