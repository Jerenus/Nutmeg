"""Evidence & context value objects.

Availability/status/lineup describe people in a match; ClaimStatus and
VerificationMethod grade evidence. Enum values are stable snake_case and are the
strings stored in the database. Evidence ids are opaque and prefixed by kind
(``claim-<hex>``, ``obs-<hex>``).
"""
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4


class Availability(StrEnum):
    EXPECTED = 'expected'
    AVAILABLE = 'available'
    DOUBTFUL = 'doubtful'
    OUT = 'out'
    SUSPENDED = 'suspended'
    RETURNED = 'returned'


class StatusKind(StrEnum):
    INJURY = 'injury'
    SUSPENSION = 'suspension'
    ROTATION = 'rotation'
    SELECTION = 'selection'
    COACH_STATUS = 'coach_status'


class LineupStatus(StrEnum):
    EXPECTED = 'expected'
    CONFIRMED = 'confirmed'


class LineupRole(StrEnum):
    STARTER = 'starter'
    SUBSTITUTE = 'substitute'
    UNAVAILABLE = 'unavailable'


class ClaimStatus(StrEnum):
    PROVISIONAL = 'provisional'
    CORROBORATED = 'corroborated'
    VERIFIED = 'verified'
    DISPUTED = 'disputed'
    EXPIRED = 'expired'
    RETRACTED = 'retracted'


class VerificationMethod(StrEnum):
    DETERMINISTIC = 'deterministic'
    OFFICIAL = 'official'
    CORROBORATED = 'corroborated'
    ADJUDICATED = 'adjudicated'


def mint_evidence_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'
