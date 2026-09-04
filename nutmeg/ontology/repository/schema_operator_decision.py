"""Append-only operator decision and evidence intake storage."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata


def _canonical_decimal_check(column_name: str, *, probability: bool) -> str:
    numeric_bounds = (
        f"CAST({column_name} AS REAL) BETWEEN 0.0 AND 1.0"
        if probability
        else f"CAST({column_name} AS REAL) BETWEEN -1.0 AND 1.0"
    )
    return (
        f"typeof({column_name}) = 'text' "
        f"AND printf('%.12f', CAST({column_name} AS REAL)) = {column_name} "
        f"AND {numeric_bounds}"
    )

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


operator_market_prior_baseline_revisions = Table(
    "operator_market_prior_baseline_revisions",
    metadata,
    Column("market_prior_baseline_revision_id", Text, primary_key=True),
    Column("market_prior_baseline_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "task_evidence_bundle_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("information_cutoff_at", Text, nullable=False),
    Column(
        "policy_version",
        Text,
        ForeignKey("policy_versions.policy_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("arithmetic_version", Text, nullable=False),
    Column("probability_precision", Integer, nullable=False),
    Column("comparison_only", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_market_prior_baseline_revision"),
    CheckConstraint(
        "probability_precision > 0",
        name="ck_market_prior_baseline_precision",
    ),
    CheckConstraint(
        "comparison_only = 1",
        name="ck_market_prior_baseline_comparison_only",
    ),
    UniqueConstraint(
        "market_prior_baseline_family_id",
        "revision_no",
        name="uq_market_prior_baseline_revision",
    ),
)


operator_market_prior_baseline_probabilities = Table(
    "operator_market_prior_baseline_probabilities",
    metadata,
    Column("market_prior_baseline_probability_id", Text, primary_key=True),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("item_index", Integer, nullable=False),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"), nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey("official_offer_revisions.official_offer_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "market_definition_id",
        Text,
        ForeignKey("market_definitions.market_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("face_code", Text, nullable=False),
    Column("probability_decimal", Text, nullable=False),
    Column(
        "market_snapshot_id",
        Text,
        ForeignKey("market_snapshots.market_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "quote_id",
        Text,
        ForeignKey("market_quotes.quote_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("item_index >= 0", name="ck_market_prior_probability_index"),
    CheckConstraint(
        _canonical_decimal_check("probability_decimal", probability=True),
        name="ck_market_prior_probability_canonical",
    ),
    UniqueConstraint(
        "market_prior_baseline_revision_id",
        "item_index",
        name="uq_market_prior_probability_index",
    ),
    UniqueConstraint(
        "market_prior_baseline_revision_id",
        "match_id",
        "market_definition_id",
        "face_code",
        name="uq_market_prior_probability_face",
    ),
)


operator_baseline_envelope_revisions = Table(
    "operator_baseline_envelope_revisions",
    metadata,
    Column("baseline_envelope_revision_id", Text, primary_key=True),
    Column("baseline_envelope_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "task_evidence_bundle_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("ticket_kind", Text, nullable=False),
    Column("capital_cap_minor", Integer, nullable=False),
    Column("currency", Text, nullable=False),
    Column("maximum_ticket_count", Integer, nullable=False),
    Column("maximum_exhaustive_candidate_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_baseline_envelope_revision"),
    CheckConstraint("capital_cap_minor >= 0", name="ck_baseline_envelope_cap"),
    CheckConstraint("maximum_ticket_count > 0", name="ck_baseline_envelope_ticket_count"),
    CheckConstraint(
        "maximum_exhaustive_candidate_count > 0",
        name="ck_baseline_envelope_enumeration_count",
    ),
    UniqueConstraint(
        "baseline_envelope_family_id",
        "revision_no",
        name="uq_baseline_envelope_revision",
    ),
)


operator_baseline_envelope_offer_constraints = Table(
    "operator_baseline_envelope_offer_constraints",
    metadata,
    Column("baseline_envelope_offer_constraint_id", Text, primary_key=True),
    Column(
        "baseline_envelope_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("constraint_index", Integer, nullable=False),
    Column("official_match_no", Text, nullable=False),
    Column("market_code", Text, nullable=False),
    Column("omission_allowed", Integer, nullable=False),
    CheckConstraint("constraint_index >= 0", name="ck_baseline_offer_constraint_index"),
    CheckConstraint("omission_allowed IN (0, 1)", name="ck_baseline_offer_omission"),
    UniqueConstraint(
        "baseline_envelope_revision_id",
        "constraint_index",
        name="uq_baseline_offer_constraint_index",
    ),
    UniqueConstraint(
        "baseline_envelope_revision_id",
        "official_match_no",
        "market_code",
        name="uq_baseline_offer_constraint",
    ),
)


operator_baseline_envelope_face_bundles = Table(
    "operator_baseline_envelope_face_bundles",
    metadata,
    Column("baseline_envelope_face_bundle_id", Text, primary_key=True),
    Column(
        "baseline_envelope_offer_constraint_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_offer_constraints."
            "baseline_envelope_offer_constraint_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("bundle_index", Integer, nullable=False),
    Column("bundle_code", Text, nullable=False),
    CheckConstraint("bundle_index >= 0", name="ck_baseline_face_bundle_index"),
    UniqueConstraint(
        "baseline_envelope_offer_constraint_id",
        "bundle_index",
        name="uq_baseline_face_bundle_index",
    ),
    UniqueConstraint(
        "baseline_envelope_offer_constraint_id",
        "bundle_code",
        name="uq_baseline_face_bundle_code",
    ),
)


operator_baseline_envelope_bundle_faces = Table(
    "operator_baseline_envelope_bundle_faces",
    metadata,
    Column("baseline_envelope_bundle_face_id", Text, primary_key=True),
    Column(
        "baseline_envelope_face_bundle_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_face_bundles.baseline_envelope_face_bundle_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("face_index", Integer, nullable=False),
    Column("face_code", Text, nullable=False),
    CheckConstraint("face_index >= 0", name="ck_baseline_bundle_face_index"),
    UniqueConstraint(
        "baseline_envelope_face_bundle_id",
        "face_index",
        name="uq_baseline_bundle_face_index",
    ),
    UniqueConstraint(
        "baseline_envelope_face_bundle_id",
        "face_code",
        name="uq_baseline_bundle_face_code",
    ),
)


operator_baseline_envelope_structure_templates = Table(
    "operator_baseline_envelope_structure_templates",
    metadata,
    Column("baseline_envelope_structure_template_id", Text, primary_key=True),
    Column(
        "baseline_envelope_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("template_index", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("structure_code", Text, nullable=False),
    Column("pass_size", Integer, nullable=True),
    Column("required_offer_count", Integer, nullable=False),
    Column("maximum_groups", Integer, nullable=False),
    CheckConstraint("template_index >= 0", name="ck_baseline_structure_template_index"),
    CheckConstraint("pass_size IS NULL OR pass_size > 0", name="ck_baseline_pass_size"),
    CheckConstraint(
        "required_offer_count > 0 AND maximum_groups > 0",
        name="ck_baseline_structure_template_counts",
    ),
    UniqueConstraint(
        "baseline_envelope_revision_id",
        "template_index",
        name="uq_baseline_structure_template_index",
    ),
    UniqueConstraint(
        "baseline_envelope_revision_id",
        "structure_code",
        name="uq_baseline_structure_template_code",
    ),
)


operator_baseline_envelope_template_offers = Table(
    "operator_baseline_envelope_template_offers",
    metadata,
    Column("baseline_envelope_template_offer_id", Text, primary_key=True),
    Column(
        "baseline_envelope_structure_template_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_structure_templates."
            "baseline_envelope_structure_template_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("offer_index", Integer, nullable=False),
    Column("official_match_no", Text, nullable=False),
    CheckConstraint("offer_index >= 0", name="ck_baseline_template_offer_index"),
    UniqueConstraint(
        "baseline_envelope_structure_template_id",
        "offer_index",
        name="uq_baseline_template_offer_index",
    ),
    UniqueConstraint(
        "baseline_envelope_structure_template_id",
        "official_match_no",
        name="uq_baseline_template_offer_number",
    ),
)


operator_match_judgment_revisions = Table(
    "operator_match_judgment_revisions",
    metadata,
    Column("operator_match_judgment_revision_id", Text, primary_key=True),
    Column("operator_match_judgment_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "task_evidence_bundle_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "baseline_envelope_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"), nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey("official_offer_revisions.official_offer_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "market_definition_id",
        Text,
        ForeignKey("market_definitions.market_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "forecast_revision_id",
        Text,
        ForeignKey("forecast_revisions.forecast_revision_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("falsifier", Text, nullable=False),
    Column("rationale", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_operator_match_judgment_revision"),
    UniqueConstraint(
        "operator_match_judgment_family_id",
        "revision_no",
        name="uq_operator_match_judgment_revision",
    ),
)


operator_match_judgment_probabilities = Table(
    "operator_match_judgment_probabilities",
    metadata,
    Column("operator_match_judgment_probability_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("face_index", Integer, nullable=False),
    Column("face_code", Text, nullable=False),
    Column("prior_probability_decimal", Text, nullable=False),
    Column("belief_probability_decimal", Text, nullable=False),
    Column("delta_probability_decimal", Text, nullable=False),
    CheckConstraint("face_index >= 0", name="ck_judgment_probability_index"),
    CheckConstraint(
        _canonical_decimal_check("prior_probability_decimal", probability=True),
        name="ck_judgment_prior_probability_canonical",
    ),
    CheckConstraint(
        _canonical_decimal_check("belief_probability_decimal", probability=True),
        name="ck_judgment_belief_probability_canonical",
    ),
    CheckConstraint(
        _canonical_decimal_check("delta_probability_decimal", probability=False),
        name="ck_judgment_delta_probability_canonical",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "face_index",
        name="uq_judgment_probability_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "face_code",
        name="uq_judgment_probability_face",
    ),
)


operator_match_judgment_factor_adjustments = Table(
    "operator_match_judgment_factor_adjustments",
    metadata,
    Column("operator_match_judgment_factor_adjustment_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("factor_index", Integer, nullable=False),
    Column(
        "factor_definition_id",
        Text,
        ForeignKey("factor_definitions.factor_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("scope_entity_id", Text, nullable=False),
    CheckConstraint("factor_index >= 0", name="ck_judgment_factor_index"),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "factor_index",
        name="uq_judgment_factor_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "factor_definition_id",
        "scope_entity_id",
        name="uq_judgment_factor_scope",
    ),
)


operator_match_judgment_factor_offsets = Table(
    "operator_match_judgment_factor_offsets",
    metadata,
    Column("operator_match_judgment_factor_offset_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_factor_adjustment_id",
        Text,
        ForeignKey(
            "operator_match_judgment_factor_adjustments."
            "operator_match_judgment_factor_adjustment_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("face_index", Integer, nullable=False),
    Column("face_code", Text, nullable=False),
    Column("offset_probability_decimal", Text, nullable=False),
    CheckConstraint("face_index >= 0", name="ck_judgment_factor_offset_index"),
    CheckConstraint(
        _canonical_decimal_check("offset_probability_decimal", probability=False),
        name="ck_judgment_factor_offset_canonical",
    ),
    UniqueConstraint(
        "operator_match_judgment_factor_adjustment_id",
        "face_index",
        name="uq_judgment_factor_offset_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_factor_adjustment_id",
        "face_code",
        name="uq_judgment_factor_offset_face",
    ),
)


operator_match_judgment_factor_evidence_refs = Table(
    "operator_match_judgment_factor_evidence_refs",
    metadata,
    Column("operator_match_judgment_factor_evidence_ref_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_factor_adjustment_id",
        Text,
        ForeignKey(
            "operator_match_judgment_factor_adjustments."
            "operator_match_judgment_factor_adjustment_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("evidence_index", Integer, nullable=False),
    Column("evidence_ref_token", Text, nullable=False),
    CheckConstraint("evidence_index >= 0", name="ck_judgment_factor_evidence_index"),
    UniqueConstraint(
        "operator_match_judgment_factor_adjustment_id",
        "evidence_index",
        name="uq_judgment_factor_evidence_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_factor_adjustment_id",
        "evidence_ref_token",
        name="uq_judgment_factor_evidence_token",
    ),
)


operator_match_judgment_face_bundles = Table(
    "operator_match_judgment_face_bundles",
    metadata,
    Column("operator_match_judgment_face_bundle_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("bundle_index", Integer, nullable=False),
    Column("bundle_code", Text, nullable=False),
    CheckConstraint("bundle_index >= 0", name="ck_judgment_face_bundle_index"),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "bundle_index",
        name="uq_judgment_face_bundle_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "bundle_code",
        name="uq_judgment_face_bundle_code",
    ),
)


operator_match_judgment_bundle_faces = Table(
    "operator_match_judgment_bundle_faces",
    metadata,
    Column("operator_match_judgment_bundle_face_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_face_bundle_id",
        Text,
        ForeignKey(
            "operator_match_judgment_face_bundles.operator_match_judgment_face_bundle_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("face_index", Integer, nullable=False),
    Column("face_code", Text, nullable=False),
    CheckConstraint("face_index >= 0", name="ck_judgment_bundle_face_index"),
    UniqueConstraint(
        "operator_match_judgment_face_bundle_id",
        "face_index",
        name="uq_judgment_bundle_face_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_face_bundle_id",
        "face_code",
        name="uq_judgment_bundle_face_code",
    ),
)


operator_match_judgment_rule_refs = Table(
    "operator_match_judgment_rule_refs",
    metadata,
    Column("operator_match_judgment_rule_ref_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("rule_index", Integer, nullable=False),
    Column("rule_id", Text, nullable=False),
    CheckConstraint("rule_index >= 0", name="ck_judgment_rule_index"),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "rule_index",
        name="uq_judgment_rule_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "rule_id",
        name="uq_judgment_rule_id",
    ),
)


operator_match_judgment_evidence_refs = Table(
    "operator_match_judgment_evidence_refs",
    metadata,
    Column("operator_match_judgment_evidence_ref_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("evidence_index", Integer, nullable=False),
    Column("evidence_ref_token", Text, nullable=False),
    CheckConstraint("evidence_index >= 0", name="ck_judgment_evidence_index"),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "evidence_index",
        name="uq_judgment_evidence_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "evidence_ref_token",
        name="uq_judgment_evidence_token",
    ),
)


operator_judgment_prescription_revisions = Table(
    "operator_judgment_prescription_revisions",
    metadata,
    Column("judgment_prescription_revision_id", Text, primary_key=True),
    Column("judgment_prescription_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_judgment_prescription_revisions.judgment_prescription_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "task_evidence_bundle_revision_id",
        Text,
        ForeignKey(
            "operator_task_evidence_bundle_revisions.task_evidence_bundle_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "baseline_envelope_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("required_match_count", Integer, nullable=False),
    Column("judgment_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_judgment_prescription_revision"),
    CheckConstraint(
        "required_match_count >= 1 AND judgment_count = required_match_count",
        name="ck_judgment_prescription_counts",
    ),
    UniqueConstraint(
        "judgment_prescription_family_id",
        "revision_no",
        name="uq_judgment_prescription_revision",
    ),
)


operator_judgment_prescription_items = Table(
    "operator_judgment_prescription_items",
    metadata,
    Column("operator_judgment_prescription_item_id", Text, primary_key=True),
    Column(
        "judgment_prescription_revision_id",
        Text,
        ForeignKey(
            "operator_judgment_prescription_revisions.judgment_prescription_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("item_index", Integer, nullable=False),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"), nullable=False),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    CheckConstraint("item_index >= 0", name="ck_judgment_prescription_item_index"),
    UniqueConstraint(
        "judgment_prescription_revision_id",
        "item_index",
        name="uq_judgment_prescription_item_index",
    ),
    UniqueConstraint(
        "judgment_prescription_revision_id",
        "match_id",
        name="uq_judgment_prescription_match",
    ),
)


__all__ = [
    "operator_baseline_envelope_bundle_faces",
    "operator_baseline_envelope_face_bundles",
    "operator_baseline_envelope_offer_constraints",
    "operator_baseline_envelope_revisions",
    "operator_baseline_envelope_structure_templates",
    "operator_baseline_envelope_template_offers",
    "operator_evidence_coverage_receipts",
    "operator_evidence_freeze_requests",
    "operator_evidence_intake_objects",
    "operator_evidence_intake_receipts",
    "operator_judgment_prescription_items",
    "operator_judgment_prescription_revisions",
    "operator_market_prior_baseline_probabilities",
    "operator_market_prior_baseline_revisions",
    "operator_match_judgment_bundle_faces",
    "operator_match_judgment_evidence_refs",
    "operator_match_judgment_face_bundles",
    "operator_match_judgment_factor_adjustments",
    "operator_match_judgment_factor_evidence_refs",
    "operator_match_judgment_factor_offsets",
    "operator_match_judgment_probabilities",
    "operator_match_judgment_revisions",
    "operator_match_judgment_rule_refs",
    "operator_task_evidence_bundle_items",
    "operator_task_evidence_bundle_revisions",
    "operator_worker_jobs",
]
