from __future__ import annotations

from datetime import date

import httpx
import pytest

from nutmeg.data.api_football import ApiFootballClient, ApiFootballError
from nutmeg.domain.snapshot import (
    AvailabilityRecord,
    HeadToHeadSummary,
    InjuryStatus,
    LineupPlayer,
    TeamLineup,
    TeamSplitSummary,
)


def _fixture_payload(fixture_id: int, page: int, total: int) -> dict[str, object]:
    return {
        'errors': [],
        'paging': {'current': page, 'total': total},
        'response': [
            {
                'fixture': {
                    'id': fixture_id,
                    'date': '2026-04-26T15:00:00+00:00',
                    'venue': {'name': 'Test Ground'},
                    'referee': 'Michael Oliver',
                    'status': {'short': 'NS', 'long': 'Not Started'},
                },
                'league': {'id': 39, 'season': 2025, 'round': 'Regular Season - 34'},
                'teams': {
                    'home': {'id': 42, 'name': 'Arsenal'},
                    'away': {'id': 49, 'name': 'Chelsea'},
                },
                'goals': {'home': None, 'away': None},
            }
        ],
    }


def test_fetch_upcoming_fixtures_uses_single_request_without_page_param() -> None:
    seen_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=_fixture_payload(1001, page=1, total=1),
            headers={
                'x-ratelimit-requests-remaining': '7420',
                'x-ratelimit-remaining': '55',
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    batch = api_client.fetch_upcoming_fixtures(
        league_code='epl',
        league_id=39,
        season=2025,
        date_from=date(2026, 4, 24),
        date_to=date(2026, 5, 1),
    )

    assert seen_params == [
        {
            'league': '39',
            'season': '2025',
            'from': '2026-04-24',
            'to': '2026-05-01',
            'timezone': 'UTC',
        }
    ]
    assert len(batch.fixtures) == 1
    assert batch.requests_made == 1
    assert batch.fixtures[0].league_code == 'epl'
    assert batch.fixtures[0].home_team_id == 42
    assert batch.fixtures[0].away_team_id == 49
    assert batch.fixtures[0].referee == 'Michael Oliver'
    assert batch.quota.requests_remaining == 7420


def test_fetch_upcoming_fixtures_raises_on_api_errors() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': {'league': 'invalid'},
                'paging': {'current': 1, 'total': 1},
                'response': [],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    with pytest.raises(ApiFootballError, match='invalid'):
        api_client.fetch_upcoming_fixtures(
            league_code='epl',
            league_id=39,
            season=2025,
            date_from=date(2026, 4, 24),
            date_to=date(2026, 5, 1),
        )


def test_fetch_upcoming_fixtures_raises_on_429() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={}))
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    with pytest.raises(ApiFootballError, match='rate limit exceeded'):
        api_client.fetch_upcoming_fixtures(
            league_code='epl',
            league_id=39,
            season=2025,
            date_from=date(2026, 4, 24),
            date_to=date(2026, 5, 1),
        )


def test_fetch_fixture_injuries_deduplicates_provider_duplicates() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'team': {'id': 42, 'name': 'Arsenal'},
                        'player': {
                            'id': 7,
                            'name': 'Bukayo Saka',
                            'type': 'Injured',
                            'reason': 'Hamstring',
                            'expected_return': '2026-05-01',
                        },
                    },
                    {
                        'team': {'id': 42, 'name': 'Arsenal'},
                        'player': {
                            'id': 7,
                            'name': 'Bukayo Saka',
                            'type': 'Injured',
                            'reason': 'Hamstring',
                            'expected_return': '2026-05-01',
                        },
                    },
                    {
                        'team': {'id': 42, 'name': 'Arsenal'},
                        'player': {
                            'id': 29,
                            'name': 'Kai Havertz',
                            'type': 'Injured',
                            'reason': 'Hamstring',
                            'expected_return': '2026-05-06',
                        },
                    },
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    injuries = api_client.fetch_fixture_injuries(fixture_id='1234')

    assert injuries == {
        42: [
            InjuryStatus(
                player_name='Bukayo Saka',
                status='Injured',
                reason='Hamstring',
                expected_return='2026-05-01',
                source='api-football',
            ),
            InjuryStatus(
                player_name='Kai Havertz',
                status='Injured',
                reason='Hamstring',
                expected_return='2026-05-06',
                source='api-football',
            ),
        ]
    }


def test_fetch_fixture_injuries_normalizes_team_scoped_records() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'team': {'id': 42, 'name': 'Arsenal'},
                        'player': {
                            'id': 7,
                            'name': 'Bukayo Saka',
                            'type': 'Injured',
                            'reason': 'Hamstring',
                        },
                        'fixture': {'id': 1234},
                        'league': {'id': 39, 'season': 2025},
                    }
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    injuries = api_client.fetch_fixture_injuries(fixture_id='1234')

    assert injuries == {
        42: [
            InjuryStatus(
                player_name='Bukayo Saka',
                status='Injured',
                reason='Hamstring',
                expected_return=None,
                source='api-football',
            )
        ]
    }


