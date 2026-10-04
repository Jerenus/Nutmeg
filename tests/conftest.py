from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.config.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('NUTMEG_DATA_DIR', str(tmp_path / '.nutmeg-data'))
    monkeypatch.setenv('NUTMEG_LANGSMITH_ENABLED', 'false')
    monkeypatch.delenv('NUTMEG_API_FOOTBALL_KEY', raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
