from __future__ import annotations

from dataclasses import fields, replace

import pytest
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import (
    ArchiveDecisionRow,
    DiscoveryRunRow,
    HoldoutExposureRow,
    NodeEvaluationRow,
    NodeRow,
    PolicyBrakeEventRow,
    PolicyDeploymentRow,
    PolicyParentLinkRow,
    PolicyReplayCompletionRow,
    PolicyReplayRoundRow,
    PolicyReplayRunRow,
    PolicyRevisionRow,
    TournamentCandidateRow,
    TournamentCompletionRow,
    TournamentResultRow,
    TournamentRow,
    TournamentWorldRow,
    WorldEventRow,
    WorldRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _world() -> WorldRow:
    return WorldRow(
        world_id="world-1",
        task_family="structural_candidate_audit",
        business_date="2026-09-21",
        lane="jczq",
        strata={"board_size": "small"},
        input_manifest_hash="a" * 64,
        input_manifest={"snapshot": "b" * 64},
        pilot_contract_hash="c" * 64,
        legal_action_schema={"operators": ["stop"]},
        evaluator_revision="structural-candidate-evaluator-v1",
        resource_budget={"max_nodes": 32},
        cutoff_at="2026-09-21T07:00:00+00:00",
        provenance_mode="prospective_online",
        isolated_store_identity="shadow:test",
        root_node_id="node-root",
        created_at="2026-09-21T07:01:00+00:00",
        action_id="a1",
    )


def _event(sequence: int, kind: str) -> WorldEventRow:
    return WorldEventRow(
        world_event_id=f"we-{sequence}",
        world_id="world-1",
        sequence_no=sequence,
        event_kind=kind,
        reason=kind,
        manifest_hash="a" * 64,
        occurred_at=f"2026-09-21T07:0{sequence}:00+00:00",
        action_id="a1",
    )


def _record(cls, **overrides):
    values = {}
    for field in fields(cls):
        name = field.name
        if name in overrides:
            values[name] = overrides[name]
        elif name in {"frontier_eligible", "selectable", "disqualified"}:
            values[name] = False
        elif name in {
            "depth",
            "sibling_order",
            "creation_sequence",
            "revision_no",
            "visibility_sequence",
            "parent_index",
            "round_no",
            "candidate_index",
            "world_index",
            "generation_timeout_seconds",
            "latency_ms",
            "random_seed",
        }:
            values[name] = 1
        elif name.endswith(("_at", "_date", "_boundary")):
            values[name] = "2026-09-21T07:01:00+00:00"
        elif name in {
            "discovery_run_id",
            "parent_node_id",
            "retry_of_node_id",
            "supersedes_evaluation_id",
            "supersedes_deployment_id",
            "rollback_policy_revision_id",
            "generation_trace_hash",
            "winner_policy_revision_id",
            "finished_at",
            "terminal_reason",
            "exclusion_reason",
            "reason",
            "manifest_hash",
        }:
            values[name] = None
        elif name in {
            "world_id",
            "policy_family",
            "family",
            "policy_revision_id",
            "parent_policy_revision_id",
            "incumbent_policy_revision_id",
        }:
            values[name] = {
                "world_id": "world-1",
                "policy_family": "family-1",
                "family": "family-1",
                "policy_revision_id": "policy-1",
                "parent_policy_revision_id": "policy-1",
                "incumbent_policy_revision_id": "policy-1",
            }[name]
        elif name.endswith(
            (
                "_manifest",
                "_schema",
                "_budget",
                "_result",
                "_cost",
                "_descriptors",
                "_configuration",
                "_conditions",
                "_evidence",
            )
        ):
            values[name] = {}
        elif name.endswith(
            ("_refs", "_ids", "_actions", "_surfaces", "_families", "_reasons", "_codes")
        ):
            values[name] = []
        elif name in {
            "stratum_labels",
            "score_vector",
            "scope",
            "decision_contract",
            "aggregate_outcome",
            "random_seed_policy",
            "validation_result",
            "generator_descriptors",
            "generation_input_manifest",
            "generation_budget",
            "generation_cost",
            "max_resource_permissions",
            "change_surfaces",
            "compatible_world_families",
            "novelty_descriptors",
            "tie_policy_revision_ids",
            "disqualification_reasons",
        }:
            values[name] = {}
        else:
            values[name] = "test"
    return cls(**values)


def _store(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def _policy(policy_id: str) -> PolicyRevisionRow:
    return _record(PolicyRevisionRow, policy_revision_id=policy_id)


def _node(node_id: str, sequence: int, **overrides) -> NodeRow:
    return _record(
        NodeRow,
        node_id=node_id,
        creation_sequence=sequence,
        visibility_sequence=overrides.pop("visibility_sequence", sequence),
        **overrides,
    )


def test_world_round_trip_and_projected_state(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_world_event(_event(1, "created"))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world("world-1") == _world()
        assert uow.discovery.world_state("world-1") == "created"
        assert uow.discovery.count_sealed_worlds("structural_candidate_audit") == 0
        assert uow.discovery.counts()["discovery_world_count"] == 1
        uow.discovery.insert_world_event(_event(2, "sealed"))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state("world-1") == "sealed"
        assert uow.discovery.count_sealed_worlds("structural_candidate_audit") == 1
        assert tuple(e.sequence_no for e in uow.discovery.world_events("world-1")) == (1, 2)


def test_duplicate_world_event_sequence_rolls_back(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_world_event(_event(1, "created"))
    with pytest.raises(IntegrityError):
        with OntologyUnitOfWork(engine) as uow:
            uow.discovery.insert_world_event(replace(_event(1, "sealed"), world_event_id="other"))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state("world-1") == "created"


def test_node_and_superseding_evaluation_round_trip(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_policy(_policy("policy-1"))
        uow.discovery.insert_run(_record(DiscoveryRunRow, discovery_run_id="run-1"))
        uow.discovery.insert_node(_node("node-root", 1))
        uow.discovery.insert_node(
            _node("node-child", 2, parent_node_id="node-root", discovery_run_id="run-1")
        )
        first = _record(
            NodeEvaluationRow,
            node_evaluation_id="eval-1",
            node_id="node-child",
            revision_no=1,
            result={"score": 1},
            selectable=True,
        )
        second = _record(
            NodeEvaluationRow,
            node_evaluation_id="eval-2",
            node_id="node-child",
            revision_no=2,
            supersedes_evaluation_id="eval-1",
            result={"score": 2},
            selectable=False,
        )
        uow.discovery.insert_node_evaluation(first)
        uow.discovery.insert_node_evaluation(second)
    with OntologyUnitOfWork(engine) as uow:
        assert [n.node_id for n in uow.discovery.nodes_for_world("world-1")] == [
            "node-root",
            "node-child",
        ]
        assert uow.discovery.latest_node_evaluation("node-child") == second
        assert (
            uow.connection.exec_driver_sql(
                "SELECT count(*) FROM discovery_node_evaluations WHERE node_id='node-child'"
            ).scalar_one()
            == 2
        )


def test_multi_parent_policy_lineage_is_ordered(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        for policy_id in ("policy-1", "policy-2", "policy-3"):
            uow.discovery.insert_policy(_policy(policy_id))
        uow.discovery.insert_policy_parent_link(
            _record(
                PolicyParentLinkRow,
                policy_revision_id="policy-3",
                parent_index=1,
                parent_policy_revision_id="policy-2",
            )
        )
        uow.discovery.insert_policy_parent_link(
            _record(
                PolicyParentLinkRow,
                policy_revision_id="policy-3",
                parent_index=0,
                parent_policy_revision_id="policy-1",
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_parents("policy-3") == ("policy-1", "policy-2")


def test_policy_replay_rounds_and_completion_round_trip(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_policy(_policy("policy-1"))
        envelope = _record(PolicyReplayRunRow, policy_replay_run_id="replay-1")
        uow.discovery.insert_policy_replay(envelope)
        uow.discovery.insert_policy_replay_round(
            _record(
                PolicyReplayRoundRow,
                policy_replay_run_id="replay-1",
                round_no=2,
                revealed_node_ids=["node-child"],
            )
        )
        uow.discovery.insert_policy_replay_round(
            _record(
                PolicyReplayRoundRow,
                policy_replay_run_id="replay-1",
                round_no=1,
                revealed_node_ids=["node-root"],
            )
        )
        completion = _record(
            PolicyReplayCompletionRow, policy_replay_run_id="replay-1", trace_hash="a" * 64
        )
        uow.discovery.insert_policy_replay_completion(completion)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_replay("replay-1") == envelope
        assert [r.round_no for r in uow.discovery.policy_replay_rounds("replay-1")] == [1, 2]
        assert uow.discovery.policy_replay_completion("replay-1") == completion


def test_tournament_graph_round_trip(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_world(replace(_world(), world_id="world-2"))
        uow.discovery.insert_policy(_policy("policy-1"))
        uow.discovery.insert_policy(_policy("policy-2"))
        tournament = _record(TournamentRow, policy_tournament_id="t-1")
        uow.discovery.insert_tournament(tournament)
        for index, policy_id in ((1, "policy-2"), (0, "policy-1")):
            uow.discovery.insert_tournament_candidate(
                _record(
                    TournamentCandidateRow,
                    policy_tournament_id="t-1",
                    candidate_index=index,
                    policy_revision_id=policy_id,
                )
            )
        for index, world_id in ((1, "world-2"), (0, "world-1")):
            uow.discovery.insert_tournament_world(
                _record(
                    TournamentWorldRow,
                    policy_tournament_id="t-1",
                    world_index=index,
                    world_id=world_id,
                )
            )
        for policy_id in ("policy-1", "policy-2"):
            for world_id in ("world-1", "world-2"):
                uow.discovery.insert_tournament_result(
                    _record(
                        TournamentResultRow,
                        policy_tournament_id="t-1",
                        policy_revision_id=policy_id,
                        world_id=world_id,
                    )
                )
        uow.discovery.insert_tournament_completion(
            _record(
                TournamentCompletionRow,
                policy_tournament_id="t-1",
                winner_policy_revision_id="policy-1",
            )
        )
        uow.discovery.insert_archive_decision(
            _record(
                ArchiveDecisionRow,
                archive_decision_id="archive-1",
                policy_tournament_id="t-1",
                policy_revision_id="policy-2",
                disposition="stepping_stone",
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament("t-1") == tournament
        assert [p.policy_revision_id for p in uow.discovery.tournament_candidates("t-1")] == [
            "policy-1",
            "policy-2",
        ]
        assert [w.world_id for w in uow.discovery.tournament_worlds("t-1")] == [
            "world-1",
            "world-2",
        ]
        assert len(uow.discovery.tournament_results("t-1")) == 4
        assert uow.discovery.tournament_completion("t-1").winner_policy_revision_id == "policy-1"
        assert uow.discovery.latest_archive_decision("policy-2").disposition == "stepping_stone"


def test_archive_and_holdout_exposure_round_trip(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_policy(_policy("policy-1"))
        uow.discovery.insert_tournament(_record(TournamentRow, policy_tournament_id="t-1"))
        exposure = _record(
            HoldoutExposureRow, holdout_exposure_id="h-1", policy_tournament_id="t-1"
        )
        uow.discovery.insert_holdout_exposure(exposure)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.exposed_holdouts("family-1") == (exposure,)
        assert uow.discovery.policy("policy-1") == _policy("policy-1")


def test_deployment_and_brake_round_trip(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy(_policy("policy-1"))
        uow.discovery.insert_policy(_policy("policy-2"))
        deployed = _record(
            PolicyDeploymentRow,
            policy_deployment_id="deployment-1",
            policy_revision_id="policy-2",
            rollback_policy_revision_id="policy-1",
            decision="deploy",
        )
        uow.discovery.insert_deployment(deployed)
        brake = _record(
            PolicyBrakeEventRow,
            policy_brake_event_id="brake-1",
            policy_deployment_id="deployment-1",
            tripped_policy_revision_id="policy-2",
            restored_policy_revision_id="policy-1",
        )
        uow.discovery.insert_brake(brake)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.latest_deployment("family-1") == deployed
        assert uow.discovery.latest_brake("deployment-1") == brake


def test_duplicate_ordinals_are_rejected(tmp_path):
    engine = _store(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_policy(_policy("policy-1"))
        uow.discovery.insert_run(_record(DiscoveryRunRow, discovery_run_id="run-1"))
        uow.discovery.insert_node(_node("node-root", 1))
        uow.discovery.insert_policy_replay(_record(PolicyReplayRunRow, policy_replay_run_id="r-1"))
        uow.discovery.insert_tournament(_record(TournamentRow, policy_tournament_id="t-1"))
        uow.discovery.insert_tournament_candidate(
            _record(TournamentCandidateRow, policy_tournament_id="t-1", candidate_index=0)
        )
    duplicates = (
        lambda d: d.insert_node(_node("other", 1)),
        lambda d: d.insert_node(_node("other", 2, visibility_sequence=1)),
        lambda d: d.insert_policy_replay_round(
            _record(PolicyReplayRoundRow, policy_replay_run_id="r-1", round_no=1)
        ),
        lambda d: d.insert_tournament_candidate(
            _record(TournamentCandidateRow, policy_tournament_id="t-1", candidate_index=0)
        ),
    )
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy_replay_round(
            _record(PolicyReplayRoundRow, policy_replay_run_id="r-1", round_no=1)
        )
    for attempt in duplicates:
        with pytest.raises(IntegrityError):
            with OntologyUnitOfWork(engine) as uow:
                attempt(uow.discovery)
    with OntologyUnitOfWork(engine) as uow:
        assert [n.node_id for n in uow.discovery.nodes_for_world("world-1")] == ["node-root"]
        assert len(uow.discovery.policy_replay_rounds("r-1")) == 1
