"""Official sale-slate storage for the dual-lane operator."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata

official_sale_slate_revisions = Table(
    "official_sale_slate_revisions",
    metadata,
    Column("slate_revision_id", Text, primary_key=True),
    Column("slate_family_id", Text, nullable=False, index=True),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "source_artifact_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("published_at", Text, nullable=False),
    Column("retrieved_at", Text, nullable=False),
    Column("valid_from", Text, nullable=False),
    Column(
        "supersedes_slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    ),
    Column("content_hash", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_official_slates_lane"),
    CheckConstraint("revision_no >= 1", name="ck_official_slates_revision"),
    UniqueConstraint("lane", "business_key", "revision_no", name="uq_official_slates_revision"),
    UniqueConstraint("slate_family_id", "content_hash", name="uq_official_slates_content"),
)

official_offer_families = Table(
    "official_offer_families",
    metadata,
    Column("official_offer_family_id", Text, primary_key=True),
    Column("lane", Text, nullable=False, index=True),
    Column("business_key", Text, nullable=False, index=True),
    Column("official_match_no", Text, nullable=False),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_official_offer_families_lane"),
    UniqueConstraint(
        "lane",
        "business_key",
        "official_match_no",
        "match_id",
        name="uq_official_offer_family_identity",
    ),
)

official_offer_revisions = Table(
    "official_offer_revisions",
    metadata,
    Column("official_offer_revision_id", Text, primary_key=True),
    Column(
        "official_offer_family_id",
        Text,
        ForeignKey("official_offer_families.official_offer_family_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("official_match_no", Text, nullable=False),
    Column("market_definition_ids_json", Text, nullable=False),
    Column("sale_opens_at", Text, nullable=False),
    Column("sale_deadline_at", Text, nullable=False),
    Column("status", Text, nullable=False),
    CheckConstraint(
        "status IN ('scheduled', 'on_sale', 'sale_closed', 'cancelled')",
        name="ck_official_offer_status",
    ),
    UniqueConstraint(
        "slate_revision_id",
        "official_offer_family_id",
        name="uq_official_offer_per_slate",
    ),
    UniqueConstraint(
        "slate_revision_id",
        "official_match_no",
        name="uq_official_offer_number_per_slate",
    ),
)

official_schedule_check_receipts = Table(
    "official_schedule_check_receipts",
    metadata,
    Column("schedule_check_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("lane", Text, nullable=False, index=True),
    Column("shanghai_check_date", Text, nullable=False, index=True),
    Column("checked_at", Text, nullable=False),
    Column(
        "source_run_id",
        Text,
        ForeignKey("source_runs.source_run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("check_state", Text, nullable=False),
    Column("parser_contract_version", Text, nullable=True),
    Column("official_source_content_hash", Text, nullable=True),
    Column(
        "official_source_artifact_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("observed_business_keys_json", Text, nullable=False),
    Column("imported_business_keys_json", Text, nullable=False),
    Column("error_code", Text, nullable=True),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_official_schedule_checks_lane"),
    CheckConstraint(
        "check_state IN ('slate_imported', 'confirmed_no_sale', 'failed')",
        name="ck_official_schedule_check_state",
    ),
    UniqueConstraint(
        "source_run_id",
        "lane",
        "shanghai_check_date",
        name="uq_official_schedule_check_run_scope",
    ),
)

__all__ = [
    "official_offer_families",
    "official_offer_revisions",
    "official_sale_slate_revisions",
    "official_schedule_check_receipts",
]
