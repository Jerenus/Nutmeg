from __future__ import annotations

from nutmeg.services.jczq import JczqMixedReportService, SampleJczqCalculatorProvider
from nutmeg.services.psychology.engine import (
    BudgetGuard,
    ConvictionGate,
    PsychologyEngine,
    Reconciliator,
    SignalContext,
)
from nutmeg.services.psychology.schemas import SignalReading


class _StubProvider:
    name = "stub"

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        readings: list[SignalReading] = []
        for fx in ctx.fixtures:
            target = self._mapping.get(str(fx.get("id")))
            if target:
                readings.append(
                    SignalReading(
                        self.name,
                        str(fx.get("id")),
                        "HHAD",
                        target,
                        0.85,
                        ["forced for test"],
                        [],
                        None,
                    )
                )
        return readings


def test_disabled_psychology_layer_keeps_data_picks() -> None:
    report = JczqMixedReportService(provider=SampleJczqCalculatorProvider()).build_report(
        dry_run=True
    )
    assert report.combinations


def test_enabled_layer_overrides_one_leg(monkeypatch) -> None:
    sample_provider = SampleJczqCalculatorProvider()
    base_report = JczqMixedReportService(provider=sample_provider).build_report(dry_run=True)
    first_leg = base_report.combinations[0].legs[0]
    target_fixture_id = f"{first_leg.match_no}:{first_leg.home_team}:{first_leg.away_team}"
    flip_target = "draw" if first_leg.pick != "draw" else "home_win"
    svc = JczqMixedReportService(
        provider=sample_provider,
        psychology_engine=PsychologyEngine(
            providers=[_StubProvider({target_fixture_id: flip_target})]
        ),
        reconciliator=Reconciliator(ConvictionGate(0.7), BudgetGuard(1)),
    )
    report = svc.build_report(dry_run=True)
    assert report.combinations[0].legs[0].pick == flip_target
    assert (
        report.psychology_reports[report.combinations[0].name].final_scheme.legs[0].provenance
        == "psychology"
    )


def test_d_layout_sections_appear_in_markdown() -> None:
    sample_provider = SampleJczqCalculatorProvider()
    base = JczqMixedReportService(provider=sample_provider).build_report(dry_run=True)
    first_leg = base.combinations[0].legs[0]
    target_fixture_id = f"{first_leg.match_no}:{first_leg.home_team}:{first_leg.away_team}"
    flip_target = "draw" if first_leg.pick != "draw" else "home_win"
    svc = JczqMixedReportService(
        provider=sample_provider,
        psychology_engine=PsychologyEngine(
            providers=[_StubProvider({target_fixture_id: flip_target})]
        ),
        reconciliator=Reconciliator(ConvictionGate(0.7), BudgetGuard(1)),
    )
    md = svc.render_markdown(svc.build_report(dry_run=True))
    assert "三栏诊断板" in md
    assert "心理博弈方案" in md
    assert "当日决策" in md
    assert "provenance" in md or "来源" in md
