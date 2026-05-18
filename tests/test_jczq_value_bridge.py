from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_match_align import MatchAligner
from nutmeg.services.jczq_value_bridge import JczqValueBridge
from nutmeg.services.value import ValueBoardService

# Reuse the value-service test doubles — they already build the four-market
# snapshot/odds fakes the value engine needs.
from tests.test_value_service import (
    FakeOddsService,
    FakeSnapshotService,
    _multi_market_odds,
    _snapshot,
)


def _jczq_match(
    *,
    match_no: str = "周六001",
    league: str = "英超",
    home: str = "阿森纳",
    away: str = "热刺",
    match_date: str = "2026-05-17",
) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=match_no,
        match_date=match_date,
        match_time="22:00",
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
) -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        league_code="epl",
        provider_league_id=39,
        season=2025,
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team_id=42,
        away_team_id=47,
        home_team=home,
        away_team=away,
        source="api-football",
        status=FixtureStatus.SCHEDULED,
    )


class _FakeFixtureProvider:
    def __init__(self, fixtures_by_query: dict[tuple[int, str], list[Fixture]]) -> None:
        self._fixtures_by_query = fixtures_by_query

    def fixtures_for(self, *, league_id: int, date: str) -> list[Fixture]:
        return self._fixtures_by_query.get((league_id, date), [])


def _bridge_with(
    *,
    matches: list[JczqDailyMatch],
    fixtures: list[Fixture],
) -> JczqValueBridge:
    aligner = MatchAligner(
        fixture_provider=_FakeFixtureProvider(
            {(39, "2026-05-17"): fixtures}
        )
    )
    snapshots = {fx.fixture_id: _snapshot(fx) for fx in fixtures}
    odds = {fx.fixture_id: _multi_market_odds(fx) for fx in fixtures}
    value_service = ValueBoardService(
        # build_board takes a FixtureRepository; the bridge supplies a
        # per-fixture-list shim, so this constructor repo is never used.
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService(snapshots),
        odds_service=FakeOddsService(odds),
    )
    return JczqValueBridge(aligner=aligner, value_service=value_service)


def test_bridge_produces_conflict_points_for_aligned_match() -> None:
    fixture = _af_fixture()
    bridge = _bridge_with(matches=[_jczq_match()], fixtures=[fixture])

    report = bridge.evaluate_day([_jczq_match()])

    assert len(report.matches) == 1
    entry = report.matches[0]
    assert entry.match_no == "周六001"
    assert entry.aligned is True
    assert entry.fixture_id == "1379305"
    assert entry.conflicts, "expected at least one value conflict candidate"
    # Conflicts span the four Phase 3a markets surfaced by _multi_market_odds.
    markets = {c.market_key for c in entry.conflicts}
    assert "match_winner" in markets
    # Each conflict carries the data the brief needs side by side.
    top = entry.conflicts[0]
    assert top.edge >= 0.03
    assert top.best_odds > 1
    assert 0 < top.model_probability < 1
    assert 0 < top.market_probability < 1


def test_bridge_marks_unaligned_match_with_coverage_note() -> None:
    bridge = _bridge_with(
        matches=[_jczq_match(home="未知队")], fixtures=[_af_fixture()]
    )

    report = bridge.evaluate_day([_jczq_match(home="未知队")])

    entry = report.matches[0]
    assert entry.aligned is False
    assert entry.fixture_id is None
    assert entry.conflicts == []
    assert entry.coverage_note is not None
    assert "球队" in entry.coverage_note


def test_bridge_conflicts_sorted_by_edge_descending() -> None:
    fixture = _af_fixture()
    bridge = _bridge_with(matches=[_jczq_match()], fixtures=[fixture])

    report = bridge.evaluate_day([_jczq_match()])
    edges = [c.edge for c in report.matches[0].conflicts]

    assert edges == sorted(edges, reverse=True)


def test_bridge_remaps_match_winner_conflicts_when_orientation_swapped() -> None:
    # API-Football lists Tottenham as home, but JCZQ lists Arsenal as home.
    # A model edge on API "home" therefore means JCZQ "away"/负.
    fixture = _af_fixture(home="Tottenham", away="Arsenal")
    match = _jczq_match(home="阿森纳", away="热刺")
    bridge = _bridge_with(matches=[match], fixtures=[fixture])

    report = bridge.evaluate_day([match])

    entry = report.matches[0]
    assert entry.orientation_swapped is True
    had_conflict = next(c for c in entry.conflicts if c.market_key == "match_winner")
    assert had_conflict.outcome_key == "away"
    assert had_conflict.outcome_name == "Away"
    assert had_conflict.home_team == "阿森纳"
    assert had_conflict.away_team == "热刺"


def test_bridge_remaps_handicap_and_score_conflicts_when_orientation_swapped() -> None:
    fixture = _af_fixture(home="Tottenham", away="Arsenal")
    match = _jczq_match(home="阿森纳", away="热刺")
    bridge = _bridge_with(matches=[match], fixtures=[fixture])

    report = bridge.evaluate_day([match])

    entry = report.matches[0]
    hhad_conflict = next(
        c for c in entry.conflicts if c.market_key.startswith("handicap_home_")
    )
    assert hhad_conflict.market_key == "handicap_home_plus_1"
    assert hhad_conflict.outcome_key == "away"
    assert hhad_conflict.outcome_name == "Away"

    score_conflict = next(c for c in entry.conflicts if c.outcome_key == "score_0_2")
    assert score_conflict.market_key == "correct_score"
    assert score_conflict.outcome_name == "0:2"


def test_bridge_handles_multiple_matches_some_unaligned() -> None:
    fixture = _af_fixture()
    matches = [
        _jczq_match(match_no="周六001"),
        _jczq_match(match_no="周六002", home="未知队"),
        _jczq_match(match_no="周六003", league="火星联赛"),
    ]
    bridge = _bridge_with(matches=matches, fixtures=[fixture])

    report = bridge.evaluate_day(matches)

    assert [m.match_no for m in report.matches] == ["周六001", "周六002", "周六003"]
    assert report.matches[0].aligned is True
    assert report.matches[1].aligned is False
    assert report.matches[2].aligned is False
    assert report.aligned_count == 1
    assert report.coverage_pct == round(1 / 3, 4)


def test_bridge_skips_value_eval_when_no_match_winner_market() -> None:
    # An aligned fixture whose odds lack a usable match_winner market yields an
    # aligned entry with no conflicts (the value engine skipped it).
    from dataclasses import replace

    from nutmeg.domain.odds import MarketOddsSnapshot

    fixture = _af_fixture()
    aligner = MatchAligner(
        fixture_provider=_FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    )
    odds = _multi_market_odds(fixture)
    markets = dict(odds.markets)
    markets["match_winner"] = MarketOddsSnapshot(
        market_key="match_winner",
        market_name="Match Winner",
        status="unavailable",
        line=None,
        source_market_ids=[],
        outcomes=[],
    )
    odds = replace(odds, markets=markets)
    value_service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: odds}),
    )
    bridge = JczqValueBridge(aligner=aligner, value_service=value_service)

    report = bridge.evaluate_day([_jczq_match()])

    entry = report.matches[0]
    assert entry.aligned is True
    assert entry.conflicts == []
    assert entry.coverage_note is not None
