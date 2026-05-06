"""CLI tool: 给定 Poisson 单核腿，找出与主单**完全独立**的 2 串 1 候选。

解决 2026-05-06 出现的"反向覆盖"bug 类——LLM 推荐了与主单 had 三选反向的腿
当作 hedge，而它实际是反向押注。这个工具用 `find_safe_second_legs` 做规则筛
选 + 联合 EV/命中率排序，让人工不用再嘴算。

用法：
    uv run python scripts/jczq_suggest_second_leg.py \\
        --date 2026-05-06 --solo "周三003 crs 0:0" \\
        --top 8

    # 自动从 final-plan.json 读主单：
    uv run python scripts/jczq_suggest_second_leg.py --date 2026-05-06 --auto

输出：候选腿表，按"完全独立 → 反向 → 已用过"排序，附联合赔率 / 命中率 / EV。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch, JczqDailyPlan
from nutmeg.services.jczq_diagnostics import find_safe_second_legs
from nutmeg.services.jczq_intelligence import (
    compute_analytics,
    compute_poisson_edges,
    poisson_edge_index,
)


def _load_matches(context_path: Path) -> list[JczqDailyMatch]:
    ctx = json.loads(context_path.read_text(encoding="utf-8"))
    matches: list[JczqDailyMatch] = []
    for item in ctx["matches"]:
        legs = [
            JczqDailyLeg(
                match_no=c["match_no"], league=c["league"],
                home_team=c["home_team"], away_team=c["away_team"],
                pool=c["pool"], play=c["play"], pick=c["pick"],
                odds=float(c["odds"]),
                logic=c.get("logic", ""),
                goal_line=c.get("goal_line", ""),
                odds_update=c.get("odds_update", ""),
            )
            for c in item["candidates"]
        ]
        matches.append(JczqDailyMatch(
            match_no=item["match_no"], match_date=item["match_date"],
            match_time=item["match_time"], league=item["league"],
            home_team=item["home_team"], away_team=item["away_team"],
            status=item["status"], hot_direction=item["hot_direction"],
            role=item["role"], confidence_note=item["confidence_note"],
            candidates=legs,
        ))
    return matches


def _load_main_plans_from_final(final_plan_json: Path) -> list[JczqDailyPlan]:
    """Reconstruct lightweight JczqDailyPlan list from a final-plan.json file."""

    if not final_plan_json.exists():
        return []
    payload = json.loads(final_plan_json.read_text(encoding="utf-8"))
    plans: list[JczqDailyPlan] = []
    for ticket in payload.get("tickets", []):
        legs: list[JczqDailyLeg] = []
        for leg in ticket.get("legs", []):
            legs.append(JczqDailyLeg(
                match_no=leg["match_no"],
                league=leg.get("league", ""),
                home_team=leg.get("home_team", ""),
                away_team=leg.get("away_team", ""),
                pool=leg["pool"],
                play=leg.get("play", ""),
                pick=leg["pick"],
                odds=float(leg.get("odds", 0)),
                logic="",
                goal_line=str(leg.get("goal_line", "")),
            ))
        plans.append(JczqDailyPlan(
            name=ticket.get("name", ticket.get("id", "")),
            kind=ticket.get("kind", ticket.get("id", "")),
            description="",
            legs=legs,
            total_odds=float(ticket.get("total_odds", 0.0)),
            two_yuan_return=0.0,
            risk_note="",
        ))
    return plans


def _parse_solo(arg: str) -> tuple[str, str, str]:
    parts = arg.strip().split()
    if len(parts) != 3:
        raise SystemExit(
            f"--solo 格式必须是 '<match_no> <pool> <pick>'，例如 '周三003 crs 0:0'，得到 {arg!r}"
        )
    return parts[0], parts[1], parts[2]


def _solo_from_final(final_plan_json: Path) -> tuple[str, str, str] | None:
    """Auto-detect the Poisson solo leg from final-plan.json."""
    if not final_plan_json.exists():
        return None
    payload = json.loads(final_plan_json.read_text(encoding="utf-8"))
    for ticket in payload.get("tickets", []):
        if ticket.get("kind") == "poisson_solo" and len(ticket.get("legs", [])) == 1:
            leg = ticket["legs"][0]
            return leg["match_no"], leg["pool"], leg["pick"]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="目标日期 (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default=".nutmeg-data/jczq")
    parser.add_argument(
        "--solo",
        default=None,
        help="单核腿，格式 '<match_no> <pool> <pick>'，例如 '周三003 crs 0:0'",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="自动从 final-plan.json 读取 poisson_solo 腿和主单",
    )
    parser.add_argument("--top", type=int, default=8, help="输出前 N 个候选")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    daily_dir = output_dir / "daily" / args.date
    context_path = daily_dir / "context.json"
    final_plan_path = daily_dir / "debate" / "final-plan.json"

    if not context_path.exists():
        print(f"context.json not found: {context_path}", file=sys.stderr)
        sys.exit(2)

    matches = _load_matches(context_path)

    # Resolve solo leg.
    if args.auto:
        solo = _solo_from_final(final_plan_path)
        if solo is None:
            print("--auto 失败：final-plan.json 里找不到 poisson_solo 票", file=sys.stderr)
            sys.exit(2)
    elif args.solo:
        solo = _parse_solo(args.solo)
    else:
        print("必须提供 --solo 或 --auto", file=sys.stderr)
        sys.exit(2)

    # Resolve main plans (auto from final-plan.json or empty).
    main_plans = _load_main_plans_from_final(final_plan_path) if args.auto else []
    if not main_plans and final_plan_path.exists():
        # Auto-load even without --auto, since it's the most useful behavior.
        main_plans = _load_main_plans_from_final(final_plan_path)

    # Compute Poisson edges + analytics for coinflip detection.
    edges = poisson_edge_index(compute_poisson_edges(matches))
    analytics = compute_analytics(matches)
    coinflip_match_nos = {
        mn for mn, ana in analytics.items() if ana.is_three_way_coinflip
    }

    candidates = find_safe_second_legs(
        solo_match_no=solo[0], solo_pool=solo[1], solo_pick=solo[2],
        matches=matches, main_plans=main_plans,
        poisson_edge_index=edges,
        rule_e_coinflip_match_nos=coinflip_match_nos,
    )

    # Render
    print(f"\n=== 2 串 1 候选 — 单核 {solo[0]} {solo[1]} {solo[2]} ===")
    print(f"主单已加载 {len(main_plans)} 张票（来源：{final_plan_path}）")
    print()
    print(
        f"{'候选腿':<28}{'赔率':>7}{'edge':>9}{'命中率':>8}"
        f"{'组合赔率':>10}{'联合命中率':>12}{'EV系数':>9}  独立性"
    )
    print("-" * 100)
    rendered = 0
    for c in candidates:
        if rendered >= args.top:
            break
        label = f"{c.leg_match_no} {c.pool} {c.pick}"
        edge_str = f"{c.edge:+.1%}" if c.edge is not None else "    N/A"
        flag = ""
        if c.independence == "完全独立" and not c.conflicts:
            flag = "✓ 独立"
        elif c.independence == "已用过":
            flag = "✗ 已用"
        elif c.independence == "反向":
            flag = "✗ 反向"
        else:
            flag = c.independence
        if c.conflicts:
            flag += " (" + "; ".join(c.conflicts[:1]) + ")"
        print(
            f"{label:<28}{c.odds:>7.2f}{edge_str:>9}{c.fair_hit_rate:>7.1%}"
            f"{c.combined_odds:>9.1f}x{c.joint_hit_rate:>11.2%}"
            f"{c.joint_ev:>9.3f}  {flag}"
        )
        rendered += 1
    print()


if __name__ == "__main__":
    main()
