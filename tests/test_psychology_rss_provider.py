from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nutmeg.services.psychology.io import NewsCache, RssProvider


def test_fetches_each_feed_and_merges(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(
        side_effect=[
            {"entries": [{"title": "PSG injury list", "link": "https://a/1", "summary": "..."}]},
            {
                "entries": [
                    {"title": "Bayern compact 3-back", "link": "https://b/1", "summary": "..."}
                ]
            },
        ]
    )
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(
        feeds=["https://a/feed.xml", "https://b/feed.xml"], fetcher=fake_fetcher, cache=cache
    )
    items = provider.fetch(date="2026-04-29", query=None)
    assert len(items) == 2
    assert items[0]["link"] == "https://a/1"
    assert items[1]["link"] == "https://b/1"


def test_filters_by_query_when_supplied(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(
        side_effect=[
            {
                "entries": [
                    {"title": "Bayern reset", "link": "https://b/1", "summary": "Kompany 3-back"},
                    {"title": "Random news", "link": "https://b/2", "summary": "unrelated"},
                ]
            }
        ]
    )
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://b/feed.xml"], fetcher=fake_fetcher, cache=cache)
    items = provider.fetch(date="2026-04-29", query="bayern")
    assert len(items) == 1
    assert items[0]["link"] == "https://b/1"


def test_single_feed_failure_does_not_block(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(
        side_effect=[
            RuntimeError("404"),
            {"entries": [{"title": "ok", "link": "https://b/1", "summary": ""}]},
        ]
    )
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://a", "https://b"], fetcher=fake_fetcher, cache=cache)
    items = provider.fetch(date="2026-04-29", query=None)
    assert len(items) == 1
    assert items[0]["link"] == "https://b/1"


def test_uses_cache(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(return_value={"entries": [{"title": "t", "link": "l", "summary": ""}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://a"], fetcher=fake_fetcher, cache=cache)
    provider.fetch(date="2026-04-29", query=None)
    provider.fetch(date="2026-04-29", query=None)
    assert fake_fetcher.call_count == 1
