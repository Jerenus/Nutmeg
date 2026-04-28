from __future__ import annotations

import re
import unicodedata
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from nutmeg.config.catalog import get_league
from nutmeg.core.repositories import FixtureRepository, OddsEventRepository
from nutmeg.domain.odds import (
    BookmakerQuote,
    MarketOddsSnapshot,
    OddsProviderEvent,
    OddsProviderSnapshotFeed,
    OutcomeOddsSnapshot,
)

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

CANONICAL_MARKET_NAMES: dict[str, str] = {
    'match_winner': 'Match Winner',
    'totals_1_5': 'Goals Over/Under',
    'totals_2_5': 'Goals Over/Under',
    'totals_3_5': 'Goals Over/Under',
    'btts': 'Both Teams Score',
    **{
        f"asian_handicap_{line.replace('.', '_')}": 'Asian Handicap'
        for line in SUPPORTED_HANDICAP_LINES
    },
}
SOURCE_MARKET_IDS: dict[str, int] = {
    'h2h': 1001,
    'h2h_3_way': 1002,
    'totals': 1005,
    'btts': 1008,
    'spreads': 1013,
}
SUPPORTED_TOTAL_LINES = {'1.5', '2.5', '3.5'}
TEAM_STOPWORDS = {'ac', 'afc', 'cf', 'club', 'fc', 'sc', 'the'}
TEAM_MIN_SIMILARITY = 0.75
KICKOFF_TOLERANCE = timedelta(hours=6)


@dataclass(slots=True, frozen=True)
class TheOddsApiHealthSnapshot:
    provider: str
    cache_hits: int = 0
    cache_misses: int = 0
    reconcile_attempts: int = 0
    reconcile_failures: int = 0
    stale_refresh_attempts: int = 0
    stale_refresh_successes: int = 0
    last_event_id: str | None = None
    last_error: str | None = None
    updated_at: datetime | None = None


class OddsProviderHealthRepository(Protocol):
    def get_latest(self, provider: str) -> TheOddsApiHealthSnapshot | None:
        ...

    def record_snapshot(self, snapshot: TheOddsApiHealthSnapshot) -> None:
        ...


class TheOddsApiError(RuntimeError):
    pass


