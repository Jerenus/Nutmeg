from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.sources.news_cache import NewsCache

RssFetcher = Callable[[str], dict[str, Any]]


def _matches(entry: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    q = query.lower()
    haystack = " ".join([str(entry.get("title", "")), str(entry.get("summary", ""))]).lower()
    return q in haystack


@dataclass(slots=True)
class RssProvider:
    feeds: list[str]
    fetcher: RssFetcher
    cache: NewsCache

    def fetch(self, *, date: str, query: str | None) -> list[dict[str, Any]]:
        cache_key = f"rss:{','.join(self.feeds)}:{query or ''}"
        cached = self.cache.get(date=date, key=cache_key)
        if cached is not None:
            return cached
        merged: list[dict[str, Any]] = []
        for feed_url in self.feeds:
            try:
                payload = self.fetcher(feed_url)
            except Exception:  # noqa: BLE001 - external IO degradation path
                continue
            for entry in payload.get("entries") or []:
                if _matches(entry, query):
                    merged.append(
                        {
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "summary": entry.get("summary", ""),
                            "feed": feed_url,
                        }
                    )
        self.cache.put(date=date, key=cache_key, payload=merged)
        return merged
