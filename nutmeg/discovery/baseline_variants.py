"""Closed deterministic baseline challenger artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import BaselinePolicyArtifact, FrozenContract
from nutmeg.discovery.generation_contracts import PolicyProgramArtifact
from nutmeg.ontology.discovery.models import canonical_hash


def variant_policy_revision_id(document: dict[str, object]) -> str:
    body = {key: value for key, value in document.items() if key != "policy_revision_id"}
    return f"structural-baseline-variant-{canonical_hash(body)[:24]}"


class DeterministicBaselineVariantArtifact(FrozenContract):
    schema_version: Literal["1"]
    policy_revision_id: str = Field(pattern=r"^structural-baseline-variant-[0-9a-f]{24}$")
    family: Literal["structural_candidate_exploration"]
    interface_version: Literal["discovery-policy-v1"]
    constraints_version: Literal["structural-candidate-v1"]
    generator_family: Literal["baseline"]
    change_surfaces: tuple[Literal["exploration_policy"], ...]
    random_seed_policy: dict[str, object]
    compatible_world_families: tuple[Literal["structural_candidate_audit"], ...]
    template_order: tuple[str, ...] = Field(min_length=1)
    batch_limit: int = Field(ge=1)
    stop_selector: Literal["best_audit_clean_node_per_band"]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_closed_variant(self) -> DeterministicBaselineVariantArtifact:
        if len(set(self.template_order)) != len(self.template_order):
            raise ValueError("template order contains duplicate template")
        if self.random_seed_policy != {"kind": "none", "deterministic": True}:
            raise ValueError("baseline variant random seed policy must be deterministic")
        if self.policy_revision_id != variant_policy_revision_id(
            self.model_dump(mode="json", exclude={"policy_revision_id"})
        ):
            raise ValueError("baseline variant policy id is not content-addressed")
        return self


PolicyArtifact = (
    BaselinePolicyArtifact | DeterministicBaselineVariantArtifact | PolicyProgramArtifact
)


def load_policy_artifact(document: object) -> PolicyArtifact:
    if not isinstance(document, dict):
        raise ValueError("policy artifact must be an object")
    if document.get("policy_revision_id") == "structural-baseline-v1":
        return BaselinePolicyArtifact.model_validate(document)
    if document.get("generator_family") == "bounded_evolution":
        return PolicyProgramArtifact.model_validate(document)
    return DeterministicBaselineVariantArtifact.model_validate(document)
