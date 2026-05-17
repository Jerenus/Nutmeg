from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.zucai import ZucaiIssue, ZucaiMatch
from nutmeg.services.jczq_match_align import MatchAligner
from nutmeg.services.value import ValueBoardService
from nutmeg.services.zucai_value_bridge import ZucaiValueBridge

# Reuse the value-service test doubles — they already build the four-market
# snapshot/odds fakes the value engine needs.
from tests.test_value_service import (
    FakeOddsService,
    FakeSnapshotService,
    _multi_market_odds,
    _snapshot,
)


def _zucai_match(
    *,
    match_no: int = 1,
    competition: str = "英超",
    home: str = "阿森纳",
    away: str = "热刺",
    match_date: str | None = "2026-05-17",
) -> ZucaiMatch:
    return ZucaiMatch(
        match_no=match_no,
        competition=competition,
        home_team=home,
        away_team=away,
        match_date=match_date,
    )


def _issue(matches: list[ZucaiMatch]) -> ZucaiIssue:
    return ZucaiIssue(
        issue_id="26074",
        game_type="sfc14",
        sale_stop="2026-05-17 20:30",
        matches=matches,
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


def _bridge_with(*, fixtures: list[Fixture]) -> ZucaiValueBridge:
    aligner = MatchAligner(
        fixture_provider=_FakeFixtureProvider({(39, "2026-05-17"): fixtures})
    )
    snapshots = {fx.fixture_id: _snapshot(fx) for fx in fixtures}
    odds = {fx.fixture_id: _multi_market_odds(fx) for fx in fixtures}
    value_service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService(snapshots),
        odds_service=FakeOddsService(odds),
    )
    return ZucaiValueBridge(aligner=aligner, value_service=value_service)


def test_bridge_produces_had_signal_for_aligned_match() -> None:
    bridge = _bridge_with(fixtures=[_af_fixture()])

    report = bridge.evaluate_issue(_issue([_zucai_match()]))

    assert len(report.matches) == 1
    entry = report.matches[0]
    assert entry.match_no == 1
    assert entry.aligned is True
    assert entry.fixture_id == "1379305"
    signal = entry.had_signal
    assert signal is not None
    # 1X2 pick code is one of 3/1/0 (home/draw/away).
    assert signal.pick in {"3", "1", "0"}
    assert signal.edge >= 0.03
    assert 0 < signal.model_probability < 1
    assert 0 < signal.market_probability < 1
    assert signal.best_odds > 1
    # Verdict is a short human-readable annotation.
    assert "模型" in signal.verdict
    assert "edge" in signal.verdict


def test_bridge_marks_unaligned_match_with_coverage_note() -> None:
    bridge = _bridge_with(fixtures=[_af_fixture()])

    report = bridge.evaluate_issue(_issue([_zucai_match(home="未知队")]))

    entry = report.matches[0]
    assert entry.aligned is False
    assert entry.fixture_id is None
    assert entry.had_signal is None
    assert entry.coverage_note is not None
    assert "球队" in entry.coverage_note


def test_bridge_handles_unknown_league_gracefully() -> None:
    bridge = _bridge_with(fixtures=[_af_fixture()])

    report = bridge.evaluate_issue(_issue([_zucai_match(competition="火星联赛")]))

    entry = report.matches[0]
    assert entry.aligned is False
    assert entry.had_signal is None
    assert entry.coverage_note is not None


def test_bridge_handles_missing_match_date() -> None:
    bridge = _bridge_with(fixtures=[_af_fixture()])

    report = bridge.evaluate_issue(_issue([_zucai_match(match_date=None)]))

    entry = report.matches[0]
    # No date → aligner cannot query fixtures → unaligned, but no crash.
    assert entry.aligned is False
    assert entry.had_signal is None
    assert entry.coverage_note is not None


def test_bridge_aligned_match_without_had_edge_has_no_signal() -> None:
    # An aligned fixture whose match_winner market yields no +edge outcome
    # produces an aligned entry with had_signal None and a coverage note.
    from dataclasses import replace

    from nutmeg.domain.odds import MarketOddsSnapshot, OutcomeOddsSnapshot

    fixture = _af_fixture()
    aligner = MatchAligner(
        fixture_provider=_FakeFixtureProvider({(39, "2026-05-17"): [fixture]})
    )
    odds = _multi_market_odds(fixture)
    markets = dict(odds.markets)
    # match_winner available but every outcome fairly priced near the model →
    # no outcome clears the min_edge bar.
    markets["match_winner"] = MarketOddsSnapshot(
        market_key="match_winner",
        market_name="Match Winner",
        status="available",
        line=None,
        source_market_ids=[1],
        outcomes=[
            OutcomeOddsSnapshot(
                outcome_key="home",
                outcome_name="Home",
                bookmaker_quotes=[],
                best_odds=1.01,
                average_odds=1.01,
                fair_probability=0.99,
                fair_odds=1.01,
                bookmaker_count=2,
            ),
            OutcomeOddsSnapshot(
                outcome_key="draw",
                outcome_name="Draw",
                bookmaker_quotes=[],
                best_odds=1.01,
                average_odds=1.01,
                fair_probability=0.99,
                fair_odds=1.01,
                bookmaker_count=2,
            ),
            OutcomeOddsSnapshot(
                outcome_key="away",
                outcome_name="Away",
                bookmaker_quotes=[],
                best_odds=1.01,
                average_odds=1.01,
                fair_probability=0.99,
                fair_odds=1.01,
                bookmaker_count=2,
            ),
        ],
    )
    odds = replace(odds, markets=markets)
    value_service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: odds}),
    )
    bridge = ZucaiValueBridge(aligner=aligner, value_service=value_service)

    report = bridge.evaluate_issue(_issue([_zucai_match()]))

    entry = report.matches[0]
    assert entry.aligned is True
    assert entry.had_signal is None
    assert entry.coverage_note is not None


def test_bridge_report_coverage_metrics() -> None:
    fixture = _af_fixture()
    matches = [
        _zucai_match(match_no=1),
        _zucai_match(match_no=2, home="未知队"),
        _zucai_match(match_no=3, competition="火星联赛"),
    ]
    bridge = _bridge_with(fixtures=[fixture])

    report = bridge.evaluate_issue(_issue(matches))

    assert [m.match_no for m in report.matches] == [1, 2, 3]
    assert report.matches[0].aligned is True
    assert report.matches[1].aligned is False
    assert report.matches[2].aligned is False
    assert report.aligned_count == 1
    assert report.coverage_pct == round(1 / 3, 4)
    assert report.signal_for(1) is report.matches[0].had_signal
    assert report.signal_for(99) is None
