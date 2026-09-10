from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.product.operator_settlement import (
    SettlementLegInput,
    SettlementNoteInput,
    SettlementOutcomeInput,
    SettlementTicketInput,
    ZucaiPrizeTierInput,
    grade_ticket_settlement,
    plan_payout_cash_entries,
)
from tests.ontology.operator.test_task_settlement import (
    _invoke_public_result_ingest,
    _jczq_result_manifest_document,
    _place_jczq_ticket,
    _public_replay_workspace,
    _request_public_settlement,
    _seed_result_retrievals,
)


def _outcome(
    match_id: str,
    *,
    home_90: int | None,
    away_90: int | None,
    disposition: str = "played_90",
) -> SettlementOutcomeInput:
    return SettlementOutcomeInput(
        outcome_revision_id=f"outcome:{match_id}",
        match_id=match_id,
        result_disposition=disposition,
        home_90=home_90,
        away_90=away_90,
    )


def _leg(
    index: int,
    *,
    match_id: str,
    selection_code: str,
    market_definition_id: str = "md-had",
    odds: str | None = "2.000000000000",
    line: str | None = None,
    policy_id: str | None = None,
) -> SettlementLegInput:
    return SettlementLegInput(
        ticket_note_leg_id=f"leg-{index}",
        official_offer_revision_id=f"offer-{index}",
        match_id=match_id,
        market_definition_id=market_definition_id,
        selection_code=selection_code,
        booked_decimal_odds=odds,
        settlement_parameter_decimal=line,
        fixed_prize_policy_revision_id=policy_id,
    )


def test_jczq_ticket_plan_grades_each_legs_own_outcome_and_reconciles_counts() -> None:
    ticket = SettlementTicketInput(
        ticket_id="ticket-jczq",
        ticket_kind="jczq_pass",
        currency="CNY",
        stake_minor=400,
        fixed_prize_policy_revision_id=None,
        notes=(
            SettlementNoteInput(
                ticket_note_id="note-won",
                ticket_kind="jczq_pass",
                currency="CNY",
                unit_stake_minor=200,
                unit_count=1,
                stake_minor=200,
                fixed_prize_policy_revision_id=None,
                legs=(
                    _leg(1, match_id="match-1", selection_code="3", odds="1.500000000000"),
                    _leg(2, match_id="match-2", selection_code="1", odds="3.000000000000"),
                ),
            ),
            SettlementNoteInput(
                ticket_note_id="note-lost",
                ticket_kind="jczq_pass",
                currency="CNY",
                unit_stake_minor=200,
                unit_count=1,
                stake_minor=200,
                fixed_prize_policy_revision_id=None,
                legs=(
                    _leg(3, match_id="match-1", selection_code="0"),
                    _leg(4, match_id="match-2", selection_code="1"),
                ),
            ),
        ),
    )

    plan = grade_ticket_settlement(
        ticket,
        settlement_method_version="operator-task-settlement-v1",
        outcomes_by_match={
            "match-1": _outcome("match-1", home_90=2, away_90=1),
            "match-2": _outcome("match-2", home_90=0, away_90=0),
        },
    )

    assert [note.note_grade for note in plan.notes] == ["won", "lost"]
    assert [note.payout_minor for note in plan.notes] == [900, 0]
    assert plan.distinct_note_count == 2
    assert plan.paid_note_unit_count == 2
    assert plan.winning_note_unit_count == 1
    assert plan.void_note_unit_count == 0
    assert plan.gross_payout_minor == 900
    assert [leg.outcome_revision_id for leg in plan.notes[0].legs] == [
        "outcome:match-1",
        "outcome:match-2",
    ]


