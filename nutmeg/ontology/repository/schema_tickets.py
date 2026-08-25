"""Protected pre-booking and placement tables introduced by migration 12."""
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

ticket_batch_revisions = Table(
    "ticket_batch_revisions",
    metadata,
    Column("ticket_batch_revision_id", Text, primary_key=True),
    Column("ticket_batch_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "ticket_batch_revisions.ticket_batch_revision_id", ondelete="RESTRICT"
        ),
        nullable=True,
    ),
    Column("run_date", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column(
        "account_id",
        Text,
        ForeignKey("cash_accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("currency", Text, nullable=False),
    Column("deadline_at", Text, nullable=False),
    Column("input_legs_json", Text, nullable=False),
    Column("composition_json", Text, nullable=False),
    Column("audit_findings_json", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "source_artifact_id",
        Text,
        ForeignKey("source_artifacts.artifact_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    Column(
        "created_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("revision_no > 0", name="ck_ticket_batch_revision_positive"),
    UniqueConstraint(
        "ticket_batch_id", "revision_no", name="uq_ticket_batch_revision"
    ),
)

audited_ticket_artifacts = Table(
    "audited_ticket_artifacts",
    metadata,
    Column("ticket_artifact_id", Text, primary_key=True),
    Column(
        "ticket_batch_revision_id",
        Text,
        ForeignKey(
            "ticket_batch_revisions.ticket_batch_revision_id", ondelete="RESTRICT"
        ),
        nullable=False,
        index=True,
    ),
    Column("ticket_index", Integer, nullable=False),
    Column("ticket_hash", Text, nullable=False, unique=True),
    Column(
        "source_artifact_id",
        Text,
        ForeignKey("source_artifacts.artifact_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("amount", Float, nullable=False),
    Column("currency", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("deadline_at", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("approved_at", Text, nullable=False),
    Column(
        "approved_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("ticket_index >= 0", name="ck_ticket_artifact_index"),
    CheckConstraint("amount > 0", name="ck_ticket_artifact_amount"),
    UniqueConstraint(
        "ticket_batch_revision_id",
        "ticket_index",
        name="uq_ticket_artifact_revision_index",
    ),
)

ticket_confirmation_challenges = Table(
    "ticket_confirmation_challenges",
    metadata,
    Column("confirmation_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("nonce_hash", Text, nullable=False, unique=True),
    Column("ticket_hash", Text, nullable=False),
    Column("amount", Float, nullable=False),
    Column("currency", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("issued_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("consumed_at", Text, nullable=True),
    Column(
        "consumed_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    CheckConstraint("amount > 0", name="ck_ticket_confirmation_amount"),
)

ticket_placements = Table(
    "ticket_placements",
    metadata,
    Column("ticket_placement_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "ticket_id",
        Text,
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("placement_mode", Text, nullable=False),
    Column("external_reference", Text, nullable=False),
    Column(
        "receipt_artifact_id",
        Text,
        ForeignKey("source_artifacts.artifact_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "receipt_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("placed_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
)
