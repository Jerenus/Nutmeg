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


operator_evidence_freeze_requests = Table(
    "operator_evidence_freeze_requests",
    metadata,
    Column("evidence_freeze_request_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("task_snapshot_hash", Text, nullable=False),
    Column("requirement_revision_token", Text, nullable=False),
    Column("information_cutoff_at", Text, nullable=False),
    Column(
        "policy_version",
        Text,
        ForeignKey("policy_versions.policy_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("dependency_fingerprint", Text, nullable=False),
    Column("requested_at", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_evidence_freeze_request_lane"),
    UniqueConstraint(
        "task_family_id",
        "dependency_fingerprint",
        name="uq_evidence_freeze_request_dependencies",
    ),
)


operator_task_evidence_bundle_revisions = Table(
    "operator_task_evidence_bundle_revisions",
    metadata,
    Column("task_evidence_bundle_revision_id", Text, primary_key=True),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "evidence_freeze_request_id",
        Text,
        ForeignKey(
            "operator_evidence_freeze_requests.evidence_freeze_request_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column(
        "link_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("task_snapshot_hash", Text, nullable=False),
    Column("requirement_revision_token", Text, nullable=False),
    Column("information_cutoff_at", Text, nullable=False),
    Column(
        "policy_version",
        Text,
        ForeignKey("policy_versions.policy_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("dependency_fingerprint", Text, nullable=False),
    Column("required_match_count", Integer, nullable=False),
    Column("bundle_count", Integer, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("conflicts_cleared_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("frozen_at", Text, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_task_evidence_bundle_lane"),
    CheckConstraint("revision_no >= 1", name="ck_task_evidence_bundle_revision"),
    CheckConstraint(
        "required_match_count >= 1 AND bundle_count = required_match_count "
        "AND item_count = bundle_count AND conflicts_cleared_count >= 0",
        name="ck_task_evidence_bundle_counts_reconciled",
    ),
    UniqueConstraint(
        "task_family_id",
        "revision_no",
        name="uq_task_evidence_bundle_revision",
    ),
    UniqueConstraint(
        "task_family_id",
        "content_hash",
        name="uq_task_evidence_bundle_content",
    ),
)


operator_task_evidence_bundle_items = Table(
    "operator_task_evidence_bundle_items",
    metadata,
    Column("task_evidence_bundle_item_id", Text, primary_key=True),
    Column(
        "task_evidence_bundle_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
        index=True,
    ),
    Column("item_index", Integer, nullable=False),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "evidence_bundle_id",
        Text,
        ForeignKey("evidence_bundles.evidence_bundle_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "freeze_bundle_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requirement_states_json", Text, nullable=False),
    Column("requirement_ref_tokens_json", Text, nullable=False),
    Column("market_prior_ref_tokens_json", Text, nullable=False),
    Column("conflicts_cleared_ref_tokens_json", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    CheckConstraint("item_index >= 0", name="ck_task_evidence_bundle_item_index"),
    UniqueConstraint(
        "task_evidence_bundle_revision_id",
        "item_index",
        name="uq_task_evidence_bundle_item_index",
    ),
    UniqueConstraint(
        "task_evidence_bundle_revision_id",
        "match_id",
        name="uq_task_evidence_bundle_match",
    ),
)


operator_worker_jobs = Table(
    "operator_worker_jobs",
    metadata,
    Column("worker_job_id", Text, primary_key=True),
    Column("job_kind", Text, nullable=False, index=True),
    Column("source_object_type", Text, nullable=False),
    Column("source_object_id", Text, nullable=False),
    Column("state", Text, nullable=False, index=True),
    Column("lease_owner", Text, nullable=True),
    Column("lease_expires_at", Text, nullable=True),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("available_at", Text, nullable=False, index=True),
    Column("last_error_code", Text, nullable=True),
    Column(
        "result_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("result_object_type", Text, nullable=True),
    Column("result_object_id", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint(
        "job_kind IN ('evidence_freeze', 'market_baseline', 'candidate_generation', "
        "'task_settlement', 'review_materialization', 'scoreboard_review_completion')",
        name="ck_operator_worker_job_kind",
    ),
    CheckConstraint(
        "state IN ('queued', 'leased', 'completed', 'failed')",
        name="ck_operator_worker_job_state",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_operator_worker_job_attempts"),
    CheckConstraint(
        "(state = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
        "OR (state != 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        name="ck_operator_worker_job_lease_state",
    ),
    CheckConstraint(
        "(state = 'completed' AND result_action_id IS NOT NULL "
        "AND result_object_type IS NOT NULL AND result_object_id IS NOT NULL) "
        "OR (state != 'completed' AND result_action_id IS NULL "
        "AND result_object_type IS NULL AND result_object_id IS NULL)",
        name="ck_operator_worker_job_result_ref",
    ),
    UniqueConstraint(
        "job_kind",
        "source_object_type",
        "source_object_id",
        name="uq_operator_worker_job_source",
    ),
)


__all__ = [
    "operator_evidence_coverage_receipts",
    "operator_evidence_freeze_requests",
    "operator_evidence_intake_objects",
    "operator_evidence_intake_receipts",
    "operator_task_evidence_bundle_items",
    "operator_task_evidence_bundle_revisions",
    "operator_worker_jobs",
]
