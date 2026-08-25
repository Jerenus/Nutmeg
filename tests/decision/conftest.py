"""Decision 测试套件环境隔离。

生产 `.env` 自 cutover §2.3 起携带 ``NUTMEG_ONTOLOGY_V2=1``，而 env var 优先级
盖过 env_file——不钉住的话，v1 路径测试会在 main worktree 被静默路由进 kernel
adapter（无 `.env` 的 CI / worktree 则全绿）。默认显式 ``=0``（而非 delenv）；
需要 v2 路径的测试自行 ``setenv("NUTMEG_ONTOLOGY_V2", "1")`` 并清 settings 缓存。
"""

import pytest

import nutmeg.config.settings as settings_module


@pytest.fixture(autouse=True)
def _pin_ontology_flag_off(monkeypatch):
    monkeypatch.setenv("NUTMEG_ONTOLOGY_V2", "0")
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()
