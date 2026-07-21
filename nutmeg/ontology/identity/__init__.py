"""Football identity layer — public exports."""
from __future__ import annotations

from nutmeg.ontology.identity.models import (
    EntityType,
    MatchSide,
    MatchStatus,
    ResolutionStatus,
    TeamKind,
    mint_id,
)
from nutmeg.ontology.identity.resolver import Resolution, ResolutionMethod, resolve_entity

__all__ = [
    'EntityType',
    'MatchSide',
    'MatchStatus',
    'Resolution',
    'ResolutionMethod',
    'ResolutionStatus',
    'TeamKind',
    'mint_id',
    'resolve_entity',
]
