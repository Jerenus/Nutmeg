from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.odds import (
    BookmakerQuote,
    MarketOddsSnapshot,
    OddsProviderSnapshotFeed,
    OutcomeOddsSnapshot,
)
from nutmeg.domain.snapshot import (
    AvailabilityRecord,
    HeadToHeadSummary,
    InjuryStatus,
    LineupPlayer,
    TeamLineup,
    TeamSplitSummary,
)


class ApiFootballError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ApiQuota:
    requests_remaining: int | None = None
    minute_remaining: int | None = None


@dataclass(slots=True, frozen=True)
class FixtureBatch:
    fixtures: list[Fixture]
    requests_made: int
    quota: ApiQuota


def _parse_datetime(raw_value: str) -> datetime:
    return datetime.fromisoformat(raw_value.replace('Z', '+00:00')).astimezone(UTC)


def _parse_errors(payload: dict[str, Any]) -> str | None:
    errors = payload.get('errors')
    if errors in (None, [], {}):
        return None
    if isinstance(errors, dict):
        return '; '.join(f'{key}: {value}' for key, value in errors.items())
    if isinstance(errors, list):
        return '; '.join(str(item) for item in errors)
    return str(errors)


def _parse_quota(headers: httpx.Headers) -> ApiQuota:
    def _to_int(value: str | None) -> int | None:
        if value is None or value == '':
            return None
        try:
            return int(value)
        except ValueError:
            return None

    return ApiQuota(
        requests_remaining=_to_int(headers.get('x-ratelimit-requests-remaining')),
        minute_remaining=_to_int(headers.get('x-ratelimit-remaining')),
    )


def _normalized_player_key(value: Any) -> str:
    return str(value or 'unknown').strip().casefold()


SUPPORTED_HANDICAP_LINES: tuple[str, ...] = (
    '0.25',
    '0.5',
    '0.75',
    '1.0',
    '1.25',
    '1.5',
    '1.75',
    '2.0',
    '2.25',
    '2.5',
)

def _goal_handicap_suffix(line: int) -> str:
    if line == 0:
        return '0'
    return f"{'minus' if line < 0 else 'plus'}_{abs(line)}"


def total_goals_outcome_keys() -> tuple[str, ...]:
    """Exact total-goals bucket keys: total_0..total_6 plus a 7+ tail."""
    return tuple(
        f'total_{count}' for count in range(MAX_TOTAL_GOALS_BUCKET)
    ) + (f'total_{MAX_TOTAL_GOALS_BUCKET}_plus',)


def _correct_score_sort_key(outcome_key: str) -> tuple[int, int]:
    parts = outcome_key.removeprefix('score_').split('_')
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return (99, 99)


def _goal_handicap_line_label(line: int) -> str:
    if line == 0:
        return '0'
    return f'{line:+d}'


# Integer European handicap lines (applied to the home tally), shared with the
# Dixon-Coles pricing model. A negative line is a home deficit.
SUPPORTED_GOAL_HANDICAP_LINES: tuple[int, ...] = (-2, -1, 0, 1, 2)

# Total-goals exact buckets: 0..6 plus a 7+ residual tail.
MAX_TOTAL_GOALS_BUCKET: int = 7

SUPPORTED_ODDS_MARKETS: dict[str, tuple[int, str]] = {
    'match_winner': (1, 'Match Winner'),
    'totals_1_5': (5, 'Goals Over/Under'),
    'totals_2_5': (5, 'Goals Over/Under'),
    'totals_3_5': (5, 'Goals Over/Under'),
    'btts': (8, 'Both Teams Score'),
    'total_goals': (38, 'Exact Goals Number'),
    'correct_score': (92, 'Exact Score'),
    **{
        f"asian_handicap_{line.replace('.', '_')}": (13, 'Asian Handicap')
        for line in SUPPORTED_HANDICAP_LINES
    },
    **{
        f'handicap_home_{_goal_handicap_suffix(line)}': (9, 'Handicap Result')
        for line in SUPPORTED_GOAL_HANDICAP_LINES
    },
}


class ApiFootballClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={
                'x-apisports-key': api_key or '',
                'accept': 'application/json',
            },
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_upcoming_fixtures(
        self,
        *,
        league_code: str,
        league_id: int,
        season: int,
        date_from: date,
        date_to: date,
        timezone: str = 'UTC',
    ) -> FixtureBatch:
        if not self._api_key:
            raise ApiFootballError('NUTMEG_API_FOOTBALL_KEY is not configured.')

        payload, quota = self._request_payload(
            '/fixtures',
            params={
                'league': league_id,
                'season': season,
                'from': date_from.isoformat(),
                'to': date_to.isoformat(),
                'timezone': timezone,
            },
        )
        fixtures = [
            self._normalize_fixture(item, league_code)
            for item in payload.get('response', [])
        ]

        return FixtureBatch(
            fixtures=fixtures,
            requests_made=1,
            quota=quota,
        )

    def fetch_fixtures_by_date(
        self,
        day: date,
        *,
        timezone: str = 'UTC',
    ) -> FixtureBatch:
        """All fixtures on a single calendar day, across every league.

        Mirrors the API-Football tester's ``GET /fixtures?date=YYYY-MM-DD`` —
        one request returns the whole day's board (clubs + national teams)
        regardless of league. The JCZQ daily flow uses this to align the 体彩
        国际赛/世界杯 board (national-team friendlies) against API-Football
        without needing a per-league id alias for each tournament. A malformed
        fixture row is skipped rather than crashing the batch.
        """
        if not self._api_key:
            raise ApiFootballError('NUTMEG_API_FOOTBALL_KEY is not configured.')

        payload, quota = self._request_payload(
            '/fixtures',
            params={'date': day.isoformat(), 'timezone': timezone},
        )
        fixtures: list[Fixture] = []
        for item in payload.get('response', []):
            league = item.get('league') or {}
            league_code = str(league.get('name') or league.get('id') or 'api-football')
            try:
                fixtures.append(self._normalize_fixture(item, league_code))
            except (KeyError, TypeError, ValueError):
                continue
        return FixtureBatch(fixtures=fixtures, requests_made=1, quota=quota)

    def _normalize_fixture(
        self,
        payload: dict[str, Any],
        league_code: str,
    ) -> Fixture:
        fixture = payload.get('fixture', {})
        league = payload.get('league', {})
        teams = payload.get('teams', {})
        goals = payload.get('goals', {})
        status = fixture.get('status', {})
        return Fixture(
            fixture_id=str(fixture['id']),
            league_code=league_code,
            provider_league_id=int(league['id']),
            season=int(league['season']),
            kickoff_at=_parse_datetime(fixture['date']),
            home_team_id=teams.get('home', {}).get('id'),
            away_team_id=teams.get('away', {}).get('id'),
            home_team=teams.get('home', {}).get('name', 'Unknown'),
            away_team=teams.get('away', {}).get('name', 'Unknown'),
            source='api-football',
            status=FixtureStatus.from_api_short(status.get('short')),
            status_short=status.get('short', 'NS'),
            status_long=status.get('long', 'Unknown'),
            round_name=league.get('round'),
            venue=(fixture.get('venue') or {}).get('name'),
            referee=fixture.get('referee'),
            home_goals=goals.get('home'),
            away_goals=goals.get('away'),
        )

    def fetch_fixture_injuries(self, fixture_id: str) -> dict[int, list[InjuryStatus]]:
        if not self._api_key:
            return {}

        payload, _ = self._request_payload('/injuries', params={'fixture': fixture_id})

        injuries: dict[int, list[InjuryStatus]] = {}
        seen_records: set[tuple[int, int | str, str, str | None, str | None]] = set()
        for item in payload.get('response', []):
            team = item.get('team') or {}
            player = item.get('player') or {}
            team_id = team.get('id')
            if team_id is None:
                continue
            normalized_team_id = int(team_id)
            player_id = self._to_int(player.get('id'))
            record_key = (
                normalized_team_id,
                player_id if player_id is not None else _normalized_player_key(player.get('name')),
                player.get('type', 'Unavailable'),
                player.get('reason'),
                player.get('expected_return'),
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            injuries.setdefault(normalized_team_id, []).append(
                InjuryStatus(
                    player_name=player.get('name', 'Unknown'),
                    status=player.get('type', 'Unavailable'),
                    reason=player.get('reason'),
                    expected_return=player.get('expected_return'),
                    source='api-football',
                )
            )
        return injuries

    def fetch_fixture_lineups(self, fixture_id: str) -> dict[int, TeamLineup]:
        if not self._api_key:
            return {}

        payload, _ = self._request_payload('/fixtures/lineups', params={'fixture': fixture_id})

        lineups: dict[int, TeamLineup] = {}
        for item in payload.get('response', []):
            team = item.get('team') or {}
            team_id = team.get('id')
            if team_id is None:
                continue
            starters = []
            for starter in item.get('startXI', []):
                player = starter.get('player') or {}
                starters.append(
                    LineupPlayer(
                        player_name=player.get('name', 'Unknown'),
                        position=player.get('pos'),
                        shirt_number=(
                            str(player.get('number'))
                            if player.get('number') is not None
                            else None
                        ),
                        role='starter',
                        captain=bool(player.get('captain', False)),
                    )
                )
            lineups[int(team_id)] = TeamLineup(
                status='confirmed',
                source='api-football',
                formation=item.get('formation'),
                players=starters,
            )
        return lineups

    def fetch_fixture_odds(self, fixture_id: str) -> OddsProviderSnapshotFeed:
        if not self._api_key:
            raise ApiFootballError('NUTMEG_API_FOOTBALL_KEY is not configured.')

        payload, _ = self._request_payload('/odds', params={'fixture': fixture_id})
        response = payload.get('response') or []
        if not response:
            return OddsProviderSnapshotFeed(
                provider='api-football',
                updated_at=None,
                bookmaker_count=0,
                markets={},
            )

        item = response[0]
        markets: dict[str, dict[str, Any]] = {}
        bookmaker_keys: set[int | str] = set()
        seen_quotes: set[tuple[int | str, str, str]] = set()

        for bookmaker in item.get('bookmakers') or []:
            bookmaker_id = self._to_int(bookmaker.get('id'))
            bookmaker_name = str(bookmaker.get('name') or 'Unknown')
            bookmaker_identity: int | str = (
                bookmaker_id if bookmaker_id is not None else bookmaker_name
            )
            bookmaker_keys.add(bookmaker_identity)
            for bet in bookmaker.get('bets') or []:
                bet_id = self._to_int(bet.get('id'))
                bet_name = str(bet.get('name') or 'Unknown')
                for value in bet.get('values') or []:
                    normalized = self._normalize_odds_selection(
                        bet_id=bet_id,
                        bet_name=bet_name,
                        selection_value=value.get('value'),
                    )
                    if normalized is None:
                        continue
                    market_key, outcome_key, outcome_name, line = normalized
                    odd = self._to_float(value.get('odd'))
                    if odd is None or odd <= 1:
                        continue
                    dedupe_key = (
                        bookmaker_identity,
                        market_key,
                        str(value.get('value') or '').strip().casefold(),
                    )
                    if dedupe_key in seen_quotes:
                        continue
                    seen_quotes.add(dedupe_key)
                    market_entry = markets.setdefault(
                        market_key,
                        {
                            'market_name': SUPPORTED_ODDS_MARKETS[market_key][1],
                            'line': line,
                            'source_market_ids': set(),
                            'outcomes': {},
                        },
                    )
                    if bet_id is not None:
                        market_entry['source_market_ids'].add(bet_id)
                    outcome_entry = market_entry['outcomes'].setdefault(
                        outcome_key,
                        {
                            'outcome_name': outcome_name,
                            'bookmaker_quotes': [],
                        },
                    )
                    outcome_entry['bookmaker_quotes'].append(
                        BookmakerQuote(
                            bookmaker_id=bookmaker_id or -1,
                            bookmaker_name=bookmaker_name,
                            market_id=bet_id or -1,
                            market_name=bet_name,
                            selection_value=str(value.get('value') or ''),
                            decimal_odds=odd,
                            source='api-football',
                        )
                    )

        return OddsProviderSnapshotFeed(
            provider='api-football',
            updated_at=_parse_datetime(item['update']) if item.get('update') else None,
            bookmaker_count=len(bookmaker_keys),
            markets={
                market_key: MarketOddsSnapshot(
                    market_key=market_key,
                    market_name=entry['market_name'],
                    status='available',
                    line=entry['line'],
                    source_market_ids=sorted(entry['source_market_ids']),
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key=outcome_key,
                            outcome_name=entry['outcomes'][outcome_key]['outcome_name'],
                            bookmaker_quotes=entry['outcomes'][outcome_key]['bookmaker_quotes'],
                            bookmaker_count=len(
                                entry['outcomes'][outcome_key]['bookmaker_quotes']
                            ),
                        )
                        for outcome_key in self._ordered_outcome_keys(market_key, entry)
                        if outcome_key in entry['outcomes']
                    ],
                )
                for market_key, entry in markets.items()
            },
        )

    def fetch_team_sidelined(
        self,
        team_id: int,
        season: int,
        *,
        as_of_date: date | None = None,
    ) -> list[AvailabilityRecord]:
        del season
        if not self._api_key:
            return []

        squad_payload, _ = self._request_payload(
            '/players/squads',
            params={'team': team_id},
        )
        squad_response = squad_payload.get('response') or []
        if not squad_response:
            return []

        as_of = as_of_date or datetime.now(UTC).date()
        records: list[AvailabilityRecord] = []
        for player in (squad_response[0].get('players') or []):
            player_id = self._to_int(player.get('id'))
            if player_id is None:
                continue
            player_name = player.get('name', 'Unknown')
            sidelined_payload, _ = self._request_payload(
                '/sidelined',
                params={'player': player_id},
            )
            active_record = self._active_sidelined_record(
                sidelined_payload.get('response') or [],
                as_of=as_of,
            )
            if active_record is None:
                continue
            records.append(
                AvailabilityRecord(
                    player_name=player_name,
                    status=active_record.get('type')
                    or active_record.get('status')
                    or 'Unavailable',
                    reason=active_record.get('reason'),
                    expected_return=active_record.get('end')
                    or active_record.get('expected_return'),
                    source='api-football',
                )
            )
        return records

    def fetch_team_statistics(
        self,
        *,
        team_id: int,
        league_id: int,
        season: int,
    ) -> TeamSplitSummary | None:
        if not self._api_key:
            return None

        payload, _ = self._request_payload(
            '/teams/statistics',
            params={'team': team_id, 'league': league_id, 'season': season},
        )
        response = payload.get('response') or {}
        if isinstance(response, list):
            response = response[0] if response else {}
        fixtures = response.get('fixtures') or {}
        played = fixtures.get('played') or {}
        wins = fixtures.get('wins') or {}
        draws = fixtures.get('draws') or {}
        goals = ((response.get('goals') or {}).get('for') or {}).get('total') or {}

        home_played = self._to_int(played.get('home'))
        away_played = self._to_int(played.get('away'))
        home_points = (
            (self._to_int(wins.get('home')) or 0) * 3
            + (self._to_int(draws.get('home')) or 0)
        )
        away_points = (
            (self._to_int(wins.get('away')) or 0) * 3
            + (self._to_int(draws.get('away')) or 0)
        )
        home_goals = self._to_float(goals.get('home'))
        away_goals = self._to_float(goals.get('away'))
        if home_played in (None, 0) and away_played in (None, 0):
            return None
        return TeamSplitSummary(
            home_points_per_match=self._per_match(home_points, home_played),
            away_points_per_match=self._per_match(away_points, away_played),
            home_goals_for_per_match=self._per_match(home_goals, home_played),
            away_goals_for_per_match=self._per_match(away_goals, away_played),
            source='api-football',
        )

    def fetch_head_to_head(
        self,
        *,
        home_team_id: int,
        away_team_id: int,
        last: int = 5,
    ) -> HeadToHeadSummary | None:
        if not self._api_key:
            return None

        payload, _ = self._request_payload(
            '/fixtures/headtohead',
            params={'h2h': f'{home_team_id}-{away_team_id}', 'last': last},
        )
        home_wins = 0
        draws = 0
        away_wins = 0
        matches = 0
        for item in payload.get('response', []):
            teams = item.get('teams') or {}
            home_team = teams.get('home') or {}
            away_team = teams.get('away') or {}
            goals = item.get('goals') or {}
            raw_home_goals = self._to_int(goals.get('home'))
            raw_away_goals = self._to_int(goals.get('away'))
            if raw_home_goals is None or raw_away_goals is None:
                continue
            item_home_id = self._to_int(home_team.get('id'))
            item_away_id = self._to_int(away_team.get('id'))
            if item_home_id == home_team_id and item_away_id == away_team_id:
                perspective_home_goals = raw_home_goals
                perspective_away_goals = raw_away_goals
            elif item_home_id == away_team_id and item_away_id == home_team_id:
                perspective_home_goals = raw_away_goals
                perspective_away_goals = raw_home_goals
            else:
                continue
            matches += 1
            if perspective_home_goals > perspective_away_goals:
                home_wins += 1
            elif perspective_home_goals < perspective_away_goals:
                away_wins += 1
            else:
                draws += 1

        if matches == 0:
            return None
        return HeadToHeadSummary(
            matches=matches,
            home_wins=home_wins,
            draws=draws,
            away_wins=away_wins,
            source='api-football',
        )

    def _request_payload(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], ApiQuota]:
        response = self._client.get(path, params=params)
        quota = _parse_quota(response.headers)
        if response.status_code == 429:
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiFootballError(f'API-Football request failed: {exc}') from exc

        payload = response.json()
        error_message = _parse_errors(payload)
        if error_message:
            raise ApiFootballError(f'API-Football returned errors: {error_message}')
        return payload, quota

    def _to_int(self, value: Any) -> int | None:
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _per_match(self, total: int | float | None, matches: int | None) -> float | None:
        if total is None or matches in (None, 0):
            return None
        return round(float(total) / matches, 2)

    def _active_sidelined_record(
        self,
        records: list[dict[str, Any]],
        *,
        as_of: date,
    ) -> dict[str, Any] | None:
        active_records: list[tuple[date, dict[str, Any]]] = []
        for item in records:
            start = self._parse_date(item.get('start'))
            end = self._parse_date(item.get('end'))
            if start is not None and start > as_of:
                continue
            if end is not None and end < as_of:
                continue
            sort_date = start or as_of
            active_records.append((sort_date, item))
        if not active_records:
            return None
        active_records.sort(key=lambda pair: pair[0], reverse=True)
        return active_records[0][1]

    def _parse_date(self, value: Any) -> date | None:
        if value in (None, ''):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _normalize_odds_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection_value: Any,
    ) -> tuple[str, str, str, str | None] | None:
        selection = str(selection_value or '').strip()
        if self._matches_supported_odds_market(bet_id, bet_name, 'match_winner'):
            if selection == 'Home':
                return ('match_winner', 'home', 'Home', None)
            if selection == 'Draw':
                return ('match_winner', 'draw', 'Draw', None)
            if selection == 'Away':
                return ('match_winner', 'away', 'Away', None)
            return None
        if self._matches_supported_odds_market(bet_id, bet_name, 'btts'):
            if selection == 'Yes':
                return ('btts', 'yes', 'Yes', None)
            if selection == 'No':
                return ('btts', 'no', 'No', None)
            return None
        totals_selection = self._normalize_totals_selection(
            bet_id=bet_id,
            bet_name=bet_name,
            selection=selection,
        )
        if totals_selection is not None:
            return totals_selection
        total_goals_selection = self._normalize_total_goals_selection(
            bet_id=bet_id,
            bet_name=bet_name,
            selection=selection,
        )
        if total_goals_selection is not None:
            return total_goals_selection
        correct_score_selection = self._normalize_correct_score_selection(
            bet_id=bet_id,
            bet_name=bet_name,
            selection=selection,
        )
        if correct_score_selection is not None:
            return correct_score_selection
        goal_handicap_selection = self._normalize_goal_handicap_selection(
            bet_id=bet_id,
            bet_name=bet_name,
            selection=selection,
        )
        if goal_handicap_selection is not None:
            return goal_handicap_selection
        asian_selection = self._normalize_asian_handicap_selection(
            bet_id=bet_id,
            bet_name=bet_name,
            selection=selection,
        )
        if asian_selection is not None:
            return asian_selection
        return None

    def _market_outcome_order(self, market_key: str) -> tuple[str, ...]:
        if market_key == 'match_winner':
            return ('home', 'draw', 'away')
        if market_key == 'btts':
            return ('yes', 'no')
        if market_key in {'totals_1_5', 'totals_2_5', 'totals_3_5'}:
            return ('over', 'under')
        if market_key == 'total_goals':
            return total_goals_outcome_keys()
        if market_key.startswith('handicap_home_'):
            return ('home', 'draw', 'away')
        if market_key.startswith('asian_handicap_'):
            return ('home', 'away')
        return ()

    def _ordered_outcome_keys(
        self,
        market_key: str,
        entry: dict[str, Any],
    ) -> tuple[str, ...]:
        # Correct score has an open-ended outcome set; emit it in score order.
        if market_key == 'correct_score':
            return tuple(sorted(entry['outcomes'], key=_correct_score_sort_key))
        return self._market_outcome_order(market_key)

    def _matches_supported_odds_market(
        self,
        bet_id: int | None,
        bet_name: str,
        market_key: str,
    ) -> bool:
        expected_id, expected_name = SUPPORTED_ODDS_MARKETS[market_key]
        if bet_id == expected_id:
            return True
        return bet_name == expected_name

    def _normalize_totals_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection: str,
    ) -> tuple[str, str, str, str | None] | None:
        for line in ('1.5', '2.5', '3.5'):
            market_key = f"totals_{line.replace('.', '_')}"
            if not self._matches_supported_odds_market(bet_id, bet_name, market_key):
                continue
            if selection == f'Over {line}':
                return (market_key, 'over', 'Over', line)
            if selection == f'Under {line}':
                return (market_key, 'under', 'Under', line)
        return None

    def _normalize_asian_handicap_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection: str,
    ) -> tuple[str, str, str, str | None] | None:
        if not (bet_id == 13 or bet_name == 'Asian Handicap'):
            return None
        normalized = selection.replace(' ', '')
        for side, outcome_key, outcome_name in (
            ('Home', 'home', 'Home'),
            ('Away', 'away', 'Away'),
        ):
            if not normalized.startswith(side):
                continue
            line = self._normalized_handicap_line(normalized.removeprefix(side))
            if line not in SUPPORTED_HANDICAP_LINES:
                return None
            key_suffix = line.replace('.', '_')
            return (f'asian_handicap_{key_suffix}', outcome_key, outcome_name, line)
        return None

    def _normalized_handicap_line(self, value: str) -> str | None:
        raw = value.strip().lstrip('+-')
        if raw in {'', '0'}:
            return None
        try:
            numeric = abs(float(raw))
        except ValueError:
            return None
        if numeric.is_integer():
            return f'{numeric:.1f}'
        return f'{numeric:.2f}'.rstrip('0')

    def _normalize_total_goals_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection: str,
    ) -> tuple[str, str, str, str | None] | None:
        if not self._matches_supported_odds_market(bet_id, bet_name, 'total_goals'):
            return None
        raw = selection.strip().casefold()
        # Tail bucket variants: '7+', '7 or more', 'more 6.5'.
        if raw.endswith('+') or 'more' in raw or 'over' in raw:
            digits = ''.join(ch for ch in raw if ch.isdigit())
            if digits and int(digits) >= MAX_TOTAL_GOALS_BUCKET - 1:
                key = f'total_{MAX_TOTAL_GOALS_BUCKET}_plus'
                return ('total_goals', key, f'{MAX_TOTAL_GOALS_BUCKET}+', None)
            return None
        if not raw.isdigit():
            return None
        goals = int(raw)
        if goals < 0:
            return None
        if goals >= MAX_TOTAL_GOALS_BUCKET:
            key = f'total_{MAX_TOTAL_GOALS_BUCKET}_plus'
            return ('total_goals', key, f'{MAX_TOTAL_GOALS_BUCKET}+', None)
        return ('total_goals', f'total_{goals}', str(goals), None)

    def _normalize_correct_score_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection: str,
    ) -> tuple[str, str, str, str | None] | None:
        if not self._matches_supported_odds_market(bet_id, bet_name, 'correct_score'):
            return None
        raw = selection.strip().replace(' ', '')
        separator = ':' if ':' in raw else ('-' if '-' in raw else None)
        if separator is None:
            return None
        home_part, _, away_part = raw.partition(separator)
        if not (home_part.isdigit() and away_part.isdigit()):
            return None
        home_goals = int(home_part)
        away_goals = int(away_part)
        return (
            'correct_score',
            f'score_{home_goals}_{away_goals}',
            f'{home_goals}:{away_goals}',
            None,
        )

    def _normalize_goal_handicap_selection(
        self,
        *,
        bet_id: int | None,
        bet_name: str,
        selection: str,
    ) -> tuple[str, str, str, str | None] | None:
        if not (bet_id == 9 or bet_name == 'Handicap Result'):
            return None
        parts = selection.strip().split()
        if len(parts) != 2:
            return None
        side, raw_line = parts
        outcome = {'home': 'home', 'draw': 'draw', 'away': 'away'}.get(side.casefold())
        if outcome is None:
            return None
        try:
            line = int(float(raw_line))
        except ValueError:
            return None
        if line not in SUPPORTED_GOAL_HANDICAP_LINES:
            return None
        market_key = f'handicap_home_{_goal_handicap_suffix(line)}'
        return (
            market_key,
            outcome,
            outcome.capitalize(),
            _goal_handicap_line_label(line),
        )
