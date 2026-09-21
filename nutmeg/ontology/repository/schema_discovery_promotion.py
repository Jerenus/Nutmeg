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
