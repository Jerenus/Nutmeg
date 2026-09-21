"""Enumerated, bounded D4-compatible baseline proposals."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from time import monotonic

from nutmeg.discovery.baseline_variants import (
    DeterministicBaselineVariantArtifact,
    variant_policy_revision_id,
)


@dataclass(frozen=True, slots=True)
class BaselineGeneration:
    proposals: tuple[DeterministicBaselineVariantArtifact, ...]
    attempts: tuple[dict[str, object], ...]
    status: str
    cost: dict[str, int]


def generate_baselines(
    template_ids: tuple[str, ...],
    *,
    seed: int,
    candidate_cap: int,
    attempt_budget: int,
    timeout_seconds: int = 10,
) -> BaselineGeneration:
    if seed < 0 or candidate_cap < 1 or attempt_budget < 1:
        raise ValueError("generation caps and seed must be valid")
    if len(set(template_ids)) != len(template_ids) or not template_ids:
        raise ValueError("template vocabulary must be nonempty and unique")
    if timeout_seconds <= 0:
        return BaselineGeneration((), (), "timeout", {"attempts": 0})
    deadline = monotonic() + timeout_seconds
    proposals = []
    attempts = []
    seen = set()
    # The seed rotates only the enumerated starting priority; it never changes the grammar.
    ordered = tuple(sorted(template_ids))
    ordered = ordered[seed % len(ordered) :] + ordered[: seed % len(ordered)]
    variants = permutations(ordered)
    limit = min(candidate_cap, attempt_budget)
    expired = False
    for order in variants:
        if len(attempts) >= limit:
            break
        if monotonic() >= deadline:
            expired = True
            break
        body = {
            "schema_version": "1",
            "family": "structural_candidate_exploration",
            "interface_version": "discovery-policy-v1",
            "constraints_version": "structural-candidate-v1",
            "generator_family": "baseline",
            "change_surfaces": ["exploration_policy"],
            "random_seed_policy": {"kind": "none", "deterministic": True},
            "compatible_world_families": ["structural_candidate_audit"],
            "template_order": list(order),
            "batch_limit": min(len(order), 2),
            "stop_selector": "best_audit_clean_node_per_band",
            "rationale": "Deterministic template priority baseline.",
        }
        artifact = DeterministicBaselineVariantArtifact.model_validate(
            {"policy_revision_id": variant_policy_revision_id(body), **body}
        )
        digest = artifact.policy_revision_id
        if digest not in seen:
            proposals.append(artifact)
            seen.add(digest)
        attempts.append({"policy_revision_id": digest, "status": "proposed"})
    total = 1
    for n in range(2, len(ordered) + 1):
        total *= n
    return BaselineGeneration(
        tuple(proposals),
        tuple(attempts),
        "timeout" if expired else "truncated" if len(attempts) < total else "complete",
        {"attempts": len(attempts)},
    )
