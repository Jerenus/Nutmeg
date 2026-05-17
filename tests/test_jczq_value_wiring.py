"""Bridge-builder wiring for the daily brief (Phase 3 piece 2).

``build_jczq_value_bridge`` assembles a live ``JczqValueBridge`` from settings,
or returns ``None`` (graceful degradation) when the API-Football key is absent.
No network: tests only exercise the no-key path and pure helpers.
"""

from __future__ import annotations

from nutmeg.config.settings import AppSettings
from nutmeg.services.jczq_value_wiring import (
    build_jczq_value_bridge,
    season_for_date,
)


def test_season_for_date_maps_spring_to_prior_year() -> None:
    # A European-league fixture in May 2026 belongs to the 2025/26 season,
    # which API-Football labels season=2025.
    assert season_for_date("2026-05-17") == 2025


def test_season_for_date_maps_autumn_to_same_year() -> None:
    # An August fixture starts the new season → season == the calendar year.
    assert season_for_date("2025-08-30") == 2025


def test_build_bridge_returns_none_without_api_key() -> None:
    # No NUTMEG_API_FOOTBALL_KEY → graceful degradation, no bridge, no crash.
    settings = AppSettings(api_football_key=None)

    bridge = build_jczq_value_bridge(settings=settings, run_date="2026-05-17")

    assert bridge is None


def test_build_bridge_returns_none_for_blank_api_key() -> None:
    settings = AppSettings(api_football_key="   ")

    bridge = build_jczq_value_bridge(settings=settings, run_date="2026-05-17")

    assert bridge is None
