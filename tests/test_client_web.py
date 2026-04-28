from __future__ import annotations

from fastapi.testclient import TestClient

from nutmeg.interfaces.client_web import create_client_app


class FakeClientService:
    def status(self, user_id: str | None = None):
        return {
            'user_id': user_id or 'owner',
            'health': {'health': 'healthy', 'blocking_reasons': []},
            'providers': {},
            'entitlements': {'plan': 'owner'},
            'responsible_use': '分析仅供参考，不构成投注建议。',
        }


def test_client_web_status_route_returns_json_payload() -> None:
    client = TestClient(create_client_app(service=FakeClientService()))

    response = client.get('/client/api/status?user_id=owner')

    assert response.status_code == 200
    assert response.json()['user_id'] == 'owner'
    assert response.json()['health']['health'] == 'healthy'


def test_client_web_manifest_route_returns_pwa_manifest() -> None:
    client = TestClient(create_client_app(service=FakeClientService()))

    response = client.get('/client/manifest.webmanifest')

    assert response.status_code == 200
    assert response.json()['short_name'] == 'Nutmeg'
    assert response.json()['display'] == 'standalone'


class FakeFeedService(FakeClientService):
    def daily_feed(self, *, user_id=None, league='epl', days=3, limit=5, demo=False):
        return {
            'user_id': user_id or 'owner',
            'league': league,
            'days': days,
            'generated_at': '2026-04-26T00:00:00+00:00',
            'opportunities': [
                {
                    'fixture_id': 'epl-001',
                    'league': 'epl',
                    'home_team': 'Arsenal',
                    'away_team': 'Tottenham Hotspur',
                    'kickoff_at': '2026-04-26T18:00:00+00:00',
                    'status': 'scheduled',
                    'rank': 1,
                    'score': 110,
                    'actionability': 'value',
                    'confidence': 'medium',
                    'edge_status': 'positive_edge',
                    'reasons': ['positive model-vs-market edge'],
                    'freshness': {'health': 'healthy', 'blocking_reasons': []},
                    'suggested_action': 'inspect_match',
                }
            ],
            'health': {'health': 'healthy', 'blocking_reasons': []},
            'responsible_use': '分析仅供参考，不构成投注建议。',
        }


def test_client_web_feed_api_returns_contract_payload() -> None:
    client = TestClient(create_client_app(service=FakeFeedService()))

    response = client.get('/client/api/feed?league=epl&days=3&demo=true')

    assert response.status_code == 200
    payload = response.json()
    assert payload['league'] == 'epl'
    assert payload['opportunities'][0]['fixture_id'] == 'epl-001'
    assert payload['opportunities'][0]['freshness']['health'] == 'healthy'
    assert '不构成投注建议' in payload['responsible_use']


def test_client_web_feed_page_renders_chinese_responsive_cards() -> None:
    client = TestClient(create_client_app(service=FakeFeedService()))

    response = client.get('/client?league=epl&days=3&demo=true')

    assert response.status_code == 200
    assert 'Nutmeg 今日机会' in response.text
    assert 'Arsenal vs Tottenham Hotspur' in response.text
    assert 'data-actionability="value"' in response.text
    assert 'viewport' in response.text


def test_client_web_feed_page_renders_watchlist_controls() -> None:
    client = TestClient(create_client_app(service=FakeFeedService()))

    response = client.get('/client?league=epl&days=3&demo=true')

    assert response.status_code == 200
    assert 'data-watchlist-form' in response.text
    assert 'action="/client/api/watchlist"' in response.text
    assert 'name="target_id" value="epl-001"' in response.text
    assert '保存观察' in response.text
    assert '按比赛和变更类型分组' in response.text


class FakeAlertPageService(FakeFeedService):
    def alerts(self, *, user_id):
        return {
            'alerts': [
                {
                    'alert_id': 'alert-1',
                    'fixture_id': 'epl-001',
                    'change_type': 'odds',
                    'group_key': 'epl-001:odds',
                    'after_summary': 'Home price shortened.',
                    'severity': 'important',
                }
            ]
        }


def test_client_web_feed_page_renders_grouped_alert_snippets() -> None:
    client = TestClient(create_client_app(service=FakeAlertPageService()))

    response = client.get('/client?league=epl&days=3&demo=true')

    assert response.status_code == 200
    assert '重要变化提醒' in response.text
    assert 'Home price shortened.' in response.text
    assert 'epl-001:odds' in response.text


class FakeWorkspaceService(FakeFeedService):
    def match_workspace(self, *, user_id=None, fixture_id):
        return {
            'fixture_id': fixture_id,
            'actionability': 'value',
            'judgment': {
                'verdict': 'Lean Arsenal pre-match.',
                'confidence': 'high',
                'counterargument': 'Derby volatility raises risk.',
            },
            'value': {'edge': 0.08},
            'market': {'summary': 'Home price shortened.'},
            'tactics': {'summary': 'Arsenal press can pin Spurs back.'},
            'players': {'summary': 'Tottenham fullback availability is uncertain.'},
            'information': {
                'summary': 'No confirmed lineup leak yet.',
                'items': [
                    {
                        'title': 'Rumor of winger fitness test',
                        'source_name': 'Supporter Wire',
                        'reliability': 'rumor',
                    }
                ],
                'warnings': ['Rumor/unverified information is not confirmed.'],
            },
            'evidence': [
                {
                    'kind': 'brief',
                    'source_name': 'Nutmeg match brief',
                    'summary': 'Lean Arsenal pre-match.',
                    'staleness': 'fresh',
                }
            ],
            'freshness': {'health': 'healthy', 'blocking_reasons': []},
            'caveats': ['Wait for confirmed lineups.'],
            'audit_id': 'audit-1',
            'responsible_use': '分析仅供参考，不构成投注建议。',
        }


