"""Governed, separately metered generation of unregistered policy proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, select

from nutmeg.discovery.baseline_variants import load_policy_artifact
from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.generation_contracts import (
    DevelopmentWorld,
    EligibleParent,
    GenerationContext,
)
from nutmeg.discovery.generator_baseline import generate_baselines
from nutmeg.discovery.generator_evolution import generate_evolution
from nutmeg.discovery.readiness import ReadinessReport
from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    RecordPolicyGenerationRoundRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.repository import schema_discovery as sd
from nutmeg.ontology.repository.discovery import DiscoveryRepository, PolicyGenerationRoundRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    round_id: str
    candidate_hashes: tuple[str, ...]
    blocking_metrics: tuple[str, ...]
    status: str


def parent_parameters(
    policy, repository: DiscoveryRepository
) -> tuple[tuple[str, ...], int] | None:
    round_id = policy.generator_descriptors.get("generation_round_id")
    if round_id:
        round_row = repository.generation_round(round_id)
        if round_row is None:
            return None
        source = next(
            (
                item
                for item in round_row.trace["proposals"]
                if item.get("policy_revision_id") == policy.policy_revision_id
                and canonical_hash(item) == policy.source_artifact_hash
            ),
            None,
        )
        if source is None:
            return None
        artifact = load_policy_artifact(source)
        program = artifact.program if hasattr(artifact, "program") else artifact
        return program.template_order, program.batch_limit
    config = policy.configuration
    order = tuple(config.get("template_order", ()))
    return (order, int(config.get("batch_limit", 1)))


class GenerationService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pilot = load_pilot_contract(
            Path(__file__).resolve().parents[2]
            / "experiments/discovery/structural-candidate-v1.contract.json"
        )

    def _context(
        self,
        *,
        family: str,
        seed: int,
        candidate_cap: int,
        compute_budget: int,
        timeout_seconds: int,
        development_cutoff: str | None,
    ) -> GenerationContext:
        with self.engine.connect() as connection:
            repo = DiscoveryRepository(connection)
            worlds = []
            template_ids = set()
            ids = connection.execute(
                select(sd.discovery_worlds.c.world_id).order_by(sd.discovery_worlds.c.world_id)
            ).scalars()
            for world_id in ids:
                world = repo.world(world_id)
                if (
                    development_cutoff is None
                    or world.cutoff_at > development_cutoff
                    or repo.world_state(world_id) != "sealed"
                ):
                    continue
                events = repo.world_events(world_id)
                if not events or events[-1].event_kind != "sealed":
                    continue
                from nutmeg.discovery.sealed_tree import SealedTree

                nodes = repo.nodes_for_world(world_id)
                try:
                    SealedTree.from_rows(
                        world,
                        nodes,
                        events,
                        {
                            node.node_id: evaluation
                            for node in nodes
                            if (evaluation := repo.latest_node_evaluation(node.node_id)) is not None
                        },
                    )
                except ValueError:
                    continue
                worlds.append(
                    DevelopmentWorld(
                        world_id=world_id,
                        seal_hash=events[-1].manifest_hash,
                        pool_role="development",
                        provenance_mode=world.provenance_mode,
                        sealed=True,
                        diagnostic_codes=tuple(
                            sorted({code for node in nodes for code in node.diagnostic_codes})
                        ),
                    )
                )
                template_ids.update(world.input_manifest.get("template_ids", ()))
            parents = []
            policies = connection.execute(
                select(sd.exploration_policy_revisions.c.policy_revision_id).order_by(
                    sd.exploration_policy_revisions.c.policy_revision_id
                )
            ).scalars()
            lineage_counts: dict[str, int] = {}
            for policy_id in policies:
                policy = repo.policy(policy_id)
                archive = repo.latest_archive_decision(policy_id)
                disposition = archive.disposition if archive else None
                if policy_id == "structural-baseline-v1":
                    disposition = "incumbent"
                if disposition not in {
                    "incumbent",
                    "stepping_stone",
                } or not policy.validation_result.get("valid"):
                    continue
                root = repo.policy_parents(policy_id)
                root_id = root[0] if root else policy_id
                if (
                    lineage_counts.get(root_id, 0) >= self.pilot.archive.max_per_lineage
                    or len(parents) >= self.pilot.archive.capacity
                ):
                    continue
                parameters = parent_parameters(policy, repo)
                if parameters is None:
                    continue
                order, batch_limit = parameters
                if not order:
                    order = tuple(sorted(template_ids))
                if not order:
                    continue
                parents.append(
                    EligibleParent(
                        policy_revision_id=policy_id,
                        disposition=disposition,
                        lineage_root=root_id,
                        template_order=order,
                        batch_limit=batch_limit,
                    )
                )
                lineage_counts[root_id] = lineage_counts.get(root_id, 0) + 1
        return GenerationContext(
            schema_version="1",
            generator_revision="baseline-v1" if family == "baseline" else "bounded-evolution-v1",
            constraint_revision="structural-candidate-v1",
            development_worlds=tuple(worlds),
            eligible_parents=tuple(parents),
            template_ids=tuple(sorted(template_ids)),
            seed=seed,
            candidate_cap=candidate_cap,
            compute_budget=compute_budget,
            timeout_seconds=timeout_seconds,
        )

    def generate(
        self,
        family: str,
        *,
        round_id: str,
        seed: int,
        candidate_cap: int = 4,
        compute_budget: int = 8,
        timeout_seconds: int = 10,
        development_cutoff: str | None = None,
        requested_at: datetime | None = None,
    ) -> GenerationOutcome:
        if family not in {"baseline", "bounded_evolution"}:
            raise ValueError("unsupported generator family")
        if seed < 0 or min(candidate_cap, compute_budget, timeout_seconds) < 1:
            raise ValueError("generation budget and seed must be valid")
        if (
            candidate_cap > self.pilot.budgets.max_candidate_generation_count
            or timeout_seconds > self.pilot.budgets.max_wall_seconds
        ):
            raise ValueError("generation exceeds frozen pilot budget")
        # The gate runs before reading development input or invoking a generator.
        report: ReadinessReport = DiscoveryReadService(self.engine).readiness()
        metrics = report.metrics if family == "baseline" else report.optimizer_metrics
        blockers = tuple(sorted(key for key, metric in metrics.items() if metric.status != "pass"))
        enabled = report.mode in (
            {"baseline_comparison", "optimizer_eligible"}
            if family == "baseline"
            else {"optimizer_eligible"}
        )
        context = None
        if enabled and not blockers:
            if development_cutoff is None:
                blockers = ("development_cutoff",)
            else:
                context = self._context(
                    family=family,
                    seed=seed,
                    candidate_cap=candidate_cap,
                    compute_budget=compute_budget,
                    timeout_seconds=timeout_seconds,
                    development_cutoff=development_cutoff,
                )
        revision = "baseline-v1" if family == "baseline" else "bounded-evolution-v1"
        manifest = {
            "development_worlds": (
                [
                    {"world_id": item.world_id, "seal_hash": item.seal_hash}
                    for item in context.development_worlds
                ]
                if context
                else []
            ),
            "eligible_parent_ids": (
                [item.policy_revision_id for item in context.eligible_parents] if context else []
            ),
            "generator_revision": revision,
            "constraint_revision": "structural-candidate-v1",
            "development_cutoff": development_cutoff,
            "seed": seed,
            "candidate_cap": candidate_cap,
            "compute_budget": compute_budget,
            "timeout_seconds": timeout_seconds,
        }
        manifest_hash = canonical_hash(manifest)
        if context is None:
            blockers = blockers or ("readiness_mode",)
            proposals, attempts, status, cost = (), (), "blocked", {"attempts": 0}
        elif family == "baseline":
            generated = generate_baselines(
                context.template_ids,
                seed=seed,
                candidate_cap=candidate_cap,
                attempt_budget=compute_budget,
                timeout_seconds=timeout_seconds,
            )
            proposals, attempts, status, cost = (
                generated.proposals,
                generated.attempts,
                generated.status,
                generated.cost,
            )
        else:
            generated = generate_evolution(context, report)
            proposals, attempts, status, cost = (
                generated.proposals,
                generated.attempts,
                generated.status,
                generated.cost,
            )
            blockers = generated.blocking_metrics
        trace = {
            "attempts": list(attempts),
            "proposals": [item.model_dump(mode="json") for item in proposals],
        }
        hashes = [canonical_hash(item) for item in trace["proposals"]]
        row = PolicyGenerationRoundRow(
            generation_round_id=round_id,
            generator_family=family,
            generator_revision=revision,
            generator_artifact_hash=canonical_hash({"revision": revision}),
            input_manifest_hash=manifest_hash,
            input_manifest=manifest,
            eligible_parent_ids=manifest["eligible_parent_ids"],
            seed=seed,
            candidate_cap=candidate_cap,
            compute_budget=compute_budget,
            timeout_seconds=timeout_seconds,
            generation_cost=cost,
            status=status,
            candidate_hashes=hashes,
            trace=trace,
            trace_hash=canonical_hash(trace),
            blocking_metrics=list(blockers),
            created_at=(requested_at or datetime.now(UTC)).isoformat(),
            action_id="pending",
        )
        action = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(self.engine)))
        outcome = action.record_generation_round(
            RecordPolicyGenerationRoundRequest(
                row,
                "sys:discovery-generator",
                ActorRole.DETERMINISTIC_SYSTEM,
                f"generation:{round_id}",
                requested_at or datetime.now(UTC),
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("generation receipt did not commit")
        return GenerationOutcome(round_id, tuple(hashes), tuple(blockers), status)
