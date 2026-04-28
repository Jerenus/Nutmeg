from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nutmeg.domain.client import SubscriptionPlan, SubscriptionStatus
from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.value import ValueBoard, ValueCandidate
from nutmeg.services.client import ClientService
from nutmeg.services.popularity import MatchPopularityRanker
from nutmeg.storage.client_state_repository import SqlAlchemyClientStateRepository


def _service(
    default_user_id: str = 'owner',
) -> tuple[ClientService, SqlAlchemyClientStateRepository, Session]:
    engine = create_engine('sqlite:///:memory:', future=True)
    session = Session(engine)
    repository = SqlAlchemyClientStateRepository(session)
    return (
        ClientService(state_repository=repository, default_user_id=default_user_id),
        repository,
        session,
    )


def test_client_service_status_uses_owner_default_identity_and_entitlement() -> None:
    service, _repository, session = _service(default_user_id='owner')
    try:
        payload = service.status()
    finally:
        session.close()

    assert payload['user_id'] == 'owner'
    assert payload['entitlements']['plan'] == 'owner'
    assert payload['entitlements']['premium_match_detail_enabled'] is True
    assert payload['health']['health'] in {'healthy', 'partial', 'stale', 'failing'}
    assert '不构成投注建议' in payload['responsible_use']


def test_client_service_status_reads_non_owner_entitlement() -> None:
    service, repository, session = _service(default_user_id='owner')
    try:
        repository.upsert_entitlement(
            user_id='guest',
            plan=SubscriptionPlan.BASIC,
            status=SubscriptionStatus.ACTIVE,
            premium_match_detail_enabled=False,
            alerts_enabled=False,
            history_enabled=False,
        )
        payload = service.status(user_id='guest')
    finally:
        session.close()

    assert payload['user_id'] == 'guest'
    assert payload['entitlements']['plan'] == 'basic'
    assert payload['entitlements']['premium_match_detail_enabled'] is False


def _fixture(
    fixture_id: str,
    *,
    home_team: str = 'Arsenal',
    away_team: str = 'Tottenham Hotspur',
    kickoff_at: datetime | None = None,
    status: FixtureStatus = FixtureStatus.SCHEDULED,
) -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        league_code='epl',
        provider_league_id=39,
        season=2025,
        kickoff_at=kickoff_at or datetime(2026, 4, 26, 18, tzinfo=UTC),
        home_team_id=None,
        away_team_id=None,
        home_team=home_team,
        away_team=away_team,
        status=status,
        venue='Emirates Stadium',
    )


class FakeFixtureService:
    def __init__(self, fixtures: list[Fixture]) -> None:
        self.fixtures = fixtures
        self.calls: list[tuple[str, int, bool]] = []

    def list_upcoming(self, league: str, days: int, demo: bool = False):
        self.calls.append((league, days, demo))
        return self.fixtures


class FakeValueBoardService:
    def __init__(self, board: ValueBoard | None = None) -> None:
        self.board = board or ValueBoard(
            league='epl',
            days=3,
            generated_at=datetime(2026, 4, 26, tzinfo=UTC),
            candidates=[],
            skipped=[],
        )

    def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
        return self.board


def _value_candidate(fixture_id: str = 'epl-001') -> ValueCandidate:
    return ValueCandidate(
        fixture_id=fixture_id,
        kickoff_at=datetime(2026, 4, 26, 18, tzinfo=UTC),
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        outcome_key='home',
        outcome_name='Arsenal',
        model_probability=0.58,
        market_probability=0.50,
        edge=0.08,
        best_odds=2.10,
        expected_value=0.218,
        quarter_kelly_fraction=0.03,
        rating='strong',
        model_name='dixon-coles-lite-poisson',
        source_notes=['positive model-vs-market edge'],
    )


def _client_service_with_feed(
    fixtures: list[Fixture],
    board: ValueBoard | None = None,
) -> tuple[ClientService, Session]:
    engine = create_engine('sqlite:///:memory:', future=True)
    session = Session(engine)
    repository = SqlAlchemyClientStateRepository(session)
    return (
        ClientService(
            state_repository=repository,
            default_user_id='owner',
            fixture_service=FakeFixtureService(fixtures),
            popularity_ranker=MatchPopularityRanker(),
            value_board_service=FakeValueBoardService(board),
        ),
        session,
    )


