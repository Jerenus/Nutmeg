"""Decision 测试套件环境隔离：每个测试前后清 settings 缓存，免得 env 改动串到下一个测试。"""

import pytest

import nutmeg.config.settings as settings_module


@pytest.fixture(autouse=True)
def _fresh_settings():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()
