"""Core psychology engine: signal providers, reduction, reconciliation.

Consolidates the former ``signals/base``, the four signal provider modules
(``tournament_stage``, ``contrarian_narrative``, ``personal_narrative``,
``reflexive_tactic``), ``engine``, ``guardrails``, ``reconciliator`` and
``jczq_adapter`` modules. Pure domain types live in
:mod:`nutmeg.services.psychology.schemas`; external IO lives in
:mod:`nutmeg.services.psychology.io`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field, is_dataclass, replace
from typing import Any, Protocol, runtime_checkable

from nutmeg.services.psychology.io import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DataLeg,
    DualSchemeReport,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    InspirationNote,
    OutcomeView,
    OverrideCandidate,
    PsychologyVerdict,
    Scheme,
    SignalReading,
)

# ---------------------------------------------------------------------------
# Signal provider protocol and context (formerly signals/base.py)
# ---------------------------------------------------------------------------


class SignalProviderError(RuntimeError):
    """Raised when a signal provider fails irrecoverably."""


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Bundle of inputs every provider receives. Providers ignore unused fields."""

    date: str
    fixtures: list[dict[str, Any]]
    snapshots: dict[str, dict[str, Any]]
    odds: dict[str, dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SignalProvider(Protocol):
    name: str

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        """Return one or more readings, degrading partial-source failures to abstain."""


# ---------------------------------------------------------------------------
# Tournament stage signal (formerly signals/tournament_stage.py)
# ---------------------------------------------------------------------------

UCL_LIKE = {"UCL", "UEL", "UECL"}


@dataclass(slots=True)
class TournamentStageSignal:
    name: str = "tournament_stage"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        readings: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            comp = str(fx.get("competition_code") or "")
            stage = str(fx.get("stage") or "")
            leg = fx.get("leg")
            tier_h = fx.get("tier_home")
            tier_a = fx.get("tier_away")
            agg_diff = fx.get("aggregate_score_diff")
            matched = False
            if (
                comp in UCL_LIKE
                and stage == "knockout"
                and leg == 1
                and tier_h == 1
                and tier_a == 1
            ):
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "draw",
                        0.65,
                        ["UCL/UEL knockout 1st leg, both top-tier teams - conservative"],
                        ["rule:ucl_first_leg_low_block"],
                        None,
                    )
                )
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "TTG",
                        "under_2_5",
                        0.65,
                        ["First-leg compactness historically suppresses goals"],
                        ["rule:ucl_first_leg_low_block"],
                        None,
                    )
                )
                matched = True
            if comp in UCL_LIKE and stage == "knockout" and leg == 2 and agg_diff == 0:
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "home_win",
                        0.55,
                        ["2nd leg with tied aggregate - home pushes for decisive win"],
                        ["rule:ucl_2nd_leg_tied_aggregate"],
                        None,
                    )
                )
                matched = True
            if stage == "cup" and tier_h is not None and tier_a is not None and tier_h > tier_a:
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "handicap",
                        "home_plus_one",
                        0.45,
                        ["Cup tie with lower-tier home - upset volatility"],
                        ["rule:cup_lower_tier_home"],
                        None,
                    )
                )
                matched = True
            if stage == "final_round" and bool(fx.get("away_has_stakes")):
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "away_win",
                        0.50,
                        ["Final round, away team still has table stakes; home decided"],
                        ["rule:league_final_round_motivation_gap"],
                        None,
                    )
                )
                matched = True
            if not matched:
                readings.append(
                    SignalReading(
                        self.name, fixture_id, "HHAD", None, 0.0, [], [], "no rule matched"
                    )
                )
        return readings


# ---------------------------------------------------------------------------
# Contrarian narrative signal (formerly signals/contrarian_narrative.py)
# ---------------------------------------------------------------------------

