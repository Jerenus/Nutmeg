from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.selection_contract import load_selection_contract
from nutmeg.ontology.actions.discovery_governance_actions import (
    ApprovePolicyDeploymentRequest,
    CreatePolicyTournamentRequest,
    DiscoveryGovernanceActions,
    FinishPolicyTournamentRequest,
    PreregisterPolicyShadowWindowRequest,
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
    PolicyShadowWindowRow,
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


def _seed(engine, *, sealed=True, expanded_world_ids=(), missing_evaluation_world_ids=()):
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
                if world_id not in missing_evaluation_world_ids:
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
                                "attempts": 2 if world_id in expanded_world_ids else 1,
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


def test_direct_create_rejects_exposed_development_without_newer_hidden_holdout(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    from nutmeg.ontology.repository.discovery import HoldoutExposureRow

    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_tournament(_create_request().tournament)
        uow.discovery.insert_holdout_exposure(
            _record(
                HoldoutExposureRow,
                holdout_exposure_id="exposure-dev",
                policy_tournament_id="t-1",
                policy_family="family-1",
                world_id="world-1",
            )
        )
    request = _create_request(tournament_id="t-2", idempotency_key="tournament:rotation")
    # The second cutoff is later than the development world's cutoff, but not
    # later than the completed tournament's protected holdout cutoff.
    old = replace(_create_request().tournament, holdout_cutoff_at="2026-09-22T00:00:00+00:00")
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_tournament(replace(old, policy_tournament_id="t-prior"))
        uow.discovery.insert_holdout_exposure(
            _record(
                HoldoutExposureRow,
                holdout_exposure_id="exposure-prior",
                policy_tournament_id="t-prior",
                policy_family="family-1",
                world_id="world-1",
            )
        )
    with pytest.raises(ValueError, match="strictly newer"):
        actions.create_tournament(request)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-2") is None


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


def test_two_temporary_cycles_preserve_first_tournament_and_rotate_exposure(
    tmp_path,
    monkeypatch,
):
    import sys

    from nutmeg.discovery.iteration_readiness import review_new_information
    from nutmeg.discovery.readiness import CoverageWorld
    from nutmeg.ontology.repository import schema
    from nutmeg.ontology.repository import schema_discovery as sd

    new_worlds = tuple((f"world-new-{day}", f"2026-09-{day}") for day in (22, 23, 24))
    monkeypatch.setattr(sys.modules[__name__], "FIXTURE_WORLDS", (*FIXTURE_WORLDS, *new_worlds))
    actions, engine = _rig(tmp_path)
    _seed(engine, expanded_world_ids={world_id for world_id, _day in new_worlds})
    first = _create_request()
    first_worlds = first.worlds[:-3]
    first = replace(
        first,
        worlds=first_worlds,
        tournament=replace(
            first.tournament,
            world_pool_manifest_hash=canonical_hash([asdict(item) for item in first_worlds]),
        ),
    )
    assert actions.create_tournament(first).status is ActionStatus.COMMITTED
    original = _finish_request(archives=())
    first_results = tuple(
        item
        for item in original.results
        if item.world_id not in {world_id for world_id, _day in new_worlds}
    )
    original = replace(
        original,
        results=first_results,
        completion=replace(
            original.completion,
            reproduction_hash=actions.selection_proof(first.tournament, first_results, "policy-1"),
        ),
    )
    assert actions.finish_tournament(original).status is ActionStatus.COMMITTED

    old = tuple(
        CoverageWorld(world_id, day, f"snap-{day}", "s1", (), True, True, 2, False)
        for world_id, day in FIXTURE_WORLDS[:-3]
    )
    incoming = tuple(
        CoverageWorld(world_id, day, f"snap-{day}", "s1", (), True, True, 2, False)
        for world_id, day in new_worlds
    )
    assert review_new_information(old, incoming, min_clusters=3).effective_new_clusters == 3

    second = _create_request(tournament_id="t-2", idempotency_key="cycle:2")
    second_worlds = tuple(
        replace(item, pool_role="holdout" if item.world_id == "world-new-24" else "development")
        for item in second.worlds
    )
    second = replace(
        second,
        worlds=second_worlds,
        tournament=replace(
            second.tournament,
            development_cutoff_at="2026-09-23T23:59:59+00:00",
            holdout_cutoff_at="2026-09-24T23:59:59+00:00",
            world_pool_manifest_hash=canonical_hash([asdict(item) for item in second_worlds]),
        ),
    )
    assert actions.create_tournament(second).status is ActionStatus.COMMITTED
    results = tuple(
        replace(
            item,
            policy_tournament_id="t-2",
            score_vector={
                **item.score_vector,
                "node_count": "2"
                if item.world_id in {world_id for world_id, _day in new_worlds}
                else "1",
            },
        )
        for item in _finish_request().results
    )
    second_finish = _finish_request(archives=())
    second_finish = replace(
        second_finish,
        tournament_id="t-2",
        results=results,
        idempotency_key="cycle:2:finish",
        completion=replace(
            second_finish.completion,
            policy_tournament_id="t-2",
            reproduction_hash=actions.selection_proof(second.tournament, results, "policy-1"),
        ),
    )
    assert actions.finish_tournament(second_finish).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") == first.tournament.__class__(
            **{**asdict(first.tournament), "action_id": uow.discovery.tournament("t-1").action_id}
        )
        assert uow.discovery.tournament_completion("t-1").reproduction_hash == (
            original.completion.reproduction_hash
        )
        assert {item.world_id for item in uow.discovery.exposed_holdouts("family-1")} == {
            "world-2",
            "world-new-24",
        }
        assert uow.discovery.latest_deployment("family-1") is None
        protected = uow.connection.execute(
            select(sd.policy_deployments.c.policy_deployment_id)
        ).all()
        assert protected == []
        protected_types = {
            "confirm_ticket_placement",
            "record_cash_transaction",
            "rsi_approve_deployment",
            "approve_policy_deployment",
            "trip_policy_brake",
        }
        assert not protected_types.intersection(
            uow.connection.execute(select(schema.actions.c.action_type)).scalars().all()
        )
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    timeline = DiscoveryReadService(engine).iteration("family-1")
    assert timeline["effective_new_clusters"] == 0
    assert timeline["drift"]["state"] == "hold_for_review"
    assert timeline["exposed_holdout_ids"] == ["world-2", "world-new-24"]
    assert timeline["protected_holdout_ids"] == ["world-new-24"]
    assert timeline["policy_lineage"]["policy-1"] == []


def test_iteration_projection_does_not_count_invalid_sealed_tree(tmp_path):
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    _actions, engine = _rig(tmp_path)
    _seed(engine, missing_evaluation_world_ids={"world-1"})
    report = DiscoveryReadService(engine).iteration("family-1")
    assert report["effective_new_clusters"] == len(FIXTURE_WORLDS) - 1


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
    with pytest.raises(ValueError, match="preregistered shadow window"):
        actions.approve_deployment(_deployment_request())
    for decision in ("canary", "deploy"):
        with pytest.raises(ValueError, match="fresh prospective shadow"):
            actions.approve_deployment(
                _deployment_request(decision, deployment_id=f"dep-{decision}")
            )


def test_shadow_requires_human_preregistered_future_window(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with pytest.raises(ValueError, match="preregistered shadow window"):
        actions.approve_deployment(_deployment_request())
    window = _record(
        PolicyShadowWindowRow,
        policy_shadow_window_id="window-1",
        policy_family="family-1",
        scope={"pilot": "structural"},
        policy_revision_id="policy-1",
        policy_tournament_id="t-1",
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-25T00:00:00+00:00",
        minimum_independent_worlds=2,
        invariant_codes=["permission_leak"],
        human_actor_id="Jun",
        acted_by="Jun",
        created_at=T0.isoformat(),
    )
    request = PreregisterPolicyShadowWindowRequest(
        window=window,
        actor_id="op:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="window:1",
        requested_at=T0,
    )
    assert actions.preregister_shadow_window(request).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        stored = uow.discovery.shadow_window("window-1")
        assert stored.policy_revision_id == "policy-1"
    shadow = _deployment_request()
    shadow = replace(
        shadow,
        deployment=replace(
            shadow.deployment,
            brake_conditions={"conditions": ["permission_leak"]},
            evidence_refs={
                "shadow_window_id": "window-1",
                "shadow_window_hash": canonical_hash(
                    {k: v for k, v in asdict(stored).items() if k != "action_id"}
                ),
            },
        ),
    )
    assert actions.approve_deployment(shadow).status is ActionStatus.COMMITTED


def test_shadow_cannot_weaken_preregistered_invariants(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    window = _record(
        PolicyShadowWindowRow,
        policy_shadow_window_id="window-1",
        policy_family="family-1",
        scope={"pilot": "structural"},
        policy_revision_id="policy-1",
        policy_tournament_id="t-1",
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-25T00:00:00+00:00",
        minimum_independent_worlds=1,
        invariant_codes=["permission_leak"],
        human_actor_id="Jun",
        acted_by="Jun",
        created_at=T0.isoformat(),
    )
    actions.preregister_shadow_window(
        PreregisterPolicyShadowWindowRequest(
            window,
            "op:jun",
            ActorRole.JUDGE_OPERATOR,
            "window:weak",
            T0,
        )
    )
    with OntologyUnitOfWork(engine) as uow:
        stored = uow.discovery.shadow_window("window-1")
    request = _deployment_request(
        deployment=replace(
            _deployment_request().deployment,
            evidence_refs={
                "shadow_window_id": "window-1",
                "shadow_window_hash": canonical_hash(
                    {k: v for k, v in asdict(stored).items() if k != "action_id"}
                ),
            },
            brake_conditions={"conditions": ["drift"]},
        )
    )
    with pytest.raises(ValueError, match="invariant"):
        actions.approve_deployment(request)


def test_challenger_shadow_run_requires_authorized_window(tmp_path):
    from nutmeg.ontology.actions.discovery_world_actions import StartDiscoveryRunRequest

    actions, engine = _rig(tmp_path)
    _seed(engine, sealed=False)
    run = _record(
        DiscoveryRunRow,
        discovery_run_id="candidate-run",
        world_id="world-1",
        policy_revision_id="policy-2",
        environment_mode="shadow",
    )
    with pytest.raises(ValueError, match="prior human-authorized window"):
        DiscoveryWorldActions(ActionService(lambda: OntologyUnitOfWork(engine))).start_run(
            StartDiscoveryRunRequest(
                run, "sys:discovery", ActorRole.DETERMINISTIC_SYSTEM, "challenger:unauthorized", T0
            )
        )


def test_braked_challenger_cannot_start_new_shadow_run(tmp_path):
    from nutmeg.ontology.actions.discovery_world_actions import StartDiscoveryRunRequest

    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        evidence_action_id = uow.discovery.tournament("t-1").action_id
        uow.discovery.insert_world(
            replace(_world(), world_id="prospective", cutoff_at="2026-09-23T07:00:00+00:00")
        )
        uow.discovery.insert_world_event(
            replace(
                _event(1, "created"), world_id="prospective", world_event_id="prospective:created"
            )
        )
        uow.discovery.insert_shadow_window(
            _record(
                PolicyShadowWindowRow,
                policy_shadow_window_id="window-1",
                policy_family="family-1",
                scope={"pilot": "structural"},
                policy_revision_id="policy-1",
                policy_tournament_id="t-1",
                start_at="2026-09-22T00:00:00+00:00",
                end_at="2026-09-25T00:00:00+00:00",
                minimum_independent_worlds=1,
                invariant_codes=["permission_leak"],
                action_id=evidence_action_id,
            )
        )
        uow.discovery.insert_deployment(
            replace(
                _deployment_request("shadow").deployment,
                evidence_refs={"shadow_window_id": "window-1"},
                action_id=evidence_action_id,
            )
        )
        uow.discovery.insert_brake(replace(_brake_request().brake, action_id=evidence_action_id))
    run = _record(
        DiscoveryRunRow,
        discovery_run_id="braked-run",
        world_id="prospective",
        policy_revision_id="policy-1",
        environment_mode="shadow",
    )
    with pytest.raises(ValueError, match="braked"):
        DiscoveryWorldActions(ActionService(lambda: OntologyUnitOfWork(engine))).start_run(
            StartDiscoveryRunRequest(
                run,
                "sys:test",
                ActorRole.DETERMINISTIC_SYSTEM,
                "braked:run",
                datetime(2026, 9, 23, tzinfo=UTC),
            )
        )


def test_shadow_window_rejects_nonhuman_late_and_stale_tournament(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    window = _record(
        PolicyShadowWindowRow,
        policy_shadow_window_id="window-1",
        policy_family="family-1",
        scope={"pilot": "structural"},
        policy_revision_id="policy-1",
        policy_tournament_id="t-1",
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-25T00:00:00+00:00",
        minimum_independent_worlds=2,
        invariant_codes=["permission_leak"],
        human_actor_id="Jun",
        acted_by="Jun",
        created_at=T0.isoformat(),
    )
    request = PreregisterPolicyShadowWindowRequest(
        window,
        "op:jun",
        ActorRole.DETERMINISTIC_SYSTEM,
        "window:nonhuman",
        T0,
    )
    assert actions.preregister_shadow_window(request).status is ActionStatus.REJECTED
    request = replace(
        request,
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="window:late",
        window=replace(window, start_at=T0.isoformat()),
    )
    with pytest.raises(ValueError, match="future ordered cutoffs"):
        actions.preregister_shadow_window(request)
    request = replace(
        request,
        idempotency_key="window:stale",
        window=replace(window, policy_tournament_id="other"),
    )
    with pytest.raises(ValueError, match="latest tournament winner"):
        actions.preregister_shadow_window(request)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.shadow_window("window-1") is None


def test_only_one_deployed_incumbent_exists_per_family_scope(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("deploy").deployment)
    with pytest.raises(ValueError, match="supersede"):
        actions.approve_deployment(
            _deployment_request(
                "deploy", deployment_id="dep-2", idempotency_key="deployment:second"
            )
        )


def test_shadow_update_requires_latest_scoped_predecessor(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("shadow").deployment)
    with pytest.raises(ValueError, match="supersede"):
        actions.approve_deployment(
            _deployment_request("shadow", deployment_id="dep-next", idempotency_key="shadow:stale")
        )


def test_scoped_successor_must_be_newer_than_predecessor(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("hold").deployment)
    row = replace(
        _deployment_request("hold", deployment_id="dep-next").deployment,
        supersedes_deployment_id="dep-1",
    )
    with pytest.raises(ValueError, match="newer"):
        actions.approve_deployment(
            _deployment_request(
                "hold", deployment_id="dep-next", idempotency_key="hold:backdated", deployment=row
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
    with pytest.raises(ValueError, match="supersede"):
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


def test_deploy_with_fresh_shadow_and_fallback_still_requires_reviewed_scope(tmp_path):
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
    with pytest.raises(ValueError, match="supersede"):
        actions.approve_deployment(request)
    with OntologyUnitOfWork(engine) as uow:
        deployed = uow.discovery.latest_deployment_for_scope("family-1", {"pilot": "structural"})
        assert deployed.policy_deployment_id == "dep-fallback"


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


def test_d6_brake_cannot_use_unverified_self_report(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(
            replace(
                _deployment_request("deploy").deployment,
                brake_conditions={"conditions": ["permission_leak"]},
            )
        )
    request = _brake_request()
    with pytest.raises(ValueError, match="committed diagnostic"):
        actions.trip_brake(
            replace(
                request,
                brake=replace(
                    request.brake, condition_code="permission_leak", evidence={"measured": True}
                ),
            )
        )


def test_scope_review_action_denies_nonhuman_and_unreviewed_hash(tmp_path):
    from nutmeg.ontology.actions.discovery_governance_actions import ApprovePilotScopeRequest
    from tests.discovery.test_pilot_scope import _contract

    actions, engine = _rig(tmp_path)
    contract = _contract()
    request = ApprovePilotScopeRequest(
        contract=contract,
        reviewed_hash="0" * 64,
        approval_ref=contract["approval_ref"],
        actor_id="op:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="scope:wrong",
        requested_at=T0,
    )
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        actions.approve_pilot_scope(request)
    assert (
        actions.approve_pilot_scope(
            replace(
                request,
                reviewed_hash=canonical_hash(contract),
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key="scope:system",
            )
        ).status
        is ActionStatus.REJECTED
    )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.scope_review(canonical_hash(contract)) is None


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
                    decided_at=T0.isoformat(),
                ),
                idempotency_key="resume:operator",
            )
        ).status
        is ActionStatus.COMMITTED
    )
