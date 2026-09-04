"""Exact curated competition-edition resolution for source board labels."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from nutmeg.decision.entities import load_seed_entities
from nutmeg.decision.identity import norm_team
from nutmeg.decision.ontology import League
from nutmeg.ontology.identity.models import CompetitionEditionRef


def resolve_competition_edition(
    source_name: str,
    *,
    leagues: Iterable[League] | None = None,
) -> CompetitionEditionRef | None:
    """Resolve one unique exact alias with an explicit curated season."""

    normalized = norm_team(source_name)
    if not normalized:
        return None
    candidates: dict[tuple[str, str], League] = {}
    if leagues is None:
        _, loaded = load_seed_entities()
        leagues = loaded
    for league in leagues:
        aliases = (league.name_zh, league.name_en, *league.aliases)
        if normalized in {norm_team(alias) for alias in aliases if alias}:
            season = league.season.strip()
            if season:
                candidates[(league.league_id, season)] = league
    if len(candidates) != 1:
        return None
    (competition_id, season), league = next(iter(candidates.items()))
    digest = hashlib.sha256(f"{competition_id}\0{season}".encode()).hexdigest()[:24]
    display_name = league.name_en or league.name_zh
    return CompetitionEditionRef(
        competition_id=competition_id,
        competition_name=display_name,
        competition_country=league.country or None,
        competition_kind="football",
        competition_edition_id=f"competition-edition-{digest}",
        edition_name=f"{display_name} {season}",
        season_label=season,
    )
