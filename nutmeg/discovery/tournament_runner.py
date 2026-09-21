"""Prepare a frozen D4 matrix from existing replay facts and finish via governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select

from nutmeg.discovery.sealed_tree import SealedTree
from nutmeg.discovery.tournament_scores import score_sealed_replay
from nutmeg.discovery.tournament_selector import SelectionCell, select_winner
from nutmeg.ontology.actions.discovery_governance_actions import (
    DiscoveryGovernanceActions,
    FinishPolicyTournamentRequest,
)
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository.discovery import TournamentCompletionRow, TournamentResultRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


@dataclass(frozen=True, slots=True)
class PreparedTournament:
    results: tuple[TournamentResultRow, ...]
    winner_policy_revision_id: str
    proof_hash: str
    disqualification_reasons: dict[str, str]


def prepare_tournament(engine: Engine, tournament_id: str) -> PreparedTournament:
    """No tournament creation or holdout exposure occurs while preparing scores."""
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.discovery
        tournament = repo.tournament(tournament_id)
        if tournament is None or repo.tournament_completion(tournament_id) is not None:
            raise ValueError("tournament must be frozen and unfinished")
        candidates = repo.tournament_candidates(tournament_id)
        worlds = repo.tournament_worlds(tournament_id)
        if not candidates or not worlds:
            raise ValueError("frozen tournament has no candidate/world matrix")
        results = []
        selection_cells = []
        for world_row in worlds:
            world = repo.world(world_row.world_id)
            nodes = repo.nodes_for_world(world_row.world_id)
            tree = SealedTree.from_rows(
                world,
                nodes,
                repo.world_events(world_row.world_id),
                {
                    node.node_id: evaluation
                    for node in nodes
                    if (evaluation := repo.latest_node_evaluation(node.node_id)) is not None
                },
            )
            for candidate in candidates:
                replay_ids = (
                    uow.connection.execute(
                        select(sd.policy_replay_runs.c.policy_replay_run_id)
                        .join(
                            sd.policy_replay_completions,
                            sd.policy_replay_completions.c.policy_replay_run_id
                            == sd.policy_replay_runs.c.policy_replay_run_id,
                        )
                        .where(
                            sd.policy_replay_runs.c.world_id == world_row.world_id,
                            sd.policy_replay_runs.c.policy_revision_id
                            == candidate.policy_revision_id,
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(replay_ids) != 1:
                    raise ValueError("tournament requires exactly one frozen replay per cell")
                replay_id = replay_ids[0]
                completion = repo.policy_replay_completion(replay_id)
                score = score_sealed_replay(tree, repo.policy_replay_rounds(replay_id), completion)
                result = TournamentResultRow(
                    policy_tournament_id=tournament_id,
                    policy_revision_id=candidate.policy_revision_id,
                    world_id=world_row.world_id,
                    score_vector=score.score_vector,
                    disqualified=score.disqualified,
                    exclusion_reason=score.exclusion_reason,
                    trace_hash=completion.trace_hash,
                )
                results.append(result)
                selection_cells.append(
                    SelectionCell(
                        policy_revision_id=result.policy_revision_id,
                        world_id=result.world_id,
                        pool_role=world_row.pool_role,
                        strata=tuple(world_row.stratum_labels["labels"]),
                        score_vector=result.score_vector,
                        disqualified=result.disqualified,
                        exclusion_reason=result.exclusion_reason,
                        trace_hash=result.trace_hash,
                    )
                )
        selection = select_winner(
            DiscoveryGovernanceActions._approved_selection_contract(),
            tournament.incumbent_policy_revision_id,
            tuple(row.policy_revision_id for row in candidates),
            tuple(selection_cells),
        )
        ordered = tuple(sorted(results, key=lambda row: (row.policy_revision_id, row.world_id)))
        proof = DiscoveryGovernanceActions.selection_proof(
            tournament, ordered, selection.winner_policy_revision_id
        )
        return PreparedTournament(
            ordered,
            selection.winner_policy_revision_id,
            proof,
            selection.disqualification_reasons,
        )


def finish_frozen_tournament(engine: Engine, tournament_id: str, *, requested_at: datetime):
    prepared = prepare_tournament(engine, tournament_id)
    actions = DiscoveryGovernanceActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    return actions.finish_tournament(
        FinishPolicyTournamentRequest(
            tournament_id=tournament_id,
            results=prepared.results,
            completion=TournamentCompletionRow(
                policy_tournament_id=tournament_id,
                winner_policy_revision_id=prepared.winner_policy_revision_id,
                tie_policy_revision_ids=[],
                disqualification_reasons=prepared.disqualification_reasons,
                reproduction_hash=prepared.proof_hash,
                finished_at=requested_at.isoformat(),
                action_id="pending",
            ),
            archive_decisions=(),
            actor_id="sys:structural-tournament",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"{tournament_id}:finish:{prepared.proof_hash}",
            requested_at=requested_at,
        )
    )
