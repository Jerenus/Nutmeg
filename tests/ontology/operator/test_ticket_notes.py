from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.operator.confirmation import (
    TicketNoteLegDraft,
    materialize_ticket_note_drafts,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_result import (
    CandidateTicketLegRow,
    CandidateTicketRow,
    OperatorResultRepository,
    PlacementCashLinkRow,
    TicketNoteLegRow,
    TicketNoteRow,
)


def _ticket(*, ticket_kind: str = "jczq_pass") -> CandidateTicketRow:
    return CandidateTicketRow(
        candidate_ticket_id="candidate-ticket-1",
        candidate_revision_id="candidate-1",
        ticket_index=0,
        ticket_kind=ticket_kind,
        structure_code="2x1" if ticket_kind == "jczq_pass" else ticket_kind,
        group_code="A" if ticket_kind == "jczq_pass" else None,
        currency="CNY",
        unit_stake_minor=200,
        unit_count=2,
        stake_minor=400,
        composition_hash="candidate-composition",
        fixed_prize_policy_revision_id=(
            None if ticket_kind == "jczq_pass" else "fixed-policy-1"
        ),
    )


def _leg(
    *,
    leg_index: int,
    offer: str,
    match: str,
    face: str,
    odds: str = "2.000000000000",
) -> CandidateTicketLegRow:
    return CandidateTicketLegRow(
        candidate_ticket_leg_id=f"leg-{leg_index}",
        candidate_ticket_id="candidate-ticket-1",
        leg_index=leg_index,
        official_offer_revision_id=offer,
        match_id=match,
        market_definition_id="md-had",
        selection_code=face,
        quote_id=f"quote-{leg_index}",
        booked_decimal_odds=odds,
        settlement_parameter_decimal=None,
    )


def test_jczq_multi_face_legs_expand_and_combine_canonical_notes() -> None:
    legs = (
        _leg(leg_index=0, offer="offer-1", match="match-1", face="3"),
        _leg(leg_index=1, offer="offer-1", match="match-1", face="1"),
        _leg(leg_index=2, offer="offer-2", match="match-2", face="0"),
    )

    notes = materialize_ticket_note_drafts(_ticket(), legs)

    assert len(notes) == 2
    assert sum(note.unit_count for note in notes) == 2
    assert sum(note.stake_minor for note in notes) == 400
    assert [tuple(leg.selection_code for leg in note.legs) for note in notes] == [
        ("1", "0"),
        ("3", "0"),
    ]
    assert all(note.unit_count == 1 for note in notes)
    assert all(note.fixed_prize_policy_revision_id is None for note in notes)


def test_duplicate_canonical_notes_are_combined_through_unit_count() -> None:
    ticket = replace(_ticket(), unit_count=4, stake_minor=800)
    legs = (
        _leg(leg_index=0, offer="offer-1", match="match-1", face="3"),
        _leg(leg_index=1, offer="offer-1", match="match-1", face="1"),
        _leg(leg_index=2, offer="offer-2", match="match-2", face="0"),
    )

    notes = materialize_ticket_note_drafts(ticket, legs)

    assert [note.unit_count for note in notes] == [2, 2]
    assert [note.stake_minor for note in notes] == [400, 400]


def test_same_offer_cross_market_faces_share_one_canonical_choice_group() -> None:
    ticket = replace(_ticket(), unit_count=2, stake_minor=400)
    legs = (
        _leg(
            leg_index=0,
            offer="offer-1",
            match="match-1",
            face="3",
        ),
        replace(
            _leg(
                leg_index=1,
                offer="offer-1",
                match="match-1",
                face="1",
                odds="3.200000000000",
            ),
            market_definition_id="md-hhad",
            settlement_parameter_decimal="-1.000000000000",
        ),
    )

    notes = materialize_ticket_note_drafts(ticket, legs)

    assert len(notes) == 2
    assert [note.unit_count for note in notes] == [1, 1]
    assert [note.legs[0].market_definition_id for note in notes] == [
        "md-had",
        "md-hhad",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("quote_id", None, "quote"),
        ("booked_decimal_odds", None, "odds"),
        ("booked_decimal_odds", "0.000000000000", "positive"),
    ],
)
def test_jczq_note_rejects_missing_or_invalid_booked_quote(
    field: str,
    value: str | None,
    message: str,
) -> None:
    leg = replace(
        _leg(leg_index=0, offer="offer-1", match="match-1", face="3"),
        **{field: value},
    )

    with pytest.raises(ValueError, match=message):
        materialize_ticket_note_drafts(
            replace(_ticket(), unit_count=1, stake_minor=200),
            (leg,),
        )


