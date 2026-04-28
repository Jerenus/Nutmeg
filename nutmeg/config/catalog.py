from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(slots=True, frozen=True)
class LeagueConfig:
    code: str
    name: str
    country: str
    group: str
    api_football_id: int
    season_start_month: int = 7
    soccerdata_fbref: str | None = None
    soccerdata_understat: str | None = None
    transfermarkt_competition_id: str | None = None
    the_odds_api_sport_key: str | None = None

    def resolve_season(self, now: datetime) -> int:
        return now.year if now.month >= self.season_start_month else now.year - 1

    def soccerdata_league(self, provider: str) -> str | None:
        if provider == 'fbref':
            return self.soccerdata_fbref
        if provider == 'understat':
            return self.soccerdata_understat
        raise KeyError(f'Unknown soccerdata provider: {provider}')

    @property
    def supports_soccerdata(self) -> bool:
        return bool(self.soccerdata_fbref and self.soccerdata_understat)


@lru_cache(maxsize=1)
def load_league_catalog(config_path: str = 'config/leagues.yaml') -> dict[str, LeagueConfig]:
    path = Path(config_path)
    payload = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    catalog: dict[str, LeagueConfig] = {}
    for item in payload.get('leagues', []):
        league = LeagueConfig(**item)
        catalog[league.code] = league
    return catalog


def select_leagues(codes: list[str] | None = None) -> list[LeagueConfig]:
    catalog = load_league_catalog()
    if not codes:
        return list(catalog.values())
    missing = [code for code in codes if code not in catalog]
    if missing:
        raise KeyError(f'Unknown league codes: {", ".join(missing)}')
    return [catalog[code] for code in codes]


def get_league(code: str) -> LeagueConfig:
    catalog = load_league_catalog()
    try:
        return catalog[code]
    except KeyError as exc:
        raise KeyError(f'Unknown league code: {code}') from exc
