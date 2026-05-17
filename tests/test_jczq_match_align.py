from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_match_align import (
    MatchAligner,
    load_league_aliases,
    load_team_aliases,
)


def _jczq_match(
    *,
    match_no: str = "周六001",
    league: str = "英超",
    home: str = "阿森纳",
    away: str = "热刺",
    match_date: str = "2026-05-17",
    match_time: str = "22:00",
) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=match_no,
        match_date=match_date,
        match_time=match_time,
        league=league,
        home_team=home,
        away_team=away,
        status="售卖中",
        hot_direction="主胜",
        role="—",
        confidence_note="",
    )


def _af_fixture(
    *,
    fixture_id: str = "1379305",
    home: str = "Arsenal",
    away: str = "Tottenham",
    league_id: int = 39,
) -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        league_code="epl",
        provider_league_id=league_id,
        season=2025,
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team_id=42,
        away_team_id=47,
        home_team=home,
        away_team=away,
        source="api-football",
        status=FixtureStatus.SCHEDULED,
    )


def test_load_aliases_seed_values() -> None:
    leagues = load_league_aliases()
    assert leagues["英超"] == 39
    assert leagues["德甲"] == 78
    assert leagues["法甲"] == 61

    teams = load_team_aliases()
    assert teams["英超"]["阿森纳"] == "Arsenal"
    assert teams["西甲"]["皇马"] == "Real Madrid"


class _FakeFixtureProvider:
    """Records (league_id, date) calls; returns canned fixtures, no network."""

    def __init__(self, fixtures_by_query: dict[tuple[int, str], list[Fixture]]) -> None:
        self._fixtures_by_query = fixtures_by_query
        self.calls: list[tuple[int, str]] = []

    def fixtures_for(self, *, league_id: int, date: str) -> list[Fixture]:
        self.calls.append((league_id, date))
        return self._fixtures_by_query.get((league_id, date), [])


def test_aligns_jczq_match_to_api_football_fixture() -> None:
    fixture = _af_fixture()
    provider = _FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(_jczq_match())

    assert result.matched is True
    assert result.fixture_id == "1379305"
    assert result.fixture is fixture
    assert result.match_no == "周六001"
    assert result.reason is None
    assert provider.calls == [(39, "2026-05-17")]


def test_late_night_match_queried_by_utc_date_not_beijing_date() -> None:
    """A JCZQ '周日' match kicking off 00:00 Beijing on 2026-05-18 actually
    plays at 2026-05-17 16:00 UTC — API-Football files it under 2026-05-17.
    Aligning by the raw Beijing match_date queries the wrong day and misses.
    """
    fixture = _af_fixture()
    provider = _FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(
        _jczq_match(match_date="2026-05-18", match_time="00:00:00")
    )

    assert result.matched is True
    assert result.fixture_id == "1379305"
    assert provider.calls == [(39, "2026-05-17")]


def test_unmapped_league_yields_no_signal_and_logs_reason() -> None:
    provider = _FakeFixtureProvider({})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(_jczq_match(league="火星联赛"))

    assert result.matched is False
    assert result.fixture_id is None
    assert "联赛" in (result.reason or "")
    # An unmapped league must never trigger a fixtures query.
    assert provider.calls == []


def test_unmapped_team_yields_no_signal_never_guesses() -> None:
    fixture = _af_fixture()
    provider = _FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(_jczq_match(home="未知队"))

    assert result.matched is False
    assert result.fixture_id is None
    assert "球队" in (result.reason or "")


def test_no_fixture_on_date_yields_no_signal() -> None:
    provider = _FakeFixtureProvider({(39, "2026-05-17"): []})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(_jczq_match())

    assert result.matched is False
    assert result.fixture_id is None
    assert result.reason is not None


def test_alignment_tolerates_swapped_home_away() -> None:
    # Sporttery occasionally lists the nominal away team as home; the aligner
    # should still match on the team pair and flag the orientation.
    fixture = _af_fixture(home="Tottenham", away="Arsenal")
    provider = _FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    aligner = MatchAligner(fixture_provider=provider)

    result = aligner.align(_jczq_match())

    assert result.matched is True
    assert result.fixture_id == "1379305"
    assert result.orientation_swapped is True


def test_align_day_returns_one_result_per_match() -> None:
    fixture = _af_fixture()
    provider = _FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    aligner = MatchAligner(fixture_provider=provider)

    matches = [
        _jczq_match(match_no="周六001"),
        _jczq_match(match_no="周六002", home="未知队"),
    ]
    results = aligner.align_day(matches)

    assert len(results) == 2
    assert results[0].matched is True
    assert results[1].matched is False
    # Same league+date → fixture provider hit once (cached).
    assert provider.calls == [(39, "2026-05-17")]
