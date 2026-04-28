from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from nutmeg.core.quota import QuotaSnapshot


class UserTier(StrEnum):
    OWNER = 'owner'
    FRIEND = 'friend'
    SUBSCRIBER = 'subscriber'


@dataclass(slots=True, frozen=True)
class UserIdentity:
    user_id: str
    tier: UserTier
    created_at: datetime
    quota: QuotaSnapshot = field(default_factory=QuotaSnapshot)
    preferences: dict[str, object] = field(default_factory=dict)


def owner_identity(preferences: dict[str, object] | None = None) -> UserIdentity:
    return UserIdentity(
        user_id='owner',
        tier=UserTier.OWNER,
        created_at=datetime.now(UTC),
        preferences=preferences or {},
    )