CONTRARIAN_MIN_SAMPLE = 5
CONTRARIAN_INTENSITY_GATE = 0.6
CONTRARIAN_CONVICTION_CAP = 0.75
CONTRARIAN_SYSTEM_PROMPT = (
    "Return JSON with consensus home|away|draw|mixed and intensity 0..1."
)


def _opposite(consensus: str) -> str | None:
    if consensus == "home":
        return "away_win"
    if consensus == "away":
        return "home_win"
    return None


@dataclass(slots=True)
class ContrarianNarrativeSignal:
    zhilio: Any
    rss: Any
    llm: LLMCompleter
    name: str = "contrarian_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            query = f"{fx.get('home_team_name') or ''} {fx.get('away_team_name') or ''}".strip()
            items: list[dict[str, Any]] = []
            items.extend(self.zhilio.search_news(query=query, date=ctx.date) or [])
            items.extend(self.zhilio.hotlist(date=ctx.date) or [])
            items.extend(self.rss.fetch(date=ctx.date, query=query) or [])
            if len(items) < CONTRARIAN_MIN_SAMPLE:
                out.append(self._abstain(fixture_id, "insufficient sample"))
                continue
            user_prompt = "\n".join(f"- {it.get('title', '')}" for it in items[:25])
            try:
                payload = json.loads(
                    self.llm.complete(system=CONTRARIAN_SYSTEM_PROMPT, user=user_prompt)
                )
                consensus = str(payload.get("consensus"))
                intensity = float(payload.get("intensity", 0.0))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue
            if intensity < CONTRARIAN_INTENSITY_GATE or consensus not in {"home", "away"}:
                out.append(self._abstain(fixture_id, f"intensity below gate ({intensity:.2f})"))
                continue
            contrarian = _opposite(consensus)
            if contrarian is None:
                out.append(self._abstain(fixture_id, "no contrarian outcome"))
                continue
            out.append(
                SignalReading(
                    self.name,
                    fixture_id,
                    "HHAD",
                    contrarian,
                    min(intensity, CONTRARIAN_CONVICTION_CAP),
                    [f"Public consensus leans {consensus} at intensity {intensity:.2f}"],
                    [str(it.get("link") or it.get("url") or "") for it in items[:5]],
                    None,
                )
            )
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)


# ---------------------------------------------------------------------------
# Personal narrative signal (formerly signals/personal_narrative.py)
# ---------------------------------------------------------------------------

STORY_KEYWORDS = ["复仇", "首秀", "末战", "回归", "重逢", "里程碑"]
PERSONAL_SYSTEM_PROMPT = (
    "Return JSON with story_present, team_advantaged home|away|none, conviction, story_summary."
)


@dataclass(slots=True)
class PersonalNarrativeSignal:
    rss: Any
    llm: LLMCompleter
    name: str = "personal_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            home = str(fx.get("home_team_name") or "")
            away = str(fx.get("away_team_name") or "")
            items = self.rss.fetch(date=ctx.date, query=home) or []
            items += self.rss.fetch(date=ctx.date, query=away) or []
            for kw in STORY_KEYWORDS:
                items += self.rss.fetch(date=ctx.date, query=kw) or []
            if not items:
                out.append(self._abstain(fixture_id, "no RSS items"))
                continue
            headlines = "\n".join(f"- {it.get('title', '')}" for it in items[:30])
            user = f"Home: {home}\nAway: {away}\nHeadlines:\n{headlines}"
            try:
                payload = json.loads(
                    self.llm.complete(system=PERSONAL_SYSTEM_PROMPT, user=user)
                )
                story_present = bool(payload.get("story_present"))
                team = str(payload.get("team_advantaged"))
                conviction = float(payload.get("conviction", 0.0))
                summary = str(payload.get("story_summary", ""))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue
            if not story_present or team not in {"home", "away"}:
                out.append(self._abstain(fixture_id, "no actionable story"))
                continue
            outcome = "home_win" if team == "home" else "away_win"
            out.append(
                SignalReading(
                    self.name,
                    fixture_id,
                    "HHAD",
                    outcome,
                    max(0.0, min(conviction, 0.7)),
                    [summary] if summary else ["personal narrative present"],
                    [str(it.get("link") or "") for it in items[:5]],
                    None,
                )
            )
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)


