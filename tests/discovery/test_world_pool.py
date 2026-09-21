from __future__ import annotations

from dataclasses import replace

import pytest

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.world_pool import (
    WorldPoolInput,
    WorldReadinessFacts,
    assess_baseline_readiness,
    freeze_world_pool,
)

PILOT = load_pilot_contract(
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _world(world_id: str, day: int, **changes) -> WorldPoolInput:
    world = WorldPoolInput(
        world_id=world_id,
        business_date=f"2026-09-{day:02d}",
        cutoff_at=f"2026-09-{day:02d}T07:00:00+00:00",
        task_snapshot_hash=f"snapshot-{day}",
        slate_revision_id=f"slate-{day}",
        task_family="structural_candidate_audit",
        evaluator_revision="structural-candidate-evaluator-v1",
        strata=(f"board_size:{'small' if day % 2 else 'medium'}",),
        sealed=True,
        manifest_valid=True,
        failed_or_no_solution=False,
    )
    return replace(world, **changes)


def test_freeze_world_pool_is_time_forward_and_weights_duplicate_cluster_once():
    development = _world("dev-a", 10)
    duplicate = replace(development, world_id="dev-b")
    holdout = _world("holdout", 21)

    pool = freeze_world_pool(
        (duplicate, holdout, development),
        development_cutoff="2026-09-15T23:59:59+00:00",
        holdout_cutoff="2026-09-21T23:59:59+00:00",
        required_strata=("board_size:small", "board_size:medium"),
    )

    assert tuple(item.world_id for item in pool.worlds) == ("dev-a", "holdout")
    assert tuple(item.pool_role for item in pool.worlds) == ("development", "holdout")
    assert pool.effective_cluster_count == 2
    assert pool.exclusions == (("dev-b", "duplicate_cluster"),)


def test_freeze_world_pool_rejects_unsealed_invalid_or_exposed_holdout():
    for changed, reason in (
        ({"sealed": False}, "sealed"),
        ({"manifest_valid": False}, "manifest"),
    ):
        with pytest.raises(ValueError, match=reason):
            freeze_world_pool(
                (_world("dev", 10, **changed), _world("holdout", 21)),
                development_cutoff="2026-09-15T23:59:59+00:00",
                holdout_cutoff="2026-09-21T23:59:59+00:00",
                required_strata=("board_size:small", "board_size:medium"),
            )

    with pytest.raises(ValueError, match="exposed"):
        freeze_world_pool(
            (_world("dev", 10), _world("holdout", 21)),
            development_cutoff="2026-09-15T23:59:59+00:00",
            holdout_cutoff="2026-09-21T23:59:59+00:00",
            required_strata=("board_size:small", "board_size:medium"),
            exposed_holdout_ids=("holdout",),
        )


def test_freeze_world_pool_retains_failed_worlds_and_requires_strata_and_roles():
    pool = freeze_world_pool(
        (
            _world("failed-dev", 10, failed_or_no_solution=True),
            _world("holdout", 21),
        ),
        development_cutoff="2026-09-15T23:59:59+00:00",
        holdout_cutoff="2026-09-21T23:59:59+00:00",
        required_strata=("board_size:small", "board_size:medium"),
    )
    assert pool.worlds[0].failed_or_no_solution is True

    with pytest.raises(ValueError, match="strata"):
        freeze_world_pool(
            (_world("dev", 10), _world("holdout", 21, strata=("board_size:small",))),
            development_cutoff="2026-09-15T23:59:59+00:00",
            holdout_cutoff="2026-09-21T23:59:59+00:00",
            required_strata=("board_size:large",),
        )

    with pytest.raises(ValueError, match="holdout"):
        freeze_world_pool(
            (_world("dev", 10),),
            development_cutoff="2026-09-15T23:59:59+00:00",
            holdout_cutoff="2026-09-21T23:59:59+00:00",
            required_strata=("board_size:small",),
        )


def test_freeze_world_pool_rejects_incompatible_family_or_evaluator():
    with pytest.raises(ValueError, match="family|evaluator"):
        freeze_world_pool(
            (
                _world("dev", 10),
                _world("holdout", 21, evaluator_revision="other"),
            ),
            development_cutoff="2026-09-15T23:59:59+00:00",
            holdout_cutoff="2026-09-21T23:59:59+00:00",
            required_strata=("board_size:small", "board_size:medium"),
        )


def test_exposed_holdout_cluster_cannot_return_under_a_new_world_id():
    exposed_cluster = ("2026-09-21", "snapshot-21", "slate-21")
    with pytest.raises(ValueError, match="exposed.*cluster"):
        freeze_world_pool(
            (_world("dev", 10), _world("new-world-id", 21)),
            development_cutoff="2026-09-15T23:59:59+00:00",
            holdout_cutoff="2026-09-21T23:59:59+00:00",
            required_strata=("board_size:small", "board_size:medium"),
            exposed_cluster_keys=(exposed_cluster,),
        )


def test_record_to_baseline_readiness_requires_effective_dates_and_replay():
    worlds = tuple(
        _world(
            f"world-{day}",
            day,
            strata=(f"board_size:{('small', 'medium', 'large')[day % 3]}",),
        )
        for day in range(1, 31)
    )
    pool = freeze_world_pool(
        worlds,
        development_cutoff="2026-09-20T23:59:59+00:00",
        holdout_cutoff="2026-09-30T23:59:59+00:00",
        required_strata=PILOT.readiness.required_strata,
    )
    facts = tuple(
        WorldReadinessFacts(
            world_id=world.world_id,
            distinct_legal_continuations=2,
            incumbent_replay_available=True,
            requested_continuations=2,
            unavailable_continuations=0,
        )
        for world in pool.worlds
    )

    assert assess_baseline_readiness(pool, facts, PILOT).ready is True
    missing_replay = (*facts[:-1], replace(facts[-1], incumbent_replay_available=False))
    report = assess_baseline_readiness(pool, missing_replay, PILOT)
    assert report.ready is False
    assert "incumbent_replay_missing" in report.reasons


def test_record_to_baseline_readiness_cannot_count_duplicate_dates_as_independent():
    worlds = (
        _world("dev", 10),
        _world("holdout", 21),
    )
    pool = freeze_world_pool(
        worlds,
        development_cutoff="2026-09-15T23:59:59+00:00",
        holdout_cutoff="2026-09-21T23:59:59+00:00",
        required_strata=("board_size:small", "board_size:medium"),
    )
    facts = tuple(WorldReadinessFacts(w.world_id, 2, True, 1, 0) for w in pool.worlds)
    report = assess_baseline_readiness(pool, facts, PILOT)
    assert report.ready is False
    assert "sealed_world_count" in report.reasons
    assert "independent_business_dates" in report.reasons
