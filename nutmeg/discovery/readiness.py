"""Deterministic coverage report; no optimization or policy authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nutmeg.discovery.contracts import ReadinessContract, ReadinessThreshold


@dataclass(frozen=True, slots=True)
class CoverageWorld:
    world_id: str
    business_date: str
    task_snapshot_hash: str
    slate_revision_id: str
    strata: tuple[str, ...]
    sealed: bool
    manifest_complete: bool
    alternative_count: int
    failed_or_degraded: bool


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    integrity_proven: bool
    action_overlap: float | None
    branch_unavailable_rate: float | None


@dataclass(frozen=True, slots=True)
class Metric:
    status: str
    observed: int | float | None
    required: int | float


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    mode: str
    metrics: dict[str, Metric]
    optimizer_metrics: dict[str, Metric]
    blocking_reasons: tuple[str, ...]


def _checks(
    worlds: tuple[CoverageWorld, ...],
    effective: tuple[CoverageWorld, ...],
    threshold: ReadinessThreshold,
    required_strata: tuple[str, ...],
    replay: ReplayMetrics | None,
) -> dict[str, Metric]:
    def minimum(observed: int | float, required: int | float) -> Metric:
        return Metric("pass" if observed >= required else "fail", observed, required)

    def maximum(observed: int | float | None, required: float) -> Metric:
        if observed is None:
            return Metric("unknown", None, required)
        return Metric("pass" if observed <= required else "fail", observed, required)

    size = len(effective)
    complete = sum(world.manifest_complete for world in worlds) / len(worlds) if worlds else 0.0
    alternatives = sum(world.alternative_count >= 2 for world in effective) / size if size else 0.0
    stratum_min = min(
        (sum(stratum in world.strata for world in effective) for stratum in required_strata),
        default=0,
    )
    replay_valid = replay is not None and replay.integrity_proven
    return {
        "replay_integrity": (
            Metric("pass" if replay_valid else "fail", int(replay_valid), 1)
            if replay is not None
            else Metric("unknown", None, 1)
        ),
        "sealed_worlds": minimum(len(worlds), threshold.min_sealed_worlds),
        "independent_business_dates": minimum(
            len({world.business_date for world in effective}),
            threshold.min_independent_business_dates,
        ),
        "effective_sample_size": minimum(size, threshold.min_effective_sample_size),
        "manifest_completeness": minimum(complete, threshold.min_manifest_completeness),
        "multi_alternative_fraction": minimum(
            alternatives, threshold.min_multi_alternative_fraction
        ),
        "failed_or_degraded_worlds": minimum(
            sum(world.failed_or_degraded for world in effective),
            threshold.min_failed_or_degraded_worlds,
        ),
        "worlds_per_required_stratum": minimum(
            stratum_min, threshold.min_worlds_per_required_stratum
        ),
        "action_overlap": (
            minimum(replay.action_overlap, threshold.min_action_overlap)
            if replay_valid and replay.action_overlap is not None
            else Metric("unknown", None, threshold.min_action_overlap)
        ),
        "branch_unavailable_rate": maximum(
            replay.branch_unavailable_rate if replay_valid else None,
            threshold.max_branch_unavailable_rate,
        ),
    }


def assess_readiness(
    worlds: tuple[CoverageWorld, ...],
    contract: ReadinessContract,
    replay_metrics: ReplayMetrics | None = None,
) -> ReadinessReport:
    sealed = tuple(world for world in worlds if world.sealed)
    clusters: dict[tuple[str, str, str], CoverageWorld] = {}
    for world in sorted(sealed, key=lambda item: item.world_id):
        key = (world.business_date, world.task_snapshot_hash, world.slate_revision_id)
        clusters.setdefault(key, world)
    effective = tuple(clusters.values())
    baseline = _checks(
        sealed, effective, contract.record_to_baseline, contract.required_strata, replay_metrics
    )
    optimizer = _checks(
        sealed,
        effective,
        contract.baseline_to_optimizer,
        contract.required_strata,
        replay_metrics,
    )
    baseline_blockers = tuple(
        sorted(key for key, metric in baseline.items() if metric.status != "pass")
    )
    optimizer_blockers = tuple(
        sorted(key for key, metric in optimizer.items() if metric.status != "pass")
    )
    if baseline_blockers:
        return ReadinessReport("record_only", baseline, optimizer, baseline_blockers)
    if optimizer_blockers:
        return ReadinessReport("baseline_comparison", baseline, optimizer, optimizer_blockers)
    return ReadinessReport("optimizer_eligible", baseline, optimizer, ())
