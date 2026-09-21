"""Seeded mutation of validated parent policies, gated at the direct API."""

from __future__ import annotations

import random
from dataclasses import dataclass
from time import monotonic

from nutmeg.discovery.generation_contracts import (
    GenerationContext,
    PolicyProgramArtifact,
    program_policy_revision_id,
)
from nutmeg.discovery.readiness import ReadinessReport


@dataclass(frozen=True, slots=True)
class EvolutionGeneration:
    proposals: tuple[PolicyProgramArtifact, ...]
    attempts: tuple[dict[str, object], ...]
    status: str
    cost: dict[str, int]
    blocking_metrics: tuple[str, ...]


def generate_evolution(context: GenerationContext, report: ReadinessReport) -> EvolutionGeneration:
    blockers = tuple(
        sorted(k for k, metric in report.optimizer_metrics.items() if metric.status != "pass")
    )
    if report.mode != "optimizer_eligible" or blockers:
        return EvolutionGeneration(
            (), (), "blocked", {"attempts": 0}, blockers or ("optimizer_readiness",)
        )
    if context.generator_revision != "bounded-evolution-v1":
        raise ValueError("unsupported generator revision")
    if not context.eligible_parents:
        return EvolutionGeneration((), (), "blocked", {"attempts": 0}, ("eligible_parents",))
    rng = random.Random(context.seed)
    deadline = monotonic() + context.timeout_seconds
    parents = context.eligible_parents
    proposals = []
    attempts = []
    seen = set()
    limit = min(context.candidate_cap, context.compute_budget)
    expired = False
    for index in range(limit):
        if monotonic() >= deadline:
            expired = True
            break
        parent = parents[index % len(parents)]
        order = tuple(item for item in parent.template_order if item in context.template_ids)
        if not order:
            attempts.append({"parent": parent.policy_revision_id, "status": "incompatible"})
            continue
        order = order[index % len(order) :] + order[: index % len(order)]
        if len(order) > 1 and rng.randrange(2):
            order = tuple(reversed(order))
        body = {
            "schema_version": "1",
            "family": "structural_candidate_exploration",
            "interface_version": "discovery-policy-v1",
            "constraints_version": "structural-candidate-v1",
            "generator_family": "bounded_evolution",
            "generator_revision": context.generator_revision,
            "parent_policy_revision_ids": [parent.policy_revision_id],
            "seed": context.seed,
            "change_surfaces": ["exploration_policy"],
            "descriptor_set": ["allocation", "batch", "priority", "stop"],
            "program": {
                "template_order": list(order),
                "batch_limit": min(len(order), max(1, parent.batch_limit + (index % 2))),
                "budget_allocation": "frontier_first" if index % 2 == 0 else "quality_first",
                "stop_quality_threshold": str(index % 2),
            },
        }
        proposal = PolicyProgramArtifact.model_validate(
            {"policy_revision_id": program_policy_revision_id(body), **body}
        )
        if proposal.policy_revision_id not in seen:
            proposals.append(proposal)
            seen.add(proposal.policy_revision_id)
            status = "proposed"
        else:
            status = "duplicate"
        attempts.append(
            {
                "parent": parent.policy_revision_id,
                "policy_revision_id": proposal.policy_revision_id,
                "status": status,
            }
        )
    return EvolutionGeneration(
        tuple(proposals),
        tuple(attempts),
        "timeout" if expired else "truncated",
        {"attempts": len(attempts)},
        (),
    )
