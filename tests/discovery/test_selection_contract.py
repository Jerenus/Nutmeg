from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from nutmeg.discovery.contracts import canonical_hash, load_pilot_contract
from nutmeg.discovery.selection_contract import SelectionContract

ROOT = Path(__file__).resolve().parents[2]
PILOT = load_pilot_contract(
    ROOT / "experiments/discovery/structural-candidate-v1.contract.json"
)


def _document() -> dict[str, object]:
    return {
        "schema_version": "1",
        "contract_id": "structural-selection-v1",
        "evaluator_revision": "structural-candidate-evaluator-v1",
        "aggregation_revision": "structural-selection-aggregation-v1",
        "lexicographic_tiers": list(PILOT.evaluator.lexicographic_tiers),
        "quality_fields": list(PILOT.evaluator.quality_fields),
        "cluster_weighting": "equal_independent_cluster",
        "development_holdout_rule": "separate_time_forward",
        "within_tier": [
            {
                "tier": "safety_isolation",
                "fields": [
                    {"name": "invariant_violation_count", "direction": "min", "materiality": "0"}
                ],
            },
            {
                "tier": "validity",
                "fields": [
                    {"name": "invalid_selected_count", "direction": "min", "materiality": "0"}
                ],
            },
            {
                "tier": "discovery_quality",
                "fields": [
                    {"name": "eligible_band_count", "direction": "max", "materiality": "1"},
                    {
                        "name": "best_objective_probability_by_band",
                        "direction": "max",
                        "materiality": "0.001",
                    },
                    {
                        "name": "distinct_valid_candidate_count_capped",
                        "direction": "max",
                        "materiality": "1",
                    },
                ],
            },
            {
                "tier": "robustness",
                "fields": [
                    {"name": "failure_recovery_rate", "direction": "max", "materiality": "0.001"}
                ],
            },
            {
                "tier": "cost",
                "fields": [
                    {"name": "node_count", "direction": "min", "materiality": "1"},
                    {"name": "wall_seconds", "direction": "min", "materiality": "0.001"},
                ],
            },
            {
                "tier": "parallel_efficiency",
                "fields": [
                    {"name": "effective_parallelism", "direction": "max", "materiality": "0.001"}
                ],
            },
        ],
        "missing_value_rule": "explicit_unknown_cannot_win_tier",
        "tie_rule": "incumbent",
        "cost_units": {
            "node_count": "attempt_nodes",
            "candidate_generation_count": "generated_candidates",
            "wall_seconds": "seconds",
            "retry_count": "attempt_nodes",
        },
        "failure_penalty": "disqualify_safety_else_explicit_robustness_failure",
        "worst_stratum": {
            "strata": list(PILOT.readiness.required_strata),
            "max_decline": "0",
        },
    }


def test_selection_contract_is_strict_decimal_safe_and_hash_stable():
    contract = SelectionContract.model_validate_with_pilot(_document(), PILOT)

    assert contract.within_tier[2].fields[1].materiality == Decimal("0.001")
    assert canonical_hash(contract) == canonical_hash(
        SelectionContract.model_validate_with_pilot(dict(reversed(_document().items())), PILOT)
    )

    with pytest.raises(ValidationError, match="unexpected"):
        SelectionContract.model_validate_with_pilot({**_document(), "unexpected": True}, PILOT)


def test_selection_contract_rejects_pilot_drift_and_missing_as_zero():
    changed_tiers = {**_document(), "lexicographic_tiers": ["validity", "safety_isolation"]}
    with pytest.raises(ValueError, match="tier"):
        SelectionContract.model_validate_with_pilot(changed_tiers, PILOT)

    changed_fields = {**_document(), "quality_fields": ["eligible_band_count"]}
    with pytest.raises(ValueError, match="quality"):
        SelectionContract.model_validate_with_pilot(changed_fields, PILOT)

    missing_as_zero = {**_document(), "missing_value_rule": "zero"}
    with pytest.raises(ValidationError, match="missing_value_rule"):
        SelectionContract.model_validate_with_pilot(missing_as_zero, PILOT)


def test_selection_contract_requires_nonnegative_materiality_and_every_tier():
    document = _document()
    within_tier = list(document["within_tier"])
    quality = dict(within_tier[2])
    fields = list(quality["fields"])
    fields[0] = {**fields[0], "materiality": "-1"}
    quality["fields"] = fields
    within_tier[2] = quality
    with pytest.raises(ValidationError, match="materiality"):
        SelectionContract.model_validate_with_pilot(
            {**document, "within_tier": within_tier}, PILOT
        )

    with pytest.raises(ValueError, match="tier"):
        SelectionContract.model_validate_with_pilot(
            {**document, "within_tier": within_tier[:-1]}, PILOT
        )


def test_selection_contract_requires_declared_cost_units_and_worst_strata():
    document = _document()
    with pytest.raises(ValueError, match="cost unit"):
        SelectionContract.model_validate_with_pilot(
            {**document, "cost_units": {"node_count": "attempt_nodes"}}, PILOT
        )

    with pytest.raises(ValueError, match="strata"):
        SelectionContract.model_validate_with_pilot(
            {
                **document,
                "worst_stratum": {
                    "strata": ["board_size:small"],
                    "max_decline": "0",
                },
            },
            PILOT,
        )
