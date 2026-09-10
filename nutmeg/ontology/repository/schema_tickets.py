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

ticket_shadow_records = Table(
    "ticket_shadow_records",
    metadata,
    Column("ticket_shadow_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "confirmation_id",
        Text,
        ForeignKey("ticket_confirmation_challenges.confirmation_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("reason", Text, nullable=False),
    Column("deadline_at", Text, nullable=False),
    Column("marked_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
)


operator_artifact_work_item_links = Table(
    "operator_artifact_work_item_links",
    metadata,
    Column("artifact_work_item_link_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
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
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("linked_at", Text, nullable=False),
)


operator_protected_artifact_bindings = Table(
    "operator_protected_artifact_bindings",
    metadata,
    Column("protected_artifact_binding_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "lineage_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_decision_lineage_revisions.lineage_revision_id",
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
    Column(
        "candidate_ticket_id",
        Text,
        ForeignKey("operator_candidate_tickets.candidate_ticket_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("ticket_index", Integer, nullable=False),
    Column("ticket_kind", Text, nullable=False),
    Column("stake_minor", Integer, nullable=False),
    Column("currency", Text, nullable=False),
    Column("composition_hash", Text, nullable=False),
    Column(
        "fixed_prize_policy_revision_id",
        Text,
        ForeignKey(
            "zucai_fixed_prize_policy_revisions.fixed_prize_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("frozen_deadline_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint(
        "ticket_index >= 0",
        name="ck_operator_protected_artifact_ticket_index",
    ),
    CheckConstraint(
        "ticket_kind IN ('jczq_pass', 'sfc', 'renjiu')",
        name="ck_operator_protected_artifact_ticket_kind",
    ),
    CheckConstraint(
        "stake_minor > 0",
        name="ck_operator_protected_artifact_stake_minor",
    ),
    CheckConstraint(
        "length(currency) = 3",
        name="ck_operator_protected_artifact_currency",
    ),
    CheckConstraint(
        "(ticket_kind = 'jczq_pass' AND fixed_prize_policy_revision_id IS NULL) "
        "OR (ticket_kind IN ('sfc', 'renjiu') "
        "AND fixed_prize_policy_revision_id IS NOT NULL)",
        name="ck_operator_protected_artifact_policy",
    ),
    UniqueConstraint(
        "candidate_revision_id",
        "ticket_index",
        name="uq_operator_protected_artifact_candidate_ticket_index",
    ),
)


operator_protected_artifact_offer_revision_links = Table(
    "operator_protected_artifact_offer_revision_links",
    metadata,
    Column("protected_artifact_offer_revision_link_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey(
            "operator_protected_artifact_bindings.ticket_artifact_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("offer_index", Integer, nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey(
            "official_offer_revisions.official_offer_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    CheckConstraint(
        "offer_index >= 0",
        name="ck_operator_protected_artifact_offer_index",
    ),
    UniqueConstraint(
        "ticket_artifact_id",
        "offer_index",
        name="uq_operator_protected_artifact_offer_index",
    ),
    UniqueConstraint(
        "ticket_artifact_id",
        "official_offer_revision_id",
        name="uq_operator_protected_artifact_offer_revision",
    ),
)


operator_confirmation_challenge_revisions = Table(
    "operator_confirmation_challenge_revisions",
    metadata,
    Column("challenge_revision_id", Text, primary_key=True),
    Column("challenge_family_id", Text, nullable=False, index=True),
    Column("legacy_confirmation_id", Text, nullable=True, unique=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_confirmation_challenge_revisions.challenge_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("artifact_composition_hash", Text, nullable=False),
    Column(
        "lineage_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_decision_lineage_revisions.lineage_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("nonce_hash", Text, nullable=False, unique=True),
    Column("issued_at", Text, nullable=False),
    Column("effective_cutoff_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint(
        "revision_no >= 1",
        name="ck_operator_confirmation_challenge_revision_positive",
    ),
    UniqueConstraint(
        "challenge_family_id",
        "revision_no",
        name="uq_operator_confirmation_challenge_family_revision",
    ),
)


operator_confirmation_challenge_heads = Table(
    "operator_confirmation_challenge_heads",
    metadata,
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "challenge_revision_id",
        Text,
        ForeignKey(
            "operator_confirmation_challenge_revisions.challenge_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column("challenge_family_id", Text, nullable=False),
    Column("revision_no", Integer, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint(
        "revision_no >= 1",
        name="ck_operator_confirmation_challenge_head_revision_positive",
    ),
)


operator_artifact_terminal_receipts = Table(
    "operator_artifact_terminal_receipts",
    metadata,
    Column("artifact_terminal_receipt_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "challenge_revision_id",
        Text,
        ForeignKey(
            "operator_confirmation_challenge_revisions.challenge_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("terminal_kind", Text, nullable=False),
    Column("terminal_reason", Text, nullable=False),
    Column("effective_cutoff_at", Text, nullable=False),
    Column("terminal_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    CheckConstraint(
        "terminal_kind IN ('placed', 'shadow')",
        name="ck_operator_artifact_terminal_kind",
    ),
    CheckConstraint(
        "(terminal_kind = 'placed' AND terminal_reason = "
        "'actual_placement_confirmed') OR "
        "(terminal_kind = 'shadow' AND terminal_reason IN "
        "('confirmation_not_requested', 'deadline_unconfirmed', 'human_no_ticket', "
        "'official_deadline_shortened', 'official_offer_cancelled'))",
        name="ck_operator_artifact_terminal_reason",
    ),
)


__all__ = [
    "audited_ticket_artifacts",
    "operator_artifact_terminal_receipts",
    "operator_artifact_work_item_links",
    "operator_confirmation_challenge_heads",
    "operator_confirmation_challenge_revisions",
    "operator_protected_artifact_bindings",
    "operator_protected_artifact_offer_revision_links",
    "ticket_batch_revisions",
    "ticket_confirmation_challenges",
    "ticket_placements",
    "ticket_shadow_records",
]
