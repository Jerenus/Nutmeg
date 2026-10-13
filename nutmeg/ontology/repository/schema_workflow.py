"""Governed human/AI workflow objects and the durable product event outbox."""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from nutmeg.ontology.repository.schema import metadata

adjudications = Table(
    "adjudications",
    metadata,
    Column("adjudication_id", Text, primary_key=True),
    Column("subject_type", Text, nullable=False, index=True),
    Column("subject_id", Text, nullable=False, index=True),
    Column("decision", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("evidence_rejected_json", Text, nullable=False),
    Column("alternative_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("supersedes_adjudication_id", Text, nullable=True),
)

flag_instances = Table(
    "flag_instances",
    metadata,
    Column("flag_instance_id", Text, primary_key=True),
    Column("flag_type", Text, nullable=False, index=True),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("direction", Text, nullable=True),
    Column("strength", Float, nullable=False),
    Column("evidence_refs_json", Text, nullable=False),
    Column("predicted_face", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

predictions = Table(
    "predictions",
    metadata,
    Column("prediction_id", Text, primary_key=True),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    ),
    Column("subject_type", Text, nullable=False, index=True),
    Column("subject_id", Text, nullable=False, index=True),
    Column("claim", Text, nullable=False),
    Column("falsifier", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("outcome", Text, nullable=True),
    Column("registered_at", Text, nullable=False),
    Column("settled_at", Text, nullable=True),
)

outbox_events = Table(
    "outbox_events",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("topic", Text, nullable=False, index=True),
    Column("object_type", Text, nullable=True),
    Column("object_id", Text, nullable=True),
    Column("payload_json", Text, nullable=False),
    Column("occurred_at", Text, nullable=False),
    UniqueConstraint("action_id", "topic", name="uq_outbox_action_topic"),
)

operator_projection_cursors = Table(
    "operator_projection_cursors",
    metadata,
    Column("consumer_name", Text, primary_key=True),
    Column("last_sequence", Integer, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint(
        "last_sequence >= 0",
        name="ck_operator_projection_cursors_sequence",
    ),
)