def test_client_service_daily_feed_ranks_top_opportunities_with_value_context() -> None:
    fixtures = [
        _fixture('epl-001', home_team='Arsenal', away_team='Tottenham Hotspur'),
        _fixture('epl-002', home_team='Manchester City', away_team='Liverpool'),
        _fixture('epl-003', home_team='Brentford', away_team='Fulham'),
    ]
    board = ValueBoard(
        league='epl',
        days=3,
        generated_at=datetime(2026, 4, 26, tzinfo=UTC),
        candidates=[_value_candidate('epl-001')],
        skipped=[],
    )
    service, session = _client_service_with_feed(fixtures, board)
    try:
        payload = service.daily_feed(league='epl', days=3, limit=3, demo=True)
    finally:
        session.close()

    assert payload['user_id'] == 'owner'
    assert payload['league'] == 'epl'
    assert len(payload['opportunities']) == 3
    opportunity = next(
        item for item in payload['opportunities'] if item['fixture_id'] == 'epl-001'
    )
    assert opportunity['actionability'] == 'value'
    assert opportunity['edge_status'] == 'positive_edge'
    assert opportunity['value']['edge'] == 0.08
    assert opportunity['freshness']['health'] == 'healthy'
    assert '不构成投注建议' in payload['responsible_use']


def test_client_service_daily_feed_marks_missing_inputs_without_false_value_call() -> None:
    service, session = _client_service_with_feed([_fixture('epl-001')])
    try:
        payload = service.daily_feed(league='epl', days=3, limit=1, demo=True)
    finally:
        session.close()

    opportunity = payload['opportunities'][0]
    assert opportunity['actionability'] == 'watch'
    assert opportunity['edge_status'] == 'unavailable'
    assert opportunity['freshness']['health'] == 'partial'
    assert 'odds/value evidence unavailable' in opportunity['freshness']['blocking_reasons']


def test_client_service_daily_feed_highlights_live_or_near_kickoff_risk() -> None:
    fixture = _fixture(
        'epl-live',
        kickoff_at=datetime.now(UTC) - timedelta(minutes=15),
        status=FixtureStatus.LIVE,
    )
    board = ValueBoard(
        league='epl',
        days=3,
        generated_at=datetime(2026, 4, 26, tzinfo=UTC),
        candidates=[_value_candidate('epl-live')],
        skipped=[],
    )
    service, session = _client_service_with_feed([fixture], board)
    try:
        payload = service.daily_feed(league='epl', days=3, limit=1, demo=True)
    finally:
        session.close()

    opportunity = payload['opportunities'][0]
    assert opportunity['actionability'] == 'watch'
    assert opportunity['suggested_action'] == 'wait_for_late_data'
    assert 'live or near kickoff risk' in opportunity['freshness']['blocking_reasons']


class FakeBriefProvider:
    def __init__(self, *, conflict_state: str = 'aligned') -> None:
        self.conflict_state = conflict_state

    def build_brief(self, fixture_id: str):
        return {
            'fixture_id': fixture_id,
            'fixture': {
                'fixture_id': fixture_id,
                'league_code': 'epl',
                'home_team': 'Arsenal',
                'away_team': 'Tottenham Hotspur',
                'kickoff_at': '2026-04-26T18:00:00+00:00',
                'status': 'scheduled',
            },
            'judgment': {
                'verdict': 'Lean Arsenal pre-match.',
                'confidence': 'high',
                'core_reasons': ['Arsenal chance quality is stronger.'],
                'counterargument': 'Derby volatility raises risk.',
            },
            'sections': {
                'caveats': ['Wait for confirmed lineups.'],
                'tactical_evidence': ['Arsenal press can pin Spurs back.'],
                'market_evidence': ['Home price shortened.'],
            },
            'conflict_state': self.conflict_state,
            'generated_at': '2026-04-26T00:00:00+00:00',
        }


