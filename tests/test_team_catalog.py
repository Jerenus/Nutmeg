from __future__ import annotations

from nutmeg.config.team_catalog import load_team_catalog


def test_team_catalog_normalizes_aliases_and_source_names() -> None:
    catalog = load_team_catalog()

    assert catalog.normalize('spurs') == 'Tottenham Hotspur'
    assert catalog.resolve_source_name('spurs', provider='understat') == 'Tottenham'
    assert catalog.resolve_source_name('Tottenham Hotspur', provider='fbref') == 'Tottenham Hotspur'


def test_team_catalog_falls_back_to_canonical_name_when_mapping_is_not_needed() -> None:
    catalog = load_team_catalog()

    assert catalog.resolve_source_name('Arsenal', provider='understat') == 'Arsenal'
