from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime

import pytest

from nutmeg.ontology.actions.discovery_governance_actions import (
    ApprovePolicyDeploymentRequest,
    CreatePolicyTournamentRequest,
    DiscoveryGovernanceActions,
    FinishPolicyTournamentRequest,
    TripPolicyBrakeRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import (
    ArchiveDecisionRow,
    DiscoveryRunRow,
    PolicyBrakeEventRow,
    PolicyDeploymentRow,
    PolicyParentLinkRow,
    TournamentCandidateRow,
    TournamentCompletionRow,
    TournamentResultRow,
    TournamentRow,
    TournamentWorldRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_discovery_repository import _event, _policy, _record, _world

T0 = datetime(2026, 9, 21, 8, tzinfo=UTC)
CONTRACT = {
    "evaluator_revision": "structural-candidate-evaluator-v1",
    "aggregation_revision": "structural-aggregation-v1",
    "tie_rule": "incumbent",
    "archive_rule": {"capacity": 12, "max_per_lineage": 3},
    "minimum_materiality": 0.01,
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
        for world_id, day in (("world-1", "2026-09-20"), ("world-2", "2026-09-21")):
            uow.discovery.insert_world(
                replace(
                    _world(),
                    world_id=world_id,
                    business_date=day,
                    cutoff_at=f"{day}T07:00:00+00:00",
                )
            )
            uow.discovery.insert_world_event(
                replace(
                    _event(1, "created"), world_id=world_id, world_event_id=f"{world_id}:created"
                )
            )
            if sealed:
                uow.discovery.insert_world_event(
                    replace(
                        _event(2, "sealed"), world_id=world_id, world_event_id=f"{world_id}:sealed"
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
        else (
            _record(
                TournamentWorldRow,
                policy_tournament_id=tournament_id,
                world_index=0,
                world_id="world-1",
                pool_role="development",
                stratum_labels={},
            ),
            _record(
                TournamentWorldRow,
                policy_tournament_id=tournament_id,
                world_index=1,
                world_id="world-2",
                pool_role="holdout",
                stratum_labels={},
            ),
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
                score_vector={"safety": 1, "quality": 2},
            )
            for policy_id in ("policy-1", "policy-2")
            for world_id in ("world-1", "world-2")
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
    proof = canonical_hash(
        {
            "candidate_set_hash": _create_request().tournament.candidate_set_hash,
            "world_pool_manifest_hash": _create_request().tournament.world_pool_manifest_hash,
            "results": [asdict(r) for r in results],
            "winner": winner,
        }
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


def test_disqualified_policy_cannot_enter_archive(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    actions.create_tournament(_create_request())
    request = _finish_request()
    disqualified = replace(request.results[2], disqualified=True, exclusion_reason="invalid")
    bad = _finish_request(
        results=(request.results[0], request.results[1], disqualified, request.results[3])
    )
    with pytest.raises(ValueError, match="disqualified"):
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
