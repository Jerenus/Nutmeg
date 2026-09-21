"""Typed, append-only discovery world lifecycle Actions (D1 storage boundary)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import ProvenanceMode, canonical_hash
from nutmeg.ontology.repository.discovery import (
    DiscoveryRunRow,
    NodeEvaluationRow,
    NodeRow,
    WorldEventRow,
    WorldRow,
)

_PILOT_PATH = (
    Path(__file__).resolve().parents[3]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _event(
    world_id: str,
    sequence: int,
    kind: str,
    reason: str,
    manifest_hash: str | None,
    command: ActionCommand,
) -> WorldEventRow:
    return WorldEventRow(
        world_event_id=f"WE-{uuid4().hex}",
        world_id=world_id,
        sequence_no=sequence,
        event_kind=kind,
        reason=reason,
        manifest_hash=manifest_hash,
        occurred_at=command.requested_at,
        action_id=command.action_id,
    )


@dataclass(frozen=True, slots=True)
class CreateDiscoveryWorldRequest:
    world: WorldRow
    root: NodeRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class StartDiscoveryRunRequest:
    run: DiscoveryRunRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RecordDiscoveryNodeRequest:
    node: NodeRow
    evaluation: NodeEvaluationRow | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RecordDiscoveryFailureRequest:
    node: NodeRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class SealDiscoveryWorldRequest:
    world_id: str
    terminal_reason: str
    sealed_manifest_hash: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class DiscoveryWorldActions:
    def __init__(self, action_service: ActionService) -> None:
        self._svc = action_service

    def _command(self, action_type: str, request, payload: dict) -> ActionCommand:
        return ActionCommand.create(
            action_type=action_type,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload=payload,
        )

    def create_world(self, request: CreateDiscoveryWorldRequest) -> ActionOutcome:
        command = self._command(
            "create_discovery_world",
            request,
            {
                "world": asdict(request.world),
                "root": asdict(request.root),
            },
        )

        def handler(uow, cmd):
            from nutmeg.discovery.contracts import canonical_hash as contract_hash
            from nutmeg.discovery.contracts import load_pilot_contract

            world, root = request.world, request.root
            if canonical_hash(world.input_manifest) != world.input_manifest_hash:
                raise ValueError("world input manifest hash mismatch")
            pilot = load_pilot_contract(_PILOT_PATH)
            if world.pilot_contract_hash != contract_hash(pilot):
                raise ValueError("pilot contract hash mismatch")
            if (
                world.task_family != pilot.task_family
                or world.evaluator_revision != pilot.evaluator.revision
            ):
                raise ValueError("world task/evaluator does not match frozen pilot")
            ProvenanceMode(world.provenance_mode)
            if (
                world.provenance_mode == ProvenanceMode.PROSPECTIVE_ONLINE
                and not world.isolated_store_identity.startswith("shadow:")
            ):
                raise ValueError("prospective world requires shadow isolation")
            if root.node_id != world.root_node_id or root.world_id != world.world_id:
                raise ValueError("root must belong to the world")
            if (
                root.parent_node_id is not None
                or root.discovery_run_id is not None
                or root.creation_sequence != 1
            ):
                raise ValueError("root lineage is invalid")
            if uow.discovery.world(world.world_id) is not None:
                raise ValueError("world already exists")
            uow.discovery.insert_world(replace(world, action_id=cmd.action_id))
            uow.discovery.insert_node(replace(root, action_id=cmd.action_id))
            event = _event(
                world.world_id, 1, "created", "world_created", world.input_manifest_hash, cmd
            )
            uow.discovery.insert_world_event(event)
            return (
                ObjectRef("discovery_world", world.world_id),
                ObjectRef("discovery_node", root.node_id),
            )

        return self._svc.execute(command, handler, acquire_write_lock=True)

    def start_run(self, request: StartDiscoveryRunRequest) -> ActionOutcome:
        command = self._command("start_discovery_run", request, {"run": asdict(request.run)})

        def handler(uow, cmd):
            run = request.run
            world = uow.discovery.world(run.world_id)
            if world is None or uow.discovery.world_state(run.world_id) != "created":
                raise ValueError("world must be created before starting a run")
            policy = uow.discovery.policy(run.policy_revision_id)
            if policy is None or not policy.validation_result.get("valid"):
                raise ValueError("run requires a validated registered policy")
            if world.task_family not in policy.compatible_world_families:
                raise ValueError("policy is incompatible with world family")
            uow.discovery.insert_run(replace(run, action_id=cmd.action_id))
            events = uow.discovery.world_events(run.world_id)
            uow.discovery.insert_world_event(
                _event(run.world_id, len(events) + 1, "run_started", "policy_bound", None, cmd)
            )
            return (ObjectRef("discovery_run", run.discovery_run_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    @staticmethod
    def _validate_node(uow, node: NodeRow) -> WorldRow:
        world = uow.discovery.world(node.world_id)
        if world is None or uow.discovery.world_state(node.world_id) != "running":
            raise ValueError("terminal or missing world cannot accept nodes")
        run = uow.discovery.run(node.discovery_run_id) if node.discovery_run_id else None
        if run is None or run.world_id != node.world_id:
            raise ValueError("node requires a run in the same world")
        parent = uow.discovery.node(node.parent_node_id) if node.parent_node_id else None
        if parent is None or parent.world_id != world.world_id:
            raise ValueError("node requires a visible parent in the same world")
        prior = uow.discovery.nodes_for_world(world.world_id)
        if node.creation_sequence != max(n.creation_sequence for n in prior) + 1:
            raise ValueError("node creation sequence is not next")
        if node.visibility_sequence != max(n.visibility_sequence for n in prior) + 1:
            raise ValueError("node visibility sequence is not next")
        if parent.visibility_sequence >= node.visibility_sequence:
            raise ValueError("node parent must be visible")
        operator = node.continuation_action.get("operator") if node.continuation_action else None
        if operator not in world.legal_action_schema.get("operators", []):
            raise ValueError("node operator is not legal")
        if (
            not node.policy_decision
            or node.policy_decision.get("policy_revision_id") != run.policy_revision_id
        ):
            raise ValueError("node policy decision does not match run")
        if (
            node.artifact_manifest is not None
            and canonical_hash(node.artifact_manifest) != node.artifact_manifest_hash
        ):
            raise ValueError("node artifact manifest hash mismatch")
        cutoff = datetime.fromisoformat(world.cutoff_at)
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("world cutoff must be timezone-aware")
        for ref in node.business_refs:
            captured = datetime.fromisoformat(ref["captured_at"])
            if captured.tzinfo is None or captured.utcoffset() is None or captured > cutoff:
                raise ValueError("node evidence exceeds world cutoff")
        if node.retry_of_node_id:
            retried = uow.discovery.node(node.retry_of_node_id)
            if (
                retried is None
                or retried.world_id != world.world_id
                or retried.execution_status != "failed"
            ):
                raise ValueError("retry must refer to a failed node in the same world")
        return world

    def record_node(self, request: RecordDiscoveryNodeRequest) -> ActionOutcome:
        command = self._command(
            "record_discovery_node",
            request,
            {
                "node": asdict(request.node),
                "evaluation": asdict(request.evaluation) if request.evaluation else None,
            },
        )

        def handler(uow, cmd):
            node = request.node
            self._validate_node(uow, node)
            uow.discovery.insert_node(replace(node, action_id=cmd.action_id))
            refs = [ObjectRef("discovery_node", node.node_id)]
            if request.evaluation:
                evaluation = request.evaluation
                if evaluation.node_id != node.node_id or evaluation.revision_no != 1:
                    raise ValueError("initial evaluation must belong to node at revision 1")
                uow.discovery.insert_node_evaluation(replace(evaluation, action_id=cmd.action_id))
                refs.append(ObjectRef("node_evaluation", evaluation.node_evaluation_id))
            return tuple(refs)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    def record_failure(self, request: RecordDiscoveryFailureRequest) -> ActionOutcome:
        command = self._command("record_discovery_failure", request, {"node": asdict(request.node)})

        def handler(uow, cmd):
            node = request.node
            self._validate_node(uow, node)
            if node.execution_status != "failed" or node.frontier_eligible:
                raise ValueError("failure must be non-frontier and failed")
            if not node.resource_cost or not node.diagnostic_codes:
                raise ValueError("failure requires cost and diagnostics")
            uow.discovery.insert_node(replace(node, action_id=cmd.action_id))
            return (ObjectRef("discovery_node", node.node_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    @staticmethod
    def seal_manifest(world: WorldRow, nodes: tuple[NodeRow, ...]) -> str:
        return canonical_hash(
            {
                "world_id": world.world_id,
                "input_manifest_hash": world.input_manifest_hash,
                "nodes": [asdict(node) for node in nodes],
            }
        )

    def seal_world(self, request: SealDiscoveryWorldRequest) -> ActionOutcome:
        command = self._command(
            "seal_discovery_world",
            request,
            {
                "world_id": request.world_id,
                "terminal_reason": request.terminal_reason,
                "sealed_manifest_hash": request.sealed_manifest_hash,
            },
        )

        def handler(uow, cmd):
            world = uow.discovery.world(request.world_id)
            if world is None or uow.discovery.world_state(request.world_id) != "running":
                raise ValueError("terminal or missing world cannot be sealed")
            nodes = uow.discovery.nodes_for_world(world.world_id)
            if not request.terminal_reason:
                raise ValueError("seal requires a terminal reason")
            for node in nodes[1:]:
                if (
                    not node.parent_node_id
                    or not node.continuation_action
                    or node.artifact_manifest is None
                    or node.resource_cost is None
                    or node.diagnostic_codes is None
                ):
                    raise ValueError("incomplete node lineage")
            if request.terminal_reason != "no_solution" and not any(
                node.execution_status == "complete"
                and (evaluation := uow.discovery.latest_node_evaluation(node.node_id)) is not None
                and evaluation.selectable
                for node in nodes[1:]
            ):
                raise ValueError("seal requires a selectable terminal or explicit no_solution")
            if self.seal_manifest(world, nodes) != request.sealed_manifest_hash:
                raise ValueError("sealed manifest hash mismatch")
            event = _event(
                world.world_id,
                len(uow.discovery.world_events(world.world_id)) + 1,
                "sealed",
                request.terminal_reason,
                request.sealed_manifest_hash,
                cmd,
            )
            uow.discovery.insert_world_event(event)
            return (ObjectRef("discovery_world_event", event.world_event_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)
