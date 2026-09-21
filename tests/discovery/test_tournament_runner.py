from __future__ import annotations

from pathlib import Path

from nutmeg.discovery.contracts import load_baseline_policy, load_pilot_contract
from nutmeg.discovery.online_recorder import record_shadow_world
from nutmeg.discovery.tournament_runner import (
    ensure_registered_replays,
    finish_frozen_tournament,
    prepare_tournament,
)
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_online_adapter import _snapshot
from tests.discovery.test_online_recorder import _rig as _online_rig
from tests.discovery.test_replay_runner import T0
from tests.ontology.test_discovery_governance_actions import _create_request, _rig, _seed

ROOT = Path(__file__).resolve().parents[2]


def test_explicit_replay_preparation_persists_missing_cells_once(tmp_path):
    engine = _online_rig(tmp_path)
    pilot = load_pilot_contract(
        ROOT / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    policy = load_baseline_policy(ROOT / "experiments/discovery/structural-baseline-v1.policy.json")
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id=policy.policy_revision_id,
        requested_at=T0,
        fixture_only=True,
    )
    first = ensure_registered_replays(
        engine, (recorded.world_id,), (policy,), pilot, seed=7, requested_at=T0
    )
    second = ensure_registered_replays(
        engine, (recorded.world_id,), (policy,), pilot, seed=7, requested_at=T0
    )
    assert first == second
    assert len(first) == 1
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_replay_completion(first[0].policy_replay_run_id)


def test_frozen_tournament_preparation_reproduces_matrix_and_proof(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    assert actions.create_tournament(_create_request()).status is ActionStatus.COMMITTED

    first = prepare_tournament(engine, "t-1")
    second = prepare_tournament(engine, "t-1")
    assert first == second
    assert len(first.results) == 60
    assert first.winner_policy_revision_id == "policy-1"

    outcome = finish_frozen_tournament(engine, "t-1", requested_at=_create_request().requested_at)
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1").reproduction_hash == first.proof_hash
        assert [row.world_id for row in uow.discovery.exposed_holdouts("family-1")] == ["world-2"]
