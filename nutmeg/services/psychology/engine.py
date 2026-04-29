from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from nutmeg.services.psychology.schemas import OutcomeView, PsychologyVerdict, SignalReading
from nutmeg.services.psychology.signals.base import SignalContext, SignalProvider


@dataclass(slots=True)
class PsychologyEngine:
    providers: list[SignalProvider]
    max_workers: int = 4

    def evaluate(self, *, ctx: SignalContext, data_picks: dict[str, dict[str, str]]) -> list[PsychologyVerdict]:
        readings_by_provider: dict[str, list[SignalReading]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._safe_evaluate, p, ctx): p for p in self.providers}
            for future, provider in futures.items():
                readings_by_provider[provider.name] = future.result()
        all_readings = [r for readings in readings_by_provider.values() for r in readings]
        per_fixture: dict[str, list[SignalReading]] = defaultdict(list)
        for reading in all_readings:
            per_fixture[reading.fixture_id].append(reading)
        return [self._reduce(str(fx.get("id")), per_fixture.get(str(fx.get("id")), []), data_picks.get(str(fx.get("id")), {})) for fx in ctx.fixtures]

    def _safe_evaluate(self, provider: SignalProvider, ctx: SignalContext) -> list[SignalReading]:
        try:
            return list(provider.evaluate(ctx))
        except Exception as exc:  # noqa: BLE001 - provider isolation point
            return [SignalReading(provider.name, str(fx.get("id")), "HHAD", None, 0.0, [], [], f"provider_crashed: {type(exc).__name__}") for fx in ctx.fixtures]

    def _reduce(self, fixture_id: str, readings: list[SignalReading], data_picks_for_fixture: dict[str, str]) -> PsychologyVerdict:
        active = [r for r in readings if r.outcome_view is not None and r.conviction > 0]
        market_views: dict[str, OutcomeView] = {}
        by_market: dict[str, list[SignalReading]] = defaultdict(list)
        for reading in active:
            by_market[reading.market].append(reading)
        for market, rs in by_market.items():
            by_outcome: dict[str, list[float]] = defaultdict(list)
            for reading in rs:
                by_outcome[str(reading.outcome_view)].append(reading.conviction)
            winning_outcome = max(by_outcome, key=lambda outcome: (max(by_outcome[outcome]), len(by_outcome[outcome])))
            supporting = by_outcome[winning_outcome]
            conviction = sum(supporting) / len(supporting) if len(supporting) > 1 else supporting[0]
            market_views[market] = OutcomeView(market=market, outcome=winning_outcome, conviction=min(conviction, 0.95))
        overall_conviction = max((view.conviction for view in market_views.values()), default=0.0)
        if not market_views:
            lean_direction = "neutral"
        else:
            mismatches = [market for market, view in market_views.items() if data_picks_for_fixture.get(market) and view.outcome != data_picks_for_fixture.get(market)]
            lean_direction = "diverge_data" if mismatches else "agree_data"
        return PsychologyVerdict(fixture_id, market_views, overall_conviction, lean_direction, readings)