# ---------------------------------------------------------------------------
# Reflexive tactic signal (formerly signals/reflexive_tactic.py)
# ---------------------------------------------------------------------------

REFLEXIVE_VALID_PICKS = {"home_win", "draw", "away_win"}
REFLEXIVE_SYSTEM_PROMPT = (
    "Return JSON with second_order_pick home_win|draw|away_win, conviction, reasoning."
)


@dataclass(slots=True)
class ReflexiveTacticSignal:
    llm: LLMCompleter
    name: str = "reflexive_tactic"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            snap = ctx.snapshots.get(fixture_id)
            if not snap:
                out.append(self._abstain(fixture_id, "no tactical snapshot"))
                continue
            user = (
                f"Home: {fx.get('home_team_name', '')}, shape={snap.get('home_shape', '')}\n"
                f"Away: {fx.get('away_team_name', '')}, "
                f"shape={snap.get('away_shape', '')}"
            )
            try:
                payload = json.loads(
                    self.llm.complete(system=REFLEXIVE_SYSTEM_PROMPT, user=user)
                )
                pick = str(payload.get("second_order_pick"))
                conviction = float(payload.get("conviction", 0.0))
                reasoning = list(payload.get("reasoning") or [])
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue
            if pick not in REFLEXIVE_VALID_PICKS:
                out.append(self._abstain(fixture_id, f"invalid pick {pick!r}"))
                continue
            out.append(
                SignalReading(
                    self.name,
                    fixture_id,
                    "HHAD",
                    pick,
                    max(0.0, min(conviction, 1.0)),
                    reasoning or [f"Second-order tactical surprise -> {pick}"],
                    ["llm:reflexive_tactic"],
                    None,
                )
            )
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)


# ---------------------------------------------------------------------------
# Psychology engine (formerly engine.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PsychologyEngine:
    providers: list[SignalProvider]
    max_workers: int = 4

    def evaluate(
        self, *, ctx: SignalContext, data_picks: dict[str, dict[str, str]]
    ) -> list[PsychologyVerdict]:
        readings_by_provider: dict[str, list[SignalReading]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._safe_evaluate, p, ctx): p for p in self.providers}
            for future, provider in futures.items():
                readings_by_provider[provider.name] = future.result()
        all_readings = [r for readings in readings_by_provider.values() for r in readings]
        per_fixture: dict[str, list[SignalReading]] = defaultdict(list)
        for reading in all_readings:
            per_fixture[reading.fixture_id].append(reading)
        return [
            self._reduce(
                str(fx.get("id")),
                per_fixture.get(str(fx.get("id")), []),
                data_picks.get(str(fx.get("id")), {}),
            )
            for fx in ctx.fixtures
        ]

    def _safe_evaluate(self, provider: SignalProvider, ctx: SignalContext) -> list[SignalReading]:
        try:
            return list(provider.evaluate(ctx))
        except Exception as exc:  # noqa: BLE001 - provider isolation point
            return [
                SignalReading(
                    provider.name,
                    str(fx.get("id")),
                    "HHAD",
                    None,
                    0.0,
                    [],
                    [],
                    f"provider_crashed: {type(exc).__name__}",
                )
                for fx in ctx.fixtures
            ]

    def _reduce(
        self, fixture_id: str, readings: list[SignalReading], data_picks_for_fixture: dict[str, str]
    ) -> PsychologyVerdict:
        active = [r for r in readings if r.outcome_view is not None and r.conviction > 0]
        market_views: dict[str, OutcomeView] = {}
        by_market: dict[str, list[SignalReading]] = defaultdict(list)
        for reading in active:
            by_market[reading.market].append(reading)
        for market, rs in by_market.items():
            by_outcome: dict[str, list[float]] = defaultdict(list)
            for reading in rs:
                by_outcome[str(reading.outcome_view)].append(reading.conviction)
            winning_outcome = max(
                by_outcome, key=lambda outcome: (max(by_outcome[outcome]), len(by_outcome[outcome]))
            )
            supporting = by_outcome[winning_outcome]
            conviction = sum(supporting) / len(supporting) if len(supporting) > 1 else supporting[0]
            market_views[market] = OutcomeView(
                market=market, outcome=winning_outcome, conviction=min(conviction, 0.95)
            )
        overall_conviction = max((view.conviction for view in market_views.values()), default=0.0)
        if not market_views:
            lean_direction = "neutral"
        else:
            mismatches = [
                market
                for market, view in market_views.items()
                if data_picks_for_fixture.get(market)
                and view.outcome != data_picks_for_fixture.get(market)
            ]
            lean_direction = "diverge_data" if mismatches else "agree_data"
        return PsychologyVerdict(
            fixture_id, market_views, overall_conviction, lean_direction, readings
        )


