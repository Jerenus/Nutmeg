"""Prospective evidence checks; replay outcomes never count as shadow samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ShadowEligibility:
    eligible_for_canary: bool
    blocking_codes: tuple[str, ...]
    effective_world_count: int


def evaluate_shadow_window(
    window, tournament, sealed_worlds, *, now: datetime, excluded_world_ids=()
) -> ShadowEligibility:
    start = datetime.fromisoformat(window.start_at)
    end = datetime.fromisoformat(window.end_at)
    cutoff = datetime.fromisoformat(tournament.holdout_cutoff_at)
    if any(value.tzinfo is None for value in (start, end, cutoff, now)) or not cutoff < start < end:
        raise ValueError("shadow window requires ordered timezone-aware cutoffs")
    seen = set()
    count = 0
    for world in sealed_worlds:
        instant = datetime.fromisoformat(world.cutoff_at)
        manifest = world.input_manifest
        identity = (manifest.get("task_snapshot_hash"), manifest.get("slate_revision_id"))
        if (
            world.world_id in excluded_world_ids
            or instant.tzinfo is None
            or not start <= instant <= end
            or world.provenance_mode != "prospective_online"
            or not all(identity)
            or identity in seen
        ):
            continue
        seen.add(identity)
        count += 1
    blocked = []
    if now <= end:
        blocked.append("window_open")
    if count < window.minimum_independent_worlds:
        blocked.append("fresh_prospective_world")
    return ShadowEligibility(not blocked, tuple(blocked), count)
