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


def _canonical_nonnegative_decimal_check(column_name: str) -> str:
    return (
        f"typeof({column_name}) = 'text' "
        f"AND printf('%.12f', CAST({column_name} AS REAL)) = {column_name} "
        f"AND CAST({column_name} AS REAL) >= 0.0"
    )


def _canonical_positive_decimal_check(column_name: str) -> str:
    return (
        f"typeof({column_name}) = 'text' "
        f"AND printf('%.12f', CAST({column_name} AS REAL)) = {column_name} "
        f"AND CAST({column_name} AS REAL) > 1.0"
    )


def _canonical_unbounded_decimal_check(column_name: str) -> str:
    return (
        f"typeof({column_name}) = 'text' "
        f"AND printf('%.12f', CAST({column_name} AS REAL)) = {column_name}"
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
    Column("booked_decimal_odds", Text, nullable=False),
    Column("quote_captured_at", Text, nullable=False),
    Column("settlement_parameter_decimal", Text, nullable=True),
    CheckConstraint("item_index >= 0", name="ck_market_prior_probability_index"),
    CheckConstraint(
        _canonical_decimal_check("probability_decimal", probability=True),
        name="ck_market_prior_probability_canonical",
    ),
    CheckConstraint(
        _canonical_positive_decimal_check("booked_decimal_odds"),
        name="ck_market_prior_booked_odds_canonical",
    ),
    CheckConstraint(
        "settlement_parameter_decimal IS NULL OR "
        + _canonical_unbounded_decimal_check("settlement_parameter_decimal"),
        name="ck_market_prior_settlement_parameter_canonical",
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


# 2026-09-10（migration 28）：C5/C7/C13/C14 需要的两项操作员事实。判断层此前只存概率、
# 因子、面集合与规则引用，候选审计因此只能用 anchor_integrity="unknown" + 空 precedents
# 造 Leg——C5 的 ERROR 硬门与 C7/C13 在应用里永远不触发，C14 则在任何被排面 >20% 的候选上
# 永远亮 WARN。两张表把这两项事实接回判断层，且和判断修订一样只增不改。
operator_match_judgment_anchor_facts = Table(
    "operator_match_judgment_anchor_facts",
    metadata,
    Column("operator_match_judgment_anchor_fact_id", Text, primary_key=True),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column("anchor_integrity", Text, nullable=False),
    CheckConstraint(
        "anchor_integrity IN ('pass', 'fail', 'symmetric_damage', 'unknown')",
        name="ck_judgment_anchor_integrity",
    ),
)


operator_match_judgment_face_precedents = Table(
    "operator_match_judgment_face_precedents",
    metadata,
    Column("operator_match_judgment_face_precedent_id", Text, primary_key=True),
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
    Column("precedent_index", Integer, nullable=False),
    Column("face_code", Text, nullable=False),
    Column("precedent_ref", Text, nullable=False),
    Column("status", Text, nullable=False),
    CheckConstraint("precedent_index >= 0", name="ck_judgment_precedent_index"),
    CheckConstraint("face_code IN ('3', '1', '0')", name="ck_judgment_precedent_face"),
    CheckConstraint("status IN ('alive', 'dead')", name="ck_judgment_precedent_status"),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "precedent_index",
        name="uq_judgment_precedent_index",
    ),
    UniqueConstraint(
        "operator_match_judgment_revision_id",
        "face_code",
        "precedent_ref",
        name="uq_judgment_precedent_ref",
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


operator_candidate_generation_requests = Table(
    "operator_candidate_generation_requests",
    metadata,
    Column("generation_request_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
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
    Column(
        "judgment_prescription_revision_id",
        Text,
        ForeignKey(
            "operator_judgment_prescription_revisions.judgment_prescription_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "fixed_prize_policy_revision_id",
        Text,
        ForeignKey(
            "zucai_fixed_prize_policy_revisions.fixed_prize_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("dependency_fingerprint", Text, nullable=False),
    Column("expected_current_revision_no", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("requested_at", Text, nullable=False),
    CheckConstraint(
        "expected_current_revision_no >= 0",
        name="ck_operator_candidate_generation_expected_revision",
    ),
    UniqueConstraint(
        "task_family_id",
        "work_item_id",
        "content_hash",
        name="uq_operator_candidate_generation_request",
    ),
)


operator_candidate_set_revisions = Table(
    "operator_candidate_set_revisions",
    metadata,
    Column("candidate_set_revision_id", Text, primary_key=True),
    Column("candidate_set_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "generation_request_id",
        Text,
        ForeignKey(
            "operator_candidate_generation_requests.generation_request_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
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
    Column(
        "judgment_prescription_revision_id",
        Text,
        ForeignKey(
            "operator_judgment_prescription_revisions.judgment_prescription_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("set_kind", Text, nullable=False),
    Column("comparison_only", Integer, nullable=False),
    Column("generator_version", Text, nullable=False),
    Column("audit_policy_version", Text, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("eligible_count", Integer, nullable=False),
    Column("audit_blocked_count", Integer, nullable=False),
    Column("over_cap_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_operator_candidate_set_revision"),
    CheckConstraint(
        "set_kind IN ('judgment_bound', 'conditional_market_counterfactual')",
        name="ck_operator_candidate_set_kind",
    ),
    CheckConstraint(
        "(set_kind = 'judgment_bound' AND comparison_only = 0) "
        "OR (set_kind = 'conditional_market_counterfactual' AND comparison_only = 1)",
        name="ck_operator_candidate_set_comparison",
    ),
    CheckConstraint(
        "candidate_count >= 0 AND eligible_count >= 0 "
        "AND audit_blocked_count >= 0 AND over_cap_count >= 0 "
        "AND candidate_count = eligible_count + audit_blocked_count + over_cap_count",
        name="ck_operator_candidate_set_counts",
    ),
    UniqueConstraint(
        "candidate_set_family_id",
        "revision_no",
        name="uq_operator_candidate_set_revision",
    ),
    UniqueConstraint(
        "generation_request_id",
        "set_kind",
        name="uq_operator_candidate_set_request_kind",
    ),
)


operator_candidates = Table(
    "operator_candidates",
    metadata,
    Column("candidate_revision_id", Text, primary_key=True),
    Column(
        "candidate_set_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("candidate_index", Integer, nullable=False),
    Column("candidate_code", Text, nullable=False),
    Column("partition", Text, nullable=False),
    Column("rank", Integer, nullable=True),
    Column("eligible", Integer, nullable=False),
    Column("deployable", Integer, nullable=False),
    Column("leg_audit_completed", Integer, nullable=False),
    Column("prescription_audit_completed", Integer, nullable=False),
    Column("budget_check_completed", Integer, nullable=False),
    Column("deployment_report_completed", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("odds_band", Text, nullable=True),
    Column("target_odds_min_decimal", Text, nullable=True),
    Column("target_odds_max_decimal", Text, nullable=True),
    Column("combined_decimal_odds", Text, nullable=True),
    Column("parent_candidate_revision_id", Text, nullable=True),
    Column("delta_reason", Text, nullable=True),
    CheckConstraint("candidate_index >= 0", name="ck_operator_candidate_index"),
    CheckConstraint(
        "partition IN ('eligible', 'audit_blocked', 'over_cap')",
        name="ck_operator_candidate_partition",
    ),
    CheckConstraint(
        "(partition = 'eligible' AND eligible = 1) "
        "OR (partition != 'eligible' AND eligible = 0)",
        name="ck_operator_candidate_eligible",
    ),
    CheckConstraint(
        "(partition = 'eligible' AND rank IS NOT NULL AND rank > 0) "
        "OR (partition != 'eligible' AND rank IS NULL)",
        name="ck_operator_candidate_rank",
    ),
    CheckConstraint(
        "eligible IN (0, 1) AND deployable IN (0, 1) AND deployable <= eligible",
        name="ck_operator_candidate_deployability",
    ),
    CheckConstraint(
        "leg_audit_completed = 1 AND prescription_audit_completed = 1 "
        "AND budget_check_completed = 1 AND deployment_report_completed = 1",
        name="ck_operator_candidate_all_audits",
    ),
    CheckConstraint(
        "(odds_band IS NULL AND target_odds_min_decimal IS NULL "
        "AND target_odds_max_decimal IS NULL AND combined_decimal_odds IS NULL) OR "
        "(odds_band IN ('10x', '20x', '50x', '100x') "
        "AND target_odds_min_decimal IS NOT NULL "
        "AND target_odds_max_decimal IS NOT NULL "
        "AND combined_decimal_odds IS NOT NULL)",
        name="ck_operator_candidate_odds_band_shape",
    ),
    CheckConstraint(
        "(parent_candidate_revision_id IS NULL AND delta_reason IS NULL) OR "
        "(parent_candidate_revision_id IS NOT NULL "
        "AND length(trim(delta_reason)) > 0)",
        name="ck_operator_candidate_iteration_shape",
    ),
    UniqueConstraint(
        "candidate_set_revision_id",
        "candidate_index",
        name="uq_operator_candidate_index",
    ),
    UniqueConstraint(
        "candidate_set_revision_id",
        "candidate_code",
        name="uq_operator_candidate_code",
    ),
    UniqueConstraint(
        "candidate_set_revision_id",
        "content_hash",
        name="uq_operator_candidate_content",
    ),
)


operator_candidate_band_outcomes = Table(
    "operator_candidate_band_outcomes",
    metadata,
    Column("candidate_band_outcome_id", Text, primary_key=True),
    Column(
        "candidate_set_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("odds_band", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("reason_code", Text, nullable=True),
    CheckConstraint(
        "odds_band IN ('10x', '20x', '50x', '100x')",
        name="ck_operator_candidate_band_outcome_band",
    ),
    CheckConstraint(
        "(status = 'candidates' AND candidate_count > 0 AND reason_code IS NULL) OR "
        "(status = 'no_feasible_candidate' AND candidate_count = 0 "
        "AND length(trim(reason_code)) > 0)",
        name="ck_operator_candidate_band_outcome_shape",
    ),
    UniqueConstraint(
        "candidate_set_revision_id",
        "odds_band",
        name="uq_operator_candidate_band_outcome",
    ),
)


operator_candidate_metrics = Table(
    "operator_candidate_metrics",
    metadata,
    Column("candidate_metric_id", Text, primary_key=True),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("currency", Text, nullable=False),
    Column("ticket_count", Integer, nullable=False),
    Column("distinct_note_count", Integer, nullable=False),
    Column("paid_note_unit_count", Integer, nullable=False),
    Column("stake_minor", Integer, nullable=False),
    Column("capital_utilization_decimal", Text, nullable=False),
    Column("probability_kind", Text, nullable=False),
    Column("objective_probability_decimal", Text, nullable=False),
    Column("expected_broken_legs_decimal", Text, nullable=False),
    Column("break_even_bonus_minor", Integer, nullable=True),
    Column("break_even_to_official_median_decimal", Text, nullable=True),
    CheckConstraint("length(currency) = 3", name="ck_operator_candidate_metric_currency"),
    CheckConstraint(
        "ticket_count > 0 AND distinct_note_count > 0 "
        "AND paid_note_unit_count > 0 AND stake_minor > 0",
        name="ck_operator_candidate_metric_counts",
    ),
    CheckConstraint(
        "probability_kind IN ('all_required_legs', 'any_ticket_all_required_legs')",
        name="ck_operator_candidate_probability_kind",
    ),
    CheckConstraint(
        _canonical_nonnegative_decimal_check("capital_utilization_decimal"),
        name="ck_operator_candidate_capital_utilization",
    ),
    CheckConstraint(
        _canonical_decimal_check("objective_probability_decimal", probability=True),
        name="ck_operator_candidate_objective_probability",
    ),
    CheckConstraint(
        _canonical_nonnegative_decimal_check("expected_broken_legs_decimal"),
        name="ck_operator_candidate_expected_broken_legs",
    ),
    CheckConstraint(
        "break_even_bonus_minor IS NULL OR break_even_bonus_minor >= 0",
        name="ck_operator_candidate_break_even",
    ),
    CheckConstraint(
        "break_even_to_official_median_decimal IS NULL OR "
        + _canonical_nonnegative_decimal_check(
            "break_even_to_official_median_decimal"
        ),
        name="ck_operator_candidate_median_multiple",
    ),
)


operator_candidate_dead_faces = Table(
    "operator_candidate_dead_faces",
    metadata,
    Column("candidate_dead_face_id", Text, primary_key=True),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("dead_face_index", Integer, nullable=False),
    Column("official_match_no", Text, nullable=False),
    Column("face_code", Text, nullable=False),
    CheckConstraint("dead_face_index >= 0", name="ck_operator_candidate_dead_face_index"),
    UniqueConstraint(
        "candidate_revision_id",
        "dead_face_index",
        name="uq_operator_candidate_dead_face_index",
    ),
    UniqueConstraint(
        "candidate_revision_id",
        "official_match_no",
        "face_code",
        name="uq_operator_candidate_dead_face",
    ),
)


operator_candidate_audit_findings = Table(
    "operator_candidate_audit_findings",
    metadata,
    Column("candidate_audit_finding_id", Text, primary_key=True),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("finding_index", Integer, nullable=False),
    Column("audit_kind", Text, nullable=False),
    Column("finding_code", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("official_match_no", Text, nullable=True),
    Column("rule_id", Text, nullable=True),
    CheckConstraint("finding_index >= 0", name="ck_operator_candidate_finding_index"),
    CheckConstraint(
        "audit_kind IN ('legs', 'prescription_difference', 'budget', 'deployment')",
        name="ck_operator_candidate_audit_kind",
    ),
    CheckConstraint(
        "severity IN ('WARN', 'ERROR')",
        name="ck_operator_candidate_audit_severity",
    ),
    UniqueConstraint(
        "candidate_revision_id",
        "finding_index",
        name="uq_operator_candidate_finding_index",
    ),
)


operator_candidate_selections = Table(
    "operator_candidate_selections",
    metadata,
    Column("candidate_selection_id", Text, primary_key=True),
    Column("candidate_selection_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_selections.candidate_selection_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "candidate_set_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
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
    Column("reason", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("selected_at", Text, nullable=False),
    CheckConstraint(
        "revision_no >= 1",
        name="ck_operator_candidate_selection_revision_positive",
    ),
    CheckConstraint("length(trim(reason)) > 0", name="ck_operator_candidate_selection_reason"),
    UniqueConstraint(
        "candidate_selection_family_id",
        "revision_no",
        name="uq_operator_candidate_selection_family_revision",
    ),
)


operator_ticket_decision_lineage_revisions = Table(
    "operator_ticket_decision_lineage_revisions",
    metadata,
    Column("lineage_revision_id", Text, primary_key=True),
    Column("lineage_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_decision_lineage_revisions."
            "lineage_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "ticket_batch_revision_id",
        Text,
        ForeignKey("ticket_batch_revisions.ticket_batch_revision_id", ondelete="RESTRICT"),
        nullable=False,
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
    Column(
        "judgment_prescription_revision_id",
        Text,
        ForeignKey(
            "operator_judgment_prescription_revisions.judgment_prescription_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "candidate_set_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "candidate_selection_id",
        Text,
        ForeignKey(
            "operator_candidate_selections.candidate_selection_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("audit_policy_version", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint(
        "revision_no >= 1",
        name="ck_operator_ticket_decision_lineage_revision_positive",
    ),
    UniqueConstraint(
        "lineage_family_id",
        "revision_no",
        name="uq_operator_ticket_decision_lineage_family_revision",
    ),
    UniqueConstraint(
        "ticket_batch_revision_id",
        "action_id",
        name="uq_operator_ticket_decision_lineage_batch_action",
    ),
)


operator_ticket_decision_lineage_items = Table(
    "operator_ticket_decision_lineage_items",
    metadata,
    Column("lineage_item_id", Text, primary_key=True),
    Column(
        "lineage_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_decision_lineage_revisions."
            "lineage_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("item_index", Integer, nullable=False),
    Column(
        "candidate_ticket_id",
        Text,
        ForeignKey("operator_candidate_tickets.candidate_ticket_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("ticket_index", Integer, nullable=False),
    Column(
        "candidate_ticket_leg_id",
        Text,
        ForeignKey(
            "operator_candidate_ticket_legs.candidate_ticket_leg_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("leg_index", Integer, nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey(
            "official_offer_revisions.official_offer_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"), nullable=False),
    Column(
        "market_definition_id",
        Text,
        ForeignKey("market_definitions.market_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("selection_code", Text, nullable=False),
    Column(
        "market_prior_baseline_probability_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_probabilities."
            "market_prior_baseline_probability_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "operator_match_judgment_revision_id",
        Text,
        ForeignKey(
            "operator_match_judgment_revisions.operator_match_judgment_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "forecast_revision_id",
        Text,
        ForeignKey("forecast_revisions.forecast_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint(
        "item_index >= 0 AND ticket_index >= 0 AND leg_index >= 0",
        name="ck_operator_ticket_decision_lineage_item_indexes",
    ),
    UniqueConstraint(
        "lineage_revision_id",
        "item_index",
        name="uq_operator_ticket_decision_lineage_item_index",
    ),
    UniqueConstraint(
        "lineage_revision_id",
        "candidate_ticket_leg_id",
        name="uq_operator_ticket_decision_lineage_candidate_leg",
    ),
)


operator_ticket_audit_override_receipts = Table(
    "operator_ticket_audit_override_receipts",
    metadata,
    Column("ticket_audit_override_receipt_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("receipt_index", Integer, nullable=False),
    Column(
        "adjudication_id",
        Text,
        ForeignKey("adjudications.adjudication_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "ticket_batch_revision_id",
        Text,
        ForeignKey("ticket_batch_revisions.ticket_batch_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "lineage_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_decision_lineage_revisions."
            "lineage_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("candidate_content_hash", Text, nullable=False),
    Column(
        "candidate_audit_finding_id",
        Text,
        ForeignKey(
            "operator_candidate_audit_findings.candidate_audit_finding_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("finding_code", Text, nullable=False),
    Column("audit_policy_version", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("rule_ids_json", Text, nullable=False),
    Column("evidence_rejected_json", Text, nullable=False),
    Column("recorded_at", Text, nullable=False),
    CheckConstraint("receipt_index >= 0", name="ck_operator_ticket_override_index"),
    CheckConstraint(
        "length(trim(reason)) > 0",
        name="ck_operator_ticket_override_reason",
    ),
    CheckConstraint(
        "json_valid(evidence_rejected_json) "
        "AND json_array_length(evidence_rejected_json) >= 1",
        name="ck_operator_ticket_override_evidence_rejected",
    ),
    UniqueConstraint(
        "action_id",
        "receipt_index",
        name="uq_operator_ticket_override_action_index",
    ),
    UniqueConstraint(
        "ticket_batch_revision_id",
        "candidate_revision_id",
        "candidate_audit_finding_id",
        "audit_policy_version",
        name="uq_operator_ticket_override_exact_finding",
    ),
)


operator_candidate_generation_override_links = Table(
    "operator_candidate_generation_override_links",
    metadata,
    Column("candidate_generation_override_link_id", Text, primary_key=True),
    Column(
        "generation_request_id",
        Text,
        ForeignKey(
            "operator_candidate_generation_requests.generation_request_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("link_index", Integer, nullable=False),
    Column(
        "override_receipt_id",
        Text,
        ForeignKey(
            "operator_ticket_audit_override_receipts.ticket_audit_override_receipt_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint(
        "link_index >= 0",
        name="ck_operator_candidate_generation_override_link_index",
    ),
    UniqueConstraint(
        "generation_request_id",
        "link_index",
        name="uq_operator_candidate_generation_override_link_index",
    ),
)


operator_no_ticket_revisions = Table(
    "operator_no_ticket_revisions",
    metadata,
    Column("no_ticket_revision_id", Text, primary_key=True),
    Column("no_ticket_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_no_ticket_revisions.no_ticket_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
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
    Column("reason_code", Text, nullable=False),
    Column("reason_basis", Text, nullable=False),
    Column("reason_text", Text, nullable=False),
    Column("rule_ids_json", Text, nullable=False),
    Column("phase", Text, nullable=False),
    Column("requirement_snapshot_hash", Text, nullable=True),
    Column("missing_requirement_ids_json", Text, nullable=False),
    Column("stale_requirement_ids_json", Text, nullable=False),
    Column("conflicting_requirement_ids_json", Text, nullable=False),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "baseline_envelope_revision_id",
        Text,
        ForeignKey(
            "operator_baseline_envelope_revisions.baseline_envelope_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "candidate_set_revision_id",
        Text,
        ForeignKey(
            "operator_candidate_set_revisions.candidate_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "comparison_candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("deployment_outcome", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("recorded_at", Text, nullable=False),
    CheckConstraint(
        "revision_no >= 1",
        name="ck_operator_no_ticket_revision_positive",
    ),
    CheckConstraint(
        "reason_code IN ('human_all_dice', 'evidence_incomplete', "
        "'no_compliant_structure_within_cap', 'discipline_brake', "
        "'operator_discretion')",
        name="ck_operator_no_ticket_reason_code",
    ),
    CheckConstraint(
        "reason_basis IN ('rule_derived', 'operator_judgment')",
        name="ck_operator_no_ticket_reason_basis",
    ),
    CheckConstraint(
        "length(trim(reason_text)) > 0",
        name="ck_operator_no_ticket_reason_text",
    ),
    CheckConstraint(
        "phase IN ('discovery', 'evidence', 'baseline', 'envelope', 'candidate', "
        "'artifact')",
        name="ck_operator_no_ticket_phase",
    ),
    CheckConstraint(
        "deployment_outcome IN ('no_ticket', 'partially_placed', 'reopened')",
        name="ck_operator_no_ticket_deployment_outcome",
    ),
    UniqueConstraint(
        "no_ticket_family_id",
        "revision_no",
        name="uq_operator_no_ticket_family_revision",
    ),
)


operator_no_ticket_offer_scopes = Table(
    "operator_no_ticket_offer_scopes",
    metadata,
    Column("no_ticket_offer_scope_id", Text, primary_key=True),
    Column(
        "no_ticket_revision_id",
        Text,
        ForeignKey("operator_no_ticket_revisions.no_ticket_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("scope_index", Integer, nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey(
            "official_offer_revisions.official_offer_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("effective_cutoff_at", Text, nullable=False),
    CheckConstraint("scope_index >= 0", name="ck_operator_no_ticket_offer_scope_index"),
    UniqueConstraint(
        "no_ticket_revision_id",
        "scope_index",
        name="uq_operator_no_ticket_offer_scope_index",
    ),
    UniqueConstraint(
        "no_ticket_revision_id",
        "official_offer_revision_id",
        name="uq_operator_no_ticket_offer_scope_offer",
    ),
)


operator_no_ticket_artifact_scopes = Table(
    "operator_no_ticket_artifact_scopes",
    metadata,
    Column("no_ticket_artifact_scope_id", Text, primary_key=True),
    Column(
        "no_ticket_revision_id",
        Text,
        ForeignKey("operator_no_ticket_revisions.no_ticket_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("scope_index", Integer, nullable=False),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("effective_cutoff_at", Text, nullable=False),
    CheckConstraint(
        "scope_index >= 0",
        name="ck_operator_no_ticket_artifact_scope_index",
    ),
    UniqueConstraint(
        "no_ticket_revision_id",
        "scope_index",
        name="uq_operator_no_ticket_artifact_scope_index",
    ),
    UniqueConstraint(
        "no_ticket_revision_id",
        "ticket_artifact_id",
        name="uq_operator_no_ticket_artifact_scope_artifact",
    ),
)


operator_no_ticket_command_receipts = Table(
    "operator_no_ticket_command_receipts",
    metadata,
    Column("no_ticket_command_receipt_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("command_kind", Text, nullable=False),
    Column(
        "no_ticket_revision_id",
        Text,
        ForeignKey("operator_no_ticket_revisions.no_ticket_revision_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("submitted_task_snapshot_hash", Text, nullable=False),
    Column("resolved_task_snapshot_hash", Text, nullable=False),
    Column("result", Text, nullable=False),
    Column("received_at", Text, nullable=False),
    CheckConstraint(
        "command_kind IN ('record_no_ticket', 'supersede_no_ticket')",
        name="ck_operator_no_ticket_command_kind",
    ),
    CheckConstraint(
        "result IN ('recorded', 'task_snapshot_changed', 'already_current')",
        name="ck_operator_no_ticket_command_result",
    ),
    CheckConstraint(
        "(result IN ('recorded', 'already_current') "
        "AND no_ticket_revision_id IS NOT NULL) "
        "OR (result = 'task_snapshot_changed' AND no_ticket_revision_id IS NULL)",
        name="ck_operator_no_ticket_command_revision_result",
    ),
)


__all__ = [
    "operator_baseline_envelope_bundle_faces",
    "operator_baseline_envelope_face_bundles",
    "operator_baseline_envelope_offer_constraints",
    "operator_baseline_envelope_revisions",
    "operator_baseline_envelope_structure_templates",
    "operator_baseline_envelope_template_offers",
    "operator_candidate_audit_findings",
    "operator_candidate_band_outcomes",
    "operator_candidate_dead_faces",
    "operator_candidate_generation_requests",
    "operator_candidate_metrics",
    "operator_candidate_selections",
    "operator_candidate_generation_override_links",
    "operator_candidate_set_revisions",
    "operator_candidates",
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
    "operator_no_ticket_artifact_scopes",
    "operator_no_ticket_command_receipts",
    "operator_no_ticket_offer_scopes",
    "operator_no_ticket_revisions",
    "operator_task_evidence_bundle_items",
    "operator_task_evidence_bundle_revisions",
    "operator_ticket_audit_override_receipts",
    "operator_ticket_decision_lineage_items",
    "operator_ticket_decision_lineage_revisions",
    "operator_worker_jobs",
]