def test_jczq_all_void_note_refunds_its_exact_persisted_stake() -> None:
    policy = None
    ticket = SettlementTicketInput(
        ticket_id="ticket-void",
        ticket_kind="jczq_pass",
        currency="CNY",
        stake_minor=600,
        fixed_prize_policy_revision_id=policy,
        notes=(
            SettlementNoteInput(
                ticket_note_id="note-void",
                ticket_kind="jczq_pass",
                currency="CNY",
                unit_stake_minor=200,
                unit_count=3,
                stake_minor=600,
                fixed_prize_policy_revision_id=policy,
                legs=(_leg(1, match_id="match-1", selection_code="3"),),
            ),
        ),
    )

    plan = grade_ticket_settlement(
        ticket,
        settlement_method_version="operator-task-settlement-v1",
        outcomes_by_match={
            "match-1": _outcome(
                "match-1",
                home_90=None,
                away_90=None,
                disposition="official_void",
            )
        },
    )

    assert plan.notes[0].note_grade == "void"
    assert plan.notes[0].void_unit_count == 3
    assert plan.void_note_unit_count == 3
    assert plan.gross_payout_minor == 600


@pytest.mark.parametrize(
    ("ticket_kind", "leg_count", "required_correct", "tier_code", "payout"),
    (
        ("sfc", 14, 14, "sfc_first", 1_000_000),
        ("sfc", 14, 13, "sfc_second", 20_000),
        ("renjiu", 9, 9, "renjiu_first", 1_000),
    ),
)
def test_zucai_ticket_plan_uses_exact_bound_legs_and_one_exact_tier(
    ticket_kind: str,
    leg_count: int,
    required_correct: int,
    tier_code: str,
    payout: int,
) -> None:
    policy_id = f"policy:{ticket_kind}"
    losing = leg_count - required_correct
    legs = tuple(
        _leg(
            index,
            match_id=f"match-{index}",
            selection_code="0" if index < losing else "3",
            odds=None,
            policy_id=policy_id,
        )
        for index in range(leg_count)
    )
    ticket = SettlementTicketInput(
        ticket_id=f"ticket:{ticket_kind}",
        ticket_kind=ticket_kind,
        currency="CNY",
        stake_minor=400,
        fixed_prize_policy_revision_id=policy_id,
        notes=(
            SettlementNoteInput(
                ticket_note_id="note-1",
                ticket_kind=ticket_kind,
                currency="CNY",
                unit_stake_minor=200,
                unit_count=2,
                stake_minor=400,
                fixed_prize_policy_revision_id=policy_id,
                legs=legs,
            ),
        ),
    )

    plan = grade_ticket_settlement(
        ticket,
        settlement_method_version="operator-task-settlement-v1",
        outcomes_by_match={
            f"match-{index}": _outcome(
                f"match-{index}", home_90=1, away_90=0
            )
            for index in range(leg_count)
        },
        prize_tiers=(
            ZucaiPrizeTierInput(
                tier_code=tier_code,
                ticket_kind=ticket_kind,
                required_correct_count=required_correct,
                payout_minor_per_winning_note=payout,
            ),
        ),
    )

    note = plan.notes[0]
    assert note.note_grade == "won"
    assert note.correct_leg_count == required_correct
    assert note.prize_tier_code == tier_code
    assert note.payout_minor == payout * 2
    assert plan.winning_note_unit_count == 2
    assert plan.void_note_unit_count == 0


def test_settlement_plan_fails_closed_on_missing_outcome_or_binding_drift() -> None:
    note = SettlementNoteInput(
        ticket_note_id="note-1",
        ticket_kind="jczq_pass",
        currency="CNY",
        unit_stake_minor=200,
        unit_count=1,
        stake_minor=200,
        fixed_prize_policy_revision_id=None,
        legs=(_leg(1, match_id="match-1", selection_code="3"),),
    )
    ticket = SettlementTicketInput(
        ticket_id="ticket-1",
        ticket_kind="jczq_pass",
        currency="CNY",
        stake_minor=200,
        fixed_prize_policy_revision_id=None,
        notes=(note,),
    )

    with pytest.raises(ValueError, match="Outcome"):
        grade_ticket_settlement(
            ticket,
            settlement_method_version="operator-task-settlement-v1",
            outcomes_by_match={},
        )
    with pytest.raises(ValueError, match="stake"):
        grade_ticket_settlement(
            SettlementTicketInput(
                ticket_id=ticket.ticket_id,
                ticket_kind=ticket.ticket_kind,
                currency=ticket.currency,
                stake_minor=400,
                fixed_prize_policy_revision_id=None,
                notes=ticket.notes,
            ),
            settlement_method_version="operator-task-settlement-v1",
            outcomes_by_match={
                "match-1": _outcome("match-1", home_90=1, away_90=0)
            },
        )


