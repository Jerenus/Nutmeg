from __future__ import annotations

from nutmeg.config.settings import get_settings
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.reference_repository import DuckDbReferenceRepository


def test_reference_repository_resolves_player_aliases_and_unmatched() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbReferenceRepository(settings)

    primary = repository.resolve_player_identity(
        league_code='epl',
        team_name='Arsenal',
        provider='api-football',
        player_name='Gabriel Magalhães',
        position='Defender',
        provider_player_id='9001',
    )
    alias = repository.resolve_player_identity(
        league_code='epl',
        team_name='Arsenal',
        provider='transfermarkt',
        player_name='Gabriel',
        position='Defender',
    )
    unresolved = repository.resolve_player_identity(
        league_code='epl',
        team_name='Arsenal',
        provider='api-football',
        player_name='Mystery Trialist',
        position='Attack',
    )

    assert primary is not None
    assert alias is not None
    assert alias.identity_id == primary.identity_id
    assert alias.canonical_name == 'Gabriel Magalhaes'
    assert alias.match_confidence == 'catalog'
    assert unresolved is None
