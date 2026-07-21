"""Decision (belief) layer value objects.

Forecast/factor/session status enums grade the belief write path; ids are opaque
and prefixed by kind (``fr-<hex>`` forecast revision, ``sess-<hex>`` session,
``eb-<hex>`` evidence bundle). Enum values are the strings stored in the database.
"""
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4


class SessionStatus(StrEnum):
    OPEN = 'open'
    CLOSED = 'closed'


class ForecastStatus(StrEnum):
    DRAFT = 'draft'
    COMMITTED = 'committed'
    SUPERSEDED = 'superseded'
    WITHDRAWN = 'withdrawn'


class FactorStatus(StrEnum):
    PROBATION = 'probation'
    ACTIVE = 'active'
    RETIRED = 'retired'


class CommitmentTier(StrEnum):
    FOLLOW = 'follow'
    LEAN = 'lean'
    COMMIT = 'commit'


def mint_decision_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'