@pytest.mark.parametrize(
    (
        "prior_payout_minor",
        "new_payout_minor",
        "prior_transaction_id",
        "expected",
    ),
    (
        (500, 0, "payout-v1", (("payout_reversal", -500, "payout-v1"),)),
        (0, 700, None, (("payout", 700, None),)),
        (
            500,
            700,
            "payout-v1",
            (
                ("payout_reversal", -500, "payout-v1"),
                ("payout", 700, None),
            ),
        ),
        (0, 0, None, ()),
    ),
)
def test_payout_correction_has_exact_closed_cash_transitions(
    prior_payout_minor: int,
    new_payout_minor: int,
    prior_transaction_id: str | None,
    expected: tuple[tuple[str, int, str | None], ...],
) -> None:
    entries = plan_payout_cash_entries(
        prior_payout_minor=prior_payout_minor,
        new_payout_minor=new_payout_minor,
        predecessor_payout_transaction_id=prior_transaction_id,
    )

    assert tuple(
        (entry.transaction_kind, entry.amount_minor, entry.reverses_transaction_id)
        for entry in entries
    ) == expected


def test_consecutive_correction_reverses_only_the_direct_predecessor_replacement() -> None:
    second_revision = plan_payout_cash_entries(
        prior_payout_minor=500,
        new_payout_minor=700,
        predecessor_payout_transaction_id="payout-v1",
    )
    assert second_revision[-1].transaction_kind == "payout"

    third_revision = plan_payout_cash_entries(
        prior_payout_minor=700,
        new_payout_minor=300,
        predecessor_payout_transaction_id="payout-v2",
    )

    assert [entry.reverses_transaction_id for entry in third_revision] == [
        "payout-v2",
        None,
    ]
    assert all(
        entry.reverses_transaction_id != "payout-v1" for entry in third_revision
    )


