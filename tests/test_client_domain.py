from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.client import (
    ACTIONABLE_CLASSES,
    RESPONSIBLE_USE_COPY,
    Actionability,
    EvidenceItem,
    EvidenceStaleness,
    FreshnessHealth,
    FreshnessLedger,
    SubscriptionEntitlement,
    SubscriptionPlan,
)


def test_client_domain_exposes_actionability_and_responsible_use_copy() -> None:
    assert [item.value for item in ACTIONABLE_CLASSES] == [
        'value',
        'lean',
        'watch',
        'avoid',
        'no-bet',
    ]
    assert Actionability.NO_BET.value == 'no-bet'
    assert '不构成投注建议' in RESPONSIBLE_USE_COPY


def test_freshness_ledger_blocks_action_when_stale_or_failing() -> None:
    stale = FreshnessLedger(
        health=FreshnessHealth.STALE,
        blocking_reasons=['odds snapshot is stale'],
        analysis_generated_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    healthy = FreshnessLedger(health=FreshnessHealth.HEALTHY, blocking_reasons=[])

    assert stale.blocks_actionable_claim is True
    assert healthy.blocks_actionable_claim is False
    assert stale.to_dict()['health'] == 'stale'
    assert stale.to_dict()['blocking_reasons'] == ['odds snapshot is stale']


def test_evidence_item_requires_source_for_external_claims() -> None:
    item = EvidenceItem(
        kind='odds',
        source_name='The Odds API',
        summary='Home price shortened from 2.10 to 1.91',
        staleness=EvidenceStaleness.FRESH,
        retrieved_at=datetime(2026, 4, 26, tzinfo=UTC),
    )

    assert item.to_dict()['source_name'] == 'The Odds API'
    assert item.to_dict()['staleness'] == 'fresh'
    assert item.to_dict()['retrieved_at'] == '2026-04-26T00:00:00+00:00'


def test_subscription_entitlement_defaults_owner_to_full_access() -> None:
    entitlement = SubscriptionEntitlement.owner('owner')

    assert entitlement.user_id == 'owner'
    assert entitlement.plan == SubscriptionPlan.OWNER
    assert entitlement.premium_match_detail_enabled is True
    assert entitlement.alerts_enabled is True
    assert entitlement.history_enabled is True
    assert entitlement.is_active is True
