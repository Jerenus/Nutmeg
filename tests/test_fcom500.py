"""Tests for the 500.com data collector (`nutmeg/data/fcom500.py`).

No live network: every test drives the parsers/provider with the recorded
gb2312-decoded fixtures in `tests/fixtures/fcom500/`. The HTTP client is
exercised through an injected `httpx.MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from nutmeg.data.fcom500 import Fcom500Client, parse_jczq_list

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


def _list_html() -> str:
    return (_FIXTURE_DIR / "jczq-list.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task A3 — parse the 竞彩 match list
# ---------------------------------------------------------------------------


def test_parse_jczq_list_returns_one_record_per_match() -> None:
    matches = parse_jczq_list(_list_html())

    # The recorded 2026-05-17 list page carries 38 matches.
    assert len(matches) == 38
    # Each carries the 竞彩号↔fid join established from this single page.
    assert all(m.match_no and m.fid for m in matches)


def test_parse_jczq_list_known_matches() -> None:
    by_no = {m.match_no: m for m in parse_jczq_list(_list_html())}

    m1 = by_no["周日001"]
    assert m1.fid == "1366371"
    assert m1.home_team == "大阪樱花"
    assert m1.away_team == "名古屋鲸八"
    assert m1.league_short == "日职"
    assert m1.kickoff.startswith("05-17")

    m2 = by_no["周日002"]
    assert m2.fid == "1373152"
    assert m2.home_team == "全北现代"
    assert m2.away_team == "金泉尚武"


# ---------------------------------------------------------------------------
# Task A4 — parse 欧赔 (1X2 international odds)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task A5 — parse 让球 (handicap)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task A6 — parse 总进球 + 比分
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task A7 — Fcom500OddsProvider
# ---------------------------------------------------------------------------


def _provider_routes() -> dict[str, bytes]:
    """Route every recorded analysis sub-page for the two recorded matches."""
    routes = {"/jczq/": _fixture_bytes("jczq-list.html")}
    for fid in ("1366371", "1373152"):
        routes[f"/fenxi/ouzhi-{fid}.shtml"] = _fixture_bytes(f"ouzhi-{fid}.html")
        routes[f"/fenxi/yazhi-{fid}.shtml"] = _fixture_bytes(f"yazhi-{fid}.html")
        routes[f"/fenxi/jqs-{fid}.shtml"] = _fixture_bytes(f"jqs-{fid}.html")
        routes[f"/fenxi/bifen-{fid}.shtml"] = _fixture_bytes(f"bifen-{fid}.html")
    return routes


# ---------------------------------------------------------------------------
# Task A8 — wire into the conflict engine
# ---------------------------------------------------------------------------


# 周日005 (热那亚 vs AC米兰, 意甲) is fully covered by the alias tables. The
# recorded list page carries it; route its 欧赔 page to the recorded ouzhi
# table so the conflict engine has a match_winner market to price.
_FCOM500_005_FID = "1199712"


def _alias_covered_routes() -> dict[str, bytes]:
    """List page + a 欧赔 page for 周日005 (an alias-covered 意甲 match)."""
    return {
        "/jczq/": _fixture_bytes("jczq-list.html"),
        f"/fenxi/ouzhi-{_FCOM500_005_FID}.shtml": _fixture_bytes(
            "ouzhi-1366371.html"
        ),
    }


def _genoa_milan_match():
    """The JCZQ 周日005 match — Chinese names, as the daily report carries it."""
    from nutmeg.domain.jczq_daily import JczqDailyMatch

    return JczqDailyMatch(
        match_no="周日005",
        match_date="2026-05-17",
        match_time="02:45",
        league="意甲",
        home_team="热那亚",
        away_team="AC米兰",
        status="Selling",
        hot_direction="",
        role="",
        confidence_note="",
    )


# ---------------------------------------------------------------------------
# Task 1 — model-side identity (Chinese → English + catalog league code)
# ---------------------------------------------------------------------------


def _jczq_match(
    *,
    match_no: str,
    league: str,
    home_team: str,
    away_team: str,
):
    from nutmeg.domain.jczq_daily import JczqDailyMatch

    return JczqDailyMatch(
        match_no=match_no,
        match_date="2026-05-17",
        match_time="14:00",
        league=league,
        home_team=home_team,
        away_team=away_team,
        status="Selling",
        hot_direction="",
        role="",
        confidence_note="",
    )


