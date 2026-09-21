from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nutmeg.discovery.contracts import (
    BaselinePolicyArtifact,
    PilotContract,
    canonical_hash,
    load_baseline_policy,
    load_pilot_contract,
)


def _pilot() -> dict[str, object]:
    return {
        "schema_version": "1",
        "pilot_id": "structural-candidate-v1",
        "task_family": "structural_candidate_audit",
        "lane": "jczq",
        "mode": "shadow_only",
        "authoritative_workflow": {
            "generator": "nutmeg.product.operator_candidates:enumerate_band_candidates",
            "candidate_set_kind": "judgment_bound",
            "generator_version": "operator-candidate-v2-bands",
            "audit_policy_source": "candidate_set.audit_policy_version",
        },
        "operator_grammar": [
            {"name": "enumerate_template_shard", "parameters": ["template_ids"]},
            {"name": "stop", "parameters": ["selected_node_ids", "reason"]},
        ],
        "evaluator": {
            "revision": "structural-candidate-evaluator-v1",
            "lexicographic_tiers": [
                "safety_isolation",
                "validity",
                "discovery_quality",
                "robustness",
                "cost",
                "parallel_efficiency",
            ],
            "quality_fields": [
                "eligible_band_count",
                "best_objective_probability_by_band",
                "distinct_valid_candidate_count_capped",
            ],
            "candidate_count_cap_per_band": 20,
        },
        "readiness": {
            "record_to_baseline": {
                "min_sealed_worlds": 30,
                "min_independent_business_dates": 20,
                "min_effective_sample_size": 24,
                "min_manifest_completeness": 1.0,
                "min_multi_alternative_fraction": 0.80,
                "min_action_overlap": 0.0,
                "max_branch_unavailable_rate": 0.40,
                "min_failed_or_degraded_worlds": 0,
                "min_worlds_per_required_stratum": 0,
            },
            "baseline_to_optimizer": {
                "min_sealed_worlds": 60,
                "min_independent_business_dates": 40,
                "min_effective_sample_size": 48,
                "min_manifest_completeness": 1.0,
                "min_multi_alternative_fraction": 0.85,
                "min_action_overlap": 0.70,
                "max_branch_unavailable_rate": 0.25,
                "min_failed_or_degraded_worlds": 3,
                "min_worlds_per_required_stratum": 8,
            },
            "required_strata": [
                "board_size:small",
                "board_size:medium",
                "board_size:large",
            ],
            "duplicate_cluster_key": [
                "business_date",
                "task_snapshot_hash",
                "slate_revision_id",
            ],
        },
        "archive": {
            "capacity": 12,
            "max_per_lineage": 3,
            "diversity_descriptors": [
                "action_histogram",
                "stop_depth",
                "selected_band_coverage",
                "stratum_strengths",
            ],
            "admission_reasons": [
                "behavioral_coverage",
                "underrepresented_stratum",
                "novel_legal_trajectory",
            ],
            "minimum_action_jaccard_distance": 0.20,
            "eviction_order": [
                "disqualified",
                "irreproducible",
                "dominated_clone",
                "oldest",
            ],
        },
        "budgets": {
            "max_rounds": 4,
            "max_nodes": 32,
            "max_concurrency": 4,
            "max_wall_seconds": 120,
            "max_candidate_generation_count": 50000,
        },
        "frozen_surfaces": [
            "model_weights",
            "evaluator_code",
            "action_permissions",
            "ontology_handlers",
            "football_rules",
            "audit_rules",
            "funds_actions",
        ],
        "protected_actions": [
            "confirm_ticket_placement",
            "record_cash_transaction",
            "rsi_approve_deployment",
        ],
    }


def _policy() -> dict[str, object]:
    return {
        "schema_version": "1",
        "policy_revision_id": "structural-baseline-v1",
        "family": "structural_candidate_exploration",
        "interface_version": "discovery-policy-v1",
        "constraints_version": "structural-candidate-v1",
        "generator_family": "baseline",
        "change_surfaces": ["exploration_policy"],
        "random_seed_policy": {"kind": "none", "deterministic": True},
        "compatible_world_families": ["structural_candidate_audit"],
        "steps": [
            {
                "round": 1,
                "action": "continue_batch",
                "selector": "all_template_shards",
            },
            {
                "round": 2,
                "action": "stop",
                "selector": "best_audit_clean_node_per_band",
            },
        ],
        "rationale": "Represent current bounded exhaustive generation as the incumbent.",
    }


def test_contracts_reject_unknown_fields_and_non_shadow_mode(tmp_path):
    bad = {**_pilot(), "unknown": True}
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError, match="unknown"):
        load_pilot_contract(path)

    bad = {**_pilot(), "mode": "production"}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError, match="shadow_only"):
        load_pilot_contract(path)


def test_optimizer_gate_is_stricter_than_baseline_gate():
    contract = PilotContract.model_validate(_pilot())
    baseline = contract.readiness.record_to_baseline
    optimizer = contract.readiness.baseline_to_optimizer
    assert optimizer.min_sealed_worlds >= baseline.min_sealed_worlds
    assert optimizer.min_independent_business_dates >= baseline.min_independent_business_dates
    assert optimizer.min_effective_sample_size >= baseline.min_effective_sample_size
    assert optimizer.min_action_overlap >= baseline.min_action_overlap
    assert optimizer.max_branch_unavailable_rate <= baseline.max_branch_unavailable_rate


def test_policy_is_baseline_only_and_has_no_authority_surface():
    policy = BaselinePolicyArtifact.model_validate(_policy())
    assert policy.generator_family == "baseline"
    assert policy.change_surfaces == ("exploration_policy",)
    assert all("deploy" not in step.selector for step in policy.steps)


def test_canonical_hash_is_stable_and_changes_with_semantics(tmp_path):
    pilot = PilotContract.model_validate(_pilot())
    first = canonical_hash(pilot)
    second = canonical_hash(PilotContract.model_validate(dict(reversed(_pilot().items()))))
    assert first == second
    changed = PilotContract.model_validate(
        {**_pilot(), "budgets": {**_pilot()["budgets"], "max_nodes": 33}}
    )
    assert canonical_hash(changed) != first

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy()), encoding="utf-8")
    assert load_baseline_policy(path).policy_revision_id == "structural-baseline-v1"
