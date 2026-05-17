"""Tests for the 500.com data collector (`nutmeg/data/fcom500.py`).

No live network: every test drives the parsers/provider with the recorded
gb2312-decoded fixtures in `tests/fixtures/fcom500/`. The HTTP client is
exercised through an injected `httpx.MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from nutmeg.data.fcom500 import (
    Fcom500Client,
    Fcom500OddsProvider,
    parse_correct_score,
    parse_european_1x2,
    parse_handicap,
    parse_jczq_list,
    parse_total_goals,
)

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


def test_parse_european_1x2_returns_devigged_probabilities() -> None:
    html = (_FIXTURE_DIR / "ouzhi-1366371.html").read_text(encoding="utf-8")

    market = parse_european_1x2(html)

    assert market is not None
    assert market.independent is True
    assert set(market.odds) == {"home", "draw", "away"}
    # Average over ~14 international books — finite, > evens-ish.
    assert all(o > 1.0 for o in market.odds.values())
    # De-vigged fair probabilities sum to 1 and exclude the bookmaker margin.
    assert set(market.fair_probability) == {"home", "draw", "away"}
    assert abs(sum(market.fair_probability.values()) - 1.0) < 1e-6
    # 大阪樱花 (home) was the strong favourite on the 竞彩 line (spf 1.39).
    assert market.fair_probability["home"] > market.fair_probability["away"]
    assert market.bookmaker_count >= 5


def test_parse_european_1x2_second_match() -> None:
    html = (_FIXTURE_DIR / "ouzhi-1373152.html").read_text(encoding="utf-8")

    market = parse_european_1x2(html)

    assert market is not None
    assert abs(sum(market.fair_probability.values()) - 1.0) < 1e-6


def test_parse_european_1x2_returns_none_on_empty_page() -> None:
    assert parse_european_1x2("<html><body>no table</body></html>") is None


# ---------------------------------------------------------------------------
# Task A5 — parse 让球 (handicap)
# ---------------------------------------------------------------------------


def test_parse_handicap_returns_line_and_devigged_probabilities() -> None:
    html = (_FIXTURE_DIR / "yazhi-1366371.html").read_text(encoding="utf-8")

    market = parse_handicap(html)

    assert market is not None
    assert market.independent is True
    assert set(market.odds) == {"handicap_home", "handicap_away"}
    assert market.line is not None
    # Asian-handicap odds sit around ~0.9 (the margin is split, not added) —
    # the fair probabilities, not the raw odds, are the conflict signal.
    assert all(o > 0 for o in market.odds.values())
    assert abs(sum(market.fair_probability.values()) - 1.0) < 1e-6
    assert market.bookmaker_count >= 5


def test_parse_handicap_returns_none_on_empty_page() -> None:
    assert parse_handicap("<html><body>nothing</body></html>") is None


# ---------------------------------------------------------------------------
# Task A6 — parse 总进球 + 比分
# ---------------------------------------------------------------------------


def test_parse_total_goals_returns_exact_count_buckets() -> None:
    html = (_FIXTURE_DIR / "jqs-1366371.html").read_text(encoding="utf-8")

    market = parse_total_goals(html)

    assert market is not None
    # Only 体彩-derived rows exist on the jqs page — flagged weak signal.
    assert market.independent is False
    # Buckets match the model vocabulary total_0..total_6, total_7_plus.
    assert "total_0" in market.odds
    assert "total_7_plus" in market.odds
    assert abs(sum(market.fair_probability.values()) - 1.0) < 1e-6


def test_parse_total_goals_returns_none_on_empty_page() -> None:
    assert parse_total_goals("<html><body>no table</body></html>") is None


def test_parse_correct_score_is_none_js_rendered() -> None:
    # The 比分 page's odds are JS-loaded — the static pub_table is header-only.
    html = (_FIXTURE_DIR / "bifen-1366371.html").read_text(encoding="utf-8")
    assert parse_correct_score(html) is None


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


def test_provider_collects_per_match_fixture_and_odds() -> None:
    client = Fcom500Client(transport=_mock_transport(_provider_routes()))
    provider = Fcom500OddsProvider(client=client)

    collected = provider.collect("2026-05-17")

    # Keyed by 竞彩 number.
    assert "周日001" in collected
    entry = collected["周日001"]
    # Synthetic fixture: id fcom500:周日NNN, teams/league/date from 500.com.
    assert entry.fixture.fixture_id == "fcom500:周日001"
    assert entry.fixture.home_team == "大阪樱花"
    assert entry.fixture.source == "fcom500"
    # The conflict engine focuses on 胜平负 only — the OddsSnapshot carries
    # ONLY the match_winner market.
    markets = entry.odds.markets
    assert set(markets) == {"match_winner"}
    assert markets["match_winner"].status == "available"
    mw = {o.outcome_key: o for o in markets["match_winner"].outcomes}
    assert set(mw) == {"home", "draw", "away"}
    assert all(o.fair_probability is not None for o in mw.values())
    # total_goals (体彩-derived, circular) and handicap (2-way 亚盘, no
    # key-match) are dropped from the conflict-engine snapshot.
    assert "total_goals" not in markets
    assert "handicap" not in markets
    # correct_score is JS-rendered → never collected (§4 verdict).
    assert "correct_score" not in markets


def test_provider_keys_every_parseable_match() -> None:
    client = Fcom500Client(transport=_mock_transport(_provider_routes()))
    provider = Fcom500OddsProvider(client=client)

    collected = provider.collect("2026-05-17")

    # 38 matches in the list; only the 2 recorded ones have sub-pages routed —
    # the rest 404 and degrade to a zero-market entry, never crashing.
    assert len(collected) == 38
    assert collected["周日003"].market_count == 0


def test_provider_degrades_when_market_page_missing() -> None:
    # Route the list + only 周日001's 欧赔 — every other sub-page 404s.
    routes = {
        "/jczq/": _fixture_bytes("jczq-list.html"),
        "/fenxi/ouzhi-1366371.shtml": _fixture_bytes("ouzhi-1366371.html"),
    }
    client = Fcom500Client(transport=_mock_transport(routes))
    provider = Fcom500OddsProvider(client=client)

    collected = provider.collect("2026-05-17")

    entry = collected["周日001"]
    # The missing sub-pages degrade those markets — match_winner still present.
    assert "match_winner" in entry.odds.markets
    assert "total_goals" not in entry.odds.markets
    assert "handicap" not in entry.odds.markets


def test_provider_returns_empty_when_list_fetch_fails() -> None:
    client = Fcom500Client(transport=_mock_transport({}))
    provider = Fcom500OddsProvider(client=client)

    # The 竞彩 list itself 404s → empty result, no crash.
    assert provider.collect("2026-05-17") == {}


# ---------------------------------------------------------------------------
# Task A8 — wire into the conflict engine
# ---------------------------------------------------------------------------


def test_fcom500_odds_service_serves_collected_snapshots() -> None:
    """The OddsService seam: a collected snapshot is served by fixture id,
    keyed fcom500:周日NNN — the conflict engine consumes it unchanged."""
    from nutmeg.data.fcom500 import Fcom500OddsService

    client = Fcom500Client(transport=_mock_transport(_provider_routes()))
    collected = Fcom500OddsProvider(client=client).collect("2026-05-17")
    odds_service = Fcom500OddsService(collected)

    snapshot = odds_service.build_snapshot("fcom500:周日001", persist_history=False)

    assert snapshot.fixture.fixture_id == "fcom500:周日001"
    assert "match_winner" in snapshot.markets


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


def test_fcom500_value_bridge_keys_conflicts_by_jczq_number() -> None:
    """The 500.com bridge: evaluate_day produces a JczqValueReport keyed by
    竞彩 number with NO MatchAligner / API-Football call.

    De-masked: the snapshot fake is keyed by fixture id and the fixture
    repository captures what the bridge upserts — so the model-side identity
    translation (Chinese→English + catalog league code) is exercised, not
    bypassed. The real ``FixtureSnapshotService`` re-fetches the fixture from
    the repo by id and reads its team names / league code; this test asserts
    the bridge upserts an English-identity fixture for it to consume.
    """
    from nutmeg.data.fcom500 import Fcom500ValueBridge
    from nutmeg.services.value import ValueBoardService
    from tests.test_value_service import (
        FakeFixtureRepository,
        FakeSnapshotService,
        _snapshot,
    )

    client = Fcom500Client(transport=_mock_transport(_alias_covered_routes()))
    provider = Fcom500OddsProvider(client=client)

    repo = FakeFixtureRepository([])

    # The snapshot fake is keyed by fixture id: the bridge must build a
    # model-side fixture under fcom500:周日005 for the snapshot to resolve.
    from datetime import UTC, datetime

    from nutmeg.domain.fixtures import Fixture, FixtureStatus

    model_fixture = Fixture(
        fixture_id="fcom500:周日005",
        league_code="serie-a",
        provider_league_id=135,
        season=2025,
        kickoff_at=datetime(2026, 5, 17, 2, 45, tzinfo=UTC),
        home_team_id=None,
        away_team_id=None,
        home_team="Genoa",
        away_team="AC Milan",
        source="fcom500",
        status=FixtureStatus.SCHEDULED,
    )
    snapshots = {"fcom500:周日005": _snapshot(model_fixture)}

    def value_service_factory() -> ValueBoardService:
        return ValueBoardService(
            fixture_repository=repo,
            snapshot_service=FakeSnapshotService(snapshots),
            odds_service=None,  # type: ignore[arg-type] — replaced per collect
        )

    bridge = Fcom500ValueBridge(
        provider=provider,
        run_date="2026-05-17",
        value_service_factory=value_service_factory,
    )

    report = bridge.evaluate_day([_genoa_milan_match()])

    # One match in, one entry out, keyed by the 竞彩 number.
    assert len(report.matches) == 1
    entry = report.matches[0]
    assert entry.match_no == "周日005"
    assert entry.aligned is True
    assert entry.fixture_id == "fcom500:周日005"
    # The bridge upserted a MODEL-side fixture: English team names + a catalog
    # league code — not the Chinese 500.com synthetic identity. This is the
    # identity the real FixtureSnapshotService re-fetches and reads.
    assert len(repo.upserted) == 1
    upserted = repo.upserted[0]
    assert upserted.fixture_id == "fcom500:周日005"
    assert upserted.home_team == "Genoa"
    assert upserted.away_team == "AC Milan"
    assert upserted.league_code == "serie-a"


def test_fcom500_value_bridge_aligns_without_model_identity() -> None:
    """A JCZQ match with 500.com odds but no alias coverage degrades honestly:
    aligned to the 500.com odds, but no model identity → no conflicts, with a
    coverage note (never a crash, never a fabricated conflict)."""
    from nutmeg.data.fcom500 import Fcom500ValueBridge
    from nutmeg.domain.jczq_daily import JczqDailyMatch
    from nutmeg.services.value import ValueBoardService
    from tests.test_value_service import FakeFixtureRepository, FakeSnapshotService

    client = Fcom500Client(transport=_mock_transport(_provider_routes()))
    provider = Fcom500OddsProvider(client=client)

    def value_service_factory() -> ValueBoardService:
        return ValueBoardService(
            fixture_repository=FakeFixtureRepository([]),
            snapshot_service=FakeSnapshotService({}),
            odds_service=None,  # type: ignore[arg-type]
        )

    bridge = Fcom500ValueBridge(
        provider=provider,
        run_date="2026-05-17",
        value_service_factory=value_service_factory,
    )

    # 周日001 is 日职 — recorded by 500.com but absent from the team-alias
    # tables, so the model side has no identity for it.
    matches = [
        JczqDailyMatch(
            match_no="周日001",
            match_date="2026-05-17",
            match_time="14:00",
            league="日职",
            home_team="大阪樱花",
            away_team="名古屋鲸八",
            status="Selling",
            hot_direction="",
            role="",
            confidence_note="",
        ),
    ]

    report = bridge.evaluate_day(matches)

    assert len(report.matches) == 1
    entry = report.matches[0]
    assert entry.match_no == "周日001"
    # Aligned to 500.com odds, but honestly no conflicts and a coverage note.
    assert entry.aligned is True
    assert entry.conflicts == []
    assert entry.coverage_note is not None
    assert "别名表" in entry.coverage_note


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


def test_model_identity_translates_chinese_teams_and_league() -> None:
    """A JCZQ match in an alias-covered league yields a model-side Fixture with
    English team names + a catalog league code, keeping fcom500:周日NNN as id."""
    from nutmeg.data.fcom500 import build_model_identity

    match = _jczq_match(
        match_no="周日010",
        league="英超",
        home_team="曼联",
        away_team="纽卡斯尔",
    )

    fixture = build_model_identity(match, run_date="2026-05-17")

    assert fixture is not None
    # Chinese → English via load_team_aliases()['英超'].
    assert fixture.home_team == "Manchester United"
    assert fixture.away_team == "Newcastle"
    # League → catalog code so FixtureSnapshotService.get_league() resolves.
    assert fixture.league_code == "epl"
    # The id stays the 竞彩-keyed synthetic id so Fcom500OddsService matches.
    assert fixture.fixture_id == "fcom500:周日010"


def test_model_identity_degrades_when_league_not_in_alias_table() -> None:
    """A league absent from the alias tables → no model identity (None),
    never a crash. 500.com-path model coverage = alias-table coverage."""
    from nutmeg.data.fcom500 import build_model_identity

    match = _jczq_match(
        match_no="周日001",
        league="日职",  # 日职 has no team-alias table
        home_team="大阪樱花",
        away_team="名古屋鲸八",
    )

    assert build_model_identity(match, run_date="2026-05-17") is None


def test_model_identity_degrades_when_team_not_in_alias_table() -> None:
    """A team missing from its league's alias table → no model identity."""
    from nutmeg.data.fcom500 import build_model_identity

    match = _jczq_match(
        match_no="周日011",
        league="英超",
        home_team="曼联",
        away_team="不存在的球队",
    )

    assert build_model_identity(match, run_date="2026-05-17") is None


