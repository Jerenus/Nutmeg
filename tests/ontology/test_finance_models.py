from nutmeg.ontology.finance.models import (
    OutcomeStatus,
    ProposalStatus,
    SettlementGrade,
    TicketStatus,
    TransactionKind,
    mint_finance_id,
)


def test_enum_values() -> None:
    assert TicketStatus.APPROVED.value == "approved"
    assert TransactionKind.STAKE.value == "stake"
    assert TransactionKind.PAYOUT.value == "payout"
    assert OutcomeStatus.FINAL.value == "final"
    assert SettlementGrade.WIN.value == "win"
    assert SettlementGrade.LOSS.value == "loss"
    assert SettlementGrade.VOID.value == "void"
    assert ProposalStatus.PROPOSED.value == "proposed"


def test_mint_finance_id() -> None:
    a = mint_finance_id("tk")
    assert a.startswith("tk-") and a != mint_finance_id("tk")
