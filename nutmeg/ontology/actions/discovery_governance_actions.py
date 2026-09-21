"""Governed tournament facts and human-controlled discovery deployment events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import ArchiveDisposition, DeploymentDecision, canonical_hash
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository.discovery import (
    ArchiveDecisionRow,
    HoldoutExposureRow,
    PolicyBrakeEventRow,
    PolicyDeploymentRow,
    TournamentCandidateRow,
    TournamentCompletionRow,
    TournamentResultRow,
    TournamentRow,
    TournamentWorldRow,
)


@dataclass(frozen=True, slots=True)
class CreatePolicyTournamentRequest:
    tournament: TournamentRow
    candidates: tuple[TournamentCandidateRow, ...]
    worlds: tuple[TournamentWorldRow, ...]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class FinishPolicyTournamentRequest:
    tournament_id: str
    results: tuple[TournamentResultRow, ...]
    completion: TournamentCompletionRow
    archive_decisions: tuple[ArchiveDecisionRow, ...]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovePolicyDeploymentRequest:
    deployment: PolicyDeploymentRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class TripPolicyBrakeRequest:
    brake: PolicyBrakeEventRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class DiscoveryGovernanceActions:
    def __init__(self, action_service: ActionService) -> None:
        self._svc = action_service

    @staticmethod
    def _command(name: str, request, payload: dict) -> ActionCommand:
        return ActionCommand.create(
            action_type=name,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload=payload,
        )

    def create_tournament(self, request: CreatePolicyTournamentRequest) -> ActionOutcome:
        command = self._command(
            "create_policy_tournament",
            request,
            {
                "tournament": asdict(request.tournament),
                "candidates": [asdict(row) for row in request.candidates],
                "worlds": [asdict(row) for row in request.worlds],
            },
        )

        def handler(uow, cmd):
            tournament = request.tournament
            incumbents = [
                row
                for row in request.candidates
                if row.policy_revision_id == tournament.incumbent_policy_revision_id
                and row.candidate_role == "incumbent"
            ]
            if (
                len(incumbents) != 1
                or len({row.policy_revision_id for row in request.candidates})
                != len(request.candidates)
                or sum(row.candidate_role == "incumbent" for row in request.candidates) != 1
            ):
                raise ValueError("tournament requires exactly one incumbent candidate")
            if (
                canonical_hash([asdict(r) for r in request.candidates])
                != tournament.candidate_set_hash
            ):
                raise ValueError("candidate set hash mismatch")
            if (
                canonical_hash([asdict(r) for r in request.worlds])
                != tournament.world_pool_manifest_hash
            ):
                raise ValueError("world pool manifest hash mismatch")
            if not request.worlds or len({r.world_id for r in request.worlds}) != len(
                request.worlds
            ):
                raise ValueError("duplicate or empty tournament worlds")
            if tuple(r.candidate_index for r in request.candidates) != tuple(
                range(len(request.candidates))
            ):
                raise ValueError("candidate indexes must be contiguous")
            if tuple(r.world_index for r in request.worlds) != tuple(range(len(request.worlds))):
                raise ValueError("world indexes must be contiguous")
            contract = tournament.decision_contract
            if (
                contract.get("evaluator_revision") != tournament.evaluator_revision
                or contract.get("aggregation_revision") != tournament.aggregation_revision
                or not contract.get("lexicographic_tiers")
                or contract.get("tie_rule") != "incumbent"
                or not isinstance(contract.get("archive_rule"), dict)
                or "minimum_materiality" not in contract
            ):
                raise ValueError("tournament decision contract is incomplete")
            from nutmeg.discovery.contracts import load_pilot_contract

            pilot = load_pilot_contract(
                Path(__file__).resolve().parents[3]
                / "experiments/discovery/structural-candidate-v1.contract.json"
            )
            if (
                contract["lexicographic_tiers"] != list(pilot.evaluator.lexicographic_tiers)
                or contract["archive_rule"].get("capacity") != pilot.archive.capacity
                or contract["archive_rule"].get("max_per_lineage") != pilot.archive.max_per_lineage
                or tournament.evaluator_revision != pilot.evaluator.revision
            ):
                raise ValueError("tournament conflicts with frozen pilot evaluator or archive")
            for row in request.candidates:
                if row.policy_tournament_id != tournament.policy_tournament_id:
                    raise ValueError("candidate belongs to another tournament")
                policy = uow.discovery.policy(row.policy_revision_id)
                if policy is None or policy.family != tournament.policy_family:
                    raise ValueError("candidate policy family mismatch")
                if not policy.validation_result.get("valid"):
                    raise ValueError("tournament candidates must be validated policies")
            exposed = {
                row.world_id for row in uow.discovery.exposed_holdouts(tournament.policy_family)
            }
            for row in request.worlds:
                if row.policy_tournament_id != tournament.policy_tournament_id:
                    raise ValueError("world belongs to another tournament")
                world = uow.discovery.world(row.world_id)
                if world is None or uow.discovery.world_state(row.world_id) != "sealed":
                    raise ValueError("tournament requires sealed worlds")
                cutoff = datetime.fromisoformat(world.cutoff_at)
                development = datetime.fromisoformat(tournament.development_cutoff_at)
                holdout = datetime.fromisoformat(tournament.holdout_cutoff_at)
                if row.pool_role == "development" and cutoff > development:
                    raise ValueError("development world is later than cutoff")
                if row.pool_role == "holdout" and not (development < cutoff <= holdout):
                    raise ValueError("holdout world is outside frozen temporal window")
                if row.pool_role == "holdout" and row.world_id in exposed:
                    raise ValueError("exposed holdout cannot be reused as hidden holdout")
                if row.pool_role not in {"development", "holdout"}:
                    raise ValueError("unrecognized tournament world pool role")
                if world.evaluator_revision != tournament.evaluator_revision:
                    raise ValueError("world evaluator differs from tournament")
                if any(
                    world.task_family
                    not in uow.discovery.policy(
                        candidate.policy_revision_id
                    ).compatible_world_families
                    for candidate in request.candidates
                ):
                    raise ValueError("tournament world is incompatible with candidate policies")
            uow.discovery.insert_tournament(replace(tournament, action_id=cmd.action_id))
            for row in request.candidates:
                uow.discovery.insert_tournament_candidate(row)
            for row in request.worlds:
                uow.discovery.insert_tournament_world(row)
            return (ObjectRef("policy_tournament", tournament.policy_tournament_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    @staticmethod
    def selection_proof(
        tournament: TournamentRow, results: tuple[TournamentResultRow, ...], winner: str | None
    ) -> str:
        return canonical_hash(
            {
                "candidate_set_hash": tournament.candidate_set_hash,
                "world_pool_manifest_hash": tournament.world_pool_manifest_hash,
                "results": [asdict(row) for row in results],
                "winner": winner,
            }
        )

    @staticmethod
    def _lineage_roots(discovery, policy_id: str) -> set[str]:
        roots = set()
        pending = [policy_id]
        seen = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            parents = discovery.policy_parents(current)
            if parents:
                pending.extend(parents)
            else:
                roots.add(current)
        return roots

    @staticmethod
    def _active_archive_ids(uow, family: str) -> set[str]:
        archive = sd.policy_archive_decisions
        policies = sd.exploration_policy_revisions
        rows = uow.connection.execute(
            select(archive.c.policy_revision_id, archive.c.disposition)
            .join(policies, policies.c.policy_revision_id == archive.c.policy_revision_id)
            .where(policies.c.family == family)
            .order_by(archive.c.decided_at, archive.c.archive_decision_id)
        ).all()
        latest = dict(rows)
        return {
            policy_id
            for policy_id, disposition in latest.items()
            if disposition not in {"rejected", "retired"}
        }

    def finish_tournament(self, request: FinishPolicyTournamentRequest) -> ActionOutcome:
        command = self._command(
            "finish_policy_tournament",
            request,
            {
                "tournament_id": request.tournament_id,
                "results": [asdict(row) for row in request.results],
                "completion": asdict(request.completion),
                "archive": [asdict(row) for row in request.archive_decisions],
            },
        )

        def handler(uow, cmd):
            tournament = uow.discovery.tournament(request.tournament_id)
            if tournament is None or uow.discovery.tournament_completion(request.tournament_id):
                raise ValueError("tournament missing or already completed")
            candidates = uow.discovery.tournament_candidates(request.tournament_id)
            worlds = uow.discovery.tournament_worlds(request.tournament_id)
            expected = {(p.policy_revision_id, w.world_id) for p in candidates for w in worlds}
            actual = {(r.policy_revision_id, r.world_id) for r in request.results}
            if actual != expected or len(request.results) != len(expected):
                raise ValueError("tournament requires complete candidate/world matrix")
            if any(
                r.policy_tournament_id != request.tournament_id
                or (r.disqualified and not r.exclusion_reason)
                for r in request.results
            ):
                raise ValueError("tournament matrix has invalid exclusion or owner")
            winner = request.completion.winner_policy_revision_id
            if request.completion.policy_tournament_id != request.tournament_id:
                raise ValueError("completion belongs to another tournament")
            if winner not in {p.policy_revision_id for p in candidates} or any(
                r.disqualified for r in request.results if r.policy_revision_id == winner
            ):
                raise ValueError("winner must be a registered non-disqualified candidate")
            if request.completion.reproduction_hash != self.selection_proof(
                tournament, request.results, winner
            ):
                raise ValueError("selection proof reproduction hash mismatch")
            archive = tournament.decision_contract["archive_rule"]
            active_archive = self._active_archive_ids(uow, tournament.policy_family)
            bad_policies = {r.policy_revision_id for r in request.results if r.disqualified}
            admitted = set()
            for row in request.archive_decisions:
                disposition = ArchiveDisposition(row.disposition)
                if (
                    row.policy_tournament_id != request.tournament_id
                    or row.policy_revision_id not in {p.policy_revision_id for p in candidates}
                    or row.policy_revision_id in bad_policies
                ):
                    raise ValueError("disqualified or foreign policy cannot enter archive")
                if disposition is ArchiveDisposition.STEPPING_STONE and (
                    row.policy_revision_id == winner or not row.reason_code or not row.evidence
                ):
                    raise ValueError("archive stepping stone is not an evidence-backed nonwinner")
                if row.policy_revision_id in admitted:
                    raise ValueError("duplicate archive decision")
                admitted.add(row.policy_revision_id)
            all_admitted = active_archive | {
                row.policy_revision_id
                for row in request.archive_decisions
                if row.disposition not in {"rejected", "retired"}
            }
            if len(all_admitted) > archive["capacity"]:
                raise ValueError("archive capacity exceeded")
            for policy_id in all_admitted:
                roots = self._lineage_roots(uow.discovery, policy_id)
                if (
                    sum(
                        bool(roots & self._lineage_roots(uow.discovery, peer))
                        for peer in all_admitted
                    )
                    > archive["max_per_lineage"]
                ):
                    raise ValueError("archive per-lineage capacity exceeded")
            for row in request.results:
                uow.discovery.insert_tournament_result(row)
            uow.discovery.insert_tournament_completion(
                replace(request.completion, action_id=cmd.action_id)
            )
            for row in request.archive_decisions:
                uow.discovery.insert_archive_decision(replace(row, action_id=cmd.action_id))
            for row in worlds:
                if row.pool_role == "holdout":
                    uow.discovery.insert_holdout_exposure(
                        HoldoutExposureRow(
                            holdout_exposure_id=f"H-{uuid4().hex}",
                            policy_tournament_id=request.tournament_id,
                            world_id=row.world_id,
                            policy_family=tournament.policy_family,
                            exposed_at=cmd.requested_at,
                            action_id=cmd.action_id,
                        )
                    )
            return (ObjectRef("policy_tournament", request.tournament_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    @staticmethod
    def _latest_winning_tournament(uow, family: str):
        t = sd.policy_tournaments
        rows = uow.connection.execute(
            select(t.c.policy_tournament_id)
            .where(t.c.policy_family == family)
            .order_by(t.c.created_at.desc(), t.c.policy_tournament_id.desc())
        ).scalars()
        for tournament_id in rows:
            completion = uow.discovery.tournament_completion(tournament_id)
            if completion is not None:
                return uow.discovery.tournament(tournament_id), completion
        return None, None

    def approve_deployment(self, request: ApprovePolicyDeploymentRequest) -> ActionOutcome:
        command = self._command(
            "approve_policy_deployment",
            request,
            {
                "deployment": asdict(request.deployment),
            },
        )

        def handler(uow, cmd):
            deployment = request.deployment
            decision = DeploymentDecision(deployment.decision)
            if not deployment.human_actor_id or not deployment.acted_by or not deployment.reason:
                raise ValueError("deployment requires human identity and reason")
            policy = uow.discovery.policy(deployment.policy_revision_id)
            if policy is None or policy.family != deployment.policy_family:
                raise ValueError("deployment policy family mismatch")
            if deployment.rollback_policy_revision_id:
                fallback = uow.discovery.policy(deployment.rollback_policy_revision_id)
                if fallback is None or fallback.family != policy.family:
                    raise ValueError("rollback fallback must be registered in same family")
            tournament, completion = self._latest_winning_tournament(uow, policy.family)
            if decision in {
                DeploymentDecision.SHADOW,
                DeploymentDecision.CANARY,
                DeploymentDecision.DEPLOY,
            }:
                if (
                    completion is None
                    or completion.winner_policy_revision_id != policy.policy_revision_id
                ):
                    raise ValueError("deployment requires latest tournament winner")
            previous = uow.discovery.latest_deployment_for_scope(policy.family, deployment.scope)
            if deployment.supersedes_deployment_id and (
                previous is None
                or deployment.supersedes_deployment_id != previous.policy_deployment_id
            ):
                raise ValueError("deployment must supersede latest human event")
            if (
                decision is DeploymentDecision.DEPLOY
                and previous is not None
                and (
                    previous.decision == "deploy"
                    and previous.scope == deployment.scope
                    and uow.discovery.latest_brake(previous.policy_deployment_id) is None
                )
            ):
                raise ValueError("active deployed incumbent requires explicit supersession")
            if decision in {DeploymentDecision.CANARY, DeploymentDecision.DEPLOY}:
                prior_worlds = {
                    w.world_id
                    for w in uow.discovery.tournament_worlds(tournament.policy_tournament_id)
                }
                runs = sd.discovery_runs
                worlds = sd.discovery_worlds
                rows = uow.connection.execute(
                    select(worlds.c.world_id, worlds.c.cutoff_at)
                    .join(runs, runs.c.world_id == worlds.c.world_id)
                    .where(
                        runs.c.policy_revision_id == policy.policy_revision_id,
                        runs.c.environment_mode == "shadow",
                        worlds.c.provenance_mode == "prospective_online",
                    )
                ).all()
                if not any(
                    wid not in prior_worlds
                    and datetime.fromisoformat(cutoff)
                    > datetime.fromisoformat(tournament.holdout_cutoff_at)
                    and uow.discovery.world_state(wid) == "sealed"
                    for wid, cutoff in rows
                ):
                    raise ValueError("canary/deploy requires fresh prospective shadow worlds")
            if decision is DeploymentDecision.DEPLOY and not deployment.rollback_policy_revision_id:
                raise ValueError("deploy requires recorded rollback fallback")
            if decision in {DeploymentDecision.CANARY, DeploymentDecision.DEPLOY}:
                prior_approval = uow.connection.execute(
                    select(sd.policy_deployments.c.policy_deployment_id)
                    .where(
                        sd.policy_deployments.c.policy_family == policy.family,
                        sd.policy_deployments.c.scope_json == canonical_json(deployment.scope),
                        sd.policy_deployments.c.policy_revision_id
                        == deployment.rollback_policy_revision_id,
                        sd.policy_deployments.c.decision.in_(("shadow", "canary", "deploy")),
                    )
                    .limit(1)
                ).first()
                if (
                    deployment.rollback_policy_revision_id == deployment.policy_revision_id
                    or prior_approval is None
                ):
                    raise ValueError("canary/deploy requires a distinct human-approved fallback")
            uow.discovery.insert_deployment(replace(deployment, action_id=cmd.action_id))
            return (ObjectRef("policy_deployment", deployment.policy_deployment_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

    def trip_brake(self, request: TripPolicyBrakeRequest) -> ActionOutcome:
        command = self._command("trip_policy_brake", request, {"brake": asdict(request.brake)})

        def handler(uow, cmd):
            brake = request.brake
            table = sd.policy_deployments
            raw = (
                uow.connection.execute(
                    select(table).where(table.c.policy_deployment_id == brake.policy_deployment_id)
                )
                .mappings()
                .first()
            )
            if raw is None:
                raise ValueError("brake requires an active deployment")
            deployment = uow.discovery.latest_deployment_for_scope(
                raw["policy_family"], uow.discovery.deployment(brake.policy_deployment_id).scope
            )
            if deployment.policy_deployment_id != brake.policy_deployment_id or (
                deployment.decision not in {"shadow", "canary", "deploy"}
                or uow.discovery.latest_brake(brake.policy_deployment_id) is not None
            ):
                raise ValueError("brake requires an active unbraked deployment")
            if (
                brake.tripped_policy_revision_id != deployment.policy_revision_id
                or brake.restored_policy_revision_id != deployment.rollback_policy_revision_id
            ):
                raise ValueError("brake can only restore recorded approved fallback")
            if brake.condition_code not in deployment.brake_conditions.get("conditions", []):
                raise ValueError("brake condition is not in frozen contract")
            uow.discovery.insert_brake(replace(brake, action_id=cmd.action_id))
            return (ObjectRef("policy_brake_event", brake.policy_brake_event_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)
