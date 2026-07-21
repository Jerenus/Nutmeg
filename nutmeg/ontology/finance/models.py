"""Finance & outcome value objects.

Ticket/transaction/outcome/settlement status enums grade the money write path;
ids are opaque and prefixed by kind (``tk-`` ticket, ``bl-`` bet leg, ``cx-``
cash transaction, ``mo-`` match outcome). Enum values are stored verbatim.
"""
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4


class ProposalStatus(StrEnum):
    PROPOSED = 'proposed'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class TicketStatus(StrEnum):
    PROPOSED = 'proposed'
    APPROVED = 'approved'
    SETTLED = 'settled'
    VOID = 'void'


class TransactionKind(StrEnum):
    STAKE = 'stake'
    PAYOUT = 'payout'
    ADJUSTMENT = 'adjustment'


class OutcomeStatus(StrEnum):
    PROVISIONAL = 'provisional'
    FINAL = 'final'


class SettlementGrade(StrEnum):
    WIN = 'win'
    LOSS = 'loss'
    VOID = 'void'
    PUSH = 'push'


def mint_finance_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'
