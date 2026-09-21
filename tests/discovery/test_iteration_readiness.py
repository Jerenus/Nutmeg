from dataclasses import replace

from nutmeg.discovery.iteration_readiness import review_new_information
from nutmeg.discovery.readiness import CoverageWorld, ReadinessReport, ReplayMetrics


def world(world_id, date="2026-09-01", snapshot="snapshot", strata=("small",)):
    return CoverageWorld(world_id, date, snapshot, "slate", strata, True, True, 2, False)


def test_duplicate_and_derivative_worlds_do_not_increase_effective_count():
    previous = (world("old"),)
    incoming = (world("duplicate"), world("other", "2026-09-02"))
    report = review_new_information(previous, incoming, min_clusters=2)
    assert report.raw_new_worlds == 2
    assert report.effective_new_clusters == 1
    assert report.duplicate_world_ids == ("duplicate",)
    assert not report.ready_for_operator_tournament_request


def test_distinct_signals_and_fail_closed_replay_and_optimizer():
    previous = (world("old"),)
    incoming = (replace(world("new", "2026-09-02", strata=("large",)), failed_or_degraded=True),)
    report = review_new_information(
        previous,
        incoming,
        min_clusters=1,
        previous_actions=("a",),
        new_actions=("a", "b"),
        replay=ReplayMetrics(True, 0.8, 0.0),
        readiness=ReadinessReport("baseline_comparison", {}, {}, ("optimizer",)),
    )
    assert report.added_actions == ("b",)
    assert report.added_failures == 1
    assert report.stratum_changes == (("large", 1),)
    assert not report.ready_for_operator_tournament_request


def test_unapproved_contract_never_authorizes_runtime_round():
    report = review_new_information(
        (),
        (world("new"),),
        min_clusters=1,
        replay=ReplayMetrics(True, 0.8, 0.0),
        readiness=ReadinessReport("optimizer_eligible", {}, {}, ()),
    )
    assert report.trigger_conditions_met
    assert not report.ready_for_operator_tournament_request
    assert "contract_unapproved" in report.blocking_reasons


def test_caller_cannot_assert_contract_approval():
    import pytest

    with pytest.raises(TypeError, match="contract_approved"):
        review_new_information((), (), min_clusters=1, contract_approved=True)


def test_information_does_not_override_minimum_round_interval():
    report = review_new_information(
        (),
        (world("new"),),
        min_clusters=1,
        previous_completed_at="2026-09-21T12:00:00+00:00",
        reviewed_at="2026-09-22T12:00:00+00:00",
        min_days_between_rounds=2,
    )
    assert report.trigger_conditions_met is False
    assert "minimum_round_interval" in report.blocking_reasons


def test_missing_cluster_identity_cannot_count_as_information():
    report = review_new_information((), (world("missing", snapshot=""),), min_clusters=1)
    assert report.effective_new_clusters == 0
    assert "sealed_manifest_validity" in report.blocking_reasons


def test_new_action_signal_can_trigger_only_with_independent_cluster():
    old = (world("old"),)
    independent = (world("new", date="2026-09-02"),)
    kwargs = {
        "min_clusters": 3,
        "min_action_coverage_delta": 1,
        "previous_actions": ("a",),
        "new_actions": ("a", "b"),
    }
    assert review_new_information(old, independent, **kwargs).trigger_conditions_met
    assert not review_new_information(old, (world("duplicate"),), **kwargs).trigger_conditions_met


def test_duplicate_action_cannot_piggyback_on_other_effective_cluster():
    old = (world("old"),)
    report = review_new_information(
        old,
        (world("fresh", date="2026-09-02"), world("duplicate")),
        min_clusters=3,
        min_action_coverage_delta=1,
        previous_actions=("a",),
        new_actions=("a", "b"),
        action_worlds={"fresh": ("a",), "duplicate": ("b",)},
    )
    assert report.added_actions == ()
    assert not report.trigger_conditions_met
