from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Actionability(StrEnum):
    VALUE = 'value'
    LEAN = 'lean'
    WATCH = 'watch'
    AVOID = 'avoid'
    NO_BET = 'no-bet'


ACTIONABLE_CLASSES = [
    Actionability.VALUE,
    Actionability.LEAN,
    Actionability.WATCH,
    Actionability.AVOID,
    Actionability.NO_BET,
]


class FreshnessHealth(StrEnum):
    HEALTHY = 'healthy'
    STALE = 'stale'
    PARTIAL = 'partial'
    FAILING = 'failing'


class EvidenceStaleness(StrEnum):
    FRESH = 'fresh'
    STALE = 'stale'
    UNAVAILABLE = 'unavailable'
    CONFLICTING = 'conflicting'


class SubscriptionPlan(StrEnum):
    OWNER = 'owner'
    FREE = 'free'
    BASIC = 'basic'
    PREMIUM = 'premium'
    EXPIRED = 'expired'


class SubscriptionStatus(StrEnum):
    ACTIVE = 'active'
    TRIAL = 'trial'
    EXPIRED = 'expired'
    DISABLED = 'disabled'


RESPONSIBLE_USE_COPY = '分析仅供参考，不构成投注建议；请量力而行，避免冲动投注。'


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(slots=True, frozen=True)
class FreshnessLedger:
    health: FreshnessHealth
    blocking_reasons: list[str] = field(default_factory=list)
    fixture_updated_at: datetime | None = None
    odds_updated_at: datetime | None = None
    team_player_updated_at: datetime | None = None
    tactical_updated_at: datetime | None = None
    information_updated_at: datetime | None = None
    analysis_generated_at: datetime | None = None

    @property
    def blocks_actionable_claim(self) -> bool:
        return self.health in {FreshnessHealth.STALE, FreshnessHealth.FAILING} or bool(
            self.blocking_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'fixture_updated_at': _serialize_datetime(self.fixture_updated_at),
            'odds_updated_at': _serialize_datetime(self.odds_updated_at),
            'team_player_updated_at': _serialize_datetime(self.team_player_updated_at),
            'tactical_updated_at': _serialize_datetime(self.tactical_updated_at),
            'information_updated_at': _serialize_datetime(self.information_updated_at),
            'analysis_generated_at': _serialize_datetime(self.analysis_generated_at),
            'health': self.health.value,
            'blocking_reasons': list(self.blocking_reasons),
        }


@dataclass(slots=True, frozen=True)
class EvidenceItem:
    kind: str
    source_name: str
    summary: str
    staleness: EvidenceStaleness
    evidence_id: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'evidence_id': self.evidence_id,
            'kind': self.kind,
            'source_name': self.source_name,
            'source_url': self.source_url,
            'published_at': _serialize_datetime(self.published_at),
            'retrieved_at': _serialize_datetime(self.retrieved_at),
            'summary': self.summary,
            'staleness': self.staleness.value,
        }


@dataclass(slots=True, frozen=True)
class SubscriptionEntitlement:
    user_id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    premium_match_detail_enabled: bool = False
    alerts_enabled: bool = False
    history_enabled: bool = False
    valid_until: datetime | None = None

    @classmethod
    def owner(cls, user_id: str = 'owner') -> 'SubscriptionEntitlement':
        return cls(
            user_id=user_id,
            plan=SubscriptionPlan.OWNER,
            status=SubscriptionStatus.ACTIVE,
            premium_match_detail_enabled=True,
            alerts_enabled=True,
            history_enabled=True,
        )

    @classmethod
    def free(cls, user_id: str) -> 'SubscriptionEntitlement':
        return cls(user_id=user_id, plan=SubscriptionPlan.FREE)

    @property
    def is_active(self) -> bool:
        return self.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}

    def to_dict(self) -> dict[str, Any]:
        return {
            'user_id': self.user_id,
            'plan': self.plan.value,
            'status': self.status.value,
            'premium_match_detail_enabled': self.premium_match_detail_enabled,
            'alerts_enabled': self.alerts_enabled,
            'history_enabled': self.history_enabled,
            'valid_until': _serialize_datetime(self.valid_until),
            'is_active': self.is_active,
        }


@dataclass(slots=True, frozen=True)
class WatchlistItem:
    watchlist_id: str
    user_id: str
    target_type: str
    target_id: str
    alert_preferences: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class Alert:
    alert_id: str
    user_id: str
    fixture_id: str
    change_type: str
    after_summary: str
    severity: str
    group_key: str
    created_at: datetime
    before_summary: str | None = None
    actionability_before: Actionability | None = None
    actionability_after: Actionability | None = None
    read_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AnalysisAuditRecord:
    audit_id: str
    user_id: str
    fixture_id: str
    actionability: Actionability
    confidence: str
    verdict: str
    evidence_snapshot: dict[str, Any]
    generated_text: str | None
    created_at: datetime