def test_fcom500_value_bridge_marks_unmatched_jczq_match() -> None:
    """A JCZQ match absent from the 500.com collection degrades honestly."""
    from nutmeg.data.fcom500 import Fcom500ValueBridge
    from nutmeg.domain.jczq_daily import JczqDailyMatch
    from nutmeg.services.value import ValueBoardService
    from tests.test_value_service import FakeSnapshotService

    client = Fcom500Client(transport=_mock_transport({"/jczq/": _fixture_bytes("jczq-list.html")}))
    provider = Fcom500OddsProvider(client=client)

    def value_service_factory() -> ValueBoardService:
        return ValueBoardService(
            fixture_repository=None,  # type: ignore[arg-type]
            snapshot_service=FakeSnapshotService({}),
            odds_service=None,  # type: ignore[arg-type]
        )

    bridge = Fcom500ValueBridge(
        provider=provider,
        run_date="2026-05-17",
        value_service_factory=value_service_factory,
    )

    matches = [
        JczqDailyMatch(
            match_no="周三999",
            match_date="2026-05-17",
            match_time="14:00",
            league="未知",
            home_team="X",
            away_team="Y",
            status="Selling",
            hot_direction="",
            role="",
            confidence_note="",
        ),
    ]

    report = bridge.evaluate_day(matches)

    assert len(report.matches) == 1
    assert report.matches[0].aligned is False
    assert report.matches[0].coverage_note is not None
