from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.sources.news_cache import NewsCache

CallSearchNews = Callable[..., dict[str, Any]]
CallHotlist = Callable[..., dict[str, Any]]


@dataclass(slots=True)
class ZhilioProvider:
    """Thin wrapper around zhilio MCP read tools."""

    call_search_news: CallSearchNews
    call_hotlist: CallHotlist
    cache: NewsCache

    def search_news(self, *, query: str, date: str, limit: int = 20) -> list[dict[str, Any]]:
        cached = self.cache.get(date=date, key=f"news:{query}:{limit}")
        if cached is not None:
            return cached
        try:
            response = self.call_search_news(query=query, limit=limit)
        except Exception:  # noqa: BLE001 - external IO degradation path
            return []
        items = list(response.get("items") or [])
        self.cache.put(date=date, key=f"news:{query}:{limit}", payload=items)
        return items

    def hotlist(self, *, date: str) -> list[dict[str, Any]]:
        cached = self.cache.get(date=date, key="hotlist")
        if cached is not None:
            return cached
        try:
            response = self.call_hotlist()
        except Exception:  # noqa: BLE001 - external IO degradation path
            return []
        items = list(response.get("items") or [])
        self.cache.put(date=date, key="hotlist", payload=items)
        return items
