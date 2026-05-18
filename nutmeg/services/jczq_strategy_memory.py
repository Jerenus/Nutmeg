from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

MEMORY_VERSION = 2
POLICY_VERSION = 1
MEMORY_RELATIVE_PATH = Path("memory") / "strategy-memory.json"

PATTERN_BUCKET_EV_DECAY = 0.85
PATTERN_BUCKET_RECENT_LIMIT = 30

# R1 (5/08): Poisson lambda calibration loop.
# A (league × pool) bucket showing systematic under-pricing of goals
# (avg goal_residual ≥ this threshold, sample_count ≥ this floor) gets
# its recommended min_edge raised — generator should then refuse low-
# edge crs/ttg picks in that league until the model recalibrates.
POISSON_RESIDUAL_BIAS_THRESHOLD = 0.5
POISSON_RESIDUAL_MIN_SAMPLES = 3
POISSON_RESIDUAL_RECENT_LIMIT = 200
POISSON_DEFAULT_CRS_MIN_EDGE = 0.15
POISSON_RAISED_CRS_MIN_EDGE = 0.25
# R24 (5/13): cooling-off detection — if last 3 poisson_solo plans all missed,
# the generator caps the next plan to 1 leg. The list below is rolling and
# capped at RECENT_PLAN_RESULTS_LIMIT entries per kind.
POISSON_SOLO_COOLING_OFF_LOOKBACK = 3
RECENT_PLAN_RESULTS_LIMIT = 60
# R25 (5/13): per-league ttg/crs Poisson residual bias. When a league has at
# least POISSON_LEAGUE_BIAS_MIN_SAMPLES priced ttg/crs entries with average
# goal residual > 0 (model systematically under-prices goals), apply a
# negative shift POISSON_LEAGUE_BIAS_DELTA to all ttg/crs Poisson edges in
# that league. 5/13: 法甲 had 7 ttg/crs samples, all missed across 5/10
# 5/12 5/13. Subtract -0.10 from edges to compensate for the model's λ
# under-estimate. Bias only applies to pools whose hit-rate depends directly
# on goal totals (ttg/crs); had/hhad/hafu unaffected.
POISSON_LEAGUE_BIAS_MIN_SAMPLES = 5
POISSON_LEAGUE_BIAS_DELTA = -0.10
# F2 (5/14): empirical alpha decay — for picks where Poisson model systematically
# over-prices the probability (e.g., crs 0:0 实测 6.25% vs implied ~10%), apply
# a multiplicative decay to the Poisson edge so the alpha tickets get correctly
# downweighted instead of relying on hard threshold rules (R23 +25%) alone.
#
# Baseline implied probabilities below come from typical Sporttery market prices
# for each pick category (1/odds, vig-adjusted). When empirical hit rate falls
# below the baseline, decay = max(floor, actual / baseline).
EMPIRICAL_DECAY_BASELINES: dict[tuple[str, str], float] = {
    ("crs", "0:0"): 0.10,   # ~10x odds → 10% implied
    ("crs", "0:1"): 0.08,
    ("crs", "1:0"): 0.10,
    ("ttg", "0球"): 0.10,
    ("ttg", "1球"): 0.22,
}
EMPIRICAL_DECAY_MIN_SAMPLES = 5
EMPIRICAL_DECAY_FLOOR = 0.5
EMPIRICAL_DECAY_TOLERANCE = 0.95  # actual >= baseline * tolerance → no decay
# F3 (5/14): daily alpha concentration warning — when a single day's brief shows
# ≥ DAILY_CONCENTRATION_TRIGGER_COUNT distinct matches with strong alpha
# (≥ DAILY_CONCENTRATION_ALPHA_THRESHOLD) all in the same direction (currently
# only low_goals direction tracked), apply DAILY_CONCENTRATION_DECAY multiplier
# to all alpha edges in that direction. This is a *meta-rule* on top of F2's
# per-(pool,pick) static decay — F3 catches day-specific model bias (e.g.,
# 5/14: 4 ≥+15% alpha all in low_goals direction signals overall under-pricing
# of goals system-wide that day).
DAILY_CONCENTRATION_ALPHA_THRESHOLD = 0.15
DAILY_CONCENTRATION_TRIGGER_COUNT = 3
DAILY_CONCENTRATION_DECAY = 0.9
LOW_GOALS_PICKS: frozenset[tuple[str, str]] = frozenset({
    ("crs", "0:0"),
    ("crs", "0:1"),
    ("crs", "1:0"),
    ("ttg", "0球"),
    ("ttg", "1球"),
})
# F1 (5/14): Dixon-Coles tau correction parameter, read from memory key
# `dixon_coles_rho`. Default 0.0 = F1 disabled (independent Poisson). Operator
# can manually set this in strategy-memory.json based on backtest:
#   - 0.05 ~ 0.10: deflate 0:0 (JCZQ case where 实测命中率 < implied)
#   - -0.05 ~ -0.10: inflate 0:0 (textbook D-C for European football)
DIXON_COLES_RHO_KEY = "dixon_coles_rho"
DIXON_COLES_RHO_DEFAULT = 0.0


