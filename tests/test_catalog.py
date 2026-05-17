"""Tests for the league catalog helpers."""

from __future__ import annotations

from nutmeg.config.catalog import league_code_by_api_football_id


def test_league_code_by_api_football_id_maps_to_catalog_codes() -> None:
    """The aligner labels API-Football fixtures with the catalog league code
    so the model snapshot's get_league() resolves them — without this the
    fixture carries a non-catalog label and FixtureSnapshotService raises
    'Unknown league code'.
    """
    mapping = league_code_by_api_football_id()

    assert mapping[39] == "epl"
    assert mapping[140] == "laliga"
    assert mapping[135] == "serie-a"
    assert mapping[61] == "ligue-1"
    assert mapping[78] == "bundesliga"
