from __future__ import annotations

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
