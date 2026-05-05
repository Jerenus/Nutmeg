"""One-shot 每日 brief：把今天我会手动跑的所有分析步骤打包成一个命令。

跑一次输出包含：
  1. 全天可售场次 + 角色 / 热门方向 / hhad 让球数 / 三方匀盘 / 高波动联赛
  2. compute_analytics() 的 vig / implied / EV gap 全表
  3. Poisson 拟合后的 +EV 腿（按 edge 排序）
  4. 角色桶分布（强胆 / 舒服盘 / draw_friendly / coinflip 计数）
  5. JczqDailyAdvisorService 自动生成的全部票（含 Rule A poisson_solo）
  6. 跟 Poisson edge 对照后，每张自动票里被模型强烈反对的腿

输出是结构化 Markdown，可以直接贴给 Claude 让它做投资建议，也可以人肉读。

用法:
    uv run python scripts/jczq_daily_brief.py                        # 今天 live
    uv run python scripts/jczq_daily_brief.py --date 2026-05-04      # 指定日期 live
    uv run python scripts/jczq_daily_brief.py --replay 2026-05-03    # 用已存的 context.json 回放
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_daily import (
    JczqDailyAdvisorService,
    _report_from_dict,
)
from nutmeg.services.jczq_intelligence import (
    LeaguePriorBaseline,
    PoissonEdgeEntry,
    compute_analytics,
    compute_poisson_edges,
)
from nutmeg.services.jczq_strategy_memory import (
    compute_league_ttg_volatility,
    load_strategy_memory,
)

POISSON_EDGE_THRESHOLD = 0.05  # surface legs with ≥ +5% Poisson edge


def _hhad_goal_line(match: JczqDailyMatch) -> str:
    for leg in match.candidates:
        if leg.pool == "hhad" and leg.goal_line:
            return leg.goal_line
    return ""


def _emit_markdown(
    *,
    run_date: str,
    matches: list[JczqDailyMatch],
    analytics: dict,
    plans: list,
    poisson_rows: list[PoissonEdgeEntry],
    poisson_index: dict[tuple[str, str, str], float],
    summary: str,
    official_last_update: str | None,
    league_volatility: dict[str, float],
) -> str:
    out: list[str] = []
    out.append(f"# JCZQ 每日 Brief — {run_date}")
    out.append("")
    out.append(f"官方赔率更新：{official_last_update or '未知'}")
    out.append(f"全天可售场次：{len(matches)}")
    out.append("")

    # 1. 盘面热度（含 Rule D 让球线 / Rule E coinflip / Rule C 高波动联赛）
    out.append("## 1. 盘面热度扫描")
    out.append("")
    out.append(
        "| 编号 | 联赛 | 对阵 | 热门方向 | 让球线 | 角色 | 强胆 | 舒服盘 | "
        "draw | coinflip | hi-vol联赛 |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for m in matches:
        handicap = _hhad_goal_line(m) or "—"
        a = analytics.get(m.match_no)
        if a is None:
            out.append(
                f"| {m.match_no} | {m.league} | {m.home_team} vs {m.away_team} | "
                f"{m.hot_direction} | {handicap} | {m.role} | -- | -- | -- | -- | -- |"
            )
            continue
        out.append(
            f"| {m.match_no} | {m.league} | {m.home_team} vs {m.away_team} | "
            f"{m.hot_direction} | {handicap} | {m.role} | "
            f"{'✓' if a.is_strong_banker else ''} | "
            f"{'✓' if a.is_comfort_risk else ''} | "
            f"{'✓' if a.is_draw_friendly else ''} | "
            f"{'⚠' if a.is_three_way_coinflip else ''} | "
            f"{'⚠' if a.is_high_volatility_league else ''} |"
        )
    out.append("")

    # 2. EV gap 表（HAD pool）
    out.append("## 2. HAD 池 implied probability 与联赛先验 gap")
    out.append("")
    out.append("| 编号 | P(胜) | P(平) | P(负) | gap(胜) | gap(平) | gap(负) | vig |")
    out.append("|---|---|---|---|---|---|---|---|")
    for m in matches:
        a = analytics.get(m.match_no)
        if a is None:
            continue
        gaps = a.ev_gaps.get("had", {})
        impl = a.implied_probs
        out.append(
            f"| {m.match_no} | {impl.get('胜', 0):.0%} | {impl.get('平', 0):.0%} | "
            f"{impl.get('负', 0):.0%} | {gaps.get('胜', 0):+.2f} | "
            f"{gaps.get('平', 0):+.2f} | {gaps.get('负', 0):+.2f} | "
            f"{a.vig_pct * 100:.1f}% |"
        )
    out.append("")

    # 3. 桶分布
    strong_count = sum(1 for a in analytics.values() if a.is_strong_banker)
    comfort_count = sum(1 for a in analytics.values() if a.is_comfort_risk)
    draw_count = sum(1 for a in analytics.values() if a.is_draw_friendly)
    upset_count = sum(1 for a in analytics.values() if a.is_upset_candidate)
    chaos_count = sum(1 for a in analytics.values() if a.is_chaos)
    coinflip_count = sum(1 for a in analytics.values() if a.is_three_way_coinflip)
    hi_vol_count = sum(1 for a in analytics.values() if a.is_high_volatility_league)
    out.append("## 3. 桶分布")
    out.append("")
    strong_note = "(≥3 → upset_cluster 触发)" if strong_count >= 3 else "(< 3，cluster 不触发)"
    comfort_note = "(≥3 → draw_cluster 触发)" if comfort_count >= 3 else "(< 3，cluster 不触发)"
    out.append(f"- 强胆场（had ≤ 1.35）: **{strong_count}** {strong_note}")
    out.append(f"- 舒服盘（1.75-2.05 非强胆）: **{comfort_count}** {comfort_note}")
    out.append(f"- draw_friendly（implied 平 > 先验+4pp）: **{draw_count}**")
    out.append(f"- upset_candidate（强胆 + EV 反向）: **{upset_count}**")
    out.append(f"- chaos（vig 高 + 三方接近）: **{chaos_count}**")
    out.append(
        f"- coinflip（Rule E：vig>12.5% + implied 极差<10pp，had 不可做杠杆）: **{coinflip_count}**"
    )
    out.append(
        f"- 高波动联赛（Rule C：近期 ttg 中位数 ≥ 2.7，低 ttg 腿降权）: **{hi_vol_count}**"
    )
    if league_volatility:
        rendered = ", ".join(
            f"{league}({median:g})"
            for league, median in sorted(league_volatility.items())
            if median >= 2.7
        )
        if rendered:
            out.append(f"  - 命中联赛：{rendered}")
    out.append("")

    # 4. Poisson +EV 腿
    out.append(f"## 4. Poisson 模型指出的 +EV 腿（edge ≥ +{POISSON_EDGE_THRESHOLD * 100:.0f}%）")
    out.append("")
    positive = [row for row in poisson_rows if row.edge >= POISSON_EDGE_THRESHOLD]
    if positive:
        out.append("| 标的 | 池 | 选项 | 市场 | 公允 | edge | 对阵 |")
        out.append("|---|---|---|---|---|---|---|")
        for row in positive[:25]:
            out.append(
                f"| {row.match_no} | {row.pool} | {row.pick} | "
                f"{row.market_odd:.2f} | {row.fair_odd:.2f} | "
                f"**{row.edge:+.1%}** | {row.home} vs {row.away} |"
            )
    else:
        out.append("（今天无 ≥ +5% edge 的腿）")
    out.append("")

    # 5. 系统自动生成的票
    out.append("## 5. 系统自动票（generator 输出）")
    out.append("")
    out.append(summary)
    out.append("")
    for plan in plans:
        if not plan.legs:
            continue
        legs_text = " × ".join(
            f"{leg.match_no}{leg.play}{leg.pick}@{leg.odds}" for leg in plan.legs
        )
        out.append(f"**{plan.name}（{plan.kind}）{plan.total_odds:.2f} 倍**")
        out.append(f"`{legs_text}`")
        # 区分"vig-only 负"（-8~-15%，标准抽水）与"Poisson 主动反对"（≤ -20%）
        strong_warnings = []
        for leg in plan.legs:
            edge = poisson_index.get((leg.match_no, leg.pool, leg.pick))
            if edge is not None and edge <= -0.20:
                strong_warnings.append(
                    f"❌ {leg.match_no} {leg.pool} {leg.pick} Poisson edge {edge:+.1%}（强烈反对）"
                )
        if strong_warnings:
            out.append("Poisson 强烈反对腿（edge ≤ -20%）：")
            for w in strong_warnings:
                out.append(f"- {w}")
        out.append("")

    # 6. 给 Claude 的指令模板
    out.append("## 6. 投递给 Claude 的指令模板")
    out.append("")
    out.append("把以上 1-5 节复制贴给 Claude，附加这句话即可触发跟今天一致的决策流程：")
    out.append("")
    out.append("> 用 Nutmeg 改造版的 jczq 系统对今天进行投资建议（Rule A-F 已落库）：")
    out.append("> 1. 跟 Poisson +EV 腿走，第 4 节里 edge ≥ +15% 的腿优先做 Poisson 单核票；")
    out.append("> 2. 出 5-6 张票：稳健底仓 / 主方案 / Poisson 单核 / 反大众 / 极限娱乐；")
    out.append("> 3. 主方案禁用 had ≤ 1.40 的强胆托底（Rule B），改用让球/总进球支撑；")
    out.append("> 4. 标 ⚠coinflip 的场次不要用 had 平/胜/负 做杠杆（Rule E），允许 hhad/ttg/crs；")
    out.append("> 5. 标 ⚠hi-vol 联赛的场次不要选 ttg ≤ 2 球（Rule C），优先 3+球或半全场；")
    out.append("> 6. 标⚠让球线为空的 hhad 腿一律不要（Rule D）；")
    out.append("> 7. 给注金分配（小注娱乐预算 100 元假设）+ 标注最看好那张。")
    out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="目标日期 (YYYY-MM-DD)，默认今天 live")
    parser.add_argument("--replay", default=None, help="从已存 context.json 回放，传日期")
    parser.add_argument(
        "--output-dir",
        default="/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq",
        help="JCZQ 数据根目录",
    )
    parser.add_argument(
        "--write",
        default=None,
        help="把 brief markdown 写到指定路径（默认 stdout）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.replay:
        run_date = args.replay
        ctx_path = output_dir / "daily" / run_date / "context.json"
        if not ctx_path.exists():
            print(f"context.json not found: {ctx_path}", file=sys.stderr)
            sys.exit(2)
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        report = _report_from_dict(ctx)
        # Re-generate plans from current code so report.plans 是新版
        service = JczqDailyAdvisorService.__new__(JczqDailyAdvisorService)
        service.__init__()  # type: ignore[misc]
        memory = load_strategy_memory(output_dir)
        league_vol = compute_league_ttg_volatility(memory)
        analytics = compute_analytics(
            report.matches,
            baseline=service._baseline_provider,
            league_volatility=league_vol,
        )
        plans = service._build_plans(
            report.matches,
            instruction=None,
            strategy_memory=memory,
            analytics=analytics,
        )
        official = report.official_last_update
        summary = service._summary(plans, revision_instruction=None, strategy_memory=memory)
    else:
        from nutmeg.interfaces.cli import build_jczq_daily_advisor_service

        service = build_jczq_daily_advisor_service(provider="live")
        run_date = args.date or _today_iso()
        report = service.build_report(
            run_date=run_date,
            output_dir=output_dir,
            dispatch_telegram=False,
            dry_run=True,
            record_final=False,
        )
        memory = load_strategy_memory(output_dir)
        league_vol = compute_league_ttg_volatility(memory)
        analytics = compute_analytics(
            report.matches,
            baseline=LeaguePriorBaseline(),
            league_volatility=league_vol,
        )
        plans = report.plans
        official = report.official_last_update
        summary = report.summary

    poisson_rows = compute_poisson_edges(report.matches)
    poisson_index = {(row.match_no, row.pool, row.pick): row.edge for row in poisson_rows}

    md = _emit_markdown(
        run_date=run_date,
        matches=report.matches,
        analytics=analytics,
        plans=plans,
        poisson_rows=poisson_rows,
        poisson_index=poisson_index,
        summary=summary,
        official_last_update=official,
        league_volatility=league_vol,
    )

    if args.write:
        Path(args.write).write_text(md, encoding="utf-8")
        print(f"Wrote brief: {args.write}", file=sys.stderr)
    else:
        print(md)


def _today_iso() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


if __name__ == "__main__":
    main()