class FakeOddsProvider:
    def build_market(self, fixture_id: str):
        return {
            'fixture_id': fixture_id,
            'source_name': 'The Odds API',
            'retrieved_at': '2026-04-26T00:01:00+00:00',
            'summary': 'Home price shortened from 2.10 to 1.91.',
        }


class FakeTacticalProvider:
    def build_tactics(self, fixture_id: str):
        return {
            'fixture_id': fixture_id,
            'source_name': 'Nutmeg tactical visuals',
            'retrieved_at': '2026-04-26T00:02:00+00:00',
            'summary': 'Lineup-network proxy favors Arsenal width.',
        }


class FakePlayerProvider:
    def build_players(self, fixture_id: str):
        return {
            'fixture_id': fixture_id,
            'source_name': 'Nutmeg player profile',
            'retrieved_at': '2026-04-26T00:03:00+00:00',
            'summary': 'Tottenham fullback availability is uncertain.',
        }


class FakeInformationProvider:
    def build_information(self, fixture_id: str):
        return {
            'fixture_id': fixture_id,
            'source_name': 'verified team news feed',
            'retrieved_at': '2026-04-26T00:04:00+00:00',
            'summary': 'No confirmed lineup leak yet.',
        }


def _client_service_with_workspace(
    *,
    conflict_state: str = 'aligned',
) -> tuple[ClientService, Session]:
    board = ValueBoard(
        league='epl',
        days=3,
        generated_at=datetime(2026, 4, 26, tzinfo=UTC),
        candidates=[_value_candidate('epl-001')],
        skipped=[],
    )
    engine = create_engine('sqlite:///:memory:', future=True)
    session = Session(engine)
    repository = SqlAlchemyClientStateRepository(session)
    return (
        ClientService(
            state_repository=repository,
            default_user_id='owner',
            value_board_service=FakeValueBoardService(board),
            match_brief_provider=FakeBriefProvider(conflict_state=conflict_state),
            odds_provider=FakeOddsProvider(),
            tactical_provider=FakeTacticalProvider(),
            player_provider=FakePlayerProvider(),
            information_provider=FakeInformationProvider(),
        ),
        session,
    )


def test_client_service_match_workspace_combines_analysis_sections_and_audit() -> None:
    service, session = _client_service_with_workspace()
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert workspace['fixture_id'] == 'epl-001'
    assert workspace['actionability'] == 'value'
    assert workspace['judgment']['verdict'] == 'Lean Arsenal pre-match.'
    assert workspace['value']['edge'] == 0.08
    assert workspace['market']['summary'] == 'Home price shortened from 2.10 to 1.91.'
    assert workspace['tactics']['summary'] == 'Lineup-network proxy favors Arsenal width.'
    assert workspace['players']['summary'] == 'Tottenham fullback availability is uncertain.'
    assert workspace['information']['summary'] == 'No confirmed lineup leak yet.'
    assert workspace['audit_id']
    assert '不构成投注建议' in workspace['responsible_use']


def test_client_service_match_workspace_conflict_lowers_actionability() -> None:
    service, session = _client_service_with_workspace(conflict_state='market_vs_tactics')
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert workspace['actionability'] == 'watch'
    assert 'market/tactical conflict' in workspace['caveats']


def test_client_service_match_workspace_evidence_has_source_and_timestamps() -> None:
    service, session = _client_service_with_workspace()
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert {item['source_name'] for item in workspace['evidence']} >= {
        'Nutmeg match brief',
        'Nutmeg value board',
        'The Odds API',
        'Nutmeg tactical visuals',
        'Nutmeg player profile',
        'verified team news feed',
    }
    assert all('retrieved_at' in item for item in workspace['evidence'])


class FakeAnswerGenerator:
    def answer(self, *, question: str, workspace: dict[str, object]) -> str:
        return 'Guaranteed profit: bet Arsenal now.'


