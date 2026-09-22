"""Pure time-forward world-pool freezing for discovery tournaments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.discovery.contracts import PilotContract
from nutmeg.ontology.discovery.models import canonical_hash


@dataclass(frozen=True, slots=True)
class WorldPoolInput:
    world_id: str
    business_date: str
    cutoff_at: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_family: str
    evaluator_revision: str
    strata: tuple[str, ...]
    sealed: bool
    manifest_valid: bool
    failed_or_no_solution: bool


@dataclass(frozen=True, slots=True)
class FrozenWorld:
    world_id: str
    pool_role: str
    cluster_key: tuple[str, str, str]
    strata: tuple[str, ...]
    failed_or_no_solution: bool


@dataclass(frozen=True, slots=True)
class FrozenWorldPool:
    worlds: tuple[FrozenWorld, ...]
    exclusions: tuple[tuple[str, str], ...]
    effective_cluster_count: int
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class WorldReadinessFacts:
    world_id: str
    distinct_legal_continuations: int
    incumbent_replay_available: bool
    requested_continuations: int
    unavailable_continuations: int


@dataclass(frozen=True, slots=True)
class BaselineReadinessReport:
    ready: bool
    reasons: tuple[str, ...]
    metrics: dict[str, object]


def assess_baseline_readiness(
    pool: FrozenWorldPool,
    facts: tuple[WorldReadinessFacts, ...],
    pilot: PilotContract,
) -> BaselineReadinessReport:
    """Record-to-baseline gate over a frozen pool.

    Delegates to the single readiness computation in `nutmeg.discovery.readiness`
    so the tournament Action and the operator projection cannot disagree. Fails
    closed: a missing incumbent replay or zero requested continuations leaves the
    replay metrics unknown, and unknown never passes.
    """
    from nutmeg.discovery.readiness import CoverageWorld, ReplayMetrics, assess_readiness

    if len(facts) != len(pool.worlds) or {item.world_id for item in facts} != {
        world.world_id for world in pool.worlds
    }:
        raise ValueError("readiness facts must cover every frozen world exactly once")
    if any(
        item.distinct_legal_continuations < 0
        or item.requested_continuations < 0
        or not 0 <= item.unavailable_continuations <= item.requested_continuations
        for item in facts
    ):
        raise ValueError("readiness counts must be nonnegative and consistent")
    facts_by_id = {item.world_id: item for item in facts}
    coverage = tuple(
        CoverageWorld(
            world_id=world.world_id,
            business_date=world.cluster_key[0],
            task_snapshot_hash=world.cluster_key[1],
            slate_revision_id=world.cluster_key[2],
            strata=world.strata,
            sealed=True,
            manifest_complete=True,
            alternative_count=facts_by_id[world.world_id].distinct_legal_continuations,
            failed_or_degraded=world.failed_or_no_solution,
        )
        for world in pool.worlds
    )
    requested = sum(item.requested_continuations for item in facts)
    unavailable = sum(item.unavailable_continuations for item in facts)
    replay = ReplayMetrics(
        integrity_proven=all(item.incumbent_replay_available for item in facts),
        action_overlap=(requested - unavailable) / requested if requested else None,
        branch_unavailable_rate=unavailable / requested if requested else None,
    )
    report = assess_readiness(coverage, pilot.readiness, replay)
    reasons = tuple(
        sorted(key for key, metric in report.metrics.items() if metric.status != "pass")
    )
    return BaselineReadinessReport(not reasons, reasons, dict(report.metrics))


def freeze_world_pool(
    worlds: tuple[WorldPoolInput, ...],
    *,
    development_cutoff: str,
    holdout_cutoff: str,
    required_strata: tuple[str, ...],
    exposed_holdout_ids: tuple[str, ...] = (),
    exposed_cluster_keys: tuple[tuple[str, str, str], ...] = (),
) -> FrozenWorldPool:
    development_at = datetime.fromisoformat(development_cutoff)
    holdout_at = datetime.fromisoformat(holdout_cutoff)
    if development_at >= holdout_at:
        raise ValueError("holdout cutoff must be strictly later than development cutoff")
    if not worlds:
        raise ValueError("world pool is empty")
    if any(not world.sealed for world in worlds):
        raise ValueError("world pool requires sealed worlds")
    if any(not world.manifest_valid for world in worlds):
        raise ValueError("world pool requires manifest-valid worlds")
    if any(
        world.task_family != "structural_candidate_audit"
        or world.evaluator_revision != "structural-candidate-evaluator-v1"
        for world in worlds
    ):
        raise ValueError("world family or evaluator is incompatible")

    selected: list[FrozenWorld] = []
    exclusions: list[tuple[str, str]] = []
    clusters: set[tuple[str, str, str]] = set()
    exposed = set(exposed_holdout_ids)
    for world in sorted(worlds, key=lambda item: item.world_id):
        cutoff = datetime.fromisoformat(world.cutoff_at)
        if cutoff <= development_at:
            role = "development"
        elif cutoff <= holdout_at:
            role = "holdout"
        else:
            exclusions.append((world.world_id, "after_holdout_cutoff"))
            continue
        cluster = (
            world.business_date,
            world.task_snapshot_hash,
            world.slate_revision_id,
        )
        if role == "holdout" and world.world_id in exposed:
            raise ValueError("exposed holdout cannot be reused as hidden holdout")
        if role == "holdout" and cluster in exposed_cluster_keys:
            raise ValueError("exposed holdout cluster cannot be reused under another world ID")
        if cluster in clusters:
            exclusions.append((world.world_id, "duplicate_cluster"))
            continue
        clusters.add(cluster)
        selected.append(
            FrozenWorld(
                world_id=world.world_id,
                pool_role=role,
                cluster_key=cluster,
                strata=tuple(sorted(world.strata)),
                failed_or_no_solution=world.failed_or_no_solution,
            )
        )

    roles = {world.pool_role for world in selected}
    if "development" not in roles or "holdout" not in roles:
        raise ValueError("world pool requires development and holdout worlds")
    present_strata = {stratum for world in selected for stratum in world.strata}
    if any(stratum not in present_strata for stratum in required_strata):
        raise ValueError("world pool is missing required strata")
    frozen = tuple(sorted(selected, key=lambda item: (item.pool_role, item.world_id)))
    payload = [
        {
            "world_id": item.world_id,
            "pool_role": item.pool_role,
            "cluster_key": list(item.cluster_key),
            "strata": list(item.strata),
            "failed_or_no_solution": item.failed_or_no_solution,
        }
        for item in frozen
    ]
    return FrozenWorldPool(
        worlds=frozen,
        exclusions=tuple(sorted(exclusions)),
        effective_cluster_count=len(frozen),
        manifest_hash=canonical_hash(payload),
    )
