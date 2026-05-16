from __future__ import annotations

from nutmeg.services.psychology.engine import BudgetGuard, ConvictionGate, Reconciliator
from nutmeg.services.psychology.schemas import (
    DataLeg,
    InspirationNote,
    InspirationTags,
    OutcomeView,
    PsychologyVerdict,
    Scheme,
)


def _data_scheme() -> Scheme:
    return Scheme(
        name="data",
        legs=[
            DataLeg("L1", "f1", "HHAD", "home_win", 2.10),
            DataLeg("L2", "f2", "HHAD", "draw", 3.20),
            DataLeg("L3", "f3", "HHAD", "away_win", 2.50),
        ],
    )


def _psy_verdict(
    fixture: str, outcome: str, conv: float, lean: str = "diverge_data"
) -> PsychologyVerdict:
    return PsychologyVerdict(fixture, {"HHAD": OutcomeView("HHAD", outcome, conv)}, conv, lean, [])  # type: ignore[arg-type]


def _build_recon() -> Reconciliator:
    return Reconciliator(
        conviction_gate=ConvictionGate(threshold=0.7), budget_guard=BudgetGuard(max_reversals=1)
    )


def test_no_disagreement_keeps_data_scheme() -> None:
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[
            _psy_verdict("f1", "home_win", 0.8, "agree_data"),
            _psy_verdict("f2", "draw", 0.5, "agree_data"),
            _psy_verdict("f3", "away_win", 0.3, "agree_data"),
        ],
        inspiration=None,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)
    assert report.final_scheme.confidence == "high"


def test_high_conviction_disagreement_overrides() -> None:
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1", "away_win", 0.85)],
        inspiration=None,
    )
    overridden = [leg for leg in report.final_scheme.legs if leg.provenance == "psychology"]
    assert len(overridden) == 1 and overridden[0].fixture_id == "f1"
    assert overridden[0].outcome == "away_win"


def test_budget_caps_at_one() -> None:
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[
            _psy_verdict("f1", "away_win", 0.85),
            _psy_verdict("f2", "home_win", 0.9),
        ],
        inspiration=None,
    )
    assert len([leg for leg in report.final_scheme.legs if leg.provenance == "psychology"]) == 1
    assert any("budget" in reason for _, reason in report.guardrail.rejected)
    assert report.final_scheme.confidence == "low"


def test_conviction_gate_filters_low_conviction() -> None:
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1", "away_win", 0.5)],
        inspiration=None,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)


def test_force_data_skips_psychology() -> None:
    insp = InspirationNote(
        "2026-04-29",
        "只走数据",
        InspirationTags("data", "high", [], False, True),
        "llm",
        "2026-04-29T14:00Z",
    )
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1", "away_win", 0.99)],
        inspiration=insp,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)


def test_force_psychology_bypasses_conviction_gate() -> None:
    insp = InspirationNote(
        "2026-04-29",
        "今天必须心理",
        InspirationTags("psychology", "high", [], True, False),
        "llm",
        "2026-04-29T14:00Z",
    )
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1", "away_win", 0.5)],
        inspiration=insp,
    )
    forced = [leg for leg in report.final_scheme.legs if leg.provenance == "inspiration_forced"]
    assert len(forced) == 1
    assert forced[0].outcome == "away_win"


def test_focus_filter_drops_off_focus_provider() -> None:
    insp = InspirationNote(
        "2026-04-29",
        "重点看大赛阶段",
        InspirationTags("psychology", "high", ["tournament_stage"], False, False),
        "llm",
        "2026-04-29T14:00Z",
    )
    v = PsychologyVerdict(
        "f1", {"HHAD": OutcomeView("HHAD", "away_win", 0.85)}, 0.85, "diverge_data", []
    )
    report = _build_recon().reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[v],
        inspiration=insp,
        provider_origin={"f1::HHAD": "contrarian_narrative"},
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)