# ---------------------------------------------------------------------------
# Guardrails (formerly guardrails.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ConvictionGate:
    threshold: float = 0.7

    def apply(
        self, candidates: list[OverrideCandidate]
    ) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        accepted: list[OverrideCandidate] = []
        rejected: list[tuple[OverrideCandidate, str]] = []
        for candidate in candidates:
            if candidate.conviction >= self.threshold:
                accepted.append(candidate)
            else:
                rejected.append(
                    (
                        candidate,
                        f"below_conviction({candidate.conviction:.2f}<{self.threshold:.2f})",
                    )
                )
        return accepted, rejected


@dataclass(slots=True)
class BudgetGuard:
    max_reversals: int = 1

    def apply(
        self, candidates: list[OverrideCandidate]
    ) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        ranked = sorted(candidates, key=lambda candidate: candidate.conviction, reverse=True)
        accepted = ranked[: self.max_reversals]
        rejected = [(candidate, "budget_exhausted") for candidate in ranked[self.max_reversals :]]
        return accepted, rejected


# ---------------------------------------------------------------------------
# Reconciliator (formerly reconciliator.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Reconciliator:
    conviction_gate: ConvictionGate
    budget_guard: BudgetGuard

    def reconcile(
        self,
        *,
        data_scheme: Scheme,
        psychology_verdicts: list[PsychologyVerdict],
        inspiration: InspirationNote | None,
        provider_origin: dict[str, str] | None = None,
    ) -> DualSchemeReport:
        verdict_by_fixture = {verdict.fixture_id: verdict for verdict in psychology_verdicts}
        psych_legs: list[DataLeg] = []
        candidates: list[OverrideCandidate] = []
        provider_origin = provider_origin or {}
        for leg in data_scheme.legs:
            verdict = verdict_by_fixture.get(leg.fixture_id)
            if (
                verdict
                and (
                    view := (
                        verdict.market_views.get(leg.market) or verdict.market_views.get("HHAD")
                    )
                )
                and view.outcome != leg.outcome
                and view.conviction > 0
            ):
                psych_legs.append(
                    DataLeg(leg.leg_id, leg.fixture_id, leg.market, view.outcome, leg.odds)
                )
                candidates.append(
                    OverrideCandidate(
                        leg.leg_id,
                        leg.fixture_id,
                        leg.market,
                        leg.outcome,
                        view.outcome,
                        view.conviction,
                        [],
                        provider_origin.get(f"{leg.fixture_id}::{leg.market}", "psychology"),
                    )
                )
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
                rejected.extend(
                    (candidate, f"focus_excluded({candidate.source_provider})")
                    for candidate in filtered
                    if candidate.source_provider not in allowed
                )
                filtered = [
                    candidate for candidate in filtered if candidate.source_provider in allowed
                ]
            if inspiration and inspiration.parsed_tags.force_psychology:
                accepted_pre_budget = filtered
                forced_via_inspiration = True
            else:
                accepted_pre_budget, gated_reject = self.conviction_gate.apply(filtered)
                rejected.extend(gated_reject)
        budget_pass, budget_reject = self.budget_guard.apply(accepted_pre_budget)
        rejected.extend(budget_reject)
        accepted_set = {
            (candidate.fixture_id, candidate.market): candidate for candidate in budget_pass
        }
        final_legs: list[FinalLeg] = []
        for leg in data_scheme.legs:
            candidate = accepted_set.get((leg.fixture_id, leg.market))
            if candidate:
                final_legs.append(
                    FinalLeg(
                        leg.leg_id,
                        leg.fixture_id,
                        leg.market,
                        candidate.to_outcome,
                        leg.odds,
                        "inspiration_forced" if forced_via_inspiration else "psychology",
                    )
                )
            else:
                final_legs.append(
                    FinalLeg(leg.leg_id, leg.fixture_id, leg.market, leg.outcome, leg.odds, "data")
                )
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
            psych_view = (
                (verdict.market_views.get(leg.market) or verdict.market_views.get("HHAD"))
                if verdict
                else None
            )
            psych_pick = psych_view.outcome if psych_view else None
            final_outcome = next(
                final_leg.outcome for final_leg in final_legs if final_leg.leg_id == leg.leg_id
            )
            dashboard.append(
                DashboardRow(
                    leg.fixture_id,
                    leg.outcome,
                    psych_pick,
                    psych_pick is not None and psych_pick != leg.outcome,
                    final_outcome,
                    verdict.conviction if verdict else 0.0,
                )
            )
        return DualSchemeReport(
            data_scheme,
            psych_scheme,
            FinalScheme(final_legs, confidence, notes),
            dashboard,
            inspiration,
            GuardrailDecision(
                list(budget_pass),
                rejected,
                {
                    "budget": f"{len(budget_pass)}/{self.budget_guard.max_reversals}",
                    "conviction_gate": f"{self.conviction_gate.threshold:.2f}",
                    "kill_switch": "warming_up",
                },
            ),
        )


