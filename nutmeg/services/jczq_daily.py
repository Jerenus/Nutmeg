"""⚠️ DEPRECATED（退役 Poisson generator · 2026-06-04 标记 · spec §33）。

本模块是 v1 generator 引擎（R1-R28 / A-J 选腿逻辑的家）。**live 引擎是 jczq_tiered，
每日决策唯一入口是 `nutmeg jczq-today`（spec §32）。** 本模块仅供退役命令
（jczq-daily-advisor / -brief / -review / -replay）与历史参考；勿用于每日决策。
背景见 docs/jczq-decision-chain-critique.md。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from nutmeg.domain.jczq_daily import (
    JczqDailyAdvisorReport,
    JczqDailyLeg,
    JczqDailyMatch,
    JczqDailyPlan,
)
from nutmeg.services.jczq import (
    SPORTTERY_JCZQ_PAGE,
    JczqCalculatorProvider,
    SampleJczqCalculatorProvider,
    SportteryJczqCalculatorProvider,
)
from nutmeg.services.jczq_baseline import build_default_providers
from nutmeg.services.jczq_diagnostics import (
    apply_rule_l_concentration_cap,
    apply_rule_l_story_cap,
    apply_rule_n_late_kickoff_cap,
    enforce_main_plan_pool_diversity,
)
from nutmeg.services.jczq_drift import (
    OddsDriftStore,
    drift_provider_from_signals,
)
from nutmeg.services.jczq_intelligence import (
    CONTRARIAN_POISSON_REJECT_BELOW,
    CRS_POISSON_EDGE_FLOOR,
    HHAD_DRAW_MIN_EDGE,
    HHAD_POISSON_REJECT_BELOW,
    HIGH_ODDS_HAD_REQUIRED_EDGE,
    HIGH_ODDS_HAD_THRESHOLD,
    BaselineProvider,
    DriftProvider,
    LeaguePriorBaseline,
    MatchAnalytics,
    PopularityProvider,
    compute_analytics,
    compute_poisson_edges,
    poisson_edge_index,
    select_top_legs,
)
from nutmeg.services.jczq_strategy_memory import (
    compute_daily_concentration_bias,
    compute_empirical_decay_map,
    compute_league_residual_bias,
    compute_league_ttg_volatility,
    compute_poisson_lambda_signals,
    decision_policy_rule,
    decision_policy_rule_active,
    detect_poisson_solo_cooling_off,
    get_dixon_coles_rho,
    load_strategy_memory,
    memory_pattern_positive,
    oracle_learning_for,
    pattern_bucket_ev,
    recently_burned_teams,
    render_decision_policy_notes,
    render_strategy_memory_notes,
)

# Rule B (5/07 iteration): had legs priced at or below this floor are too thin to anchor.
# Bumped 1.40 → 1.50 after 5/06 review: stable_base stats 5 hits / 6 misses (n=11);
# 5/06 specific: 拜仁 had 胜 @ 1.52 in stable_base MISS (1:1). Razor-thin 1.40-1.50
# bankers consistently underperform; 1.50-1.60 still allowed but flagged in soft rules.
HAD_BANKER_FLOOR = 1.50
# R20 (5/11): stable_base had favorites need a Poisson quality gate on top
# of Rule B's odds floor. 5/11 A 票 had 005 had 胜 @1.60 (Poisson edge
# -10.56%) + 006 had 胜 @1.60 (edge -10.01%) — both passed Rule B (odds >
# 1.50) but lost. -10% Poisson edge on a had favorite means the market has
# already priced beyond model-fair (vig + over-confidence); the "stable
# base" premise is broken. Floor matches Rule J / R12 (-10%) so the system
# uses one consistent "strongly opposed" threshold across pools.
STABLE_BASE_HAD_MIN_POISSON_EDGE = -0.10
# R21 (5/12): extend R20 floor from stable_base to main. 5/12 main 票 had
# 三腿全 ≤ -10% Poisson edge → 1/3 命中：003 had 胜 -10.46% MISS, 004 had
# 平 -10.94% HIT (lucky), 006 had 平 -10.64% MISS. Same -10% floor logic
# as R20 (consistent threshold w/ Rule J / R12). Applied at _select_leg
# time so main slot collapses to None if no eligible candidate — _make_plan
# tolerates None legs and the plan simply shrinks.
MAIN_HAD_MIN_POISSON_EDGE = -0.10
# Rule A: a leg with at least this much Poisson edge triggers the poisson_solo ticket.
POISSON_SOLO_EDGE_THRESHOLD = 0.15
# R23 (5/13): aggregate 10-day evidence shows crs 0:0 alpha hits 1/16 = 6.25%
# vs implied 8-15%. Single biggest miss-rate bucket; raise the poisson_solo
# floor for crs 0:0 specifically from +15% to +25%. Other crs picks (0:1, 1:0)
# and ttg/had/hhad/hafu still use POISSON_SOLO_EDGE_THRESHOLD. 5/13 005 crs
# 0:0 +40.4% would still pass; 5/12 006 crs 0:0 +16.3% would not. R23 stacks
# on top of R1 league signals (which can raise the floor further) — both are
# upward-only, so the effective floor is the max.
POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE = 0.25
# Rule O (5/07 iteration after sport.gov.cn rule reminder): same-match different-pool
# legs may NOT be combined into one parlay ticket per 国家体育总局《竞彩自由过关》rule.
# Source: https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21177108/content.html
# This invalidated the original Rule A v2 design ("crs requires same-match support") —
# the support pairing forced ttg+crs same-match combos that the official rule forbids.
# Rule A v2 (5/07 redesign): crs single-leg is allowed solo at edge ≥ +15% (~10% hit
# rate is acceptable for 25 yuan small-bet entertainment). To pair, must use a
# DIFFERENT-MATCH +EV row (≥ +5%) — never same-match. Same-match support is now
# advisory analysis only, surfaced in brief Section 5b but never multiplied in a
# ticket leg.
POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE = 0.05
# Rule A: legs with edge ≤ this are flagged in the report as model-opposed.
POISSON_STRONG_OPPOSE_THRESHOLD = -0.20
# Rule A v3 (R5, 5/08): cross-match crs×crs combos have ~0.6% joint hit
# probability (each ~8% individually). 5/07 C ticket (005 0:0 × 002 0:0)
# was billed as alpha but the joint was a longshot. Cap poisson_solo at
# at most 1 crs leg total — the other slot must come from ttg/had/hhad.
POISSON_SOLO_MAX_CRS_LEGS = 1
# R13 (5/10): poisson_solo ttg-low picks must agree with model expected_goals.
# 5/09 incident — 周六016 斯图加特 vs 勒沃 fit gave expected_goals = 3.2; the
# model still produced ttg 1球 with edge +30.4% and that leg made it into the
# ticket; actual 4 goals → C ticket lost a leg. The +30% edge is real (ttg 1球
# fair prob ≈ 0.13 vs implied 0.10) but at expected_goals ≥ 2.7 the single-bin
# 0/1/2-球 prediction has ~10-13% hit rate; the variance dominates the EV.
# Human debate auditor (5/09) caught this and replaced the leg with 周六019
# expected_goals=2.0 → ttg 1球 hit. Hard-filter at the row eligibility stage.
POISSON_SOLO_TTG_LOW_GOAL_THRESHOLD = 2.7
POISSON_SOLO_TTG_LOW_PICKS = ("0球", "1球", "2球")
# Used by R17 (low_goals narrative test) and EXTREME_CRS_LOW_PICKS / R18.
# Picks below have <= 1 total goal — single-bin and narratively the same
# "low scoring evening" bet.
POISSON_SOLO_CRS_LOW_PICKS = ("0:0", "0:1", "1:0")
# R17 (5/11): when poisson_solo selects 2 legs and BOTH are "low_goals"
# narrative (crs 0:0/0:1/1:0 OR ttg 0/1/2球), AND any leg has expected_goals
# ≥ POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER (2.3), drop the higher-λ leg and
# keep only the more consistent one. Prevents narrative concentration in
# C tickets — 5/11 C 票 007 crs 0:0 (λ=1.9, R13/R16 ok individually) +
# 001 ttg 1球 (λ=2.5) — both individually allowed but the joint failure
# mode is "any goal-fest blows up both legs at once".
POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER = 2.3
# R24 (5/13): when last 3 poisson_solo plans all missed (5/11 + 5/12 + 5/13
# accumulated 70 元 alpha 0 中), the next poisson_solo is hard-capped to a
# single leg regardless of how many +EV rows qualify. Cooling-off matches
# real-world position sizing: when a model goes cold for 3 days straight,
# don't double down. Detection lives in jczq_strategy_memory; the cap is
# applied at the end of `_build_poisson_solo_plan` after R17 has run.
POISSON_SOLO_COOLING_OFF_LOOKBACK = 3
# F4 (5/14): when same-match alpha candidates include both ttg and crs,
# prefer ttg (more robust 0/1/2/3+ buckets) over crs (9-way fine split)
# unless crs edge dominates by F4_DOMINANCE_THRESHOLD. Rule O already forbids
# same-match different-pool combos in one ticket; F4 is the policy for
# *which* alpha to surface when multiple are available for the same match.
F4_DOMINANCE_THRESHOLD = 0.10
# R12 (5/10): false_signal ttg/crs/hafu legs must clear this Poisson edge floor.
# false_signal's premise is "the market over-weighted external narrative; the
# real-strength delta still holds". That premise is for had/hhad. Pools the
# Poisson model can directly price (ttg/crs/hafu) should not be actively
# contradicted by the model. 5/09 周六024 ttg 4球 had edge -19% — the model
# said "no" loudly and the leg lost (actual 1 球). Floor at -10%: anything
# more model-opposed than that is noise, not contrarian narrative.
FALSE_SIGNAL_PRICED_EDGE_FLOOR = -0.10
# R11 (5/10): draw_cluster legs (had 平 in comfort-risk matches) must clear
# this Poisson edge floor. The cluster fires when comfort-risk matches ≥ 3,
# but on 5/09 all 4 picked legs sat between -10% and -13% edge → 0/4. The
# joint EV at 4 × -10% legs is ~3.6 / 1 = 36% per-leg success rate; below
# random. Floor at -8% trades coverage for quality — the cluster shrinks to
# 2-3 legs on dry days rather than betting the spread on negative-EV draws.
DRAW_CLUSTER_EDGE_FLOOR = -0.08
# R9 (5/10): extreme cross-match crs combos must clear quality bars. 5/07 had
# 005 0:0 × 002 0:0 both at +20%-30% edge → joint ~0.6% → 0/2. 5/09 had 010
# 0:0 (edge +7%) × 007 0:0 (edge +35%) — the +7% leg dragged the joint down
# while 007 was the real alpha. Rule J (CRS_POISSON_EDGE_FLOOR = -0.10) only
# blocks model-actively-opposed crs; it doesn't separate "alpha" from "tepid".
# R9 raises the floor for any 2nd+ crs leg in the same ticket: must be ≥ +15%
# AND the ticket's strongest crs must be ≥ +25%. When the bar fails, the
# weaker crs leg is dropped (extreme falls back to a single crs).
EXTREME_CRS_MULTI_LEG_PEAK_EDGE = 0.25
EXTREME_CRS_MULTI_LEG_MIN_EDGE = 0.15
# R18 (5/11): extreme ticket may have at most 1 crs leg in
# EXTREME_CRS_LOW_PICKS (the "low_goals" macro narrative). 5/11 E 票 was
# 001 crs 0:0 × 007 crs 0:1 × 009 crs 0:0 — all three at +20%+ edge, all
# passed R9 (peak +47.8% ≥ 25%, extras +24.5% / +20.3% ≥ 15%) — but the
# joint depends on "all 3 leagues hit ≤1 goal in the same evening" which is
# one narrative bet packaged as three. Keep the strongest by edge; drop
# extras so the ticket forces narrative diversity at the leg level.
EXTREME_CRS_LOW_PICKS = ("0:0", "0:1", "1:0")
# Rule F: bias subtracted from a leg's score when its team is on the burned list.
BURNED_TEAM_BIAS = -0.5
# Rule H: hafu legs hit 0/9 across the 4-day backtest spanning every non-extreme
# plan kind. They are blocked from main / inspiration / contrarian / false_signal
# at the source and stripped post-hoc by `_apply_rule_h_hafu_block`.
RULE_H_NON_EXTREME_HAFU_BLOCKED = True
# R27 (5/15): Rule H upgraded — hafu now drops from EXTREME too. 5/01-5/14
# aggregate: hafu legs 0/18 across all plan kinds (incl. 0/8 in extreme); every
# ticket that contained any hafu leg failed the integer-hit screen (0/18).
# The original carve-out ("hafu still allowed in extreme entertainment lottery")
# is dead weight per the data. `_apply_rule_h_hafu_block` now strips hafu
# unconditionally; extreme drops the hafu leg without replacement so total
# ticket odds stay representative of an entertainment longshot.
RULE_R27_HAFU_FULLY_BLOCKED = True
# R26 (5/15): crs is no longer eligible for poisson_solo. 5/01-5/14 aggregate:
# crs alpha 30 picks → 1 leg-hit (3.3%); 0:0 alone is 1/17 (5.9%); 1:0 0/6,
# 0:1 0/2, 0:2 0/4. Even after R23 raised the 0:0 floor to +25%, 5/14 004
# (λ=2.4, adjusted edge +36.1%) still passed and missed. The model produces an
# "edge" but the joint hit rate is below market-implied across every sub-bucket
# — Poisson on score-grid cells under-models real-world goal-time clustering
# and team scoring rhythm. poisson_solo now restricts eligibility to
# ttg / had / hhad pools. crs remains available in extreme/inspiration where
# diversified narrative absorbs the per-leg miss rate.
RULE_R26_DROP_CRS_FROM_POISSON_SOLO = True
# R28 (5/16): the poisson_solo ticket is retired. 5/01-5/15 aggregate:
# whole-ticket hit 1/11 days, leg-hit 2/16 (12.5%), realized -47.7% over the
# 11-day window (staked 11 units, returned 5.75). The ticket selects the
# single highest-Poisson-edge leg — but "highest model edge" is structurally
# the most over-concentrated bin on the score grid (always ttg 1球 or crs 0:0),
# i.e. adverse selection against the model's own worst-calibrated output. Six
# patches (R17 narrative collapse, R18 crs diversity, R22 hi-vol crs, R23 0:0
# floor, R24 cooling-off, R26 crs-out) treated symptoms; the structure stays
# -EV. Parallels R27 (hafu retired) / R26 (crs out of solo). `_build_poisson_solo_plan`
# is still invoked so cooling-off + the Poisson edge index stay warm and the
# function keeps its unit-test coverage — but the plan is dropped from output.
# A ≥30-day re-review can revive it by flipping this flag to False.
RULE_R28_RETIRE_POISSON_SOLO = True


class JczqTextSender(Protocol):
    def send_message(self, *, chat_id: int, text: str): ...


class JczqDailyAdvisorError(ValueError):
    pass


def select_preferred_alpha_per_match(
    rows: "list[Any]",
    *,
    dominance_threshold: float = F4_DOMINANCE_THRESHOLD,
) -> "list[Any]":
    """F4 (5/14): collapse same-match alpha candidates to one preferred row.

    For each match present in `rows`:
      - If only one row → keep as-is.
      - If multiple rows but only one pool type → keep highest-edge row.
      - If both ttg and crs present → prefer ttg unless `crs.edge - ttg.edge
        >= dominance_threshold` (default +0.10), in which case crs wins.
      - Other pools (had/hhad/hafu) follow highest-edge fallback.

    Returns rows sorted by edge descending (preserves caller's expectation
    of ranked alpha list).
    """

    by_match: dict[str, list[Any]] = {}
    for row in rows:
        match_no = str(getattr(row, "match_no", "") or "")
        if not match_no:
            continue
        by_match.setdefault(match_no, []).append(row)

    selected: list[Any] = []
    for _, match_rows in by_match.items():
        if len(match_rows) == 1:
            selected.append(match_rows[0])
            continue
        ttg_rows = [r for r in match_rows if getattr(r, "pool", "") == "ttg"]
        crs_rows = [r for r in match_rows if getattr(r, "pool", "") == "crs"]
        if ttg_rows and crs_rows:
            best_ttg = max(ttg_rows, key=lambda r: float(getattr(r, "edge", 0.0)))
            best_crs = max(crs_rows, key=lambda r: float(getattr(r, "edge", 0.0)))
            if best_crs.edge - best_ttg.edge >= dominance_threshold:
                selected.append(best_crs)
            else:
                selected.append(best_ttg)
        elif ttg_rows:
            selected.append(max(ttg_rows, key=lambda r: float(getattr(r, "edge", 0.0))))
        elif crs_rows:
            selected.append(max(crs_rows, key=lambda r: float(getattr(r, "edge", 0.0))))
        else:
            selected.append(max(match_rows, key=lambda r: float(getattr(r, "edge", 0.0))))

    selected.sort(key=lambda r: float(getattr(r, "edge", 0.0)), reverse=True)
    return selected


HAD_LABELS = {"h": "胜", "d": "平", "a": "负"}
HHAD_LABELS = {"h": "让胜", "d": "让平", "a": "让负"}
HAFU_LABELS = {
    "hh": "胜/胜",
    "hd": "胜/平",
    "ha": "胜/负",
    "dh": "平/胜",
    "dd": "平/平",
    "da": "平/负",
    "ah": "负/胜",
    "ad": "负/平",
    "aa": "负/负",
}
CRS_LABELS = {
    "s01s00": "1:0",
    "s02s00": "2:0",
    "s02s01": "2:1",
    "s03s01": "3:1",
    "s00s00": "0:0",
    "s01s01": "1:1",
    "s02s02": "2:2",
    "s00s01": "0:1",
    "s00s02": "0:2",
    "s01s02": "1:2",
}
TTG_KEYS = {"s1": "1球", "s2": "2球", "s3": "3球", "s4": "4球", "s5": "5球"}
OPEN_LEAGUE_HINTS = {"挪超", "荷乙", "美职", "德甲"}
CAUTIOUS_LEAGUE_HINTS = {"意甲", "西甲", "法甲"}


class JczqDailyAdvisorService:
    def __init__(
        self,
        *,
        provider: JczqCalculatorProvider | None = None,
        telegram_sender: JczqTextSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        betting_repository: Any | None = None,
        baseline_provider: BaselineProvider | None = None,
        popularity_provider: PopularityProvider | None = None,
        drift_provider: DriftProvider | None = None,
        drift_store: OddsDriftStore | None = None,
        persist_drift_snapshot: bool = False,
    ) -> None:
        self._provider = provider or SportteryJczqCalculatorProvider()
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._betting_repository = betting_repository
        self._baseline_provider = baseline_provider or LeaguePriorBaseline()
        self._popularity_provider = popularity_provider
        self._drift_provider = drift_provider
        self._drift_store = drift_store
        self._persist_drift_snapshot = persist_drift_snapshot
        # Lazy-construct popularity adapter so unit tests with a stub baseline
        # don't pay the import/construction cost.
        if self._popularity_provider is None:
            try:
                _, popularity_adapter = build_default_providers()
                self._popularity_provider = popularity_adapter
            except Exception:  # pragma: no cover - defensive: missing optional deps
                self._popularity_provider = None

    def build_report(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str | None = None,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        revision_instruction: str | None = None,
        record_final: bool = False,
    ) -> JczqDailyAdvisorReport:
        resolved_date = _normalize_date(run_date)
        value = self._provider.fetch()
        matches = self._extract_matches(value, run_date=resolved_date)
        if not matches:
            warnings = ["今日官方接口没有可售竞彩足球比赛。"]
        else:
            warnings = []
        strategy_memory = load_strategy_memory(Path(output_dir)) if output_dir is not None else {}
        drift_provider = self._resolve_drift_provider(
            run_date=resolved_date,
            payload=value,
            output_dir=output_dir,
        )
        league_volatility = compute_league_ttg_volatility(strategy_memory)
        analytics = compute_analytics(
            matches,
            baseline=self._baseline_provider,
            popularity=self._popularity_provider,
            drift=drift_provider,
            league_volatility=league_volatility,
        )
        plans = self._build_plans(
            matches,
            instruction=revision_instruction,
            strategy_memory=strategy_memory,
            analytics=analytics,
        )
        summary = self._summary(
            plans,
            revision_instruction=revision_instruction,
            strategy_memory=strategy_memory,
        )
        report = JczqDailyAdvisorReport(
            run_date=resolved_date,
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            official_last_update=value.get("lastUpdateTime"),
            source_page=getattr(self._provider, "source_page", SPORTTERY_JCZQ_PAGE),
            source_api=getattr(self._provider, "source_api", "unknown"),
            matches=matches,
            plans=plans,
            summary=summary,
            revision={"version": 1, "instruction": revision_instruction},
            warnings=warnings,
        )
        if output_dir is not None:
            report = self._write_artifacts(report, output_dir=Path(output_dir))
        if dispatch_telegram:
            report = self._replace_dispatch(report, self._dispatch(report, dry_run=dry_run))
            if report.artifacts.get("context_path"):
                Path(str(report.artifacts["context_path"])).write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        if record_final and self._betting_repository is not None:
            self._betting_repository.record_jczq_report(report)
        return report

    def revise(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str,
        instruction: str,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        record_final: bool = False,
    ) -> JczqDailyAdvisorReport:
        resolved_date = _normalize_date(run_date)
        context_path = self._context_path(Path(output_dir), resolved_date)
        version = 1
        if context_path.exists():
            try:
                existing = json.loads(context_path.read_text(encoding="utf-8"))
                version = int((existing.get("revision") or {}).get("version") or 1) + 1
                base_report = _report_from_dict(existing)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                version = 2
                base_report = None
        else:
            base_report = None
        if base_report is None:
            report = self.build_report(
                run_date=resolved_date,
                output_dir=output_dir,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                revision_instruction=instruction,
                record_final=record_final,
            )
        else:
            strategy_memory = load_strategy_memory(Path(output_dir))
            analytics = compute_analytics(
                base_report.matches,
                baseline=self._baseline_provider,
                popularity=self._popularity_provider,
                drift=self._drift_provider,
            )
            plans = self._build_plans(
                base_report.matches,
                instruction=instruction,
                strategy_memory=strategy_memory,
                analytics=analytics,
            )
            report = replace(
                base_report,
                generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
                plans=plans,
                summary=self._summary(
                    plans,
                    revision_instruction=instruction,
                    strategy_memory=strategy_memory,
                ),
                dispatch={"status": "skipped"},
            )
            report = self._write_artifacts(report, output_dir=Path(output_dir))
            if dispatch_telegram:
                report = self._replace_dispatch(report, self._dispatch(report, dry_run=dry_run))
        report = replace(
            report,
            revision={"version": version, "instruction": instruction},
        )
        if report.artifacts.get("context_path"):
            Path(str(report.artifacts["context_path"])).write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if record_final and self._betting_repository is not None:
            self._betting_repository.record_jczq_report(report)
        return report

    def render_message(self, report: JczqDailyAdvisorReport) -> str:
        lines = [
            f"【Nutmeg｜{report.run_date} 竞彩足球每日顾问】",
            f"官方赔率更新时间：{report.official_last_update or '未知'}",
            "仅供小注娱乐和赛前分析参考，不保证命中；出票前以竞彩终端为准。",
            "",
            report.summary,
            "",
            "今日盘口热度扫描：",
        ]
        for match in report.matches:
            lines.append(
                f"- {match.match_no} {match.home_team} vs {match.away_team}："
                f"{match.role}；大众方向 {match.hot_direction}；{match.confidence_note}"
            )
        for plan in report.plans:
            lines.extend(["", f"{plan.name}（{plan.kind}）", plan.description])
            legs = " × ".join(f"{leg.match_no}{leg.play}{leg.pick}" for leg in plan.legs)
            lines.append(legs)
            lines.append(
                f"估算总赔率：{plan.total_odds:.2f}；2元理论返奖：{plan.two_yuan_return:.2f}元"
            )
            lines.append(f"风险：{plan.risk_note}")
        if report.revision.get("instruction"):
            lines.extend(["", f"本次修正要求：{report.revision['instruction']}"])
        return "\n".join(lines)

    def _extract_matches(
        self, value: dict[str, Any], *, run_date: str | None = None
    ) -> list[JczqDailyMatch]:
        matches: list[JczqDailyMatch] = []
        for day in value.get("matchInfoList") or []:
            business_date = str(day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            for raw in day.get("subMatchList") or []:
                if str(raw.get("matchStatus") or "").casefold() != "selling":
                    continue
                candidates = self._candidates_for(raw)
                if not candidates:
                    continue
                had = raw.get("had") or {}
                h = _float(had.get("h"))
                d = _float(had.get("d"))
                a = _float(had.get("a"))
                hot = _hot_direction(h, d, a)
                role = _role(h, d, a, raw.get("leagueAbbName"))
                confidence = _confidence_note(h, d, a, role=role)
                matches.append(
                    JczqDailyMatch(
                        match_no=str(raw.get("matchNumStr") or ""),
                        match_date=str(raw.get("matchDate") or ""),
                        match_time=str(raw.get("matchTime") or ""),
                        league=str(raw.get("leagueAbbName") or ""),
                        home_team=str(raw.get("homeTeamAbbName") or ""),
                        away_team=str(raw.get("awayTeamAbbName") or ""),
                        status=str(raw.get("matchStatus") or ""),
                        hot_direction=hot,
                        role=role,
                        confidence_note=confidence,
                        candidates=candidates,
                    )
                )
        return matches

    def _candidates_for(self, raw: dict[str, Any]) -> list[JczqDailyLeg]:
        allowed = _allowed_pools(raw)
        candidates: list[JczqDailyLeg] = []
        base = {
            "match_no": str(raw.get("matchNumStr") or ""),
            "league": str(raw.get("leagueAbbName") or ""),
            "home_team": str(raw.get("homeTeamAbbName") or ""),
            "away_team": str(raw.get("awayTeamAbbName") or ""),
        }
        if "had" in allowed:
            pool = raw.get("had") or {}
            for key, label in HAD_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="had", play="胜平负", key=key, pick=label)
                if leg:
                    candidates.append(replace(leg, logic=_had_logic(label, leg.odds)))
        if "hhad" in allowed:
            pool = raw.get("hhad") or {}
            for key, label in HHAD_LABELS.items():
                leg = _leg(
                    base,
                    pool=pool,
                    pool_name="hhad",
                    play="让球胜平负",
                    key=key,
                    pick=label,
                    goal_line=str(pool.get("goalLine") or ""),
                )
                if leg:
                    candidates.append(replace(leg, logic="用让球盘判断热门方向是否能打穿或被卡。"))
        if "ttg" in allowed:
            pool = raw.get("ttg") or {}
            for key, label in TTG_KEYS.items():
                leg = _leg(base, pool=pool, pool_name="ttg", play="总进球", key=key, pick=label)
                if leg:
                    candidates.append(
                        replace(leg, logic="避开胜负热度，改押比赛节奏和总进球落点。")
                    )
        if "hafu" in allowed:
            pool = raw.get("hafu") or {}
            for key, label in HAFU_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="hafu", play="半全场", key=key, pick=label)
                if leg:
                    candidates.append(
                        replace(leg, logic="用上下半场剧本放大赔率，适合僵持后分胜负。")
                    )
        if "crs" in allowed:
            pool = raw.get("crs") or {}
            for key, label in CRS_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="crs", play="比分", key=key, pick=label)
                if leg:
                    candidates.append(replace(leg, logic="比分是极限灵感入口，只适合极小注。"))
        return candidates

    def _build_plans(
        self,
        matches: list[JczqDailyMatch],
        *,
        instruction: str | None,
        strategy_memory: dict[str, Any] | None = None,
        analytics: dict[str, MatchAnalytics] | None = None,
    ) -> list[JczqDailyPlan]:
        if not matches:
            return []
        memory = strategy_memory or {}
        analytics = analytics if analytics is not None else compute_analytics(
            matches,
            baseline=self._baseline_provider,
            league_volatility=compute_league_ttg_volatility(memory),
        )
        burned_teams = recently_burned_teams(memory)
        memory_bias = _build_memory_bias(memory, burned_teams=burned_teams)
        self._active_bias_fn = memory_bias  # consumed by _search_plan helpers
        # Rule A: precompute Poisson edge index so poisson_solo + report rendering share it.
        # R25 (5/13): apply per-league residual bias for ttg/crs leg edges (法甲
        # 7-sample under-estimate triggers -0.10). Bias is empty when no
        # league qualifies; the call is safe with empty bias.
        # F2 (5/14): apply per-(pool, pick) empirical decay multiplier — corrects
        # systematic over-pricing on picks like crs 0:0 (实测 1/16 vs implied 10%).
        # F3 (5/14): daily alpha concentration warning — when ≥3 distinct matches
        # show ≥+15% alpha all in low_goals direction, apply additional ×0.9
        # decay. F3 detects on RAW alpha (pre-bias), so we need a 2-pass call:
        # first compute raw rows for F3 detection, then re-compute with all biases.
        league_residual_bias = compute_league_residual_bias(memory)
        empirical_decay_map = compute_empirical_decay_map(memory)
        # F1 (5/14): Dixon-Coles tau parameter from memory (default 0.0 disabled)
        dc_rho = get_dixon_coles_rho(memory)
        raw_poisson_rows = compute_poisson_edges(matches, dc_rho=dc_rho)
        daily_concentration_bias = compute_daily_concentration_bias(raw_poisson_rows)
        poisson_rows = compute_poisson_edges(
            matches,
            league_residual_bias=league_residual_bias,
            empirical_decay_map=empirical_decay_map,
            daily_concentration_bias=daily_concentration_bias,
            dc_rho=dc_rho,
        )
        self._active_poisson_index = poisson_edge_index(poisson_rows)
        self._active_analytics = analytics
        self._active_coinflip_match_nos = {
            mn for mn, ana in analytics.items() if ana.is_three_way_coinflip
        }
        no_score = bool(
            instruction and any(word in instruction for word in ["不要比分", "不比分", "不要 比分"])
        )
        target_high = 100 if instruction and ("100" in instruction or "提高" in instruction) else 60
        used_match_nos: set[str] = set()
        stable_base = self._build_stable_base_plan(matches)
        main = self._make_plan(
            "最终主方案",
            "main",
            "用胜平负低赔方向保生命力，把高赔点留给半全场/平局。",
            [
                # Rule B: had bankers must be > 1.40 (>=1.41) to avoid 1.24/1.34-style chalk dumps.
                # R21: had picks below MAIN_HAD_MIN_POISSON_EDGE are filtered.
                _select_leg(
                    matches,
                    used_match_nos,
                    pool="had",
                    min_odds=HAD_BANKER_FLOOR + 0.01,
                    max_odds=1.9,
                    target=1.55,
                    skip_match_nos=self._active_coinflip_match_nos,
                    poisson_idx=self._active_poisson_index,
                    min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE,
                ),
                # Rule H: hafu pool blocked from main; substitute a mid-priced
                # ttg leg, falling back to a hhad cover with handicap.
                (
                    _select_leg(
                        matches,
                        used_match_nos,
                        pool="ttg",
                        min_odds=3.4,
                        max_odds=6.0,
                        target=4.0,
                    )
                    or _select_leg(
                        matches,
                        used_match_nos,
                        pool="hhad",
                        min_odds=2.5,
                        max_odds=4.5,
                        target=3.2,
                    )
                ),
                _select_leg(
                    matches,
                    used_match_nos,
                    pool="had",
                    min_odds=HAD_BANKER_FLOOR + 0.01,
                    max_odds=1.9,
                    target=1.55,
                    skip_match_nos=self._active_coinflip_match_nos,
                    poisson_idx=self._active_poisson_index,
                    min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE,
                ),
                # R21: high-odds had slot (3.0+) also subject to the floor.
                # 5/12 003 had 胜 was 1.67 (covered by slot 1) — slot 4
                # historically picks had 平 / 客胜 picks that often sit at
                # -10% edge too.
                _select_leg(
                    matches,
                    used_match_nos,
                    pool="had",
                    min_odds=3.0,
                    target=3.4,
                    skip_match_nos=self._active_coinflip_match_nos,
                    poisson_idx=self._active_poisson_index,
                    min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE,
                ),
            ],
            "主方案仍依赖一到两个高波动平局/半全场点；Rule B 已禁用 ≤1.40 强胆。",
        )
        inspiration = self._search_plan(
            matches,
            analytics=analytics,
            name="高赔率灵感票",
            kind="inspiration",
            description="跨胜平负、让球、总进球、半全场和比分做乘法杠杆，优先保留可解释剧本。",
            target_min=target_high,
            target_max=3000,
            no_score=no_score,
        )
        contrarian = self._search_plan(
            matches,
            analytics=analytics,
            name="反大众盘口票",
            kind="contrarian",
            description="规避低赔热门胜负，优先选择总进球、半全场、平局和让球卡盘路径。",
            target_min=120,
            target_max=500,
            no_score=no_score,
            contrarian=True,
        )
        false_signal = self._build_false_signal_plan(matches)
        extreme = self._search_plan(
            matches,
            analytics=analytics,
            name="极限小注票",
            kind="extreme",
            description="用比分和半全场追求极高赔率，仅适合极小注娱乐。",
            target_min=300,
            target_max=5000,
            no_score=False,
            extreme=True,
        )
        draw_cluster = self._build_draw_cluster_plan(matches, analytics=analytics)
        upset_cluster = self._build_upset_cluster_plan(matches, analytics=analytics)
        # R1 (5/08): per-league Poisson threshold from rolling residuals.
        poisson_lambda_signals = compute_poisson_lambda_signals(memory)
        poisson_solo = self._build_poisson_solo_plan(
            matches,
            poisson_rows=poisson_rows,
            league_min_edge=poisson_lambda_signals,
            analytics=analytics,
            cooling_off=detect_poisson_solo_cooling_off(memory),
        )
        plans = [
            plan
            for plan in [
                stable_base,
                main,
                poisson_solo,
                inspiration,
                contrarian,
                false_signal,
                extreme,
                draw_cluster,
                upset_cluster,
            ]
            if plan.legs
            # R28 (5/16): poisson_solo ticket retired — see
            # RULE_R28_RETIRE_POISSON_SOLO. The plan is still built above
            # (keeps cooling-off + edge index warm) but excluded from output.
            and not (RULE_R28_RETIRE_POISSON_SOLO and plan.kind == "poisson_solo")
        ]
        plans = self._apply_revision_overrides(plans, matches, instruction=instruction)
        plans = self._apply_memory_overrides(plans, matches, strategy_memory=strategy_memory or {})
        # Rule H/I run before decision_policy so dedup runs against scrubbed
        # plans; they also run again at the end to catch any post-hoc
        # injection from comfort/decorrelation/policy steps.
        plans = self._apply_rule_h_hafu_block(plans, matches)
        plans = self._apply_rule_i_poisson_scrub(plans, matches)
        plans = self._apply_decision_policy(plans, matches, strategy_memory=strategy_memory or {})
        plans = self._apply_comfort_risk_protection(plans, matches)
        plans = self._apply_portfolio_decorrelation(plans, matches, analytics=analytics)
        # Rule L hard cap (R3, 5/08): no match may appear in more than 3 plans.
        # Drops the over-exposed leg from the lowest-priority plan(s); see
        # nutmeg.services.jczq_diagnostics.RULE_L_PLAN_PRIORITY.
        plans = apply_rule_l_concentration_cap(plans)
        # R3.1 (5/09): cap (match, pool, pick) story at 2 plans. 5/08 had
        # 008 ttg 1球 in B + C + E and 011 hhad 让平 in B + D + E — when
        # those signals failed, three plans lost the same leg.
        plans = apply_rule_l_story_cap(plans)
        # Rule N (R4, 5/08): cap main/inspiration to ≤1 late-kickoff leg
        # (Beijing time hour ∈ [6, 12)). 5/07 周四006 (08:30 Beijing) sat
        # in 3 plans and was 'unknown' at the next-day review window.
        late_match_nos = {
            mn for mn, ana in analytics.items() if ana.is_late_kickoff
        }
        plans = apply_rule_n_late_kickoff_cap(plans, late_match_nos=late_match_nos)
        # Rule R6 (5/08): rebalance main plan when any single pool > 60% of
        # legs. 5/07 main was 3 ttg + 1 had (75% ttg) → entire ticket lost
        # to the high-goals result.
        plans = self._apply_rule_r6_main_diversity(plans, matches, analytics=analytics)
        plans = self._apply_rule_h_hafu_block(plans, matches)
        plans = self._apply_rule_i_poisson_scrub(plans, matches)
        return plans

    def _apply_rule_r6_main_diversity(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        analytics: dict[str, MatchAnalytics],
    ) -> list[JczqDailyPlan]:
        """Run enforce_main_plan_pool_diversity on the main plan with
        swap candidates pulled via select_top_legs from un-used matches."""
        main_idx = next(
            (i for i, plan in enumerate(plans) if plan.kind == "main" and plan.legs),
            None,
        )
        if main_idx is None:
            return plans
        main = plans[main_idx]
        used_match_nos = {leg.match_no for leg in main.legs}
        pool_counts: dict[str, int] = {}
        for leg in main.legs:
            pool_counts[leg.pool] = pool_counts.get(leg.pool, 0) + 1
        if not pool_counts:
            return plans
        dominant_pool = max(pool_counts.items(), key=lambda item: item[1])[0]
        bias_fn = getattr(self, "_active_bias_fn", None)
        candidate_pools = {"had", "hhad", "ttg"} - {dominant_pool}
        evaluations = select_top_legs(
            matches,
            analytics,
            intent="main",
            k=10,
            pool_filter=candidate_pools,
            odds_min=HAD_BANKER_FLOOR + 0.01,
            odds_max=8.0,
            avoid_match_nos=used_match_nos,
            enforce_pool_diversity=False,
            bias_fn=bias_fn,
            skip_coinflip_had=True,
            require_hhad_handicap=True,
        )
        # Exclude any (match, pool, pick) already used in any plan so R6
        # doesn't re-introduce a duplicate story that the rest of the
        # pipeline (decorrelation, decision_policy) already deduped.
        used_stories: set[tuple[str, str, str]] = {
            (leg.match_no, leg.pool, leg.pick)
            for plan in plans
            for leg in plan.legs
        }
        swap_candidates = [
            ev.leg
            for ev in evaluations
            if (ev.leg.match_no, ev.leg.pool, ev.leg.pick) not in used_stories
        ]
        new_main = enforce_main_plan_pool_diversity(main, swap_candidates=swap_candidates)
        if new_main is main:
            return plans
        plans = list(plans)
        plans[main_idx] = self._make_plan(
            main.name,
            main.kind,
            main.description,
            list(new_main.legs),
            (main.risk_note + " Rule R6：主方案池多样性已应用。").strip(),
        )
        return plans

    def _apply_rule_i_poisson_scrub(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
    ) -> list[JczqDailyPlan]:
        """Rule I/J safety net: post-hoc overrides (revision, memory,
        decision_policy, comfort_risk_protection, decorrelation) can
        re-introduce legs the Poisson model rejects. Apply per-plan
        thresholds:

        - contrarian:               -0.15 (Rule I-2 model-opposed)
        - main / inspiration / false_signal: -0.20 (strongly opposed —
          matches POISSON_STRONG_OPPOSE_THRESHOLD)
        - extreme:                  -0.10 on crs only (Rule J floor)

        stable_base / cluster plans are heuristic-driven and not in scope.
        """

        poisson_idx = getattr(self, "_active_poisson_index", None)
        if poisson_idx is None:
            return plans
        analytics_idx = getattr(self, "_active_analytics", None) or {}
        kind_thresholds: dict[str, float] = {
            "contrarian": CONTRARIAN_POISSON_REJECT_BELOW,
            "main": POISSON_STRONG_OPPOSE_THRESHOLD,
            "inspiration": POISSON_STRONG_OPPOSE_THRESHOLD,
            "false_signal": POISSON_STRONG_OPPOSE_THRESHOLD,
            # extreme uses CRS_POISSON_EDGE_FLOOR but only on crs pool.
            "extreme": CRS_POISSON_EDGE_FLOOR,
        }
        match_by_no = {match.match_no: match for match in matches}
        cleaned: list[JczqDailyPlan] = []
        for plan in plans:
            threshold = kind_thresholds.get(plan.kind)
            if threshold is None or not plan.legs:
                cleaned.append(plan)
                continue
            kept: list[JczqDailyLeg] = []
            replaced = False
            for leg in plan.legs:
                if leg.pool == "hhad":
                    kept.append(leg)
                    continue
                # Rule J only governs crs in extreme — non-crs legs in extreme
                # (none should exist post Rule H, but defensive) bypass.
                if plan.kind == "extreme" and leg.pool != "crs":
                    kept.append(leg)
                    continue
                edge = poisson_idx.get((leg.match_no, leg.pool, leg.pick))
                if edge is None or edge >= threshold:
                    kept.append(leg)
                    continue
                if plan.kind == "extreme":
                    # Drop the rejected crs leg; let the plan run with fewer
                    # legs rather than swap to an unrelated outcome.
                    replaced = True
                    continue
                ana_for_match = analytics_idx.get(leg.match_no)
                replacement = _rule_i2_contrarian_replacement(
                    match_by_no.get(leg.match_no),
                    poisson_idx,
                    min_edge=threshold,
                    is_strong_banker=(
                        plan.kind == "contrarian"
                        and ana_for_match is not None
                        and ana_for_match.is_strong_banker
                    ),
                )
                if replacement is not None:
                    kept.append(
                        replace(
                            replacement,
                            logic=(
                                f"Rule I：原 {leg.pool} {leg.pick} edge {edge:+.1%}"
                                f" 被模型强反对，替换为 {replacement.pool}。{replacement.logic}"
                            ),
                        )
                    )
                    replaced = True
            if not replaced and len(kept) == len(plan.legs):
                cleaned.append(plan)
                continue
            note = plan.risk_note + (
                f" | Rule I/J：已剥离 Poisson edge ≤ {threshold:+.0%} 的腿。"
            )
            cleaned.append(
                self._make_plan(plan.name, plan.kind, plan.description, kept, note)
            )
        return cleaned

    def _apply_rule_h_hafu_block(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
    ) -> list[JczqDailyPlan]:
        """Rule H (+ R27): hafu hit 0/18 across all plan kinds (5/01-5/14).
        Strip any hafu leg from every plan. For non-extreme plans, substitute
        a ttg or hhad equivalent when possible (preserve ticket structure).
        For extreme plans (R27), drop the leg without replacement — extreme
        ticket odds may shrink but the hafu pool is dead weight per the data.
        """

        match_by_no = {match.match_no: match for match in matches}
        cleaned: list[JczqDailyPlan] = []
        for plan in plans:
            if not any(leg.pool == "hafu" for leg in plan.legs):
                cleaned.append(plan)
                continue
            is_extreme = plan.kind == "extreme"
            new_legs: list[JczqDailyLeg] = []
            for leg in plan.legs:
                if leg.pool != "hafu":
                    new_legs.append(leg)
                    continue
                # R27 (5/15): extreme drops hafu without replacement.
                if is_extreme:
                    continue
                replacement = _rule_h_hafu_replacement(match_by_no.get(leg.match_no))
                if replacement is None:
                    # No safe non-hafu replacement; drop the leg entirely.
                    continue
                new_legs.append(
                    replace(
                        replacement,
                        logic=(
                            "Rule H：半全场 0/9 命中率永久下架，"
                            f"已替换为 {replacement.pool}。{replacement.logic}"
                        ),
                    )
                )
            risk_note = (
                "R27：半全场 0/18 命中率全面下架（含极限票）。"
                if is_extreme
                else "Rule H：半全场已从非极限票剥离。"
            )
            cleaned.append(
                self._make_plan(
                    plan.name,
                    plan.kind,
                    plan.description,
                    new_legs,
                    risk_note,
                )
            )
        return cleaned

    def _build_false_signal_plan(self, matches: list[JczqDailyMatch]) -> JczqDailyPlan:
        legs: list[JczqDailyLeg | None] = []
        used_match_nos: set[str] = set()

        # R12 (5/10): false_signal ttg/crs/hafu legs must clear the
        # FALSE_SIGNAL_PRICED_EDGE_FLOOR; the model-priced pools should not be
        # actively contradicted. 5/09 周六024 ttg 4球 had edge -19% and still
        # entered false_signal → lost (actual 1球). The model-opposed leg is
        # not "false signal", it's noise. had / hhad legs bypass this floor —
        # the plan's premise (反热门/胜负叙事拥挤) lives there.
        poisson_idx = getattr(self, "_active_poisson_index", None)

        def _r12_passes(leg: JczqDailyLeg | None) -> bool:
            if leg is None or poisson_idx is None:
                return leg is not None
            if leg.pool not in {"ttg", "crs", "hafu"}:
                return True
            edge = poisson_idx.get((leg.match_no, leg.pool, leg.pick))
            return edge is None or edge >= FALSE_SIGNAL_PRICED_EDGE_FLOOR

        strong_cover = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_favorite_cover_leg,
            target=2.4,
        )
        if strong_cover is not None and _r12_passes(strong_cover):
            legs.append(
                replace(strong_cover, logic="外部不利叙事可能被资金放大，真实实力差仍支持打穿。")
            )

        comfort_resistance = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_comfort_resistance_leg,
            target=2.2,
        )
        if comfort_resistance is not None and _r12_passes(comfort_resistance):
            legs.append(
                replace(comfort_resistance, logic="热门方向过于顺滑，改用让球保护规避大热陷阱。")
            )

        tactical = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_tactical_process_leg,
            target=4.2,
        )
        if tactical is not None and _r12_passes(tactical):
            legs.append(replace(tactical, logic="胜负叙事拥挤时，改用节奏/过程标的表达判断。"))

        second_cover = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_favorite_cover_leg,
            target=2.4,
        )
        if second_cover is not None and _r12_passes(second_cover):
            legs.append(
                replace(second_cover, logic="不机械反热门，强弱差明确时继续保留打穿表达。")
            )

        return self._make_plan(
            "假信号审问票",
            "false_signal",
            "把天气、轮换、战意、裁判等信息视为市场叙事，识别过度放大的有利/不利因素，再混合让球、过程和节奏标的。",
            legs,
            "假信号票不机械反热门：同时保留大热规避、实力打穿和战术过程标的。",
        )

    def _build_stable_base_plan(self, matches: list[JczqDailyMatch]) -> JczqDailyPlan:
        selected: list[JczqDailyLeg] = []
        used_match_nos: set[str] = set()
        candidates: list[tuple[float, JczqDailyLeg]] = []
        coinflip_match_nos = getattr(self, "_active_coinflip_match_nos", set())
        poisson_idx = getattr(self, "_active_poisson_index", None)

        def _r20_passes(leg: JczqDailyLeg) -> bool:
            """R20 (5/11): stable_base had legs must clear Poisson edge ≥
            STABLE_BASE_HAD_MIN_POISSON_EDGE. Only applies to had pool —
            hhad uses Rule D's goal_line gate + R7.1's hhad floor; comfort
            cover legs handled by their own resistance logic."""
            if leg.pool != "had" or poisson_idx is None:
                return True
            edge = poisson_idx.get((leg.match_no, "had", leg.pick))
            if edge is None:
                return True  # no model coverage — fall back to Rule B alone
            return edge >= STABLE_BASE_HAD_MIN_POISSON_EDGE

        for match in matches:
            if _is_comfort_risk(match):
                # Comfortable favorites can appear only through a protected low-odds cover.
                cover = _comfort_resistance_leg(match)
                if cover is not None and cover.odds <= 2.05 and cover.goal_line:
                    candidates.append((0.15 + abs(cover.odds - 1.75), cover))
                continue
            if match.match_no in coinflip_match_nos:
                # Rule E: coin-flip 3-way matches are not safe banker territory.
                continue
            favorite = _favorite_had_with_odds(match)
            if favorite is not None:
                pick, odds = favorite
                # Rule B: had legs at or below HAD_BANKER_FLOOR are too thin to anchor.
                if HAD_BANKER_FLOOR < odds <= 1.65:
                    leg = _find_leg(match, pool="had", pick=pick)
                    if leg is not None and _r20_passes(leg):
                        role_bonus = -0.25 if match.role == "强胆场" else 0.0
                        candidates.append((role_bonus + abs(leg.odds - 1.55), leg))
            hhad_lows = [
                leg
                for leg in match.candidates
                # Rule D: hhad legs require an explicit handicap line.
                if leg.pool == "hhad"
                and leg.pick in {"让胜", "让负"}
                and leg.odds <= 1.85
                and leg.goal_line
            ]
            if hhad_lows:
                leg = min(hhad_lows, key=lambda item: abs(item.odds - 1.7))
                candidates.append((0.25 + abs(leg.odds - 1.7), leg))
        for _, leg in sorted(candidates, key=lambda item: item[0]):
            if leg.match_no in used_match_nos:
                continue
            selected.append(replace(leg, logic=f"稳健底仓：{leg.logic}"))
            used_match_nos.add(leg.match_no)
            total = 1.0
            for item in selected:
                total *= item.odds
            if len(selected) >= 3 or (len(selected) >= 2 and total >= 8):
                break
        return self._make_plan(
            "稳健底仓A",
            "stable_base",
            "每日持续参与的基础组合，只保留强度明确或已保护的低波动腿。",
            selected,
            "底仓不追大冷，用来维持每日基础；机会票另行承担赔率弹性。",
        )

    def _apply_revision_overrides(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        instruction: str | None,
    ) -> list[JczqDailyPlan]:
        if not instruction:
            return plans
        updated = list(plans)
        wants_half_full_draw_away = "平负" in instruction or "平/负" in instruction
        if not wants_half_full_draw_away:
            return updated
        for match in matches:
            match_tokens = {match.match_no, match.match_no[-3:], match.home_team, match.away_team}
            if not any(token and token in instruction for token in match_tokens):
                continue
            leg = _find_leg(match, pool="hafu", pick="平/负")
            if leg is not None:
                updated = self._inject_leg(
                    updated,
                    target_kind="main",
                    leg=leg,
                    reason="用户修正信号已升权：半全场平/负进入主方案。",
                )
        return updated

    def _apply_memory_overrides(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        strategy_memory: dict[str, Any],
    ) -> list[JczqDailyPlan]:
        if not memory_pattern_positive(strategy_memory, "user_revision_hafu_draw_away"):
            return plans
        updated = list(plans)
        for match in matches:
            if "客胜低赔" not in match.hot_direction and match.role != "谨慎博弈场":
                continue
            leg = _find_leg(match, pool="hafu", pick="平/负")
            if leg is None:
                continue
            updated = self._inject_leg(
                updated,
                target_kind="main",
                leg=leg,
                reason="历史记忆升权：半全场平/负近期有效，已进入主方案。",
            )
            break
        return updated

    def _apply_decision_policy(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        strategy_memory: dict[str, Any],
    ) -> list[JczqDailyPlan]:
        updated = list(plans)
        if decision_policy_rule_active(strategy_memory, "stable_base"):
            updated = [
                self._downgrade_stable_base_by_policy(plan, matches=matches) for plan in updated
            ]
        preferred_ttg = _decision_policy_preferred_ttg(strategy_memory)
        if decision_policy_rule_active(strategy_memory, "hafu"):
            updated = [
                self._replace_hafu_by_policy(plan, matches=matches, preferred_ttg=preferred_ttg)
                for plan in updated
            ]
        if decision_policy_rule_active(strategy_memory, "total_goals"):
            updated = self._ensure_total_goals_policy_leg(
                updated, matches=matches, preferred_ttg=preferred_ttg
            )
        if decision_policy_rule_active(strategy_memory, "reuse_guard"):
            updated = self._limit_duplicate_policy_stories(
                updated,
                matches=matches,
                avoid_hafu=decision_policy_rule_active(strategy_memory, "hafu"),
            )
        return updated

    def _downgrade_stable_base_by_policy(
        self, plan: JczqDailyPlan, *, matches: list[JczqDailyMatch]
    ) -> JczqDailyPlan:
        if plan.kind != "stable_base":
            return plan
        match_by_no = {match.match_no: match for match in matches}
        legs = []
        for leg in plan.legs:
            match = match_by_no.get(leg.match_no)
            is_cold_strong_banker = (
                match is not None
                and match.role == "强胆场"
                and leg.pool == "had"
                and leg.pick in {"胜", "负"}
                and leg.odds <= 1.65
            )
            # Rule B: also strip any had leg priced at or below the banker floor.
            is_thin_had_banker = leg.pool == "had" and leg.odds <= HAD_BANKER_FLOOR
            if not is_cold_strong_banker and not is_thin_had_banker:
                legs.append(leg)
        if len(legs) == len(plan.legs):
            return plan
        if not legs:
            replacement = _low_volatility_policy_leg(matches)
            if replacement is not None:
                legs.append(
                    replace(
                        replacement,
                        logic=f"策略迭代：强胆低赔降权后保留低波动替代。{replacement.logic}",
                    )
                )
        return self._make_plan(
            plan.name,
            plan.kind,
            plan.description,
            legs,
            "策略迭代：强胆低赔近期失真，底仓已降权。",
        )

    def _replace_hafu_by_policy(
        self,
        plan: JczqDailyPlan,
        *,
        matches: list[JczqDailyMatch],
        preferred_ttg: list[str],
    ) -> JczqDailyPlan:
        if not any(leg.pool == "hafu" for leg in plan.legs):
            return plan
        match_by_no = {match.match_no: match for match in matches}
        changed = False
        legs: list[JczqDailyLeg] = []
        is_extreme = plan.kind == "extreme"
        for leg in plan.legs:
            if leg.pool != "hafu":
                legs.append(leg)
                continue
            # R27 (5/15): extreme drops hafu without replacement.
            if is_extreme:
                changed = True
                continue
            replacement = _preferred_total_goals_leg(match_by_no.get(leg.match_no), preferred_ttg)
            if replacement is None:
                replacement = _policy_hhad_fallback(match_by_no.get(leg.match_no))
            if replacement is None:
                legs.append(leg)
                continue
            legs.append(
                replace(
                    replacement,
                    logic=f"策略迭代：半全场近期降权，改用总进球/让球表达。{replacement.logic}",
                )
            )
            changed = True
        if not changed:
            return plan
        risk_note = (
            "R27：半全场 0/18 命中率全面下架（含极限票）。"
            if is_extreme
            else "策略迭代：半全场非极限票降权。"
        )
        return self._make_plan(
            plan.name,
            plan.kind,
            plan.description,
            legs,
            risk_note,
        )

    def _ensure_total_goals_policy_leg(
        self,
        plans: list[JczqDailyPlan],
        *,
        matches: list[JczqDailyMatch],
        preferred_ttg: list[str],
    ) -> list[JczqDailyPlan]:
        if any(
            leg.pool == "ttg" and leg.pick in set(preferred_ttg)
            for plan in plans
            if plan.kind != "extreme"
            for leg in plan.legs
        ):
            return plans
        preferred = _best_total_goals_policy_leg(matches, preferred_ttg)
        if preferred is None:
            return plans
        return self._inject_leg(
            plans,
            target_kind="contrarian",
            leg=replace(
                preferred,
                logic=f"策略迭代：2球/小比分近期升权，进入反大众组合。{preferred.logic}",
            ),
            reason="策略迭代：2球/小比分近期升权。",
        )

    def _limit_duplicate_policy_stories(
        self,
        plans: list[JczqDailyPlan],
        *,
        matches: list[JczqDailyMatch],
        avoid_hafu: bool,
    ) -> list[JczqDailyPlan]:
        match_by_no = {match.match_no: match for match in matches}
        seen: set[tuple[str, str, str]] = set()
        poisson_idx = getattr(self, "_active_poisson_index", None)
        # Rule I: when fixing duplicates, never bring in a Poisson-rejected
        # leg. Use the same per-plan thresholds as `_apply_rule_i2_*_scrub`.
        kind_min_edge = {
            "contrarian": CONTRARIAN_POISSON_REJECT_BELOW,
            "main": POISSON_STRONG_OPPOSE_THRESHOLD,
            "inspiration": POISSON_STRONG_OPPOSE_THRESHOLD,
            "false_signal": POISSON_STRONG_OPPOSE_THRESHOLD,
        }
        updated: list[JczqDailyPlan] = []
        for plan in plans:
            if plan.kind == "extreme":
                updated.append(plan)
                continue
            min_edge = kind_min_edge.get(plan.kind)
            changed = False
            legs: list[JczqDailyLeg] = []
            for leg in plan.legs:
                key = (leg.match_no, leg.pool, leg.pick)
                if key in seen:
                    replacement = _duplicate_story_replacement(
                        match_by_no.get(leg.match_no),
                        seen=seen,
                        avoid_hafu=avoid_hafu,
                        poisson_edge_index=poisson_idx,
                        min_poisson_edge=min_edge,
                    )
                    if replacement is not None:
                        leg = replace(
                            replacement,
                            logic=f"策略迭代：避免同场同玩法重复拖累多张串。{replacement.logic}",
                        )
                        key = (leg.match_no, leg.pool, leg.pick)
                        changed = True
                legs.append(leg)
                seen.add(key)
            if changed:
                updated.append(
                    self._make_plan(
                        plan.name,
                        plan.kind,
                        plan.description,
                        legs,
                        "策略迭代：已限制同场同玩法重复。",
                    )
                )
            else:
                updated.append(plan)
        return updated

    def _apply_comfort_risk_protection(
        self, plans: list[JczqDailyPlan], matches: list[JczqDailyMatch]
    ) -> list[JczqDailyPlan]:
        protected = list(plans)
        for match in [item for item in matches if _is_comfort_risk(item)]:
            favorite = _favorite_had_pick(match)
            # Rule H: never substitute had 平 with hafu 平/平 — hafu locked to extreme only.
            draw_leg = _find_leg(match, pool="had", pick="平")
            cold_pick = "负" if favorite == "胜" else "胜" if favorite == "负" else "平"
            cold_leg = _find_leg(match, pool="had", pick=cold_pick)
            if favorite:
                protected = [
                    self._replace_plan_leg(
                        plan,
                        match_no=match.match_no,
                        current_pool="had",
                        current_pick=favorite,
                        replacement=draw_leg or cold_leg,
                        reason="舒服盘不能作为隐形胆，已替换为防平/防冷保护。",
                    )
                    for plan in protected
                ]
            if draw_leg and not _plans_contain_leg(
                protected, draw_leg.match_no, draw_leg.pool, draw_leg.pick
            ):
                protected = self._inject_leg(
                    protected,
                    target_kind="main",
                    leg=draw_leg,
                    reason="舒服盘审问：已强制加入防平保护。",
                )
            if cold_leg and not _plans_contain_leg(
                protected, cold_leg.match_no, cold_leg.pool, cold_leg.pick
            ):
                protected = self._inject_leg(
                    protected,
                    target_kind="inspiration",
                    leg=cold_leg,
                    reason="舒服盘审问：已强制加入防冷保护。",
                )
        return protected

    def _replace_plan_leg(
        self,
        plan: JczqDailyPlan,
        *,
        match_no: str,
        current_pool: str,
        current_pick: str,
        replacement: JczqDailyLeg | None,
        reason: str,
    ) -> JczqDailyPlan:
        if replacement is None:
            return plan
        changed = False
        legs = []
        for leg in plan.legs:
            if leg.match_no == match_no and leg.pool == current_pool and leg.pick == current_pick:
                legs.append(replacement)
                changed = True
            else:
                legs.append(leg)
        if not changed:
            return plan
        return self._make_plan(plan.name, plan.kind, plan.description, legs, reason)

    def _inject_leg(
        self,
        plans: list[JczqDailyPlan],
        *,
        target_kind: str,
        leg: JczqDailyLeg,
        reason: str,
    ) -> list[JczqDailyPlan]:
        updated: list[JczqDailyPlan] = []
        injected = False
        for plan in plans:
            if not injected and plan.kind == target_kind and plan.legs:
                legs = [item for item in plan.legs if item.match_no != leg.match_no]
                if len(legs) == len(plan.legs):
                    replace_index = _least_protective_leg_index(legs)
                    legs[replace_index] = leg
                else:
                    legs.append(leg)
                updated.append(
                    self._make_plan(plan.name, plan.kind, plan.description, legs, reason)
                )
                injected = True
            else:
                updated.append(plan)
        return updated

    def _search_plan(
        self,
        matches: list[JczqDailyMatch],
        *,
        analytics: dict[str, MatchAnalytics],
        name: str,
        kind: str,
        description: str,
        target_min: float,
        target_max: float,
        no_score: bool,
        contrarian: bool = False,
        extreme: bool = False,
    ) -> JczqDailyPlan:
        intent = "inspiration"
        if extreme:
            intent = "extreme"
        elif contrarian:
            intent = "contrarian"

        if kind == "inspiration":
            selected = self._select_inspiration_legs(
                matches, analytics, no_score=no_score, k=4
            )
        else:
            pool_filter: set[str] | None = None
            if extreme:
                # Rule H: hafu blocked from non-extreme — and Rule J keeps crs as
                # the only extreme pool (Poisson edge floor enforced below).
                pool_filter = {"crs"}
            elif contrarian:
                # Rule H: hafu blocked from contrarian.
                pool_filter = {"ttg", "hhad", "had"}
            odds_min = 4.0 if extreme else (3.0 if contrarian else 1.75)
            odds_max = 999.0 if extreme else 8.0
            poisson_idx = getattr(self, "_active_poisson_index", None)
            pool_min_edge: dict[str, float] | None = None
            high_odds_had_min: tuple[float, float] | None = None
            reject_below: float | None = None
            if extreme:
                # Rule J: crs picks must clear Poisson edge floor.
                pool_min_edge = {"crs": CRS_POISSON_EDGE_FLOOR}
            if contrarian:
                # Rule I-2: drop legs the Poisson model strongly opposes.
                reject_below = CONTRARIAN_POISSON_REJECT_BELOW
            evaluations = select_top_legs(
                matches,
                analytics,
                intent=intent,
                k=4,
                pool_filter=pool_filter,
                odds_min=odds_min,
                odds_max=odds_max,
                enforce_pool_diversity=not extreme,
                bias_fn=getattr(self, "_active_bias_fn", None),
                skip_coinflip_had=True,
                require_hhad_handicap=True,
                poisson_edge_index=poisson_idx,
                pool_min_edge=pool_min_edge,
                high_odds_had_min_edge=high_odds_had_min,
                reject_poisson_edge_below=reject_below,
                # R7.1: drop hhad legs the Poisson model strongly opposes
                hhad_min_edge=HHAD_POISSON_REJECT_BELOW,
                # R19 (5/11): tighter floor for hhad 让平 in main/contrarian.
                # See HHAD_DRAW_MIN_EDGE comment for the draw_friendly bucket
                # vs Poisson verdict contradiction story.
                hhad_draw_min_edge=HHAD_DRAW_MIN_EDGE,
            )
            if no_score:
                evaluations = [ev for ev in evaluations if ev.leg.pool != "crs"]
            selected = [ev.leg for ev in evaluations[:4]]
            # R9 (5/10): extreme tickets with ≥ 2 crs legs need a strong-anchor
            # gate. Strongest must be ≥ +25%; any extra crs leg ≥ +15%.
            # Otherwise the weakest crs is dropped — single-crs extreme is OK.
            if extreme and poisson_idx is not None and selected:
                crs_edges: list[tuple[float, JczqDailyLeg]] = []
                for leg in selected:
                    if leg.pool == "crs":
                        edge = poisson_idx.get((leg.match_no, "crs", leg.pick))
                        if edge is None:
                            continue
                        crs_edges.append((edge, leg))
                if len(crs_edges) >= 2:
                    crs_edges.sort(key=lambda item: item[0], reverse=True)
                    peak = crs_edges[0][0]
                    weak_legs: list[JczqDailyLeg] = []
                    if peak < EXTREME_CRS_MULTI_LEG_PEAK_EDGE:
                        # No leg clears +25%: drop every crs but the strongest.
                        weak_legs = [leg for _, leg in crs_edges[1:]]
                    else:
                        weak_legs = [
                            leg
                            for edge, leg in crs_edges[1:]
                            if edge < EXTREME_CRS_MULTI_LEG_MIN_EDGE
                        ]
                    if weak_legs:
                        weak_ids = {id(leg) for leg in weak_legs}
                        selected = [leg for leg in selected if id(leg) not in weak_ids]
            # R18 (5/11): cap "low_goals" crs narrative legs (0:0/0:1/1:0)
            # at 1 per extreme ticket. R9 controls edge strength but allows
            # narrative concentration; R18 enforces narrative diversity.
            # Keep the strongest by edge; drop the rest. When poisson_idx
            # has no entry for a leg, treat it as edge=0 (so legs without
            # model coverage fall to the bottom of the keep-priority).
            if extreme and selected:
                low_goals_crs: list[tuple[float, JczqDailyLeg]] = []
                for leg in selected:
                    if leg.pool != "crs" or leg.pick not in EXTREME_CRS_LOW_PICKS:
                        continue
                    edge = -1.0
                    if poisson_idx is not None:
                        edge = poisson_idx.get(
                            (leg.match_no, "crs", leg.pick), -1.0
                        )
                    low_goals_crs.append((edge, leg))
                if len(low_goals_crs) >= 2:
                    low_goals_crs.sort(key=lambda item: item[0], reverse=True)
                    drop_ids = {id(leg) for _, leg in low_goals_crs[1:]}
                    selected = [leg for leg in selected if id(leg) not in drop_ids]
        plan = self._make_plan(
            name, kind, description, selected, "高赔票核心风险来自精确进球/半全场/平局落点。"
        )
        if plan.total_odds < target_min and not no_score and selected:
            boosted = []
            existing_match_nos = {leg.match_no for leg in selected}
            for leg in selected:
                match = next((m for m in matches if m.match_no == leg.match_no), None)
                if match is None:
                    boosted.append(leg)
                    continue
                # Rule H (+ R27 5/15): hafu blocked everywhere — including
                # extreme — since 0/18 historical hit rate makes the carve-out
                # dead weight.
                allow_hafu = False
                pool_candidates = [
                    item
                    for item in match.candidates
                    if (
                        item.pool == "crs"
                        or (allow_hafu and item.pool == "hafu")
                    )
                    and item.odds >= 4
                ]
                # Rule J: when boosting extreme, only keep Poisson-supported crs.
                if extreme and poisson_idx is not None:
                    pool_candidates = [
                        item
                        for item in pool_candidates
                        if item.pool != "crs"
                        or (
                            poisson_idx.get((item.match_no, "crs", item.pick), -1.0)
                            >= CRS_POISSON_EDGE_FLOOR
                        )
                    ]
                if no_score:
                    pool_candidates = [item for item in pool_candidates if item.pool != "crs"]
                if not pool_candidates:
                    boosted.append(leg)
                    continue
                boosted.append(
                    max(pool_candidates, key=lambda item: min(item.odds, 10))
                )
            # Backfill if fewer than 4 legs (e.g., very small fixture set).
            if len(boosted) < 4:
                fillers = select_top_legs(
                    matches,
                    analytics,
                    intent=intent,
                    k=4,
                    avoid_match_nos=existing_match_nos,
                    enforce_pool_diversity=False,
                    bias_fn=getattr(self, "_active_bias_fn", None),
                )
                for ev in fillers:
                    if len(boosted) >= 4:
                        break
                    if ev.leg.match_no in {item.match_no for item in boosted}:
                        continue
                    boosted.append(ev.leg)
            plan = self._make_plan(
                name, kind, description, boosted, "赔率已提高，但命中波动显著增加。"
            )
        if plan.total_odds > target_max and kind != "extreme":
            softened = []
            for leg in plan.legs:
                alternatives = [
                    candidate
                    for match in matches
                    for candidate in match.candidates
                    if candidate.match_no == leg.match_no and candidate.odds <= max(5.5, leg.odds)
                ]
                softened.append(min(alternatives or [leg], key=lambda item: abs(item.odds - 3.5)))
            plan = self._make_plan(
                name, kind, description, softened, "已控制赔率上限，但仍属于高波动组合。"
            )
        return plan

    def _select_inspiration_legs(
        self,
        matches: list[JczqDailyMatch],
        analytics: dict[str, MatchAnalytics],
        *,
        no_score: bool,
        k: int,
    ) -> list[JczqDailyLeg]:
        """Pick one leg per pool from the highest-EV match for that pool.

        Preserves the historic "inspiration spans 4 distinct pools" guarantee
        while letting the search consider the full match list (no more
        `matches[:4]` truncation).
        """

        # Rule H: hafu dropped from inspiration pool order.
        pool_order = ["had", "hhad", "ttg"]
        if not no_score:
            pool_order.append("crs")
        used_match_nos: set[str] = set()
        legs: list[JczqDailyLeg] = []
        poisson_idx = getattr(self, "_active_poisson_index", None)
        # Rule I-1: high-odds had legs (≥ 5.0) need Poisson EV ≥ +5%.
        high_odds_had_min = (HIGH_ODDS_HAD_THRESHOLD, HIGH_ODDS_HAD_REQUIRED_EDGE)
        # Rule J: inspiration's optional crs slot must clear the same floor.
        pool_min_edge = {"crs": CRS_POISSON_EDGE_FLOOR}
        for pool in pool_order:
            if len(legs) >= k:
                break
            evaluations = select_top_legs(
                matches,
                analytics,
                intent="inspiration",
                k=20,
                pool_filter={pool},
                odds_min=1.75,
                odds_max=8.0,
                avoid_match_nos=used_match_nos,
                enforce_pool_diversity=False,
                bias_fn=getattr(self, "_active_bias_fn", None),
                skip_coinflip_had=True,
                require_hhad_handicap=True,
                poisson_edge_index=poisson_idx,
                pool_min_edge=pool_min_edge,
                high_odds_had_min_edge=high_odds_had_min,
            )
            for ev in evaluations:
                if ev.leg.match_no in used_match_nos:
                    continue
                legs.append(ev.leg)
                used_match_nos.add(ev.leg.match_no)
                break
        if len(legs) < k:
            fillers = select_top_legs(
                matches,
                analytics,
                intent="inspiration",
                k=20,
                avoid_match_nos=used_match_nos,
                enforce_pool_diversity=False,
                bias_fn=getattr(self, "_active_bias_fn", None),
                poisson_edge_index=poisson_idx,
                pool_min_edge=pool_min_edge,
                high_odds_had_min_edge=high_odds_had_min,
            )
            for ev in fillers:
                if len(legs) >= k:
                    break
                if ev.leg.match_no in used_match_nos:
                    continue
                if no_score and ev.leg.pool == "crs":
                    continue
                # Rule H: hafu blocked from inspiration even in fallback path.
                if ev.leg.pool == "hafu":
                    continue
                legs.append(ev.leg)
                used_match_nos.add(ev.leg.match_no)
        return legs[:k]

    def _build_draw_cluster_plan(
        self,
        matches: list[JczqDailyMatch],
        *,
        analytics: dict[str, MatchAnalytics],
    ) -> JczqDailyPlan:
        """Dedicated draw-only ticket activated when comfort-risk count ≥ 3.

        Each leg is a 平 (had) pick on a comfort-risk match, ranked by
        draw-friendliness EV gap. Threshold prevents this from firing in tiny
        fixture sets (e.g., the 4-match unit test fixture). Rule H: hafu 平/平
        is no longer eligible — non-extreme plans are hafu-blocked.
        """

        comfort_matches = [
            match
            for match in matches
            if (analytics.get(match.match_no) and analytics[match.match_no].is_comfort_risk)
        ]
        if len(comfort_matches) < 3:
            return self._make_plan(
                "防平簇A",
                "draw_cluster",
                "舒服盘 ≥ 3 场时启用：一张专攻平局的独立票。",
                [],
                "防平簇仅在舒服盘集群足够厚时出场。",
            )
        evaluations = select_top_legs(
            comfort_matches,
            analytics,
            intent="draw",
            k=4,
            pool_filter={"had"},  # Rule H: hafu blocked from draw_cluster.
            odds_min=2.4,
            odds_max=8.0,
            enforce_pool_diversity=False,
            bias_fn=getattr(self, "_active_bias_fn", None),
            skip_coinflip_had=True,
            require_hhad_handicap=True,
        )
        legs: list[JczqDailyLeg] = []
        seen_matches: set[str] = set()
        # R11 (5/10): apply Poisson edge floor to the had 平 picks. 5/09 4
        # legs all sat at -10% to -13% edge → 0/4. Floor trims to 2-3 legs
        # on dry days rather than spraying negative-EV draws.
        poisson_idx = getattr(self, "_active_poisson_index", None)
        for ev in evaluations:
            leg = ev.leg
            if leg.match_no in seen_matches:
                continue
            if leg.pool == "had" and leg.pick != "平":
                continue
            if poisson_idx is not None:
                edge = poisson_idx.get((leg.match_no, leg.pool, leg.pick))
                if edge is not None and edge < DRAW_CLUSTER_EDGE_FLOOR:
                    continue
            legs.append(replace(leg, logic=f"防平簇：{leg.logic} EV gap {ev.ev_gap:+.2f}"))
            seen_matches.add(leg.match_no)
            if len(legs) >= 4:
                break
        return self._make_plan(
            "防平簇A",
            "draw_cluster",
            "舒服盘集群专属：用平局/平半全场吃掉热门塌房。",
            legs,
            "防平簇与主方案完全解耦，不再让 main 一边防一边输。",
        )

    def _build_upset_cluster_plan(
        self,
        matches: list[JczqDailyMatch],
        *,
        analytics: dict[str, MatchAnalytics],
    ) -> JczqDailyPlan:
        """Dedicated upset ticket activated when strong-banker count ≥ 3."""

        strong_matches = [
            match
            for match in matches
            if (analytics.get(match.match_no) and analytics[match.match_no].is_strong_banker)
        ]
        if len(strong_matches) < 3:
            return self._make_plan(
                "冷门簇A",
                "upset_cluster",
                "强胆 ≥ 3 场时启用：专攻让球反向/客胜/平局塌房。",
                [],
                "冷门簇仅在低赔强胆集群足够厚时出场。",
            )
        evaluations = select_top_legs(
            strong_matches,
            analytics,
            intent="upset",
            k=4,
            pool_filter={"hhad", "had"},
            odds_min=2.0,
            odds_max=12.0,
            enforce_pool_diversity=False,
            bias_fn=getattr(self, "_active_bias_fn", None),
            skip_coinflip_had=True,
            require_hhad_handicap=True,
        )
        legs: list[JczqDailyLeg] = []
        seen_matches: set[str] = set()
        for ev in evaluations:
            leg = ev.leg
            if leg.match_no in seen_matches:
                continue
            ana = analytics.get(leg.match_no)
            if ana is None:
                continue
            if leg.pool == "had" and leg.pick == ana.favorite_outcome:
                continue
            if leg.pool == "hhad" and leg.pick == "让胜" and ana.favorite_outcome == "胜":
                continue
            if leg.pool == "hhad" and leg.pick == "让负" and ana.favorite_outcome == "负":
                continue
            legs.append(replace(leg, logic=f"冷门簇：{leg.logic} EV gap {ev.ev_gap:+.2f}"))
            seen_matches.add(leg.match_no)
            if len(legs) >= 4:
                break
        return self._make_plan(
            "冷门簇A",
            "upset_cluster",
            "强胆集群专属：用让球反向/客胜/平局博低赔翻车。",
            legs,
            "冷门簇承担反人性风险，不会污染主方案的稳定性。",
        )

    def _build_poisson_solo_plan(
        self,
        matches: list[JczqDailyMatch],
        *,
        poisson_rows: list,
        league_min_edge: dict[str, dict[str, Any]] | None = None,
        analytics: dict[str, "MatchAnalytics"] | None = None,
        cooling_off: bool = False,
    ) -> JczqDailyPlan:
        """Rule A v2 (5/07 redesign after sport.gov.cn rule reminder).

        Original Rule A v2 ("crs requires same-match support pairing") was scrapped
        because 国家体彩 forbids same-match different-pool combinations in one parlay.

        Current behavior:
          - eligible = rows with edge >= POISSON_SOLO_EDGE_THRESHOLD (default +15%)
          - Pick top eligible rows (sorted by edge), at most 2 legs, all from
            DIFFERENT matches. Pool type doesn't matter — crs solo is fine since
            +15% edge translates to acceptable EV even at ~10% hit rate.
          - Optionally extend to a 2nd leg using a CROSS-MATCH +EV row at edge
            >= POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE (default +5%).
          - Same-match support rows are surfaced in brief Section 5b as analysis
            evidence ONLY — never combined into the ticket's legs.

        See `nutmeg.services.jczq_diagnostics.check_same_match_pool_legality`
        which post-validates plans against this rule.
        """

        # R1: per-league dynamic threshold for crs picks. Default is
        # POISSON_SOLO_EDGE_THRESHOLD (+15%); leagues flagged for systematic
        # under-pricing of goals get the raised floor (e.g., +25%).
        signals = league_min_edge or {}

        def _row_threshold(row) -> float:
            base = POISSON_SOLO_EDGE_THRESHOLD
            # R23 (5/13): crs 0:0 floor raised to +25% globally based on 10-day
            # 1/16 = 6.25% hit rate. Applied before R1 per-league signals so
            # the league signal can raise it further but never lower it.
            if row.pool == "crs" and row.pick == "0:0":
                base = max(base, POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE)
            if row.pool != "crs":
                return base
            sig = signals.get(row.league)
            if not sig:
                return base
            recommended = float(sig.get("recommended_crs_min_edge") or base)
            return max(base, recommended)

        def _r13_consistent(row) -> bool:
            """R13: ttg low-goal picks must agree with the model's expected
            goals. expected_goals defaults to 0 on synthetic fixtures; treat 0
            as "unknown" and skip the gate so legacy tests stay green."""
            if row.pool != "ttg" or row.pick not in POISSON_SOLO_TTG_LOW_PICKS:
                return True
            if row.expected_goals <= 0:
                return True
            return row.expected_goals < POISSON_SOLO_TTG_LOW_GOAL_THRESHOLD

        def _is_low_goals_narrative(leg: JczqDailyLeg) -> bool:
            """R17 helper: ttg 0/1/2球 or crs 0:0/0:1/1:0."""
            if leg.pool == "ttg" and leg.pick in POISSON_SOLO_TTG_LOW_PICKS:
                return True
            if leg.pool == "crs" and leg.pick in POISSON_SOLO_CRS_LOW_PICKS:
                return True
            return False

        # R22 (5/13): hi-vol 联赛 crs 低进球三花 (0:0/0:1/1:0) hard reject from
        # poisson_solo. 10-day aggregate: crs low-goals alpha hits 1/24 = 4.2%
        # (vs implied 25-40%); 5/13 D 票 004 (西甲 hi-vol+coinflip) 0:0 +28.6%
        # alpha 实际 2:0. league hi-vol 标志由 compute_analytics 计算 (override
        # 联赛 + ttg-volatility 信号)。`analytics` 为 None 时（合成测试）跳过
        # — 仅在生产路径 (build_report 注入) 触发。
        ana_map = analytics or {}

        def _r22_hi_vol_crs_blocked(row) -> bool:
            if row.pool != "crs" or row.pick not in POISSON_SOLO_CRS_LOW_PICKS:
                return False
            ana = ana_map.get(row.match_no)
            return ana is not None and ana.is_high_volatility_league

        eligible = [
            row
            for row in poisson_rows
            if row.edge >= _row_threshold(row)
            and _r13_consistent(row)
            and not _r22_hi_vol_crs_blocked(row)
            # R26 (5/15): crs pool blocked from poisson_solo (1/30 historical
            # leg-hit). Other pools (ttg/had/hhad) still eligible; crs alpha
            # routes to inspiration/extreme via _search_plan.
            and (not RULE_R26_DROP_CRS_FROM_POISSON_SOLO or row.pool != "crs")
        ]
        # F4 (5/14): same-match alpha preference — collapse multiple alpha
        # candidates per match to one row using ttg-over-crs preference
        # (unless crs edge dominates by F4_DOMINANCE_THRESHOLD). Reduces
        # narrative concentration when same-match alpha appears in multiple
        # pools (e.g., 5/14 004 had both crs 0:0 +36% and ttg 1球 +20%).
        if eligible:
            eligible = select_preferred_alpha_per_match(eligible)
        if not eligible:
            return self._make_plan(
                "Poisson 单核灵感票",
                "poisson_solo",
                "Rule A v2: 至少 1 条腿 Poisson edge ≥ +15% 时启用；跨场组合，不同场不同玩法。",
                [],
                "Poisson 单核仅在模型有强信号时出场。",
            )
        match_index: dict[str, JczqDailyMatch] = {
            match.match_no: match for match in matches
        }

        def _is_thin_had_banker(leg: JczqDailyLeg) -> bool:
            return leg.pool == "had" and leg.odds <= HAD_BANKER_FLOOR

        def _build_leg(row, match: JczqDailyMatch) -> JczqDailyLeg | None:
            leg = _find_leg(match, pool=row.pool, pick=row.pick)
            if leg is None:
                return None
            if _is_thin_had_banker(leg):
                return None
            return replace(
                leg,
                logic=(
                    f"Poisson 单核：edge {row.edge:+.1%}"
                    f"（公允 {row.fair_odd}），模型主动支持。"
                ),
            )

        legs: list[JczqDailyLeg] = []
        seen_matches: set[str] = set()
        crs_count = 0

        # Pass 1: take top eligible rows from distinct matches (max 2).
        # Rule A v3 (R5): cap crs legs at POISSON_SOLO_MAX_CRS_LEGS — a 2nd
        # crs leg from a different match has joint hit rate ~0.6% which is
        # not "alpha" regardless of individual edge. Skip extra crs rows
        # and let Pass 2 fill the slot from a different pool's +EV row.
        for row in eligible:
            if len(legs) >= 2:
                break
            if row.match_no in seen_matches:
                continue  # Rule O: never combine two legs from the same match.
            if row.pool == "crs" and crs_count >= POISSON_SOLO_MAX_CRS_LEGS:
                continue
            match = match_index.get(row.match_no)
            if match is None:
                continue
            built = _build_leg(row, match)
            if built is None:
                continue
            legs.append(built)
            seen_matches.add(row.match_no)
            if row.pool == "crs":
                crs_count += 1

        # Pass 2: fill 2nd slot from cross-match +EV rows at >=
        # POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE if Pass 1 produced only 1
        # leg. Same R5 cap on crs applies here.
        if len(legs) == 1:
            cross_support = [
                row
                for row in poisson_rows
                if row.match_no not in seen_matches
                and row.edge >= POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE
                and _r13_consistent(row)
                and not _r22_hi_vol_crs_blocked(row)
            ]
            for row in cross_support:
                if row.pool == "crs" and crs_count >= POISSON_SOLO_MAX_CRS_LEGS:
                    continue
                match = match_index.get(row.match_no)
                if match is None:
                    continue
                built = _build_leg(row, match)
                if built is None:
                    continue
                legs.append(built)
                seen_matches.add(row.match_no)
                if row.pool == "crs":
                    crs_count += 1
                break

        # R17 (5/11): when both selected legs are low_goals narrative AND
        # any leg's expected_goals ≥ POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER,
        # collapse to a single leg — keep the highest-edge leg, drop the
        # other. Prevents same-macro-narrative concentration where one
        # high-scoring evening kills both legs (5/11 C 票 007 0:0 + 001
        # ttg 1球 joint ≈ 3% hit). Keeping the highest-edge leg preserves
        # the strongest model conviction; the 5/04 regression confirms
        # this is also the leg most likely to be the actual winner
        # (007 0:0 +21.6% edge was the day's actual hit).
        if len(legs) == 2 and all(_is_low_goals_narrative(leg) for leg in legs):
            row_by_key = {
                (row.match_no, row.pool, row.pick): row for row in poisson_rows
            }
            legs_with_meta: list[tuple[float, float, JczqDailyLeg]] = []
            for leg in legs:
                row = row_by_key.get((leg.match_no, leg.pool, leg.pick))
                lam = float(getattr(row, "expected_goals", 0.0) or 0.0) if row else 0.0
                edge = float(getattr(row, "edge", 0.0) or 0.0) if row else 0.0
                legs_with_meta.append((lam, edge, leg))
            max_lambda = max(lam for lam, _, _ in legs_with_meta)
            if max_lambda >= POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER:
                # Keep the highest-edge leg.
                legs_with_meta.sort(key=lambda item: item[1], reverse=True)
                legs = [legs_with_meta[0][2]]
        # R24 (5/13): cooling-off cap — last 3 poisson_solo plans all missed.
        # Hard-cap to 1 leg (keep highest-edge leg) regardless of R17 outcome.
        # No-op when cooling_off=False or already ≤ 1 leg.
        description_extra = ""
        if cooling_off and len(legs) >= 2:
            row_by_key = {
                (row.match_no, row.pool, row.pick): row for row in poisson_rows
            }
            legs_with_edge: list[tuple[float, JczqDailyLeg]] = []
            for leg in legs:
                row = row_by_key.get((leg.match_no, leg.pool, leg.pick))
                edge = float(getattr(row, "edge", 0.0) or 0.0) if row else 0.0
                legs_with_edge.append((edge, leg))
            legs_with_edge.sort(key=lambda item: item[0], reverse=True)
            legs = [legs_with_edge[0][1]]
            description_extra = "（R24 cooling-off：最近 3 天 poisson_solo 连失，本轮限 1 腿）"
        return self._make_plan(
            "Poisson 单核灵感票",
            "poisson_solo",
            "Rule A v2: 跨场 +EV 腿组合（同场不同玩法不可混合过关，"
            f"国家体彩规则）。{description_extra}",
            legs,
            "Poisson 单核小注娱乐：腿少杠杆高，赔率波动大。",
        )

    def _apply_portfolio_decorrelation(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        analytics: dict[str, MatchAnalytics],
    ) -> list[JczqDailyPlan]:
        """Across opportunity tickets, ensure no match appears in more than one.

        Stable_base / main / false_signal / draw_cluster / upset_cluster are
        exempt — the constraint targets `inspiration`, `contrarian`, `extreme`
        which previously shared the same first-4 matches.
        """

        opportunity_kinds = ("inspiration", "contrarian", "extreme")
        seen_match_nos: dict[str, str] = {}
        updated: list[JczqDailyPlan] = []
        for plan in plans:
            if plan.kind not in opportunity_kinds or not plan.legs:
                updated.append(plan)
                continue
            new_legs: list[JczqDailyLeg] = []
            taken: set[str] = {leg.match_no for leg in plan.legs}
            for leg in plan.legs:
                conflict = seen_match_nos.get(leg.match_no)
                if conflict is None or conflict == plan.kind:
                    new_legs.append(leg)
                    seen_match_nos[leg.match_no] = plan.kind
                    continue
                replacement = self._find_decorrelation_swap(
                    matches=matches,
                    analytics=analytics,
                    plan_kind=plan.kind,
                    avoid=seen_match_nos.keys() | taken,
                    pool_hint=leg.pool,
                )
                if replacement is None:
                    new_legs.append(leg)
                    continue
                new_legs.append(replace(replacement, logic=f"组合去相关：{replacement.logic}"))
                seen_match_nos[replacement.match_no] = plan.kind
                taken.add(replacement.match_no)
            updated.append(
                self._make_plan(
                    plan.name,
                    plan.kind,
                    plan.description,
                    new_legs,
                    "组合去相关已应用：跨 opportunity 票同场最多复用 1 次。",
                )
            )
        return updated

    def _find_decorrelation_swap(
        self,
        *,
        matches: list[JczqDailyMatch],
        analytics: dict[str, MatchAnalytics],
        plan_kind: str,
        avoid: Any,
        pool_hint: str | None,
    ) -> JczqDailyLeg | None:
        intent_map = {
            "inspiration": "inspiration",
            "contrarian": "contrarian",
            "extreme": "extreme",
        }
        intent = intent_map.get(plan_kind, "inspiration")
        bias_fn = getattr(self, "_active_bias_fn", None)
        avoid_set = set(avoid)

        # Tier 1: same pool as the conflicting leg (preserve plan composition).
        if pool_hint:
            evaluations = select_top_legs(
                matches,
                analytics,
                intent=intent,
                k=30,
                pool_filter={pool_hint},
                odds_min=1.3,
                odds_max=999.0,
                avoid_match_nos=avoid_set,
                enforce_pool_diversity=False,
                bias_fn=bias_fn,
                skip_coinflip_had=True,
                require_hhad_handicap=True,
            )
            for ev in evaluations:
                if ev.leg.match_no not in avoid_set:
                    return ev.leg

        # Tier 2: drop the pool restriction; any pool of the same intent works.
        evaluations = select_top_legs(
            matches,
            analytics,
            intent=intent,
            k=30,
            odds_min=1.3,
            odds_max=999.0,
            avoid_match_nos=avoid_set,
            enforce_pool_diversity=False,
            bias_fn=bias_fn,
            skip_coinflip_had=True,
            require_hhad_handicap=True,
        )
        for ev in evaluations:
            if ev.leg.match_no not in avoid_set:
                return ev.leg

        # Tier 3: any leg from any unused match — last-resort backstop so the
        # decorrelation pass never surfaces a duplicate when alternatives exist.
        for match in matches:
            if match.match_no in avoid_set:
                continue
            if not match.candidates:
                continue
            return match.candidates[0]
        return None

    def _resolve_drift_provider(
        self,
        *,
        run_date: str,
        payload: dict[str, Any],
        output_dir: Path | str | None,
    ) -> DriftProvider | None:
        """Persist the latest snapshot when configured and expose drift signals."""

        if self._drift_provider is not None:
            return self._drift_provider
        store = self._drift_store
        if store is None and output_dir is not None and self._persist_drift_snapshot:
            store = OddsDriftStore(Path(output_dir))
        if store is None:
            return None
        if self._persist_drift_snapshot:
            try:
                store.persist(run_date=run_date, payload=payload)
            except Exception:  # pragma: no cover - filesystem edge cases
                pass
        signals = store.compute_drift(run_date)
        if not signals:
            return None
        signal_index = drift_provider_from_signals(signals)
        return _DictDriftProvider(signal_index)

    def _make_plan(
        self,
        name: str,
        kind: str,
        description: str,
        legs: list[JczqDailyLeg | None],
        risk_note: str,
    ) -> JczqDailyPlan:
        clean = [leg for leg in legs if leg is not None]
        total = 1.0
        for leg in clean:
            total *= leg.odds
        total = round(total, 2) if clean else 0.0
        return JczqDailyPlan(
            name=name,
            kind=kind,
            description=description,
            legs=clean,
            total_odds=total,
            two_yuan_return=round(total * 2, 2),
            risk_note=risk_note,
        )

    def _summary(
        self,
        plans: list[JczqDailyPlan],
        *,
        revision_instruction: str | None,
        strategy_memory: dict[str, Any] | None = None,
    ) -> str:
        main = next((plan for plan in plans if plan.kind == "main"), None)
        stable = next((plan for plan in plans if plan.kind == "stable_base"), None)
        inspiration = next((plan for plan in plans if plan.kind == "inspiration"), None)
        text = (
            "每日固定仓位：先保留1-2张稳健底仓，再用机会票捕捉有逻辑的反人性赔率。"
            "舒服盘审问已启用：1.75-2.05的非强胆热门必须防平防冷。"
            "假信号审问已启用：外部信息先视为资金叙事，再判断真实实力差是否被遮蔽。"
        )
        if stable:
            text += f" 稳健底仓约{stable.total_odds:.2f}倍。"
        if main and inspiration:
            text += (
                f" 最终主方案约{main.total_odds:.2f}倍，"
                f"高赔率灵感票约{inspiration.total_odds:.2f}倍。"
            )
        poisson_solo = next((plan for plan in plans if plan.kind == "poisson_solo"), None)
        draw_cluster = next((plan for plan in plans if plan.kind == "draw_cluster"), None)
        upset_cluster = next((plan for plan in plans if plan.kind == "upset_cluster"), None)
        if poisson_solo and poisson_solo.legs:
            text += (
                f" Poisson 单核约{poisson_solo.total_odds:.2f}倍"
                f"（{len(poisson_solo.legs)} 腿，模型 +EV ≥15%）。"
            )
        if draw_cluster and draw_cluster.legs:
            text += f" 防平簇约{draw_cluster.total_odds:.2f}倍（独立于 main）。"
        if upset_cluster and upset_cluster.legs:
            text += f" 冷门簇约{upset_cluster.total_odds:.2f}倍（强胆塌房专用）。"
        memory_notes = render_strategy_memory_notes(strategy_memory or {})
        if memory_notes:
            text += " 历史记忆提示：" + "；".join(memory_notes) + "。"
        policy_notes = render_decision_policy_notes(strategy_memory or {})
        if policy_notes:
            text += " 策略迭代执行：" + "；".join(policy_notes) + "。"
        if revision_instruction:
            text += f" 已按你的修正想法重算：{revision_instruction}。"
        return text

    def _write_artifacts(
        self, report: JczqDailyAdvisorReport, *, output_dir: Path
    ) -> JczqDailyAdvisorReport:
        run_dir = output_dir / "daily" / report.run_date
        run_dir.mkdir(parents=True, exist_ok=True)
        context_path = run_dir / "context.json"
        markdown_path = run_dir / "report.md"
        artifacts = {"context_path": str(context_path), "markdown_path": str(markdown_path)}
        enriched = replace(report, artifacts=artifacts)
        markdown_path.write_text(self.render_message(enriched), encoding="utf-8")
        context_path.write_text(
            json.dumps(enriched.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return enriched

    def _dispatch(self, report: JczqDailyAdvisorReport, *, dry_run: bool) -> dict[str, Any]:
        text = self.render_message(report)
        if dry_run:
            return {
                "status": "dry_run",
                "chat_ids": list(self._telegram_chat_ids),
                "caption": text[:120],
            }
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return {
                "status": "skipped",
                "chat_ids": list(self._telegram_chat_ids),
                "error": "telegram not configured",
            }
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_message(chat_id=chat_id, text=text)
        except Exception as exc:  # pragma: no cover - defensive network seam
            return {
                "status": "failed",
                "chat_ids": list(self._telegram_chat_ids),
                "error": str(exc),
            }
        return {"status": "sent", "chat_ids": list(self._telegram_chat_ids)}

    def _replace_dispatch(
        self, report: JczqDailyAdvisorReport, dispatch: dict[str, Any]
    ) -> JczqDailyAdvisorReport:
        return replace(report, dispatch=dispatch)

    def _context_path(self, output_dir: Path, run_date: str) -> Path:
        return output_dir / "daily" / run_date / "context.json"


def build_jczq_daily_provider(provider: str) -> JczqCalculatorProvider:
    key = provider.strip().casefold()
    if key == "live":
        return SportteryJczqCalculatorProvider()
    if key == "sample":
        return SampleJczqCalculatorProvider()
    raise JczqDailyAdvisorError("provider must be `live` or `sample`.")


def _report_from_dict(payload: dict[str, Any]) -> JczqDailyAdvisorReport:
    matches = [_match_from_dict(item) for item in payload.get("matches") or []]
    plans = [
        JczqDailyPlan(
            name=str(item.get("name") or ""),
            kind=str(item.get("kind") or ""),
            description=str(item.get("description") or ""),
            legs=[_leg_from_dict(leg) for leg in item.get("legs") or []],
            total_odds=float(item.get("total_odds") or 0),
            two_yuan_return=float(item.get("two_yuan_return") or 0),
            risk_note=str(item.get("risk_note") or ""),
        )
        for item in payload.get("plans") or []
    ]
    return JczqDailyAdvisorReport(
        run_date=str(payload.get("run_date") or _normalize_date(None)),
        generated_at=str(payload.get("generated_at") or ""),
        official_last_update=payload.get("official_last_update"),
        source_page=str(payload.get("source_page") or SPORTTERY_JCZQ_PAGE),
        source_api=str(payload.get("source_api") or "unknown"),
        matches=matches,
        plans=plans,
        summary=str(payload.get("summary") or ""),
        revision=dict(payload.get("revision") or {"version": 1}),
        artifacts=dict(payload.get("artifacts") or {}),
        dispatch=dict(payload.get("dispatch") or {"status": "skipped"}),
        warnings=[str(item) for item in payload.get("warnings") or []],
    )


def _match_from_dict(payload: dict[str, Any]) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=str(payload.get("match_no") or ""),
        match_date=str(payload.get("match_date") or ""),
        match_time=str(payload.get("match_time") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        status=str(payload.get("status") or ""),
        hot_direction=str(payload.get("hot_direction") or ""),
        role=str(payload.get("role") or ""),
        confidence_note=str(payload.get("confidence_note") or ""),
        candidates=[_leg_from_dict(item) for item in payload.get("candidates") or []],
    )


def _leg_from_dict(payload: dict[str, Any]) -> JczqDailyLeg:
    return JczqDailyLeg(
        match_no=str(payload.get("match_no") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        pool=str(payload.get("pool") or ""),
        play=str(payload.get("play") or ""),
        pick=str(payload.get("pick") or ""),
        odds=float(payload.get("odds") or 0),
        logic=str(payload.get("logic") or ""),
        goal_line=str(payload.get("goal_line") or ""),
        odds_update=str(payload.get("odds_update") or ""),
    )


def _normalize_date(value: str | None) -> str:
    if value is None or value == "today":
        return date.today().isoformat()
    return value


def _allowed_pools(raw: dict[str, Any]) -> set[str]:
    allowed = set()
    for item in raw.get("poolList") or []:
        if str(item.get("poolStatus") or "").casefold() == "selling":
            allowed.add(str(item.get("poolCode") or "").casefold())
    return allowed


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _leg(
    base: dict[str, str],
    *,
    pool: dict[str, Any],
    pool_name: str,
    play: str,
    key: str,
    pick: str,
    goal_line: str = "",
) -> JczqDailyLeg | None:
    odds = _float(pool.get(key))
    if odds is None or odds <= 0:
        return None
    update = " ".join(
        part
        for part in [str(pool.get("updateDate") or ""), str(pool.get("updateTime") or "")]
        if part
    )
    return JczqDailyLeg(
        match_no=base["match_no"],
        league=base["league"],
        home_team=base["home_team"],
        away_team=base["away_team"],
        pool=pool_name,
        play=play,
        pick=pick,
        odds=odds,
        logic="",
        goal_line=goal_line,
        odds_update=update,
    )


def _hot_direction(h: float | None, d: float | None, a: float | None) -> str:
    values = [("主胜", h), ("平局", d), ("客胜", a)]
    present = [(name, value) for name, value in values if value is not None]
    if not present:
        return "未知"
    name, value = min(present, key=lambda item: item[1])
    return f"{name}低赔({value:.2f})"


def _role(h: float | None, d: float | None, a: float | None, league: Any) -> str:
    league_name = str(league or "")
    low = (
        min(value for value in [h, d, a] if value is not None)
        if any(value is not None for value in [h, d, a])
        else 9
    )
    if low <= 1.35:
        return "强胆场"
    if league_name in OPEN_LEAGUE_HINTS:
        return "开放节奏场"
    if league_name in CAUTIOUS_LEAGUE_HINTS:
        return "谨慎博弈场"
    return "均衡分歧场"


def _confidence_note(
    h: float | None, d: float | None, a: float | None, *, role: str = ""
) -> str:
    low = (
        min(value for value in [h, d, a] if value is not None)
        if any(value is not None for value in [h, d, a])
        else None
    )
    if low is None:
        return "缺少胜平负概率基准。"
    implied = 1 / low
    if implied >= 0.72:
        return "胜平负方向可做胆，但让胜不能自动视为稳胆。"
    if 1.75 <= low <= 2.05 and role != "强胆场":
        return "有倾向但分歧仍大，舒服盘需防平防冷，不能作为隐形胆。"
    if implied >= 0.5:
        return "有倾向但分歧仍大，适合做组合变量。"
    return "均衡盘不宜做胆，更适合寻找反大众杠杆。"


def _had_logic(label: str, odds: float) -> str:
    if odds <= 1.4:
        return "低赔热门方向，适合保生命力但赔率杠杆有限。"
    if label == "平":
        return "平局是阻击大众胜负方向的主要反人性入口。"
    return "胜负方向赔率有分歧，需结合其他玩法放大或降风险。"


def _select_leg(
    matches: list[JczqDailyMatch],
    used_match_nos: set[str],
    *,
    pool: str,
    min_odds: float = 0,
    max_odds: float = 99,
    target: float,
    skip_match_nos: set[str] | None = None,
    poisson_idx: dict[tuple[str, str, str], float] | None = None,
    min_poisson_edge: float | None = None,
) -> JczqDailyLeg | None:
    candidates: list[JczqDailyLeg] = []
    skip = skip_match_nos or set()
    for match in matches:
        if match.match_no in used_match_nos or match.match_no in skip:
            continue
        for leg in match.candidates:
            if leg.pool != pool or not (min_odds <= leg.odds <= max_odds):
                continue
            # R21 hook: when caller passes min_poisson_edge + poisson_idx,
            # legs the model strongly opposes are filtered out. If the model
            # doesn't price this (match, pool, pick) tuple, fall through.
            if min_poisson_edge is not None and poisson_idx is not None:
                edge = poisson_idx.get((leg.match_no, leg.pool, leg.pick))
                if edge is not None and edge < min_poisson_edge:
                    continue
            candidates.append(leg)
    if not candidates:
        return None
    choice = min(candidates, key=lambda leg: abs(leg.odds - target))
    used_match_nos.add(choice.match_no)
    return choice


def _best_false_signal_leg(
    matches: list[JczqDailyMatch],
    used_match_nos: set[str],
    *,
    selector,
    target: float,
) -> JczqDailyLeg | None:
    candidates: list[JczqDailyLeg] = []
    for match in matches:
        if match.match_no in used_match_nos:
            continue
        leg = selector(match)
        if leg is not None:
            candidates.append(leg)
    if not candidates:
        return None
    choice = min(candidates, key=lambda leg: abs(leg.odds - target))
    used_match_nos.add(choice.match_no)
    return choice


def _decision_policy_preferred_ttg(strategy_memory: dict[str, Any]) -> list[str]:
    rule = decision_policy_rule(strategy_memory, "total_goals")
    preferred = [str(item) for item in rule.get("preferred_picks") or [] if str(item).strip()]
    return preferred or ["2球"]


def _low_volatility_policy_leg(matches: list[JczqDailyMatch]) -> JczqDailyLeg | None:
    candidates = [
        leg
        for match in matches
        if match.role != "强胆场"
        for leg in match.candidates
        if leg.pool in {"had", "hhad"} and leg.odds <= 2.05
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda leg: abs(leg.odds - 1.8))


def _preferred_total_goals_leg(
    match: JczqDailyMatch | None, preferred_ttg: list[str]
) -> JczqDailyLeg | None:
    if match is None:
        return None
    for pick in preferred_ttg:
        leg = _find_leg(match, pool="ttg", pick=pick)
        if leg is not None:
            return leg
    return None


def _policy_hhad_fallback(match: JczqDailyMatch | None) -> JczqDailyLeg | None:
    if match is None:
        return None
    candidates = [
        leg
        for leg in match.candidates
        if leg.pool == "hhad" and leg.pick in {"让胜", "让平", "让负"} and 1.65 <= leg.odds <= 4.2
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda leg: abs(leg.odds - 3.0))


def _best_total_goals_policy_leg(
    matches: list[JczqDailyMatch], preferred_ttg: list[str]
) -> JczqDailyLeg | None:
    candidates = [
        leg
        for match in matches
        for pick in preferred_ttg
        for leg in [_find_leg(match, pool="ttg", pick=pick)]
        if leg is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda leg: (preferred_ttg.index(leg.pick), abs(leg.odds - 3.5)))


def _duplicate_story_replacement(
    match: JczqDailyMatch | None,
    *,
    seen: set[tuple[str, str, str]],
    avoid_hafu: bool,
    poisson_edge_index: dict[tuple[str, str, str], float] | None = None,
    min_poisson_edge: float | None = None,
) -> JczqDailyLeg | None:
    if match is None:
        return None
    pool_rank = {"ttg": 0, "hhad": 1, "had": 2}
    candidates = [
        leg
        for leg in match.candidates
        if leg.pool in pool_rank
        and not (avoid_hafu and leg.pool == "hafu")
        and (leg.match_no, leg.pool, leg.pick) not in seen
    ]
    if poisson_edge_index is not None and min_poisson_edge is not None:
        # Rule I-2: drop replacement candidates the Poisson model strongly
        # opposes (hhad has no Poisson coverage so it bypasses).
        candidates = [
            leg
            for leg in candidates
            if leg.pool == "hhad"
            or poisson_edge_index.get((leg.match_no, leg.pool, leg.pick), 0.0)
            >= min_poisson_edge
        ]
    if not candidates:
        return None
    return min(candidates, key=lambda leg: (pool_rank[leg.pool], abs(leg.odds - 3.2)))


def _favorite_cover_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    favorite = _favorite_had_with_odds(match)
    if favorite is None:
        return None
    pick, odds = favorite
    if odds > 1.65:
        return None
    cover_pick = _hhad_cover_pick(match, pick)
    if cover_pick is None:
        return None
    return _find_leg(match, pool="hhad", pick=cover_pick)


def _comfort_resistance_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    if not _is_comfort_risk(match):
        return None
    favorite = _favorite_had_pick(match)
    if favorite is None:
        return None
    if favorite == "胜":
        return _find_leg(match, pool="hhad", pick="让负")
    if favorite == "负":
        return _find_leg(match, pool="hhad", pick="让胜")
    return _find_leg(match, pool="had", pick="平")


def _tactical_process_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    # Rule H: hafu blocked from non-extreme; tactical fallback is ttg only.
    preferred = [
        leg
        for leg in match.candidates
        if leg.pool == "ttg" and leg.pick in {"3球", "4球", "5球"}
        and 3.4 <= leg.odds <= 6.5
    ]
    if not preferred:
        return None
    return min(preferred, key=lambda leg: abs(leg.odds - 4.2))


def _is_comfort_risk(match: JczqDailyMatch) -> bool:
    return "舒服盘" in match.confidence_note


def _rule_i2_contrarian_replacement(
    match: JczqDailyMatch | None,
    poisson_edge_index: dict[tuple[str, str, str], float],
    *,
    min_edge: float = CONTRARIAN_POISSON_REJECT_BELOW,
    is_strong_banker: bool = False,
) -> JczqDailyLeg | None:
    """Pick a leg the Poisson model doesn't reject (Rule I scrub helper).

    Preference: ttg picks meeting `min_edge`, then hhad cover (Poisson-blind,
    safe by default).

    R15 (5/10): when the source match is a strong-banker, exclude hhad 让胜
    odds ≤ 3.0 from the hhad fallback set — those are leveraged-favorite
    legs, not contrarian. 5/09 周六029 莱切-尤文 was the canonical case.
    """

    if match is None:
        return None
    safe_ttg = [
        leg
        for leg in match.candidates
        if leg.pool == "ttg"
        and 3.0 <= leg.odds <= 8.0
        and poisson_edge_index.get((leg.match_no, "ttg", leg.pick), -1.0) >= min_edge
    ]
    if safe_ttg:
        return min(safe_ttg, key=lambda leg: abs(leg.odds - 3.5))
    hhad_options = [
        leg
        for leg in match.candidates
        if leg.pool == "hhad"
        and leg.goal_line
        and 2.0 <= leg.odds <= 5.0
        and not (
            is_strong_banker
            and leg.pick == "让胜"
            and leg.odds <= 3.0
        )
    ]
    if hhad_options:
        return min(hhad_options, key=lambda leg: abs(leg.odds - 3.0))
    return None


def _rule_h_hafu_replacement(match: JczqDailyMatch | None) -> JczqDailyLeg | None:
    """Pick a ttg or hhad leg that can stand in for a hafu pick (Rule H).

    Preference order: ttg 2球/3球 (mid-priced), then hhad cover with handicap,
    then any ttg leg in the 3-6 odds band.
    """

    if match is None:
        return None
    for pick in ("2球", "3球", "1球"):
        leg = _find_leg(match, pool="ttg", pick=pick)
        if leg is not None and 1.6 <= leg.odds <= 6.5:
            return leg
    hhad_options = [
        leg
        for leg in match.candidates
        if leg.pool == "hhad"
        and leg.pick in {"让胜", "让平", "让负"}
        and leg.goal_line
        and 1.8 <= leg.odds <= 4.5
    ]
    if hhad_options:
        return min(hhad_options, key=lambda leg: abs(leg.odds - 3.0))
    ttg_any = [leg for leg in match.candidates if leg.pool == "ttg" and 2.5 <= leg.odds <= 6.0]
    if ttg_any:
        return min(ttg_any, key=lambda leg: abs(leg.odds - 4.0))
    return None


def _favorite_had_pick(match: JczqDailyMatch) -> str | None:
    had = [leg for leg in match.candidates if leg.pool == "had" and leg.pick in {"胜", "负"}]
    if not had:
        return None
    favorite = min(had, key=lambda leg: leg.odds)
    if 1.75 <= favorite.odds <= 2.05:
        return favorite.pick
    return None


def _favorite_had_with_odds(match: JczqDailyMatch) -> tuple[str, float] | None:
    had = [leg for leg in match.candidates if leg.pool == "had" and leg.pick in {"胜", "负"}]
    if not had:
        return None
    favorite = min(had, key=lambda leg: leg.odds)
    return favorite.pick, favorite.odds


def _hhad_cover_pick(match: JczqDailyMatch, favorite: str) -> str | None:
    goal_lines = [leg.goal_line for leg in match.candidates if leg.pool == "hhad" and leg.goal_line]
    goal_line = goal_lines[0] if goal_lines else ""
    if favorite == "胜" and goal_line.startswith("-"):
        return "让胜"
    if favorite == "负" and goal_line.startswith("+"):
        return "让负"
    return None


def _find_leg(match: JczqDailyMatch, *, pool: str, pick: str) -> JczqDailyLeg | None:
    return next((leg for leg in match.candidates if leg.pool == pool and leg.pick == pick), None)


def _plans_contain_leg(
    plans: list[JczqDailyPlan], match_no: str, pool: str, pick: str
) -> bool:
    return any(
        leg.match_no == match_no and leg.pool == pool and leg.pick == pick
        for plan in plans
        for leg in plan.legs
    )


def _least_protective_leg_index(legs: list[JczqDailyLeg]) -> int:
    if not legs:
        return 0
    for index, leg in enumerate(legs):
        if leg.pool == "had" and leg.odds <= 2.05:
            return index
    return min(range(len(legs)), key=lambda index: legs[index].odds)


def _build_memory_bias(
    strategy_memory: dict[str, Any], *, burned_teams: set[str] | None = None
):
    """Construct a `bias_fn` for `select_top_legs` that folds memory hints in.

    Three signals are blended:
      - pattern_bucket EV (league × role × pool) decayed historical performance
      - oracle_learnings: matches in the same league/pool that historically had
        a different winning pick than what we tend to pick give a small bonus
        when the candidate matches the recently-victorious side.
      - burned_teams (Rule F): teams from the previous review's burned-match
        list get a static -bias when they reappear today.
    """

    burned_teams = burned_teams or set()
    if not strategy_memory and not burned_teams:
        return None
    has_buckets = bool(strategy_memory.get("pattern_buckets"))
    has_oracle = bool(strategy_memory.get("oracle_learnings"))
    if not (has_buckets or has_oracle or burned_teams):
        return None

    def bias_fn(leg: JczqDailyLeg, analytics: MatchAnalytics | None) -> float:
        bias = 0.0
        league = leg.league or (analytics.league if analytics else "")
        role = ""
        if analytics is not None:
            if analytics.is_strong_banker:
                role = "强胆场"
            elif analytics.is_comfort_risk:
                role = "舒服盘"
            elif analytics.is_chaos:
                role = "均衡分歧场"
            else:
                role = "谨慎博弈场"
        if has_buckets:
            ev = pattern_bucket_ev(strategy_memory, league, role, leg.pool)
            # Soft scale: clamp to [-0.6, +0.6] so memory cannot dominate analytics.
            bias += max(-0.6, min(0.6, ev * 0.05))
        if has_oracle:
            for entry in oracle_learning_for(strategy_memory, league, leg.pool):
                if str(entry.get("winning_pick") or "") == leg.pick:
                    bias += 0.15
                    break
        if burned_teams and (leg.home_team in burned_teams or leg.away_team in burned_teams):
            bias += BURNED_TEAM_BIAS
        return bias

    return bias_fn


class _DictDriftProvider:
    """Adapts a `{match_no: {(pool, pick): delta}}` dict to DriftProvider."""

    __slots__ = ("_index",)

    def __init__(self, index: dict[str, dict[tuple[str, str], float]]) -> None:
        self._index = index

    def get(self, match_no: str) -> dict[tuple[str, str], float]:
        return dict(self._index.get(match_no, {}))
