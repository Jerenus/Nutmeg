"""Governed tournament facts and human-controlled discovery deployment events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
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
    PolicyShadowWindowRow,
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
    reviewed_scope_hash: str | None = None
    scope_approval_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PreregisterPolicyShadowWindowRequest:
    window: PolicyShadowWindowRow
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovePilotScopeRequest:
    contract: dict
    reviewed_hash: str
    approval_ref: str
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

    @staticmethod
    def _approved_selection_contract():
        from nutmeg.discovery.contracts import load_pilot_contract
        from nutmeg.discovery.selection_contract import load_selection_contract

        root = Path(__file__).resolve().parents[3] / "experiments/discovery"
        pilot = load_pilot_contract(root / "structural-candidate-v1.contract.json")
        return load_selection_contract(root / "structural-selection-v1.contract.json", pilot)

    def approve_pilot_scope(self, request: ApprovePilotScopeRequest) -> ActionOutcome:
        command = self._command("approve_pilot_scope_contract", request, {
            "contract": request.contract, "reviewed_hash": request.reviewed_hash,
            "approval_ref": request.approval_ref,
        })

        def handler(uow, cmd):
            from nutmeg.discovery.pilot_scope import validate_control_scope

            scope = request.contract.get("scope", {})
            contract = validate_control_scope(
                scope, request.contract, reviewed_hash=request.reviewed_hash,
                approval_ref=request.approval_ref,
            )
            if not request.actor_id.startswith("op:"):
                raise ValueError("scope approval requires identified human operator")
            uow.discovery.insert_scope_review({
                "scope_contract_hash": request.reviewed_hash,
                "contract_json": canonical_json(contract.model_dump(mode="json")),
                "approval_ref": request.approval_ref,
                "human_actor_id": request.actor_id,
                "approved_at": cmd.requested_at,
                "action_id": cmd.action_id,
            })
            return (ObjectRef("policy_scope_review", request.reviewed_hash),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

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
            from nutmeg.discovery.contracts import canonical_hash as contract_hash

            selection = self._approved_selection_contract()
            if (
                contract.get("selection_contract_hash") != contract_hash(selection)
                or tournament.aggregation_revision != selection.aggregation_revision
                or tournament.evaluator_revision != selection.evaluator_revision
            ):
                raise ValueError("tournament selection contract hash or revision is unapproved")
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

            def cluster_key(world):
                key = (
                    world.business_date,
                    world.input_manifest.get("task_snapshot_hash"),
                    world.input_manifest.get("slate_revision_id"),
                )
                if not all(key):
                    raise ValueError("tournament world is missing derivative cluster identity")
                return key

            exposed_clusters = {cluster_key(uow.discovery.world(world_id)) for world_id in exposed}
            from nutmeg.discovery.sealed_tree import SealedTree
            from nutmeg.discovery.world_pool import (
                WorldPoolInput,
                WorldReadinessFacts,
                assess_baseline_readiness,
                freeze_world_pool,
            )

            replays = sd.policy_replay_runs
            seen_clusters = set()
            pool_inputs = []
            readiness_facts = []
            for row in request.worlds:
                if row.policy_tournament_id != tournament.policy_tournament_id:
                    raise ValueError("world belongs to another tournament")
                world = uow.discovery.world(row.world_id)
                if world is None or uow.discovery.world_state(row.world_id) != "sealed":
                    raise ValueError("tournament requires sealed worlds")
                expected_labels = sorted(f"{key}:{value}" for key, value in world.strata.items())
                if row.stratum_labels != {"labels": expected_labels}:
                    raise ValueError("tournament stratum labels differ from sealed world")
                cluster = cluster_key(world)
                if cluster in seen_clusters:
                    raise ValueError("duplicate derivative cluster in tournament world pool")
                seen_clusters.add(cluster)
                cutoff = datetime.fromisoformat(world.cutoff_at)
                development = datetime.fromisoformat(tournament.development_cutoff_at)
                holdout = datetime.fromisoformat(tournament.holdout_cutoff_at)
                if row.pool_role == "development" and cutoff > development:
                    raise ValueError("development world is later than cutoff")
                if row.pool_role == "holdout" and not (development < cutoff <= holdout):
                    raise ValueError("holdout world is outside frozen temporal window")
                if row.pool_role == "holdout" and row.world_id in exposed:
                    raise ValueError("exposed holdout cannot be reused as hidden holdout")
                if row.pool_role == "holdout" and cluster in exposed_clusters:
                    raise ValueError("exposed holdout cluster cannot be reused as hidden holdout")
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
                nodes = uow.discovery.nodes_for_world(row.world_id)
                SealedTree.from_rows(
                    world,
                    nodes,
                    uow.discovery.world_events(row.world_id),
                    {
                        node.node_id: evaluation
                        for node in nodes
                        if (evaluation := uow.discovery.latest_node_evaluation(node.node_id))
                        is not None
                    },
                )
                continuations = {
                    canonical_json(node.continuation_action)
                    for node in nodes
                    if node.parent_node_id == world.root_node_id
                    and node.continuation_action.get("operator") != "stop"
                }
                replay_ids = (
                    uow.connection.execute(
                        select(replays.c.policy_replay_run_id)
                        .join(
                            sd.policy_replay_completions,
                            sd.policy_replay_completions.c.policy_replay_run_id
                            == replays.c.policy_replay_run_id,
                        )
                        .where(
                            replays.c.world_id == world.world_id,
                            replays.c.policy_revision_id == tournament.incumbent_policy_revision_id,
                        )
                    )
                    .scalars()
                    .all()
                )
                requested = 0
                unavailable = 0
                for replay_id in replay_ids:
                    for replay_round in uow.discovery.policy_replay_rounds(replay_id):
                        requested += len(replay_round.requested_actions)
                        unavailable += sum(
                            item.get("reason") == "branch_unavailable"
                            for item in replay_round.rejected_actions
                        )
                pool_inputs.append(
                    WorldPoolInput(
                        world_id=world.world_id,
                        business_date=world.business_date,
                        cutoff_at=world.cutoff_at,
                        task_snapshot_hash=cluster[1],
                        slate_revision_id=cluster[2],
                        task_family=world.task_family,
                        evaluator_revision=world.evaluator_revision,
                        strata=tuple(f"{key}:{value}" for key, value in world.strata.items()),
                        sealed=True,
                        manifest_valid=True,
                        failed_or_no_solution=any(
                            node.execution_status in {"failed", "no_solution"} for node in nodes
                        ),
                    )
                )
                readiness_facts.append(
                    WorldReadinessFacts(
                        world_id=world.world_id,
                        distinct_legal_continuations=len(continuations),
                        incumbent_replay_available=bool(replay_ids),
                        requested_continuations=requested,
                        unavailable_continuations=unavailable,
                    )
                )
            try:
                pool = freeze_world_pool(
                    tuple(pool_inputs),
                    development_cutoff=tournament.development_cutoff_at,
                    holdout_cutoff=tournament.holdout_cutoff_at,
                    required_strata=pilot.readiness.required_strata,
                    exposed_cluster_keys=tuple(exposed_clusters),
                )
                readiness = assess_baseline_readiness(pool, tuple(readiness_facts), pilot)
            except ValueError as exc:
                raise ValueError(f"baseline readiness world pool rejected: {exc}") from exc
            if not readiness.ready:
                raise ValueError(f"baseline readiness failed: {', '.join(readiness.reasons)}")
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
                "selection_contract_hash": tournament.decision_contract.get(
                    "selection_contract_hash"
                ),
                "results": [
                    asdict(row)
                    for row in sorted(
                        results, key=lambda item: (item.policy_revision_id, item.world_id)
                    )
                ],
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

    @staticmethod
    def _action_jaccard_distance(left: object, right: object) -> Decimal | None:
        if not isinstance(left, list) or not isinstance(right, list):
            return None
        if (
            not left
            or not right
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (*left, *right)
            )
        ):
            raise ValueError("archive action histogram must be nonnegative counts")
        size = max(len(left), len(right))
        a = left + [0] * (size - len(left))
        b = right + [0] * (size - len(right))
        union = sum(max(x, y) for x, y in zip(a, b, strict=True))
        if not union:
            raise ValueError("archive action histogram must contain observed actions")
        return Decimal(1) - Decimal(sum(min(x, y) for x, y in zip(a, b, strict=True))) / Decimal(
            union
        )

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
            replays = sd.policy_replay_runs
            completions = sd.policy_replay_completions
            from nutmeg.discovery.sealed_tree import SealedTree
            from nutmeg.discovery.tournament_scores import score_sealed_replay

            trees = {}
            for row in request.results:
                matched = (
                    uow.connection.execute(
                        select(replays.c.policy_replay_run_id)
                        .join(
                            completions,
                            completions.c.policy_replay_run_id == replays.c.policy_replay_run_id,
                        )
                        .where(
                            replays.c.policy_revision_id == row.policy_revision_id,
                            replays.c.world_id == row.world_id,
                            completions.c.trace_hash == row.trace_hash,
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(matched) != 1:
                    raise ValueError("tournament result needs exactly one persisted replay trace")
                if row.world_id not in trees:
                    world = uow.discovery.world(row.world_id)
                    nodes = uow.discovery.nodes_for_world(row.world_id)
                    trees[row.world_id] = SealedTree.from_rows(
                        world,
                        nodes,
                        uow.discovery.world_events(row.world_id),
                        {
                            node.node_id: evaluation
                            for node in nodes
                            if (evaluation := uow.discovery.latest_node_evaluation(node.node_id))
                            is not None
                        },
                    )
                replay_id = matched[0]
                score = score_sealed_replay(
                    trees[row.world_id],
                    uow.discovery.policy_replay_rounds(replay_id),
                    uow.discovery.policy_replay_completion(replay_id),
                )
                if (
                    score.score_vector != row.score_vector
                    or score.disqualified != row.disqualified
                    or score.exclusion_reason != row.exclusion_reason
                ):
                    raise ValueError("tournament score differs from persisted replay evidence")
            winner = request.completion.winner_policy_revision_id
            if request.completion.policy_tournament_id != request.tournament_id:
                raise ValueError("completion belongs to another tournament")
            if winner not in {p.policy_revision_id for p in candidates} or any(
                r.disqualified for r in request.results if r.policy_revision_id == winner
            ):
                raise ValueError("winner must be a registered non-disqualified candidate")
            from nutmeg.discovery.tournament_selector import SelectionCell, select_winner

            roles = {row.world_id: row for row in worlds}
            selection = select_winner(
                self._approved_selection_contract(),
                tournament.incumbent_policy_revision_id,
                tuple(row.policy_revision_id for row in candidates),
                tuple(
                    SelectionCell(
                        policy_revision_id=row.policy_revision_id,
                        world_id=row.world_id,
                        pool_role=roles[row.world_id].pool_role,
                        strata=tuple(roles[row.world_id].stratum_labels.get("labels", ())),
                        score_vector=row.score_vector,
                        disqualified=row.disqualified,
                        exclusion_reason=row.exclusion_reason,
                        trace_hash=row.trace_hash,
                    )
                    for row in request.results
                ),
            )
            if winner != selection.winner_policy_revision_id:
                raise ValueError("selection derived winner differs from supplied completion")
            if request.completion.reproduction_hash != self.selection_proof(
                tournament, request.results, winner
            ):
                raise ValueError("selection proof reproduction hash mismatch")
            archive = tournament.decision_contract["archive_rule"]
            from nutmeg.discovery.contracts import load_pilot_contract

            pilot = load_pilot_contract(
                Path(__file__).resolve().parents[3]
                / "experiments/discovery/structural-candidate-v1.contract.json"
            )
            active_archive = self._active_archive_ids(uow, tournament.policy_family)
            bad_policies = {r.policy_revision_id for r in request.results if r.disqualified}
            admitted = set()
            retirements = []
            for row in request.archive_decisions:
                disposition = ArchiveDisposition(row.disposition)
                candidate_ids = {p.policy_revision_id for p in candidates}
                if row.policy_tournament_id != request.tournament_id or (
                    disposition is not ArchiveDisposition.RETIRED
                    and (
                        row.policy_revision_id not in candidate_ids
                        or row.policy_revision_id in bad_policies
                    )
                ):
                    raise ValueError("disqualified or foreign policy cannot enter archive")
                if disposition is ArchiveDisposition.RETIRED:
                    retirements.append(row)
                if disposition is ArchiveDisposition.STEPPING_STONE and (
                    row.policy_revision_id == winner or not row.reason_code or not row.evidence
                ):
                    raise ValueError("archive stepping stone is not an evidence-backed nonwinner")
                if disposition is ArchiveDisposition.STEPPING_STONE and (
                    row.reason_code not in pilot.archive.admission_reasons
                    or not set(row.diversity_descriptors) & set(pilot.archive.diversity_descriptors)
                ):
                    raise ValueError("archive reason or diversity descriptor is not approved")
                if disposition is ArchiveDisposition.STEPPING_STONE:
                    for existing_id in active_archive:
                        existing = uow.discovery.latest_archive_decision(existing_id)
                        if existing is not None and (
                            existing.diversity_descriptors == row.diversity_descriptors
                        ):
                            raise ValueError("archive rejects dominated behavioral clone")
                        if existing is not None:
                            distance = self._action_jaccard_distance(
                                row.diversity_descriptors.get("action_histogram"),
                                existing.diversity_descriptors.get("action_histogram"),
                            )
                            if distance is not None and distance < Decimal(
                                str(pilot.archive.minimum_action_jaccard_distance)
                            ):
                                raise ValueError("archive action Jaccard diversity below minimum")
                if row.policy_revision_id in admitted:
                    raise ValueError("duplicate archive decision")
                admitted.add(row.policy_revision_id)
            new_admissions = {
                row.policy_revision_id
                for row in request.archive_decisions
                if row.disposition not in {"rejected", "retired"}
            }
            if retirements:
                required_retirements = max(
                    0, len(active_archive | new_admissions) - archive["capacity"]
                )
                if len(retirements) != required_retirements:
                    raise ValueError("archive may retire exactly the members needed for capacity")
                archive_rows = sd.policy_archive_decisions
                policies = sd.exploration_policy_revisions
                ordered = (
                    uow.connection.execute(
                        select(archive_rows.c.policy_revision_id)
                        .join(
                            policies,
                            policies.c.policy_revision_id == archive_rows.c.policy_revision_id,
                        )
                        .where(policies.c.family == tournament.policy_family)
                        .order_by(archive_rows.c.decided_at, archive_rows.c.archive_decision_id)
                    )
                    .scalars()
                    .all()
                )
                if len(active_archive) < archive["capacity"] or not new_admissions:
                    raise ValueError("archive retirement requires a full archive and new admission")
                remaining = active_archive.copy()
                for row in retirements:
                    duplicate_id = row.evidence.get("duplicate_of")
                    existing = uow.discovery.latest_archive_decision(row.policy_revision_id)
                    duplicate = (
                        uow.discovery.latest_archive_decision(duplicate_id)
                        if duplicate_id
                        else None
                    )
                    clones = [
                        policy_id
                        for policy_id in ordered
                        if policy_id in remaining
                        and (other := uow.discovery.latest_archive_decision(policy_id)) is not None
                        and existing is not None
                        and other.diversity_descriptors == existing.diversity_descriptors
                    ]
                    if (
                        row.policy_revision_id not in remaining
                        or row.policy_revision_id in candidate_ids
                        or row.reason_code != "dominated_clone"
                        or duplicate_id == row.policy_revision_id
                        or duplicate_id not in remaining
                        or duplicate is None
                        or existing is None
                        or duplicate.diversity_descriptors != existing.diversity_descriptors
                        or not clones
                        or row.policy_revision_id != clones[0]
                    ):
                        raise ValueError("archive retirement must evict oldest dominated clone")
                    remaining.remove(row.policy_revision_id)
                active_archive = remaining
            all_admitted = active_archive | new_admissions
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

    def preregister_shadow_window(
        self, request: PreregisterPolicyShadowWindowRequest
    ) -> ActionOutcome:
        command = self._command(
            "preregister_policy_shadow_window", request, {"window": asdict(request.window)}
        )

        def handler(uow, cmd):
            window = request.window
            tournament, completion = self._latest_winning_tournament(uow, window.policy_family)
            if (
                tournament is None
                or completion.winner_policy_revision_id != window.policy_revision_id
                or tournament.policy_tournament_id != window.policy_tournament_id
            ):
                raise ValueError("shadow window requires latest tournament winner")
            policy = uow.discovery.policy(window.policy_revision_id)
            if policy is None or policy.family != window.policy_family:
                raise ValueError("shadow window family mismatch")
            start, end = (
                datetime.fromisoformat(window.start_at),
                datetime.fromisoformat(window.end_at),
            )
            holdout = datetime.fromisoformat(tournament.holdout_cutoff_at)
            if (
                any(value.tzinfo is None for value in (start, end, holdout))
                or not max(request.requested_at, holdout) < start < end
                or window.minimum_independent_worlds < 1
            ):
                raise ValueError("shadow window must be preregistered with future ordered cutoffs")
            if (
                not window.human_actor_id
                or not window.acted_by
                or window.acted_by != window.human_actor_id
                or not window.scope
                or not window.invariant_codes
            ):
                raise ValueError("shadow window requires human identity, scope and invariants")
            uow.discovery.insert_shadow_window(replace(window, action_id=cmd.action_id))
            return (ObjectRef("policy_shadow_window", window.policy_shadow_window_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)

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
            if deployment.supersedes_deployment_id != (
                previous.policy_deployment_id if previous is not None else None
            ):
                raise ValueError("deployment must supersede latest scoped human event")
            if (previous is not None and datetime.fromisoformat(deployment.decided_at)
                <= datetime.fromisoformat(previous.decided_at)):
                raise ValueError("scoped successor must have newer decision time")
            if decision is DeploymentDecision.SHADOW:
                from nutmeg.ontology.discovery.models import canonical_hash

                refs = deployment.evidence_refs or {}
                window = uow.discovery.shadow_window(refs.get("shadow_window_id", ""))
                if (
                    window is None
                    or window.policy_family != policy.family
                    or window.policy_revision_id != policy.policy_revision_id
                    or window.policy_tournament_id != tournament.policy_tournament_id
                    or window.scope != deployment.scope
                    or refs.get("shadow_window_hash")
                    != canonical_hash(
                        {key: value for key, value in asdict(window).items() if key != "action_id"}
                    )
                    or request.requested_at >= datetime.fromisoformat(window.start_at)
                ):
                    raise ValueError("shadow requires preregistered shadow window")
                if set(deployment.brake_conditions.get("conditions", ())) != set(
                    window.invariant_codes
                ):
                    raise ValueError("shadow brake invariants differ from preregistered window")
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
                    select(sd.policy_deployments.c.policy_deployment_id,
                           sd.policy_deployments.c.decided_at)
                    .where(
                        sd.policy_deployments.c.policy_family == policy.family,
                        sd.policy_deployments.c.scope_json == canonical_json(deployment.scope),
                        sd.policy_deployments.c.policy_revision_id
                        == deployment.rollback_policy_revision_id,
                        sd.policy_deployments.c.decision.in_(("shadow", "canary", "deploy")),
                    )
                    .order_by(sd.policy_deployments.c.decided_at.desc())
                    .limit(1)
                ).first()
                if (
                    deployment.rollback_policy_revision_id == deployment.policy_revision_id
                    or prior_approval is None
                    or prior_approval.decided_at >= deployment.decided_at
                ):
                    raise ValueError("canary/deploy requires a distinct human-approved fallback")
                from nutmeg.discovery.promotion_evidence import (
                    evaluate_shadow_window,
                    valid_protected_receipt,
                )
                from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions
                from nutmeg.ontology.discovery.models import canonical_hash

                refs = deployment.evidence_refs or {}
                window = uow.discovery.shadow_window(refs.get("shadow_window_id", ""))
                shadow = uow.discovery.deployment(refs.get("shadow_deployment_id", ""))
                if (
                    window is None
                    or shadow is None
                    or shadow.decision != "shadow"
                    or shadow.policy_revision_id != policy.policy_revision_id
                    or shadow.scope != deployment.scope
                    or window.scope != deployment.scope
                    or window.policy_tournament_id != tournament.policy_tournament_id
                    or window.policy_revision_id != policy.policy_revision_id
                    or shadow.evidence_refs.get("shadow_window_id")
                    != window.policy_shadow_window_id
                    or refs.get("shadow_window_hash")
                    != canonical_hash(
                        {key: value for key, value in asdict(window).items() if key != "action_id"}
                    )
                ):
                    raise ValueError("canary/deploy requires closed prospective shadow window")
                rows = uow.connection.execute(
                    select(worlds.c.world_id)
                    .join(runs, runs.c.world_id == worlds.c.world_id)
                    .where(
                        runs.c.policy_revision_id == policy.policy_revision_id,
                        runs.c.environment_mode == "shadow",
                    )
                ).scalars()
                sealed = []
                invalid_window_world = False
                for world_id in rows:
                    world = uow.discovery.world(world_id)
                    if datetime.fromisoformat(world.cutoff_at) < datetime.fromisoformat(
                        window.start_at
                    ):
                        continue
                    events = uow.discovery.world_events(world_id)
                    nodes = uow.discovery.nodes_for_world(world_id)
                    if (
                        world.cutoff_at > shadow.decided_at
                        and uow.discovery.world_state(world_id) == "sealed"
                        and events[-1].manifest_hash
                        == DiscoveryWorldActions.seal_manifest(world, nodes)
                        and world.input_manifest_hash == canonical_hash(world.input_manifest)
                        and uow.discovery.protected_receipt(world_id) is not None
                    ):
                        sealed.append(world)
                    else:
                        invalid_window_world = True
                if invalid_window_world:
                    raise ValueError("canary/deploy rejects unsealed or altered shadow world")
                receipts = {}
                for world in sealed:
                    receipt = uow.discovery.protected_receipt(world.world_id)
                    if valid_protected_receipt({key: receipt[key] for key in (
                        "schema_version", "world_id", "policy_revision_id",
                        "before_hash", "after_hash", "receipt_hash"
                    )}, world.world_id, policy.policy_revision_id):
                        receipts[world.world_id] = {
                            key: receipt[key] for key in (
                                "schema_version", "world_id", "policy_revision_id",
                                "before_hash", "after_hash", "receipt_hash"
                            ) if key in receipt
                        }
                eligibility = evaluate_shadow_window(
                    window,
                    tournament,
                    sealed,
                    now=request.requested_at,
                    excluded_world_ids=prior_worlds,
                    policy_revision_id=policy.policy_revision_id,
                    receipts=receipts,
                )
                if not eligibility.eligible_for_canary:
                    raise ValueError(
                        "canary/deploy requires closed prospective shadow window: "
                        + ", ".join(eligibility.blocking_codes)
                    )
                from nutmeg.discovery.pilot_scope import validate_control_scope

                refs = deployment.evidence_refs or {}
                contract = validate_control_scope(
                    deployment.scope, refs.get("scope_contract", {}),
                    reviewed_hash=request.reviewed_scope_hash,
                    approval_ref=request.scope_approval_ref,
                )
                review = uow.discovery.scope_review(request.reviewed_scope_hash)
                if (review is None or review["contract"] != contract.model_dump(mode="json")
                    or review["approval_ref"] != request.scope_approval_ref
                    or refs.get("scope_review_action_id") != review["action_id"]
                    or datetime.fromisoformat(review["approved_at"])
                    >= request.requested_at):
                    raise ValueError("separate human-reviewed scope approval is required")
                if (refs.get("scope_contract_hash") != request.reviewed_scope_hash
                    or refs.get("scope_approval_ref") != request.scope_approval_ref
                    or contract.effective_boundary != deployment.effective_boundary
                    or contract.fallback_policy_revision_id
                    != deployment.rollback_policy_revision_id
                    or set(deployment.brake_conditions.get("conditions", ()))
                    != set(contract.brake_codes)
                    or request.requested_at >= datetime.fromisoformat(contract.effective_boundary)):
                    raise ValueError("deployment differs from reviewed prospective scope")
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
            if brake.condition_code in {
                "permission_leak", "audit_invalidation", "protected_mutation",
                "resource_overrun", "manifest_breach",
            } and not isinstance(brake.evidence, dict):
                raise ValueError("brake requires committed diagnostic evidence")
            if brake.condition_code in {
                "permission_leak", "audit_invalidation", "protected_mutation",
                "resource_overrun", "manifest_breach",
            } and "action_id" not in brake.evidence:
                raise ValueError("brake requires committed diagnostic evidence")
            if isinstance(brake.evidence, dict) and "action_id" in brake.evidence:
                from nutmeg.ontology.repository import schema

                source = uow.connection.execute(select(schema.actions).where(
                    schema.actions.c.action_id == brake.evidence["action_id"],
                    schema.actions.c.status == "committed",
                    schema.actions.c.action_type == "record_discovery_failure",
                )).mappings().first()
                node_raw = uow.connection.execute(select(sd.discovery_nodes).where(
                    sd.discovery_nodes.c.action_id == brake.evidence["action_id"],
                )).mappings().first()
                if source is None or node_raw is None:
                    raise ValueError("brake requires committed diagnostic fact")
                node = uow.discovery.node(node_raw["node_id"])
                run = uow.discovery.run(node.discovery_run_id)
                if (brake.evidence != {
                    "action_id": source["action_id"], "request_hash": source["request_hash"],
                    "node_id": node.node_id,
                } or run.policy_revision_id != deployment.policy_revision_id
                    or brake.condition_code not in node.diagnostic_codes):
                    raise ValueError("brake evidence does not match registered committed fact")
            uow.discovery.insert_brake(replace(brake, action_id=cmd.action_id))
            return (ObjectRef("policy_brake_event", brake.policy_brake_event_id),)

        return self._svc.execute(command, handler, acquire_write_lock=True)
