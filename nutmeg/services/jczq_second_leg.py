"""2 串 1 候选搜索（核心腿 + 主单的安全 hedge 候选）。

CLI 包装见 ``nutmeg.interfaces.cli.jczq_second_leg``。
"""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch, JczqDailyPlan
from nutmeg.services.jczq_diagnostics import find_safe_second_legs
from nutmeg.services.jczq_intelligence import (
    compute_analytics,
    compute_poisson_edges,
    poisson_edge_index,
)


def load_matches_from_context(context_path: Path) -> list[JczqDailyMatch]:
    ctx = json.loads(Path(context_path).read_text(encoding="utf-8"))
    matches: list[JczqDailyMatch] = []
    for item in ctx["matches"]:
        legs = [
            JczqDailyLeg(
                match_no=c["match_no"],
                league=c["league"],
                home_team=c["home_team"],
                away_team=c["away_team"],
                pool=c["pool"],
                play=c["play"],
                pick=c["pick"],
                odds=float(c["odds"]),
                logic=c.get("logic", ""),
                goal_line=c.get("goal_line", ""),
                odds_update=c.get("odds_update", ""),
            )
            for c in item["candidates"]
        ]
        matches.append(
            JczqDailyMatch(
                match_no=item["match_no"],
                match_date=item["match_date"],
                match_time=item["match_time"],
                league=item["league"],
                home_team=item["home_team"],
                away_team=item["away_team"],
                status=item["status"],
                hot_direction=item["hot_direction"],
                role=item["role"],
                confidence_note=item["confidence_note"],
                candidates=legs,
            )
        )
    return matches


def load_main_plans_from_final(final_plan_json: Path) -> list[JczqDailyPlan]:
    """Reconstruct lightweight JczqDailyPlan list from a final-plan.json file."""

    final_plan_json = Path(final_plan_json)
    if not final_plan_json.exists():
        return []
    payload = json.loads(final_plan_json.read_text(encoding="utf-8"))
    plans: list[JczqDailyPlan] = []
    for ticket in payload.get("tickets", []):
        legs: list[JczqDailyLeg] = []
        for leg in ticket.get("legs", []):
            legs.append(
                JczqDailyLeg(
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
                )
            )
        plans.append(
            JczqDailyPlan(
                name=ticket.get("name", ticket.get("id", "")),
                kind=ticket.get("kind", ticket.get("id", "")),
                description="",
                legs=legs,
                total_odds=float(ticket.get("total_odds", 0.0)),
                two_yuan_return=0.0,
                risk_note="",
            )
        )
    return plans


def parse_solo(arg: str) -> tuple[str, str, str]:
    parts = arg.strip().split()
    if len(parts) != 3:
        raise ValueError(
            f"--solo 格式必须是 '<match_no> <pool> <pick>'，例如 '周三003 crs 0:0'，得到 {arg!r}"
        )
    return parts[0], parts[1], parts[2]


def solo_from_final(final_plan_json: Path) -> tuple[str, str, str] | None:
    final_plan_json = Path(final_plan_json)
    if not final_plan_json.exists():
        return None
    payload = json.loads(final_plan_json.read_text(encoding="utf-8"))
    top_level = _leg_tuple(payload.get("solo_leg"))
    if top_level is not None:
        return top_level

    tickets = payload.get("tickets", [])
    favorite_ticket_id = payload.get("favorite_ticket_id")
    for ticket in tickets:
        if ticket.get("id") == favorite_ticket_id or ticket.get("favorite") is True:
            legs = ticket.get("legs", [])
            if legs:
                return _leg_tuple(legs[0])

    for ticket in payload.get("tickets", []):
        legs = ticket.get("legs", [])
        if len(legs) == 1:
            return _leg_tuple(legs[0])
    return None


def _leg_tuple(raw: object) -> tuple[str, str, str] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return str(raw["match_no"]), str(raw["pool"]), str(raw["pick"])
    except KeyError:
        return None


def render_table(
    *,
    solo: tuple[str, str, str],
    main_plans: list[JczqDailyPlan],
    final_plan_path: Path,
    candidates,
    top: int,
) -> str:
    out: list[str] = []
    out.append(f"\n=== 2 串 1 候选 — 核心腿 {solo[0]} {solo[1]} {solo[2]} ===")
    out.append(f"主单已加载 {len(main_plans)} 张票（来源：{final_plan_path}）")
    out.append("")
    out.append(
        f"{'候选腿':<28}{'赔率':>7}{'edge':>9}{'命中率':>8}"
        f"{'组合赔率':>10}{'联合命中率':>12}{'EV系数':>9}  独立性"
    )
    out.append("-" * 100)
    rendered = 0
    for c in candidates:
        if rendered >= top:
            break
        label = f"{c.leg_match_no} {c.pool} {c.pick}"
        edge_str = f"{c.edge:+.1%}" if c.edge is not None else "    N/A"
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
        out.append(
            f"{label:<28}{c.odds:>7.2f}{edge_str:>9}{c.fair_hit_rate:>7.1%}"
            f"{c.combined_odds:>9.1f}x{c.joint_hit_rate:>11.2%}"
            f"{c.joint_ev:>9.3f}  {flag}"
        )
        rendered += 1
    out.append("")
    return "\n".join(out)


def suggest_second_legs(
    *,
    run_date: str,
    output_dir: Path,
    solo: tuple[str, str, str] | None = None,
    auto: bool = False,
    top: int = 8,
) -> str:
    """Return rendered text table (compatible with the legacy script output)."""

    output_dir = Path(output_dir)
    daily_dir = output_dir / "daily" / run_date
    context_path = daily_dir / "context.json"
    final_plan_path = daily_dir / "debate" / "final-plan.json"

    if not context_path.exists():
        raise FileNotFoundError(f"context.json not found: {context_path}")

    matches = load_matches_from_context(context_path)

    if auto:
        resolved_solo = solo_from_final(final_plan_path)
        if resolved_solo is None:
            raise ValueError("--auto 失败：final-plan.json 里找不到可用核心腿")
    elif solo is not None:
        resolved_solo = solo
    else:
        raise ValueError("必须提供 solo 或 auto")

    main_plans = load_main_plans_from_final(final_plan_path) if auto else []
    if not main_plans and final_plan_path.exists():
        main_plans = load_main_plans_from_final(final_plan_path)

    edges = poisson_edge_index(compute_poisson_edges(matches))
    analytics = compute_analytics(matches)
    coinflip_match_nos = {
        mn for mn, ana in analytics.items() if ana.is_three_way_coinflip
    }

    candidates = find_safe_second_legs(
        solo_match_no=resolved_solo[0],
        solo_pool=resolved_solo[1],
        solo_pick=resolved_solo[2],
        matches=matches,
        main_plans=main_plans,
        poisson_edge_index=edges,
        rule_e_coinflip_match_nos=coinflip_match_nos,
    )

    return render_table(
        solo=resolved_solo,
        main_plans=main_plans,
        final_plan_path=final_plan_path,
        candidates=candidates,
        top=top,
    )
