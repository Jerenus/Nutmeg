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
        "settlement_run_id",
        Text,
        ForeignKey(
            "operator_task_settlement_runs.settlement_run_id",
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
        "'official_cancellation', 'settlement')",
        name="ck_operator_review_eligibility_terminal_trigger",
    ),
    CheckConstraint(
        "(terminal_trigger = 'no_ticket' "
        "AND no_ticket_revision_id IS NOT NULL "
        "AND artifact_terminal_receipt_id IS NULL "
        "AND settlement_run_id IS NULL) OR "
        "(terminal_trigger IN ('artifact_terminal', 'official_cancellation') "
        "AND no_ticket_revision_id IS NULL "
        "AND artifact_terminal_receipt_id IS NOT NULL "
        "AND settlement_run_id IS NULL) OR "
        "(terminal_trigger = 'settlement' "
        "AND no_ticket_revision_id IS NULL "
        "AND artifact_terminal_receipt_id IS NULL "
        "AND settlement_run_id IS NOT NULL)",
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
    UniqueConstraint(
        "settlement_run_id",
        name="uq_operator_review_eligibility_settlement_run",
    ),
)


operator_ticket_notes = Table(
    "operator_ticket_notes",
    metadata,
    Column("ticket_note_id", Text, primary_key=True),
    Column(
        "ticket_id",
        Text,
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("note_index", Integer, nullable=False),
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
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("note_index >= 0", name="ck_operator_ticket_note_index"),
    CheckConstraint(
        "ticket_kind IN ('jczq_pass', 'sfc', 'renjiu')",
        name="ck_operator_ticket_note_kind",
    ),
    CheckConstraint("length(currency) = 3", name="ck_operator_ticket_note_currency"),
    CheckConstraint(
        "unit_stake_minor > 0 AND unit_count > 0 "
        "AND stake_minor = unit_stake_minor * unit_count",
        name="ck_operator_ticket_note_stake",
    ),
    CheckConstraint(
        "(ticket_kind = 'jczq_pass' AND fixed_prize_policy_revision_id IS NULL) "
        "OR (ticket_kind IN ('sfc', 'renjiu') "
        "AND fixed_prize_policy_revision_id IS NOT NULL)",
        name="ck_operator_ticket_note_policy",
    ),
    UniqueConstraint("ticket_id", "note_index", name="uq_operator_ticket_note_index"),
    UniqueConstraint(
        "ticket_id",
        "composition_hash",
        name="uq_operator_ticket_note_composition",
    ),
)


operator_ticket_note_legs = Table(
    "operator_ticket_note_legs",
    metadata,
    Column("ticket_note_leg_id", Text, primary_key=True),
    Column(
        "ticket_note_id",
        Text,
        ForeignKey("operator_ticket_notes.ticket_note_id", ondelete="RESTRICT"),
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
    Column(
        "fixed_prize_policy_revision_id",
        Text,
        ForeignKey(
            "zucai_fixed_prize_policy_revisions.fixed_prize_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("leg_index >= 0", name="ck_operator_ticket_note_leg_index"),
    CheckConstraint(
        "booked_decimal_odds IS NULL OR "
        + _canonical_decimal_check("booked_decimal_odds", positive=True),
        name="ck_operator_ticket_note_leg_odds",
    ),
    CheckConstraint(
        "settlement_parameter_decimal IS NULL OR "
        + _canonical_decimal_check("settlement_parameter_decimal"),
        name="ck_operator_ticket_note_leg_parameter",
    ),
    CheckConstraint(
        "(fixed_prize_policy_revision_id IS NULL "
        "AND quote_id IS NOT NULL AND booked_decimal_odds IS NOT NULL) OR "
        "(fixed_prize_policy_revision_id IS NOT NULL "
        "AND quote_id IS NULL AND booked_decimal_odds IS NULL "
        "AND settlement_parameter_decimal IS NULL)",
        name="ck_operator_ticket_note_leg_kind_shape",
    ),
    UniqueConstraint(
        "ticket_note_id",
        "leg_index",
        name="uq_operator_ticket_note_leg_index",
    ),
)


operator_placement_cash_links = Table(
    "operator_placement_cash_links",
    metadata,
    Column("placement_cash_link_id", Text, primary_key=True),
    Column(
        "ticket_id",
        Text,
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "transaction_id",
        Text,
        ForeignKey("cash_transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("stake_minor", Integer, nullable=False),
    Column("currency", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("stake_minor > 0", name="ck_operator_placement_cash_stake"),
    CheckConstraint("length(currency) = 3", name="ck_operator_placement_cash_currency"),
)


operator_telegram_owner_heartbeats = Table(
    "operator_telegram_owner_heartbeats",
    metadata,
    Column("telegram_owner_heartbeat_id", Text, primary_key=True),
    Column("account_id", Text, nullable=False),
    Column("owner_instance_id", Text, nullable=False),
    Column("transport_label", Text, nullable=False),
    Column("owner_mode", Text, nullable=False),
    Column("router_version", Text, nullable=False),
    Column("heartbeat_sequence", Integer, nullable=False),
    Column("observed_at", Text, nullable=False),
    Column("lease_expires_at", Text, nullable=False),
    Column(
        "registration_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    CheckConstraint(
        "account_id = 'nutmeg'",
        name="ck_operator_telegram_owner_account",
    ),
    CheckConstraint(
        "owner_mode IN ('openclaw', 'native_distinct_token')",
        name="ck_operator_telegram_owner_mode",
    ),
    CheckConstraint(
        "heartbeat_sequence >= 1",
        name="ck_operator_telegram_owner_sequence",
    ),
    UniqueConstraint(
        "account_id",
        "owner_instance_id",
        name="uq_operator_telegram_owner_instance",
    ),
)


operator_telegram_callback_attestations = Table(
    "operator_telegram_callback_attestations",
    metadata,
    Column("telegram_callback_attestation_id", Text, primary_key=True),
    Column("account_id", Text, nullable=False),
    Column("owner_instance_id", Text, nullable=False),
    Column("callback_query_id", Text, nullable=False),
    Column("sender_id", Text, nullable=False),
    Column("chat_id", Text, nullable=False),
    Column("message_id", Text, nullable=False),
    Column("namespace", Text, nullable=False),
    Column("callback_data_hash", Text, nullable=False),
    Column("server_ingress_at", Text, nullable=False),
    Column(
        "owner_heartbeat_id",
        Text,
        ForeignKey(
            "operator_telegram_owner_heartbeats.telegram_owner_heartbeat_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "source_artifact_id",
        Text,
        ForeignKey("source_artifacts.artifact_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "source_artifact_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("account_id = 'nutmeg'", name="ck_operator_callback_account"),
    CheckConstraint("namespace = 'ntc'", name="ck_operator_callback_namespace"),
    UniqueConstraint(
        "account_id",
        "callback_query_id",
        name="uq_operator_callback_query",
    ),
)


operator_result_set_families = Table(
    "operator_result_set_families",
    metadata,
    Column("result_set_family_id", Text, primary_key=True),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("lane", Text, nullable=False),
    Column("business_key", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_result_family_lane"),
    UniqueConstraint(
        "lane",
        "business_key",
        name="uq_result_family_business_key",
    ),
)


zucai_prize_table_revisions = Table(
    "zucai_prize_table_revisions",
    metadata,
    Column("prize_table_revision_id", Text, primary_key=True),
    Column("prize_table_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("issue", Text, nullable=False, index=True),
    Column("currency", Text, nullable=False),
    Column("published_at", Text, nullable=False),
    Column(
        "source_artifact_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("tier_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_zucai_prize_revision"),
    CheckConstraint("currency = 'CNY'", name="ck_zucai_prize_currency"),
    CheckConstraint("tier_count = 3", name="ck_zucai_prize_tier_count"),
    UniqueConstraint(
        "prize_table_family_id",
        "revision_no",
        name="uq_zucai_prize_family_revision",
    ),
)


zucai_prize_table_tiers = Table(
    "zucai_prize_table_tiers",
    metadata,
    Column("prize_table_tier_id", Text, primary_key=True),
    Column(
        "prize_table_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("tier_index", Integer, nullable=False),
    Column("tier_code", Text, nullable=False),
    Column("ticket_kind", Text, nullable=False),
    Column("required_correct_count", Integer, nullable=False),
    Column("official_winning_note_count", Integer, nullable=False),
    Column("payout_minor_per_winning_note", Integer, nullable=False),
    CheckConstraint("tier_index BETWEEN 0 AND 2", name="ck_zucai_prize_tier_index"),
    CheckConstraint(
        "(tier_code = 'sfc_first' AND ticket_kind = 'sfc' "
        "AND required_correct_count = 14) OR "
        "(tier_code = 'sfc_second' AND ticket_kind = 'sfc' "
        "AND required_correct_count = 13) OR "
        "(tier_code = 'renjiu_first' AND ticket_kind = 'renjiu' "
        "AND required_correct_count = 9)",
        name="ck_zucai_prize_tier_identity",
    ),
    CheckConstraint(
        "official_winning_note_count >= 0",
        name="ck_zucai_prize_winning_count",
    ),
    CheckConstraint(
        "payout_minor_per_winning_note >= 0",
        name="ck_zucai_prize_payout",
    ),
    UniqueConstraint(
        "prize_table_revision_id",
        "tier_index",
        name="uq_zucai_prize_tier_index",
    ),
    UniqueConstraint(
        "prize_table_revision_id",
        "tier_code",
        name="uq_zucai_prize_tier_code",
    ),
)


operator_result_set_revisions = Table(
    "operator_result_set_revisions",
    metadata,
    Column("result_set_revision_id", Text, primary_key=True),
    Column(
        "result_set_family_id",
        Text,
        ForeignKey(
            "operator_result_set_families.result_set_family_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("lane", Text, nullable=False),
    Column("business_key", Text, nullable=False),
    Column("task_snapshot_hash", Text, nullable=False),
    Column(
        "slate_revision_id",
        Text,
        ForeignKey("official_sale_slate_revisions.slate_revision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("result_cutoff_at", Text, nullable=False),
    Column("importer_version", Text, nullable=False),
    Column(
        "zucai_prize_table_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("match_count", Integer, nullable=False),
    Column("source_receipt_count", Integer, nullable=False),
    Column("outcome_count", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_result_set_revision"),
    CheckConstraint("lane IN ('jczq', 'zucai')", name="ck_result_set_lane"),
    CheckConstraint("match_count >= 1", name="ck_result_set_match_count"),
    CheckConstraint(
        "source_receipt_count = match_count * 3",
        name="ck_result_set_source_count",
    ),
    CheckConstraint(
        "outcome_count BETWEEN 0 AND match_count",
        name="ck_result_set_outcome_count",
    ),
    CheckConstraint(
        "(lane = 'jczq' AND zucai_prize_table_revision_id IS NULL) OR lane = 'zucai'",
        name="ck_result_set_prize_lane",
    ),
    UniqueConstraint(
        "result_set_family_id",
        "revision_no",
        name="uq_result_set_family_revision",
    ),
)


operator_result_match_revisions = Table(
    "operator_result_match_revisions",
    metadata,
    Column("match_result_revision_id", Text, primary_key=True),
    Column(
        "result_set_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("match_index", Integer, nullable=False),
    Column("official_match_no", Text, nullable=False),
    Column(
        "official_offer_revision_id",
        Text,
        ForeignKey(
            "official_offer_revisions.official_offer_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("normalized_disposition", Text, nullable=True),
    Column("normalized_home_90", Integer, nullable=True),
    Column("normalized_away_90", Integer, nullable=True),
    Column("agreement_state", Text, nullable=False),
    CheckConstraint("match_index >= 0", name="ck_result_match_index"),
    CheckConstraint(
        "agreement_state IN ('missing', 'conflict', 'agreed')",
        name="ck_result_match_agreement",
    ),
    CheckConstraint(
        "(agreement_state IN ('missing', 'conflict') "
        "AND normalized_disposition IS NULL "
        "AND normalized_home_90 IS NULL AND normalized_away_90 IS NULL) OR "
        "(agreement_state = 'agreed' "
        "AND normalized_disposition = 'played_90' "
        "AND normalized_home_90 >= 0 AND normalized_away_90 >= 0) OR "
        "(agreement_state = 'agreed' "
        "AND normalized_disposition IN ('postponed', 'official_void') "
        "AND normalized_home_90 IS NULL AND normalized_away_90 IS NULL)",
        name="ck_result_match_normalized_shape",
    ),
    UniqueConstraint(
        "result_set_revision_id",
        "match_index",
        name="uq_result_match_index",
    ),
    UniqueConstraint(
        "result_set_revision_id",
        "official_offer_revision_id",
        name="uq_result_match_offer",
    ),
    UniqueConstraint(
        "result_set_revision_id",
        "match_id",
        name="uq_result_match_identity",
    ),
)


operator_result_source_receipts = Table(
    "operator_result_source_receipts",
    metadata,
    Column("result_source_receipt_id", Text, primary_key=True),
    Column(
        "match_result_revision_id",
        Text,
        ForeignKey(
            "operator_result_match_revisions.match_result_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("source_index", Integer, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column(
        "source_artifact_retrieval_id",
        Text,
        ForeignKey("artifact_retrievals.artifact_retrieval_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("captured_at", Text, nullable=True),
    Column("source_disposition", Text, nullable=True),
    Column("home_90", Integer, nullable=True),
    Column("away_90", Integer, nullable=True),
    Column("receipt_state", Text, nullable=False),
    Column("invalid_code", Text, nullable=True),
    CheckConstraint("source_index BETWEEN 0 AND 2", name="ck_result_source_index"),
    CheckConstraint(
        "source_kind IN ('api_football', 'sporttery_game90', 'okooo_manual')",
        name="ck_result_source_kind",
    ),
    CheckConstraint(
        "receipt_state IN ('missing', 'invalid', 'available')",
        name="ck_result_source_state",
    ),
    CheckConstraint(
        "invalid_code IS NULL OR invalid_code IN ("
        "'artifact_unreadable', 'schema_mismatch', 'invalid_score', "
        "'source_identity_mismatch', 'unsupported_status')",
        name="ck_result_source_invalid_code",
    ),
    CheckConstraint(
        "(receipt_state = 'missing' AND source_artifact_retrieval_id IS NULL "
        "AND captured_at IS NULL AND source_disposition IS NULL "
        "AND home_90 IS NULL AND away_90 IS NULL AND invalid_code IS NULL) OR "
        "(receipt_state = 'invalid' AND source_artifact_retrieval_id IS NOT NULL "
        "AND captured_at IS NOT NULL AND source_disposition IS NULL "
        "AND home_90 IS NULL AND away_90 IS NULL AND invalid_code IS NOT NULL) OR "
        "(receipt_state = 'available' AND source_artifact_retrieval_id IS NOT NULL "
        "AND captured_at IS NOT NULL AND invalid_code IS NULL AND ("
        "(source_disposition = 'played_90' AND home_90 >= 0 AND away_90 >= 0) OR "
        "(source_disposition IN ('postponed', 'official_void') "
        "AND home_90 IS NULL AND away_90 IS NULL)))",
        name="ck_result_source_shape",
    ),
    UniqueConstraint(
        "match_result_revision_id",
        "source_index",
        name="uq_result_source_index",
    ),
    UniqueConstraint(
        "match_result_revision_id",
        "source_kind",
        name="uq_result_source_kind",
    ),
)


operator_outcome_revisions = Table(
    "operator_outcome_revisions",
    metadata,
    Column("outcome_revision_id", Text, primary_key=True),
    Column("outcome_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_outcome_revisions.outcome_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("outcome_index", Integer, nullable=False),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "match_result_revision_id",
        Text,
        ForeignKey(
            "operator_result_match_revisions.match_result_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column(
        "result_set_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("result_disposition", Text, nullable=False),
    Column("home_90", Integer, nullable=True),
    Column("away_90", Integer, nullable=True),
    Column("source_artifact_retrieval_ids_json", Text, nullable=False),
    Column("recorded_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    CheckConstraint("revision_no >= 1", name="ck_outcome_revision"),
    CheckConstraint("outcome_index >= 0", name="ck_outcome_index"),
    CheckConstraint(
        "(result_disposition = 'played_90' AND home_90 >= 0 AND away_90 >= 0) "
        "OR (result_disposition = 'official_void' "
        "AND home_90 IS NULL AND away_90 IS NULL)",
        name="ck_outcome_shape",
    ),
    UniqueConstraint(
        "outcome_family_id",
        "revision_no",
        name="uq_outcome_family_revision",
    ),
    UniqueConstraint("action_id", "outcome_index", name="uq_outcome_action_index"),
)


operator_settlement_requests = Table(
    "operator_settlement_requests",
    metadata,
    Column("settlement_request_id", Text, primary_key=True),
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
        "result_set_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "prize_table_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("requested_at", Text, nullable=False),
)


operator_task_settlement_runs = Table(
    "operator_task_settlement_runs",
    metadata,
    Column("settlement_run_id", Text, primary_key=True),
    Column(
        "settlement_request_id",
        Text,
        ForeignKey(
            "operator_settlement_requests.settlement_request_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    ),
    Column(
        "request_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "settle_action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("task_family_id", Text, nullable=False, index=True),
    Column("work_item_id", Text, nullable=False, index=True),
    Column("work_item_snapshot_hash", Text, nullable=False),
    Column(
        "result_set_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "prize_table_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    Column("settlement_method_version", Text, nullable=False),
    Column("rounding_policy_version", Text, nullable=True),
    Column("fixed_prize_policy_revision_ids_json", Text, nullable=False),
    Column("settlement_state", Text, nullable=False),
    Column("requested_ticket_count", Integer, nullable=False),
    Column("eligible_ticket_count", Integer, nullable=False),
    Column("settled_ticket_count", Integer, nullable=False),
    Column("skipped_ticket_count", Integer, nullable=False),
    Column("persisted_settlement_count", Integer, nullable=False),
    Column("persisted_note_grade_count", Integer, nullable=False),
    Column("persisted_leg_grade_count", Integer, nullable=False),
    Column("persisted_cash_count", Integer, nullable=False),
    Column("ticket_settlement_revision_ids_json", Text, nullable=False),
    Column("completed_at", Text, nullable=False),
    CheckConstraint(
        "settlement_state IN ('not_applicable', 'settled', 'corrected')",
        name="ck_task_settlement_state",
    ),
    CheckConstraint(
        "requested_ticket_count >= 0 AND eligible_ticket_count >= 0 "
        "AND settled_ticket_count >= 0 AND skipped_ticket_count >= 0 "
        "AND persisted_settlement_count >= 0 "
        "AND persisted_note_grade_count >= 0 "
        "AND persisted_leg_grade_count >= 0 AND persisted_cash_count >= 0",
        name="ck_task_settlement_nonnegative_counts",
    ),
    CheckConstraint(
        "requested_ticket_count = eligible_ticket_count + skipped_ticket_count "
        "AND eligible_ticket_count = settled_ticket_count "
        "AND settled_ticket_count = persisted_settlement_count",
        name="ck_task_settlement_reconciled_counts",
    ),
    CheckConstraint(
        "settlement_state != 'not_applicable' OR "
        "(requested_ticket_count = 0 AND persisted_note_grade_count = 0 "
        "AND persisted_leg_grade_count = 0 AND persisted_cash_count = 0)",
        name="ck_task_settlement_not_applicable",
    ),
)


operator_task_settlement_skips = Table(
    "operator_task_settlement_skips",
    metadata,
    Column("settlement_skip_id", Text, primary_key=True),
    Column(
        "settlement_run_id",
        Text,
        ForeignKey(
            "operator_task_settlement_runs.settlement_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column("skip_index", Integer, nullable=False),
    Column(
        "ticket_id",
        Text,
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("reason_code", Text, nullable=False),
    CheckConstraint("skip_index >= 0", name="ck_task_settlement_skip_index"),
    CheckConstraint(
        "reason_code IN ('already_current', 'result_not_ready', "
        "'prize_not_ready', 'placement_integrity_blocked')",
        name="ck_task_settlement_skip_reason",
    ),
    UniqueConstraint(
        "settlement_run_id",
        "skip_index",
        name="uq_task_settlement_skip_index",
    ),
    UniqueConstraint(
        "settlement_run_id",
        "ticket_id",
        name="uq_task_settlement_skip_ticket",
    ),
)


operator_ticket_settlement_revisions = Table(
    "operator_ticket_settlement_revisions",
    metadata,
    Column("settlement_revision_id", Text, primary_key=True),
    Column("settlement_family_id", Text, nullable=False, index=True),
    Column("revision_no", Integer, nullable=False),
    Column(
        "supersedes_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_settlement_revisions.settlement_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        unique=True,
    ),
    Column("settlement_index", Integer, nullable=False),
    Column(
        "settlement_run_id",
        Text,
        ForeignKey(
            "operator_task_settlement_runs.settlement_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column(
        "ticket_id",
        Text,
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column(
        "result_set_revision_id",
        Text,
        ForeignKey(
            "operator_result_set_revisions.result_set_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "prize_table_revision_id",
        Text,
        ForeignKey(
            "zucai_prize_table_revisions.prize_table_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
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
    Column("method_version", Text, nullable=False),
    Column("rounding_policy_version", Text, nullable=True),
    Column("settlement_state", Text, nullable=False),
    Column("currency", Text, nullable=False),
    Column("stake_minor", Integer, nullable=False),
    Column("distinct_note_count", Integer, nullable=False),
    Column("paid_note_unit_count", Integer, nullable=False),
    Column("winning_note_unit_count", Integer, nullable=False),
    Column("void_note_unit_count", Integer, nullable=False),
    Column("gross_payout_minor", Integer, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("created_at", Text, nullable=False),
    CheckConstraint("revision_no >= 1", name="ck_ticket_settlement_revision"),
    CheckConstraint("settlement_index >= 0", name="ck_ticket_settlement_index"),
    CheckConstraint(
        "settlement_state IN ('settled', 'corrected')",
        name="ck_ticket_settlement_state",
    ),
    CheckConstraint("length(currency) = 3", name="ck_ticket_settlement_currency"),
    CheckConstraint("stake_minor > 0", name="ck_ticket_settlement_stake"),
    CheckConstraint(
        "distinct_note_count > 0 AND paid_note_unit_count > 0 "
        "AND winning_note_unit_count >= 0 AND void_note_unit_count >= 0 "
        "AND winning_note_unit_count + void_note_unit_count <= paid_note_unit_count "
        "AND gross_payout_minor >= 0",
        name="ck_ticket_settlement_counts",
    ),
    CheckConstraint(
        "(fixed_prize_policy_revision_id IS NULL "
        "AND prize_table_revision_id IS NULL "
        "AND rounding_policy_version IS NOT NULL) OR "
        "(fixed_prize_policy_revision_id IS NOT NULL "
        "AND prize_table_revision_id IS NOT NULL "
        "AND rounding_policy_version IS NULL AND void_note_unit_count = 0)",
        name="ck_ticket_settlement_lane_policy",
    ),
    UniqueConstraint(
        "settlement_family_id",
        "revision_no",
        name="uq_ticket_settlement_family_revision",
    ),
    UniqueConstraint(
        "settlement_run_id",
        "settlement_index",
        name="uq_ticket_settlement_run_index",
    ),
)


operator_ticket_note_settlements = Table(
    "operator_ticket_note_settlements",
    metadata,
    Column("note_settlement_id", Text, primary_key=True),
    Column(
        "settlement_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_settlement_revisions.settlement_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column(
        "ticket_note_id",
        Text,
        ForeignKey("operator_ticket_notes.ticket_note_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("note_grade", Text, nullable=False),
    Column("unit_count", Integer, nullable=False),
    Column("winning_unit_count", Integer, nullable=False),
    Column("void_unit_count", Integer, nullable=False),
    Column("correct_leg_count", Integer, nullable=False),
    Column("void_leg_count", Integer, nullable=False),
    Column("prize_tier_code", Text, nullable=True),
    Column("payout_minor", Integer, nullable=False),
    CheckConstraint(
        "note_grade IN ('won', 'lost', 'void')",
        name="ck_note_settlement_grade",
    ),
    CheckConstraint(
        "unit_count > 0 AND winning_unit_count >= 0 AND void_unit_count >= 0 "
        "AND correct_leg_count >= 0 AND void_leg_count >= 0 AND payout_minor >= 0",
        name="ck_note_settlement_counts",
    ),
    CheckConstraint(
        "(note_grade = 'won' AND winning_unit_count = unit_count "
        "AND void_unit_count = 0) OR "
        "(note_grade = 'void' AND winning_unit_count = 0 "
        "AND void_unit_count = unit_count AND prize_tier_code IS NULL) OR "
        "(note_grade = 'lost' AND winning_unit_count = 0 "
        "AND void_unit_count = 0 AND prize_tier_code IS NULL AND payout_minor = 0)",
        name="ck_note_settlement_grade_counts",
    ),
    UniqueConstraint(
        "settlement_revision_id",
        "ticket_note_id",
        name="uq_note_settlement_note",
    ),
)


operator_ticket_note_leg_settlements = Table(
    "operator_ticket_note_leg_settlements",
    metadata,
    Column("leg_settlement_id", Text, primary_key=True),
    Column(
        "settlement_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_settlement_revisions.settlement_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column(
        "ticket_note_leg_id",
        Text,
        ForeignKey("operator_ticket_note_legs.ticket_note_leg_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "outcome_revision_id",
        Text,
        ForeignKey(
            "operator_outcome_revisions.outcome_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("result_disposition", Text, nullable=False),
    Column("market_result_code", Text, nullable=False),
    Column("leg_grade", Text, nullable=False),
    CheckConstraint(
        "result_disposition IN ('played_90', 'official_void')",
        name="ck_leg_settlement_disposition",
    ),
    CheckConstraint(
        "leg_grade IN ('won', 'lost', 'void')",
        name="ck_leg_settlement_grade",
    ),
    UniqueConstraint(
        "settlement_revision_id",
        "ticket_note_leg_id",
        name="uq_leg_settlement_leg",
    ),
)


operator_settlement_cash_links = Table(
    "operator_settlement_cash_links",
    metadata,
    Column("settlement_cash_link_id", Text, primary_key=True),
    Column(
        "settlement_revision_id",
        Text,
        ForeignKey(
            "operator_ticket_settlement_revisions.settlement_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    ),
    Column(
        "transaction_id",
        Text,
        ForeignKey("cash_transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("transaction_kind", Text, nullable=False),
    Column(
        "reverses_transaction_id",
        Text,
        ForeignKey("cash_transactions.transaction_id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    ),
    Column("amount_minor", Integer, nullable=False),
    Column("currency", Text, nullable=False),
    CheckConstraint(
        "transaction_kind IN ('payout', 'payout_reversal')",
        name="ck_settlement_cash_kind",
    ),
    CheckConstraint(
        "(transaction_kind = 'payout' AND amount_minor > 0 "
        "AND reverses_transaction_id IS NULL) OR "
        "(transaction_kind = 'payout_reversal' AND amount_minor < 0 "
        "AND reverses_transaction_id IS NOT NULL)",
        name="ck_settlement_cash_direction",
    ),
    CheckConstraint("length(currency) = 3", name="ck_settlement_cash_currency"),
)


__all__ = [
    "operator_candidate_ticket_legs",
    "operator_candidate_tickets",
    "operator_outcome_revisions",
    "operator_placement_cash_links",
    "operator_result_match_revisions",
    "operator_result_set_families",
    "operator_result_set_revisions",
    "operator_result_source_receipts",
    "operator_review_eligibility_facts",
    "operator_settlement_cash_links",
    "operator_settlement_requests",
    "operator_task_settlement_runs",
    "operator_task_settlement_skips",
    "operator_telegram_callback_attestations",
    "operator_telegram_owner_heartbeats",
    "operator_ticket_note_leg_settlements",
    "operator_ticket_note_legs",
    "operator_ticket_note_settlements",
    "operator_ticket_notes",
    "operator_ticket_settlement_revisions",
    "zucai_fixed_prize_policy_revisions",
    "zucai_fixed_prize_policy_tiers",
    "zucai_prize_table_revisions",
    "zucai_prize_table_tiers",
]
