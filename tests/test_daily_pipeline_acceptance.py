"""End-to-end acceptance test for the JCZQ daily pipeline (consolidation 补充 E).

This is the consolidation's validation capstone. It drives the FULL daily
pipeline — the diagram in the consolidation design §3 — composed from the
*real* wired services, and asserts the key output of every stage:

    数据 (JCZQ fixtures + 独立赔率)
      → 冲突点检测   ValueBoardService.build_board_for_fixtures
      → 桥接归组     JczqValueBridge.evaluate_day  (real MatchAligner)
      → 串关构造器   ParlayConstructor  (Rule O + 集中度上限)
      → brief 渲染   build_brief(value_bridge=...)  → 「冲突点」+「串关候选」节
      → 注金阶梯     ConflictStore / resolve_stake_phase  (OBSERVE→SMALL→…)

Only the network boundary is faked — the same in-memory doubles the existing
unit tests already use (``FakeSnapshotService`` / ``FakeOddsService`` /
``_multi_market_odds`` from ``test_value_service``; a per-(league,date)
``FixtureProvider`` shim). Every service *between* those seams runs its real
production code: the real ``MatchAligner`` resolving the shipped JCZQ league /
team alias tables, the real ``ValueBoardService`` Dixon-Coles pricing, the real
``JczqValueBridge``, the real ``ParlayConstructor``, the real ``build_brief``
markdown emitter, and the real ``ConflictStore``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.services.jczq_brief import build_brief
from nutmeg.services.jczq_conflict_bridge import record_conflict_signals
from nutmeg.services.jczq_conflict_store import ConflictStore, resolve_stake_phase
from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.services.jczq_match_align import MatchAligner
from nutmeg.services.jczq_parlay_constructor import ParlayConstructor
from nutmeg.services.jczq_value_bridge import JczqValueBridge
from nutmeg.services.value import ValueBoardService

# Reuse the value-service in-memory doubles: they already build the four-market
# odds/snapshot fakes the value engine needs, and the snapshot trend it carries
# makes the Dixon-Coles model favour the home side — a real edge to detect.
from tests.test_value_service import (
    FakeOddsService,
    FakeSnapshotService,
    _multi_market_odds,
    _snapshot,
)


# --- the day's data --------------------------------------------------------
#
# A JCZQ day of three 英超 matches. 英超 (→ league_id 39) and these team names
# are all in the shipped alias tables (jczq_league_aliases.json /
# jczq_team_aliases.json), so the REAL MatchAligner aligns them with no
# stubbing of the alias layer. Two are given API-Football fixtures with a real
# under-priced market (an alignable + priceable pair → a parlay needs ≥2); the
# third has no fixture so the pipeline's graceful-degradation path is exercised
# end to end too.

RUN_DATE = "2026-05-01"
MATCH_DATE = "2026-05-02"  # JCZQ payload's per-match date

_ALIGNED = [
    # (match_no, zh_home, zh_away, en_home, en_away, af_league_id)
    ("周五001", "阿森纳", "热刺", "Arsenal", "Tottenham", 39),
    ("周五002", "利物浦", "切尔西", "Liverpool", "Chelsea", 39),
]
_UNALIGNED = ("周五003", "曼联", "曼城")  # 英超, but no API-Football fixture


def _pool(**kwargs: object) -> dict:
    return dict(kwargs)


def _jczq_match_payload(num: str, home: str, away: str) -> dict:
    """One Sporttery-shaped JCZQ submatch (all five pools selling)."""
    return {
        "matchNumStr": num,
        "matchDate": MATCH_DATE,
        "matchTime": "03:00:00",
        "leagueAbbName": "英超",
        "homeTeamAbbName": home,
        "awayTeamAbbName": away,
        "matchStatus": "Selling",
        "poolList": [
            {"poolCode": code, "poolStatus": "Selling", "single": 1, "allUp": 1}
            for code in ("HAD", "HHAD", "TTG", "HAFU", "CRS")
        ],
        "had": _pool(
            h="2.05", d="3.30", a="3.55",
            updateDate="2026-04-30", updateTime="13:25:09",
        ),
        "hhad": _pool(
            h="1.95", d="3.60", a="2.95", goalLine="-1",
            updateDate="2026-04-30", updateTime="13:25:09",
        ),
        "ttg": _pool(
            s2="3.00", s3="3.45", s4="4.40",
            updateDate="2026-04-30", updateTime="13:25:14",
        ),
        "hafu": _pool(
            hh="1.76", dh="3.95", dd="8.25",
            updateDate="2026-04-30", updateTime="13:25:09",
        ),
        "crs": _pool(
            s02s00="7.25", s02s01="6.75", s01s01="9.00",
            updateDate="2026-04-30", updateTime="13:25:09",
        ),
    }


def _jczq_daily_payload() -> dict:
    """A full Sporttery JCZQ daily payload: three 英超 matches."""
    submatches = [
        _jczq_match_payload(num, home, away)
        for num, home, away, *_ in _ALIGNED
    ]
    submatches.append(_jczq_match_payload(*_UNALIGNED))
    return {
        "lastUpdateTime": "2026-04-30 18:10:23",
        "matchInfoList": [
            {"businessDate": RUN_DATE, "subMatchList": submatches}
        ],
    }


class _JczqProvider:
    """JCZQ calculator provider double — returns the canned daily payload."""

    source_api = "fake://jczq-daily-acceptance"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def fetch(self) -> dict:
        return _jczq_daily_payload()


def _af_fixture(fixture_id: str, home: str, away: str, league_id: int) -> Fixture:
    """An API-Football fixture for the value engine to price."""
    return Fixture(
        fixture_id=fixture_id,
        league_code="epl",
        provider_league_id=league_id,
        season=2025,
        kickoff_at=datetime(2026, 5, 2, 14, 0, tzinfo=UTC),
        home_team_id=hash(home) % 1000,
        away_team_id=hash(away) % 1000,
        home_team=home,
        away_team=away,
        source="api-football",
        status=FixtureStatus.SCHEDULED,
    )


class _FakeFixtureProvider:
    """The network seam for MatchAligner: (league_id, date) → fixtures.

    Keyed exactly like ``ApiFootballFixtureProvider`` so the *real*
    ``MatchAligner`` runs unchanged on top of it.
    """

    def __init__(self, fixtures_by_query: dict[tuple[int, str], list[Fixture]]):
        self._fixtures_by_query = fixtures_by_query

    def fixtures_for(self, *, league_id: int, date: str) -> list[Fixture]:
        return self._fixtures_by_query.get((league_id, date), [])


def _build_value_bridge() -> JczqValueBridge:
    """Compose the real value-engine pipeline behind faked network seams.

    real MatchAligner (shipped alias tables)
        + real ValueBoardService (Dixon-Coles pricing over faked odds/snapshots)
        → real JczqValueBridge
    """
    aligned_fixtures = [
        _af_fixture(f"fx-{num}", en_home, en_away, league_id)
        for num, _zh_home, _zh_away, en_home, en_away, league_id in _ALIGNED
    ]
    fixtures_by_query: dict[tuple[int, str], list[Fixture]] = {}
    for fx in aligned_fixtures:
        fixtures_by_query.setdefault(
            (fx.provider_league_id, MATCH_DATE), []
        ).append(fx)

    aligner = MatchAligner(
        fixture_provider=_FakeFixtureProvider(fixtures_by_query)
    )
    snapshots = {fx.fixture_id: _snapshot(fx) for fx in aligned_fixtures}
    odds = {fx.fixture_id: _multi_market_odds(fx) for fx in aligned_fixtures}
    value_service = ValueBoardService(
        # build_board_for_fixtures (the bridge entry point) never touches the
        # repository — it prices an explicit fixture list.
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService(snapshots),
        odds_service=FakeOddsService(odds),
    )
    return JczqValueBridge(aligner=aligner, value_service=value_service)


def _seed_jczq_day(output_dir: Path) -> list:
    """Run the REAL daily advisor → context.json on disk; return the matches.

    This is stage 1 (数据): the real ``JczqDailyAdvisorService`` parses the
    Sporttery payload into ``JczqDailyMatch`` objects and persists the day's
    ``context.json`` that ``build_brief(replay_date=...)`` later replays.
    """
    report = JczqDailyAdvisorService(provider=_JczqProvider()).build_report(
        run_date=RUN_DATE, output_dir=output_dir
    )
    return list(report.matches)


# --- stage 1: 数据 ----------------------------------------------------------


def test_stage1_daily_advisor_parses_the_jczq_day(tmp_path: Path) -> None:
    matches = _seed_jczq_day(tmp_path)

    # The real advisor parsed all three submatches into JCZQ matches.
    assert [m.match_no for m in matches] == ["周五001", "周五002", "周五003"]
    assert all(m.league == "英超" for m in matches)
    # And persisted the replay context the brief stage consumes.
    assert (tmp_path / "daily" / RUN_DATE / "context.json").exists()


# --- stage 2: 冲突点检测 (ValueBoardService) --------------------------------


def test_stage2_value_board_produces_conflict_signals_with_edge_and_ev(
    tmp_path: Path,
) -> None:
    matches = _seed_jczq_day(tmp_path)
    bridge = _build_value_bridge()

    # JczqValueBridge → real MatchAligner → real ValueBoardService.
    report = bridge.evaluate_day(matches)

    # Two of the three matches align to an API-Football fixture; the third has
    # no fixture and is honestly marked, not papered over.
    assert report.aligned_count == 2
    aligned = [m for m in report.matches if m.aligned]
    unaligned = [m for m in report.matches if not m.aligned]
    assert {m.match_no for m in aligned} == {"周五001", "周五002"}
    assert [m.match_no for m in unaligned] == ["周五003"]
    assert unaligned[0].coverage_note is not None
    assert unaligned[0].conflicts == []

    # Every aligned match carries ≥1 real model-vs-market conflict signal.
    total_conflicts = [c for m in aligned for c in m.conflicts]
    assert total_conflicts, "expected the value board to surface conflicts"
    for c in total_conflicts:
        assert c.edge >= 0.03, "conflict must clear the +edge floor"
        assert c.expected_value > 0, "conflict must be +EV"
        assert c.best_odds > 1
        assert 0 < c.model_probability < 1
        assert 0 < c.market_probability < 1
        # The edge IS the model-vs-market probability gap.
        assert c.model_probability > c.market_probability

    # match_winner — the mandatory anchor market — is among the conflicts.
    assert any(c.market_key == "match_winner" for c in total_conflicts)


# --- stage 3: 串关构造器 (ParlayConstructor) --------------------------------


def test_stage3_parlay_constructor_obeys_rule_o_and_concentration_cap(
    tmp_path: Path,
) -> None:
    matches = _seed_jczq_day(tmp_path)
    report = _build_value_bridge().evaluate_day(matches)

    max_appearances = 3
    parlays = ParlayConstructor(
        max_match_appearances=max_appearances
    ).build(report)

    # Two aligned conflict matches → the constructor builds 2串1 candidate(s).
    assert parlays, "expected ≥1 parlay from the two aligned conflict legs"
    assert all(p.fold >= 2 for p in parlays)
    assert any(p.fold == 2 for p in parlays)

    appearances: dict[str, int] = {}
    for parlay in parlays:
        match_nos = [leg.match_no for leg in parlay.legs]
        # Rule O: a single parlay never takes two legs of the same match
        # (and therefore never mixes two pools of one match into one ticket).
        assert len(match_nos) == len(set(match_nos)), "Rule O violated"
        for mn in match_nos:
            appearances[mn] = appearances.get(mn, 0) + 1
        # combined odds == product of leg odds.
        product = 1.0
        for leg in parlay.legs:
            product *= leg.odds
        assert abs(parlay.combined_odds - product) < 1e-6

    # Concentration cap: no match appears across more parlays than the cap.
    assert appearances
    assert max(appearances.values()) <= max_appearances

    # The unaligned match never leaks into a parlay.
    assert "周五003" not in appearances


# --- stage 4: brief 渲染 (build_brief) --------------------------------------


def test_stage4_brief_renders_conflict_and_parlay_sections(
    tmp_path: Path,
) -> None:
    _seed_jczq_day(tmp_path)
    bridge = _build_value_bridge()

    # The real build_brief replays context.json, invokes the bridge over the
    # day's matches, and renders the 冲突点 + 串关候选 sections itself.
    markdown = build_brief(
        replay_date=RUN_DATE,
        output_dir=tmp_path,
        value_bridge=bridge,
    )

    # 「冲突点」 section is present and carries the real conflict numbers.
    assert "## 赔率冲突点" in markdown
    assert "价值引擎未接线" not in markdown, "bridge wired → not the placeholder"
    assert "周五001" in markdown and "周五002" in markdown
    assert "价值引擎冲突点" in markdown

    # 串关候选 section is present and lists a real parlay.
    assert "串关候选" in markdown
    assert "2串1" in markdown

    # Coverage line reflects 2/3 aligned, and the conflict section precedes the
    # Claude instruction block (debate consumes it in order).
    assert "2/3 场已对齐" in markdown
    assert markdown.index("## 赔率冲突点") < markdown.index(
        "## 6. 投递给 Claude 的指令模板"
    )


def test_stage4_brief_degrades_to_placeholder_without_bridge(
    tmp_path: Path,
) -> None:
    # No value bridge wired → the brief must still render, with the placeholder
    # marking the unwired slot. Graceful degradation is part of the pipeline.
    _seed_jczq_day(tmp_path)

    markdown = build_brief(replay_date=RUN_DATE, output_dir=tmp_path)

    assert "## 赔率冲突点" in markdown
    assert "价值引擎未接线" in markdown
    assert "串关候选" not in markdown


# --- stage 5: 注金阶梯 (ConflictStore / resolve_stake_phase) ----------------


def test_stage5_stake_ladder_observes_then_climbs_with_graded_history(
    tmp_path: Path,
) -> None:
    _seed_jczq_day(tmp_path)
    bridge = _build_value_bridge()

    # Persist the day's conflict signals into the store — the real recorder
    # runs the real bridge and writes had-pool CrossCheckSignal rows.
    recorded = record_conflict_signals(
        value_bridge=bridge,
        run_date=RUN_DATE,
        output_dir=tmp_path,
    )
    assert recorded >= 1, "expected ≥1 had-pool conflict signal recorded"

    store = ConflictStore(tmp_path / "memory" / "conflict-signals.json")

    # A store with only ungraded rows has no track record → OBSERVE: the engine
    # is unproven, so real money stays tiny (≤2%/signal).
    fresh_phase = store.phase()
    assert fresh_phase.name == "OBSERVE"
    assert fresh_phase.max_pct_per_signal == 0.02

    # Grade the recorded signals as a clean sweep of hits; with only a handful
    # of graded rows the ladder still holds at OBSERVE — evidence is too thin.
    rows = store.load()
    results = {row["match_no"]: row["pick"] for row in rows}
    store.grade(RUN_DATE, results=results)
    graded = [r for r in store.load() if r["hit"] is not None]
    assert graded, "grading must mark the recorded rows"
    assert all(r["hit"] is True for r in graded)
    assert store.phase().name == "OBSERVE", "a few graded rows ≠ enough evidence"


def test_stage5_stake_ladder_drives_every_rung(tmp_path: Path) -> None:
    """Drive resolve_stake_phase across the full OBSERVE→SMALL→NORMAL→KILL ladder.

    The ladder is the consolidation's risk layer: stakes scale with *proven*
    ROI, never with added rules. Exercising each rung is part of the
    end-to-end contract — an engine without a track record cannot bet big.
    """
    # OBSERVE — thin evidence, even at a great ROI.
    observe = resolve_stake_phase(graded_count=10, rolling_roi=1.5)
    assert observe.name == "OBSERVE"
    assert observe.max_pct_per_signal == 0.02

    # SMALL — ≥15 graded and ROI strictly above 1.0.
    small = resolve_stake_phase(graded_count=15, rolling_roi=1.01)
    assert small.name == "SMALL"
    assert small.max_pct_per_signal == 0.10

    # NORMAL — ≥40 graded and ROI strictly above 1.05.
    normal = resolve_stake_phase(graded_count=40, rolling_roi=1.06)
    assert normal.name == "NORMAL"
    assert normal.max_pct_per_signal == 0.30

    # KILL — ≥25 graded and ROI below 0.95, and it takes precedence.
    kill = resolve_stake_phase(graded_count=50, rolling_roi=0.90)
    assert kill.name == "KILL"
    assert kill.max_pct_per_signal == 0.0


def test_stage5_conflict_store_grades_against_results_into_rolling_roi(
    tmp_path: Path,
) -> None:
    # Drive ConflictStore.phase past OBSERVE by seeding enough graded ROI>1
    # history — the self-validation loop a real season would accumulate.
    store = ConflictStore(tmp_path / "memory" / "conflict-signals.json")
    matches = _seed_jczq_day(tmp_path)
    bridge = _build_value_bridge()
    report = bridge.evaluate_day(matches)
    from nutmeg.services.jczq_conflict_bridge import value_report_to_signals

    signals, sporttery_odds = value_report_to_signals(report)
    assert signals, "the day must yield had-pool signals to grade"

    # 20 historical days of the same winning conflict signal → 20 graded hits.
    for day in range(20):
        date = f"2026-04-{day + 1:02d}"
        store.record(date, signals, sporttery_odds=sporttery_odds)
        store.grade(
            date, results={s.match_no: s.pick for s in signals}
        )

    graded = [r for r in store.load() if r["hit"] is not None]
    assert len(graded) == 20 * len(signals)
    # Every graded row hit at its Sporttery odds (all > 1) → rolling ROI > 1.
    phase = store.phase()
    assert phase.name in {"SMALL", "NORMAL"}, (
        f"20+ graded ROI>1 days must climb off OBSERVE; got {phase.name}"
    )
    assert phase.max_pct_per_signal > 0.02


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
