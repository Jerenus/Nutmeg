"""Append-only Discovery Harness records, separate from business candidate lineage."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata

TABLE_KEYS = {
    "discovery_worlds": ("world_id",),
    "discovery_world_events": ("world_event_id",),
    "discovery_runs": ("discovery_run_id",),
    "discovery_nodes": ("node_id",),
    "discovery_node_evaluations": ("node_evaluation_id",),
    "exploration_policy_revisions": ("policy_revision_id",),
    "exploration_policy_parent_links": ("policy_revision_id", "parent_index"),
    "policy_replay_runs": ("policy_replay_run_id",),
    "policy_replay_rounds": ("policy_replay_run_id", "round_no"),
    "policy_replay_completions": ("policy_replay_run_id",),
    "policy_tournaments": ("policy_tournament_id",),
    "policy_tournament_candidates": ("policy_tournament_id", "candidate_index"),
    "policy_tournament_worlds": ("policy_tournament_id", "world_index"),
    "policy_tournament_results": ("policy_tournament_id", "policy_revision_id", "world_id"),
    "policy_tournament_completions": ("policy_tournament_id",),
    "policy_archive_decisions": ("archive_decision_id",),
    "policy_holdout_exposures": ("holdout_exposure_id",),
    "policy_deployments": ("policy_deployment_id",),
    "policy_brake_events": ("policy_brake_event_id",),
}

# The keys and foreign keys are declared explicitly; all non-key optional values
# are text unless the schema calls for integer ordinals, counters, or flags.
_COLUMNS = {
    "discovery_worlds": (
        "task_family business_date lane strata_json input_manifest_hash input_manifest_json "
        "pilot_contract_hash legal_action_schema_json evaluator_revision resource_budget_json "
        "cutoff_at provenance_mode isolated_store_identity root_node_id created_at action_id"
    ),
    "exploration_policy_revisions": (
        "family source_artifact_hash interface_version constraints_version generator_family "
        "generator_revision generation_trace_hash generator_descriptors_json "
        "generation_input_manifest_hash generation_budget_json generation_cost_json "
        "generation_timeout_seconds rationale change_summary configuration_json "
        "random_seed_policy_json compatible_world_families_json "
        "max_resource_permissions_json change_surfaces_json novelty_descriptors_json "
        "validation_result_json created_by created_at action_id"
    ),
    "discovery_world_events": (
        "world_id sequence_no event_kind reason manifest_hash occurred_at action_id"
    ),
    "discovery_runs": "world_id policy_revision_id environment_mode started_at action_id",
    "discovery_nodes": (
        "world_id discovery_run_id parent_node_id depth sibling_order creation_sequence "
        "continuation_action_json policy_decision_json artifact_manifest_hash "
        "artifact_manifest_json business_refs_json execution_status diagnostic_codes_json "
        "started_at finished_at latency_ms resource_cost_json retry_of_node_id "
        "terminal_reason frontier_eligible visibility_sequence action_id"
    ),
    "discovery_node_evaluations": (
        "node_id revision_no supersedes_evaluation_id evaluator_revision result_json "
        "selectable evaluated_at action_id"
    ),
    "exploration_policy_parent_links": "parent_policy_revision_id",
    "policy_replay_runs": (
        "policy_revision_id world_id initial_observation_hash evaluator_revision "
        "cost_policy_revision random_seed started_at action_id"
    ),
    "policy_replay_rounds": (
        "observation_hash policy_state_hash requested_actions_json accepted_actions_json "
        "rejected_actions_json revealed_node_ids_json remaining_budget_json decided_at"
    ),
    "policy_replay_completions": (
        "stop_reason budget_used_json failure_codes_json selected_node_ids_json "
        "aggregate_outcome_json trace_hash finished_at action_id"
    ),
    "policy_tournaments": (
        "policy_family incumbent_policy_revision_id candidate_set_hash "
        "world_pool_manifest_hash evaluator_revision aggregation_revision "
        "decision_contract_json development_cutoff_at holdout_cutoff_at created_at action_id"
    ),
    "policy_tournament_candidates": (
        "policy_revision_id candidate_generator_revision candidate_role"
    ),
    "policy_tournament_worlds": "world_id pool_role stratum_labels_json",
    "policy_tournament_results": "score_vector_json disqualified exclusion_reason trace_hash",
    "policy_tournament_completions": (
        "winner_policy_revision_id tie_policy_revision_ids_json disqualification_reasons_json "
        "reproduction_hash finished_at action_id"
    ),
    "policy_archive_decisions": (
        "policy_tournament_id policy_revision_id disposition reason_code "
        "diversity_descriptors_json evidence_json decided_at action_id"
    ),
    "policy_holdout_exposures": (
        "policy_tournament_id world_id policy_family exposed_at action_id"
    ),
    "policy_deployments": (
        "policy_family policy_revision_id decision scope_json effective_boundary "
        "evidence_refs_json human_actor_id acted_by reason supersedes_deployment_id "
        "rollback_policy_revision_id brake_conditions_json decided_at action_id"
    ),
    "policy_brake_events": (
        "policy_deployment_id tripped_policy_revision_id restored_policy_revision_id "
        "condition_code evidence_json effective_boundary tripped_at action_id"
    ),
}

_FOREIGN_KEYS = {
    ("discovery_world_events", "world_id"): "discovery_worlds.world_id",
    ("discovery_runs", "world_id"): "discovery_worlds.world_id",
    ("discovery_runs", "policy_revision_id"): "exploration_policy_revisions.policy_revision_id",
    ("discovery_nodes", "world_id"): "discovery_worlds.world_id",
    ("discovery_nodes", "discovery_run_id"): "discovery_runs.discovery_run_id",
    ("discovery_nodes", "parent_node_id"): "discovery_nodes.node_id",
    ("discovery_nodes", "retry_of_node_id"): "discovery_nodes.node_id",
    ("discovery_node_evaluations", "node_id"): "discovery_nodes.node_id",
    (
        "discovery_node_evaluations",
        "supersedes_evaluation_id",
    ): "discovery_node_evaluations.node_evaluation_id",
    (
        "exploration_policy_parent_links",
        "policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    (
        "exploration_policy_parent_links",
        "parent_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_replay_runs", "policy_revision_id"): "exploration_policy_revisions.policy_revision_id",
    ("policy_replay_runs", "world_id"): "discovery_worlds.world_id",
    ("policy_replay_rounds", "policy_replay_run_id"): "policy_replay_runs.policy_replay_run_id",
    (
        "policy_replay_completions",
        "policy_replay_run_id",
    ): "policy_replay_runs.policy_replay_run_id",
    (
        "policy_tournaments",
        "incumbent_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    (
        "policy_tournament_candidates",
        "policy_tournament_id",
    ): "policy_tournaments.policy_tournament_id",
    (
        "policy_tournament_candidates",
        "policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_tournament_worlds", "policy_tournament_id"): "policy_tournaments.policy_tournament_id",
    ("policy_tournament_worlds", "world_id"): "discovery_worlds.world_id",
    (
        "policy_tournament_results",
        "policy_tournament_id",
    ): "policy_tournaments.policy_tournament_id",
    (
        "policy_tournament_results",
        "policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_tournament_results", "world_id"): "discovery_worlds.world_id",
    (
        "policy_tournament_completions",
        "policy_tournament_id",
    ): "policy_tournaments.policy_tournament_id",
    (
        "policy_tournament_completions",
        "winner_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_archive_decisions", "policy_tournament_id"): "policy_tournaments.policy_tournament_id",
    (
        "policy_archive_decisions",
        "policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_holdout_exposures", "policy_tournament_id"): "policy_tournaments.policy_tournament_id",
    ("policy_holdout_exposures", "world_id"): "discovery_worlds.world_id",
    ("policy_deployments", "policy_revision_id"): "exploration_policy_revisions.policy_revision_id",
    ("policy_deployments", "supersedes_deployment_id"): "policy_deployments.policy_deployment_id",
    (
        "policy_deployments",
        "rollback_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    ("policy_brake_events", "policy_deployment_id"): "policy_deployments.policy_deployment_id",
    (
        "policy_brake_events",
        "tripped_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
    (
        "policy_brake_events",
        "restored_policy_revision_id",
    ): "exploration_policy_revisions.policy_revision_id",
}

_INTEGERS = {
    "sequence_no",
    "depth",
    "sibling_order",
    "creation_sequence",
    "latency_ms",
    "frontier_eligible",
    "visibility_sequence",
    "revision_no",
    "selectable",
    "parent_index",
    "generation_timeout_seconds",
    "random_seed",
    "round_no",
    "candidate_index",
    "world_index",
    "disqualified",
}
_NULLABLE = {
    "root_node_id",
    "generation_trace_hash",
    "discovery_run_id",
    "parent_node_id",
    "retry_of_node_id",
    "supersedes_evaluation_id",
    "finished_at",
    "latency_ms",
    "terminal_reason",
    "exclusion_reason",
    "winner_policy_revision_id",
    "supersedes_deployment_id",
    "rollback_policy_revision_id",
    "reason",
    "manifest_hash",
    "continuation_action_json",
    "policy_decision_json",
    "artifact_manifest_hash",
    "artifact_manifest_json",
    "business_refs_json",
    "resource_cost_json",
    "visibility_sequence",
}
_UNIQUES = {
    "discovery_world_events": (("world_id", "sequence_no"),),
    "discovery_nodes": (("world_id", "creation_sequence"), ("world_id", "visibility_sequence")),
    "discovery_node_evaluations": (("node_id", "revision_no"),),
    "policy_deployments": (("policy_family", "effective_boundary", "action_id"),),
}


def _table(name: str) -> Table:
    fields = (*TABLE_KEYS[name], *_COLUMNS[name].split())
    columns = [
        Column(
            field,
            Integer if field in _INTEGERS else Text,
            *(
                [ForeignKey(_FOREIGN_KEYS[name, field], ondelete="RESTRICT")]
                if (name, field) in _FOREIGN_KEYS
                else []
            ),
            primary_key=field in TABLE_KEYS[name],
            nullable=field in _NULLABLE if field not in TABLE_KEYS[name] else False,
        )
        for field in fields
    ]
    constraints = [UniqueConstraint(*fields) for fields in _UNIQUES.get(name, ())]
    return Table(name, metadata, *columns, *constraints)


for _name in TABLE_KEYS:
    globals()[_name] = _table(_name)
