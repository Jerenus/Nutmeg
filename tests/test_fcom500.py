"""Tests for the 500.com data collector (`nutmeg/data/fcom500.py`).

No live network: every test drives the parsers/provider with the recorded
gb2312-decoded fixtures in `tests/fixtures/fcom500/`. The HTTP client is
exercised through an injected `httpx.MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from nutmeg.data.fcom500 import Fcom500Client

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fcom500"


def _fixture_bytes(name: str) -> bytes:
    """Recorded fixtures are stored UTF-8; re-encode to gb2312 so the client's
    decode path is exercised exactly as it would be against the live site."""
    text = (_FIXTURE_DIR / name).read_text(encoding="utf-8")
    return text.encode("gb2312", errors="ignore")


def _mock_transport(routes: dict[str, bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, content=b"not found")
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Task A2 — Fcom500Client
# ---------------------------------------------------------------------------


def test_client_decodes_gb2312_to_utf8() -> None:
    transport = _mock_transport(
        {"/jczq/": _fixture_bytes("jczq-list.html")}
    )
    client = Fcom500Client(transport=transport)

    html = client.get("https://trade.500.com/jczq/")

    # A known Chinese string from the recorded list page must round-trip.
    assert "竞彩足球" in html
    assert "周日001" in html


def test_client_caches_repeated_get() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=_fixture_bytes("jczq-list.html"))

    client = Fcom500Client(transport=httpx.MockTransport(handler))

    first = client.get("https://trade.500.com/jczq/")
    second = client.get("https://trade.500.com/jczq/")

    assert first == second
    # Cached: the transport is hit exactly once for the same URL.
    assert len(calls) == 1


def test_client_missing_page_raises_httpx_error() -> None:
    client = Fcom500Client(transport=_mock_transport({}))

    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://odds.500.com/fenxi/ouzhi-999999.shtml")
