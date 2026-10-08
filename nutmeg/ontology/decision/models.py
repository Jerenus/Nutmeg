"""Decision (belief) layer value objects.

The forecast status enum grades the belief write path; ids are opaque and
prefixed by kind (``fr-<hex>`` forecast revision, ``fs-<hex>`` series, ``fa-<hex>``
factor application). Enum values are the strings stored in the database.
"""
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4


class ForecastStatus(StrEnum):
    DRAFT = 'draft'
    COMMITTED = 'committed'
    SUPERSEDED = 'superseded'
    WITHDRAWN = 'withdrawn'


def mint_decision_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'
