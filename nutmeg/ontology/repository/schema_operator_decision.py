"""Append-only operator decision and evidence intake storage."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata

operator_evidence_intake_receipts = Table(
    "operator_evidence_intake_receipts",
    metadata,
    Column("intake_receipt_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("task_snapshot_hash", Text, nullable=False),
    Column("captured_at", Text, nullable=False),
    Column("manifest_sha256", Text, nullable=False, unique=True),
    Column("source_retrieval_ids_json", Text, nullable=False),
    Column("committed_count", Integer, nullable=False),
    Column("rejected_count", Integer, nullable=False),
    Column("skipped_count", Integer, nullable=False),
    Column("persisted_count", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_operator_evidence_lane"),
    CheckConstraint(
        "committed_count >= 0 AND rejected_count >= 0 AND skipped_count >= 0 "
        "AND persisted_count >= 0",
        name="ck_operator_evidence_counts_nonnegative",
    ),
    CheckConstraint(
        "committed_count = persisted_count AND rejected_count = 0 AND skipped_count = 0",
        name="ck_operator_evidence_counts_reconciled",
    ),
)


operator_evidence_intake_objects = Table(
    "operator_evidence_intake_objects",
    metadata,
    Column("intake_object_id", Text, primary_key=True),
    Column(
        "intake_receipt_id",
        Text,
        ForeignKey("operator_evidence_intake_receipts.intake_receipt_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("object_kind", Text, nullable=False),
    Column("object_id", Text, nullable=False),
    Column("object_index", Integer, nullable=False),
    Column("observed_at", Text, nullable=False),
    Column("source_retrieval_ids_json", Text, nullable=False),
    Column("source_kinds_json", Text, nullable=False),
    CheckConstraint(
        "object_kind IN ('observation', 'claim')",
        name="ck_operator_evidence_object_kind",
    ),
    CheckConstraint("object_index >= 0", name="ck_operator_evidence_object_index"),
    UniqueConstraint(
        "intake_receipt_id",
        "object_kind",
        "object_id",
        name="uq_operator_evidence_intake_object",
    ),
    UniqueConstraint(
        "intake_receipt_id",
        "object_index",
        name="uq_operator_evidence_intake_ordinal",
    ),
)


operator_evidence_coverage_receipts = Table(
    "operator_evidence_coverage_receipts",
    metadata,
    Column("coverage_receipt_id", Text, primary_key=True),
    Column(
        "intake_receipt_id",
        Text,
        ForeignKey("operator_evidence_intake_receipts.intake_receipt_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requirement_id", Text, nullable=False),
    Column("subject_scope", Text, nullable=False),
    Column("evidence_ref_tokens_json", Text, nullable=False),
    CheckConstraint(
        "requirement_id IN ('E1', 'E2', 'E3', 'E4', 'E5', 'E6a', 'E6b', 'EC')",
        name="ck_operator_evidence_requirement",
    ),
    UniqueConstraint(
        "intake_receipt_id",
        "match_id",
        "requirement_id",
        "subject_scope",
        name="uq_operator_evidence_coverage_scope",
    ),
)


__all__ = [
    "operator_evidence_coverage_receipts",
    "operator_evidence_intake_objects",
    "operator_evidence_intake_receipts",
]
