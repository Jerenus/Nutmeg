"""Proposed D7 test thresholds; this model grants no operational authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import FrozenContract, PilotContract, canonical_hash


class IterationContract(FrozenContract):
    schema_version: Literal["1"]
    contract_id: Literal["structural-iteration-v1"]
    approval_status: Literal["proposed_unapproved"]
    duplicate_cluster_key: tuple[str, ...]
    holdout_rotation: Literal["sealed_strictly_newer_unexposed_cluster"]
    archive_capacity: int = Field(ge=1)
    max_per_lineage: int = Field(ge=1)
    minimum_action_jaccard_distance: float = Field(ge=0, le=1)
    min_effective_new_clusters: int = Field(ge=1)
    min_days_between_rounds: int = Field(ge=0)
    min_action_coverage_delta: int = Field(ge=0)
    min_failure_case_delta: int = Field(ge=0)
    min_stratum_count_delta: int = Field(ge=0)
    min_drift_sample_clusters: int = Field(ge=1)
    min_material_quality_gain: float = Field(gt=0)
    max_branch_growth_without_gain: float = Field(ge=0)
    worst_stratum_max_decline: float = Field(ge=0)
    hard_invariant_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_hard_invariants(self) -> IterationContract:
        if not self.hard_invariant_codes or len(set(self.hard_invariant_codes)) != len(
            self.hard_invariant_codes
        ):
            raise ValueError("registered hard invariant codes are required")
        return self

    @classmethod
    def model_validate_with_pilot(cls, document: object, pilot: PilotContract) -> IterationContract:
        contract = cls.model_validate(document)
        if (
            contract.duplicate_cluster_key != pilot.readiness.duplicate_cluster_key
            or contract.archive_capacity != pilot.archive.capacity
            or contract.max_per_lineage != pilot.archive.max_per_lineage
            or contract.minimum_action_jaccard_distance
            != pilot.archive.minimum_action_jaccard_distance
        ):
            raise ValueError("iteration contract must preserve frozen D0 guards")
        return contract


def load_iteration_contract(path: Path, pilot: PilotContract) -> IterationContract:
    return IterationContract.model_validate_with_pilot(
        json.loads(path.read_text(encoding="utf-8")), pilot
    )


def proposed_contract_hash(contract: IterationContract) -> str:
    return canonical_hash(contract)
