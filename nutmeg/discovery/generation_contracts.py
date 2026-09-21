"""Closed, content-addressed policy-generation contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import FrozenContract
from nutmeg.ontology.discovery.models import canonical_hash


class DevelopmentWorld(FrozenContract):
    world_id: str
    seal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pool_role: Literal["development"]
    provenance_mode: Literal["prospective_online", "historical_replay_source"]
    sealed: Literal[True]
    diagnostic_codes: tuple[str, ...] = ()


class EligibleParent(FrozenContract):
    policy_revision_id: str
    disposition: Literal["incumbent", "stepping_stone"]
    lineage_root: str
    template_order: tuple[str, ...] = Field(min_length=1, max_length=32)
    batch_limit: int = Field(ge=1, le=32)


class GenerationContext(FrozenContract):
    schema_version: Literal["1"]
    generator_revision: Literal["bounded-evolution-v1", "baseline-v1"]
    constraint_revision: Literal["structural-candidate-v1"]
    development_worlds: tuple[DevelopmentWorld, ...]
    eligible_parents: tuple[EligibleParent, ...]
    template_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    seed: int = Field(ge=0)
    candidate_cap: int = Field(ge=1, le=100)
    compute_budget: int = Field(ge=1, le=1000)
    timeout_seconds: int = Field(ge=1, le=120)

    @model_validator(mode="after")
    def validate_context(self) -> GenerationContext:
        ids = tuple(parent.policy_revision_id for parent in self.eligible_parents)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("eligible parent IDs must be sorted and unique")
        if len(set(self.template_ids)) != len(self.template_ids):
            raise ValueError("duplicate template vocabulary")
        if tuple(world.world_id for world in self.development_worlds) != tuple(
            sorted({world.world_id for world in self.development_worlds})
        ):
            raise ValueError("development worlds must be sorted and unique")
        return self


def program_policy_revision_id(document: dict[str, object]) -> str:
    body = {key: value for key, value in document.items() if key != "policy_revision_id"}
    return f"structural-program-{canonical_hash(body)[:24]}"


class PolicyProgram(FrozenContract):
    template_order: tuple[str, ...] = Field(min_length=1, max_length=32)
    batch_limit: int = Field(ge=1, le=32)
    budget_allocation: Literal["frontier_first", "quality_first"]
    stop_quality_threshold: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_program(self) -> PolicyProgram:
        if len(set(self.template_order)) != len(self.template_order):
            raise ValueError("duplicate template priority")
        if any(not item or len(item) > 64 for item in self.template_order):
            raise ValueError("program state size exceeds frozen bound")
        if len(self.model_dump_json()) > 4096:
            raise ValueError("program state size exceeds frozen bound")
        return self


class PolicyProgramArtifact(FrozenContract):
    schema_version: Literal["1"]
    policy_revision_id: str
    family: Literal["structural_candidate_exploration"]
    interface_version: Literal["discovery-policy-v1"]
    constraints_version: Literal["structural-candidate-v1"]
    generator_family: Literal["bounded_evolution"]
    generator_revision: Literal["bounded-evolution-v1"]
    parent_policy_revision_ids: tuple[str, ...] = Field(min_length=1, max_length=2)
    seed: int = Field(ge=0)
    change_surfaces: tuple[Literal["exploration_policy"], ...] = Field(min_length=1)
    descriptor_set: tuple[Literal["priority", "batch", "allocation", "stop"], ...]
    program: PolicyProgram

    @model_validator(mode="after")
    def validate_artifact(self) -> PolicyProgramArtifact:
        if self.parent_policy_revision_ids != tuple(sorted(set(self.parent_policy_revision_ids))):
            raise ValueError("parent policy IDs must be sorted and unique")
        if self.change_surfaces != ("exploration_policy",):
            raise ValueError("unsupported frozen change surface")
        if self.descriptor_set != tuple(sorted(set(self.descriptor_set))):
            raise ValueError("descriptors must be sorted and unique")
        if self.policy_revision_id != program_policy_revision_id(
            self.model_dump(mode="json", exclude={"policy_revision_id"})
        ):
            raise ValueError("program policy ID is not content-addressed")
        return self
