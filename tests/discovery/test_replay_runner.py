from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import load_baseline_policy, load_pilot_contract
from nutmeg.discovery.online_recorder import _source_fingerprint, record_shadow_world
from nutmeg.discovery.replay_runner import run_online_baseline, run_registered_replay
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_online_adapter import _snapshot
from tests.discovery.test_online_recorder import _rig

ROOT = Path(__file__).resolve().parents[2]
PILOT = load_pilot_contract(ROOT / "experiments/discovery/structural-candidate-v1.contract.json")
POLICY = load_baseline_policy(ROOT / "experiments/discovery/structural-baseline-v1.policy.json")
T0 = datetime(2026, 9, 21, 7, 1, tzinfo=UTC)


def test_registered_baseline_replay_persists_and_reproduces_isolated_trace(tmp_path):
    engine = _rig(tmp_path)
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id=POLICY.policy_revision_id,
        requested_at=T0,
        fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        before = (
            uow.discovery.world(recorded.world_id),
            uow.discovery.nodes_for_world(recorded.world_id),
        )
    business_before = _source_fingerprint(tmp_path / "business.db")
    first = run_registered_replay(engine, recorded.world_id, POLICY, PILOT, seed=7, requested_at=T0)
    second = run_registered_replay(
        engine, recorded.world_id, POLICY, PILOT, seed=7, requested_at=T0
    )
    assert first.trace_hash == second.trace_hash
    assert first.selected_node_ids == second.selected_node_ids
    assert _source_fingerprint(tmp_path / "business.db") == business_before
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.discovery.policy_replay_rounds(first.policy_replay_run_id)) == 1
        assert (
            uow.discovery.policy_replay_completion(first.policy_replay_run_id).trace_hash
            == first.trace_hash
        )
        assert (
            uow.discovery.world(recorded.world_id),
            uow.discovery.nodes_for_world(recorded.world_id),
        ) == before


def test_runner_rejects_unregistered_policy_before_start(tmp_path):
    engine = _rig(tmp_path)

    invalid = POLICY.model_copy(update={"policy_revision_id": "other"})
    with pytest.raises(ValueError, match="registered|sealed"):
        run_registered_replay(engine, "missing", invalid, PILOT, seed=7, requested_at=T0)


def test_program_interpreter_uses_only_visible_observation_and_stops_at_threshold():
    from nutmeg.discovery.environment import ContinueBatch, Observation, RevealedNode, Stop
    from nutmeg.discovery.generation_contracts import PolicyProgramArtifact
    from nutmeg.discovery.replay_runner import policy_decision
    from tests.discovery.test_generation_contracts import _document

    policy = PolicyProgramArtifact.model_validate(_document())
    observation = Observation(
        world_id="w",
        visible_node_ids=("root",),
        frontier_node_ids=("root",),
        selectable_node_ids=(),
        legal_template_ids=("2x1",),
        remaining_rounds=2,
        remaining_nodes=1,
        max_concurrency=1,
    )
    first = policy_decision(policy, 1, observation)
    assert isinstance(first, ContinueBatch)
    assert [item.template_ids for item in first.items] == [("2x1",)]
    later = replace(
        observation,
        selectable_node_ids=("n",),
        revealed_nodes=(RevealedNode("n", "complete", (("band", "0.9"),), "a" * 64, (), ()),),
    )
    assert isinstance(policy_decision(policy, 1, later), Stop)


