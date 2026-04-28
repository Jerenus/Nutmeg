from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.config.catalog import load_league_catalog
from nutmeg.config.settings import clear_settings_cache
from nutmeg.config.team_catalog import load_team_catalog


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('NUTMEG_DATA_DIR', str(tmp_path / '.nutmeg-data'))
    monkeypatch.setenv('NUTMEG_LANGSMITH_ENABLED', 'false')
    monkeypatch.delenv('NUTMEG_API_FOOTBALL_KEY', raising=False)
    clear_settings_cache()
    load_league_catalog.cache_clear()
    load_team_catalog.cache_clear()
    yield
    clear_settings_cache()
    load_league_catalog.cache_clear()
    load_team_catalog.cache_clear()
