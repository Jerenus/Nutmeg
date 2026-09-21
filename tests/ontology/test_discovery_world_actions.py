from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.ontology.actions.discovery_world_actions import (
    CreateDiscoveryWorldRequest,
    DiscoveryWorldActions,
    RecordDiscoveryFailureRequest,
    RecordDiscoveryNodeRequest,
    SealDiscoveryWorldRequest,
    StartDiscoveryRunRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import DiscoveryRunRow, NodeEvaluationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_discovery_repository import _node, _policy, _record, _world

T0 = datetime(2026, 9, 21, 7, 1, tzinfo=UTC)
PILOT = load_pilot_contract(
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _rig(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return DiscoveryWorldActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _request(**changes):
    world = _world()
    world = replace(
        world,
        input_manifest_hash=canonical_hash(world.input_manifest),
        pilot_contract_hash=contract_hash(PILOT),
        legal_action_schema={"operators": ["enumerate_template_shard", "stop"]},
    )
    return CreateDiscoveryWorldRequest(
        world=changes.pop("world", world),
        root=changes.pop("root", _node("node-root", 1)),
        actor_id=changes.pop("actor_id", "op:jun"),
        actor_role=changes.pop("actor_role", ActorRole.JUDGE_OPERATOR),
        idempotency_key=changes.pop("idempotency_key", "world:create"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def test_create_world_atomically_writes_root_and_created_event(tmp_path):
    actions, engine = _rig(tmp_path)
    outcome = actions.create_world(_request())
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world("world-1") is not None
        assert [n.node_id for n in uow.discovery.nodes_for_world("world-1")] == ["node-root"]
        assert uow.discovery.world_state("world-1") == "created"
        assert {r.object_type for r in outcome.result_refs} == {"discovery_world", "discovery_node"}
        assert [event.action_id for event in uow.outbox.after(0, limit=10)] == [outcome.action_id]


def test_create_world_rejects_manifest_hash_mismatch(tmp_path):
    actions, engine = _rig(tmp_path)
    request = _request()
    with pytest.raises(ValueError, match="hash mismatch"):
        actions.create_world(
            replace(request, world=replace(request.world, input_manifest={"snapshot": "tampered"}))
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world("world-1") is None


def _start_request(**changes):
    return StartDiscoveryRunRequest(
        run=changes.pop("run", _record(DiscoveryRunRow, discovery_run_id="run-1")),
        actor_id=changes.pop("actor_id", "sys:discovery"),
        actor_role=changes.pop("actor_role", ActorRole.DETERMINISTIC_SYSTEM),
        idempotency_key=changes.pop("idempotency_key", "run:start"),
        requested_at=T0,
        **changes,
    )


def _node_request(node_id="node-child", sequence=2, *, status="complete", **changes):
    node = _node(
        node_id,
        sequence,
        parent_node_id="node-root",
        discovery_run_id="run-1",
        continuation_action={"operator": "enumerate_template_shard"},
        policy_decision={"policy_revision_id": "policy-1"},
        artifact_manifest={},
        artifact_manifest_hash=canonical_hash({}),
        resource_cost={"wall_ms": 12},
        diagnostic_codes=[],
        business_refs=[],
        execution_status=status,
        **changes,
    )
    evaluation = _record(
        NodeEvaluationRow,
        node_evaluation_id=f"eval-{node_id}",
        node_id=node_id,
        revision_no=1,
        result={"score": 1},
        selectable=True,
    )
    return RecordDiscoveryNodeRequest(
        node=node,
        evaluation=evaluation,
        actor_id="sys:discovery",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key=f"node:{node_id}",
        requested_at=T0,
    )


def _created(actions, engine, *, compatible=True):
    actions.create_world(_request())
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(
            replace(
                _policy("policy-1"),
                validation_result={"valid": True},
                compatible_world_families=["structural_candidate_audit"]
                if compatible
                else ["other"],
            )
        )


def _running(actions, engine):
    _created(actions, engine)
    assert actions.start_run(_start_request()).status is ActionStatus.COMMITTED


def test_start_run_requires_registered_compatible_policy(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.create_world(_request())
    with pytest.raises(ValueError, match="validated registered"):
        actions.start_run(_start_request())
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(
            replace(
                _policy("policy-1"),
                validation_result={"valid": True},
                compatible_world_families=["other"],
            )
        )
    with pytest.raises(ValueError, match="incompatible"):
        actions.start_run(_start_request())
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.run("run-1") is None
        assert uow.discovery.world_state("world-1") == "created"


def test_record_node_requires_visible_parent_same_world_and_cutoff_safe_refs(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    request = _node_request()
    with pytest.raises(ValueError, match="visible parent"):
        actions.record_node(replace(request, node=replace(request.node, parent_node_id="foreign")))
    with pytest.raises(ValueError, match="cutoff"):
        actions.record_node(
            replace(
                request,
                node=replace(
                    request.node, business_refs=[{"captured_at": "2026-09-21T08:00:00+00:00"}]
                ),
            )
        )
    with pytest.raises(ValueError, match="cutoff"):
        actions.record_node(
            replace(
                request,
                node=replace(
                    request.node, business_refs=[{"captured_at": "2026-09-21T06:00:00-02:00"}]
                ),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert [node.node_id for node in uow.discovery.nodes_for_world("world-1")] == ["node-root"]


def test_record_failure_charges_cost_and_has_no_selectable_evaluation(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    node = replace(
        _node_request(status="failed").node,
        frontier_eligible=False,
        diagnostic_codes=["timeout"],
        resource_cost={"wall_ms": 1000},
    )
    outcome = actions.record_failure(
        RecordDiscoveryFailureRequest(
            node=node,
            actor_id="sys:discovery",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="node:fail",
            requested_at=T0,
        )
    )
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.node("node-child").resource_cost == {"wall_ms": 1000}
        assert uow.discovery.latest_node_evaluation("node-child") is None


def test_record_failure_rejects_tampered_artifact_manifest(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    node = replace(
        _node_request(status="failed").node,
        diagnostic_codes=["timeout"],
        frontier_eligible=False,
        artifact_manifest={"tampered": True},
    )
    with pytest.raises(ValueError, match="artifact manifest hash mismatch"):
        actions.record_failure(
            RecordDiscoveryFailureRequest(
                node=node,
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="node:tampered",
                requested_at=T0,
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.node("node-child") is None


def test_retry_is_new_node_and_preserves_failed_node(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    failed = replace(
        _node_request(status="failed").node, frontier_eligible=False, diagnostic_codes=["timeout"]
    )
    actions.record_failure(
        RecordDiscoveryFailureRequest(
            node=failed,
            actor_id="sys:discovery",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="node:fail",
            requested_at=T0,
        )
    )
    retry = _node_request("node-retry", 3, retry_of_node_id="node-child")
    assert actions.record_node(retry).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.discovery.nodes_for_world("world-1")) == 3
        assert uow.discovery.node("node-retry").retry_of_node_id == "node-child"
        assert uow.discovery.node("node-child").execution_status == "failed"


def test_seal_requires_terminal_run_complete_lineage_and_matching_manifest(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    invalid = _node_request()
    invalid = replace(invalid, node=replace(invalid.node, resource_cost=None))
    actions.record_node(invalid)
    with pytest.raises(ValueError, match="incomplete node lineage"):
        actions.seal_world(
            SealDiscoveryWorldRequest(
                world_id="world-1",
                terminal_reason="done",
                sealed_manifest_hash="bad",
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="seal:bad",
                requested_at=T0,
            )
        )


def test_sealed_world_rejects_new_nodes(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    actions.record_node(_node_request())
    with OntologyUnitOfWork(engine) as uow:
        world = uow.discovery.world("world-1")
        nodes = uow.discovery.nodes_for_world("world-1")
    seal = SealDiscoveryWorldRequest(
        world_id="world-1",
        terminal_reason="done",
        sealed_manifest_hash=actions.seal_manifest(world, nodes),
        actor_id="sys:discovery",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="seal:ok",
        requested_at=T0,
    )
    with pytest.raises(ValueError, match="sealed manifest hash mismatch"):
        actions.seal_world(replace(seal, sealed_manifest_hash="bad", idempotency_key="seal:bad"))
    assert actions.seal_world(seal).status is ActionStatus.COMMITTED
    with pytest.raises(ValueError, match="terminal"):
        actions.record_node(_node_request("late", 3))


def test_seal_rejects_failed_only_world_as_success(tmp_path):
    actions, engine = _rig(tmp_path)
    _running(actions, engine)
    failed = replace(
        _node_request(status="failed").node,
        frontier_eligible=False,
        diagnostic_codes=["timeout"],
        terminal_reason="timeout",
    )
    actions.record_failure(
        RecordDiscoveryFailureRequest(
            node=failed,
            actor_id="sys:discovery",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="node:fail",
            requested_at=T0,
        )
    )
    with OntologyUnitOfWork(engine) as uow:
        world = uow.discovery.world("world-1")
        nodes = uow.discovery.nodes_for_world("world-1")
    with pytest.raises(ValueError, match="selectable|no_solution"):
        actions.seal_world(
            SealDiscoveryWorldRequest(
                world_id="world-1",
                terminal_reason="done",
                sealed_manifest_hash=actions.seal_manifest(world, nodes),
                actor_id="sys:discovery",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="seal:failed",
                requested_at=T0,
            )
        )


def test_ai_analyst_cannot_create_or_mutate_world(tmp_path):
    actions, engine = _rig(tmp_path)
    denied = actions.create_world(
        _request(actor_role=ActorRole.AI_ANALYST, idempotency_key="world:create:ai")
    )
    assert denied.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world("world-1") is None
    _running(actions, engine)
    denied_requests = (
        (
            actions.start_run,
            replace(_start_request(), actor_role=ActorRole.AI_ANALYST, idempotency_key="ai:start"),
        ),
        (
            actions.record_node,
            replace(_node_request(), actor_role=ActorRole.AI_ANALYST, idempotency_key="ai:node"),
        ),
        (
            actions.record_failure,
            RecordDiscoveryFailureRequest(
                node=replace(_node_request(status="failed").node, diagnostic_codes=["timeout"]),
                actor_id="ai",
                actor_role=ActorRole.AI_ANALYST,
                idempotency_key="ai:fail",
                requested_at=T0,
            ),
        ),
        (
            actions.seal_world,
            SealDiscoveryWorldRequest(
                world_id="world-1",
                terminal_reason="no_solution",
                sealed_manifest_hash="a" * 64,
                actor_id="ai",
                actor_role=ActorRole.AI_ANALYST,
                idempotency_key="ai:seal",
                requested_at=T0,
            ),
        ),
    )
    for action, request in denied_requests:
        assert action(request).status is ActionStatus.REJECTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state("world-1") == "running"
        assert len(uow.discovery.nodes_for_world("world-1")) == 1