# ---------------------------------------------------------------------------
# JCZQ adapter (formerly jczq_adapter.py)
# ---------------------------------------------------------------------------


def _fixture_id(leg: Any) -> str:
    return f"{leg.match_no}:{leg.home_team}:{leg.away_team}"


def _leg_id(idx: int) -> str:
    return f"L{idx + 1}"


def combination_to_data_scheme(combination: Any) -> Scheme:
    return Scheme(
        name=str(combination.name),
        legs=[
            DataLeg(_leg_id(idx), _fixture_id(leg), str(leg.play), str(leg.pick), float(leg.odds))
            for idx, leg in enumerate(combination.legs)
        ],
    )


def apply_final_scheme_to_combination(combination: Any, final: FinalScheme) -> Any:
    updated = deepcopy(combination)
    final_by_leg = {leg.leg_id: leg for leg in final.legs}
    new_legs = []
    changed = False
    for idx, leg in enumerate(updated.legs):
        replacement = final_by_leg.get(_leg_id(idx))
        if replacement is None:
            new_legs.append(leg)
            continue
        changed = True
        if is_dataclass(leg):
            new_legs.append(replace(leg, pick=replacement.outcome, odds=replacement.odds))
        else:
            leg.pick = replacement.outcome
            leg.odds = replacement.odds
            new_legs.append(leg)
    if changed and is_dataclass(updated):
        product = 1.0
        for leg in new_legs:
            product *= float(leg.odds)
        return replace(
            updated,
            legs=new_legs,
            total_odds=round(product, 2),
            two_yuan_return=round(product * 2, 2),
        )
    updated.legs = new_legs
    return updated
