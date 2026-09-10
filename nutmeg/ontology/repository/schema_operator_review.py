"""Append-only operator review and scoreboard-completion storage."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata

operator_review_items = Table(
    "operator_review_items",
    metadata,
    Column("review_id", Text, primary_key=True),
    Column(
        "review_eligibility_fact_id",
        Text,
        ForeignKey(
            "operator_review_eligibility_facts.review_eligibility_fact_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column("review_kind", Text, nullable=False),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("outcome_revision_ids_json", Text, nullable=False),
    Column(
        "materialized_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("materialized_at", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_operator_review_lane"),
    CheckConstraint(
        "review_kind IN ('operational_data_availability', 'forecast_truth')",
        name="ck_operator_review_kind",
    ),
    CheckConstraint(
        "json_valid(outcome_revision_ids_json) "
        "AND json_type(outcome_revision_ids_json) = 'array'",
        name="ck_operator_review_outcomes_json",
    ),
    CheckConstraint(
        "(review_kind = 'operational_data_availability' "
        "AND market_prior_baseline_revision_id IS NULL "
        "AND json_array_length(outcome_revision_ids_json) = 0) OR "
        "(review_kind = 'forecast_truth' "
        "AND market_prior_baseline_revision_id IS NOT NULL "
        "AND json_array_length(outcome_revision_ids_json) > 0)",
        name="ck_operator_review_readiness_shape",
    ),
)


operator_scoreboard_effect_disposition_revisions = Table(
    "operator_scoreboard_effect_disposition_revisions",
    metadata,
    Column("disposition_revision_id", Text, primary_key=True),
    Column("family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_scoreboard_effect_disposition_revisions.disposition_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "review_id",
        Text,
        ForeignKey("operator_review_items.review_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("disposition", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("pre_update_legacy_sha256", Text, nullable=False),
    Column("required_metric_keys_json", Text, nullable=False),
    Column(
        "created_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_scoreboard_disposition_revision"),
    CheckConstraint(
        "disposition IN ('effect_required', 'no_effect')",
        name="ck_scoreboard_disposition_kind",
    ),
    CheckConstraint("length(trim(reason)) > 0", name="ck_scoreboard_disposition_reason"),
    CheckConstraint(
        "length(pre_update_legacy_sha256) = 64",
        name="ck_scoreboard_disposition_pre_hash",
    ),
    CheckConstraint(
        "json_valid(required_metric_keys_json) "
        "AND json_type(required_metric_keys_json) = 'array'",
        name="ck_scoreboard_disposition_metrics_json",
    ),
    CheckConstraint(
        "(disposition = 'effect_required' "
        "AND json_array_length(required_metric_keys_json) > 0) OR "
        "(disposition = 'no_effect' "
        "AND json_array_length(required_metric_keys_json) = 0)",
        name="ck_scoreboard_disposition_metric_shape",
    ),
    UniqueConstraint(
        "family_id",
        "revision_no",
        name="uq_scoreboard_disposition_family_revision",
    ),
    UniqueConstraint(
        "review_id",
        "revision_no",
        name="uq_scoreboard_disposition_review_revision",
    ),
)


operator_scoreboard_review_observation_links = Table(
    "operator_scoreboard_review_observation_links",
    metadata,
    Column("observation_link_id", Text, primary_key=True),
    Column(
        "review_id",
        Text,
        ForeignKey("operator_review_items.review_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "disposition_revision_id",
        Text,
        ForeignKey(
            "operator_scoreboard_effect_disposition_revisions.disposition_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("metric_key", Text, nullable=False),
    Column(
        "scoreboard_observation_id",
        Text,
        ForeignKey("scoreboard_observations.scoreboard_observation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "observation_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("observed_legacy_sha256", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("length(trim(metric_key)) > 0", name="ck_review_observation_metric"),
    CheckConstraint(
        "length(observed_legacy_sha256) = 64",
        name="ck_review_observation_hash",
    ),
    UniqueConstraint(
        "disposition_revision_id",
        "metric_key",
        name="uq_review_observation_disposition_metric",
    ),
)


operator_scoreboard_review_completion_requests = Table(
    "operator_scoreboard_review_completion_requests",
    metadata,
    Column("completion_request_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "review_id",
        Text,
        ForeignKey("operator_review_items.review_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "disposition_revision_id",
        Text,
        ForeignKey(
            "operator_scoreboard_effect_disposition_revisions.disposition_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("shadow_review_token", Text, nullable=False),
    # The request preserves Jun's exact signed selection. The worker validates
    # the identifier against the shadow-review table before a receipt can exist.
    Column("shadow_review_id", Text, nullable=False),
    Column("shadow_source_high_watermark", Integer, nullable=False),
    Column("compared_legacy_sha256", Text, nullable=False),
    Column("metric_keys_json", Text, nullable=False),
    Column("observation_action_ids_json", Text, nullable=False),
    Column("requested_at", Text, nullable=False),
    CheckConstraint(
        "length(trim(shadow_review_token)) > 0",
        name="ck_review_completion_request_token",
    ),
    CheckConstraint(
        "shadow_source_high_watermark >= 0",
        name="ck_review_completion_request_watermark",
    ),
    CheckConstraint(
        "length(compared_legacy_sha256) = 64",
        name="ck_review_completion_request_hash",
    ),
    CheckConstraint(
        "json_valid(metric_keys_json) AND json_type(metric_keys_json) = 'array' "
        "AND json_array_length(metric_keys_json) > 0",
        name="ck_review_completion_request_metrics",
    ),
    CheckConstraint(
        "json_valid(observation_action_ids_json) "
        "AND json_type(observation_action_ids_json) = 'array' "
        "AND json_array_length(observation_action_ids_json) > 0",
        name="ck_review_completion_request_observations",
    ),
)


operator_scoreboard_review_completion_receipts = Table(
    "operator_scoreboard_review_completion_receipts",
    metadata,
    Column("completion_receipt_id", Text, primary_key=True),
    Column(
        "review_id",
        Text,
        ForeignKey("operator_review_items.review_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "disposition_revision_id",
        Text,
        ForeignKey(
            "operator_scoreboard_effect_disposition_revisions.disposition_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column(
        "completion_request_id",
        Text,
        ForeignKey(
            "operator_scoreboard_review_completion_requests.completion_request_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("post_update_legacy_sha256", Text, nullable=True),
    Column("observation_action_ids_json", Text, nullable=True),
    Column(
        "shadow_review_id",
        Text,
        ForeignKey(
            "scoreboard_shadow_reviews.scoreboard_shadow_review_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("shadow_source_high_watermark", Integer, nullable=True),
    Column(
        "completed_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("completed_at", Text, nullable=False),
    CheckConstraint(
        "(completion_request_id IS NULL "
        "AND post_update_legacy_sha256 IS NULL "
        "AND observation_action_ids_json IS NULL "
        "AND shadow_review_id IS NULL "
        "AND shadow_source_high_watermark IS NULL) OR "
        "(completion_request_id IS NOT NULL "
        "AND length(post_update_legacy_sha256) = 64 "
        "AND json_valid(observation_action_ids_json) "
        "AND json_type(observation_action_ids_json) = 'array' "
        "AND json_array_length(observation_action_ids_json) > 0 "
        "AND shadow_review_id IS NOT NULL "
        "AND shadow_source_high_watermark >= 0)",
        name="ck_review_completion_receipt_shape",
    ),
)


__all__ = [
    "operator_review_items",
    "operator_scoreboard_effect_disposition_revisions",
    "operator_scoreboard_review_completion_receipts",
    "operator_scoreboard_review_completion_requests",
    "operator_scoreboard_review_observation_links",
]
