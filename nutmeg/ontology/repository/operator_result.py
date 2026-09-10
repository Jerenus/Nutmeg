"""Typed persistence for operator candidate and fixed-prize result rows."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, exists, func, insert, or_, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import (
    CandidateAuditFindingRow,
    CandidateDeadFaceRow,
    CandidateGenerationOverrideLinkRow,
    CandidateMetricRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    NoTicketArtifactScopeRow,
    NoTicketCommandReceiptRow,
    NoTicketOfferScopeRow,
    NoTicketRevisionRow,
    ReviewEligibilityFactRow,
    TicketAuditOverrideReceiptRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    TicketDecisionLineageItemRow,
    TicketDecisionLineageRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_tickets as st


@dataclass(frozen=True, slots=True)
class ResultSetFamilyRow:
    result_set_family_id: str
    task_family_id: str
    lane: str
    business_key: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ZucaiPrizeTableRevisionRow:
    prize_table_revision_id: str
    prize_table_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    issue: str
    currency: str
    published_at: str
    source_artifact_retrieval_id: str
    tier_count: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ZucaiPrizeTableTierRow:
    prize_table_tier_id: str
    prize_table_revision_id: str
    tier_index: int
    tier_code: str
    ticket_kind: str
    required_correct_count: int
    official_winning_note_count: int
    payout_minor_per_winning_note: int


@dataclass(frozen=True, slots=True)
class ResultSetRevisionRow:
    result_set_revision_id: str
    result_set_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    task_family_id: str
    work_item_id: str
    lane: str
    business_key: str
    task_snapshot_hash: str
    slate_revision_id: str
    result_cutoff_at: str
    importer_version: str
    zucai_prize_table_revision_id: str | None
    match_count: int
    source_receipt_count: int
    outcome_count: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ResultMatchRevisionRow:
    match_result_revision_id: str
    result_set_revision_id: str
    match_index: int
    official_match_no: str
    official_offer_revision_id: str
    match_id: str
    normalized_disposition: str | None
    normalized_home_90: int | None
    normalized_away_90: int | None
    agreement_state: str


@dataclass(frozen=True, slots=True)
class ResultSourceReceiptRow:
    result_source_receipt_id: str
    match_result_revision_id: str
    source_index: int
    source_kind: str
    source_artifact_retrieval_id: str | None
    captured_at: str | None
    source_disposition: str | None
    home_90: int | None
    away_90: int | None
    receipt_state: str
    invalid_code: str | None


@dataclass(frozen=True, slots=True)
class OperatorOutcomeRevisionRow:
    outcome_revision_id: str
    outcome_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    outcome_index: int
    match_id: str
    match_result_revision_id: str
    result_set_revision_id: str
    result_disposition: str
    home_90: int | None
    away_90: int | None
    source_artifact_retrieval_ids: tuple[str, ...]
    recorded_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class SettlementRequestRow:
    settlement_request_id: str
    action_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    result_set_revision_id: str
    prize_table_revision_id: str | None
    requested_at: str


@dataclass(frozen=True, slots=True)
class TaskSettlementRunRow:
    settlement_run_id: str
    settlement_request_id: str
    request_action_id: str
    settle_action_id: str
    task_family_id: str
    work_item_id: str
    work_item_snapshot_hash: str
    result_set_revision_id: str
    prize_table_revision_id: str | None
    settlement_method_version: str
    rounding_policy_version: str | None
    fixed_prize_policy_revision_ids: tuple[str, ...]
    settlement_state: str
    requested_ticket_count: int
    eligible_ticket_count: int
    settled_ticket_count: int
    skipped_ticket_count: int
    persisted_settlement_count: int
    persisted_note_grade_count: int
    persisted_leg_grade_count: int
    persisted_cash_count: int
    ticket_settlement_revision_ids: tuple[str, ...]
    completed_at: str


@dataclass(frozen=True, slots=True)
class TaskSettlementSkipRow:
    settlement_skip_id: str
    settlement_run_id: str
    skip_index: int
    ticket_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class TicketSettlementRevisionRow:
    settlement_revision_id: str
    settlement_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    settlement_index: int
    settlement_run_id: str
    ticket_id: str
    result_set_revision_id: str
    prize_table_revision_id: str | None
    fixed_prize_policy_revision_id: str | None
    method_version: str
    rounding_policy_version: str | None
    settlement_state: str
    currency: str
    stake_minor: int
    distinct_note_count: int
    paid_note_unit_count: int
    winning_note_unit_count: int
    void_note_unit_count: int
    gross_payout_minor: int
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TicketNoteSettlementRow:
    note_settlement_id: str
    settlement_revision_id: str
    ticket_note_id: str
    note_grade: str
    unit_count: int
    winning_unit_count: int
    void_unit_count: int
    correct_leg_count: int
    void_leg_count: int
    prize_tier_code: str | None
    payout_minor: int


@dataclass(frozen=True, slots=True)
class TicketNoteLegSettlementRow:
    leg_settlement_id: str
    settlement_revision_id: str
    ticket_note_leg_id: str
    outcome_revision_id: str
    result_disposition: str
    market_result_code: str
    leg_grade: str


@dataclass(frozen=True, slots=True)
class SettlementCashLinkRow:
    settlement_cash_link_id: str
    settlement_revision_id: str
    transaction_id: str
    transaction_kind: str
    reverses_transaction_id: str | None
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class SettlementFinancialTotals:
    settlement_stake_minor: int
    settlement_distinct_note_count: int
    settlement_payout_minor: int
    note_stake_minor: int
    note_payout_minor: int
    cash_link_count: int
    cash_link_amount_minor: int
    ledger_cash_count: int
    ledger_cash_amount_minor: int
    cash_mismatch_count: int


@dataclass(frozen=True, slots=True)
class TicketNoteRow:
    ticket_note_id: str
    ticket_id: str
    ticket_artifact_id: str
    note_index: int
    ticket_kind: str
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    composition_hash: str
    fixed_prize_policy_revision_id: str | None
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TicketNoteLegRow:
    ticket_note_leg_id: str
    ticket_note_id: str
    leg_index: int
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    quote_id: str | None
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None
    fixed_prize_policy_revision_id: str | None
    action_id: str


@dataclass(frozen=True, slots=True)
class PlacementCashLinkRow:
    placement_cash_link_id: str
    ticket_id: str
    transaction_id: str
    stake_minor: int
    currency: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TelegramOwnerHeartbeatRow:
    telegram_owner_heartbeat_id: str
    account_id: str
    owner_instance_id: str
    transport_label: str
    owner_mode: str
    router_version: str
    heartbeat_sequence: int
    observed_at: str
    lease_expires_at: str
    registration_action_id: str


@dataclass(frozen=True, slots=True)
class TelegramCallbackAttestationRow:
    telegram_callback_attestation_id: str
    account_id: str
    owner_instance_id: str
    callback_query_id: str
    sender_id: str
    chat_id: str
    message_id: str
    namespace: str
    callback_data_hash: str
    server_ingress_at: str
    owner_heartbeat_id: str
    source_artifact_id: str
    source_artifact_retrieval_id: str
    action_id: str
    created_at: str


class OperatorResultRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_result_set_family(self, row: ResultSetFamilyRow) -> None:
        self._connection.execute(
            insert(sor.operator_result_set_families).values(**_row_fields(row))
        )

    def result_set_family(
        self,
        *,
        lane: str,
        business_key: str,
    ) -> ResultSetFamilyRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_result_set_families).where(
                    sor.operator_result_set_families.c.lane == lane,
                    sor.operator_result_set_families.c.business_key == business_key,
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ResultSetFamilyRow(**dict(row))

    def insert_result_set_revision(self, row: ResultSetRevisionRow) -> None:
        self._connection.execute(
            insert(sor.operator_result_set_revisions).values(**_row_fields(row))
        )

    def result_set_revision(
        self,
        revision_id: str,
    ) -> ResultSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_result_set_revisions).where(
                    sor.operator_result_set_revisions.c.result_set_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ResultSetRevisionRow(**dict(row))

    def current_result_set(
        self,
        *,
        lane: str,
        business_key: str,
    ) -> ResultSetRevisionRow | None:
        revisions = sor.operator_result_set_revisions
        children = revisions.alias("result_set_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.lane == lane,
                    revisions.c.business_key == business_key,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.result_set_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ResultSetRevisionRow(**dict(row))

    def insert_result_match_revision(self, row: ResultMatchRevisionRow) -> None:
        self._connection.execute(
            insert(sor.operator_result_match_revisions).values(**_row_fields(row))
        )

    def result_matches_for_set(
        self,
        result_set_revision_id: str,
    ) -> tuple[ResultMatchRevisionRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_result_match_revisions)
            .where(
                sor.operator_result_match_revisions.c.result_set_revision_id
                == result_set_revision_id
            )
            .order_by(sor.operator_result_match_revisions.c.match_index)
        ).mappings()
        return tuple(ResultMatchRevisionRow(**dict(row)) for row in rows)

    def insert_result_source_receipt(self, row: ResultSourceReceiptRow) -> None:
        self._connection.execute(
            insert(sor.operator_result_source_receipts).values(**_row_fields(row))
        )

    def result_source_receipts_for_set(
        self,
        result_set_revision_id: str,
    ) -> tuple[ResultSourceReceiptRow, ...]:
        receipts = sor.operator_result_source_receipts
        matches = sor.operator_result_match_revisions
        rows = self._connection.execute(
            select(receipts)
            .select_from(
                receipts.join(
                    matches,
                    receipts.c.match_result_revision_id
                    == matches.c.match_result_revision_id,
                )
            )
            .where(matches.c.result_set_revision_id == result_set_revision_id)
            .order_by(matches.c.match_index, receipts.c.source_index)
        ).mappings()
        return tuple(ResultSourceReceiptRow(**dict(row)) for row in rows)

    def insert_outcome_revision(self, row: OperatorOutcomeRevisionRow) -> None:
        values = _row_fields(row)
        values["source_artifact_retrieval_ids_json"] = canonical_json(
            list(values.pop("source_artifact_retrieval_ids"))
        )
        self._connection.execute(
            insert(sor.operator_outcome_revisions).values(**values)
        )

    def outcomes_for_result_set(
        self,
        result_set_revision_id: str,
    ) -> tuple[OperatorOutcomeRevisionRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_outcome_revisions)
            .where(
                sor.operator_outcome_revisions.c.result_set_revision_id
                == result_set_revision_id
            )
            .order_by(sor.operator_outcome_revisions.c.outcome_index)
        ).mappings()
        return tuple(_outcome_revision_row(row) for row in rows)

    def current_outcome_for_match(
        self,
        match_id: str,
    ) -> OperatorOutcomeRevisionRow | None:
        revisions = sor.operator_outcome_revisions
        children = revisions.alias("outcome_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.match_id == match_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.outcome_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _outcome_revision_row(row)

    def insert_prize_table_revision(
        self,
        row: ZucaiPrizeTableRevisionRow,
    ) -> None:
        self._connection.execute(
            insert(sor.zucai_prize_table_revisions).values(**_row_fields(row))
        )

    def prize_table_revision(
        self,
        revision_id: str,
    ) -> ZucaiPrizeTableRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.zucai_prize_table_revisions).where(
                    sor.zucai_prize_table_revisions.c.prize_table_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ZucaiPrizeTableRevisionRow(**dict(row))

    def current_prize_table(
        self,
        issue: str,
    ) -> ZucaiPrizeTableRevisionRow | None:
        revisions = sor.zucai_prize_table_revisions
        children = revisions.alias("prize_table_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.issue == issue,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.prize_table_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ZucaiPrizeTableRevisionRow(**dict(row))

    def insert_prize_table_tier(self, row: ZucaiPrizeTableTierRow) -> None:
        self._connection.execute(
            insert(sor.zucai_prize_table_tiers).values(**_row_fields(row))
        )

    def prize_table_tiers(
        self,
        revision_id: str,
    ) -> tuple[ZucaiPrizeTableTierRow, ...]:
        rows = self._connection.execute(
            select(sor.zucai_prize_table_tiers)
            .where(
                sor.zucai_prize_table_tiers.c.prize_table_revision_id
                == revision_id
            )
            .order_by(sor.zucai_prize_table_tiers.c.tier_index)
        ).mappings()
        return tuple(ZucaiPrizeTableTierRow(**dict(row)) for row in rows)

    def persisted_result_counts(
        self,
        result_set_revision_id: str,
    ) -> tuple[int, int, int]:
        matches = int(
            self._connection.scalar(
                select(func.count())
                .select_from(sor.operator_result_match_revisions)
                .where(
                    sor.operator_result_match_revisions.c.result_set_revision_id
                    == result_set_revision_id
                )
            )
            or 0
        )
        receipts = int(
            self._connection.scalar(
                select(func.count())
                .select_from(
                    sor.operator_result_source_receipts.join(
                        sor.operator_result_match_revisions,
                        sor.operator_result_source_receipts.c.match_result_revision_id
                        == sor.operator_result_match_revisions.c.match_result_revision_id,
                    )
                )
                .where(
                    sor.operator_result_match_revisions.c.result_set_revision_id
                    == result_set_revision_id
                )
            )
            or 0
        )
        outcomes = int(
            self._connection.scalar(
                select(func.count())
                .select_from(sor.operator_outcome_revisions)
                .where(
                    sor.operator_outcome_revisions.c.result_set_revision_id
                    == result_set_revision_id
                )
            )
            or 0
        )
        return matches, receipts, outcomes

    def insert_settlement_request(self, row: SettlementRequestRow) -> None:
        self._connection.execute(
            insert(sor.operator_settlement_requests).values(**_row_fields(row))
        )

    def settlement_request(self, request_id: str) -> SettlementRequestRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_settlement_requests).where(
                    sor.operator_settlement_requests.c.settlement_request_id
                    == request_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else SettlementRequestRow(**dict(row))

    def settlement_request_for_result(
        self,
        result_set_revision_id: str,
    ) -> SettlementRequestRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_settlement_requests)
                .where(
                    sor.operator_settlement_requests.c.result_set_revision_id
                    == result_set_revision_id
                )
                .order_by(
                    sor.operator_settlement_requests.c.requested_at.desc(),
                    sor.operator_settlement_requests.c.settlement_request_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return None if row is None else SettlementRequestRow(**dict(row))

    def insert_task_settlement_run(self, row: TaskSettlementRunRow) -> None:
        values = _row_fields(row)
        values["fixed_prize_policy_revision_ids_json"] = canonical_json(
            list(values.pop("fixed_prize_policy_revision_ids"))
        )
        values["ticket_settlement_revision_ids_json"] = canonical_json(
            list(values.pop("ticket_settlement_revision_ids"))
        )
        self._connection.execute(
            insert(sor.operator_task_settlement_runs).values(**values)
        )

    def task_settlement_run(self, run_id: str) -> TaskSettlementRunRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_task_settlement_runs).where(
                    sor.operator_task_settlement_runs.c.settlement_run_id == run_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _task_settlement_run_row(row)

    def task_settlement_run_for_request(
        self, request_id: str
    ) -> TaskSettlementRunRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_task_settlement_runs).where(
                    sor.operator_task_settlement_runs.c.settlement_request_id
                    == request_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _task_settlement_run_row(row)

    def insert_task_settlement_skip(self, row: TaskSettlementSkipRow) -> None:
        self._connection.execute(
            insert(sor.operator_task_settlement_skips).values(**_row_fields(row))
        )

    def task_settlement_skips(
        self, run_id: str
    ) -> tuple[TaskSettlementSkipRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_task_settlement_skips)
            .where(
                sor.operator_task_settlement_skips.c.settlement_run_id == run_id
            )
            .order_by(sor.operator_task_settlement_skips.c.skip_index)
        ).mappings()
        return tuple(TaskSettlementSkipRow(**dict(row)) for row in rows)

    def insert_ticket_settlement_revision(
        self, row: TicketSettlementRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sor.operator_ticket_settlement_revisions).values(
                **_row_fields(row)
            )
        )

    def ticket_settlement_revision(
        self, revision_id: str
    ) -> TicketSettlementRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_ticket_settlement_revisions).where(
                    sor.operator_ticket_settlement_revisions.c.settlement_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else TicketSettlementRevisionRow(**dict(row))

    def current_ticket_settlement(
        self, ticket_id: str
    ) -> TicketSettlementRevisionRow | None:
        revisions = sor.operator_ticket_settlement_revisions
        children = revisions.alias("ticket_settlement_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.ticket_id == ticket_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.settlement_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else TicketSettlementRevisionRow(**dict(row))

    def insert_ticket_note_settlement(
        self, row: TicketNoteSettlementRow
    ) -> None:
        self._connection.execute(
            insert(sor.operator_ticket_note_settlements).values(**_row_fields(row))
        )

    def ticket_note_settlements(
        self, revision_id: str
    ) -> tuple[TicketNoteSettlementRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_ticket_note_settlements)
            .where(
                sor.operator_ticket_note_settlements.c.settlement_revision_id
                == revision_id
            )
            .order_by(sor.operator_ticket_note_settlements.c.ticket_note_id)
        ).mappings()
        return tuple(TicketNoteSettlementRow(**dict(row)) for row in rows)

    def insert_ticket_note_leg_settlement(
        self, row: TicketNoteLegSettlementRow
    ) -> None:
        self._connection.execute(
            insert(sor.operator_ticket_note_leg_settlements).values(
                **_row_fields(row)
            )
        )

    def ticket_note_leg_settlements(
        self, revision_id: str
    ) -> tuple[TicketNoteLegSettlementRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_ticket_note_leg_settlements)
            .where(
                sor.operator_ticket_note_leg_settlements.c.settlement_revision_id
                == revision_id
            )
            .order_by(
                sor.operator_ticket_note_leg_settlements.c.ticket_note_leg_id
            )
        ).mappings()
        return tuple(TicketNoteLegSettlementRow(**dict(row)) for row in rows)

    def insert_settlement_cash_link(self, row: SettlementCashLinkRow) -> None:
        self._connection.execute(
            insert(sor.operator_settlement_cash_links).values(**_row_fields(row))
        )

    def settlement_cash_links(
        self, revision_id: str
    ) -> tuple[SettlementCashLinkRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_settlement_cash_links)
            .where(
                sor.operator_settlement_cash_links.c.settlement_revision_id
                == revision_id
            )
            .order_by(sor.operator_settlement_cash_links.c.transaction_id)
        ).mappings()
        return tuple(SettlementCashLinkRow(**dict(row)) for row in rows)

    def persisted_settlement_counts(
        self, run_id: str
    ) -> tuple[int, int, int, int]:
        settlements = sor.operator_ticket_settlement_revisions
        notes = sor.operator_ticket_note_settlements
        legs = sor.operator_ticket_note_leg_settlements
        cash = sor.operator_settlement_cash_links
        settlement_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(settlements)
                .where(settlements.c.settlement_run_id == run_id)
            )
            or 0
        )
        note_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(notes.join(settlements))
                .where(settlements.c.settlement_run_id == run_id)
            )
            or 0
        )
        leg_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(legs.join(settlements))
                .where(settlements.c.settlement_run_id == run_id)
            )
            or 0
        )
        cash_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(cash.join(settlements))
                .where(settlements.c.settlement_run_id == run_id)
            )
            or 0
        )
        return settlement_count, note_count, leg_count, cash_count

    def settlement_financial_totals(self, run_id: str) -> SettlementFinancialTotals:
        settlements = sor.operator_ticket_settlement_revisions
        note_results = sor.operator_ticket_note_settlements
        notes = sor.operator_ticket_notes
        cash_links = sor.operator_settlement_cash_links
        cash = sf.cash_transactions

        settlement_row = self._connection.execute(
            select(
                func.coalesce(func.sum(settlements.c.stake_minor), 0),
                func.coalesce(func.sum(settlements.c.distinct_note_count), 0),
                func.coalesce(func.sum(settlements.c.gross_payout_minor), 0),
            ).where(settlements.c.settlement_run_id == run_id)
        ).one()
        note_row = self._connection.execute(
            select(
                func.coalesce(func.sum(notes.c.stake_minor), 0),
                func.coalesce(func.sum(note_results.c.payout_minor), 0),
            )
            .select_from(
                note_results.join(
                    settlements,
                    note_results.c.settlement_revision_id
                    == settlements.c.settlement_revision_id,
                ).join(
                    notes,
                    notes.c.ticket_note_id == note_results.c.ticket_note_id,
                )
            )
            .where(settlements.c.settlement_run_id == run_id)
        ).one()
        cash_link_row = self._connection.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cash_links.c.amount_minor), 0),
            )
            .select_from(
                cash_links.join(
                    settlements,
                    cash_links.c.settlement_revision_id
                    == settlements.c.settlement_revision_id,
                )
            )
            .where(settlements.c.settlement_run_id == run_id)
        ).one()
        ledger_row = self._connection.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cash.c.amount_minor), 0),
            )
            .select_from(
                cash.join(
                    settlements,
                    cash.c.ticket_settlement_id
                    == settlements.c.settlement_revision_id,
                )
            )
            .where(settlements.c.settlement_run_id == run_id)
        ).one()
        cash_mismatch_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(
                    cash_links.join(
                        settlements,
                        cash_links.c.settlement_revision_id
                        == settlements.c.settlement_revision_id,
                    ).join(
                        cash,
                        cash.c.transaction_id == cash_links.c.transaction_id,
                    )
                )
                .where(
                    settlements.c.settlement_run_id == run_id,
                    or_(
                        cash.c.ticket_settlement_id
                        != cash_links.c.settlement_revision_id,
                        cash.c.kind != cash_links.c.transaction_kind,
                        cash.c.amount_minor != cash_links.c.amount_minor,
                        cash.c.currency != cash_links.c.currency,
                    ),
                )
            )
            or 0
        )
        return SettlementFinancialTotals(
            settlement_stake_minor=int(settlement_row[0]),
            settlement_distinct_note_count=int(settlement_row[1]),
            settlement_payout_minor=int(settlement_row[2]),
            note_stake_minor=int(note_row[0]),
            note_payout_minor=int(note_row[1]),
            cash_link_count=int(cash_link_row[0]),
            cash_link_amount_minor=int(cash_link_row[1]),
            ledger_cash_count=int(ledger_row[0]),
            ledger_cash_amount_minor=int(ledger_row[1]),
            cash_mismatch_count=cash_mismatch_count,
        )

    def placed_ticket_ids_for_work_item(self, work_item_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(st.ticket_placements.c.ticket_id)
            .select_from(
                st.operator_artifact_work_item_links.join(
                    st.operator_artifact_terminal_receipts,
                    st.operator_artifact_terminal_receipts.c.ticket_artifact_id
                    == st.operator_artifact_work_item_links.c.ticket_artifact_id,
                ).join(
                    st.ticket_placements,
                    st.ticket_placements.c.ticket_artifact_id
                    == st.operator_artifact_work_item_links.c.ticket_artifact_id,
                )
            )
            .where(
                st.operator_artifact_work_item_links.c.work_item_id == work_item_id,
                st.operator_artifact_terminal_receipts.c.terminal_kind == "placed",
            )
            .order_by(st.ticket_placements.c.ticket_id)
        ).scalars()
        return tuple(str(ticket_id) for ticket_id in rows)

    def settlement_baseline_revision_id(
        self,
        *,
        task_family_id: str,
        work_item_id: str,
        task_snapshot_hash: str,
        ticket_ids: tuple[str, ...],
    ) -> str:
        if not ticket_ids:
            raise ValueError("settlement review requires at least one placed ticket")
        placements = st.ticket_placements
        work_links = st.operator_artifact_work_item_links
        terminals = st.operator_artifact_terminal_receipts
        bindings = st.operator_protected_artifact_bindings
        lineages = sod.operator_ticket_decision_lineage_revisions
        rows = tuple(
            self._connection.execute(
                select(
                    placements.c.ticket_id,
                    lineages.c.market_prior_baseline_revision_id,
                )
                .select_from(
                    placements.join(
                        work_links,
                        work_links.c.ticket_artifact_id
                        == placements.c.ticket_artifact_id,
                    )
                    .join(
                        terminals,
                        terminals.c.ticket_artifact_id
                        == placements.c.ticket_artifact_id,
                    )
                    .join(
                        bindings,
                        bindings.c.ticket_artifact_id
                        == placements.c.ticket_artifact_id,
                    )
                    .join(
                        lineages,
                        lineages.c.lineage_revision_id
                        == bindings.c.lineage_revision_id,
                    )
                )
                .where(
                    placements.c.ticket_id.in_(ticket_ids),
                    terminals.c.terminal_kind == "placed",
                    work_links.c.task_family_id == task_family_id,
                    work_links.c.work_item_id == work_item_id,
                    work_links.c.task_snapshot_hash == task_snapshot_hash,
                    lineages.c.task_family_id == task_family_id,
                    lineages.c.work_item_id == work_item_id,
                    lineages.c.task_snapshot_hash == task_snapshot_hash,
                )
                .order_by(placements.c.ticket_id)
            )
        )
        if {str(row.ticket_id) for row in rows} != set(ticket_ids):
            raise ValueError("settlement review lineage does not cover every placed ticket")
        baseline_ids = {
            str(row.market_prior_baseline_revision_id) for row in rows
        }
        if len(baseline_ids) != 1:
            raise ValueError("settlement review requires one exact baseline")
        return baseline_ids.pop()

    def insert_ticket_decision_lineage_revision(
        self, row: TicketDecisionLineageRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_ticket_decision_lineage_revisions).values(
                **_row_fields(row)
            )
        )

    def ticket_decision_lineage_revision(
        self, lineage_revision_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_decision_lineage_revisions).where(
                    sod.operator_ticket_decision_lineage_revisions.c.lineage_revision_id
                    == lineage_revision_id
                )
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def ticket_decision_lineage_for_batch(
        self, ticket_batch_revision_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_decision_lineage_revisions)
                .where(
                    sod.operator_ticket_decision_lineage_revisions.c.
                    ticket_batch_revision_id
                    == ticket_batch_revision_id
                )
                .order_by(
                    sod.operator_ticket_decision_lineage_revisions.c.revision_no.desc()
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def current_ticket_decision_lineage(
        self, lineage_family_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        revisions = sod.operator_ticket_decision_lineage_revisions
        children = revisions.alias("lineage_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.lineage_family_id == lineage_family_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.lineage_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def insert_ticket_decision_lineage_item(
        self, row: TicketDecisionLineageItemRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_ticket_decision_lineage_items).values(
                **_row_fields(row)
            )
        )

    def ticket_decision_lineage_items(
        self, lineage_revision_id: str
    ) -> tuple[TicketDecisionLineageItemRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_ticket_decision_lineage_items)
            .where(
                sod.operator_ticket_decision_lineage_items.c.lineage_revision_id
                == lineage_revision_id
            )
            .order_by(sod.operator_ticket_decision_lineage_items.c.item_index)
        ).mappings()
        return tuple(TicketDecisionLineageItemRow(**dict(row)) for row in rows)

    def insert_ticket_audit_override_receipt(
        self, row: TicketAuditOverrideReceiptRow
    ) -> None:
        values = _row_fields(row)
        values["rule_ids_json"] = canonical_json(list(values.pop("rule_ids")))
        values["evidence_rejected_json"] = canonical_json(
            list(values.pop("evidence_rejected"))
        )
        self._connection.execute(
            insert(sod.operator_ticket_audit_override_receipts).values(**values)
        )

    def ticket_audit_override_receipt(
        self, receipt_id: str
    ) -> TicketAuditOverrideReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_audit_override_receipts).where(
                    sod.operator_ticket_audit_override_receipts.c.
                    ticket_audit_override_receipt_id
                    == receipt_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _ticket_audit_override_row(row)

    def ticket_audit_override_receipts_for_batch(
        self, ticket_batch_revision_id: str
    ) -> tuple[TicketAuditOverrideReceiptRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_ticket_audit_override_receipts)
            .where(
                sod.operator_ticket_audit_override_receipts.c.ticket_batch_revision_id
                == ticket_batch_revision_id
            )
            .order_by(
                sod.operator_ticket_audit_override_receipts.c.action_id,
                sod.operator_ticket_audit_override_receipts.c.receipt_index,
            )
        ).mappings()
        return tuple(_ticket_audit_override_row(row) for row in rows)

    def insert_candidate_generation_override_link(
        self, row: CandidateGenerationOverrideLinkRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_generation_override_links).values(
                **_row_fields(row)
            )
        )

    def candidate_generation_override_links(
        self, generation_request_id: str
    ) -> tuple[CandidateGenerationOverrideLinkRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_generation_override_links)
            .where(
                sod.operator_candidate_generation_override_links.c.generation_request_id
                == generation_request_id
            )
            .order_by(
                sod.operator_candidate_generation_override_links.c.link_index
            )
        ).mappings()
        return tuple(CandidateGenerationOverrideLinkRow(**dict(row)) for row in rows)

    def candidate_generation_override_links_for_batch(
        self, ticket_batch_revision_id: str
    ) -> tuple[CandidateGenerationOverrideLinkRow, ...]:
        links = sod.operator_candidate_generation_override_links
        receipts = sod.operator_ticket_audit_override_receipts
        rows = self._connection.execute(
            select(links)
            .join(
                receipts,
                receipts.c.ticket_audit_override_receipt_id
                == links.c.override_receipt_id,
            )
            .where(receipts.c.ticket_batch_revision_id == ticket_batch_revision_id)
            .order_by(links.c.generation_request_id, links.c.link_index)
        ).mappings()
        return tuple(CandidateGenerationOverrideLinkRow(**dict(row)) for row in rows)

    def insert_review_eligibility_fact(
        self, row: ReviewEligibilityFactRow
    ) -> None:
        self._connection.execute(
            insert(sor.operator_review_eligibility_facts).values(**_row_fields(row))
        )

    def review_eligibility_facts_for_work_item(
        self, work_item_id: str
    ) -> tuple[ReviewEligibilityFactRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_review_eligibility_facts)
            .where(
                sor.operator_review_eligibility_facts.c.work_item_id == work_item_id
            )
            .order_by(
                sor.operator_review_eligibility_facts.c.created_at,
                sor.operator_review_eligibility_facts.c.fact_index,
            )
        ).mappings()
        return tuple(ReviewEligibilityFactRow(**dict(row)) for row in rows)

    def insert_ticket_note(self, row: TicketNoteRow) -> None:
        self._connection.execute(
            insert(sor.operator_ticket_notes).values(**_row_fields(row))
        )

    def ticket_notes(self, ticket_id: str) -> tuple[TicketNoteRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_ticket_notes)
            .where(sor.operator_ticket_notes.c.ticket_id == ticket_id)
            .order_by(sor.operator_ticket_notes.c.note_index)
        ).mappings()
        return tuple(TicketNoteRow(**dict(row)) for row in rows)

    def insert_ticket_note_leg(self, row: TicketNoteLegRow) -> None:
        self._connection.execute(
            insert(sor.operator_ticket_note_legs).values(**_row_fields(row))
        )

    def ticket_note_legs(self, ticket_note_id: str) -> tuple[TicketNoteLegRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_ticket_note_legs)
            .where(sor.operator_ticket_note_legs.c.ticket_note_id == ticket_note_id)
            .order_by(sor.operator_ticket_note_legs.c.leg_index)
        ).mappings()
        return tuple(TicketNoteLegRow(**dict(row)) for row in rows)

    def insert_placement_cash_link(self, row: PlacementCashLinkRow) -> None:
        self._connection.execute(
            insert(sor.operator_placement_cash_links).values(**_row_fields(row))
        )

    def placement_cash_link(self, ticket_id: str) -> PlacementCashLinkRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_placement_cash_links).where(
                    sor.operator_placement_cash_links.c.ticket_id == ticket_id
                )
            )
            .mappings()
            .first()
        )
        return PlacementCashLinkRow(**dict(row)) if row is not None else None

    def insert_telegram_owner_heartbeat(
        self,
        row: TelegramOwnerHeartbeatRow,
    ) -> None:
        self._connection.execute(
            insert(sor.operator_telegram_owner_heartbeats).values(**_row_fields(row))
        )

    def telegram_owner_heartbeat(
        self,
        *,
        account_id: str,
        owner_instance_id: str,
    ) -> TelegramOwnerHeartbeatRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_telegram_owner_heartbeats).where(
                    sor.operator_telegram_owner_heartbeats.c.account_id == account_id,
                    sor.operator_telegram_owner_heartbeats.c.owner_instance_id
                    == owner_instance_id,
                )
            )
            .mappings()
            .first()
        )
        return TelegramOwnerHeartbeatRow(**dict(row)) if row is not None else None

    def telegram_owner_heartbeats(
        self,
        *,
        account_id: str,
    ) -> tuple[TelegramOwnerHeartbeatRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_telegram_owner_heartbeats)
            .where(
                sor.operator_telegram_owner_heartbeats.c.account_id == account_id
            )
            .order_by(
                sor.operator_telegram_owner_heartbeats.c.owner_instance_id
            )
        ).mappings()
        return tuple(TelegramOwnerHeartbeatRow(**dict(row)) for row in rows)

    def renew_telegram_owner_heartbeat(
        self,
        *,
        heartbeat_id: str,
        expected_sequence: int,
        heartbeat_sequence: int,
        observed_at: str,
        lease_expires_at: str,
    ) -> bool:
        result = self._connection.execute(
            update(sor.operator_telegram_owner_heartbeats)
            .where(
                sor.operator_telegram_owner_heartbeats.c.telegram_owner_heartbeat_id
                == heartbeat_id,
                sor.operator_telegram_owner_heartbeats.c.heartbeat_sequence
                == expected_sequence,
            )
            .values(
                heartbeat_sequence=heartbeat_sequence,
                observed_at=observed_at,
                lease_expires_at=lease_expires_at,
            )
        )
        return result.rowcount == 1

    def insert_telegram_callback_attestation(
        self,
        row: TelegramCallbackAttestationRow,
    ) -> None:
        self._connection.execute(
            insert(sor.operator_telegram_callback_attestations).values(
                **_row_fields(row)
            )
        )

    def telegram_callback_attestation(
        self,
        *,
        account_id: str,
        callback_query_id: str,
    ) -> TelegramCallbackAttestationRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_telegram_callback_attestations).where(
                    sor.operator_telegram_callback_attestations.c.account_id
                    == account_id,
                    sor.operator_telegram_callback_attestations.c.callback_query_id
                    == callback_query_id,
                )
            )
            .mappings()
            .first()
        )
        return TelegramCallbackAttestationRow(**dict(row)) if row is not None else None

    def insert_no_ticket_revision(self, row: NoTicketRevisionRow) -> None:
        values = _row_fields(row)
        for name in (
            "rule_ids",
            "missing_requirement_ids",
            "stale_requirement_ids",
            "conflicting_requirement_ids",
        ):
            values[f"{name}_json"] = canonical_json(list(values.pop(name)))
        self._connection.execute(
            insert(sod.operator_no_ticket_revisions).values(**values)
        )

    def no_ticket_revision(
        self, no_ticket_revision_id: str
    ) -> NoTicketRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_no_ticket_revisions).where(
                    sod.operator_no_ticket_revisions.c.no_ticket_revision_id
                    == no_ticket_revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_revision(
        self, no_ticket_family_id: str
    ) -> NoTicketRevisionRow | None:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("no_ticket_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.no_ticket_family_id == no_ticket_family_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.no_ticket_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_for_work_item(
        self, work_item_id: str
    ) -> NoTicketRevisionRow | None:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("work_item_no_ticket_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.work_item_id == work_item_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.no_ticket_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_revisions_for_task_family(
        self,
        task_family_id: str,
    ) -> tuple[NoTicketRevisionRow, ...]:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("task_family_no_ticket_children")
        rows = self._connection.execute(
            select(revisions)
            .where(
                revisions.c.task_family_id == task_family_id,
                ~exists(
                    select(1).where(
                        children.c.supersedes_revision_id
                        == revisions.c.no_ticket_revision_id
                    )
                ),
            )
            .order_by(revisions.c.recorded_at, revisions.c.no_ticket_revision_id)
        ).mappings()
        return tuple(_no_ticket_revision_row(row) for row in rows)

    def insert_no_ticket_offer_scope(self, row: NoTicketOfferScopeRow) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_offer_scopes).values(**_row_fields(row))
        )

    def no_ticket_offer_scopes(
        self, no_ticket_revision_id: str
    ) -> tuple[NoTicketOfferScopeRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_no_ticket_offer_scopes)
            .where(
                sod.operator_no_ticket_offer_scopes.c.no_ticket_revision_id
                == no_ticket_revision_id
            )
            .order_by(sod.operator_no_ticket_offer_scopes.c.scope_index)
        ).mappings()
        return tuple(NoTicketOfferScopeRow(**dict(row)) for row in rows)

    def insert_no_ticket_artifact_scope(
        self, row: NoTicketArtifactScopeRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_artifact_scopes).values(**_row_fields(row))
        )

    def no_ticket_artifact_scopes(
        self, no_ticket_revision_id: str
    ) -> tuple[NoTicketArtifactScopeRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_no_ticket_artifact_scopes)
            .where(
                sod.operator_no_ticket_artifact_scopes.c.no_ticket_revision_id
                == no_ticket_revision_id
            )
            .order_by(sod.operator_no_ticket_artifact_scopes.c.scope_index)
        ).mappings()
        return tuple(NoTicketArtifactScopeRow(**dict(row)) for row in rows)

    def insert_no_ticket_command_receipt(
        self, row: NoTicketCommandReceiptRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_command_receipts).values(**_row_fields(row))
        )

    def no_ticket_command_receipt_for_action(
        self, action_id: str
    ) -> NoTicketCommandReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_no_ticket_command_receipts).where(
                    sod.operator_no_ticket_command_receipts.c.action_id == action_id
                )
            )
            .mappings()
            .first()
        )
        return NoTicketCommandReceiptRow(**dict(row)) if row is not None else None

    def insert_fixed_prize_policy_revision(
        self, row: ZucaiFixedPrizePolicyRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sor.zucai_fixed_prize_policy_revisions).values(
                **_row_fields(row)
            )
        )

    def insert_fixed_prize_policy_tier(
        self, row: ZucaiFixedPrizePolicyTierRow
    ) -> None:
        self._connection.execute(
            insert(sor.zucai_fixed_prize_policy_tiers).values(**_row_fields(row))
        )

    def fixed_prize_policy_revision(
        self, revision_id: str
    ) -> ZucaiFixedPrizePolicyRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.zucai_fixed_prize_policy_revisions).where(
                    sor.zucai_fixed_prize_policy_revisions.c.
                    fixed_prize_policy_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return (
            ZucaiFixedPrizePolicyRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def current_fixed_prize_policy(
        self, ticket_kind: str
    ) -> ZucaiFixedPrizePolicyRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.zucai_fixed_prize_policy_revisions)
                .where(
                    sor.zucai_fixed_prize_policy_revisions.c.ticket_kind
                    == ticket_kind
                )
                .order_by(
                    sor.zucai_fixed_prize_policy_revisions.c.revision_no.desc(),
                    sor.zucai_fixed_prize_policy_revisions.c.created_at.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return (
            ZucaiFixedPrizePolicyRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def fixed_prize_policy_tiers(
        self, revision_id: str
    ) -> tuple[ZucaiFixedPrizePolicyTierRow, ...]:
        rows = self._connection.execute(
            select(sor.zucai_fixed_prize_policy_tiers)
            .where(
                sor.zucai_fixed_prize_policy_tiers.c.fixed_prize_policy_revision_id
                == revision_id
            )
            .order_by(sor.zucai_fixed_prize_policy_tiers.c.tier_index)
        ).mappings()
        return tuple(ZucaiFixedPrizePolicyTierRow(**dict(row)) for row in rows)

    def insert_candidate_set_revision(
        self, row: TicketCandidateSetRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_set_revisions).values(**_row_fields(row))
        )

    def candidate_set_revision(
        self, revision_id: str
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions).where(
                    sod.operator_candidate_set_revisions.c.candidate_set_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def candidate_sets_for_request(
        self, generation_request_id: str
    ) -> tuple[TicketCandidateSetRevisionRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_set_revisions)
            .where(
                sod.operator_candidate_set_revisions.c.generation_request_id
                == generation_request_id
            )
            .order_by(sod.operator_candidate_set_revisions.c.set_kind)
        ).mappings()
        return tuple(TicketCandidateSetRevisionRow(**dict(row)) for row in rows)

    def candidate_set_for_request(
        self,
        *,
        generation_request_id: str,
        set_kind: str,
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions).where(
                    sod.operator_candidate_set_revisions.c.generation_request_id
                    == generation_request_id,
                    sod.operator_candidate_set_revisions.c.set_kind == set_kind,
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def current_candidate_set(
        self,
        *,
        task_family_id: str,
        work_item_id: str,
        set_kind: str,
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions)
                .where(
                    sod.operator_candidate_set_revisions.c.task_family_id
                    == task_family_id,
                    sod.operator_candidate_set_revisions.c.work_item_id
                    == work_item_id,
                    sod.operator_candidate_set_revisions.c.set_kind == set_kind,
                )
                .order_by(
                    sod.operator_candidate_set_revisions.c.revision_no.desc(),
                    sod.operator_candidate_set_revisions.c.created_at.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def insert_candidate(self, row: TicketCandidateRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidates).values(**_row_fields(row))
        )

    def candidate(self, revision_id: str) -> TicketCandidateRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidates).where(
                    sod.operator_candidates.c.candidate_revision_id == revision_id
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateRow(**dict(row)) if row is not None else None

    def candidates_for_set(
        self, candidate_set_revision_id: str
    ) -> tuple[TicketCandidateRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidates)
            .where(
                sod.operator_candidates.c.candidate_set_revision_id
                == candidate_set_revision_id
            )
            .order_by(sod.operator_candidates.c.candidate_index)
        ).mappings()
        return tuple(TicketCandidateRow(**dict(row)) for row in rows)

    def insert_candidate_ticket(self, row: CandidateTicketRow) -> None:
        self._connection.execute(
            insert(sor.operator_candidate_tickets).values(**_row_fields(row))
        )

    def candidate_tickets(
        self, candidate_revision_id: str
    ) -> tuple[CandidateTicketRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_candidate_tickets)
            .where(
                sor.operator_candidate_tickets.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sor.operator_candidate_tickets.c.ticket_index)
        ).mappings()
        return tuple(CandidateTicketRow(**dict(row)) for row in rows)

    def insert_candidate_ticket_leg(self, row: CandidateTicketLegRow) -> None:
        self._connection.execute(
            insert(sor.operator_candidate_ticket_legs).values(**_row_fields(row))
        )

    def candidate_ticket_legs(
        self, candidate_ticket_id: str
    ) -> tuple[CandidateTicketLegRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_candidate_ticket_legs)
            .where(
                sor.operator_candidate_ticket_legs.c.candidate_ticket_id
                == candidate_ticket_id
            )
            .order_by(sor.operator_candidate_ticket_legs.c.leg_index)
        ).mappings()
        return tuple(CandidateTicketLegRow(**dict(row)) for row in rows)

    def insert_candidate_metric(self, row: CandidateMetricRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_metrics).values(**_row_fields(row))
        )

    def candidate_metric(self, candidate_revision_id: str) -> CandidateMetricRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_metrics).where(
                    sod.operator_candidate_metrics.c.candidate_revision_id
                    == candidate_revision_id
                )
            )
            .mappings()
            .first()
        )
        return CandidateMetricRow(**dict(row)) if row is not None else None

    def insert_candidate_dead_face(self, row: CandidateDeadFaceRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_dead_faces).values(**_row_fields(row))
        )

    def candidate_dead_faces(
        self, candidate_revision_id: str
    ) -> tuple[CandidateDeadFaceRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_dead_faces)
            .where(
                sod.operator_candidate_dead_faces.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sod.operator_candidate_dead_faces.c.dead_face_index)
        ).mappings()
        return tuple(CandidateDeadFaceRow(**dict(row)) for row in rows)

    def insert_candidate_audit_finding(
        self, row: CandidateAuditFindingRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_audit_findings).values(**_row_fields(row))
        )

    def candidate_audit_findings(
        self, candidate_revision_id: str
    ) -> tuple[CandidateAuditFindingRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_audit_findings)
            .where(
                sod.operator_candidate_audit_findings.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sod.operator_candidate_audit_findings.c.finding_index)
        ).mappings()
        return tuple(CandidateAuditFindingRow(**dict(row)) for row in rows)

    def candidate_audit_finding(
        self, candidate_audit_finding_id: str
    ) -> CandidateAuditFindingRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_audit_findings).where(
                    sod.operator_candidate_audit_findings.c.candidate_audit_finding_id
                    == candidate_audit_finding_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else CandidateAuditFindingRow(**dict(row))


def _row_fields(row) -> dict[str, object]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


def _ticket_audit_override_row(row) -> TicketAuditOverrideReceiptRow:
    values = dict(row)
    values["rule_ids"] = tuple(json.loads(values.pop("rule_ids_json")))
    values["evidence_rejected"] = tuple(
        json.loads(values.pop("evidence_rejected_json"))
    )
    return TicketAuditOverrideReceiptRow(**values)


def _no_ticket_revision_row(row) -> NoTicketRevisionRow:
    values = dict(row)
    for name in (
        "rule_ids",
        "missing_requirement_ids",
        "stale_requirement_ids",
        "conflicting_requirement_ids",
    ):
        values[name] = tuple(json.loads(values.pop(f"{name}_json")))
    return NoTicketRevisionRow(**values)


def _outcome_revision_row(row) -> OperatorOutcomeRevisionRow:
    values = dict(row)
    values["source_artifact_retrieval_ids"] = tuple(
        json.loads(values.pop("source_artifact_retrieval_ids_json"))
    )
    return OperatorOutcomeRevisionRow(**values)


def _task_settlement_run_row(row) -> TaskSettlementRunRow:
    values = dict(row)
    values["fixed_prize_policy_revision_ids"] = tuple(
        json.loads(values.pop("fixed_prize_policy_revision_ids_json"))
    )
    values["ticket_settlement_revision_ids"] = tuple(
        json.loads(values.pop("ticket_settlement_revision_ids_json"))
    )
    return TaskSettlementRunRow(**values)


__all__ = [
    "OperatorOutcomeRevisionRow",
    "OperatorResultRepository",
    "PlacementCashLinkRow",
    "ResultMatchRevisionRow",
    "ResultSetFamilyRow",
    "ResultSetRevisionRow",
    "ResultSourceReceiptRow",
    "SettlementCashLinkRow",
    "SettlementRequestRow",
    "TaskSettlementRunRow",
    "TaskSettlementSkipRow",
    "TelegramCallbackAttestationRow",
    "TelegramOwnerHeartbeatRow",
    "TicketNoteLegSettlementRow",
    "TicketNoteLegRow",
    "TicketNoteSettlementRow",
    "TicketNoteRow",
    "TicketSettlementRevisionRow",
    "ZucaiPrizeTableRevisionRow",
    "ZucaiPrizeTableTierRow",
]
