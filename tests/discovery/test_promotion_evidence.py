from datetime import UTC, datetime
from types import SimpleNamespace

from nutmeg.discovery.promotion_evidence import evaluate_shadow_window, protected_receipt


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
    world.input_manifest["protected_receipt"] = protected_receipt(
        "a" * 64, "a" * 64, "w1", "candidate"
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


def test_missing_or_altered_protected_receipt_blocks_eligibility():
    from nutmeg.discovery.promotion_evidence import protected_receipt

    window = SimpleNamespace(start_at="2026-09-22T00:00:00+00:00",
                             end_at="2026-09-25T00:00:00+00:00",
                             minimum_independent_worlds=1)
    world = SimpleNamespace(world_id="w1", cutoff_at="2026-09-23T00:00:00+00:00",
                            provenance_mode="prospective_online",
                            input_manifest={"task_snapshot_hash": "a", "slate_revision_id": "s"})
    result = evaluate_shadow_window(window, SimpleNamespace(
        holdout_cutoff_at="2026-09-21T00:00:00+00:00"), (world,),
        now=datetime(2026, 9, 26, tzinfo=UTC))
    assert not result.eligible_for_canary
    assert "protected_receipt" in result.blocking_codes
    receipt = protected_receipt("a" * 64, "a" * 64, "w1", "candidate")
    world.input_manifest["protected_receipt"] = receipt
    assert evaluate_shadow_window(window, SimpleNamespace(
        holdout_cutoff_at="2026-09-21T00:00:00+00:00"), (world,),
        now=datetime(2026, 9, 26, tzinfo=UTC), policy_revision_id="candidate").eligible_for_canary
    receipt["after_hash"] = "b" * 64
    assert not evaluate_shadow_window(window, SimpleNamespace(
        holdout_cutoff_at="2026-09-21T00:00:00+00:00"), (world,),
        now=datetime(2026, 9, 26, tzinfo=UTC), policy_revision_id="candidate").eligible_for_canary


def test_duplicate_receipt_world_blocks_even_when_minimum_count_met():
    from nutmeg.discovery.promotion_evidence import protected_receipt

    window = SimpleNamespace(start_at="2026-09-22T00:00:00+00:00",
                             end_at="2026-09-25T00:00:00+00:00",
                             minimum_independent_worlds=1)
    worlds = []
    for identifier in ("w1", "w2"):
        worlds.append(SimpleNamespace(
            world_id=identifier, cutoff_at="2026-09-23T00:00:00+00:00",
            provenance_mode="prospective_online",
            input_manifest={"task_snapshot_hash": "same", "slate_revision_id": "s",
                            "protected_receipt": protected_receipt(
                                "a" * 64, "a" * 64, identifier, "candidate"
                            )},
        ))
    result = evaluate_shadow_window(window, SimpleNamespace(
        holdout_cutoff_at="2026-09-21T00:00:00+00:00"), worlds,
        now=datetime(2026, 9, 26, tzinfo=UTC), policy_revision_id="candidate")
    assert not result.eligible_for_canary
    assert "duplicate_derivative_world" in result.blocking_codes


def test_late_tournament_replay_and_unsealed_worlds_are_not_promotion_evidence():
    from nutmeg.discovery.promotion_evidence import protected_receipt

    window = SimpleNamespace(start_at="2026-09-22T00:00:00+00:00",
                             end_at="2026-09-25T00:00:00+00:00",
                             minimum_independent_worlds=1)
    world = SimpleNamespace(
        world_id="w1", cutoff_at="2026-09-23T00:00:00+00:00",
        provenance_mode="prospective_online", sealed=True,
        input_manifest={"task_snapshot_hash": "unique", "slate_revision_id": "s",
                        "protected_receipt": protected_receipt("a" * 64, "a" * 64,
                                                                 "w1", "candidate")},
    )
    tournament = SimpleNamespace(holdout_cutoff_at="2026-09-21T00:00:00+00:00")
    for altered, excluded in (
        (world, ("w1",)),
        (SimpleNamespace(**{**vars(world), "sealed": False}), ()),
        (SimpleNamespace(**{**vars(world), "provenance_mode": "historical_replay_source"}), ()),
        (SimpleNamespace(**{**vars(world), "cutoff_at": "2026-09-26T00:00:00+00:00"}), ()),
    ):
        result = evaluate_shadow_window(window, tournament, (altered,),
            now=datetime(2026, 9, 26, tzinfo=UTC), policy_revision_id="candidate",
            excluded_world_ids=excluded)
        assert not result.eligible_for_canary
