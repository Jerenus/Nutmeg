"""Parse international (bold_odds/500) markets, aligned by sporttery match number.

bold_odds is keyed by the sporttery ``matchNumStr`` (e.g. "周日104"), so its quotes
carry that key and downstream ingest resolves them to the **same** opaque match_id
the sporttery parse produced — cross-channel alignment is by provider match number,
never by team-name string matching.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedIntlQuote:
    align_match_no: str
    market_kind: str
    outcome_key: str
    decimal_odds: float
    line: str | None = None


def parse_bold_odds(value: dict) -> list[ParsedIntlQuote]:
    quotes: list[ParsedIntlQuote] = []
    for match_no, markets in (value or {}).items():
        if not isinstance(markets, dict):
            continue
        odds = ((markets.get('match_winner') or {}).get('odds')) or {}
        for outcome_key in ('home', 'draw', 'away'):
            raw = odds.get(outcome_key)
            if raw is None:
                continue
            try:
                decimal_odds = float(raw)
            except (TypeError, ValueError):
                continue
            if decimal_odds <= 1.0:
                continue
            quotes.append(
                ParsedIntlQuote(
                    align_match_no=str(match_no),
                    market_kind='had',
                    outcome_key=outcome_key,
                    decimal_odds=decimal_odds,
                )
            )
    return quotes