def test_client_service_grounded_follow_up_uses_workspace_evidence() -> None:
    service, session = _client_service_with_workspace()
    try:
        answer = service.answer_question(
            fixture_id='epl-001',
            question='is the Asian handicap still playable?',
        )
    finally:
        session.close()

    assert answer['refused'] is False
    assert 'Lean Arsenal pre-match.' in answer['answer']
    assert answer['confidence'] == 'high'
    assert answer['evidence']
    assert any(item['source_name'] == 'Nutmeg match brief' for item in answer['evidence'])


def test_client_service_follow_up_refuses_out_of_scope_or_unsupported_requests() -> None:
    service, session = _client_service_with_workspace()
    try:
        answer = service.answer_question(
            fixture_id='epl-001',
            question='place this bet for me and guarantee profit',
        )
    finally:
        session.close()

    assert answer['refused'] is True
    assert answer['refusal_reason'] == 'out_of_scope_betting_execution'
    assert '不能替你下注' in answer['answer']


def test_client_service_follow_up_deterministic_verdict_overrides_generated_wording() -> None:
    service, session = _client_service_with_workspace()
    service._answer_generator = FakeAnswerGenerator()
    try:
        answer = service.answer_question(
            fixture_id='epl-001',
            question='what changed since this morning?',
        )
    finally:
        session.close()

    assert answer['refused'] is False
    assert 'Guaranteed profit' not in answer['answer']
    assert 'Lean Arsenal pre-match.' in answer['answer']


def test_client_service_gates_premium_workspace_without_leaking_value_facts() -> None:
    service, session = _client_service_with_workspace()
    try:
        service._state_repository.upsert_entitlement(
            user_id='guest',
            plan=SubscriptionPlan.BASIC,
            status=SubscriptionStatus.ACTIVE,
            premium_match_detail_enabled=False,
            alerts_enabled=False,
            history_enabled=False,
        )
        workspace = service.match_workspace(fixture_id='epl-001', user_id='guest')
    finally:
        session.close()

    assert workspace['entitlements']['premium_match_detail_enabled'] is False
    assert workspace['premium_restricted'] is True
    assert workspace['value']['gated'] is True
    assert 'edge' not in workspace['value']
    assert workspace['market']['gated'] is True


def test_client_service_user_state_isolation_for_status_watchlist_alerts_and_audits() -> None:
    service, session = _client_service_with_workspace()
    repository = service._state_repository
    try:
        repository.upsert_watchlist_item(
            user_id='owner',
            target_type='fixture',
            target_id='epl-001',
            alert_preferences=['odds'],
        )
        repository.upsert_watchlist_item(
            user_id='guest',
            target_type='fixture',
            target_id='epl-002',
            alert_preferences=['injury'],
        )
        repository.create_alert(
            user_id='owner',
            fixture_id='epl-001',
            change_type='odds',
            after_summary='Owner odds alert',
            severity='important',
            group_key='owner-alert',
        )
        workspace = service.match_workspace(fixture_id='epl-001', user_id='owner')

        assert [item.target_id for item in repository.list_watchlist('owner')] == ['epl-001']
        assert [item.target_id for item in repository.list_watchlist('guest')] == ['epl-002']
        assert repository.list_alerts('guest') == []
        assert repository.list_audit_records('guest') == []
        assert workspace['audit_id'] in [r.audit_id for r in repository.list_audit_records('owner')]
    finally:
        session.close()


class FakePredictionRepository:
    def __init__(self) -> None:
        self.calls = []

    def record_prediction(self, **kwargs):
        self.calls.append(kwargs)
        return 42

    def review(self, *, user_id: str):
        return {'total_predictions': 1, 'average_brier_score': None}


def test_client_service_creates_material_change_alerts_for_supported_change_types() -> None:
    service, session = _client_service_with_workspace()
    try:
        created = [
            service.create_material_alert(
                user_id='owner',
                fixture_id='epl-001',
                change_type=change_type,
                before_summary='before',
                after_summary='after',
                actionability_before='watch',
                actionability_after='value',
            )
            for change_type in [
                'odds',
                'lineup',
                'injury',
                'fixture_status',
                'information',
                'value_edge',
            ]
        ]
    finally:
        session.close()

    assert len(created) == 6
    assert {item['change_type'] for item in created} == {
        'odds',
        'lineup',
        'injury',
        'fixture_status',
        'information',
        'value_edge',
    }
    assert all('why_it_matters' in item for item in created)


