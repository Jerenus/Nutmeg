"""Read-only operational projections from durable discovery facts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from sqlalchemy import Engine, select

from nutmeg.ontology.discovery.models import DiscoveryStatus, canonical_hash
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository.discovery import DiscoveryRepository


class DiscoveryReadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def readiness(self):
        from nutmeg.discovery.contracts import load_pilot_contract
        from nutmeg.discovery.readiness import CoverageWorld, assess_readiness
        from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions

        pilot = load_pilot_contract(
            Path(__file__).resolve().parents[3]
            / "experiments/discovery/structural-candidate-v1.contract.json"
        )
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            ids = connection.execute(
                select(sd.discovery_worlds.c.world_id).where(
                    sd.discovery_worlds.c.task_family == pilot.task_family,
                    sd.discovery_worlds.c.provenance_mode == "prospective_online",
                )
            ).scalars()
            worlds = []
            for world_id in ids:
                if repository.world_state(world_id) != "sealed":
                    continue
                world = repository.world(world_id)
                nodes = repository.nodes_for_world(world_id)
                events = repository.world_events(world_id)
                manifest = world.input_manifest
                complete = (
                    bool(events)
                    and events[-1].manifest_hash
                    == DiscoveryWorldActions.seal_manifest(world, nodes)
                    and world.input_manifest_hash == canonical_hash(manifest)
                    and bool(manifest.get("task_snapshot_hash"))
                    and bool(manifest.get("slate_revision_id"))
                )
                worlds.append(
                    CoverageWorld(
                        world_id=world_id,
                        business_date=world.business_date,
                        task_snapshot_hash=str(manifest.get("task_snapshot_hash") or ""),
                        slate_revision_id=str(manifest.get("slate_revision_id") or ""),
                        strata=tuple(
                            sorted(f"{key}:{value}" for key, value in world.strata.items())
                        ),
                        sealed=True,
                        manifest_complete=complete,
                        alternative_count=sum(
                            node.continuation_action is not None
                            and node.continuation_action.get("operator")
                            == "enumerate_template_shard"
                            for node in nodes[1:]
                        ),
                        failed_or_degraded=any(
                            node.execution_status == "failed" or bool(node.diagnostic_codes)
                            for node in nodes[1:]
                        ),
                    )
                )
        return assess_readiness(tuple(worlds), pilot.readiness)

    def status(self, policy_family: str) -> DiscoveryStatus:
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            deployment = repository.latest_deployment(policy_family)
            table = sd.policy_tournaments
            tournament_ids = connection.execute(
                select(table.c.policy_tournament_id)
                .where(table.c.policy_family == policy_family)
                .order_by(table.c.created_at.desc(), table.c.policy_tournament_id.desc())
            ).scalars()
            latest_tournament = next(
                (
                    tournament_id
                    for tournament_id in tournament_ids
                    if repository.tournament_completion(tournament_id)
                ),
                None,
            )
            policies = sd.exploration_policy_revisions
            policy_ids = (
                connection.execute(
                    select(policies.c.policy_revision_id).where(policies.c.family == policy_family)
                )
                .scalars()
                .all()
            )
            task_families = {
                task_family
                for policy_id in policy_ids
                for task_family in repository.policy(policy_id).compatible_world_families
            }
            worlds = sd.discovery_worlds
            latest_world = connection.execute(
                select(worlds.c.world_id)
                .where(worlds.c.task_family.in_(task_families))
                .order_by(worlds.c.created_at.desc(), worlds.c.world_id.desc())
                .limit(1)
            ).scalar_one_or_none()
            sealed_count = sum(repository.count_sealed_worlds(family) for family in task_families)
            brake = repository.latest_brake(deployment.policy_deployment_id) if deployment else None
            active_state = "braked" if brake else deployment.decision if deployment else None
            incumbent = (
                brake.restored_policy_revision_id
                if brake
                else deployment.policy_revision_id
                if deployment and deployment.decision in {"shadow", "canary", "deploy"}
                else None
            )
            return DiscoveryStatus(
                incumbent_policy_revision_id=incumbent,
                active_deployment_state=active_state,
                latest_tournament_id=latest_tournament,
                latest_world_id=latest_world,
                sealed_world_count=sealed_count,
                exposed_holdout_count=len(repository.exposed_holdouts(policy_family)),
                rollback_policy_revision_id=deployment.rollback_policy_revision_id
                if deployment
                else None,
            )

    def world_detail(self, world_id: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            world = repository.world(world_id)
            if world is None:
                raise KeyError(world_id)
            nodes = sorted(
                repository.nodes_for_world(world_id),
                key=lambda row: (
                    row.visibility_sequence is None,
                    row.visibility_sequence or 0,
                    row.node_id,
                ),
            )
            return {
                "world": asdict(world),
                "state": repository.world_state(world_id),
                "events": [asdict(row) for row in repository.world_events(world_id)],
                "nodes": [asdict(row) for row in nodes],
                "evaluations": [
                    asdict(result)
                    for node in nodes
                    if (result := repository.latest_node_evaluation(node.node_id))
                ],
            }

    def policy_lineage(self, policy_revision_id: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            policy = repository.policy(policy_revision_id)
            if policy is None:
                raise KeyError(policy_revision_id)
            archive = repository.latest_archive_decision(policy_revision_id)
            deployment = repository.latest_deployment(policy.family)
            completion = sd.policy_tournament_completions
            winner = (
                connection.execute(
                    select(completion.c.policy_tournament_id)
                    .where(completion.c.winner_policy_revision_id == policy_revision_id)
                    .limit(1)
                ).first()
                is not None
            )
            return {
                "policy": asdict(policy),
                "generator_family": policy.generator_family,
                "generator_revision": policy.generator_revision,
                "parents": list(repository.policy_parents(policy_revision_id)),
                "archive_disposition": archive.disposition if archive else None,
                "tournament_winner": winner,
                "deployment_state": (
                    deployment.decision
                    if deployment and deployment.policy_revision_id == policy_revision_id
                    else None
                ),
            }

    def tournament_detail(self, policy_tournament_id: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            tournament = repository.tournament(policy_tournament_id)
            if tournament is None:
                raise KeyError(policy_tournament_id)
            completion = repository.tournament_completion(policy_tournament_id)
            return {
                "tournament": asdict(tournament),
                "candidates": [
                    asdict(row) for row in repository.tournament_candidates(policy_tournament_id)
                ],
                "worlds": [
                    asdict(row) for row in repository.tournament_worlds(policy_tournament_id)
                ],
                "results": [
                    asdict(row) for row in repository.tournament_results(policy_tournament_id)
                ],
                "completion": asdict(completion) if completion else None,
                "selection_contract_hash": tournament.decision_contract.get(
                    "selection_contract_hash"
                ),
                "exposed_holdout_world_ids": sorted(
                    row.world_id
                    for row in repository.exposed_holdouts(tournament.policy_family)
                    if row.policy_tournament_id == policy_tournament_id
                ),
                "archive_decisions": [
                    asdict(row)
                    for row in repository.archive_decisions_for_tournament(policy_tournament_id)
                ],
            }
