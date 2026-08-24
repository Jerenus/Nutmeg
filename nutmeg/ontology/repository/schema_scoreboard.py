"""Governed scoreboard tables introduced by migration 13."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Integer, Table, Text

from nutmeg.ontology.repository.schema import metadata

scoreboard_observations = Table(
    "scoreboard_observations",
    metadata,
    Column("scoreboard_observation_id", Text, primary_key=True),
    Column("group_key", Text, nullable=False, index=True),
    Column("metric_key", Text, nullable=False, index=True),
    Column("tally", Text, nullable=False),
    Column("detail", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("numerator", Float, nullable=True),
    Column("denominator", Float, nullable=True),
    Column("value", Float, nullable=True),
    Column("unit", Text, nullable=True),
    Column("evidence_refs_json", Text, nullable=False),
    Column("effective_at", Text, nullable=False),
    Column("recorded_at", Text, nullable=False),
    Column(
        "supersedes_observation_id",
        Text,
        ForeignKey(
            "scoreboard_observations.scoreboard_observation_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    CheckConstraint(
        "denominator IS NULL OR denominator >= 0",
        name="ck_scoreboard_observation_denominator",
    ),
)

scoreboard_shadow_reviews = Table(
    "scoreboard_shadow_reviews",
    metadata,
    Column("scoreboard_shadow_review_id", Text, primary_key=True),
    Column(
        "legacy_source_artifact_id",
        Text,
        ForeignKey("source_artifacts.artifact_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("legacy_sha256", Text, nullable=False),
    Column("projection_version", Text, nullable=False),
    Column("source_high_watermark", Integer, nullable=False),
    Column("classification_json", Text, nullable=False),
    Column("matched_count", Integer, nullable=False),
    Column("manual_count", Integer, nullable=False),
    Column("corrected_count", Integer, nullable=False),
    Column("unexplained_count", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("reviewed_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    CheckConstraint(
        "source_high_watermark >= 0",
        name="ck_scoreboard_review_watermark",
    ),
    CheckConstraint(
        "matched_count >= 0 AND manual_count >= 0 AND corrected_count >= 0 "
        "AND unexplained_count >= 0",
        name="ck_scoreboard_review_counts",
    ),
)

scoreboard_authority = Table(
    "scoreboard_authority",
    metadata,
    Column("authority_id", Text, primary_key=True),
    Column("state", Text, nullable=False),
    Column("projection_version", Text, nullable=True),
    Column("source_high_watermark", Integer, nullable=True),
    Column("legacy_sha256", Text, nullable=True),
    Column(
        "shadow_review_id",
        Text,
        ForeignKey(
            "scoreboard_shadow_reviews.scoreboard_shadow_review_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("compatibility_export_sha256", Text, nullable=True),
    Column("approved_at", Text, nullable=True),
    Column(
        "approved_by_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("version", Integer, nullable=False),
    CheckConstraint("authority_id = 'primary'", name="ck_scoreboard_authority_singleton"),
    CheckConstraint("version > 0", name="ck_scoreboard_authority_version"),
    CheckConstraint(
        "source_high_watermark IS NULL OR source_high_watermark >= 0",
        name="ck_scoreboard_authority_watermark",
    ),
)
