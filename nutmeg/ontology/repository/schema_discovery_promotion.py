"""Migration-42 append-only prospective shadow registration."""

from sqlalchemy import Column, ForeignKey, Integer, Table, Text

from nutmeg.ontology.repository.schema import metadata

policy_shadow_windows = Table(
    "policy_shadow_windows",
    metadata,
    Column("policy_shadow_window_id", Text, primary_key=True),
    Column("policy_family", Text, nullable=False),
    Column("scope_json", Text, nullable=False),
    Column(
        "policy_revision_id",
        Text,
        ForeignKey("exploration_policy_revisions.policy_revision_id"),
        nullable=False,
    ),
    Column(
        "policy_tournament_id",
        Text,
        ForeignKey("policy_tournaments.policy_tournament_id"),
        nullable=False,
    ),
    Column("start_at", Text, nullable=False),
    Column("end_at", Text, nullable=False),
    Column("minimum_independent_worlds", Integer, nullable=False),
    Column("invariant_codes_json", Text, nullable=False),
    Column("human_actor_id", Text, nullable=False),
    Column("acted_by", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("action_id", Text, ForeignKey("actions.action_id"), nullable=False),
)

protected_shadow_receipts = Table(
    "protected_shadow_receipts", metadata,
    Column("world_id", Text, ForeignKey("discovery_worlds.world_id"), primary_key=True),
    Column("schema_version", Text, nullable=False),
    Column("policy_revision_id", Text, nullable=False),
    Column("before_hash", Text, nullable=False),
    Column("after_hash", Text, nullable=False),
    Column("receipt_hash", Text, nullable=False),
    Column("action_id", Text, ForeignKey("actions.action_id"), nullable=False),
)

policy_scope_reviews = Table(
    "policy_scope_reviews", metadata,
    Column("scope_contract_hash", Text, primary_key=True),
    Column("contract_json", Text, nullable=False),
    Column("approval_ref", Text, nullable=False, unique=True),
    Column("human_actor_id", Text, nullable=False),
    Column("approved_at", Text, nullable=False),
    Column("action_id", Text, ForeignKey("actions.action_id"), nullable=False),
)
