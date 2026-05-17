from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_conflict_section import (
    MatchInformation,
    render_conflict_section,
)
from nutmeg.services.jczq_value_bridge import JczqMatchConflicts, JczqValueReport
from nutmeg.services.psychology.schemas import SignalReading


def _candidate(
    *,
    fixture_id: str = "1379305",
    market_key: str = "match_winner",
    outcome_key: str = "home",
    outcome_name: str = "Home",
    edge: float = 0.12,
    best_odds: float = 2.2,
    model_probability: float = 0.55,
    market_probability: float = 0.43,
) -> ValueCandidate:
    return ValueCandidate(
        fixture_id=fixture_id,
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team="Arsenal",
        away_team="Tottenham",
        outcome_key=outcome_key,
        outcome_name=outcome_name,
        model_probability=model_probability,
        market_probability=market_probability,
        edge=edge,
        best_odds=best_odds,
        expected_value=0.21,
        quarter_kelly_fraction=0.03,
        rating="strong",
        model_name="dixon-coles-lite",
        market_key=market_key,
    )


def _aligned_entry(
    *,
    match_no: str = "周六001",
    conflicts: list[ValueCandidate] | None = None,
) -> JczqMatchConflicts:
    return JczqMatchConflicts(
        match_no=match_no,
        league="英超",
        home_team="阿森纳",
        away_team="热刺",
        aligned=True,
        fixture_id="1379305",
        conflicts=conflicts if conflicts is not None else [_candidate()],
    )


def _unaligned_entry(match_no: str = "周六009") -> JczqMatchConflicts:
    return JczqMatchConflicts(
        match_no=match_no,
        league="英超",
        home_team="未知队",
        away_team="热刺",
        aligned=False,
        coverage_note="无 API-Football 数据：球队未收录",
    )


def test_section_has_heading_and_table_for_aligned_match() -> None:
    report = JczqValueReport(matches=[_aligned_entry()])

    text = render_conflict_section(report)

    assert "## 赔率冲突点" in text
    assert "周六001" in text
    assert "阿森纳 vs 热刺" in text
    # value-engine conflict columns
    assert "市场" in text and "公允概率" in text and "edge" in text
    assert "+12" in text  # edge percentage rendered
    assert "match_winner" in text


def test_section_renders_psychology_signal_side_by_side() -> None:
    report = JczqValueReport(matches=[_aligned_entry()])
    psychology = {
        "周六001": [
            SignalReading(
                provider="ContrarianNarrativeSignal",
                fixture_id="1379305",
                market="match_winner",
                outcome_view="away",
                conviction=0.6,
                evidence=["公众一边倒压主胜，反向看客队"],
                source_refs=[],
                abstain_reason=None,
            )
        ]
    }

    text = render_conflict_section(report, psychology_by_match=psychology)

    assert "心理信号" in text
    assert "ContrarianNarrativeSignal" in text
    assert "公众一边倒压主胜" in text


def test_section_renders_information_lineups_and_injuries() -> None:
    report = JczqValueReport(matches=[_aligned_entry()])
    information = {
        "周六001": MatchInformation(
            lineup_note="主队首发已确认 (4-3-3)",
            injury_notes=["热刺中场 Maddison 伤缺"],
        )
    }

    text = render_conflict_section(report, information_by_match=information)

    assert "情报" in text
    assert "主队首发已确认" in text
    assert "Maddison 伤缺" in text


def test_section_shows_coverage_note_for_unaligned_match() -> None:
    report = JczqValueReport(
        matches=[_aligned_entry(), _unaligned_entry()]
    )

    text = render_conflict_section(report)

    assert "周六009" in text
    assert "无 API-Football 数据" in text
    # coverage summary line
    assert "覆盖率" in text


def test_section_handles_aligned_match_with_no_conflicts() -> None:
    entry = JczqMatchConflicts(
        match_no="周六002",
        league="英超",
        home_team="切尔西",
        away_team="埃弗顿",
        aligned=True,
        fixture_id="999",
        conflicts=[],
        coverage_note="已对齐 API-Football，但无 +edge 冲突点",
    )
    report = JczqValueReport(matches=[entry])

    text = render_conflict_section(report)

    assert "周六002" in text
    assert "无 +edge 冲突点" in text


def test_section_renders_multiple_conflicts_per_match() -> None:
    conflicts = [
        _candidate(market_key="match_winner", outcome_key="home", edge=0.15),
        _candidate(
            market_key="total_goals",
            outcome_key="total_2",
            outcome_name="2",
            edge=0.08,
        ),
    ]
    report = JczqValueReport(matches=[_aligned_entry(conflicts=conflicts)])

    text = render_conflict_section(report)

    assert "total_goals" in text
    assert "+15" in text and "+8" in text


def test_empty_report_renders_placeholder() -> None:
    report = JczqValueReport(matches=[])

    text = render_conflict_section(report)

    assert "## 赔率冲突点" in text
    assert "无" in text