def test_registered_program_replays_sealed_fixture_without_live_work(tmp_path):
    from nutmeg.discovery.generation_contracts import EligibleParent
    from nutmeg.discovery.generator_evolution import generate_evolution
    from nutmeg.ontology.actions.discovery_policy_actions import (
        DiscoveryPolicyActions,
        RecordPolicyGenerationRoundRequest,
        RegisterPolicyRevisionRequest,
    )
    from nutmeg.ontology.actions.models import ActionStatus, ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.discovery.models import canonical_hash
    from tests.discovery.test_generator_evolution import _context, _ready
    from tests.ontology.test_discovery_generation_actions import _round

    engine = _rig(tmp_path)
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id=POLICY.policy_revision_id,
        requested_at=T0,
        fixture_only=True,
    )
    context = _context().model_copy(
        update={
            "eligible_parents": (
                EligibleParent(
                    policy_revision_id=POLICY.policy_revision_id,
                    disposition="incumbent",
                    lineage_root=POLICY.policy_revision_id,
                    template_order=("1x1", "2x1"),
                    batch_limit=1,
                ),
            )
        }
    )
    proposal = generate_evolution(context, _ready()).proposals[0]
    with pytest.raises(ValueError, match="registered"):
        run_registered_replay(engine, recorded.world_id, proposal, PILOT, seed=7, requested_at=T0)
    artifact = proposal.model_dump(mode="json")
    manifest = {
        "development_worlds": [],
        "eligible_parent_ids": [POLICY.policy_revision_id],
        "generator_revision": "bounded-evolution-v1",
    }
    trace = {
        "attempts": [{"policy_revision_id": proposal.policy_revision_id, "status": "proposed"}],
        "proposals": [artifact],
    }
    round_row = replace(
        _round(),
        generator_family="bounded_evolution",
        generator_revision="bounded-evolution-v1",
        generator_artifact_hash=canonical_hash({"revision": "bounded-evolution-v1"}),
        input_manifest=manifest,
        input_manifest_hash=canonical_hash(manifest),
        eligible_parent_ids=[POLICY.policy_revision_id],
        status="complete",
        candidate_hashes=[canonical_hash(artifact)],
        trace=trace,
        trace_hash=canonical_hash(trace),
        generation_cost={"attempts": 1},
    )
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    assert (
        actions.record_generation_round(
            RecordPolicyGenerationRoundRequest(
                round_row,
                "sys:generator",
                ActorRole.DETERMINISTIC_SYSTEM,
                "program:round",
                T0,
            )
        ).status
        is ActionStatus.COMMITTED
    )
    with OntologyUnitOfWork(engine) as uow:
        incumbent = uow.discovery.policy(POLICY.policy_revision_id)
    child = replace(
        incumbent,
        policy_revision_id=proposal.policy_revision_id,
        source_artifact_hash=canonical_hash(artifact),
        generator_family="bounded_evolution",
        generator_revision="bounded-evolution-v1",
        generation_input_manifest_hash=round_row.input_manifest_hash,
        generation_trace_hash=round_row.trace_hash,
        generation_cost=round_row.generation_cost,
        generator_descriptors={"generation_round_id": round_row.generation_round_id},
    )
    assert (
        actions.register_policy(
            RegisterPolicyRevisionRequest(
                child,
                artifact,
                (POLICY.policy_revision_id,),
                "op:jun",
                ActorRole.JUDGE_OPERATOR,
                "program:register",
                T0,
            )
        ).status
        is ActionStatus.COMMITTED
    )
    first = run_registered_replay(
        engine, recorded.world_id, proposal, PILOT, seed=7, requested_at=T0
    )
    second = run_registered_replay(
        engine, recorded.world_id, proposal, PILOT, seed=7, requested_at=T0
    )
    assert first.trace_hash == second.trace_hash


def test_same_baseline_policy_operates_online_and_replay(tmp_path):
    engine = _rig(tmp_path)
    online = run_online_baseline(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy=POLICY,
        requested_at=T0,
        fixture_only=True,
    )
    replay = run_registered_replay(engine, online.world_id, POLICY, PILOT, seed=7, requested_at=T0)
    assert online.selected_node_ids == replay.selected_node_ids
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state(online.world_id) == "sealed"


def test_runner_replays_d2_linked_retry_without_synthesizing_branch(tmp_path, monkeypatch):
    from nutmeg.discovery.online_adapter import ShardExecution
    from nutmeg.ontology.discovery.models import canonical_hash

    engine = _rig(tmp_path)
    calls = []

    def flaky(_snapshot, template_ids, **_kwargs):
        calls.append(template_ids)
        failed = len(calls) == 1
        payload = {"status": "failed" if failed else "no_solution"}
        digest = canonical_hash(payload)
        return ShardExecution(
            template_ids=template_ids,
            status=payload["status"],
            artifact_manifest={**payload, "content_hash": digest},
            artifact_hash=digest,
            diagnostic_codes=("adapter_crash",) if failed else ("no_feasible_candidate",),
            resource_cost={"wall_ms": 1, "candidate_generation_count": 0},
            evaluation=None if failed else {},
            selectable=False,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder.execute_template_shard", flaky)
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id=POLICY.policy_revision_id,
        requested_at=T0,
        fixture_only=True,
    )
    assert len(calls) == 2
    result = run_registered_replay(
        engine, recorded.world_id, POLICY, PILOT, seed=7, requested_at=T0
    )
    with OntologyUnitOfWork(engine) as uow:
        rounds = uow.discovery.policy_replay_rounds(result.policy_replay_run_id)
        completion = uow.discovery.policy_replay_completion(result.policy_replay_run_id)
    assert len(rounds[0].revealed_node_ids) == 2
    assert completion.budget_used["attempts"] == 2
    assert completion.budget_used["candidate_generation_count"] == 0
