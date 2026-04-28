from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


@dataclass(slots=True, frozen=True)
class TeamSourceMapping:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    sources: dict[str, str] = field(default_factory=dict)
    home_base_query: str | None = None
    home_country: str | None = None


@dataclass(slots=True)
class TeamCatalog:
    _teams: dict[str, TeamSourceMapping]
    _aliases: dict[str, str]

    def normalize(self, team_name: str) -> str:
        return self._aliases.get(_slug(team_name), team_name)

    def resolve_source_name(self, team_name: str, provider: str) -> str:
        canonical = self.normalize(team_name)
        mapping = self._teams.get(canonical)
        if mapping is None:
            return canonical
        return mapping.sources.get(provider, canonical)

    def home_base_query(self, team_name: str) -> str | None:
        canonical = self.normalize(team_name)
        mapping = self._teams.get(canonical)
        return mapping.home_base_query if mapping is not None else None

    def home_country(self, team_name: str) -> str | None:
        canonical = self.normalize(team_name)
        mapping = self._teams.get(canonical)
        return mapping.home_country if mapping is not None else None


@lru_cache(maxsize=1)
def load_team_catalog(config_path: str = 'config/teams.yaml') -> TeamCatalog:
    payload = yaml.safe_load(Path(config_path).read_text(encoding='utf-8')) or {}
    teams: dict[str, TeamSourceMapping] = {}
    aliases: dict[str, str] = {}

    for alias, canonical in payload.get('aliases', {}).items():
        aliases[_slug(alias)] = canonical

    for canonical_name, item in payload.get('teams', {}).items():
        mapping = TeamSourceMapping(
            canonical_name=canonical_name,
            aliases=tuple(item.get('aliases', [])),
            sources=dict(item.get('sources', {})),
            home_base_query=item.get('home_base_query'),
            home_country=item.get('home_country'),
        )
        teams[canonical_name] = mapping
        aliases[_slug(canonical_name)] = canonical_name
        for alias in mapping.aliases:
            aliases[_slug(alias)] = canonical_name

    return TeamCatalog(_teams=teams, _aliases=aliases)
