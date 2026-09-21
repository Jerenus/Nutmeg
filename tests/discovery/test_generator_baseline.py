from __future__ import annotations

from nutmeg.discovery.generator_baseline import generate_baselines


def test_baseline_seed_manifest_and_cap_reproduce_ordered_hashes():
    first = generate_baselines(("1x1", "2x1", "3x1"), seed=7, candidate_cap=2, attempt_budget=3)
    second = generate_baselines(("1x1", "2x1", "3x1"), seed=7, candidate_cap=2, attempt_budget=3)
    assert first == second
    assert len(first.proposals) == 2
    assert first.status == "truncated"
    assert first.cost == {"attempts": 2}
    assert all(item.generator_family == "baseline" for item in first.proposals)
    assert all(item.policy_revision_id != "structural-baseline-v1" for item in first.proposals)


def test_baseline_budget_and_timeout_are_explicit():
    result = generate_baselines(("1x1", "2x1"), seed=2, candidate_cap=4, attempt_budget=1)
    assert result.status == "truncated"
    assert result.cost == {"attempts": 1}
    timeout = generate_baselines(
        ("1x1", "2x1"), seed=2, candidate_cap=4, attempt_budget=4, timeout_seconds=0
    )
    assert timeout.status == "timeout"
    assert timeout.proposals == ()
    assert timeout.cost == {"attempts": 0}


def test_baseline_stops_at_real_deadline_and_charges_completed_attempts(monkeypatch):
    import nutmeg.discovery.generator_baseline as generator_module

    ticks = iter((0.0, 0.1, 1.1))
    monkeypatch.setattr(generator_module, "monotonic", lambda: next(ticks), raising=False)
    result = generate_baselines(
        ("1x1", "2x1", "3x1"),
        seed=0,
        candidate_cap=4,
        attempt_budget=4,
        timeout_seconds=1,
    )
    assert result.status == "timeout"
    assert result.cost == {"attempts": 1}
