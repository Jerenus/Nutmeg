from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MEMORY_VERSION = 1
MEMORY_RELATIVE_PATH = Path("memory") / "strategy-memory.json"


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
        _write_memory(output_dir, memory)
        return memory

    reviewed_dates.add(run_date)
    memory["reviewed_dates"] = sorted(reviewed_dates)
    memory["sample_count"] = int(memory.get("sample_count") or 0) + 1
    memory["last_review_date"] = run_date
    memory["updated_at"] = _now_iso()

    _update_leg_patterns(memory, run_date=run_date, graded_legs=graded_legs)
    _update_match_patterns(memory, run_date=run_date, context=context, results=results)
    memory["insights"] = _build_insights(memory)
    memory["recent_inspirations"] = (memory.get("recent_inspirations") or [])[-20:]
    _write_memory(output_dir, memory)
    return memory


def render_strategy_memory_notes(memory: dict[str, Any], *, limit: int = 2) -> list[str]:
    notes = [str(item) for item in memory.get("insights") or [] if str(item).strip()]
    return notes[:limit]


def memory_pattern_positive(memory: dict[str, Any], key: str, *, min_hits: int = 1) -> bool:
    pattern = (memory.get("patterns") or {}).get(key) or {}
    hits = int(pattern.get("hits") or 0)
    misses = int(pattern.get("misses") or 0)
    return hits >= min_hits and hits >= misses


def _normalize_memory(payload: dict[str, Any]) -> dict[str, Any]:
    memory = dict(payload or {})
    memory.setdefault("version", MEMORY_VERSION)
    memory.setdefault("sample_count", 0)
    memory.setdefault("reviewed_dates", [])
    memory.setdefault("patterns", {})
    memory.setdefault("insights", [])
    memory.setdefault("recent_inspirations", [])
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
