"""Read-only D7 information projection, never an Action authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from nutmeg.discovery.readiness import CoverageWorld, ReadinessReport, ReplayMetrics


@dataclass(frozen=True, slots=True)
class InformationReport:
    raw_new_worlds: int
    effective_new_clusters: int
    duplicate_world_ids: tuple[str, ...]
    added_actions: tuple[str, ...]
    added_failures: int
    stratum_changes: tuple[tuple[str, int], ...]
    trigger_conditions_met: bool
    ready_for_operator_tournament_request: bool
    blocking_reasons: tuple[str, ...]


def review_new_information(
    previous: tuple[CoverageWorld, ...],
    incoming: tuple[CoverageWorld, ...],
    *,
    min_clusters: int,
    previous_actions: tuple[str, ...] = (),
    new_actions: tuple[str, ...] = (),
    action_worlds: dict[str, tuple[str, ...]] | None = None,
    min_action_coverage_delta: int | None = None,
    min_failure_case_delta: int | None = None,
    min_stratum_count_delta: int | None = None,
    replay: ReplayMetrics | None = None,
    readiness: ReadinessReport | None = None,
    previous_completed_at: str | None = None,
    reviewed_at: str | None = None,
    min_days_between_rounds: int = 0,
) -> InformationReport:
    if (
        min_clusters < 1
        or min_days_between_rounds < 0
        or any(
            item is not None and item < 1
            for item in (min_action_coverage_delta, min_failure_case_delta, min_stratum_count_delta)
        )
    ):
        raise ValueError("effective information threshold must be positive")

    def cluster(world: CoverageWorld) -> tuple[str, str, str]:
        return world.business_date, world.task_snapshot_hash, world.slate_revision_id

    seen = {cluster(item) for item in previous if item.sealed and item.manifest_complete}
    effective: list[CoverageWorld] = []
    duplicates: list[str] = []
    eligible = sorted(
        (
            item
            for item in incoming
            if item.sealed and item.manifest_complete and all(cluster(item))
        ),
        key=lambda item: item.world_id,
    )
    for item in eligible:
        if cluster(item) in seen:
            duplicates.append(item.world_id)
        else:
            effective.append(item)
            seen.add(cluster(item))
    old_strata = {label for item in previous for label in item.strata}
    strata = tuple(
        sorted(
            (label, sum(label in item.strata for item in effective))
            for label in {label for item in effective for label in item.strata} - old_strata
        )
    )
    effective_actions = (
        {action for item in effective for action in action_worlds.get(item.world_id, ())}
        if action_worlds is not None
        else set(new_actions)
    )
    added_actions = tuple(sorted(effective_actions - set(previous_actions)))
    failures = sum(item.failed_or_degraded for item in effective)
    triggered = (
        len(effective) >= min_clusters
        or bool(effective)
        and any(
            (
                min_action_coverage_delta is not None
                and len(added_actions) >= min_action_coverage_delta,
                min_failure_case_delta is not None and failures >= min_failure_case_delta,
                min_stratum_count_delta is not None
                and any(count >= min_stratum_count_delta for _, count in strata),
            )
        )
    )
    reasons = []
    if not triggered:
        reasons.append("effective_new_clusters")
    if previous_completed_at is not None:
        if reviewed_at is None:
            raise ValueError("review timestamp required for round interval")
        previous_at = datetime.fromisoformat(previous_completed_at)
        reviewed = datetime.fromisoformat(reviewed_at)
        if previous_at.tzinfo is None or reviewed.tzinfo is None:
            raise ValueError("round interval requires timezone-aware timestamps")
        if reviewed < previous_at + timedelta(days=min_days_between_rounds):
            reasons.append("minimum_round_interval")
            triggered = False
    if len(eligible) != len(incoming):
        reasons.append("sealed_manifest_validity")
    if (
        replay is None
        or not replay.integrity_proven
        or (replay.action_overlap is None or replay.branch_unavailable_rate is None)
    ):
        reasons.append("replay_integrity_or_coverage")
    if (
        readiness is None
        or readiness.mode != "optimizer_eligible"
        or (any(metric.status != "pass" for metric in readiness.optimizer_metrics.values()))
    ):
        reasons.append("optimizer_coverage")
    reasons.append("contract_unapproved")
    return InformationReport(
        len(incoming),
        len(effective),
        tuple(duplicates),
        added_actions,
        failures,
        strata,
        triggered,
        not reasons,
        tuple(reasons),
    )
