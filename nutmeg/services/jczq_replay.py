"""Replay an existing daily ``context.json`` through the upgraded JCZQ generator.

CLI 包装见 ``nutmeg.interfaces.cli.jczq_replay``。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nutmeg.services.jczq_daily import JczqDailyAdvisorService

POOL_KEY_MAP_HAD = {"胜": "h", "平": "d", "负": "a"}
POOL_KEY_MAP_HHAD = {"让胜": "h", "让平": "d", "让负": "a"}
POOL_KEY_MAP_HAFU = {
    "胜/胜": "hh", "胜/平": "hd", "胜/负": "ha",
    "平/胜": "dh", "平/平": "dd", "平/负": "da",
    "负/胜": "ah", "负/平": "ad", "负/负": "aa",
}
POOL_KEY_MAP_TTG = {
    "0球": "s0", "1球": "s1", "2球": "s2",
    "3球": "s3", "4球": "s4", "5球": "s5", "6球": "s6", "7+球": "s7",
}
POOL_KEY_MAP_CRS = {
    "1:0": "s01s00", "2:0": "s02s00", "2:1": "s02s01", "3:1": "s03s01",
    "0:0": "s00s00", "1:1": "s01s01", "2:2": "s02s02",
    "0:1": "s00s01", "0:2": "s00s02", "1:2": "s01s02",
}


def reconstruct_payload(context: dict[str, Any]) -> dict[str, Any]:
    sub_match_list: list[dict[str, Any]] = []
    for match in context.get("matches") or []:
        pools: dict[str, dict[str, Any]] = defaultdict(dict)
        goal_line = ""
        for leg in match.get("candidates") or []:
            pool = leg.get("pool")
            pick = leg.get("pick")
            odds = leg.get("odds")
            if not pool or not pick or odds in (None, ""):
                continue
            mapping = {
                "had": POOL_KEY_MAP_HAD,
                "hhad": POOL_KEY_MAP_HHAD,
                "hafu": POOL_KEY_MAP_HAFU,
                "ttg": POOL_KEY_MAP_TTG,
                "crs": POOL_KEY_MAP_CRS,
            }.get(pool, {})
            key = mapping.get(pick)
            if key is None:
                continue
            pools[pool][key] = str(odds)
            if pool == "hhad" and leg.get("goal_line"):
                goal_line = leg.get("goal_line")
                pools[pool]["goalLine"] = goal_line
        sub_match_list.append(
            {
                "matchNumStr": match.get("match_no"),
                "matchDate": match.get("match_date"),
                "matchTime": match.get("match_time"),
                "leagueAbbName": match.get("league"),
                "homeTeamAbbName": match.get("home_team"),
                "awayTeamAbbName": match.get("away_team"),
                "matchStatus": match.get("status") or "Selling",
                "poolList": [
                    {"poolCode": pool.upper(), "poolStatus": "Selling", "single": 1, "allUp": 1}
                    for pool in pools.keys()
                ],
                "had": pools.get("had", {}),
                "hhad": pools.get("hhad", {}),
                "ttg": pools.get("ttg", {}),
                "hafu": pools.get("hafu", {}),
                "crs": pools.get("crs", {}),
            }
        )
    return {
        "lastUpdateTime": context.get("official_last_update") or "unknown",
        "matchInfoList": [
            {"businessDate": context.get("run_date"), "subMatchList": sub_match_list},
        ],
    }


class ReplayProvider:
    source_api = "replay://context"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def fetch(self) -> dict[str, Any]:
        return self._payload


@dataclass(slots=True)
class ReplayLegResult:
    plan: str
    match_no: str
    pool: str
    pick: str
    odds: float
    actual: str | None
    hit: bool


@dataclass(slots=True)
class ReplayResult:
    run_date: str
    match_count: int
    leg_rows: list[ReplayLegResult] = field(default_factory=list)
    rendered_text: str = ""


def _grade_lines(plans, results: dict[str, dict[str, str]]) -> tuple[list[ReplayLegResult], list[str]]:
    rows: list[ReplayLegResult] = []
    lines: list[str] = []
    for plan in plans:
        if not plan.legs:
            continue
        hit_count = 0
        odds_product = 1.0
        for leg in plan.legs:
            actual = (results.get(leg.match_no) or {}).get(leg.pool)
            hit = actual == leg.pick
            if hit:
                hit_count += 1
            odds_product *= leg.odds
            rows.append(
                ReplayLegResult(
                    plan=plan.kind,
                    match_no=leg.match_no,
                    pool=leg.pool,
                    pick=leg.pick,
                    odds=leg.odds,
                    actual=actual,
                    hit=hit,
                )
            )
        lines.append(
            f"  {plan.kind:<14} {plan.name:<10} {hit_count}/{len(plan.legs)} 命中"
            f"  总赔率 {odds_product:.2f}  整票"
            f"{'命中' if hit_count == len(plan.legs) else '未中'}"
        )
    return rows, lines


def replay_with_new_generator(
    *,
    run_date: str,
    input_dir: Path,
) -> ReplayResult:
    daily_dir = Path(input_dir) / "daily" / run_date
    context = json.loads((daily_dir / "context.json").read_text(encoding="utf-8"))
    review_payload = json.loads((daily_dir / "review.json").read_text(encoding="utf-8"))
    results = review_payload.get("results") or {}

    payload = reconstruct_payload(context)
    sub_count = len(payload["matchInfoList"][0]["subMatchList"])

    service = JczqDailyAdvisorService(provider=ReplayProvider(payload))
    report = service.build_report(run_date=run_date)

    out: list[str] = []
    out.append(f"\n=== Replay {run_date}: {sub_count} matches ===")
    out.append("\n--- Plans (new generator) ---")
    rows, plan_lines = _grade_lines(report.plans, results)
    out.extend(plan_lines)

    out.append("\n--- New plans only ---")
    for plan in report.plans:
        if plan.kind not in {"draw_cluster", "upset_cluster"} or not plan.legs:
            continue
        out.append(f"\n{plan.kind} ({plan.name}):")
        for leg in plan.legs:
            actual = (results.get(leg.match_no) or {}).get(leg.pool)
            hit_mark = "✅" if actual == leg.pick else "❌"
            out.append(
                f"  {leg.match_no} {leg.pool} {leg.pick}@{leg.odds} → {actual} {hit_mark}"
            )

    return ReplayResult(
        run_date=run_date,
        match_count=sub_count,
        leg_rows=rows,
        rendered_text="\n".join(out),
    )
