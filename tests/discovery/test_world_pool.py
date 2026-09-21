from __future__ import annotations

from dataclasses import replace

import pytest

from nutmeg.discovery.world_pool import WorldPoolInput, freeze_world_pool


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
