"""Read-only operational projections from durable discovery facts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from sqlalchemy import Engine, select

from nutmeg.ontology.discovery.models import DiscoveryStatus, canonical_hash
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository import schema_discovery_promotion as sp
from nutmeg.ontology.repository.discovery import DiscoveryRepository


class DiscoveryReadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def promotion(self, policy_family: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            repo = DiscoveryRepository(connection)
            tournament_ids = connection.execute(
                select(sd.policy_tournaments.c.policy_tournament_id)
                .where(sd.policy_tournaments.c.policy_family == policy_family)
                .order_by(sd.policy_tournaments.c.created_at.desc())
            ).scalars()
            tournament_id = next(
                (tid for tid in tournament_ids if repo.tournament_completion(tid)), None
            )
            completion = repo.tournament_completion(tournament_id) if tournament_id else None
            window_ids = connection.execute(
                select(sp.policy_shadow_windows.c.policy_shadow_window_id)
                .where(sp.policy_shadow_windows.c.policy_family == policy_family)
                .order_by(sp.policy_shadow_windows.c.created_at.desc())
            ).scalars()
            windows = [asdict(repo.shadow_window(wid)) for wid in window_ids]
            deployment = repo.latest_deployment(policy_family)
            brake = repo.latest_brake(deployment.policy_deployment_id) if deployment else None
            return {
                "latest_tournament_id": tournament_id,
                "replay_winner": completion.winner_policy_revision_id if completion else None,
                "incumbent": brake.restored_policy_revision_id
                if brake
                else (
                    deployment.policy_revision_id
                    if deployment and deployment.decision in {"canary", "deploy"}
                    else None
                ),
                "shadow_windows": windows,
                "deployment": asdict(deployment) if deployment else None,
                "brake": asdict(brake) if brake else None,
                "pending_human_disposition": brake is not None,
                "control_available": False,
            }

    def readiness(self):
        from nutmeg.discovery.contracts import load_pilot_contract
        from nutmeg.discovery.readiness import CoverageWorld, ReplayMetrics, assess_readiness
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
            completed_replays = 0
            requested_actions = 0
            rejected_actions = 0
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
                replay_runs = connection.execute(
                    select(sd.policy_replay_runs.c.policy_replay_run_id)
                    .where(
                        sd.policy_replay_runs.c.world_id == world_id,
                        sd.policy_replay_runs.c.policy_revision_id == "structural-baseline-v1",
                    )
                    .order_by(sd.policy_replay_runs.c.policy_replay_run_id)
                ).scalars()
                for replay_id in replay_runs:
                    replay = repository.policy_replay(replay_id)
                    completion = repository.policy_replay_completion(replay_id)
                    rounds = repository.policy_replay_rounds(replay_id)
                    if not completion or not rounds:
                        continue
                    from nutmeg.ontology.actions.discovery_policy_actions import (
                        DiscoveryPolicyActions,
                    )

                    if completion.trace_hash != canonical_hash(
                        DiscoveryPolicyActions.trace_document(
                            replay, rounds, completion, source_seal_hash=events[-1].manifest_hash
                        )
                    ):
                        continue
                    completed_replays += 1
                    requested_actions += sum(len(item.requested_actions) for item in rounds)
                    rejected_actions += sum(len(item.rejected_actions) for item in rounds)
                    break
        replay_metrics = None
        if worlds and completed_replays == len(worlds):
            replay_metrics = ReplayMetrics(
                integrity_proven=True,
                action_overlap=(requested_actions - rejected_actions) / requested_actions
                if requested_actions
                else None,
                branch_unavailable_rate=rejected_actions / requested_actions
                if requested_actions
                else None,
            )
        return assess_readiness(tuple(worlds), pilot.readiness, replay_metrics)

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
                if deployment and deployment.decision in {"canary", "deploy"}
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
                "source_generation_round": (
                    asdict(round_row)
                    if (round_id := policy.generator_descriptors.get("generation_round_id"))
                    and (round_row := repository.generation_round(round_id))
                    else None
                ),
                "archive_disposition": archive.disposition if archive else None,
                "tournament_winner": winner,
                "deployment_state": (
                    deployment.decision
                    if deployment and deployment.policy_revision_id == policy_revision_id
                    else None
                ),
            }

    def generation_detail(self, generation_round_id: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            row = DiscoveryRepository(connection).generation_round(generation_round_id)
            if row is None:
                raise KeyError(generation_round_id)
            return asdict(row)

    def tournament_detail(self, policy_tournament_id: str) -> dict[str, object]:
        with self._engine.connect() as connection:
            repository = DiscoveryRepository(connection)
            tournament = repository.tournament(policy_tournament_id)
            if tournament is None:
                raise KeyError(policy_tournament_id)
            completion = repository.tournament_completion(policy_tournament_id)
            worlds = repository.tournament_worlds(policy_tournament_id)
            results = repository.tournament_results(policy_tournament_id)
            selection = None
            stratum_summary = {}
            worst_stratum = None
            if completion:
                from nutmeg.discovery.tournament_selector import (
                    SelectionCell,
                    select_winner,
                    summarize_strata,
                )
                from nutmeg.ontology.actions.discovery_governance_actions import (
                    DiscoveryGovernanceActions,
                )

                contract = DiscoveryGovernanceActions._approved_selection_contract()
                roles = {row.world_id: row for row in worlds}
                cells = tuple(
                    SelectionCell(
                        policy_revision_id=row.policy_revision_id,
                        world_id=row.world_id,
                        pool_role=roles[row.world_id].pool_role,
                        strata=tuple(roles[row.world_id].stratum_labels["labels"]),
                        score_vector=row.score_vector,
                        disqualified=row.disqualified,
                        exclusion_reason=row.exclusion_reason,
                        trace_hash=row.trace_hash,
                    )
                    for row in results
                )
                selection = select_winner(
                    contract,
                    tournament.incumbent_policy_revision_id,
                    tuple(
                        row.policy_revision_id
                        for row in repository.tournament_candidates(policy_tournament_id)
                    ),
                    cells,
                )
                stratum_summary = summarize_strata(contract, cells)
                worst_stratum = {
                    "labels": list(contract.worst_stratum.strata),
                    "max_decline": str(contract.worst_stratum.max_decline),
                }
            holdout_dates = sorted(
                repository.world(row.world_id).business_date
                for row in worlds
                if row.pool_role == "holdout"
            )
            return {
                "tournament": asdict(tournament),
                "candidates": [
                    asdict(row) for row in repository.tournament_candidates(policy_tournament_id)
                ],
                "worlds": [asdict(row) for row in worlds],
                "results": [asdict(row) for row in results],
                "completion": asdict(completion) if completion else None,
                "holdout_period": {"from": holdout_dates[0], "through": holdout_dates[-1]}
                if holdout_dates
                else None,
                "comparison_reasons": selection.comparison_reasons if selection else {},
                "worst_stratum": worst_stratum,
                "stratum_summary": stratum_summary,
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
