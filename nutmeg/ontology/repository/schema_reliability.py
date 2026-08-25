"""Reliability evidence and release approval tables introduced by migration 14."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Table, Text

from nutmeg.ontology.repository.schema import metadata

reliability_evidence = Table(
    "reliability_evidence",
    metadata,
    Column("reliability_evidence_id", Text, primary_key=True),
    Column("evidence_kind", Text, nullable=False, index=True),
    Column("workflow", Text, nullable=True, index=True),
    Column("business_date", Text, nullable=True, index=True),
    Column("observed_from", Text, nullable=False),
    Column("observed_to", Text, nullable=False),
    Column("status", Text, nullable=False, index=True),
    Column("report_json", Text, nullable=False),
    Column("source_refs_json", Text, nullable=False),
    Column("content_hash", Text, nullable=False, unique=True),
    Column("recorded_at", Text, nullable=False, index=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    CheckConstraint(
        "status IN ('passed', 'failed')",
        name="ck_reliability_evidence_status",
    ),
)

release_approvals = Table(
    "release_approvals",
    metadata,
    Column("release_approval_id", Text, primary_key=True),
    Column("release_version", Text, nullable=False, unique=True),
    Column("evidence_snapshot_sha256", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("approved_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
)
