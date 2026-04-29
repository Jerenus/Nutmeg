from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nutmeg.services.psychology.sources.news_cache import NewsCache
from nutmeg.services.psychology.sources.zhilio_provider import ZhilioProvider


def test_search_news_uses_callable(tmp_path: Path) -> None:
    fake_call = MagicMock(return_value={"items": [{"title": "PSG bottle Bayern", "url": "u1"}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    result = provider.search_news(query="巴黎 拜仁", date="2026-04-29")
    assert result == [{"title": "PSG bottle Bayern", "url": "u1"}]
    fake_call.assert_called_once_with(query="巴黎 拜仁", limit=20)


def test_search_news_uses_cache_on_second_call(tmp_path: Path) -> None:
    fake_call = MagicMock(return_value={"items": [{"title": "x", "url": "u"}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    provider.search_news(query="q", date="2026-04-29")
    provider.search_news(query="q", date="2026-04-29")
    assert fake_call.call_count == 1


def test_search_news_swallows_callable_exception(tmp_path: Path) -> None:
    fake_call = MagicMock(side_effect=RuntimeError("MCP unreachable"))
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    assert provider.search_news(query="q", date="2026-04-29") == []


def test_hotlist_returns_list(tmp_path: Path) -> None:
    fake_hot = MagicMock(return_value={"items": [{"title": "Bayern back-3 reset", "rank": 1}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=MagicMock(), call_hotlist=fake_hot, cache=cache)
    assert provider.hotlist(date="2026-04-29") == [{"title": "Bayern back-3 reset", "rank": 1}]
