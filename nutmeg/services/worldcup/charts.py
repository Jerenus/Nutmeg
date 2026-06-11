"""matplotlib 图表四件套(spec §5.2)— 全部返回 PNG bytes,Agg 后端无窗口。

CJK 字体与 ReportLab 共用同一候选路径;全部探测失败时退化为英文队名 id
(报告必须能出,spec §7)。
"""
from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .results import WcResult  # noqa: E402
from .sim import SimOutput  # noqa: E402
from .tournament import Tournament, _table_rows, rank_group  # noqa: E402

logger = logging.getLogger(__name__)

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
ACCENT = "#1a6b54"      # 世界杯主题绿
ACCENT_PREV = "#b9d6cd"


def _cjk_prop() -> font_manager.FontProperties | None:
    for path in _CJK_FONT_CANDIDATES:
        try:
            return font_manager.FontProperties(fname=path)
        except Exception:  # noqa: BLE001
            continue
    logger.warning("charts: 无 CJK 字体,退化英文队名")
    return None


def _zh(t: Tournament, team: str, prop) -> str:
    if prop is None:
        return team
    rec = t.teams.get(team)
    return rec.zh if rec else team


def _to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def champion_bar_png(
    t: Tournament, sim: SimOutput, sim_prev: SimOutput | None, top_n: int = 10
) -> bytes:
    prop = _cjk_prop()
    ranked = sorted(sim.probs.items(), key=lambda kv: kv[1]["champion"],
                    reverse=True)[:top_n][::-1]
    labels = [_zh(t, team, prop) for team, _ in ranked]
    today = [p["champion"] * 100 for _, p in ranked]
    fig, ax = plt.subplots(figsize=(6, 0.45 * len(ranked) + 1))
    if sim_prev:
        prev = [sim_prev.probs.get(team, {}).get("champion", 0) * 100
                for team, _ in ranked]
        ax.barh([i - 0.2 for i in range(len(ranked))], prev, height=0.38,
                color=ACCENT_PREV, label="昨日")
        ax.barh([i + 0.2 for i in range(len(ranked))], today, height=0.38,
                color=ACCENT, label="今日")
        ax.legend(prop=prop, fontsize=8)
    else:
        ax.barh(range(len(ranked)), today, height=0.6, color=ACCENT)
    ax.set_yticks(range(len(ranked)))
    ax.set_yticklabels(labels, fontproperties=prop, fontsize=9)
    ax.set_xlabel("夺冠概率 %", fontproperties=prop, fontsize=9)
    for i, v in enumerate(today):
        ax.text(v + 0.3, i + (0.2 if sim_prev else 0), f"{v:.1f}%",
                va="center", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    return _to_png(fig)


def champion_trend_png(
    t: Tournament, history: list[SimOutput], top_n: int = 6
) -> bytes:
    prop = _cjk_prop()
    latest = history[-1]
    leaders = [team for team, _ in sorted(
        latest.probs.items(), key=lambda kv: kv[1]["champion"], reverse=True
    )[:top_n]]
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    for team in leaders:
        xs = [s.run_date[5:] for s in history]
        ys = [s.probs.get(team, {}).get("champion", 0) * 100 for s in history]
        ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.5,
                label=_zh(t, team, prop))
    ax.set_ylabel("夺冠概率 %", fontproperties=prop, fontsize=9)
    ax.legend(prop=prop, fontsize=8, ncols=2)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.autofmt_xdate(rotation=45)
    return _to_png(fig)


def group_table_png(t: Tournament, results: list[WcResult]) -> bytes:
    """各组积分表(小组赛阶段)— 真实赛果算积分,未赛为 0。"""
    import random

    prop = _cjk_prop()
    goals = {
        (r.home, r.away): (r.goals_h_90, r.goals_a_90)
        for r in results if r.goals_h_90 is not None
    }
    n_groups = len(t.groups)
    cols = 4 if n_groups >= 4 else n_groups
    rows = -(-n_groups // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(2.1 * cols, 1.7 * rows))
    # 1x1 时 plt.subplots 返回单 Axes 非数组;>1 时先物化成 list,
    # 避免 flatiter 被 zip 消耗后尾部清理切片错位。
    flat = list(axes.flat) if n_groups > 1 else [axes]
    rng = random.Random(0)  # 仅排序稳定用,真实表不靠抽签
    for ax, (g, members) in zip(flat, sorted(t.groups.items())):
        order = rank_group(members, goals, rng)
        rows_data = _table_rows(members, goals)
        cell = [[_zh(t, team, prop), str(rows_data[team][0])] for team in order]
        ax.axis("off")
        table = ax.table(cellText=cell, colLabels=[f"组 {g}", "分"],
                         colWidths=[0.74, 0.26],
                         loc="center", cellLoc="left")
        table.auto_set_font_size(False)
        table.set_fontsize(7)
        if prop is not None:
            for c in table.get_celld().values():
                c.get_text().set_fontproperties(prop)
    for ax in flat[n_groups:]:
        ax.axis("off")
    return _to_png(fig)
