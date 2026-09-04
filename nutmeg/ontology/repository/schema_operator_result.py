"""Normalized operator candidate composition and later result storage."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata


def _canonical_decimal_check(column_name: str, *, positive: bool = False) -> str:
    bound = f"AND CAST({column_name} AS REAL) > 0.0" if positive else ""
    return (
        f"typeof({column_name}) = 'text' "
        f"AND printf('%.12f', CAST({column_name} AS REAL)) = {column_name} {bound}"
    )


zucai_fixed_prize_policy_revisions = Table(
    "zucai_fixed_prize_policy_revisions",
    metadata,
    Column("fixed_prize_policy_revision_id", Text, primary_key=True),
    Column("fixed_prize_policy_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "zucai_fixed_prize_policy_revisions.fixed_prize_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("policy_version", Text, nullable=False),
    Column("ticket_kind", Text, nullable=False),
    Column("currency", Text, nullable=False),
    Column("standard_unit_stake_minor", Integer, nullable=False),
    Column("official_void_rule", Text, nullable=False),
    Column("effective_at", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_zucai_fixed_policy_revision"),
    CheckConstraint("ticket_kind IN ('sfc', 'renjiu')", name="ck_zucai_fixed_policy_kind"),
    CheckConstraint("length(currency) = 3", name="ck_zucai_fixed_policy_currency"),
    CheckConstraint(
        "standard_unit_stake_minor > 0",
        name="ck_zucai_fixed_policy_unit_stake",
    ),
    CheckConstraint(
        "official_void_rule = 'all_faces_match'",
        name="ck_zucai_fixed_policy_void_rule",
    ),
    UniqueConstraint(
        "fixed_prize_policy_family_id",
        "revision_no",
        name="uq_zucai_fixed_policy_revision",
    ),
)


zucai_fixed_prize_policy_tiers = Table(
    "zucai_fixed_prize_policy_tiers",
    metadata,
    Column("fixed_prize_policy_tier_id", Text, primary_key=True),
    Column(
        "fixed_prize_policy_revision_id",
        Text,
        ForeignKey(
            "zucai_fixed_prize_policy_revisions.fixed_prize_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("tier_index", Integer, nullable=False),
    Column("tier_code", Text, nullable=False),
    Column("required_correct_count", Integer, nullable=False),
    CheckConstraint("tier_index >= 0", name="ck_zucai_fixed_policy_tier_index"),
    CheckConstraint(
        "required_correct_count BETWEEN 1 AND 14",
        name="ck_zucai_fixed_policy_tier_correct",
    ),
    UniqueConstraint(
        "fixed_prize_policy_revision_id",
        "tier_index",
        name="uq_zucai_fixed_policy_tier_index",
    ),
    UniqueConstraint(
        "fixed_prize_policy_revision_id",
        "tier_code",
        name="uq_zucai_fixed_policy_tier_code",
    ),
    UniqueConstraint(
        "fixed_prize_policy_revision_id",
        "required_correct_count",
        name="uq_zucai_fixed_policy_tier_correct",
    ),
)


operator_candidate_tickets = Table(
    "operator_candidate_tickets",
    metadata,
    Column("candidate_ticket_id", Text, primary_key=True),
    Column(
        "candidate_revision_id",
        Text,
        ForeignKey("operator_candidates.candidate_revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("ticket_index", Integer, nullable=False),
    Column("ticket_kind", Text, nullable=False),
    Column("structure_code", Text, nullable=False),
    Column("group_code", Text, nullable=True),
    Column("currency", Text, nullable=False),
    Column("unit_stake_minor", Integer, nullable=False),
    Column("unit_count", Integer, nullable=False),
    Column("stake_minor", Integer, nullable=False),
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
    CheckConstraint("ticket_index >= 0", name="ck_operator_candidate_ticket_index"),
    CheckConstraint(
        "ticket_kind IN ('jczq_pass', 'sfc', 'renjiu')",
        name="ck_operator_candidate_ticket_kind",
    ),
    CheckConstraint("length(currency) = 3", name="ck_operator_candidate_ticket_currency"),
    CheckConstraint(
        "unit_stake_minor > 0 AND unit_count > 0 "
        "AND stake_minor = unit_stake_minor * unit_count",
        name="ck_operator_candidate_ticket_stake",
    ),
    CheckConstraint(
        "(ticket_kind = 'jczq_pass' AND fixed_prize_policy_revision_id IS NULL) "
        "OR (ticket_kind IN ('sfc', 'renjiu') "
        "AND fixed_prize_policy_revision_id IS NOT NULL)",
        name="ck_operator_candidate_ticket_policy",
    ),
    UniqueConstraint(
        "candidate_revision_id",
        "ticket_index",
        name="uq_operator_candidate_ticket_index",
    ),
    UniqueConstraint(
        "candidate_revision_id",
        "composition_hash",
        name="uq_operator_candidate_ticket_composition",
    ),
)


operator_candidate_ticket_legs = Table(
    "operator_candidate_ticket_legs",
    metadata,
    Column("candidate_ticket_leg_id", Text, primary_key=True),
    Column(
        "candidate_ticket_id",
        Text,
        ForeignKey("operator_candidate_tickets.candidate_ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("leg_index", Integer, nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey("official_offer_revisions.official_offer_revision_id", ondelete="RESTRICT"),
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
        "quote_id",
        Text,
        ForeignKey("market_quotes.quote_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("booked_decimal_odds", Text, nullable=True),
    Column("settlement_parameter_decimal", Text, nullable=True),
    CheckConstraint("leg_index >= 0", name="ck_operator_candidate_leg_index"),
    CheckConstraint(
        "booked_decimal_odds IS NULL OR "
        + _canonical_decimal_check("booked_decimal_odds", positive=True),
        name="ck_operator_candidate_leg_odds",
    ),
    CheckConstraint(
        "settlement_parameter_decimal IS NULL OR "
        + _canonical_decimal_check("settlement_parameter_decimal"),
        name="ck_operator_candidate_leg_parameter",
    ),
    CheckConstraint(
        "(quote_id IS NULL AND booked_decimal_odds IS NULL "
        "AND settlement_parameter_decimal IS NULL) "
        "OR (quote_id IS NOT NULL AND booked_decimal_odds IS NOT NULL)",
        name="ck_operator_candidate_leg_quote_shape",
    ),
    UniqueConstraint(
        "candidate_ticket_id",
        "leg_index",
        name="uq_operator_candidate_leg_index",
    ),
    UniqueConstraint(
        "candidate_ticket_id",
        "official_offer_revision_id",
        "market_definition_id",
        "selection_code",
        name="uq_operator_candidate_leg_selection",
    ),
)


operator_review_eligibility_facts = Table(
    "operator_review_eligibility_facts",
    metadata,
    Column("review_eligibility_fact_id", Text, primary_key=True),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("fact_index", Integer, nullable=False),
    Column("terminal_trigger", Text, nullable=False),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "no_ticket_revision_id",
        Text,
        ForeignKey("operator_no_ticket_revisions.no_ticket_revision_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "artifact_terminal_receipt_id",
        Text,
        ForeignKey(
            "operator_artifact_terminal_receipts.artifact_terminal_receipt_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "market_prior_baseline_revision_id",
        Text,
        ForeignKey(
            "operator_market_prior_baseline_revisions.market_prior_baseline_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("review_kind", Text, nullable=False),
    Column("readiness_condition", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint(
        "fact_index >= 0",
        name="ck_operator_review_eligibility_fact_index",
    ),
    CheckConstraint(
        "terminal_trigger IN ('no_ticket', 'artifact_terminal', "
        "'official_cancellation')",
        name="ck_operator_review_eligibility_terminal_trigger",
    ),
    CheckConstraint(
        "(terminal_trigger = 'no_ticket' "
        "AND no_ticket_revision_id IS NOT NULL "
        "AND artifact_terminal_receipt_id IS NULL) OR "
        "(terminal_trigger IN ('artifact_terminal', 'official_cancellation') "
        "AND no_ticket_revision_id IS NULL "
        "AND artifact_terminal_receipt_id IS NOT NULL)",
        name="ck_operator_review_eligibility_source",
    ),
    CheckConstraint(
        "review_kind IN ('operational_data_availability', 'forecast_truth')",
        name="ck_operator_review_eligibility_review_kind",
    ),
    CheckConstraint(
        "readiness_condition IN ('immediate', 'outcomes_required')",
        name="ck_operator_review_eligibility_readiness",
    ),
    CheckConstraint(
        "(review_kind = 'operational_data_availability' "
        "AND readiness_condition = 'immediate' "
        "AND market_prior_baseline_revision_id IS NULL) OR "
        "(review_kind = 'forecast_truth' "
        "AND readiness_condition = 'outcomes_required' "
        "AND market_prior_baseline_revision_id IS NOT NULL)",
        name="ck_operator_review_eligibility_kind_readiness",
    ),
    UniqueConstraint(
        "action_id",
        "fact_index",
        name="uq_operator_review_eligibility_action_index",
    ),
)


__all__ = [
    "operator_candidate_ticket_legs",
    "operator_candidate_tickets",
    "operator_review_eligibility_facts",
    "zucai_fixed_prize_policy_revisions",
    "zucai_fixed_prize_policy_tiers",
]