def test_zucai_notes_copy_policy_and_forbid_quote_fields() -> None:
    ticket = replace(_ticket(ticket_kind="renjiu"), unit_count=1, stake_minor=200)
    leg = TicketNoteLegDraft(
        official_offer_revision_id="offer-1",
        match_id="match-1",
        market_definition_id="md-had",
        selection_code="3",
        quote_id=None,
        booked_decimal_odds=None,
        settlement_parameter_decimal=None,
        fixed_prize_policy_revision_id="fixed-policy-1",
    )

    notes = materialize_ticket_note_drafts(ticket, (leg,))

    assert len(notes) == 1
    assert notes[0].fixed_prize_policy_revision_id == "fixed-policy-1"
    assert notes[0].legs[0].fixed_prize_policy_revision_id == "fixed-policy-1"

    with pytest.raises(ValueError, match="forbids quote"):
        materialize_ticket_note_drafts(
            ticket,
            (replace(leg, quote_id="quote-1"),),
        )


def _note_row(*, note_id: str, note_index: int, composition_hash: str) -> TicketNoteRow:
    return TicketNoteRow(
        ticket_note_id=note_id,
        ticket_id="ticket-1",
        ticket_artifact_id="ticket-artifact-1",
        note_index=note_index,
        ticket_kind="jczq_pass",
        structure_code="2x1",
        group_code="A",
        currency="CNY",
        unit_stake_minor=200,
        unit_count=1,
        stake_minor=200,
        composition_hash=composition_hash,
        fixed_prize_policy_revision_id=None,
        action_id="action-placement-1",
        created_at="2026-09-04T09:00:00+00:00",
    )


def _note_leg_row(*, note_id: str, leg_index: int) -> TicketNoteLegRow:
    return TicketNoteLegRow(
        ticket_note_leg_id=f"{note_id}-leg-{leg_index}",
        ticket_note_id=note_id,
        leg_index=leg_index,
        official_offer_revision_id=f"offer-{leg_index}",
        match_id=f"match-{leg_index}",
        market_definition_id="md-had",
        selection_code="3",
        quote_id=f"quote-{leg_index}",
        booked_decimal_odds="2.000000000000",
        settlement_parameter_decimal=None,
        fixed_prize_policy_revision_id=None,
        action_id="action-placement-1",
    )


def _insert_v2_ticket(connection, *, stake_minor: int = 400) -> None:
    connection.execute(
        text(
            "INSERT INTO tickets "
            "(ticket_id, channel, proposal_id, approved_at, status, structure, "
            "total_stake, currency, account_id, ticket_kind, stake_minor, "
            "fixed_prize_policy_revision_id) VALUES "
            "('ticket-1', 'jczq', NULL, '2026-09-04T09:00:00+00:00', "
            "'approved', '2x1', :total_stake, 'CNY', 'account-1', "
            "'jczq_pass', :stake_minor, NULL)"
        ),
        {"total_stake": stake_minor / 100, "stake_minor": stake_minor},
    )


