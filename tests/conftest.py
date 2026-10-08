from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.config.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('NUTMEG_DATA_DIR', str(tmp_path / '.nutmeg-data'))
    monkeypatch.delenv('NUTMEG_API_FOOTBALL_KEY', raising=False)
    # 主仓 .env 里有真 bot token；环境变量优先于 .env，置空＝测试里 notify() 永远是未配置。
    monkeypatch.setenv('NUTMEG_TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setenv('NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS', '')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
