from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.selection_contract import load_selection_contract
from nutmeg.ontology.actions.discovery_governance_actions import (
    ApprovePolicyDeploymentRequest,
    CreatePolicyTournamentRequest,
    DiscoveryGovernanceActions,
    FinishPolicyTournamentRequest,
    TripPolicyBrakeRequest,
)
from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import (
    ArchiveDecisionRow,
    DiscoveryRunRow,
    NodeEvaluationRow,
    PolicyBrakeEventRow,
    PolicyDeploymentRow,
    PolicyParentLinkRow,
    PolicyReplayCompletionRow,
    PolicyReplayRoundRow,
    PolicyReplayRunRow,
    TournamentCandidateRow,
    TournamentCompletionRow,
    TournamentResultRow,
    TournamentRow,
    TournamentWorldRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_discovery_repository import _event, _node, _policy, _record, _world

T0 = datetime(2026, 9, 21, 8, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
PILOT = load_pilot_contract(ROOT / "experiments/discovery/structural-candidate-v1.contract.json")
SELECTION = load_selection_contract(
    ROOT / "experiments/discovery/structural-selection-v1.contract.json", PILOT
)
FIXTURE_WORLDS = (
    ("world-1", "2026-09-20"),
    ("world-2", "2026-09-21"),
    *((f"world-extra-{day:02d}", f"2026-08-{day:02d}") for day in range(1, 29)),
)
CONTRACT = {
    "evaluator_revision": "structural-candidate-evaluator-v1",
    "aggregation_revision": SELECTION.aggregation_revision,
    "selection_contract_hash": contract_hash(SELECTION),
    "tie_rule": "incumbent",
    "archive_rule": {"capacity": 12, "max_per_lineage": 3},
    "minimum_materiality": 1,
    "lexicographic_tiers": [
        "safety_isolation",
        "validity",
        "discovery_quality",
        "robustness",
        "cost",
        "parallel_efficiency",
    ],
}


def _rig(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return DiscoveryGovernanceActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _seed(engine, *, sealed=True):
    with OntologyUnitOfWork(engine) as uow:
        for policy_id in ("policy-1", "policy-2"):
            uow.discovery.insert_policy(
                replace(
                    _policy(policy_id),
                    validation_result={"valid": True},
                    compatible_world_families=["structural_candidate_audit"],
                )
            )
        for world_index, (world_id, day) in enumerate(FIXTURE_WORLDS):
            manifest = {
                "references": [],
                "task_snapshot_hash": f"snap-{day}",
                "slate_revision_id": "s1",
                "template_ids": ["T1"],
            }
            world = replace(
                _world(),
                world_id=world_id,
                business_date=day,
                cutoff_at=f"{day}T07:00:00+00:00",
                strata={"board_size": ("small", "medium", "large")[world_index % 3]},
                input_manifest=manifest,
                input_manifest_hash=canonical_hash(manifest),
                root_node_id=f"{world_id}:root",
            )
            uow.discovery.insert_world(world)
            uow.discovery.insert_world_event(
                replace(
                    _event(1, "created"), world_id=world_id, world_event_id=f"{world_id}:created"
                )
            )
            if sealed:
                root = replace(
                    _node(f"{world_id}:root", 1),
                    world_id=world_id,
                    parent_node_id=None,
                    artifact_manifest=manifest,
                    artifact_manifest_hash=canonical_hash(manifest),
                    finished_at=f"{day}T07:00:00+00:00",
                )
                artifact = {"candidates": [f"{world_id}:candidate"]}
                child = replace(
                    _node(f"{world_id}:child", 2),
                    world_id=world_id,
                    parent_node_id=root.node_id,
                    continuation_action={
                        "operator": "enumerate_template_shard",
                        "template_ids": ["T1"],
                    },
                    artifact_manifest=artifact,
                    artifact_manifest_hash=canonical_hash(artifact),
                    execution_status="complete",
                    finished_at=f"{day}T07:00:00+00:00",
                )
                uow.discovery.insert_node(root)
                uow.discovery.insert_node(child)
                second_artifact = {"candidates": [f"{world_id}:other"]}
                second = replace(
                    child,
                    node_id=f"{world_id}:second",
                    creation_sequence=3,
                    visibility_sequence=3,
                    sibling_order=2,
                    continuation_action={
                        "operator": "enumerate_template_shard",
                        "template_ids": ["T2"],
                    },
                    artifact_manifest=second_artifact,
                    artifact_manifest_hash=canonical_hash(second_artifact),
                )
                uow.discovery.insert_node(second)
                uow.discovery.insert_node_evaluation(
                    _record(
                        NodeEvaluationRow,
                        node_evaluation_id=f"{world_id}:evaluation",
                        node_id=child.node_id,
                        evaluator_revision=world.evaluator_revision,
                        result={
                            "eligible_band_count": 1,
                            "best_objective_probability_by_band": {"10x": "0.5"},
                            "distinct_valid_candidate_count_capped": 2,
                        },
                        selectable=True,
                        evaluated_at=f"{day}T07:01:00+00:00",
                    )
                )
                uow.discovery.insert_node_evaluation(
                    _record(
                        NodeEvaluationRow,
                        node_evaluation_id=f"{world_id}:other-evaluation",
                        node_id=second.node_id,
                        evaluator_revision=world.evaluator_revision,
                        result={
                            "eligible_band_count": 1,
                            "best_objective_probability_by_band": {"10x": "0.5"},
                            "distinct_valid_candidate_count_capped": 2,
                        },
                        selectable=True,
                        evaluated_at=f"{day}T07:01:00+00:00",
                    )
                )
                uow.discovery.insert_world_event(
                    replace(
                        _event(2, "sealed"),
                        world_id=world_id,
                        world_event_id=f"{world_id}:sealed",
                        occurred_at=f"{day}T07:02:00+00:00",
                        manifest_hash=DiscoveryWorldActions.seal_manifest(
                            world, (root, child, second)
                        ),
                    )
                )
                for policy_id in ("policy-1", "policy-2"):
                    replay_id = f"replay:{policy_id}:{world_id}"
                    uow.discovery.insert_policy_replay(
                        _record(
                            PolicyReplayRunRow,
                            policy_replay_run_id=replay_id,
                            policy_revision_id=policy_id,
                            world_id=world_id,
                        )
                    )
                    uow.discovery.insert_policy_replay_completion(
                        _record(
                            PolicyReplayCompletionRow,
                            policy_replay_run_id=replay_id,
                            trace_hash=f"trace:{policy_id}:{world_id}",
                            selected_node_ids=[child.node_id],
                            budget_used={
                                "attempts": 1,
                                "wall_ms": 1000,
                                "candidate_generation_count": 5,
                            },
                            failure_codes=[],
                        )
                    )
                    uow.discovery.insert_policy_replay_round(
                        _record(
                            PolicyReplayRoundRow,
                            policy_replay_run_id=replay_id,
                            round_no=1,
                            revealed_node_ids=[child.node_id],
                            accepted_actions=[{"revealed_node_ids": [child.node_id]}],
                            requested_actions=[
                                {"template_ids": ["T1"]},
                                {"template_ids": ["T2"]},
                            ],
                        )
                    )


def _create_request(*, candidates=None, worlds=None, tournament_id="t-1", **changes):
    candidates = (
        candidates
        if candidates is not None
        else (
            _record(
                TournamentCandidateRow,
                policy_tournament_id=tournament_id,
                candidate_index=0,
                policy_revision_id="policy-1",
                candidate_role="incumbent",
            ),
            _record(
                TournamentCandidateRow,
                policy_tournament_id=tournament_id,
                candidate_index=1,
                policy_revision_id="policy-2",
                candidate_role="challenger",
            ),
        )
    )
    worlds = (
        worlds
        if worlds is not None
        else tuple(
            _record(
                TournamentWorldRow,
                policy_tournament_id=tournament_id,
                world_index=index,
                world_id=world_id,
                pool_role="holdout" if world_id == "world-2" else "development",
                stratum_labels={
                    "labels": [f"board_size:{('small', 'medium', 'large')[index % 3]}"],
                },
            )
            for index, (world_id, _day) in enumerate(FIXTURE_WORLDS)
        )
    )
    tournament = _record(
        TournamentRow,
        policy_tournament_id=tournament_id,
        policy_family="family-1",
        incumbent_policy_revision_id="policy-1",
        candidate_set_hash=canonical_hash([asdict(c) for c in candidates]),
        world_pool_manifest_hash=canonical_hash([asdict(w) for w in worlds]),
        evaluator_revision=CONTRACT["evaluator_revision"],
        aggregation_revision=CONTRACT["aggregation_revision"],
        decision_contract=CONTRACT,
        development_cutoff_at="2026-09-20T23:59:59+00:00",
        holdout_cutoff_at="2026-09-21T23:59:59+00:00",
    )
    return CreatePolicyTournamentRequest(
        tournament=changes.pop("tournament", tournament),
        candidates=candidates,
        worlds=worlds,
        actor_id=changes.pop("actor_id", "op:jun"),
        actor_role=changes.pop("actor_role", ActorRole.JUDGE_OPERATOR),
        idempotency_key=changes.pop("idempotency_key", "tournament:create"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def test_create_tournament_requires_incumbent_in_frozen_candidates(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    request = _create_request()
    for candidates in (request.candidates[1:], (*request.candidates, request.candidates[0])):
        bad = _create_request(
            candidates=candidates, idempotency_key=f"tournament:bad:{len(candidates)}"
        )
        with pytest.raises(ValueError, match="incumbent"):
            actions.create_tournament(bad)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") is None


def test_create_tournament_refuses_two_worlds_below_frozen_readiness_gate(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)

    with pytest.raises(ValueError, match="baseline readiness"):
        actions.create_tournament(_create_request(worlds=_create_request().worlds[:2]))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") is None


def test_create_tournament_rejects_invalid_registered_candidate(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(
            replace(_policy("policy-invalid"), validation_result={"valid": False})
        )
    candidate = replace(_create_request().candidates[1], policy_revision_id="policy-invalid")
    request = _create_request(candidates=(_create_request().candidates[0], candidate))
    with pytest.raises(ValueError, match="validated"):
        actions.create_tournament(request)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") is None


def test_create_tournament_cannot_override_frozen_pilot_evaluator_or_archive(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    request = _create_request()
    for key, value in (
        ("archive_rule", {"capacity": 999, "max_per_lineage": 3}),
        ("lexicographic_tiers", ["cost", "safety_isolation"]),
    ):
        modified = replace(
            request.tournament,
            decision_contract={**request.tournament.decision_contract, key: value},
        )
        with pytest.raises(ValueError, match="frozen pilot"):
            actions.create_tournament(
                replace(request, tournament=modified, idempotency_key=f"tournament:override:{key}")
            )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") is None


def test_create_tournament_rejects_unapproved_selection_contract_hash(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    request = _create_request()
    modified = replace(
        request.tournament,
        decision_contract={**CONTRACT, "selection_contract_hash": "wrong-hash"},
    )

    with pytest.raises(ValueError, match="selection contract"):
        actions.create_tournament(replace(request, tournament=modified))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") is None


def test_create_tournament_rejects_unsealed_or_duplicate_worlds(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine, sealed=False)
    with pytest.raises(ValueError, match="sealed"):
        actions.create_tournament(_create_request())
    with OntologyUnitOfWork(engine) as uow:
        for world_id in ("world-1", "world-2"):
            uow.discovery.insert_world_event(
                replace(_event(2, "sealed"), world_id=world_id, world_event_id=f"{world_id}:sealed")
            )
    request = _create_request()
    duplicate = replace(request.worlds[1], world_id="world-1")
    with pytest.raises(ValueError, match="duplicate"):
        actions.create_tournament(_create_request(worlds=(request.worlds[0], duplicate)))


def test_create_tournament_rejects_tampered_sealed_manifest(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    with OntologyUnitOfWork(engine) as uow:
        source = uow.discovery.world("world-2")
        manifest = {**source.input_manifest, "task_snapshot_hash": "other-snapshot"}
        uow.discovery.insert_world(
            replace(
                source,
                world_id="world-3",
                business_date="2026-09-19",
                input_manifest=manifest,
                input_manifest_hash=canonical_hash(manifest),
                root_node_id="missing-root",
            )
        )
        uow.discovery.insert_world_event(
            replace(_event(1, "created"), world_id="world-3", world_event_id="world-3:created")
        )
        uow.discovery.insert_world_event(
            replace(_event(2, "sealed"), world_id="world-3", world_event_id="world-3:sealed")
        )
    request = _create_request()
    worlds = (request.worlds[0], replace(request.worlds[1], world_id="world-3"))

    with pytest.raises(ValueError, match="sealed manifest"):
        actions.create_tournament(
            replace(
                request,
                worlds=worlds,
                tournament=replace(
                    request.tournament,
                    world_pool_manifest_hash=canonical_hash([asdict(w) for w in worlds]),
                ),
            )
        )


def test_create_tournament_cannot_relabel_world_stratum(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    request = _create_request()
    worlds = (
        replace(request.worlds[0], stratum_labels={"labels": ["board_size:large"]}),
        *request.worlds[1:],
    )

    with pytest.raises(ValueError, match="stratum labels"):
        actions.create_tournament(
            replace(
                request,
                worlds=worlds,
                tournament=replace(
                    request.tournament,
                    world_pool_manifest_hash=canonical_hash([asdict(w) for w in worlds]),
                ),
            )
        )


def test_create_tournament_rejects_exposed_world_as_hidden_holdout(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_tournament(_create_request().tournament)
        from nutmeg.ontology.repository.discovery import HoldoutExposureRow

        uow.discovery.insert_holdout_exposure(
            _record(
                HoldoutExposureRow,
                holdout_exposure_id="exposure-1",
                policy_tournament_id="t-1",
                policy_family="family-1",
                world_id="world-2",
            )
        )
    with pytest.raises(ValueError, match="exposed"):
        actions.create_tournament(
            _create_request(tournament_id="t-2", idempotency_key="tournament:exposed")
        )


def test_create_tournament_rejects_exposed_derivative_cluster(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_tournament(_create_request().tournament)
        from nutmeg.ontology.repository.discovery import HoldoutExposureRow

        uow.discovery.insert_holdout_exposure(
            _record(
                HoldoutExposureRow,
                holdout_exposure_id="exposure-2",
                policy_tournament_id="t-1",
                policy_family="family-1",
                world_id="world-2",
            )
        )
        uow.discovery.insert_world(replace(uow.discovery.world("world-2"), world_id="world-3"))
        uow.discovery.insert_world_event(
            replace(_event(1, "created"), world_id="world-3", world_event_id="world-3:created")
        )
        uow.discovery.insert_world_event(
            replace(_event(2, "sealed"), world_id="world-3", world_event_id="world-3:sealed")
        )
    request = _create_request(tournament_id="t-2", idempotency_key="tournament:derivative")
    worlds = (request.worlds[0], replace(request.worlds[1], world_id="world-3"))

    with pytest.raises(ValueError, match="exposed.*cluster"):
        actions.create_tournament(
            replace(
                request,
                worlds=worlds,
                tournament=replace(
                    request.tournament,
                    world_pool_manifest_hash=canonical_hash([asdict(w) for w in worlds]),
                ),
            )
        )


def _finish_request(*, results=None, archives=None, winner="policy-1", **changes):
    results = (
        results
        if results is not None
        else tuple(
            _record(
                TournamentResultRow,
                policy_tournament_id="t-1",
                policy_revision_id=policy_id,
                world_id=world_id,
                score_vector={
                    "invariant_violation_count": "0",
                    "invalid_selected_count": "0",
                    "eligible_band_count": "1",
                    "best_objective_probability_by_band": {"10x": "0.5"},
                    "distinct_valid_candidate_count_capped": "2",
                    "failure_recovery_rate": "1",
                    "node_count": "1",
                    "wall_seconds": "1",
                    "effective_parallelism": "1",
                    "rounds": "1",
                    "retry_count": "0",
                    "candidate_generation_count": "5",
                    "unused_budget": {},
                    "failure_codes": [],
                },
                trace_hash=f"trace:{policy_id}:{world_id}",
            )
            for policy_id in ("policy-1", "policy-2")
            for world_id, _day in FIXTURE_WORLDS
        )
    )
    archives = (
        archives
        if archives is not None
        else (
            _record(
                ArchiveDecisionRow,
                archive_decision_id="archive-1",
                policy_tournament_id="t-1",
                policy_revision_id="policy-2",
                disposition="stepping_stone",
                reason_code="behavioral_coverage",
                diversity_descriptors={"action_histogram": [1]},
                evidence={"valid": True},
            ),
        )
    )
    proof = DiscoveryGovernanceActions.selection_proof(
        _create_request().tournament, results, winner
    )
    return FinishPolicyTournamentRequest(
        tournament_id="t-1",
        results=results,
        archive_decisions=archives,
        completion=changes.pop(
            "completion",
            _record(
                TournamentCompletionRow,
                policy_tournament_id="t-1",
                winner_policy_revision_id=winner,
                reproduction_hash=proof,
            ),
        ),
        actor_id=changes.pop("actor_id", "sys:tournament"),
        actor_role=changes.pop("actor_role", ActorRole.DETERMINISTIC_SYSTEM),
        idempotency_key=changes.pop("idempotency_key", "tournament:finish"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def _finished(actions, engine):
    _seed(engine)
    assert actions.create_tournament(_create_request()).status is ActionStatus.COMMITTED
    assert actions.finish_tournament(_finish_request()).status is ActionStatus.COMMITTED


def test_finish_tournament_requires_complete_policy_world_matrix_or_exclusions(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    request = _finish_request()
    with pytest.raises(ValueError, match="matrix"):
        actions.finish_tournament(_finish_request(results=request.results[:-1]))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_results("t-1") == ()
        assert uow.discovery.tournament_completion("t-1") is None


def test_finish_tournament_separates_winner_from_archive_admission(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1").winner_policy_revision_id == "policy-1"
        assert uow.discovery.latest_archive_decision("policy-2").disposition == "stepping_stone"
        assert uow.discovery.latest_deployment("family-1") is None
        assert [e.world_id for e in uow.discovery.exposed_holdouts("family-1")] == ["world-2"]


def test_finish_rejects_self_consistent_proof_for_unearned_winner(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    request = _finish_request(winner="policy-2", archives=())

    with pytest.raises(ValueError, match="derived winner|selection"):
        actions.finish_tournament(request)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None


def test_finish_rejects_result_trace_without_matching_persisted_replay(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    rows = _finish_request().results
    forged = (replace(rows[0], trace_hash="forged-trace"), *rows[1:])

    with pytest.raises(ValueError, match="replay trace"):
        actions.finish_tournament(_finish_request(results=forged))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None


def test_finish_rejects_arbitrary_quality_score_for_existing_trace(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    rows = _finish_request().results
    forged = (
        replace(rows[0], score_vector={**rows[0].score_vector, "eligible_band_count": "999"}),
        *rows[1:],
    )

    with pytest.raises(ValueError, match="score|replay evidence"):
        actions.finish_tournament(_finish_request(results=forged))


def test_finish_rejects_ambiguous_replays_for_one_cell(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    with OntologyUnitOfWork(engine) as uow:
        replay = uow.discovery.policy_replay("replay:policy-1:world-1")
        completion = uow.discovery.policy_replay_completion(replay.policy_replay_run_id)
        uow.discovery.insert_policy_replay(
            replace(replay, policy_replay_run_id="replay:duplicate", action_id="duplicate-action")
        )
        uow.discovery.insert_policy_replay_completion(
            replace(
                completion, policy_replay_run_id="replay:duplicate", action_id="duplicate-action"
            )
        )

    with pytest.raises(ValueError, match="exactly one.*replay trace"):
        actions.finish_tournament(_finish_request())


def test_selection_proof_is_independent_of_matrix_row_order():
    tournament = _create_request().tournament
    results = _finish_request().results

    assert DiscoveryGovernanceActions.selection_proof(
        tournament, results, "policy-1"
    ) == DiscoveryGovernanceActions.selection_proof(
        tournament, tuple(reversed(results)), "policy-1"
    )


def test_disqualification_flag_without_replay_evidence_cannot_enter_archive(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    request = _finish_request()
    bad = _finish_request(
        results=tuple(
            replace(row, disqualified=True, exclusion_reason="invalid")
            if row.policy_revision_id == "policy-2" and row.world_id == "world-1"
            else row
            for row in request.results
        )
    )
    with pytest.raises(ValueError, match="replay evidence"):
        actions.finish_tournament(bad)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None


def test_archive_limit_counts_existing_admissions_in_same_lineage(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy_parent_link(
            _record(
                PolicyParentLinkRow,
                policy_revision_id="policy-2",
                parent_index=0,
                parent_policy_revision_id="policy-1",
            )
        )
        for index in range(3, 6):
            uow.discovery.insert_policy(
                replace(_policy(f"policy-{index}"), validation_result={"valid": True})
            )
            uow.discovery.insert_policy_parent_link(
                _record(
                    PolicyParentLinkRow,
                    policy_revision_id=f"policy-{index}",
                    parent_index=0,
                    parent_policy_revision_id="policy-1",
                )
            )
            uow.discovery.insert_archive_decision(
                replace(
                    _finish_request().archive_decisions[0],
                    archive_decision_id=f"old-{index}",
                    policy_revision_id=f"policy-{index}",
                    diversity_descriptors={"action_histogram": [0] * index + [1]},
                )
            )
    with pytest.raises(ValueError, match="lineage"):
        actions.finish_tournament(_finish_request())
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None


def test_winner_cannot_be_labeled_stepping_stone(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    bad_archive = replace(_finish_request().archive_decisions[0], policy_revision_id="policy-1")
    with pytest.raises(ValueError, match="stepping stone"):
        actions.finish_tournament(_finish_request(archives=(bad_archive,)))


def test_archive_rejects_reason_not_in_frozen_pilot(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    bad = replace(_finish_request().archive_decisions[0], reason_code="ticket_profit")

    with pytest.raises(ValueError, match="archive reason"):
        actions.finish_tournament(_finish_request(archives=(bad,)))


def test_archive_rejects_duplicate_behavior_descriptor(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(replace(_policy("policy-3"), validation_result={"valid": True}))
        old = _finish_request().archive_decisions[0]
        uow.discovery.insert_archive_decision(
            replace(old, archive_decision_id="old-3", policy_revision_id="policy-3")
        )

    with pytest.raises(ValueError, match="clone|diversity"):
        actions.finish_tournament(_finish_request())


def test_archive_rejects_behavior_below_frozen_jaccard_distance(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    original = _finish_request().archive_decisions[0]
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(replace(_policy("policy-3"), validation_result={"valid": True}))
        uow.discovery.insert_archive_decision(
            replace(
                original,
                archive_decision_id="existing-near-clone",
                policy_revision_id="policy-3",
                diversity_descriptors={"action_histogram": [10, 10]},
            )
        )
    near_clone = replace(original, diversity_descriptors={"action_histogram": [11, 10]})
    with pytest.raises(ValueError, match="Jaccard|diversity"):
        actions.finish_tournament(_finish_request(archives=(near_clone,)))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None


def test_full_archive_retires_oldest_dominated_clone_atomically(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    original = _finish_request().archive_decisions[0]
    with OntologyUnitOfWork(engine) as uow:
        for index in range(3, 15):
            policy_id = f"policy-{index}"
            uow.discovery.insert_policy(
                replace(_policy(policy_id), validation_result={"valid": True})
            )
            uow.discovery.insert_archive_decision(
                replace(
                    original,
                    archive_decision_id=f"existing-{index}",
                    policy_revision_id=policy_id,
                    diversity_descriptors={
                        "action_histogram": [1, 0] if index in (3, 4) else [0] * index + [1]
                    },
                )
            )
    new = replace(original, diversity_descriptors={"action_histogram": [1, 1]})
    retired = replace(
        original,
        archive_decision_id="retire-oldest-clone",
        policy_revision_id="policy-3",
        disposition="retired",
        reason_code="dominated_clone",
        evidence={"duplicate_of": "policy-4"},
    )
    assert (
        actions.finish_tournament(_finish_request(archives=(new, retired))).status
        is ActionStatus.COMMITTED
    )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.latest_archive_decision("policy-3").disposition == "retired"
        assert uow.discovery.latest_archive_decision("policy-2").disposition == "stepping_stone"
        assert len(actions._active_archive_ids(uow, "family-1")) == 12


@pytest.mark.parametrize(
    ("policy_id", "duplicate_id"),
    [("policy-4", "policy-3"), ("policy-5", "policy-4"), ("policy-3", "policy-3")],
)
def test_archive_retirement_rejects_nonoldest_or_nonclone(tmp_path, policy_id, duplicate_id):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    original = _finish_request().archive_decisions[0]
    distinct = replace(original, diversity_descriptors={"action_histogram": [0] * 20 + [1]})
    with OntologyUnitOfWork(engine) as uow:
        for index in range(3, 15):
            uow.discovery.insert_policy(
                replace(_policy(f"policy-{index}"), validation_result={"valid": True})
            )
            uow.discovery.insert_archive_decision(
                replace(
                    original,
                    archive_decision_id=f"existing-{index}",
                    policy_revision_id=f"policy-{index}",
                    diversity_descriptors={
                        "action_histogram": [1, 0] if index in (3, 4) else [index]
                    },
                )
            )
    retirement = replace(
        original,
        archive_decision_id="invalid-retirement",
        policy_revision_id=policy_id,
        disposition="retired",
        reason_code="dominated_clone",
        evidence={"duplicate_of": duplicate_id},
    )
    with pytest.raises(ValueError, match="oldest dominated clone"):
        actions.finish_tournament(_finish_request(archives=(distinct, retirement)))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None
        assert uow.discovery.latest_archive_decision(policy_id).disposition == "stepping_stone"
        assert uow.discovery.exposed_holdouts("family-1") == ()


def test_archive_retirement_cannot_remove_more_members_than_needed(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    original = _finish_request().archive_decisions[0]
    distinct = replace(original, diversity_descriptors={"action_histogram": [0] * 20 + [1]})
    with OntologyUnitOfWork(engine) as uow:
        for index in range(3, 15):
            uow.discovery.insert_policy(
                replace(_policy(f"policy-{index}"), validation_result={"valid": True})
            )
            uow.discovery.insert_archive_decision(
                replace(
                    original,
                    archive_decision_id=f"existing-{index}",
                    policy_revision_id=f"policy-{index}",
                    diversity_descriptors={
                        "action_histogram": [1, 0] if index in (3, 4, 5) else [index]
                    },
                )
            )
    retirements = tuple(
        replace(
            original,
            archive_decision_id=f"retire-{index}",
            policy_revision_id=f"policy-{index}",
            disposition="retired",
            reason_code="dominated_clone",
            evidence={"duplicate_of": f"policy-{index + 1}"},
        )
        for index in (3, 4)
    )
    with pytest.raises(ValueError, match="exactly the members needed for capacity"):
        actions.finish_tournament(_finish_request(archives=(distinct, *retirements)))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1") is None
        assert uow.discovery.latest_archive_decision("policy-3").disposition == "stepping_stone"


def _deployment_request(decision="shadow", policy_id="policy-1", **changes):
    row = _record(
        PolicyDeploymentRow,
        policy_deployment_id=changes.pop("deployment_id", "dep-1"),
        policy_family="family-1",
        policy_revision_id=policy_id,
        decision=decision,
        scope={"pilot": "structural"},
        human_actor_id="Jun",
        acted_by="Jun",
        reason="approved",
        rollback_policy_revision_id="policy-2",
        brake_conditions={"conditions": ["drift"]},
    )
    return ApprovePolicyDeploymentRequest(
        deployment=changes.pop("deployment", row),
        actor_id=changes.pop("actor_id", "op:jun"),
        actor_role=changes.pop("actor_role", ActorRole.JUDGE_OPERATOR),
        idempotency_key=changes.pop("idempotency_key", f"deployment:{decision}"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def test_only_operator_can_approve_shadow_canary_deploy_hold_rollback_retire(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    for decision in ("shadow", "canary", "deploy", "hold", "rollback", "retire"):
        request = _deployment_request(decision, actor_role=ActorRole.DETERMINISTIC_SYSTEM)
        assert actions.approve_deployment(request).status is ActionStatus.REJECTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.latest_deployment("family-1") is None


def test_replay_winner_without_fresh_shadow_can_only_receive_shadow_decision(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    assert actions.approve_deployment(_deployment_request()).status is ActionStatus.COMMITTED
    for decision in ("canary", "deploy"):
        with pytest.raises(ValueError, match="fresh prospective shadow"):
            actions.approve_deployment(
                _deployment_request(decision, deployment_id=f"dep-{decision}")
            )


def test_only_one_deployed_incumbent_exists_per_family_scope(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("deploy").deployment)
    with pytest.raises(ValueError, match="active deployed incumbent"):
        actions.approve_deployment(
            _deployment_request(
                "deploy", deployment_id="dep-2", idempotency_key="deployment:second"
            )
        )


def test_deployment_uniqueness_checks_same_scope_even_when_other_scope_is_newer(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("deploy").deployment)
        other_scope = replace(
            _deployment_request("hold", deployment_id="dep-other").deployment,
            scope={"pilot": "other"},
            decided_at="2026-09-22T00:00:00+00:00",
            action_id="other-action",
        )
        uow.discovery.insert_deployment(other_scope)
        uow.discovery.insert_world(
            replace(_world(), world_id="world-3", cutoff_at="2026-09-22T07:00:00+00:00")
        )
        uow.discovery.insert_world_event(
            replace(_event(1, "created"), world_id="world-3", world_event_id="world-3:created")
        )
        uow.discovery.insert_world_event(
            replace(_event(2, "sealed"), world_id="world-3", world_event_id="world-3:sealed")
        )
        uow.discovery.insert_run(
            _record(
                DiscoveryRunRow,
                discovery_run_id="run-3",
                world_id="world-3",
                environment_mode="shadow",
            )
        )
    with pytest.raises(ValueError, match="active deployed incumbent"):
        actions.approve_deployment(
            _deployment_request(
                "deploy", deployment_id="dep-new", idempotency_key="deploy:same-scope"
            )
        )


def test_deploy_requires_previously_human_approved_fallback(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(
            replace(_world(), world_id="world-3", cutoff_at="2026-09-22T07:00:00+00:00")
        )
        uow.discovery.insert_world_event(
            replace(_event(1, "created"), world_id="world-3", world_event_id="world-3:created")
        )
        uow.discovery.insert_world_event(
            replace(_event(2, "sealed"), world_id="world-3", world_event_id="world-3:sealed")
        )
        uow.discovery.insert_run(
            _record(
                DiscoveryRunRow,
                discovery_run_id="run-3",
                world_id="world-3",
                environment_mode="shadow",
            )
        )
    with pytest.raises(ValueError, match="approved fallback"):
        actions.approve_deployment(_deployment_request("deploy"))


def test_deploy_with_fresh_shadow_and_approved_fallback_records_brake_target(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(
            replace(
                _deployment_request(
                    "shadow", policy_id="policy-2", deployment_id="dep-fallback"
                ).deployment,
                action_id="prior-human-approval",
                decided_at="2026-09-20T07:00:00+00:00",
            )
        )
        uow.discovery.insert_world(
            replace(_world(), world_id="world-3", cutoff_at="2026-09-22T07:00:00+00:00")
        )
        uow.discovery.insert_world_event(
            replace(_event(1, "created"), world_id="world-3", world_event_id="world-3:created")
        )
        uow.discovery.insert_world_event(
            replace(_event(2, "sealed"), world_id="world-3", world_event_id="world-3:sealed")
        )
        uow.discovery.insert_run(
            _record(
                DiscoveryRunRow,
                discovery_run_id="run-3",
                world_id="world-3",
                environment_mode="shadow",
            )
        )
    request = _deployment_request("deploy", deployment_id="dep-deployed")
    assert actions.approve_deployment(request).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        deployed = uow.discovery.latest_deployment_for_scope("family-1", {"pilot": "structural"})
        assert deployed.policy_deployment_id == "dep-deployed"
        assert deployed.rollback_policy_revision_id == "policy-2"


def _brake_request(*, restored="policy-2", **changes):
    return TripPolicyBrakeRequest(
        brake=_record(
            PolicyBrakeEventRow,
            policy_brake_event_id="brake-1",
            policy_deployment_id="dep-1",
            tripped_policy_revision_id="policy-1",
            restored_policy_revision_id=restored,
            condition_code="drift",
            evidence={"measured": True},
        ),
        actor_id=changes.pop("actor_id", "sys:brake"),
        actor_role=changes.pop("actor_role", ActorRole.DETERMINISTIC_SYSTEM),
        idempotency_key=changes.pop("idempotency_key", "brake:1"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def test_deterministic_brake_only_restores_recorded_approved_fallback(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("deploy").deployment)
    with pytest.raises(ValueError, match="fallback"):
        actions.trip_brake(_brake_request(restored="policy-1", idempotency_key="brake:bad"))
    assert actions.trip_brake(_brake_request()).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.latest_brake("dep-1").restored_policy_revision_id == "policy-2"


def test_braked_policy_cannot_resume_without_new_human_action(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("deploy").deployment)
    actions.trip_brake(_brake_request())
    assert (
        actions.approve_deployment(
            _deployment_request(
                "shadow",
                deployment_id="dep-2",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="resume:system",
            )
        ).status
        is ActionStatus.REJECTED
    )
    assert (
        actions.approve_deployment(
            _deployment_request(
                "hold",
                deployment_id="dep-2",
                deployment=replace(
                    _deployment_request("hold", deployment_id="dep-2").deployment,
                    supersedes_deployment_id="dep-1",
                ),
                idempotency_key="resume:operator",
            )
        ).status
        is ActionStatus.COMMITTED
    )
