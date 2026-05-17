"""Brief integration of the 赔率冲突点 section (Phase 3b piece 3)."""

from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_brief import _emit_markdown
from nutmeg.services.jczq_value_bridge import JczqMatchConflicts, JczqValueReport


def _emit(value_report: JczqValueReport | None) -> str:
    """Render the brief with empty match/plan data so only wiring is exercised."""
    return _emit_markdown(
        run_date="2026-05-17",
        matches=[],
        analytics={},
        plans=[],
        poisson_rows=[],
        poisson_index={},
        summary="(no plans)",
        official_last_update=None,
        league_volatility={},
        value_report=value_report,
    )


def _value_report() -> JczqValueReport:
    candidate = ValueCandidate(
        fixture_id="1379305",
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team="Arsenal",
        away_team="Tottenham",
        outcome_key="home",
        outcome_name="Home",
        model_probability=0.55,
        market_probability=0.43,
        edge=0.12,
        best_odds=2.2,
        expected_value=0.21,
        quarter_kelly_fraction=0.03,
        rating="strong",
        model_name="dixon-coles-lite",
        market_key="match_winner",
    )
    return JczqValueReport(
        matches=[
            JczqMatchConflicts(
                match_no="周六001",
                league="英超",
                home_team="阿森纳",
                away_team="热刺",
                aligned=True,
                fixture_id="1379305",
                conflicts=[candidate],
            )
        ]
    )


def test_brief_includes_conflict_section_when_value_report_supplied() -> None:
    text = _emit(_value_report())

    assert "## 赔率冲突点" in text
    assert "周六001" in text
    assert "+12%" in text


def test_brief_renders_placeholder_when_no_value_report() -> None:
    text = _emit(None)

    # Section header is always present so the debate flow knows the slot exists.
    assert "## 赔率冲突点" in text
    assert "价值引擎未接线" in text


def test_brief_conflict_section_precedes_claude_instruction_block() -> None:
    text = _emit(_value_report())

    assert text.index("## 赔率冲突点") < text.index("## 6. 投递给 Claude 的指令模板")


def _multi_match_value_report() -> JczqValueReport:
    """Two aligned matches → the parlay constructor can build a 2串1."""

    def _conflict(fixture_id: str, home: str, away: str) -> ValueCandidate:
        return ValueCandidate(
            fixture_id=fixture_id,
            kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
            home_team=home,
            away_team=away,
            outcome_key="home",
            outcome_name="Home",
            model_probability=0.6,
            market_probability=0.45,
            edge=0.15,
            best_odds=2.0,
            expected_value=0.2,
            quarter_kelly_fraction=0.03,
            rating="strong",
            model_name="dixon-coles-lite",
            market_key="match_winner",
        )

    return JczqValueReport(
        matches=[
            JczqMatchConflicts(
                match_no="周六001",
                league="英超",
                home_team="阿森纳",
                away_team="热刺",
                aligned=True,
                fixture_id="fx1",
                conflicts=[_conflict("fx1", "Arsenal", "Tottenham")],
            ),
            JczqMatchConflicts(
                match_no="周六002",
                league="德甲",
                home_team="拜仁",
                away_team="多特",
                aligned=True,
                fixture_id="fx2",
                conflicts=[_conflict("fx2", "Bayern", "Dortmund")],
            ),
        ]
    )


def test_brief_renders_parlay_candidates_from_conflict_legs() -> None:
    text = _emit(_multi_match_value_report())

    # The parlay constructor turned the two conflict legs into a 2串1 combo.
    assert "串关候选" in text
    assert "2串1" in text


def test_brief_has_no_parlay_section_without_value_report() -> None:
    text = _emit(None)

    assert "串关候选" not in text
