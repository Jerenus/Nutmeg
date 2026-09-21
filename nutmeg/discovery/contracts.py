from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nutmeg.ontology.actions.models import canonical_json


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowBinding(FrozenContract):
    generator: Literal[
        "nutmeg.product.operator_candidates:enumerate_band_candidates"
    ]
    candidate_set_kind: Literal["judgment_bound"]
    generator_version: Literal["operator-candidate-v2-bands"]
    audit_policy_source: Literal["candidate_set.audit_policy_version"]


class OperatorSpec(FrozenContract):
    name: Literal["enumerate_template_shard", "stop"]
    parameters: tuple[str, ...]


class EvaluatorContract(FrozenContract):
    revision: Literal["structural-candidate-evaluator-v1"]
    lexicographic_tiers: tuple[str, ...]
    quality_fields: tuple[str, ...]
    candidate_count_cap_per_band: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> EvaluatorContract:
        required = (
            "safety_isolation",
            "validity",
            "discovery_quality",
            "robustness",
            "cost",
            "parallel_efficiency",
        )
        if self.lexicographic_tiers != required:
            raise ValueError("evaluator lexicographic order is frozen")
        return self


class ReadinessThreshold(FrozenContract):
    min_sealed_worlds: int = Field(ge=1)
    min_independent_business_dates: int = Field(ge=1)
    min_effective_sample_size: int = Field(ge=1)
    min_manifest_completeness: float = Field(ge=0.0, le=1.0)
    min_multi_alternative_fraction: float = Field(ge=0.0, le=1.0)
    min_action_overlap: float = Field(ge=0.0, le=1.0)
    max_branch_unavailable_rate: float = Field(ge=0.0, le=1.0)
    min_failed_or_degraded_worlds: int = Field(ge=0)
    min_worlds_per_required_stratum: int = Field(ge=0)


class ReadinessContract(FrozenContract):
    record_to_baseline: ReadinessThreshold
    baseline_to_optimizer: ReadinessThreshold
    required_strata: tuple[str, ...]
    duplicate_cluster_key: tuple[str, ...]

    @model_validator(mode="after")
    def validate_monotonic_gates(self) -> ReadinessContract:
        low, high = self.record_to_baseline, self.baseline_to_optimizer
        increasing = (
            "min_sealed_worlds",
            "min_independent_business_dates",
            "min_effective_sample_size",
            "min_manifest_completeness",
            "min_multi_alternative_fraction",
            "min_action_overlap",
            "min_failed_or_degraded_worlds",
            "min_worlds_per_required_stratum",
        )
        if any(getattr(high, name) < getattr(low, name) for name in increasing):
            raise ValueError("optimizer readiness gate must be at least as strict")
        if high.max_branch_unavailable_rate > low.max_branch_unavailable_rate:
            raise ValueError("optimizer unavailable-branch gate must be stricter")
        return self


class ArchiveContract(FrozenContract):
    capacity: int = Field(ge=1)
    max_per_lineage: int = Field(ge=1)
    diversity_descriptors: tuple[str, ...]
    admission_reasons: tuple[str, ...]
    minimum_action_jaccard_distance: float = Field(ge=0.0, le=1.0)
    eviction_order: tuple[str, ...]


class BudgetContract(FrozenContract):
    max_rounds: int = Field(ge=1)
    max_nodes: int = Field(ge=1)
    max_concurrency: int = Field(ge=1)
    max_wall_seconds: int = Field(ge=1)
    max_candidate_generation_count: int = Field(ge=1)


class PilotContract(FrozenContract):
    schema_version: Literal["1"]
    pilot_id: Literal["structural-candidate-v1"]
    task_family: Literal["structural_candidate_audit"]
    lane: Literal["jczq"]
    mode: Literal["shadow_only"]
    authoritative_workflow: WorkflowBinding
    operator_grammar: tuple[OperatorSpec, ...]
    evaluator: EvaluatorContract
    readiness: ReadinessContract
    archive: ArchiveContract
    budgets: BudgetContract
    frozen_surfaces: tuple[str, ...]
    protected_actions: tuple[str, ...]


class PolicyStep(FrozenContract):
    round: int = Field(ge=1)
    action: Literal["continue_batch", "stop"]
    selector: Literal[
        "all_template_shards", "best_audit_clean_node_per_band"
    ]


class BaselinePolicyArtifact(FrozenContract):
    schema_version: Literal["1"]
    policy_revision_id: Literal["structural-baseline-v1"]
    family: Literal["structural_candidate_exploration"]
    interface_version: Literal["discovery-policy-v1"]
    constraints_version: Literal["structural-candidate-v1"]
    generator_family: Literal["baseline"]
    change_surfaces: tuple[Literal["exploration_policy"], ...]
    random_seed_policy: dict[str, object]
    compatible_world_families: tuple[Literal["structural_candidate_audit"], ...]
    steps: tuple[PolicyStep, ...]
    rationale: str = Field(min_length=1)


def canonical_hash(contract: FrozenContract) -> str:
    payload = contract.model_dump(mode="json")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pilot_contract(path: Path) -> PilotContract:
    return PilotContract.model_validate(_load(path))


def load_baseline_policy(path: Path) -> BaselinePolicyArtifact:
    return BaselinePolicyArtifact.model_validate(_load(path))