def test_client_web_match_api_returns_contract_payload() -> None:
    client = TestClient(create_client_app(service=FakeWorkspaceService()))

    response = client.get('/client/api/matches/epl-001')

    assert response.status_code == 200
    payload = response.json()
    assert payload['fixture_id'] == 'epl-001'
    assert payload['judgment']['verdict'] == 'Lean Arsenal pre-match.'
    assert payload['audit_id'] == 'audit-1'


def test_client_web_match_page_renders_workspace_sections() -> None:
    client = TestClient(create_client_app(service=FakeWorkspaceService()))

    response = client.get('/client/matches/epl-001')

    assert response.status_code == 200
    assert '比赛分析工作台' in response.text
    assert 'Lean Arsenal pre-match.' in response.text
    assert 'Derby volatility raises risk.' in response.text
    assert 'Wait for confirmed lineups.' in response.text
    assert 'freshness=healthy' in response.text


def test_client_web_match_page_renders_information_items_and_reliability() -> None:
    client = TestClient(create_client_app(service=FakeWorkspaceService()))

    response = client.get('/client/matches/epl-001')

    assert response.status_code == 200
    assert 'Rumor of winger fitness test' in response.text
    assert 'Supporter Wire' in response.text
    assert 'rumor' in response.text
    assert 'Rumor/unverified information is not confirmed.' in response.text


def test_client_web_match_page_renders_prediction_controls() -> None:
    client = TestClient(create_client_app(service=FakeWorkspaceService()))

    response = client.get('/client/matches/epl-001')

    assert response.status_code == 200
    assert 'data-prediction-form' in response.text
    assert 'action="/client/api/predictions"' in response.text
    assert 'name="source_audit_id" value="audit-1"' in response.text
    assert '模拟记录，不是下注' in response.text


class FakeQuestionService(FakeWorkspaceService):
    def answer_question(self, *, user_id=None, fixture_id, question):
        return {
            'answer': 'Lean Arsenal pre-match. Evidence remains grounded.',
            'confidence': 'high',
            'evidence': [{'source_name': 'Nutmeg match brief'}],
            'refused': False,
            'refusal_reason': None,
        }


def test_client_web_match_question_endpoint_returns_grounded_answer() -> None:
    client = TestClient(create_client_app(service=FakeQuestionService()))

    response = client.post(
        '/client/api/matches/epl-001/questions',
        json={'user_id': 'owner', 'question': 'what changed?'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['refused'] is False
    assert 'Lean Arsenal pre-match.' in payload['answer']


def test_client_web_match_page_renders_question_form() -> None:
    client = TestClient(create_client_app(service=FakeQuestionService()))

    response = client.get('/client/matches/epl-001')

    assert response.status_code == 200
    assert '<form' in response.text
    assert 'name="question"' in response.text
    assert 'data-question-form' in response.text


class FakeGatedService(FakeWorkspaceService):
    def match_workspace(self, *, user_id=None, fixture_id):
        payload = super().match_workspace(user_id=user_id, fixture_id=fixture_id)
        payload['premium_restricted'] = True
        payload['entitlements'] = {'premium_match_detail_enabled': False, 'plan': 'basic'}
        payload['value'] = {'gated': True, 'message': '升级后查看高级价值分析'}
        return payload


def test_client_web_match_page_renders_gated_premium_message() -> None:
    client = TestClient(create_client_app(service=FakeGatedService()))

    response = client.get('/client/matches/epl-001?user_id=guest')

    assert response.status_code == 200
    assert '升级后查看高级价值分析' in response.text
    assert 'edge=0.08' not in response.text


class FakeStatefulService(FakeQuestionService):
    def save_watchlist_item(self, *, user_id, target_type, target_id, alert_preferences=None):
        return {
            'watchlist_id': 'watch-1',
            'user_id': user_id,
            'target_type': target_type,
            'target_id': target_id,
            'alert_preferences': alert_preferences or [],
        }

    def alerts(self, *, user_id):
        return {
            'alerts': [
                {
                    'alert_id': 'alert-1',
                    'user_id': user_id,
                    'fixture_id': 'epl-001',
                    'change_type': 'odds',
                    'after_summary': 'Home price shortened.',
                    'severity': 'important',
                }
            ]
        }

    def record_prediction(
        self,
        *,
        user_id,
        fixture_id,
        pick,
        source_audit_id=None,
        client_notes=None,
    ):
        return {
            'prediction_id': 42,
            'fixture_id': fixture_id,
            'pick': pick,
            'source_audit_id': source_audit_id,
            'status': 'recorded',
        }


def test_client_web_watchlist_alerts_and_prediction_contracts() -> None:
    client = TestClient(create_client_app(service=FakeStatefulService()))

    watch = client.post(
        '/client/api/watchlist',
        json={
            'user_id': 'owner',
            'target_type': 'fixture',
            'target_id': 'epl-001',
            'alert_preferences': ['odds'],
        },
    )
    alerts = client.get('/client/api/alerts?user_id=owner')
    prediction = client.post(
        '/client/api/predictions',
        json={
            'user_id': 'owner',
            'fixture_id': 'epl-001',
            'pick': 'home',
            'source_audit_id': 'audit-1',
        },
    )

    assert watch.status_code == 200
    assert watch.json()['watchlist_id'] == 'watch-1'
    assert alerts.status_code == 200
    assert alerts.json()['alerts'][0]['change_type'] == 'odds'
    assert prediction.status_code == 200
    assert prediction.json()['prediction_id'] == 42