def test_fetch_fixture_lineups_normalizes_confirmed_lineups() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'team': {'id': 42, 'name': 'Arsenal'},
                        'formation': '4-3-3',
                        'startXI': [
                            {
                                'player': {
                                    'id': 7,
                                    'name': 'Bukayo Saka',
                                    'number': 7,
                                    'pos': 'F',
                                    'grid': '3:1',
                                }
                            }
                        ],
                        'substitutes': [],
                    }
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    lineups = api_client.fetch_fixture_lineups(fixture_id='1234')

    assert lineups == {
        42: TeamLineup(
            status='confirmed',
            source='api-football',
            formation='4-3-3',
            players=[
                LineupPlayer(
                    player_name='Bukayo Saka',
                    position='F',
                    shirt_number='7',
                    role='starter',
                    captain=False,
                )
            ],
        )
    }


def test_fetch_fixture_odds_normalizes_supported_markets_and_deduplicates_quotes() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'league': {'id': 39, 'season': 2025},
                        'fixture': {
                            'id': 1234,
                            'date': '2026-04-25T14:00:00+00:00',
                            'timezone': 'UTC',
                        },
                        'update': '2026-04-24T06:16:30+00:00',
                        'bookmakers': [
                            {
                                'id': 1,
                                'name': '10Bet',
                                'bets': [
                                    {
                                        'id': 1,
                                        'name': 'Match Winner',
                                        'values': [
                                            {'value': 'Home', 'odd': '1.45'},
                                            {'value': 'Home', 'odd': '1.45'},
                                            {'value': 'Draw', 'odd': '4.55'},
                                            {'value': 'Away', 'odd': '6.25'},
                                        ],
                                    },
                                    {
                                        'id': 5,
                                        'name': 'Goals Over/Under',
                                        'values': [
                                            {'value': 'Over 2.5', 'odd': '1.57'},
                                            {'value': 'Under 2.5', 'odd': '2.35'},
                                            {'value': 'Over 1.5', 'odd': '1.18'},
                                        ],
                                    },
                                    {
                                        'id': 8,
                                        'name': 'Both Teams Score',
                                        'values': [
                                            {'value': 'Yes', 'odd': '1.70'},
                                            {'value': 'No', 'odd': '2.10'},
                                        ],
                                    },
                                    {
                                        'id': 13,
                                        'name': 'Asian Handicap',
                                        'values': [
                                            {'value': 'Home -0.5', 'odd': '1.92'},
                                            {'value': 'Away +0.5', 'odd': '1.94'},
                                            {'value': 'Home -2', 'odd': '2.70'},
                                            {'value': 'Away +2', 'odd': '1.48'},
                                            {'value': 'Home +0.25', 'odd': '1.55'},
                                            {'value': 'Away -0.25', 'odd': '2.55'},
                                        ],
                                    },
                                ],
                            },
                            {
                                'id': 6,
                                'name': '1xBet',
                                'bets': [
                                    {
                                        'id': 1,
                                        'name': 'Match Winner',
                                        'values': [
                                            {'value': 'Home', 'odd': '1.48'},
                                            {'value': 'Draw', 'odd': '4.40'},
                                            {'value': 'Away', 'odd': '6.10'},
                                        ],
                                    },
                                    {
                                        'id': 5,
                                        'name': 'Goals Over/Under',
                                        'values': [
                                            {'value': 'Over 2.5', 'odd': '1.61'},
                                            {'value': 'Under 2.5', 'odd': '2.30'},
                                        ],
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    snapshot = api_client.fetch_fixture_odds(fixture_id='1234')

    assert snapshot.provider == 'api-football'
    assert snapshot.bookmaker_count == 2
    assert str(snapshot.updated_at) == '2026-04-24 06:16:30+00:00'
    assert set(snapshot.markets) == {
        'match_winner',
        'btts',
        'totals_1_5',
        'totals_2_5',
        'asian_handicap_0_5',
        'asian_handicap_2_0',
        'asian_handicap_0_25',
    }

    match_winner = snapshot.markets['match_winner']
    assert match_winner.status == 'available'
    home = next(
        outcome for outcome in match_winner.outcomes if outcome.outcome_key == 'home'
    )
    assert home.bookmaker_count == 2
    assert [quote.bookmaker_name for quote in home.bookmaker_quotes] == ['10Bet', '1xBet']

    totals = snapshot.markets['totals_2_5']
    assert totals.line == '2.5'
    assert [outcome.outcome_key for outcome in totals.outcomes] == ['over', 'under']

    early_totals = snapshot.markets['totals_1_5']
    assert early_totals.line == '1.5'
    assert [outcome.outcome_key for outcome in early_totals.outcomes] == ['over']

    btts = snapshot.markets['btts']
    assert [outcome.outcome_key for outcome in btts.outcomes] == ['yes', 'no']

    asian = snapshot.markets['asian_handicap_0_5']
    assert asian.line == '0.5'
    assert [outcome.outcome_key for outcome in asian.outcomes] == ['home', 'away']

    strong_asian = snapshot.markets['asian_handicap_2_0']
    assert strong_asian.line == '2.0'
    assert [outcome.outcome_key for outcome in strong_asian.outcomes] == ['home', 'away']

    quarter_asian = snapshot.markets['asian_handicap_0_25']
    assert quarter_asian.line == '0.25'
    assert [outcome.outcome_key for outcome in quarter_asian.outcomes] == ['home', 'away']


def test_fetch_fixture_odds_accepts_supported_market_id_even_if_name_varies() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'update': '2026-04-24T06:16:30+00:00',
                        'bookmakers': [
                            {
                                'id': 1,
                                'name': '10Bet',
                                'bets': [
                                    {
                                        'id': 1,
                                        'name': '1X2 Result',
                                        'values': [
                                            {'value': 'Home', 'odd': '1.45'},
                                            {'value': 'Draw', 'odd': '4.55'},
                                            {'value': 'Away', 'odd': '6.25'},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    snapshot = api_client.fetch_fixture_odds(fixture_id='1234')

    assert 'match_winner' in snapshot.markets
    assert [outcome.outcome_key for outcome in snapshot.markets['match_winner'].outcomes] == [
        'home',
        'draw',
        'away',
    ]


def test_fetch_team_sidelined_aggregates_active_player_records_from_squad() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.url.path, dict(request.url.params)))
        if request.url.path == '/players/squads':
            return httpx.Response(
                200,
                json={
                    'errors': [],
                    'response': [
                        {
                            'team': {'id': 42, 'name': 'Arsenal'},
                            'players': [
                                {'id': 12, 'name': 'William Saliba'},
                                {'id': 14, 'name': 'Healthy Player'},
                            ],
                        }
                    ],
                },
            )
        assert request.url.path == '/sidelined'
        player_id = request.url.params['player']
        if player_id == '12':
            return httpx.Response(
                200,
                json={
                    'errors': [],
                    'response': [
                        {
                            'type': 'Suspended',
                            'reason': 'Accumulated cards',
                            'start': '2026-04-20',
                            'end': '2026-04-30',
                        },
                        {
                            'type': 'Thigh Injury',
                            'reason': 'Older injury',
                            'start': '2026-03-01',
                            'end': '2026-03-10',
                        },
                    ],
                },
            )
        return httpx.Response(200, json={'errors': [], 'response': []})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    records = api_client.fetch_team_sidelined(
        team_id=42,
        season=2025,
        as_of_date=date(2026, 4, 25),
    )

    assert records == [
        AvailabilityRecord(
            player_name='William Saliba',
            status='Suspended',
            reason='Accumulated cards',
            expected_return='2026-04-30',
            source='api-football',
        )
    ]
    assert seen_requests == [
        ('/players/squads', {'team': '42'}),
        ('/sidelined', {'player': '12'}),
        ('/sidelined', {'player': '14'}),
    ]


def test_fetch_team_statistics_normalizes_home_away_splits() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': {
                    'fixtures': {
                        'played': {'home': 10, 'away': 10},
                        'wins': {'home': 7, 'away': 4},
                        'draws': {'home': 1, 'away': 2},
                    },
                    'goals': {
                        'for': {
                            'total': {'home': 21, 'away': 15},
                        }
                    },
                },
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    summary = api_client.fetch_team_statistics(team_id=42, league_id=39, season=2025)

    assert summary == TeamSplitSummary(
        home_points_per_match=2.2,
        away_points_per_match=1.4,
        home_goals_for_per_match=2.1,
        away_goals_for_per_match=1.5,
        source='api-football',
    )


def test_fetch_head_to_head_normalizes_summary_from_home_team_perspective() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                'errors': [],
                'response': [
                    {
                        'teams': {
                            'home': {'id': 42, 'name': 'Arsenal'},
                            'away': {'id': 148, 'name': 'Tottenham Hotspur'},
                        },
                        'goals': {'home': 2, 'away': 1},
                    },
                    {
                        'teams': {
                            'home': {'id': 148, 'name': 'Tottenham Hotspur'},
                            'away': {'id': 42, 'name': 'Arsenal'},
                        },
                        'goals': {'home': 0, 'away': 0},
                    },
                    {
                        'teams': {
                            'home': {'id': 148, 'name': 'Tottenham Hotspur'},
                            'away': {'id': 42, 'name': 'Arsenal'},
                        },
                        'goals': {'home': 1, 'away': 3},
                    },
                ],
            },
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    api_client = ApiFootballClient(
        base_url='https://example.test',
        api_key='demo-key',
        client=client,
    )

    summary = api_client.fetch_head_to_head(home_team_id=42, away_team_id=148, last=5)

    assert summary == HeadToHeadSummary(
        matches=3,
        home_wins=2,
        draws=1,
        away_wins=0,
        source='api-football',
    )
