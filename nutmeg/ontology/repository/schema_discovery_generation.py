"""Migration-41-only generation receipt schema."""

from sqlalchemy import Column, ForeignKey, Integer, Table, Text

from nutmeg.ontology.repository.schema import metadata

policy_generation_rounds = Table(
    "policy_generation_rounds",
    metadata,
    Column("generation_round_id", Text, primary_key=True),
    Column("generator_family", Text, nullable=False),
    Column("generator_revision", Text, nullable=False),
    Column("generator_artifact_hash", Text, nullable=False),
    Column("input_manifest_hash", Text, nullable=False),
    Column("input_manifest_json", Text, nullable=False),
    Column("eligible_parent_ids_json", Text, nullable=False),
    Column("seed", Integer, nullable=False),
    Column("candidate_cap", Integer, nullable=False),
    Column("compute_budget", Integer, nullable=False),
    Column("timeout_seconds", Integer, nullable=False),
    Column("generation_cost_json", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("candidate_hashes_json", Text, nullable=False),
    Column("trace_json", Text, nullable=False),
    Column("trace_hash", Text, nullable=False),
    Column("blocking_metrics_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("action_id", Text, ForeignKey("actions.action_id"), nullable=False),
)
