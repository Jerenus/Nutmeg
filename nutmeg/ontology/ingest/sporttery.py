"""Parse sporttery getMatchCalculatorV1 markets into typed ParsedMatch records.

Mirrors the real payload iteration of ``nutmeg.decision.market_data`` (matchInfoList
-> subMatchList, Selling only, businessDate filter) and reuses ``_had_from_pool``
for the had odds. The value it *adds* is a real ``scheduled_at``: the provider's
``matchDate`` + ``matchTime`` interpreted as Beijing (+08:00). Because ``matchDate``
already carries the true calendar date, an early-morning kickoff naturally lands on
the next day — the "周X0NN = 北京次日" trap is fixed by construction, never clamped to
the business date. A missing date/time yields an explicit ``unknown``, never a guess.

The globally-unique provider id is ``matchId``; ``matchNumStr`` (e.g. "周日104") is the
per-day cross-channel key that international odds align to.
"""
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.decision.market_data import _had_from_pool

_BEIJING_OFFSET = '+08:00'


@dataclass(frozen=True, slots=True)
class ParsedQuote:
    market_kind: str
    outcome_key: str
    decimal_odds: float
    line: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedMatch:
    provider: str
    external_id: str
    match_no: str
    business_date: str
    home_name: str
    away_name: str
    league_name: str
    scheduled_at: str | None
    schedule_status: str
    quotes: tuple[ParsedQuote, ...]


def _scheduled_at(match_date: str, match_time: str) -> str | None:
    if not match_date or not match_time:
        return None
    return f'{match_date}T{match_time}{_BEIJING_OFFSET}'


def parse_sporttery_markets(value: dict, *, business_date: str) -> list[ParsedMatch]:
    matches: list[ParsedMatch] = []
    for day in value.get('matchInfoList') or []:
        for raw in day.get('subMatchList') or []:
            if str(raw.get('matchStatus') or '').casefold() != 'selling':
                continue
            row_business_date = str(raw.get('businessDate') or day.get('businessDate') or '')
            if business_date and row_business_date and row_business_date != business_date:
                continue
            match_id = str(raw.get('matchId') or '')
            match_no = str(raw.get('matchNumStr') or '')
            if not match_id or not match_no:
                continue
            scheduled_at = _scheduled_at(
                str(raw.get('matchDate') or ''), str(raw.get('matchTime') or '')
            )
            quotes = tuple(
                ParsedQuote(market_kind='had', outcome_key=outcome_key, decimal_odds=decimal_odds)
                for outcome_key, decimal_odds in _had_from_pool(raw.get('had') or {}).items()
            )
            matches.append(
                ParsedMatch(
                    provider='sporttery',
                    external_id=match_id,
                    match_no=match_no,
                    business_date=row_business_date or business_date,
                    home_name=str(raw.get('homeTeamAbbName') or ''),
                    away_name=str(raw.get('awayTeamAbbName') or ''),
                    league_name=str(raw.get('leagueAbbName') or ''),
                    scheduled_at=scheduled_at,
                    schedule_status='scheduled' if scheduled_at else 'unknown',
                    quotes=quotes,
                )
            )
    return matches
