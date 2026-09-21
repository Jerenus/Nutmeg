"""Prospective evidence checks; replay outcomes never count as shadow samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.discovery.models import canonical_hash


def protected_receipt(before_hash: str, after_hash: str, world_id: str,
                      policy_revision_id: str) -> dict[str, str]:
    body = {"schema_version": "1", "before_hash": before_hash, "after_hash": after_hash,
            "world_id": world_id, "policy_revision_id": policy_revision_id}
    return {**body, "receipt_hash": canonical_hash(body)}


def valid_protected_receipt(receipt: object, world_id: str, policy_revision_id: str) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema_version", "before_hash", "after_hash", "world_id", "policy_revision_id",
        "receipt_hash",
    }:
        return False
    before = receipt["before_hash"]
    return (isinstance(before, str) and len(before) == 64
            and all(char in "0123456789abcdef" for char in before)
            and receipt == protected_receipt(before, before, world_id, policy_revision_id))


@dataclass(frozen=True)
class ShadowEligibility:
    eligible_for_canary: bool
    blocking_codes: tuple[str, ...]
    effective_world_count: int


def evaluate_shadow_window(
    window, tournament, sealed_worlds, *, now: datetime, excluded_world_ids=(),
    policy_revision_id: str | None = None, receipts: dict | None = None
) -> ShadowEligibility:
    start = datetime.fromisoformat(window.start_at)
    end = datetime.fromisoformat(window.end_at)
    cutoff = datetime.fromisoformat(tournament.holdout_cutoff_at)
    if any(value.tzinfo is None for value in (start, end, cutoff, now)) or not cutoff < start < end:
        raise ValueError("shadow window requires ordered timezone-aware cutoffs")
    seen = set()
    count = 0
    missing_receipt = False
    duplicates = False
    out_of_window = False
    for world in sealed_worlds:
        instant = datetime.fromisoformat(world.cutoff_at)
        manifest = world.input_manifest
        identity = (manifest.get("task_snapshot_hash"), manifest.get("slate_revision_id"))
        if (world.world_id in excluded_world_ids or getattr(world, "sealed", True) is not True
            or instant.tzinfo is None
            or not start <= instant <= end or world.provenance_mode != "prospective_online"
            or not all(identity)):
            out_of_window = True
            continue
        if identity in seen:
            duplicates = True
            continue
        receipt = (
            (receipts or {}).get(world.world_id)
            if receipts is not None else manifest.get("protected_receipt")
        )
        expected_policy = policy_revision_id or (
            receipt.get("policy_revision_id", "") if isinstance(receipt, dict) else ""
        )
        if not valid_protected_receipt(receipt, world.world_id, expected_policy):
            missing_receipt = True
            continue
        seen.add(identity)
        count += 1
    blocked = []
    if now <= end:
        blocked.append("window_open")
    if count < window.minimum_independent_worlds:
        blocked.append("fresh_prospective_world")
    if missing_receipt:
        blocked.append("protected_receipt")
    if duplicates:
        blocked.append("duplicate_derivative_world")
    if out_of_window:
        blocked.append("nonprospective_or_out_of_window_world")
    return ShadowEligibility(not blocked, tuple(blocked), count)
