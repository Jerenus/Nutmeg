from __future__ import annotations

import pytest

from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DataLeg,
    DualSchemeReport,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    InspirationTags,
    OutcomeView,
    PsychologyVerdict,
    Scheme,
    SignalReading,
)


def test_signal_reading_immutable_and_serializable() -> None:
    reading = SignalReading(
        provider="tournament_stage",
        fixture_id="psg-bay-2026-04-28",
        market="HHAD",
        outcome_view="away_win",
        conviction=0.72,
        evidence=["UCL SF first leg, both teams favor compactness"],
        source_refs=["rule:cup_first_leg_low_block"],
        abstain_reason=None,
    )
    with pytest.raises(Exception):
        reading.conviction = 0.9  # type: ignore[misc]
    assert reading.outcome_view == "away_win"


def test_psychology_verdict_lean_direction_literal() -> None:
    verdict = PsychologyVerdict(
        fixture_id="f1",
        market_views={"HHAD": OutcomeView(market="HHAD", outcome="draw", conviction=0.6)},
        conviction=0.6,
        lean_direction="diverge_data",
        contributing_readings=[],
    )
    assert verdict.lean_direction == "diverge_data"


def test_inspiration_tags_default_flags() -> None:
    tags = InspirationTags(
        lean="psychology",
        conviction="high",
        focus=["tournament_stage"],
        force_psychology=False,
        force_data=False,
    )
    assert tags.force_psychology is False


def test_dual_scheme_report_holds_all_layers() -> None:
    data_leg = DataLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="home_win", odds=2.10)
    psych_leg = DataLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="away_win", odds=2.45)
    final_leg = FinalLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="away_win", odds=2.45, provenance="psychology")
    report = DualSchemeReport(
        data_scheme=Scheme(name="data", legs=[data_leg]),
        psychology_scheme=Scheme(name="psychology", legs=[psych_leg]),
        final_scheme=FinalScheme(legs=[final_leg], confidence="medium", notes=["1 reversal applied"]),
        dashboard_rows=[DashboardRow(fixture_id="f1", data_pick="home_win", psych_pick="away_win", conflict=True, final_pick="away_win", conviction=0.72)],
        inspiration=None,
        guardrail=GuardrailDecision(accepted=[], rejected=[], guardrail_state={"budget": "1/1"}),
    )
    assert report.dashboard_rows[0].conflict is True
    assert report.final_scheme.legs[0].provenance == "psychology"
