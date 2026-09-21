from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.readiness import CoverageWorld, ReplayMetrics, assess_readiness

PILOT = load_pilot_contract(
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _worlds(count):
    return tuple(
        CoverageWorld(
            world_id=f"world-{i}",
            business_date=f"2026-08-{i + 1:02d}",
            task_snapshot_hash=f"task-{i}",
            slate_revision_id=f"slate-{i}",
            strata=("board_size:small", "board_size:medium", "board_size:large"),
            sealed=True,
            manifest_complete=True,
            alternative_count=2,
            failed_or_degraded=False,
        )
        for i in range(count)
    )


def test_empty_pool_is_record_only_with_explicit_reasons():
    report = assess_readiness((), PILOT.readiness)
    assert report.mode == "record_only"
    assert report.metrics["sealed_worlds"].observed == 0
    assert "sealed_worlds" in report.blocking_reasons


def test_threshold_counts_do_not_invent_missing_replay_measurements():
    report = assess_readiness(_worlds(30), PILOT.readiness)
    assert report.mode == "record_only"
    assert report.metrics["sealed_worlds"].status == "pass"
    assert report.metrics["branch_unavailable_rate"].status == "unknown"
    assert report.metrics["replay_integrity"].status == "unknown"
    assert "branch_unavailable_rate" in report.blocking_reasons


def test_optimizer_counts_still_need_overlap_and_branch_measurements():
    report = assess_readiness(_worlds(60), PILOT.readiness)
    assert report.mode == "record_only"
    assert report.metrics["effective_sample_size"].observed == 60
    assert report.metrics["action_overlap"].status == "unknown"


def test_duplicate_cluster_counts_once_for_effective_sample():
    worlds = _worlds(30)
    duplicate = replace(worlds[0], world_id="duplicate-world")
    report = assess_readiness((*worlds, duplicate), PILOT.readiness)
    assert report.metrics["sealed_worlds"].observed == 31
    assert report.metrics["effective_sample_size"].observed == 30


def test_missing_stratum_and_incomplete_manifest_block_optimizer():
    worlds = tuple(replace(world, strata=("board_size:small",)) for world in _worlds(60))
    worlds = (replace(worlds[0], manifest_complete=False), *worlds[1:])
    report = assess_readiness(worlds, PILOT.readiness)
    assert report.optimizer_metrics["manifest_completeness"].status == "fail"
    assert report.optimizer_metrics["worlds_per_required_stratum"].status == "fail"


def test_proven_replay_metrics_allow_baseline_but_not_early_optimizer():
    report = assess_readiness(
        _worlds(30), PILOT.readiness,
        replay_metrics=ReplayMetrics(
            integrity_proven=True, action_overlap=0.2, branch_unavailable_rate=0.1
        ),
    )
    assert report.mode == "baseline_comparison"
    assert "sealed_worlds" in report.blocking_reasons


def test_optimizer_gate_requires_failed_world_coverage_even_with_60_sealed():
    worlds = _worlds(60)
    replay = ReplayMetrics(
        integrity_proven=True, action_overlap=0.8, branch_unavailable_rate=0.1
    )
    assert assess_readiness(worlds, PILOT.readiness, replay).mode == "baseline_comparison"
    eligible = tuple(
        replace(world, failed_or_degraded=index < 3)
        for index, world in enumerate(worlds)
    )
    report = assess_readiness(eligible, PILOT.readiness, replay)
    assert report.mode == "optimizer_eligible"
    assert report.blocking_reasons == ()
