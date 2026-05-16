from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nutmeg.services.psychology.io import NewsCache


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    assert cache.get(date="2026-04-29", key="psg-bay") is None


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    payload = [{"title": "Bayern feared", "url": "https://example.com/a"}]
    cache.put(date="2026-04-29", key="psg-bay", payload=payload)
    assert cache.get(date="2026-04-29", key="psg-bay") == payload


def test_cache_expires_after_24h(tmp_path: Path) -> None:
    cache = NewsCache(
        base_dir=tmp_path, now=lambda: datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    )
    cache.put(date="2026-04-29", key="psg-bay", payload=[{"x": 1}])
    cache_aged = NewsCache(
        base_dir=tmp_path, now=lambda: datetime(2026, 4, 30, 10, 1, tzinfo=timezone.utc)
    )
    assert cache_aged.get(date="2026-04-29", key="psg-bay") is None


def test_cache_key_isolation(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    cache.put(date="2026-04-29", key="a", payload=[{"x": 1}])
    cache.put(date="2026-04-29", key="b", payload=[{"y": 2}])
    assert cache.get(date="2026-04-29", key="a") == [{"x": 1}]
    assert cache.get(date="2026-04-29", key="b") == [{"y": 2}]