def test_ticket_note_repository_round_trips_canonical_order(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "notes.db")
    run_migrations(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        _insert_v2_ticket(connection)
        repository = OperatorResultRepository(connection)
        repository.insert_ticket_note(
            _note_row(note_id="note-2", note_index=1, composition_hash="hash-2")
        )
        repository.insert_ticket_note(
            _note_row(note_id="note-1", note_index=0, composition_hash="hash-1")
        )
        repository.insert_ticket_note_leg(_note_leg_row(note_id="note-1", leg_index=1))
        repository.insert_ticket_note_leg(_note_leg_row(note_id="note-1", leg_index=0))
        connection.commit()

        assert [row.ticket_note_id for row in repository.ticket_notes("ticket-1")] == [
            "note-1",
            "note-2",
        ]
        assert [
            row.ticket_note_leg_id for row in repository.ticket_note_legs("note-1")
        ] == ["note-1-leg-0", "note-1-leg-1"]


def test_note_leg_shape_and_business_rows_are_append_only(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "note-shape.db")
    run_migrations(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        _insert_v2_ticket(connection)
        repository = OperatorResultRepository(connection)
        repository.insert_ticket_note(
            _note_row(note_id="note-1", note_index=0, composition_hash="hash-1")
        )
        with pytest.raises(IntegrityError):
            repository.insert_ticket_note_leg(
                replace(
                    _note_leg_row(note_id="note-1", leg_index=0),
                    quote_id=None,
                    booked_decimal_odds=None,
                )
            )
        repository.insert_ticket_note_leg(_note_leg_row(note_id="note-1", leg_index=0))
        connection.commit()

        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE operator_ticket_notes SET unit_count = 2 "
                    "WHERE ticket_note_id = 'note-1'"
                )
            )


def test_placement_cash_link_requires_integer_conservation(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "cash-link.db")
    run_migrations(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        connection.execute(
            text(
                "INSERT INTO cash_accounts "
                "(account_id, channel_scope, currency, status) "
                "VALUES ('account-1', 'jczq', 'CNY', 'active')"
            )
        )
        _insert_v2_ticket(connection)
        repository = OperatorResultRepository(connection)
        repository.insert_ticket_note(
            replace(
                _note_row(note_id="note-1", note_index=0, composition_hash="hash-1"),
                unit_count=2,
                stake_minor=400,
            )
        )
        connection.execute(
            text(
                "INSERT INTO cash_transactions "
                "(transaction_id, account_id, ticket_id, ticket_settlement_id, kind, "
                "amount, amount_minor, currency, occurred_at, idempotency_key) VALUES "
                "('cash-1', 'account-1', 'ticket-1', NULL, 'stake', -4.0, -400, "
                "'CNY', '2026-09-04T09:00:00+00:00', 'cash:1')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ticket_placements "
                "(ticket_placement_id, ticket_artifact_id, ticket_id, "
                "placement_mode, external_reference, receipt_artifact_id, "
                "receipt_retrieval_id, placed_at, action_id) VALUES "
                "('placement-1', 'ticket-artifact-1', 'ticket-1', 'manual', "
                "'manual-receipt', NULL, NULL, '2026-09-04T09:00:00+00:00', "
                "'action-placement-1')"
            )
        )
        with pytest.raises(IntegrityError, match="reconcile"):
            repository.insert_placement_cash_link(
                PlacementCashLinkRow(
                    placement_cash_link_id="cash-link-bad",
                    ticket_id="ticket-1",
                    transaction_id="cash-1",
                    stake_minor=200,
                    currency="CNY",
                    action_id="action-placement-1",
                    created_at="2026-09-04T09:00:00+00:00",
                )
            )
        with pytest.raises(IntegrityError, match="reconcile"):
            repository.insert_placement_cash_link(
                PlacementCashLinkRow(
                    placement_cash_link_id="cash-link-wrong-action",
                    ticket_id="ticket-1",
                    transaction_id="cash-1",
                    stake_minor=400,
                    currency="CNY",
                    action_id="action-placement-2",
                    created_at="2026-09-04T09:00:00+00:00",
                )
            )
        repository.insert_placement_cash_link(
            PlacementCashLinkRow(
                placement_cash_link_id="cash-link-1",
                ticket_id="ticket-1",
                transaction_id="cash-1",
                stake_minor=400,
                currency="CNY",
                action_id="action-placement-1",
                created_at="2026-09-04T09:00:00+00:00",
            )
        )
        connection.commit()

        assert repository.placement_cash_link("ticket-1") == PlacementCashLinkRow(
            placement_cash_link_id="cash-link-1",
            ticket_id="ticket-1",
            transaction_id="cash-1",
            stake_minor=400,
            currency="CNY",
            action_id="action-placement-1",
            created_at="2026-09-04T09:00:00+00:00",
        )