def strategy_memory_path(output_dir: Path | str) -> Path:
    return Path(output_dir) / MEMORY_RELATIVE_PATH


def load_strategy_memory(output_dir: Path | str | None) -> dict[str, Any]:
    if output_dir is None:
        return {}
    path = strategy_memory_path(output_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_strategy_memory(
    *,
    output_dir: Path | str,
    run_date: str,
    context: dict[str, Any],
    results: dict[str, dict[str, str]],
    graded_legs: list[dict[str, Any]],
    plan_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    memory = _normalize_memory(load_strategy_memory(output_dir))
    reviewed_dates = set(str(item) for item in memory.get("reviewed_dates") or [])
    if run_date in reviewed_dates:
        memory["updated_at"] = _now_iso()
        # R1 calibration: also backfill poisson_residuals on re-runs so that
        # newer R8-enriched graded_legs land in memory even when the date was
        # first reviewed before R8/R1 existed. The function dedups by
        # (date, match_no, pool) so repeat calls are idempotent.
        _update_poisson_residuals(memory, run_date=run_date, graded_legs=graded_legs)
        _update_recent_plan_results(
            memory, run_date=run_date, plan_summaries=plan_summaries or []
        )
        _update_decision_policy(
            memory,
            run_date=run_date,
            context=context,
            results=results,
            graded_legs=graded_legs,
        )
        memory["insights"] = _build_insights(memory)
        _write_memory(output_dir, memory)
        return memory

    reviewed_dates.add(run_date)
    memory["reviewed_dates"] = sorted(reviewed_dates)
    memory["sample_count"] = int(memory.get("sample_count") or 0) + 1
    memory["last_review_date"] = run_date
    memory["updated_at"] = _now_iso()

    _update_leg_patterns(memory, run_date=run_date, graded_legs=graded_legs)
    _update_match_patterns(memory, run_date=run_date, context=context, results=results)
    _update_pattern_buckets(
        memory,
        run_date=run_date,
        context=context,
        graded_legs=graded_legs,
    )
    _update_oracle_learnings(memory, run_date=run_date, context=context, results=results)
    _update_poisson_residuals(memory, run_date=run_date, graded_legs=graded_legs)
    _update_recent_plan_results(
        memory, run_date=run_date, plan_summaries=plan_summaries or []
    )
    _update_decision_policy(
        memory,
        run_date=run_date,
        context=context,
        results=results,
        graded_legs=graded_legs,
    )
    memory["insights"] = _build_insights(memory)
    memory["recent_inspirations"] = (memory.get("recent_inspirations") or [])[-20:]
    _write_memory(output_dir, memory)
    return memory


def pattern_bucket_ev(memory: dict[str, Any], league: str, role: str, pool: str) -> float:
    """Read EV-weighted score for a (league × role × pool) bucket."""

    buckets = (memory.get("pattern_buckets") or {})
    key = _bucket_key(league, role, pool)
    entry = buckets.get(key) or {}
    return float(entry.get("ev_score") or 0.0)


def oracle_learning_for(
    memory: dict[str, Any], league: str, pool: str
) -> list[dict[str, Any]]:
    """Most-recent oracle entries for a given (league, pool) tuple."""

    learnings = memory.get("oracle_learnings") or []
    out = []
    for item in learnings:
        if (
            str(item.get("league") or "") == league
            and str(item.get("pool") or "") == pool
        ):
            out.append(item)
    return out


def render_strategy_memory_notes(memory: dict[str, Any], *, limit: int = 2) -> list[str]:
    notes = [str(item) for item in memory.get("insights") or [] if str(item).strip()]
    return notes[:limit]


def render_decision_policy_notes(memory: dict[str, Any], *, limit: int = 6) -> list[str]:
    operator = memory.get("operator_strategy") or {}
    policy = memory.get("decision_policy") or {}
    notes: list[str] = []
    seen: set[str] = set()
    for source_notes in (operator.get("notes") or [], policy.get("notes") or []):
        for source in source_notes:
            note = str(source).strip()
            if not note or note in seen:
                continue
            notes.append(note)
            seen.add(note)
    return notes[:limit]


def decision_policy_rule_active(memory: dict[str, Any], key: str) -> bool:
    policy = memory.get("decision_policy") or {}
    rule = (policy.get("rules") or {}).get(key) or {}
    return bool(rule.get("active"))


def decision_policy_rule(memory: dict[str, Any], key: str) -> dict[str, Any]:
    policy = memory.get("decision_policy") or {}
    rule = (policy.get("rules") or {}).get(key) or {}
    return dict(rule) if isinstance(rule, dict) else {}


def memory_pattern_positive(memory: dict[str, Any], key: str, *, min_hits: int = 1) -> bool:
    pattern = (memory.get("patterns") or {}).get(key) or {}
    hits = int(pattern.get("hits") or 0)
    misses = int(pattern.get("misses") or 0)
    return hits >= min_hits and hits >= misses


def compute_league_ttg_volatility(
    memory: dict[str, Any], *, lookback: int = 60, min_samples: int = 4
) -> dict[str, float]:
    """Per-league median total-goals from the last N oracle entries.

    Powers Rule C: leagues whose median ttg ≥ 2.7 get the high-volatility flag,
    which the generator uses to deprioritize low-side ttg picks.
    `lookback` is in entries (each match contributes one ttg entry per pool, so
    the effective per-league window is smaller).
    """

    learnings = memory.get("oracle_learnings") or []
    recent_ttg = [
        item
        for item in learnings[-lookback * 6 :]
        if str(item.get("pool") or "") == "ttg"
    ]
    by_league: dict[str, list[int]] = {}
    for entry in recent_ttg:
        league = str(entry.get("league") or "")
        if not league:
            continue
        try:
            goals = int(str(entry.get("winning_pick") or "").rstrip("球"))
        except ValueError:
            continue
        by_league.setdefault(league, []).append(goals)
    out: dict[str, float] = {}
    for league, goals in by_league.items():
        if len(goals) < min_samples:
            continue
        ordered = sorted(goals)
        mid = len(ordered) // 2
        median = (
            ordered[mid]
            if len(ordered) % 2 == 1
            else (ordered[mid - 1] + ordered[mid]) / 2
        )
        out[league] = float(median)
    return out


def _update_poisson_residuals(
    memory: dict[str, Any],
    *,
    run_date: str,
    graded_legs: list[dict[str, Any]],
) -> None:
    """R1 calibration: append per-leg goal residuals to the rolling
    `poisson_residuals` list. Only legs with both `expected_goals` and
    `realized_goals` populated by R8 enrichment are kept; others are
    silently skipped (hhad has no Poisson price; pre-game cancellations
    have no realized goals).
    """

    samples: list[dict[str, Any]] = list(memory.get("poisson_residuals") or [])
    seen = {
        (str(s.get("date")), str(s.get("match_no")), str(s.get("pool")))
        for s in samples
    }
    for leg in graded_legs:
        pool = str(leg.get("pool") or "")
        if pool == "hhad" or not pool:
            continue
        match_no = str(leg.get("match_no") or "")
        if not match_no:
            continue
        key = (run_date, match_no, pool)
        if key in seen:
            continue
        if leg.get("expected_goals") is None or leg.get("realized_goals") is None:
            continue
        residual = leg.get("goal_residual")
        if residual is None:
            continue
        samples.append({
            "date": run_date,
            "match_no": match_no,
            "league": str(leg.get("league") or ""),
            "pool": pool,
            "pick": str(leg.get("pick") or ""),
            "expected_goals": leg.get("expected_goals"),
            "realized_goals": leg.get("realized_goals"),
            "goal_residual": residual,
            "hit": leg.get("hit"),
        })
        seen.add(key)
    memory["poisson_residuals"] = samples[-POISSON_RESIDUAL_RECENT_LIMIT:]


def _update_recent_plan_results(
    memory: dict[str, Any],
    *,
    run_date: str,
    plan_summaries: list[dict[str, Any]],
) -> None:
    """R24 (5/13): persist per-(date,kind) plan miss/hit so the daily generator
    can detect cooling-off streaks. Stores rolling history capped at
    RECENT_PLAN_RESULTS_LIMIT entries; idempotent on (date, kind) re-runs.
    """

    if not plan_summaries:
        return
    existing: list[dict[str, Any]] = list(memory.get("recent_plan_results") or [])
    seen = {(str(s.get("date")), str(s.get("kind"))) for s in existing}
    for summary in plan_summaries:
        kind = str(summary.get("kind") or "")
        if not kind:
            continue
        key = (run_date, kind)
        if key in seen:
            # Replace existing entry so re-runs reflect latest grading.
            existing = [
                s for s in existing
                if not (str(s.get("date")) == run_date and str(s.get("kind")) == kind)
            ]
            seen.discard(key)
        existing.append({
            "date": run_date,
            "kind": kind,
            "name": str(summary.get("name") or ""),
            "hits": int(summary.get("hits") or 0),
            "total": int(summary.get("total") or 0),
            "all_hit": bool(summary.get("all_hit")),
        })
        seen.add(key)
    # Sort chronologically; newest at the end.
    existing.sort(key=lambda item: (str(item.get("date")), str(item.get("kind"))))
    memory["recent_plan_results"] = existing[-RECENT_PLAN_RESULTS_LIMIT:]


def compute_poisson_lambda_signals(
    memory: dict[str, Any],
    *,
    pool: str = "crs",
    min_samples: int = POISSON_RESIDUAL_MIN_SAMPLES,
    bias_threshold: float = POISSON_RESIDUAL_BIAS_THRESHOLD,
) -> dict[str, dict[str, Any]]:
    """Per-league calibration signals derived from `poisson_residuals`.

    Returns `{league: {sample_count, avg_goal_residual, hit_rate,
    recommended_crs_min_edge}}` for leagues with enough samples in the
    given pool. Leagues with positive average residual (model under-prices
    goals) get a raised recommended floor; otherwise the default applies.
    """

    samples = memory.get("poisson_residuals") or []
    by_league: dict[str, list[dict[str, Any]]] = {}
    for entry in samples:
        if str(entry.get("pool") or "") != pool:
            continue
        league = str(entry.get("league") or "")
        if not league:
            continue
        by_league.setdefault(league, []).append(entry)

    out: dict[str, dict[str, Any]] = {}
    for league, entries in by_league.items():
        if len(entries) < min_samples:
            continue
        residuals = [
            float(e.get("goal_residual") or 0.0)
            for e in entries
            if e.get("goal_residual") is not None
        ]
        if not residuals:
            continue
        avg_residual = sum(residuals) / len(residuals)
        hits = sum(1 for e in entries if e.get("hit") is True)
        hit_rate = hits / len(entries) if entries else 0.0
        recommended = (
            POISSON_RAISED_CRS_MIN_EDGE
            if avg_residual >= bias_threshold
            else POISSON_DEFAULT_CRS_MIN_EDGE
        )
        out[league] = {
            "sample_count": len(entries),
            "avg_goal_residual": round(avg_residual, 3),
            "hit_rate": round(hit_rate, 3),
            "recommended_crs_min_edge": recommended,
        }
    return out


def detect_poisson_solo_cooling_off(
    memory: dict[str, Any],
    *,
    lookback: int = POISSON_SOLO_COOLING_OFF_LOOKBACK,
) -> bool:
    """R24: True when the last `lookback` poisson_solo plan summaries all
    missed. Returns False if fewer than `lookback` samples are recorded —
    requiring a real streak of misses, not just one bad day.
    """

    results = memory.get("recent_plan_results") or []
    poisson_only = [
        item
        for item in results
        if str(item.get("kind") or "") == "poisson_solo"
    ]
    if len(poisson_only) < lookback:
        return False
    recent = poisson_only[-lookback:]
    return all(item.get("all_hit") is False for item in recent)


def compute_league_residual_bias(
    memory: dict[str, Any],
    *,
    pools: tuple[str, ...] = ("ttg", "crs"),
    min_samples: int = POISSON_LEAGUE_BIAS_MIN_SAMPLES,
    delta: float = POISSON_LEAGUE_BIAS_DELTA,
) -> dict[str, float]:
    """R25: per-league negative edge shift for systematic goal under-estimate.

    A league qualifies when its ttg/crs Poisson residuals show:
      - sample_count >= min_samples
      - average goal_residual > 0 (actual goals consistently above expected)

    Returns `{league: delta}` (delta is negative); an empty dict means no
    league currently qualifies. Generator should apply the shift to ttg/crs
    Poisson edges only — had/hhad/hafu have their own pricing.
    """

    samples = memory.get("poisson_residuals") or []
    by_league: dict[str, list[float]] = {}
    for entry in samples:
        if str(entry.get("pool") or "") not in pools:
            continue
        league = str(entry.get("league") or "")
        if not league:
            continue
        residual = entry.get("goal_residual")
        if residual is None:
            continue
        by_league.setdefault(league, []).append(float(residual))

    out: dict[str, float] = {}
    for league, residuals in by_league.items():
        if len(residuals) < min_samples:
            continue
        avg = sum(residuals) / len(residuals)
        if avg > 0:
            out[league] = delta
    return out


def compute_empirical_alpha_decay(
    memory: dict[str, Any],
    *,
    pool: str,
    pick: str,
    min_samples: int = EMPIRICAL_DECAY_MIN_SAMPLES,
    baselines: dict[tuple[str, str], float] | None = None,
    floor: float = EMPIRICAL_DECAY_FLOOR,
    tolerance: float = EMPIRICAL_DECAY_TOLERANCE,
) -> float:
    """F2 (5/14): empirical decay factor for Poisson edge on (pool, pick).

    Returns a value in [floor, 1.0]. 1.0 means no decay (model not biased).
    Lower values mean alpha edge should be multiplied by this factor.

    Algorithm:
      - if (pool, pick) not in baselines → return 1.0 (unknown picks don't decay)
      - if samples < min_samples → return 1.0 (insufficient evidence)
      - actual_rate = sum(hit) / count
      - if actual_rate >= baseline * tolerance → return 1.0 (model not biased)
      - else decay = max(floor, actual_rate / baseline)

    The baseline table represents typical Sporttery market implied probabilities
    for each pick. When realized hit rate falls materially below baseline, the
    Poisson model is systematically over-pricing that pick — F2 corrects this
    via multiplicative decay on the alpha edge.
    """

    table = baselines if baselines is not None else EMPIRICAL_DECAY_BASELINES
    if (pool, pick) not in table:
        return 1.0
    baseline = table[(pool, pick)]

    samples = [
        s for s in (memory.get("poisson_residuals") or [])
        if str(s.get("pool") or "") == pool and str(s.get("pick") or "") == pick
    ]
    if len(samples) < min_samples:
        return 1.0

    hits = sum(1 for s in samples if s.get("hit") is True)
    actual_rate = hits / len(samples)

    if actual_rate >= baseline * tolerance:
        return 1.0
    return max(floor, actual_rate / baseline)


def compute_empirical_decay_map(
    memory: dict[str, Any],
    *,
    min_samples: int = EMPIRICAL_DECAY_MIN_SAMPLES,
    baselines: dict[tuple[str, str], float] | None = None,
) -> dict[tuple[str, str], float]:
    """F2: build (pool, pick) → decay factor map for all baseline-tracked picks.

    Returns only entries where decay < 1.0 (actually decaying); callers should
    treat missing entries as decay = 1.0 (no shift). Useful as a single argument
    to `compute_poisson_edges(empirical_decay_map=...)`.
    """

    table = baselines if baselines is not None else EMPIRICAL_DECAY_BASELINES
    out: dict[tuple[str, str], float] = {}
    for (pool, pick) in table:
        decay = compute_empirical_alpha_decay(
            memory,
            pool=pool,
            pick=pick,
            min_samples=min_samples,
            baselines=table,
        )
        if decay < 1.0:
            out[(pool, pick)] = decay
    return out


def get_dixon_coles_rho(memory: dict[str, Any]) -> float:
    """F1 (5/14): read Dixon-Coles tau parameter from strategy memory.

    Default 0.0 means F1 is disabled (no D-C correction; identical to
    pre-F1 independent-Poisson behavior). Operator may manually edit the
    `dixon_coles_rho` key in strategy-memory.json based on backtest:
      - 0.05 ~ 0.10: deflate 0:0/1:1 (when historical implied > realized,
        JCZQ case across 5/01-5/14: crs 0:0 1/16 = 6.25% vs implied ~10%)
      - -0.05 ~ -0.10: inflate 0:0/1:1 (textbook D-C for European football)
    """

    raw = memory.get(DIXON_COLES_RHO_KEY)
    if raw is None:
        return DIXON_COLES_RHO_DEFAULT
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DIXON_COLES_RHO_DEFAULT


def compute_daily_low_goals_concentration(
    poisson_rows: "Iterable[Any]",
    *,
    alpha_threshold: float = DAILY_CONCENTRATION_ALPHA_THRESHOLD,
) -> int:
    """F3: count distinct matches with ≥ alpha_threshold low_goals alpha.

    Same match with multiple low_goals legs counted once. Used to detect
    days where Poisson model has system-wide bias toward predicting low
    scoring across the entire slate.
    """

    matches_with_strong_low_alpha: set[str] = set()
    for row in poisson_rows:
        try:
            edge = float(getattr(row, "edge", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if edge < alpha_threshold:
            continue
        pool = str(getattr(row, "pool", "") or "")
        pick = str(getattr(row, "pick", "") or "")
        if (pool, pick) not in LOW_GOALS_PICKS:
            continue
        match_no = str(getattr(row, "match_no", "") or "")
        if match_no:
            matches_with_strong_low_alpha.add(match_no)
    return len(matches_with_strong_low_alpha)


def compute_daily_concentration_bias(
    poisson_rows: "Iterable[Any]",
    *,
    alpha_threshold: float = DAILY_CONCENTRATION_ALPHA_THRESHOLD,
    trigger_count: int = DAILY_CONCENTRATION_TRIGGER_COUNT,
    decay: float = DAILY_CONCENTRATION_DECAY,
) -> dict[tuple[str, str], float]:
    """F3: build {(pool, pick): decay} bias map when daily low_goals
    concentration exceeds trigger threshold.

    Returns empty dict when no concentration detected → no F3 application.
    The Poisson edge computation layer multiplies matching legs by `decay`
    (typically 0.9 = -10% additional shrinkage on top of F2 static decay).
    """

    count = compute_daily_low_goals_concentration(
        poisson_rows, alpha_threshold=alpha_threshold
    )
    if count < trigger_count:
        return {}
    return {pp: decay for pp in LOW_GOALS_PICKS}


def recently_burned_teams(
    memory: dict[str, Any], *, lookback_dates: int = 2
) -> set[str]:
    """Teams that appeared in burned-match list in the last N review dates.

    Powers Rule F: when those teams reappear, generator applies a -bias so
    the next ticket isn't built on the same losing story.
    """

    policy = memory.get("decision_policy") or {}
    burned = (policy.get("rules") or {}).get("reuse_guard") or {}
    teams = burned.get("burned_teams") or []
    if isinstance(teams, list):
        return {str(name) for name in teams if str(name).strip()}
    if isinstance(teams, dict):
        return {str(name) for name in teams.keys() if str(name).strip()}
    del lookback_dates  # reserved for future per-date filtering
    return set()


def _normalize_memory(payload: dict[str, Any]) -> dict[str, Any]:
    memory = dict(payload or {})
    memory.setdefault("version", MEMORY_VERSION)
    memory.setdefault("sample_count", 0)
    memory.setdefault("reviewed_dates", [])
    memory.setdefault("patterns", {})
    memory.setdefault("insights", [])
    memory.setdefault("recent_inspirations", [])
    memory.setdefault("pattern_buckets", {})
    memory.setdefault("oracle_learnings", [])
    return memory


def _pattern(memory: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    patterns = memory.setdefault("patterns", {})
    pattern = patterns.setdefault(
        key,
        {
            "label": label,
            "hits": 0,
            "misses": 0,
            "last_seen": None,
        },
    )
    pattern.setdefault("label", label)
    pattern.setdefault("hits", 0)
    pattern.setdefault("misses", 0)
    pattern.setdefault("last_seen", None)
    return pattern


def _record(pattern: dict[str, Any], *, hit: bool, run_date: str) -> None:
    if hit:
        pattern["hits"] = int(pattern.get("hits") or 0) + 1
    else:
        pattern["misses"] = int(pattern.get("misses") or 0) + 1
    pattern["last_seen"] = run_date


def _update_leg_patterns(
    memory: dict[str, Any], *, run_date: str, graded_legs: list[dict[str, Any]]
) -> None:
    hafu_pattern = _pattern(memory, "user_revision_hafu_draw_away", "用户修正-半全场平/负")
    for item in graded_legs:
        if item.get("pool") == "hafu" and item.get("pick") == "平/负":
            hit = item.get("hit") is True
            _record(hafu_pattern, hit=hit, run_date=run_date)
            if hit:
                _remember_inspiration(
                    memory,
                    {
                        "date": run_date,
                        "match_no": item.get("match_no"),
                        "pattern": "user_revision_hafu_draw_away",
                        "note": f"{item.get('match_no')} 半全场平/负命中",
                    },
                )


def _update_match_patterns(
    memory: dict[str, Any], *, run_date: str, context: dict[str, Any], results: dict[str, Any]
) -> None:
    comfort_pattern = _pattern(memory, "comfort_risk_draw_or_cold", "舒服盘防平防冷")
    strong_pattern = _pattern(memory, "strong_banker_positive", "强胆正路/打穿优先")
    draw_pattern = _pattern(memory, "variable_draw_protection", "变量场防平")
    for match in context.get("matches") or []:
        match_no = str(match.get("match_no") or "")
        actual = (results.get(match_no) or {}).get("had")
        if actual not in {"胜", "平", "负"}:
            continue
        favorite = _favorite_from_hot_direction(str(match.get("hot_direction") or ""))
        role = str(match.get("role") or "")
        note = str(match.get("confidence_note") or "")
        is_comfort_risk = "舒服盘" in note or (
            role != "强胆场" and _hot_odds_in_range(str(match.get("hot_direction") or ""))
        )
        if is_comfort_risk and favorite in {"胜", "负"}:
            hit = actual != favorite
            _record(comfort_pattern, hit=hit, run_date=run_date)
            if hit:
                _remember_inspiration(
                    memory,
                    {
                        "date": run_date,
                        "match_no": match_no,
                        "pattern": "comfort_risk_draw_or_cold",
                        "note": f"{match_no} 舒服盘防平防冷兑现，实际{actual}",
                    },
                )
        if role == "强胆场" and favorite in {"胜", "负"}:
            _record(strong_pattern, hit=actual == favorite, run_date=run_date)
        if role != "强胆场" and "分歧" in note:
            _record(draw_pattern, hit=actual == "平", run_date=run_date)


def _update_decision_policy(
    memory: dict[str, Any],
    *,
    run_date: str,
    context: dict[str, Any],
    results: dict[str, dict[str, str]],
    graded_legs: list[dict[str, Any]],
) -> None:
    del context  # Policy uses persisted pattern counters plus current result/leg distributions.
    patterns = memory.get("patterns") or {}
    strong = patterns.get("strong_banker_positive") or {}
    strong_hits = int(strong.get("hits") or 0)
    strong_misses = int(strong.get("misses") or 0)
    strong_active = strong_misses >= 2 and strong_misses > strong_hits

    comfort = patterns.get("comfort_risk_draw_or_cold") or {}
    comfort_hits = int(comfort.get("hits") or 0)
    comfort_misses = int(comfort.get("misses") or 0)
    comfort_active = comfort_hits > 0 and comfort_hits >= comfort_misses

    ttg_counts = Counter(
        str(row.get("ttg"))
        for row in results.values()
        if row.get("ttg") not in {None, ""}
    )
    ttg_total = sum(ttg_counts.values())
    two_goal_count = int(ttg_counts.get("2球") or 0)
    two_goal_active = ttg_total >= 3 and two_goal_count >= max(2, int(ttg_total * 0.3))
    preferred_ttg = [
        pick for pick in ["2球", "1球", "0球"] if pick == "2球" or ttg_counts.get(pick)
    ]

    hafu_items = [item for item in graded_legs if item.get("pool") == "hafu"]
    hafu_hits = sum(1 for item in hafu_items if item.get("hit") is True)
    hafu_misses = sum(1 for item in hafu_items if item.get("hit") is False)
    # Rule H is permanent: hafu is locked to the extreme ticket regardless of
    # the current sample's hits/misses. The stats still track post-Rule-H hafu
    # outcomes (only extreme legs grade as hafu now) for future calibration.
    hafu_active = True

    missed_by_match = Counter(
        str(item.get("match_no") or "")
        for item in graded_legs
        if item.get("hit") is False and item.get("match_no")
    )
    reuse_match_nos = sorted(match_no for match_no, count in missed_by_match.items() if count >= 2)
    reuse_active = bool(reuse_match_nos)
    burned_teams: set[str] = set()
    for item in graded_legs:
        if item.get("hit") is False and item.get("match_no") in set(reuse_match_nos):
            for field in ("home_team", "away_team"):
                value = str(item.get(field) or "").strip()
                if value:
                    burned_teams.add(value)

    rules = {
        "stable_base": {
            "active": strong_active,
            "action": "downgrade_low_price_bankers",
            "label": "强胆低赔降权",
            "reason": "强胆场低赔热门近期失误多于命中，底仓不能只靠低赔。",
            "stats": {"hits": strong_hits, "misses": strong_misses},
            "last_seen": run_date,
        },
        "comfort_favorite": {
            "active": comfort_active,
            "action": "directional_draw_cold_protection",
            "label": "舒服盘主客方向防平防冷",
            "reason": "1.75-2.05非强胆热门按主胜/客胜方向分别防平、防反向。",
            "stats": {"hits": comfort_hits, "misses": comfort_misses},
            "last_seen": run_date,
        },
        "total_goals": {
            "active": two_goal_active,
            "action": "promote_total_goals_two_ball",
            "label": "2球与小比分升权",
            "reason": "当前复盘样本中2球结果集中，分歧盘优先检查总进球2球。",
            "preferred_picks": preferred_ttg,
            "stats": dict(sorted(ttg_counts.items())),
            "last_seen": run_date,
        },
        "hafu": {
            "active": hafu_active,
            "action": "downgrade_half_full_non_extreme",
            "label": "半全场非极限票降权",
            "reason": "半全场近期命中差，除极限小注外优先改用总进球或让球。",
            "stats": {"hits": hafu_hits, "misses": hafu_misses},
            "last_seen": run_date,
        },
        "reuse_guard": {
            "active": reuse_active,
            "action": "avoid_reusing_missed_match_story",
            "label": "同场错误剧本复用限制",
            "reason": "同一场多次误判会拖累多张串，后续限制单场跨票重复。",
            "match_nos": reuse_match_nos[:8],
            "burned_teams": sorted(burned_teams)[:16],
            "stats": dict(sorted(missed_by_match.items())),
            "last_seen": run_date,
        },
    }

    notes: list[str] = []
    if strong_active:
        notes.append("强胆低赔近期失真，底仓必须降权并寻找让球/总进球支撑。")
    if comfort_active:
        notes.append("舒服盘继续按主客方向防平防冷，热门打出时不得误记为冷门。")
    if two_goal_active:
        notes.append("2球结果近期集中，分歧盘优先检查总进球2球和小比分路径。")
    if hafu_active:
        notes.append("半全场近期命中差，非极限票降权，优先改用总进球/让球。")
    if reuse_active:
        notes.append("同场错误剧本复用风险升高，单场不要拖累多张串。")

    memory["decision_policy"] = {
        "version": POLICY_VERSION,
        "updated_at": _now_iso(),
        "last_review_date": run_date,
        "rules": rules,
        "notes": notes[:8],
    }


def _bucket_key(league: str, role: str, pool: str) -> str:
    return f"{league or 'unknown'}::{role or 'unknown'}::{pool or 'unknown'}"


def _update_pattern_buckets(
    memory: dict[str, Any],
    *,
    run_date: str,
    context: dict[str, Any],
    graded_legs: list[dict[str, Any]],
) -> None:
    """Track EV-weighted hit/miss per (league × role × pool) bucket."""

    match_index = {
        str(item.get("match_no") or ""): item for item in (context.get("matches") or [])
    }
    buckets = memory.setdefault("pattern_buckets", {})
    # Decay all existing bucket EV scores so stale signals fade.
    for entry in buckets.values():
        entry["ev_score"] = round(float(entry.get("ev_score") or 0.0) * PATTERN_BUCKET_EV_DECAY, 4)
    for leg in graded_legs:
        match_no = str(leg.get("match_no") or "")
        match = match_index.get(match_no)
        if not match:
            continue
        league = str(match.get("league") or "")
        role = str(match.get("role") or "")
        pool = str(leg.get("pool") or "")
        key = _bucket_key(league, role, pool)
        entry = buckets.setdefault(
            key,
            {
                "league": league,
                "role": role,
                "pool": pool,
                "hits": 0,
                "misses": 0,
                "sample_size": 0,
                "ev_score": 0.0,
                "last_seen": None,
            },
        )
        entry["last_seen"] = run_date
        entry["sample_size"] = int(entry.get("sample_size") or 0) + 1
        try:
            odds = float(leg.get("odds") or 0.0)
        except (TypeError, ValueError):
            odds = 0.0
        if leg.get("hit") is True:
            entry["hits"] = int(entry.get("hits") or 0) + 1
            entry["ev_score"] = round(float(entry.get("ev_score") or 0.0) + (odds - 1.0), 4)
        elif leg.get("hit") is False:
            entry["misses"] = int(entry.get("misses") or 0) + 1
            entry["ev_score"] = round(float(entry.get("ev_score") or 0.0) - 1.0, 4)


def _update_oracle_learnings(
    memory: dict[str, Any],
    *,
    run_date: str,
    context: dict[str, Any],
    results: dict[str, dict[str, str]],
) -> None:
    """For every match with a known had outcome, persist the (league, pool, pick) we
    *should* have picked. Generator can later use this to bias scoring toward
    historically-winning league/pool combinations."""

    match_index = {
        str(item.get("match_no") or ""): item for item in (context.get("matches") or [])
    }
    learnings: list[dict[str, Any]] = list(memory.get("oracle_learnings") or [])
    for match_no, row in results.items():
        match = match_index.get(match_no)
        if not match:
            continue
        league = str(match.get("league") or "")
        for pool in ("had", "hhad", "ttg", "hafu", "crs"):
            actual = row.get(pool)
            actual_odds = row.get(f"{pool}_odds")
            if not actual or not actual_odds:
                continue
            try:
                price = float(actual_odds)
            except (TypeError, ValueError):
                continue
            learnings.append(
                {
                    "date": run_date,
                    "match_no": match_no,
                    "league": league,
                    "pool": pool,
                    "winning_pick": actual,
                    "winning_odds": price,
                }
            )
    # Keep the most recent entries (cap to avoid unbounded growth).
    memory["oracle_learnings"] = learnings[-PATTERN_BUCKET_RECENT_LIMIT * 6 :]


def _hot_odds_in_range(value: str) -> bool:
    try:
        odds_text = value.split("(", 1)[1].split(")", 1)[0]
        return 1.75 <= float(odds_text) <= 2.05
    except (IndexError, TypeError, ValueError):
        return False


def _favorite_from_hot_direction(value: str) -> str | None:
    if "主胜" in value:
        return "胜"
    if "客胜" in value:
        return "负"
    if "平局" in value:
        return "平"
    return None


def _remember_inspiration(memory: dict[str, Any], item: dict[str, Any]) -> None:
    memory.setdefault("recent_inspirations", []).append(item)


def _build_insights(memory: dict[str, Any]) -> list[str]:
    insights: list[str] = []
    if memory_pattern_positive(memory, "user_revision_hafu_draw_away"):
        insights.append("半全场平/负近期有效，谨慎客胜盘可升权。")
    if memory_pattern_positive(memory, "comfort_risk_draw_or_cold"):
        insights.append("舒服盘防平防冷持续有效，非强胆低赔热门不得当胆。")
    if memory_pattern_positive(memory, "variable_draw_protection"):
        insights.append("变量场继续保留平局、平/平、1:1保护。")
    if memory_pattern_positive(memory, "strong_banker_positive", min_hits=2):
        insights.append("强胆场优先正路和打穿表达，不机械反热门。")
    return insights[:6]


def _write_memory(output_dir: Path | str, memory: dict[str, Any]) -> None:
    path = strategy_memory_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()
