from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.schemas import DashboardRow, DataLeg, DualSchemeReport, FinalLeg, FinalScheme, GuardrailDecision, InspirationNote, OverrideCandidate, PsychologyVerdict, Scheme


@dataclass(slots=True)
class Reconciliator:
    conviction_gate: ConvictionGate
    budget_guard: BudgetGuard

    def reconcile(self, *, data_scheme: Scheme, psychology_verdicts: list[PsychologyVerdict], inspiration: InspirationNote | None, provider_origin: dict[str, str] | None = None) -> DualSchemeReport:
        verdict_by_fixture = {verdict.fixture_id: verdict for verdict in psychology_verdicts}
        psych_legs: list[DataLeg] = []
        candidates: list[OverrideCandidate] = []
        provider_origin = provider_origin or {}
        for leg in data_scheme.legs:
            verdict = verdict_by_fixture.get(leg.fixture_id)
            if verdict and (view := verdict.market_views.get(leg.market)) and view.outcome != leg.outcome and view.conviction > 0:
                psych_legs.append(DataLeg(leg.leg_id, leg.fixture_id, leg.market, view.outcome, leg.odds))
                candidates.append(OverrideCandidate(leg.leg_id, leg.fixture_id, leg.market, leg.outcome, view.outcome, view.conviction, [], provider_origin.get(f"{leg.fixture_id}::{leg.market}", "psychology")))
            else:
                psych_legs.append(leg)
        psych_scheme = Scheme(name="psychology", legs=psych_legs)
        forced_via_inspiration = False
        rejected: list[tuple[OverrideCandidate, str]] = []
        if inspiration and inspiration.parsed_tags.force_data:
            rejected.extend((candidate, "inspiration_force_data") for candidate in candidates)
            accepted_pre_budget: list[OverrideCandidate] = []
        else:
            filtered = candidates
            if inspiration and inspiration.parsed_tags.focus:
                allowed = set(inspiration.parsed_tags.focus)
                rejected.extend((candidate, f"focus_excluded({candidate.source_provider})") for candidate in filtered if candidate.source_provider not in allowed)
                filtered = [candidate for candidate in filtered if candidate.source_provider in allowed]
            if inspiration and inspiration.parsed_tags.force_psychology:
                accepted_pre_budget = filtered
                forced_via_inspiration = True
            else:
                accepted_pre_budget, gated_reject = self.conviction_gate.apply(filtered)
                rejected.extend(gated_reject)
        budget_pass, budget_reject = self.budget_guard.apply(accepted_pre_budget)
        rejected.extend(budget_reject)
        accepted_set = {(candidate.fixture_id, candidate.market): candidate for candidate in budget_pass}
        final_legs: list[FinalLeg] = []
        for leg in data_scheme.legs:
            candidate = accepted_set.get((leg.fixture_id, leg.market))
            if candidate:
                final_legs.append(FinalLeg(leg.leg_id, leg.fixture_id, leg.market, candidate.to_outcome, leg.odds, "inspiration_forced" if forced_via_inspiration else "psychology"))
            else:
                final_legs.append(FinalLeg(leg.leg_id, leg.fixture_id, leg.market, leg.outcome, leg.odds, "data"))
        if not candidates:
            confidence = "high"
        elif any("budget" in reason for _, reason in rejected):
            confidence = "low"
        elif accepted_set:
            confidence = "medium"
        else:
            confidence = "high"
        notes: list[str] = []
        if forced_via_inspiration:
            notes.append("inspiration_force_psychology applied")
        if inspiration and inspiration.parsed_tags.force_data:
            notes.append("inspiration_force_data applied")
        dashboard: list[DashboardRow] = []
        for leg in data_scheme.legs:
            verdict = verdict_by_fixture.get(leg.fixture_id)
            psych_pick = verdict.market_views.get(leg.market).outcome if verdict and leg.market in verdict.market_views else None
            final_outcome = next(final_leg.outcome for final_leg in final_legs if final_leg.leg_id == leg.leg_id)
            dashboard.append(DashboardRow(leg.fixture_id, leg.outcome, psych_pick, psych_pick is not None and psych_pick != leg.outcome, final_outcome, verdict.conviction if verdict else 0.0))
        return DualSchemeReport(data_scheme, psych_scheme, FinalScheme(final_legs, confidence, notes), dashboard, inspiration, GuardrailDecision(list(budget_pass), rejected, {"budget": f"{len(budget_pass)}/{self.budget_guard.max_reversals}", "conviction_gate": f"{self.conviction_gate.threshold:.2f}", "kill_switch": "warming_up"}))
