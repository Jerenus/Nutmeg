"""spec §32 — `jczq-today` 单一决策入口的渲染层 + 裁量派生层。

根因（见 ``docs/jczq-decision-chain-critique.md``）：用户工作流是"让 agent 跑 jczq
分析组合任务"，但没有钉死的确定性入口 → 每个 agent（GPT/Claude）自行即兴挑命令/引擎/
Poisson → 路径分叉。本模块把 tiered 引擎的确定性产出包成一个**所有 agent 共读的决策包**：
钉死指令头 + §A 引擎票面 + §B 盘面底座 + §C **有界**裁量问题。

纯确定性、无 LLM 调用。不重造票面（§A 原样嵌入 ``render_tiered_plan``），不动任何选腿逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_opportunity import (
    render_opportunity_radar,
    scan_opportunities,
)
from nutmeg.services.jczq_tiered import TieredPlan, render_tiered_plan

# spec §32.3 — 引擎原生热度分层阈值（favourite = 最低主胜/客胜 had）。
HARD_HOT_MAX: float = 1.50
SOFT_HOT_MIN: float = 1.55
SOFT_HOT_MAX: float = 2.10
# coinflip：无明确热门（favourite 偏高）且三方接近。
COINFLIP_SPREAD_MAX: float = 1.20

PACKET_SCHEMA_VERSION = "v1"
DEFAULT_POISSON_FLOOR = 0.05


@dataclass(frozen=True, slots=True)
class JudgmentQuestion:
    """spec §32.4 — 一个引擎触发的真裁量点（不让 agent 重审全盘）。"""

    q_id: str
    kind: str  # ALL_EMPTY / A_EMPTY / B_DEGRADED / SOFTHOT
    prompt: str
    default: str
    match_no: str = ""


def _favourite_had(match: BoldMatch) -> float | None:
    """最低主胜/客胜 had（被看好那一方），忽略平。无可用 had 时返回 None。"""
    vals = [
        o for o in (match.tc_odds.get("home"), match.tc_odds.get("away"))
        if o and o > 1.0
    ]
    return min(vals) if vals else None


def classify_heat(match: BoldMatch) -> str:
    """spec §32.3 — 把一场按 favourite had 分到 硬热(短赔)/软热/coinflip/普通。

    仅赔率口径：§31.1 完整硬热还需欧赔 fair≥0.55 + 逻辑，故标"短赔"诚实降级。
    """
    fav = _favourite_had(match)
    if fav is None:
        return ""
    if fav <= HARD_HOT_MAX:
        return "硬热(短赔)"
    if SOFT_HOT_MIN <= fav <= SOFT_HOT_MAX:
        return "软热"
    vals = [
        o for o in (
            match.tc_odds.get("home"),
            match.tc_odds.get("draw"),
            match.tc_odds.get("away"),
        )
        if o and o > 1.0
    ]
    if fav > SOFT_HOT_MAX and len(vals) == 3 and (max(vals) - min(vals)) <= COINFLIP_SPREAD_MAX:
        return "coinflip"
    return "普通"


def derive_judgment_questions(
    plan: TieredPlan, matches: list[BoldMatch]
) -> list[JudgmentQuestion]:
    """spec §32.4 — 确定性、有界地枚举今天真正需要判断的几个点。

    全空 → 只问空仓；否则按 A 空 / B 退化 / 软热腿（仅出现在已出票的档中）派生。
    """
    qs: list[JudgmentQuestion] = []
    tiers = plan.tiers or []
    if all(t is None for t in tiers):
        qs.append(
            JudgmentQuestion(
                q_id="Q_ALL_EMPTY",
                kind="ALL_EMPTY",
                prompt="今日盘面无任一档（引擎判定候选不足）。是否空仓？",
                default="空仓",
            )
        )
        return qs

    a_tier = tiers[0] if len(tiers) > 0 else None
    b_tier = tiers[1] if len(tiers) > 1 else None

    if a_tier is None:
        qs.append(
            JudgmentQuestion(
                q_id="Q_A_EMPTY",
                kind="A_EMPTY",
                prompt=(
                    "今晚无稳健底仓（A=None：无 ≤1.65 真热门，或最低组合总赔率超 5.5 上限）。"
                    "接受空底仓，还是你有独立理由强做一注稳健？"
                ),
                default="接受空底仓",
            )
        )

    if plan.ttg_pool_empty and b_tier is not None:
        qs.append(
            JudgmentQuestion(
                q_id="Q_B_DEGRADED",
                kind="B_DEGRADED",
                prompt=(
                    "B 主方案因 ttg 池空已退化为 hhad/had 混搭（无中线腿稀释让球反向）。仍出 B？"
                ),
                default="仍出 B",
            )
        )

    match_by_no = {m.match_no: m for m in matches}
    pick_by_match: dict[str, str] = {}
    for tier in tiers:
        if tier is None:
            continue
        for tl in tier.legs:
            lg = tl.leg
            pick_by_match.setdefault(
                lg.match_no, f"{lg.pick_label}@{lg.tc_odds:.2f}"
            )

    for mno in sorted(pick_by_match):
        m = match_by_no.get(mno)
        if m is None or classify_heat(m) != "软热":
            continue
        fav = _favourite_had(m)
        fav_str = f"{fav:.2f}" if fav is not None else "—"
        default_pick = pick_by_match[mno]
        qs.append(
            JudgmentQuestion(
                q_id=f"Q_SOFTHOT_{mno}",
                kind="SOFTHOT",
                match_no=mno,
                prompt=(
                    f"{m.home} vs {m.away} 软热（favourite @{fav_str}），"
                    f"引擎默认 {default_pick}。§31.2 这场剧本："
                    "平 / 冷 / 还是有独立理由仍站正路？"
                ),
                default=default_pick,
            )
        )
    return qs


def render_today_packet(
    plan: TieredPlan,
    matches: list[BoldMatch],
    poisson_edge_index: dict[tuple[str, str, str], float],
    *,
    poisson_floor: float = DEFAULT_POISSON_FLOOR,
) -> str:
    """spec §32.2 — 组装决策包：指令头 + §A 票面 + §B 底座 + §C 裁量问题。"""
    lines: list[str] = []
    lines.append(
        f"# JCZQ 今日决策包 — {plan.run_date} · 引擎=tiered {plan.version} · "
        f"packet {PACKET_SCHEMA_VERSION}"
    )
    lines.append("")
    lines.append("> **【给 agent 的钉死指令】这是今天唯一的决策来源。**")
    lines.append(
        "> 1. 不要在退役 generator / 旧 brief / 各 spec 间即兴发挥——本包已是引擎确定性产出。"
    )
    lines.append("> 2. §A 是引擎已定票面，照单执行或整张不买，**勿改腿**。")
    lines.append("> 3. 只在 §C「裁量问题」上动判断，按 schema 逐条作答。")
    lines.append(
        "> 4. 你与别的 agent 在某 q_id 答案不同 = 该场高不确定 → **减注或剔除**，不是二选一赌运气。"
    )
    lines.append("")

    lines.append("## A. 引擎票面（确定性，勿改腿）")
    lines.append("")
    lines.append(render_tiered_plan(plan))
    lines.append("")

    lines.append("## B. 盘面底座（引擎口径，无 generator 偏差）")
    lines.append("")
    lines.append("### B1 热度分层")
    lines.append("")
    lines.append("| 编号 | 对阵 | 最低 had | 热度 |")
    lines.append("|---|---|---|---|")
    for m in matches:
        fav = _favourite_had(m)
        fav_str = f"{fav:.2f}" if fav is not None else "—"
        lines.append(
            f"| {m.match_no} | {m.home} vs {m.away} | {fav_str} | "
            f"{classify_heat(m) or '—'} |"
        )
    lines.append("")
    lines.append(
        f"### B2 Poisson +EV 列表（raw，无 R25/F2/F3，edge ≥ +{poisson_floor * 100:.0f}%）"
    )
    lines.append("")
    positive = sorted(
        (kv for kv in poisson_edge_index.items() if kv[1] >= poisson_floor),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if positive:
        lines.append("| 编号 | 池 | 选项 | edge |")
        lines.append("|---|---|---|---|")
        for (mno, market, pick), edge in positive[:25]:
            lines.append(f"| {mno} | {market} | {pick} | {edge:+.1%} |")
    else:
        lines.append("（今日无 ≥ +5% edge 的腿。）")
    lines.append("")
    lines.append(
        "> 注：本引擎不预测胜负、长期为负（−13% 抽水）。+EV 列表只对 A 档两个结构假设"
        "（§29 gap / §28 R25）有意义；**B/D/E 是方差娱乐、零 edge，不读此表搏 edge。**"
    )
    lines.append("")

    lines.append("## C. 裁量问题（其余一切已被引擎定死）")
    lines.append("")
    questions = derive_judgment_questions(plan, matches)
    if not questions:
        lines.append("今日无裁量问题，照 §A 执行（或整张不买）。")
    else:
        for q in questions:
            lines.append(f"- **{q.q_id}**：{q.prompt}（引擎默认：{q.default}）")
        lines.append("")
        lines.append("### 作答 schema")
        lines.append("")
        lines.append("| q_id | 你的决定 | confidence(1-5) | 一行理由 |")
        lines.append("|---|---|---|---|")
        for q in questions:
            lines.append(f"| {q.q_id} |  |  |  |")
    lines.append("")

    # spec §35 — 机会雷达：多视角透镜（反面/异动/…）扫盘，补足大胆度/多样性，
    # 挖 A 档热门结构外不被注意的机会。底座可插拔，加透镜不动此处。
    lines.append(render_opportunity_radar(scan_opportunities(matches)))

    return "\n".join(lines)
