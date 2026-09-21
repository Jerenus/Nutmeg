"""Immutable time-forward role validation over append-only exposure facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Exposure:
    world_id: str
    cluster_key: tuple[str, str, str]
    cutoff_at: str
    prior_holdout_cutoff_at: str | None = None


@dataclass(frozen=True, slots=True)
class RotationWorld:
    world_id: str
    cluster_key: tuple[str, str, str]
    cutoff_at: str
    role: str
    sealed: bool


def validate_rotation(
    exposures: tuple[Exposure, ...],
    worlds: tuple[RotationWorld, ...],
    *,
    generator_world_ids: tuple[str, ...] = (),
    generator_cluster_keys: tuple[tuple[str, str, str], ...] = (),
) -> None:
    exposed_ids = {item.world_id for item in exposures}
    exposed_clusters = {item.cluster_key for item in exposures}
    holdouts = tuple(item for item in worlds if item.role == "holdout")
    for item in holdouts:
        if item.world_id in generator_world_ids or item.cluster_key in generator_cluster_keys:
            raise ValueError("hidden holdout was shared with generator input")
        if item.world_id in exposed_ids or item.cluster_key in exposed_clusters:
            raise ValueError("exposed world or derivative cannot become hidden holdout")
    for item in worlds:
        if item.role != "development" or (
            item.world_id not in exposed_ids and item.cluster_key not in exposed_clusters
        ):
            continue
        prior = [
            fact
            for fact in exposures
            if fact.world_id == item.world_id or fact.cluster_key == item.cluster_key
        ]
        if not any(
            candidate.sealed
            and candidate.cluster_key != item.cluster_key
            and candidate.cluster_key not in exposed_clusters
            and datetime.fromisoformat(candidate.cutoff_at) > datetime.fromisoformat(item.cutoff_at)
            and all(
                datetime.fromisoformat(candidate.cutoff_at)
                > datetime.fromisoformat(fact.prior_holdout_cutoff_at or fact.cutoff_at)
                for fact in prior
            )
            for candidate in holdouts
        ):
            raise ValueError("exposed development requires strictly newer sealed hidden holdout")
