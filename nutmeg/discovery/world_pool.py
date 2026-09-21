"""Pure time-forward world-pool freezing for discovery tournaments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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


def freeze_world_pool(
    worlds: tuple[WorldPoolInput, ...],
    *,
    development_cutoff: str,
    holdout_cutoff: str,
    required_strata: tuple[str, ...],
    exposed_holdout_ids: tuple[str, ...] = (),
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
        if role == "holdout" and world.world_id in exposed:
            raise ValueError("exposed holdout cannot be reused as hidden holdout")
        cluster = (
            world.business_date,
            world.task_snapshot_hash,
            world.slate_revision_id,
        )
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
