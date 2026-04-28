from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nutmeg.domain.client import Actionability, SubscriptionPlan, SubscriptionStatus
from nutmeg.storage.client_state_repository import SqlAlchemyClientStateRepository


def _repository() -> tuple[SqlAlchemyClientStateRepository, Session]:
    engine = create_engine('sqlite:///:memory:', future=True)
    session = Session(engine)
    return SqlAlchemyClientStateRepository(session), session


def test_client_state_repository_isolates_entitlements_by_user() -> None:
    repository, session = _repository()
    try:
        repository.upsert_entitlement(
            user_id='owner',
            plan=SubscriptionPlan.OWNER,
            status=SubscriptionStatus.ACTIVE,
            premium_match_detail_enabled=True,
            alerts_enabled=True,
            history_enabled=True,
        )
        repository.upsert_entitlement(
            user_id='guest',
            plan=SubscriptionPlan.BASIC,
            status=SubscriptionStatus.ACTIVE,
            premium_match_detail_enabled=False,
            alerts_enabled=False,
            history_enabled=False,
        )

        assert repository.get_entitlement('owner').premium_match_detail_enabled is True
        assert repository.get_entitlement('guest').premium_match_detail_enabled is False
    finally:
        session.close()


def test_client_state_repository_upserts_watchlist_without_cross_user_leakage() -> None:
    repository, session = _repository()
    try:
        first_id = repository.upsert_watchlist_item(
            user_id='owner',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['odds'],
        )
        second_id = repository.upsert_watchlist_item(
            user_id='owner',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['odds', 'lineup'],
        )
        repository.upsert_watchlist_item(
            user_id='guest',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['injury'],
        )

        assert second_id == first_id
        assert repository.list_watchlist('owner')[0].alert_preferences == ['odds', 'lineup']
        assert repository.list_watchlist('guest')[0].alert_preferences == ['injury']
    finally:
        session.close()


def test_client_state_repository_groups_alerts_by_user_fixture_and_group_key() -> None:
    repository, session = _repository()
    try:
        first_id = repository.create_alert(
            user_id='owner',
            fixture_id='epl-001',
            change_type='odds',
            after_summary='Home price shortened',
            severity='important',
            group_key='epl-001:odds',
            actionability_before=Actionability.WATCH,
            actionability_after=Actionability.VALUE,
        )
        second_id = repository.create_alert(
            user_id='owner',
            fixture_id='epl-001',
            change_type='odds',
            after_summary='Home price shortened again',
            severity='important',
            group_key='epl-001:odds',
            actionability_before=Actionability.WATCH,
            actionability_after=Actionability.VALUE,
        )

        alerts = repository.list_alerts('owner')
        assert second_id == first_id
        assert len(alerts) == 1
        assert alerts[0].after_summary == 'Home price shortened again'
        assert alerts[0].actionability_after == Actionability.VALUE
    finally:
        session.close()


def test_client_state_repository_inserts_audit_records_by_user() -> None:
    repository, session = _repository()
    try:
        audit_id = repository.insert_audit_record(
            user_id='owner',
            fixture_id='epl-001',
            actionability=Actionability.LEAN,
            confidence='medium',
            verdict='Lean Arsenal pre-match.',
            evidence_snapshot={'health': 'healthy'},
            generated_text='Lean Arsenal pre-match.',
        )

        owner_records = repository.list_audit_records('owner')
        guest_records = repository.list_audit_records('guest')
        assert owner_records[0].audit_id == audit_id
        assert owner_records[0].evidence_snapshot == {'health': 'healthy'}
        assert guest_records == []
    finally:
        session.close()


def test_client_state_repository_audit_records_do_not_store_secret_keys() -> None:
    repository, session = _repository()
    try:
        audit_id = repository.insert_audit_record(
            user_id='owner',
            fixture_id='epl-001',
            actionability=Actionability.VALUE,
            confidence='high',
            verdict='Lean Arsenal pre-match.',
            evidence_snapshot={
                'source': 'The Odds API',
                'api_key': 'should-not-be-stored',
                'edge': 0.08,
            },
            generated_text='Lean Arsenal pre-match.',
        )

        record = repository.list_audit_records('owner')[0]
        assert record.audit_id == audit_id
        assert 'api_key' not in record.evidence_snapshot
    finally:
        session.close()


def test_client_state_repository_entitlement_owner_fallback_and_expiration() -> None:
    repository, session = _repository()
    try:
        owner = repository.get_entitlement('owner')
        repository.upsert_entitlement(
            user_id='expired-user',
            plan=SubscriptionPlan.EXPIRED,
            status=SubscriptionStatus.EXPIRED,
            premium_match_detail_enabled=False,
            alerts_enabled=False,
            history_enabled=False,
        )
        expired = repository.get_entitlement('expired-user')

        assert owner.plan == SubscriptionPlan.OWNER
        assert owner.is_active is True
        assert expired.plan == SubscriptionPlan.EXPIRED
        assert expired.is_active is False
    finally:
        session.close()


def test_client_state_repository_watchlist_duplicate_updates_preferences() -> None:
    repository, session = _repository()
    try:
        first_id = repository.upsert_watchlist_item(
            user_id='owner',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['odds'],
        )
        second_id = repository.upsert_watchlist_item(
            user_id='owner',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['odds', 'injury', 'value_edge'],
        )

        assert second_id == first_id
        assert repository.list_watchlist('owner')[0].alert_preferences == [
            'odds',
            'injury',
            'value_edge',
        ]
    finally:
        session.close()
