from types import SimpleNamespace

from nutmeg.discovery.brake_monitor import brake_condition


def test_registered_hard_condition_trips_once():
    deployment = SimpleNamespace(brake_conditions={"conditions": ["permission_leak"]})
    assert brake_condition(
        deployment, {"permission_leak": "evidence-hash"}, already_braked=False
    ) == ("permission_leak", "evidence-hash")
    assert (
        brake_condition(deployment, {"permission_leak": "evidence-hash"}, already_braked=True)
        is None
    )


def test_unregistered_or_unverified_condition_never_selects_target():
    deployment = SimpleNamespace(brake_conditions={"conditions": ["permission_leak"]})
    assert (
        brake_condition(deployment, {"resource_overrun": "evidence-hash"}, already_braked=False)
        is None
    )
    assert brake_condition(deployment, {"permission_leak": ""}, already_braked=False) is None


def test_monitor_requires_persisted_committed_node_diagnostic(tmp_path):
    from nutmeg.discovery.brake_monitor import monitor_committed_fact
    from tests.ontology.test_discovery_governance_actions import _rig

    _actions, engine = _rig(tmp_path)
    assert monitor_committed_fact(engine, "uncommitted-fact") is None


def test_committed_failure_trips_exact_registered_brake_once(tmp_path):
    from dataclasses import replace
    from datetime import UTC, datetime

    import pytest

    from nutmeg.discovery.brake_monitor import monitor_committed_fact
    from nutmeg.ontology.actions.discovery_governance_actions import (
        DiscoveryGovernanceActions,
        TripPolicyBrakeRequest,
    )
    from nutmeg.ontology.actions.discovery_world_actions import (
        DiscoveryWorldActions,
        RecordDiscoveryFailureRequest,
        StartDiscoveryRunRequest,
    )
    from nutmeg.ontology.actions.models import ActionStatus, ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.discovery.models import canonical_hash
    from nutmeg.ontology.repository.discovery import DiscoveryRunRow
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from tests.discovery.test_online_recorder import _rig
    from tests.ontology.test_discovery_governance_actions import _deployment_request
    from tests.ontology.test_discovery_repository import _event, _node, _policy, _record, _world

    engine = _rig(tmp_path)
    at = datetime(2026, 9, 22, tzinfo=UTC)
    policy_id = "structural-baseline-v1"
    with OntologyUnitOfWork(engine) as uow:
        world = replace(_world(), root_node_id="node-root",
                        legal_action_schema={"operators": ["stop"]})
        uow.discovery.insert_world(world)
        uow.discovery.insert_world_event(_event(1, "created"))
        uow.discovery.insert_node(replace(_node("node-root", 1),
                                          parent_node_id=None, discovery_run_id=None))
        uow.discovery.insert_policy(replace(_policy("prior"),
                                            family="structural_candidate_exploration"))
        uow.discovery.insert_deployment(replace(
            _deployment_request("deploy", policy_id=policy_id).deployment,
            policy_family="structural_candidate_exploration",
            rollback_policy_revision_id="prior",
            brake_conditions={"conditions": ["permission_leak"]},
            effective_boundary="2026-09-21T00:00:00+00:00",
        ))
    actions = DiscoveryWorldActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    run = _record(DiscoveryRunRow, world_id="world-1", discovery_run_id="run-1",
                  policy_revision_id=policy_id, environment_mode="shadow")
    assert actions.start_run(StartDiscoveryRunRequest(run, "sys:test",
        ActorRole.DETERMINISTIC_SYSTEM, "run:brake", at)).status is ActionStatus.COMMITTED
    artifact = {"failure": "permission_leak"}
    node = replace(_node("failed-1", 2), world_id="world-1", discovery_run_id="run-1",
                   parent_node_id="node-root", continuation_action={"operator": "stop"},
                   policy_decision={"policy_revision_id": policy_id},
                   artifact_manifest=artifact, artifact_manifest_hash=canonical_hash(artifact),
                   diagnostic_codes=["permission_leak"], execution_status="failed",
                   frontier_eligible=False, resource_cost={"wall_ms": 1}, business_refs=[])
    fact = actions.record_failure(RecordDiscoveryFailureRequest(
        node, "sys:test", ActorRole.DETERMINISTIC_SYSTEM, "node:brake", at))
    assert fact.status is ActionStatus.COMMITTED
    first = monitor_committed_fact(engine, fact.action_id,
                                   boundary="2026-09-23T00:00:00+00:00")
    assert first.status is ActionStatus.COMMITTED
    assert monitor_committed_fact(engine, fact.action_id) is None
    with OntologyUnitOfWork(engine) as uow:
        brake = uow.discovery.latest_brake("dep-1")
        assert brake.condition_code == "permission_leak"
        assert brake.restored_policy_revision_id == "prior"
        forged = replace(brake, policy_brake_event_id="forged",
                         evidence=brake.evidence | {"request_hash": "forged"})
    with pytest.raises(ValueError, match="active unbraked|evidence"):
        DiscoveryGovernanceActions(ActionService(lambda: OntologyUnitOfWork(engine))).trip_brake(
            TripPolicyBrakeRequest(forged, "sys:test", ActorRole.DETERMINISTIC_SYSTEM,
                                   "brake:forged", at))
