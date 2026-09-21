from datetime import UTC, datetime
from types import SimpleNamespace

from nutmeg.discovery.promotion_evidence import evaluate_shadow_window


def test_replay_winner_without_new_sealed_shadow_cannot_promote():
    window = SimpleNamespace(
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-23T00:00:00+00:00",
        minimum_independent_worlds=1,
    )
    result = evaluate_shadow_window(
        window,
        SimpleNamespace(holdout_cutoff_at="2026-09-21T00:00:00+00:00"),
        sealed_worlds=(),
        now=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert result.eligible_for_canary is False
    assert "fresh_prospective_world" in result.blocking_codes


def test_open_window_cannot_promote_even_with_world():
    window = SimpleNamespace(
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-25T00:00:00+00:00",
        minimum_independent_worlds=1,
    )
    world = SimpleNamespace(
        world_id="w1",
        cutoff_at="2026-09-23T00:00:00+00:00",
        provenance_mode="prospective_online",
        input_manifest={"task_snapshot_hash": "a"},
    )
    result = evaluate_shadow_window(
        window,
        SimpleNamespace(holdout_cutoff_at="2026-09-21T00:00:00+00:00"),
        sealed_worlds=(world,),
        now=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert "window_open" in result.blocking_codes


def test_duplicate_derivative_and_replay_worlds_do_not_inflate_count():
    window = SimpleNamespace(
        start_at="2026-09-22T00:00:00+00:00",
        end_at="2026-09-25T00:00:00+00:00",
        minimum_independent_worlds=2,
    )
    world = SimpleNamespace(
        world_id="w1",
        cutoff_at="2026-09-23T00:00:00+00:00",
        provenance_mode="prospective_online",
        input_manifest={"task_snapshot_hash": "same", "slate_revision_id": "s1"},
    )
    duplicate = SimpleNamespace(
        world_id="w2",
        cutoff_at="2026-09-24T00:00:00+00:00",
        provenance_mode="prospective_online",
        input_manifest=world.input_manifest,
    )
    replay = SimpleNamespace(
        world_id="w3",
        cutoff_at="2026-09-24T00:00:00+00:00",
        provenance_mode="historical_replay_source",
        input_manifest={"task_snapshot_hash": "new", "slate_revision_id": "s2"},
    )
    result = evaluate_shadow_window(
        window,
        SimpleNamespace(holdout_cutoff_at="2026-09-21T00:00:00+00:00"),
        sealed_worlds=(world, duplicate, replay),
        now=datetime(2026, 9, 26, tzinfo=UTC),
    )
    assert result.effective_world_count == 1
    assert "fresh_prospective_world" in result.blocking_codes
