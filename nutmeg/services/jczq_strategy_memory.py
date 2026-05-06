from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MEMORY_VERSION = 2
POLICY_VERSION = 1
MEMORY_RELATIVE_PATH = Path("memory") / "strategy-memory.json"

PATTERN_BUCKET_EV_DECAY = 0.85
PATTERN_BUCKET_RECENT_LIMIT = 30


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
) -> dict[str, Any]:
    memory = _normalize_memory(load_strategy_memory(output_dir))
    reviewed_dates = set(str(item) for item in memory.get("reviewed_dates") or [])
    if run_date in reviewed_dates:
        memory["updated_at"] = _now_iso()
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
    policy = memory.get("decision_policy") or {}
    notes = [str(item) for item in policy.get("notes") or [] if str(item).strip()]
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
