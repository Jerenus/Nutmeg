"""API-Football 客户端：只剩按日期查赛程（`decision-alias-propose` 用它给中文队名找英文拼写）。

赔率部分与 `services/jczq_apifootball_odds` 备源一起于 2026-10-08 删除：免费档 8 天回放只覆盖
63/127，开着时额度耗尽、9 月 429 共 262 次一场没补上；国际欧赔由 titan007 独供。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from nutmeg.domain.fixtures import Fixture, FixtureStatus


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

    def fetch_lineups(self, fixture_id: str) -> list[dict[str, Any]]:
        """``GET /fixtures/lineups?fixture=`` → 每队 ``{team, xi:[球员名], bench:[球员名]}``。

        开球前约 1 小时才有数据；没有就返回空列表（lineup_watch 记 no_lineups 下轮再试）。
        """
        if not self._api_key:
            raise ApiFootballError('NUTMEG_API_FOOTBALL_KEY is not configured.')
        payload, _quota = self._request_payload(
            '/fixtures/lineups', params={'fixture': str(fixture_id)},
        )

        def _names(rows: Any) -> list[str]:
            return [str((r.get('player') or {}).get('name') or '')
                    for r in (rows or []) if isinstance(r, dict)]

        return [
            {
                'team': str((item.get('team') or {}).get('name') or ''),
                'xi': _names(item.get('startXI')),
                'bench': _names(item.get('substitutes')),
            }
            for item in payload.get('response', []) if isinstance(item, dict)
        ]

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
            penalty_home=(payload.get('score', {}).get('penalty') or {}).get('home'),
            penalty_away=(payload.get('score', {}).get('penalty') or {}).get('away'),
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
