"""每日 brief 的「赔率冲突点」节渲染。

Phase 3b piece 3。把价值引擎冲突点（``JczqValueReport``）渲染成 brief 的一节，
并与 psychology 心理信号、情报（阵容/伤停）**并列呈现**——多方因素同场摆放，
供 debate 工作流权衡。

冲突点是主驱动：永远来自价值引擎（模型 vs 国际市场赔率）。psychology 信号与情报
是可选的补充输入（按 ``match_no`` 索引）；某场缺这两类时只渲染冲突点。某场未对齐
国际赔率（500.com / API-Football）时如实标注覆盖缺口，绝不补空信号。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutmeg.services.jczq_value_bridge import JczqValueReport
from nutmeg.services.psychology.schemas import SignalReading


@dataclass(slots=True, frozen=True)
class MatchInformation:
    """一个 JCZQ 比赛的情报（阵容 / 伤停）。"""

    lineup_note: str | None = None
    injury_notes: list[str] = field(default_factory=list)


def render_conflict_section(
    report: JczqValueReport,
    *,
    psychology_by_match: dict[str, list[SignalReading]] | None = None,
    information_by_match: dict[str, MatchInformation] | None = None,
) -> str:
    """渲染 brief 的「## 赔率冲突点」节。

    Args:
        report: 价值引擎对当天比赛的冲突点报告（``JczqValueBridge.evaluate_day``）。
        psychology_by_match: 可选，{match_no: [SignalReading]}，并列呈现的心理信号。
        information_by_match: 可选，{match_no: MatchInformation}，并列呈现的情报。
    """
    psychology_by_match = psychology_by_match or {}
    information_by_match = information_by_match or {}

    out: list[str] = []
    out.append("## 赔率冲突点")
    out.append("")
    out.append(
        "> 由价值引擎驱动（Dixon-Coles 模型概率 vs 国际市场公允概率 → edge）。"
        "心理信号与情报（阵容/伤停）并列呈现，供 debate 多方权衡。"
    )
    out.append("")

    if not report.matches:
        out.append("（今日无可评估的比赛）")
        out.append("")
        return "\n".join(out)

    out.append(
        f"覆盖率：{report.aligned_count}/{len(report.matches)} 场已对齐"
        f"国际赔率（{report.coverage_pct:.0%}）。"
    )
    out.append("")

    for entry in report.matches:
        out.append(
            f"### {entry.match_no} {entry.home_team} vs {entry.away_team}"
            f"（{entry.league}）"
        )
        out.append("")

        if not entry.aligned:
            out.append(f"- ⚪ **冲突点**：{entry.coverage_note}")
            out.append("")
            _append_factors(out, entry.match_no, psychology_by_match, information_by_match)
            continue

        if entry.fixture_id:
            swap = "（朝向已翻转）" if entry.orientation_swapped else ""
            out.append(f"对齐 fixture_id `{entry.fixture_id}`{swap}")
            out.append("")

        if entry.conflicts:
            out.append("**价值引擎冲突点**")
            out.append("")
            out.append("| 玩法 | 选项 | 体彩赔率 | 公允概率 | 模型概率 | edge | 评级 |")
            out.append("|---|---|---|---|---|---|---|")
            for c in entry.conflicts:
                out.append(
                    f"| {c.market_key} | {c.outcome_name} | {c.best_odds:.2f} | "
                    f"{c.market_probability:.0%} | {c.model_probability:.0%} | "
                    f"**{c.edge:+.0%}** | {c.rating} |"
                )
            out.append("")
        else:
            note = entry.coverage_note or "无 +edge 冲突点"
            out.append(f"- ⚪ **价值引擎冲突点**：{note}")
            out.append("")

        _append_factors(out, entry.match_no, psychology_by_match, information_by_match)

    return "\n".join(out)


def _append_factors(
    out: list[str],
    match_no: str,
    psychology_by_match: dict[str, list[SignalReading]],
    information_by_match: dict[str, MatchInformation],
) -> None:
    """并列附加心理信号 + 情报两类多方因素。"""
    readings = psychology_by_match.get(match_no, [])
    if readings:
        out.append("**心理信号**")
        out.append("")
        for reading in readings:
            view = reading.outcome_view or "—"
            evidence = "；".join(reading.evidence) if reading.evidence else "—"
            out.append(
                f"- {reading.provider}（{reading.market} → {view}，"
                f"信念 {reading.conviction:.0%}）：{evidence}"
            )
        out.append("")

    info = information_by_match.get(match_no)
    if info is not None and (info.lineup_note or info.injury_notes):
        out.append("**情报（阵容/伤停）**")
        out.append("")
        if info.lineup_note:
            out.append(f"- 阵容：{info.lineup_note}")
        for note in info.injury_notes:
            out.append(f"- 伤停：{note}")
        out.append("")
