"""Verified sealed world source; child index is never policy-visible."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.discovery import (
    NodeEvaluationRow,
    NodeRow,
    WorldEventRow,
    WorldRow,
)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("sealed evidence requires timezone-aware timestamps")
    return parsed


@dataclass(frozen=True, slots=True)
class SealedTree:
    world: WorldRow
    nodes: tuple[NodeRow, ...]
    evaluations: Mapping[str, NodeEvaluationRow]
    manifest_hash: str
    _children: Mapping[tuple[str, str], tuple[NodeRow, ...]] = field(repr=False)

    @property
    def root_id(self) -> str:
        return self.world.root_node_id

    def child_for(self, parent_id: str, continuation: dict[str, object]) -> NodeRow | None:
        children = self.children_for(parent_id, continuation)
        return children[0] if children else None

    def children_for(self, parent_id: str, continuation: dict[str, object]) -> tuple[NodeRow, ...]:
        return self._children.get((parent_id, canonical_hash(continuation)), ())

    @classmethod
    def from_rows(
        cls,
        world: WorldRow,
        nodes: tuple[NodeRow, ...],
        events: tuple[WorldEventRow, ...],
        evaluations: Mapping[str, NodeEvaluationRow],
    ) -> SealedTree:
        if (
            not events
            or events[-1].event_kind != "sealed"
            or any(event.event_kind == "quarantined" for event in events)
        ):
            raise ValueError("world is not sealed or is quarantined")
        seal = events[-1]
        sealed_at = _aware(seal.occurred_at)
        if (
            seal.world_id != world.world_id
            or seal.manifest_hash != DiscoveryWorldActions.seal_manifest(world, nodes)
        ):
            raise ValueError("sealed manifest mismatch")
        if not nodes or nodes[0].node_id != world.root_node_id:
            raise ValueError("sealed root is missing")
        if (
            canonical_hash(world.input_manifest) != world.input_manifest_hash
            or nodes[0].artifact_manifest_hash != world.input_manifest_hash
            or nodes[0].artifact_manifest != world.input_manifest
        ):
            raise ValueError("frozen input manifest and root artifact disagree")
        cutoff = _aware(world.cutoff_at)
        for reference in world.input_manifest.get("references", ()):
            if _aware(reference["captured_at"]) > cutoff:
                raise ValueError("input reference occurs after world cutoff")
        if tuple(node.visibility_sequence for node in nodes) != tuple(range(1, len(nodes) + 1)):
            raise ValueError("sealed visibility order is not contiguous")
        known: set[str] = set()
        children: dict[tuple[str, str], tuple[NodeRow, ...]] = {}
        for node in nodes:
            if node.world_id != world.world_id or node.node_id in known:
                raise ValueError("cross-world or duplicate node")
            if node.finished_at and _aware(node.finished_at) > sealed_at:
                raise ValueError("node was recorded after seal")
            for reference in node.business_refs or ():
                if _aware(reference["captured_at"]) > cutoff:
                    raise ValueError("node reference occurs after world cutoff")
            if node.artifact_manifest is None or (
                canonical_hash(node.artifact_manifest) != node.artifact_manifest_hash
            ):
                raise ValueError("node artifact hash mismatch")
            if node.node_id != world.root_node_id:
                if node.parent_node_id not in known or not node.continuation_action:
                    raise ValueError("sealed node has no prior parent or action")
                if node.execution_status == "complete" and (
                    node.continuation_action.get("operator") != "stop"
                    and node.node_id not in evaluations
                ):
                    raise ValueError("completed node has no evaluation")
                evaluation = evaluations.get(node.node_id)
                if evaluation and _aware(evaluation.evaluated_at) > sealed_at:
                    raise ValueError("node evaluation was recorded after seal")
                key = (node.parent_node_id, canonical_hash(node.continuation_action))
                previous = children.get(key, ())
                if previous and (
                    node.retry_of_node_id != previous[-1].node_id
                    or previous[-1].execution_status != "failed"
                    or node.creation_sequence != previous[-1].creation_sequence + 1
                ):
                    raise ValueError("duplicate continuation key without linked failed retry")
                if not previous and node.retry_of_node_id:
                    raise ValueError("retry is missing its recorded initial attempt")
                children[key] = (*previous, node)
            known.add(node.node_id)
        return cls(world, nodes, dict(evaluations), seal.manifest_hash, children)
