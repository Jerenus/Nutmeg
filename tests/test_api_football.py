from __future__ import annotations

import httpx

from nutmeg.data.api_football import ApiFootballClient


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


def test_fetch_fixture_odds_normalizes_total_goals_correct_score_and_handicap() -> None:
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
                                        'id': 38,
                                        'name': 'Exact Goals Number',
                                        'values': [
                                            {'value': '0', 'odd': '11.0'},
                                            {'value': '1', 'odd': '5.5'},
                                            {'value': '2', 'odd': '3.8'},
                                            {'value': '3', 'odd': '4.0'},
                                            {'value': '4', 'odd': '6.5'},
                                            {'value': '5', 'odd': '12.0'},
                                            {'value': '6', 'odd': '26.0'},
                                            {'value': '7+', 'odd': '34.0'},
                                        ],
                                    },
                                    {
                                        'id': 92,
                                        'name': 'Exact Score',
                                        'values': [
                                            {'value': '1:0', 'odd': '7.5'},
                                            {'value': '0:1', 'odd': '10.0'},
                                            {'value': '2:1', 'odd': '9.0'},
                                        ],
                                    },
                                    {
                                        'id': 9,
                                        'name': 'Handicap Result',
                                        'values': [
                                            {'value': 'Home -1', 'odd': '2.50'},
                                            {'value': 'Draw -1', 'odd': '3.60'},
                                            {'value': 'Away -1', 'odd': '2.70'},
                                            {'value': 'Home +1', 'odd': '1.30'},
                                            {'value': 'Draw +1', 'odd': '5.50'},
                                            {'value': 'Away +1', 'odd': '9.00'},
                                        ],
                                    },
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

    total_goals = snapshot.markets['total_goals']
    assert total_goals.status == 'available'
    assert [outcome.outcome_key for outcome in total_goals.outcomes] == [
        'total_0',
        'total_1',
        'total_2',
        'total_3',
        'total_4',
        'total_5',
        'total_6',
        'total_7_plus',
    ]

    correct_score = snapshot.markets['correct_score']
    assert correct_score.status == 'available'
    assert {outcome.outcome_key for outcome in correct_score.outcomes} == {
        'score_1_0',
        'score_0_1',
        'score_2_1',
    }

    handicap = snapshot.markets['handicap_home_minus_1']
    assert handicap.line == '-1'
    assert [outcome.outcome_key for outcome in handicap.outcomes] == [
        'home',
        'draw',
        'away',
    ]
    handicap_plus = snapshot.markets['handicap_home_plus_1']
    assert handicap_plus.line == '+1'
    assert [outcome.outcome_key for outcome in handicap_plus.outcomes] == [
        'home',
        'draw',
        'away',
    ]


