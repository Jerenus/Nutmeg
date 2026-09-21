"""Frozen tournament selection contract bound to the D0 pilot."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from nutmeg.discovery.contracts import FrozenContract, PilotContract


class FieldComparator(FrozenContract):
    name: str = Field(min_length=1)
    direction: Literal["min", "max"]
    materiality: Decimal = Field(ge=Decimal("0"))


class TierComparator(FrozenContract):
    tier: str = Field(min_length=1)
    fields: tuple[FieldComparator, ...] = Field(min_length=1)


class WorstStratumRule(FrozenContract):
    strata: tuple[str, ...] = Field(min_length=1)
    max_decline: Decimal = Field(ge=Decimal("0"))


class SelectionContract(FrozenContract):
    schema_version: Literal["1"]
    contract_id: Literal["structural-selection-v1"]
    evaluator_revision: Literal["structural-candidate-evaluator-v1"]
    aggregation_revision: Literal["structural-selection-aggregation-v1"]
    lexicographic_tiers: tuple[str, ...]
    quality_fields: tuple[str, ...]
    cluster_weighting: Literal["equal_independent_cluster"]
    development_holdout_rule: Literal["separate_time_forward"]
    within_tier: tuple[TierComparator, ...]
    missing_value_rule: Literal["explicit_unknown_cannot_win_tier"]
    tie_rule: Literal["incumbent"]
    cost_units: dict[str, Literal["attempt_nodes", "generated_candidates", "seconds"]]
    failure_penalty: Literal["disqualify_safety_else_explicit_robustness_failure"]
    worst_stratum: WorstStratumRule

    @model_validator(mode="after")
    def validate_shape(self) -> SelectionContract:
        tiers = tuple(item.tier for item in self.within_tier)
        if tiers != self.lexicographic_tiers:
            raise ValueError("within-tier comparator order must match frozen tier order")
        if len(set(tiers)) != len(tiers):
            raise ValueError("within-tier comparator contains duplicate tier")
        expected_cost_units = {
            "node_count",
            "candidate_generation_count",
            "wall_seconds",
            "retry_count",
        }
        if set(self.cost_units) != expected_cost_units:
            raise ValueError("every declared cost unit is required")
        expected_fields = {
            "safety_isolation": (("invariant_violation_count", "min"),),
            "validity": (("invalid_selected_count", "min"),),
            "discovery_quality": (
                ("eligible_band_count", "max"),
                ("best_objective_probability_by_band", "max"),
                ("distinct_valid_candidate_count_capped", "max"),
            ),
            "robustness": (("failure_recovery_rate", "max"),),
            "cost": (("node_count", "min"), ("wall_seconds", "min")),
            "parallel_efficiency": (("effective_parallelism", "max"),),
        }
        for tier in self.within_tier:
            actual = tuple((field.name, field.direction) for field in tier.fields)
            if actual != expected_fields.get(tier.tier):
                raise ValueError(f"{tier.tier} comparison fields or directions differ")
        discovery = next(item for item in self.within_tier if item.tier == "discovery_quality")
        if tuple(field.name for field in discovery.fields) != self.quality_fields:
            raise ValueError("discovery-quality fields must match the frozen quality order")
        return self

    @classmethod
    def model_validate_with_pilot(
        cls, document: object, pilot: PilotContract
    ) -> SelectionContract:
        contract = cls.model_validate(document)
        if contract.evaluator_revision != pilot.evaluator.revision:
            raise ValueError("selection evaluator differs from frozen pilot")
        if contract.lexicographic_tiers != pilot.evaluator.lexicographic_tiers:
            raise ValueError("selection tier order differs from frozen pilot")
        if contract.quality_fields != pilot.evaluator.quality_fields:
            raise ValueError("selection quality fields differ from frozen pilot")
        if contract.worst_stratum.strata != pilot.readiness.required_strata:
            raise ValueError("selection worst strata differ from frozen pilot strata")
        return contract


def load_selection_contract(path: Path, pilot: PilotContract) -> SelectionContract:
    return SelectionContract.model_validate_with_pilot(
        json.loads(path.read_text(encoding="utf-8")), pilot
    )
