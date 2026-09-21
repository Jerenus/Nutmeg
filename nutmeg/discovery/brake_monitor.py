"""Select only a registered hard invariant from committed external facts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from nutmeg.ontology.actions.discovery_governance_actions import (
    DiscoveryGovernanceActions,
    TripPolicyBrakeRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository.discovery import PolicyBrakeEventRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def brake_condition(deployment, committed_facts: dict[str, str], *, already_braked: bool):
    if already_braked:
        return None
    registered = deployment.brake_conditions.get("conditions", ())
    for code in registered:
        evidence_hash = committed_facts.get(code)
        if evidence_hash:
            return code, evidence_hash
    return None


def monitor_committed_fact(engine, action_id: str, *, boundary: str | None = None):
    """Consume a committed node diagnostic and invoke the reduce-only Action once."""
    with OntologyUnitOfWork(engine) as uow:
        action = uow.connection.execute(select(schema.actions).where(
            schema.actions.c.action_id == action_id,
            schema.actions.c.status == "committed",
            schema.actions.c.action_type == "record_discovery_failure",
        )).mappings().first()
        node_raw = uow.connection.execute(select(sd.discovery_nodes).where(
            sd.discovery_nodes.c.action_id == action_id,
        )).mappings().first()
        if action is None or node_raw is None:
            return None
        node = uow.discovery.node(node_raw["node_id"])
        run = uow.discovery.run(node.discovery_run_id)
        world = uow.discovery.world(node.world_id)
        if run is None or world is None or world.provenance_mode != "prospective_online":
            return None
        policy = uow.discovery.policy(run.policy_revision_id)
        deployments = uow.connection.execute(select(sd.policy_deployments).where(
            sd.policy_deployments.c.policy_family == policy.family,
            sd.policy_deployments.c.policy_revision_id == run.policy_revision_id,
        ).order_by(sd.policy_deployments.c.decided_at.desc())).mappings().all()
        selected = None
        for raw in deployments:
            candidate = uow.discovery.deployment(raw["policy_deployment_id"])
            if (candidate.decision in {"shadow", "canary", "deploy"}
                and uow.discovery.latest_deployment_for_scope(policy.family, candidate.scope)
                == candidate):
                selected = candidate
                break
        if selected is None or uow.discovery.latest_brake(selected.policy_deployment_id):
            return None
        chosen = next((code for code in selected.brake_conditions.get("conditions", ())
                       if code in node.diagnostic_codes), None)
        if chosen is None:
            return None
        evidence_hash = action["request_hash"]
        effective = boundary or datetime.fromisoformat(action["committed_at"]).isoformat()
        brake = PolicyBrakeEventRow(
            policy_brake_event_id=f"brake:{selected.policy_deployment_id}:{action_id}",
            policy_deployment_id=selected.policy_deployment_id,
            tripped_policy_revision_id=selected.policy_revision_id,
            restored_policy_revision_id=selected.rollback_policy_revision_id,
            condition_code=chosen,
            evidence={"action_id": action_id, "request_hash": evidence_hash,
                      "node_id": node.node_id},
            effective_boundary=effective,
            tripped_at=action["committed_at"], action_id="pending",
        )
    service = DiscoveryGovernanceActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    outcome = service.trip_brake(TripPolicyBrakeRequest(
        brake=brake, actor_id="sys:discovery-brake",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key=f"brake:{selected.policy_deployment_id}:{action_id}",
        requested_at=datetime.fromisoformat(action["committed_at"]),
    ))
    if outcome.status is not ActionStatus.COMMITTED:
        raise ValueError("committed diagnostic brake was not accepted")
    return outcome
