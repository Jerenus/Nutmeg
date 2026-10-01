"""Markdown 报告：一张策略表 + regime 分桶。只排版，不下结论。"""
from __future__ import annotations

from nutmeg.gym.run import GymResult


def _row(name: str, s: dict) -> str:
    ci = f"[{s['ci'][0]:+,.0f}, {s['ci'][1]:+,.0f}]"
    return (f"| {name} | {s['keys']} | {s['stake']:,.0f} | {s['net']:+,.0f} | {s['roi']*100:+.1f}% "
            f"| {s['max_drawdown']:,.0f} | {ci} | {s['p_positive']:.2f} "
            f"| {s.get('regret_vs_flat', 0):+,.0f} | {s.get('regret_vs_best', 0):+,.0f} "
            f"| {s['illegal']} | {s['pending']} | {s['forced_flat_keys']} |")


def render(result: GymResult) -> str:
    lines = [f"# gym · {result.run_id}",
             f"板面日 {len(result.days)}（{result.days[0] if result.days else '-'} → "
             f"{result.days[-1] if result.days else '-'}）· 足彩期 {len(result.issues)}"
             + (f" · 跳过 {result.skipped}" if result.skipped else ""),
             "",
             "| 策略 | 日/期 | 投入 | 净 | ROI | 最大回撤 | 净额 95% CI | P(净>0) | 相对空仓 "
             "| 相对最优 | 非法票 | 未结 | 止损空仓日 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in result.policies:
        lines.append(_row(name, result.per_policy[name]))
    lines.append("")
    lines.append("## regime 分桶（竞彩：当日 ≥0.70 热门场数；足彩：任九奖金三分位 hot/mid/cold）")
    lines.append("")
    lines.append("| 策略 | regime | 日/期 | 投入 | 净 | ROI | P(净>0) |")
    lines.append("|---|---|---|---|---|---|---|")
    for name in result.policies:
        for regime, s in result.regimes.get(name, {}).items():
            lines.append(f"| {name} | {regime} | {s['keys']} | {s['stake']:,.0f} "
                         f"| {s['net']:+,.0f} | {s['roi']*100:+.1f}% | {s['p_positive']:.2f} |")
    return "\n".join(lines) + "\n"