@pytest.mark.parametrize(
    ("prior", "new", "transaction_id"),
    (
        (-1, 0, "payout-v1"),
        (0, -1, None),
        (True, 0, "payout-v1"),
        (0, False, None),
        (500, 0, None),
        (0, 500, "unexpected-prior"),
    ),
)
def test_payout_correction_rejects_ambiguous_or_invalid_predecessor_state(
    prior: int,
    new: int,
    transaction_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        plan_payout_cash_entries(
            prior_payout_minor=prior,
            new_payout_minor=new,
            predecessor_payout_transaction_id=transaction_id,
        )


def test_isolated_direct_predecessor_correction_replay(tmp_path: Path) -> None:
    root, workspace = _public_replay_workspace(tmp_path)
    captured_base = datetime.now(UTC) - timedelta(minutes=4)
    fixture = _place_jczq_ticket(
        workspace,
        result_captured_at=captured_base.isoformat(),
        complete_market_baseline_job=True,
    )
    first_document = _jczq_result_manifest_document(
        task_snapshot_hash=fixture.context.task_snapshot_hash,
        captured_at=captured_base.isoformat(),
    )
    _invoke_public_result_ingest(
        root=root,
        manifest_name="correction-result-0.json",
        document=first_document,
    )
    projected = _request_public_settlement(
        root=root,
        lane="jczq",
        business_key="2026-09-04",
        clock_at=datetime.now(UTC),
        idempotency_key="public:correction:settlement:0",
    )

    for revision_no, (home_90, away_90) in enumerate(
        ((0, 1), (3, 1), (4, 1)),
        start=1,
    ):
        with fixture.engine.connect() as connection:
            predecessor_id = connection.scalar(
                select(sor.operator_result_set_revisions.c.result_set_revision_id)
                .order_by(sor.operator_result_set_revisions.c.revision_no.desc())
                .limit(1)
            )
        assert predecessor_id is not None
        captured_at = (captured_base + timedelta(minutes=revision_no)).isoformat()
        suffix = f"-public-correction-{revision_no}"
        _seed_result_retrievals(
            fixture.engine,
            suffix=suffix,
            captured_at=captured_at,
        )
        document = _jczq_result_manifest_document(
            task_snapshot_hash=fixture.context.task_snapshot_hash,
            captured_at=captured_at,
        )
        document["supersedes_result_set_token"] = predecessor_id
        match = document["matches"][0]
        assert isinstance(match, dict)
        sources = match["sources"]
        assert isinstance(sources, list)
        for source in sources:
            assert isinstance(source, dict)
            source["artifact_retrieval_id"] = (
                f"result-retrieval-{source['source_kind']}{suffix}"
            )
            source["home_90"] = home_90
            source["away_90"] = away_90
        _invoke_public_result_ingest(
            root=root,
            manifest_name=f"correction-result-{revision_no}.json",
            document=document,
        )
        projected = _request_public_settlement(
            root=root,
            lane="jczq",
            business_key="2026-09-04",
            clock_at=datetime.now(UTC),
            idempotency_key=f"public:correction:settlement:{revision_no}",
        )

    with fixture.engine.connect() as connection:
        result_sets = connection.execute(
            select(sor.operator_result_set_revisions).order_by(
                sor.operator_result_set_revisions.c.revision_no
            )
        ).mappings().all()
        outcomes = connection.execute(
            select(sor.operator_outcome_revisions).order_by(
                sor.operator_outcome_revisions.c.revision_no
            )
        ).mappings().all()
        settlements = connection.execute(
            select(sor.operator_ticket_settlement_revisions).order_by(
                sor.operator_ticket_settlement_revisions.c.revision_no
            )
        ).mappings().all()
        cash_links = connection.execute(
            text("SELECT * FROM operator_settlement_cash_links ORDER BY rowid")
        ).mappings().all()
        action_counts = dict(
            connection.execute(
                select(schema.actions.c.action_type, func.count())
                .where(
                    schema.actions.c.action_type.in_(
                        (
                            "import_result_evidence_set",
                            "request_settlement",
                            "settle_task",
                        )
                    )
                )
                .group_by(schema.actions.c.action_type)
            ).all()
        )
        stake_count = connection.scalar(
            select(func.count())
            .select_from(sf.cash_transactions)
            .where(sf.cash_transactions.c.kind == "stake")
        )
        ticket_count = connection.scalar(
            select(func.count()).select_from(sf.tickets)
        )

    assert len(result_sets) == len(outcomes) == len(settlements) == 4
    for rows, id_key in (
        (result_sets, "result_set_revision_id"),
        (outcomes, "outcome_revision_id"),
        (settlements, "settlement_revision_id"),
    ):
        assert rows[0]["supersedes_revision_id"] is None
        assert [row["supersedes_revision_id"] for row in rows[1:]] == [
            row[id_key] for row in rows[:-1]
        ]
    assert [row["gross_payout_minor"] for row in settlements] == [500, 0, 500, 500]
    assert [row["amount_minor"] for row in cash_links] == [500, -500, 500, -500, 500]
    payout_ids = [
        row["transaction_id"]
        for row in cash_links
        if row["transaction_kind"] == "payout"
    ]
    assert [
        row["reverses_transaction_id"]
        for row in cash_links
        if row["transaction_kind"] == "payout_reversal"
    ] == payout_ids[:2]
    assert action_counts == {
        "import_result_evidence_set": 4,
        "request_settlement": 4,
        "settle_task": 4,
    }
    assert stake_count == ticket_count == 1
    assert projected["step"]["result_state"] == "corrected"
    assert projected["step"]["settlement_state"] == "corrected"
    assert projected["step"]["tickets"][0]["revision_no"] == 4
    assert projected["step"]["tickets"][0]["corrected"] is True