class TheOddsApiRequestError(TheOddsApiError):
    def __init__(self, message: str, *, status_code: int, path: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


def _parse_datetime(raw_value: str | None) -> datetime | None:
    if raw_value in (None, ''):
        return None
    return datetime.fromisoformat(str(raw_value).replace('Z', '+00:00')).astimezone(UTC)


def _normalized_team_name(value: str) -> str:
    normalized = (
        unicodedata.normalize('NFKD', value)
        .encode('ascii', 'ignore')
        .decode('ascii')
        .casefold()
        .replace('&', ' and ')
    )
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    tokens = [token for token in normalized.split() if token and token not in TEAM_STOPWORDS]
    return ' '.join(tokens)


def _team_similarity(left: str, right: str) -> float:
    left_name = _normalized_team_name(left)
    right_name = _normalized_team_name(right)
    if not left_name or not right_name:
        return 0.0
    if left_name == right_name:
        return 1.0
    if left_name in right_name or right_name in left_name:
        return 0.9
    left_tokens = set(left_name.split())
    right_tokens = set(right_name.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(left_tokens | right_tokens)


def _stable_id(value: str) -> int:
    return zlib.crc32(value.encode('utf-8')) & 0xFFFFFFFF


class TheOddsApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        fixture_repository: FixtureRepository,
        event_repository: OddsEventRepository,
        health_repository: OddsProviderHealthRepository | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._fixture_repository = fixture_repository
        self._event_repository = event_repository
        self._health_repository = health_repository
        self._owns_client = client is None
        latest = health_repository.get_latest(self.provider_name()) if health_repository else None
        self._cache_hits = latest.cache_hits if latest else 0
        self._cache_misses = latest.cache_misses if latest else 0
        self._reconcile_attempts = latest.reconcile_attempts if latest else 0
        self._reconcile_failures = latest.reconcile_failures if latest else 0
        self._stale_refresh_attempts = latest.stale_refresh_attempts if latest else 0
        self._stale_refresh_successes = latest.stale_refresh_successes if latest else 0
        self._last_event_id = latest.last_event_id if latest else None
        self._last_error = latest.last_error if latest else None
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={'accept': 'application/json'},
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def health_snapshot(self) -> TheOddsApiHealthSnapshot:
        return TheOddsApiHealthSnapshot(
            provider=self.provider_name(),
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            reconcile_attempts=self._reconcile_attempts,
            reconcile_failures=self._reconcile_failures,
            stale_refresh_attempts=self._stale_refresh_attempts,
            stale_refresh_successes=self._stale_refresh_successes,
            last_event_id=self._last_event_id,
            last_error=self._last_error,
            updated_at=datetime.now(UTC),
        )

    def _record_health_snapshot(self) -> None:
        if self._health_repository is not None:
            self._health_repository.record_snapshot(self.health_snapshot())

    def fetch_fixture_odds(self, fixture_id: str) -> OddsProviderSnapshotFeed:
        try:
            if not self._api_key:
                raise TheOddsApiError('NUTMEG_THE_ODDS_API_KEY is not configured.')

            fixture = self._fixture_repository.get_fixture(fixture_id)
            if fixture is None:
                raise TheOddsApiError(
                    f'Fixture `{fixture_id}` is not available for The Odds API reconciliation.'
                )

            cached_event = self._event_repository.get_event(
                fixture_id,
                provider=self.provider_name(),
            )
            if cached_event is None:
                self._cache_misses += 1
                provider_event = self._reconcile_event(fixture)
                self._event_repository.upsert_event(provider_event)
            else:
                self._cache_hits += 1
                provider_event = cached_event
            self._last_event_id = provider_event.event_id
            self._last_error = None

            try:
                payload = self._fetch_event_odds(provider_event)
            except TheOddsApiRequestError as exc:
                if cached_event is None or not self._is_stale_cached_event_error(exc):
                    self._last_error = str(exc)
                    raise
                self._stale_refresh_attempts += 1
                self._event_repository.delete_event(fixture_id, provider=self.provider_name())
                stale_event_id = cached_event.event_id
                try:
                    provider_event = self._reconcile_event(fixture)
                except TheOddsApiError as reconcile_exc:
                    message = (
                        f'Cached The Odds API event `{stale_event_id}` for fixture '
                        f'`{fixture_id}` is stale, and replacement reconciliation failed: '
                        f'{reconcile_exc}'
                    )
                    self._last_error = message
                    raise TheOddsApiError(message) from reconcile_exc
                self._event_repository.upsert_event(provider_event)
                self._stale_refresh_successes += 1
                self._last_event_id = provider_event.event_id
                self._last_error = None
                payload = self._fetch_event_odds(provider_event)
            return self._normalize_odds_payload(payload)
        finally:
            self._record_health_snapshot()

    def _fetch_event_odds(self, provider_event: OddsProviderEvent) -> Any:
        return self._request_json(
            f'/sports/{provider_event.sport_key}/events/{provider_event.event_id}/odds',
            params={
                'regions': 'uk,eu',
                'markets': 'h2h,totals,spreads,btts',
                'oddsFormat': 'decimal',
                'dateFormat': 'iso',
            },
        )

    def _is_stale_cached_event_error(self, exc: TheOddsApiRequestError) -> bool:
        return exc.status_code in {404, 410}

    def _reconcile_event(self, fixture) -> OddsProviderEvent:
        self._reconcile_attempts += 1
        league = get_league(fixture.league_code)
        if not league.the_odds_api_sport_key:
            self._reconcile_failures += 1
            raise TheOddsApiError(
                f'League `{fixture.league_code}` has no The Odds API sport mapping configured.'
            )

        payload = self._request_json(
            f'/sports/{league.the_odds_api_sport_key}/events',
            params={'dateFormat': 'iso'},
        )
        if not isinstance(payload, list):
            self._reconcile_failures += 1
            raise TheOddsApiError('The Odds API events response was not a list.')

        candidates: list[tuple[float, float, dict[str, Any], datetime]] = []
        for item in payload:
            commence_time = _parse_datetime(item.get('commence_time'))
            if commence_time is None:
                continue
            kickoff_delta = abs((commence_time - fixture.kickoff_at).total_seconds())
            if kickoff_delta > KICKOFF_TOLERANCE.total_seconds():
                continue
            home_score = _team_similarity(fixture.home_team, str(item.get('home_team') or ''))
            away_score = _team_similarity(fixture.away_team, str(item.get('away_team') or ''))
            if home_score < TEAM_MIN_SIMILARITY or away_score < TEAM_MIN_SIMILARITY:
                continue
            score = home_score + away_score - (kickoff_delta / 3600.0) * 0.01
            candidates.append((score, kickoff_delta, item, commence_time))

        if not candidates:
            self._reconcile_failures += 1
            raise TheOddsApiError(
                'The Odds API fixture-to-event reconciliation failed for '
                f'fixture `{fixture.fixture_id}` ({fixture.home_team} vs {fixture.away_team}).'
            )

        candidates.sort(key=lambda item: (-item[0], item[1], str(item[2].get('id') or '')))
        best_score, _, best_item, commence_time = candidates[0]
        if len(candidates) > 1 and abs(best_score - candidates[1][0]) < 0.05:
            self._reconcile_failures += 1
            raise TheOddsApiError(
                'The Odds API fixture-to-event reconciliation failed because multiple '
                f'events looked equally plausible for fixture `{fixture.fixture_id}`.'
            )

        event_id = str(best_item.get('id') or '').strip()
        if not event_id:
            self._reconcile_failures += 1
            raise TheOddsApiError(
                'The Odds API returned a reconciled event without an event id.'
            )
        return OddsProviderEvent(
            fixture_id=fixture.fixture_id,
            provider=self.provider_name(),
            sport_key=league.the_odds_api_sport_key,
            event_id=event_id,
            home_team=str(best_item.get('home_team') or fixture.home_team),
            away_team=str(best_item.get('away_team') or fixture.away_team),
            commence_time=commence_time,
            matched_at=datetime.now(UTC),
        )

    def _normalize_odds_payload(self, payload: dict[str, Any]) -> OddsProviderSnapshotFeed:
        bookmakers = payload.get('bookmakers') or []
        if not bookmakers:
            return OddsProviderSnapshotFeed(
                provider=self.provider_name(),
                updated_at=None,
                bookmaker_count=0,
                markets={},
            )

        home_team = str(payload.get('home_team') or '')
        away_team = str(payload.get('away_team') or '')
        markets: dict[str, dict[str, Any]] = {}
        bookmaker_keys: set[str] = set()
        updated_at_candidates: list[datetime] = []
        seen_quotes: set[tuple[str, str, str]] = set()

        for bookmaker in bookmakers:
            bookmaker_key = str(bookmaker.get('key') or bookmaker.get('title') or 'unknown')
            bookmaker_name = str(bookmaker.get('title') or bookmaker_key)
            bookmaker_keys.add(bookmaker_key)
            bookmaker_updated = _parse_datetime(bookmaker.get('last_update'))
            if bookmaker_updated is not None:
                updated_at_candidates.append(bookmaker_updated)
            for market in bookmaker.get('markets') or []:
                provider_market_key = str(market.get('key') or '').strip()
                market_updated = _parse_datetime(market.get('last_update'))
                if market_updated is not None:
                    updated_at_candidates.append(market_updated)
                for outcome in market.get('outcomes') or []:
                    normalized = self._normalize_outcome(
                        provider_market_key=provider_market_key,
                        outcome=outcome,
                        home_team=home_team,
                        away_team=away_team,
                    )
                    if normalized is None:
                        continue
                    market_key, outcome_key, outcome_name, line, selection_value = normalized
                    odds = self._to_float(outcome.get('price'))
                    if odds is None or odds <= 1:
                        continue
                    dedupe_key = (bookmaker_key, market_key, selection_value)
                    if dedupe_key in seen_quotes:
                        continue
                    seen_quotes.add(dedupe_key)
                    entry = markets.setdefault(
                        market_key,
                        {
                            'market_name': CANONICAL_MARKET_NAMES[market_key],
                            'line': line,
                            'source_market_ids': set(),
                            'outcomes': {},
                        },
                    )
                    source_market_id = SOURCE_MARKET_IDS.get(provider_market_key)
                    if source_market_id is not None:
                        entry['source_market_ids'].add(source_market_id)
                    outcome_entry = entry['outcomes'].setdefault(
                        outcome_key,
                        {
                            'outcome_name': outcome_name,
                            'bookmaker_quotes': [],
                        },
                    )
                    outcome_entry['bookmaker_quotes'].append(
                        BookmakerQuote(
                            bookmaker_id=_stable_id(bookmaker_key),
                            bookmaker_name=bookmaker_name,
                            market_id=source_market_id or -1,
                            market_name=provider_market_key,
                            selection_value=selection_value,
                            decimal_odds=odds,
                            source=self.provider_name(),
                        )
                    )

        updated_at = max(updated_at_candidates) if updated_at_candidates else None
        return OddsProviderSnapshotFeed(
            provider=self.provider_name(),
            updated_at=updated_at,
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
                        for outcome_key in self._market_outcome_order(market_key)
                        if outcome_key in entry['outcomes']
                    ],
                )
                for market_key, entry in markets.items()
            },
        )

    def _normalize_outcome(
        self,
        *,
        provider_market_key: str,
        outcome: dict[str, Any],
        home_team: str,
        away_team: str,
    ) -> tuple[str, str, str, str | None, str] | None:
        outcome_name = str(outcome.get('name') or '').strip()
        if provider_market_key in {'h2h', 'h2h_3_way'}:
            if _team_similarity(outcome_name, home_team) >= TEAM_MIN_SIMILARITY:
                return ('match_winner', 'home', 'Home', None, 'home')
            if outcome_name.casefold() == 'draw':
                return ('match_winner', 'draw', 'Draw', None, 'draw')
            if _team_similarity(outcome_name, away_team) >= TEAM_MIN_SIMILARITY:
                return ('match_winner', 'away', 'Away', None, 'away')
            return None
        if provider_market_key == 'btts':
            normalized = outcome_name.casefold()
            if normalized == 'yes':
                return ('btts', 'yes', 'Yes', None, 'yes')
            if normalized == 'no':
                return ('btts', 'no', 'No', None, 'no')
            return None
        if provider_market_key == 'totals':
            line = self._normalized_line(outcome.get('point'))
            if line not in SUPPORTED_TOTAL_LINES:
                return None
            normalized = outcome_name.casefold()
            if normalized == 'over':
                return (f"totals_{line.replace('.', '_')}", 'over', 'Over', line, f'over-{line}')
            if normalized == 'under':
                return (
                    f"totals_{line.replace('.', '_')}",
                    'under',
                    'Under',
                    line,
                    f'under-{line}',
                )
            return None
        if provider_market_key == 'spreads':
            line = self._normalized_line(abs(self._to_float(outcome.get('point')) or 0.0))
            if line not in SUPPORTED_HANDICAP_LINES:
                return None
            if _team_similarity(outcome_name, home_team) >= TEAM_MIN_SIMILARITY:
                return (
                    f'asian_handicap_{line.replace(".", "_")}',
                    'home',
                    'Home',
                    line,
                    f'home-{line}',
                )
            if _team_similarity(outcome_name, away_team) >= TEAM_MIN_SIMILARITY:
                return (
                    f'asian_handicap_{line.replace(".", "_")}',
                    'away',
                    'Away',
                    line,
                    f'away-{line}',
                )
        return None

    def _market_outcome_order(self, market_key: str) -> tuple[str, ...]:
        if market_key == 'match_winner':
            return ('home', 'draw', 'away')
        if market_key == 'btts':
            return ('yes', 'no')
        if market_key in {'totals_1_5', 'totals_2_5', 'totals_3_5'}:
            return ('over', 'under')
        if market_key.startswith('asian_handicap_'):
            return ('home', 'away')
        return ()

    def _request_json(self, path: str, *, params: dict[str, Any]) -> Any:
        request_params = {'apiKey': self._api_key, **params}
        response = self._client.get(path, params=request_params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(response)
            suffix = f': {message}' if message else ''
            raise TheOddsApiRequestError(
                f'The Odds API request failed ({response.status_code}) for `{path}`{suffix}',
                status_code=response.status_code,
                path=path,
            ) from exc
        return response.json()

    def _extract_error_message(self, response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict):
            for key in ('message', 'error', 'details'):
                value = payload.get(key)
                if value:
                    return str(value)
        return None

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalized_line(self, value: Any) -> str | None:
        numeric = self._to_float(value)
        if numeric is None:
            return None
        numeric = abs(numeric)
        if numeric.is_integer():
            return f'{numeric:.1f}'
        return f'{numeric:.2f}'.rstrip('0')

    @staticmethod
    def provider_name() -> str:
        return 'the-odds-api'