def test_client_service_groups_repeated_alerts_by_group_key() -> None:
    service, session = _client_service_with_workspace()
    try:
        first = service.create_material_alert(
            user_id='owner',
            fixture_id='epl-001',
            change_type='odds',
            before_summary='before',
            after_summary='after one',
            actionability_before='watch',
            actionability_after='value',
        )
        second = service.create_material_alert(
            user_id='owner',
            fixture_id='epl-001',
            change_type='odds',
            before_summary='before',
            after_summary='after two',
            actionability_before='watch',
            actionability_after='value',
        )
        alerts = service.alerts(user_id='owner')
    finally:
        session.close()

    assert second['alert_id'] == first['alert_id']
    assert len(alerts['alerts']) == 1
    assert alerts['alerts'][0]['after_summary'] == 'after two'


def test_client_service_records_prediction_with_audit_context() -> None:
    prediction_repository = FakePredictionRepository()
    service, session = _client_service_with_workspace()
    service._prediction_repository = prediction_repository
    try:
        payload = service.record_prediction(
            user_id='owner',
            fixture_id='epl-001',
            pick='home',
            source_audit_id='audit-1',
            client_notes='client note',
        )
    finally:
        session.close()

    assert payload['prediction_id'] == 42
    assert payload['source_audit_id'] == 'audit-1'
    assert payload['calibration_review']['total_predictions'] == 1
    assert prediction_repository.calls[0]['user_id'] == 'owner'
    assert 'audit-1' in prediction_repository.calls[0]['notes']


def test_client_service_match_workspace_consumes_information_digest_payload() -> None:
    class ContextAwareInformationProvider:
        def __init__(self) -> None:
            self.calls = []

        def build_information(self, fixture_id: str, *, home_team=None, away_team=None):
            self.calls.append((fixture_id, home_team, away_team))
            return {
                'fixture_id': fixture_id,
                'source_name': 'Nutmeg information provider',
                'retrieved_at': '2026-04-26T09:05:00+00:00',
                'summary': '3 relevant updates from 2 sources. Latest: Winger fitness test.',
                'status': 'partial',
                'staleness': 'fresh',
                'items': [
                    {
                        'title': 'Winger fitness test',
                        'source_name': 'Supporter Wire',
                        'reliability': 'rumor',
                    }
                ],
                'warnings': ['Rumor/unverified information is not confirmed.'],
            }

    provider = ContextAwareInformationProvider()
    service, session = _client_service_with_workspace()
    service._information_provider = provider
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert provider.calls == [('epl-001', 'Arsenal', 'Tottenham Hotspur')]
    assert workspace['information']['status'] == 'partial'
    assert workspace['information']['items'][0]['reliability'] == 'rumor'
    assert workspace['actionability'] == 'value'


def test_client_service_match_workspace_reports_information_unavailable() -> None:
    service, session = _client_service_with_workspace()
    service._information_provider = None
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert workspace['information']['status'] == 'unavailable'
    assert workspace['information']['summary'] == 'Information unavailable.'
    assert workspace['information']['items'] == []
    assert 'information provider unavailable' in workspace['information']['warnings']


def test_client_service_can_override_information_provider_for_manifest_digest() -> None:
    class ManifestBackedInformationProvider:
        def build_information(self, fixture_id: str, *, home_team=None, away_team=None):
            return {
                'source_name': 'Live information provider',
                'summary': 'Manifest-backed Arsenal update.',
                'status': 'complete',
                'staleness': 'fresh',
                'items': [{'title': 'Manifest-backed Arsenal update', 'reliability': 'official'}],
                'warnings': [],
            }

    service, session = _client_service_with_workspace()
    service.set_information_provider(ManifestBackedInformationProvider())
    try:
        workspace = service.match_workspace(fixture_id='epl-001')
    finally:
        session.close()

    assert workspace['information']['source_name'] == 'Live information provider'
    assert workspace['information']['items'][0]['reliability'] == 'official'
