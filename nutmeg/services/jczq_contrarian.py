"""spec §34 — 反面引擎：专打不稳定场的逆向读盘。

背景（决策链 critique §4「想象力不足」+ 用户 2026-06-07 质疑 + 06-06 神户 0-5 实证）：
tiered 引擎是"热门焊死"的——A 档要 had≤1.65 真热门，pick'em 混战不够格进 A 直接被
撤退/降格；唯一的反面档 D 被 loss-churn 阉割且只能当零 edge 小注。结果系统**在最该
亮判断的不稳定比赛里只会跳过或骑墙**（06-06 鹿岛vs神户我选了"平"，实际神户客场 5-0）。

本模块**正面补上这个能力**：挑出 A 档放弃的混战场，用三个**可计算、非嘴算**的结构信号
找出"被高估的热门"，把它的反面当**一等候选**呈现（带信心 + 依据）：
  1. **euro_inflated**（最强）：体彩 implied(热门) 远高于欧赔 de-vig fair —— 欧赔是独立
     sharp 基准，体彩把热门灌水 = 资金/大众造热，sharp 不认 → 站反面。（§29 gap 的反向用法）
  2. **pickem**：主客 implied 接近 —— 典型混战，主场/热门光环虚。
  3. **soft_fav**：热门 had 落 1.55–2.10 软热带（§31）—— 非锁。

诚实定位：**非 edge、非概率断言**（−13% 抽水里无正期望），是**读盘视角**——系统性地把
"该站反面"的场摆到台面、允许高信心，而不是永远降格成彩票。纯确定性、无 LLM、无 I/O。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutmeg.services.jczq_bold_combos import OUTCOMES, BoldMatch, _fair_from_odds

# --- 阈值（spec §34.1） ---------------------------------------------------------
PICKEM_SPREAD: float = 0.12       # |implied(主) − implied(客)| < 此 → pick'em 混战
SOFT_FAV_MIN: float = 1.55        # 热门 had 软热带下界（§31）
SOFT_FAV_MAX: float = 2.10        # 软热带上界
EURO_FADE_GAP: float = 0.05       # 体彩 implied(热门) − 欧赔 fair(热门) ≥ 此 → 灌水反面
EURO_VALUE_MIN: float = 0.04      # 欧赔 fair(某边) − 体彩 implied ≥ 此 → 该边被体彩低估

_LABEL: dict[str, str] = {"home": "主胜", "draw": "平", "away": "客胜"}
_CONF_ORDER: dict[str, int] = {"强反": 0, "中反": 1, "弱反": 2}


@dataclass(frozen=True, slots=True)
class ContrarianRead:
    """一场不稳定比赛的逆向读盘结论。"""

    match_no: str
    home: str
    away: str
    fade_from: str            # 被高估的热门方向标签（主胜/客胜）
    fade_to: str              # 该站的反面方向标签（客胜/平/主胜）
    confidence: str           # 强反 / 中反 / 弱反
    flags: tuple[str, ...]    # 触发的结构信号
    reasons: list[str] = field(default_factory=list)
    euro_gap: float | None = None     # 体彩 implied(热门) − 欧赔 fair(热门)
    value_to: float | None = None     # 欧赔 fair(反面) − 体彩 implied(反面)


def _has_usable_had(tc: dict[str, float]) -> bool:
    return all(tc.get(o) and tc.get(o, 0) > 1.0 for o in OUTCOMES)


def compute_contrarian_reads(matches: list[BoldMatch]) -> list[ContrarianRead]:
    """spec §34.1 — 确定性挑出今晚最该站反面的场（按信心 + 灌水幅度排序）。"""
    reads: list[ContrarianRead] = []
    for m in matches:
        tc = m.tc_odds or {}
        if not _has_usable_had(tc):
            continue
        imp = _fair_from_odds(tc)
        if not imp:
            continue
        # 热门 = 主/客胜里 had 更低的一方（忽略平）
        fav = "home" if tc["home"] <= tc["away"] else "away"
        dog = "away" if fav == "home" else "home"
        flags: list[str] = []
        reasons: list[str] = []

        if abs(imp["home"] - imp["away"]) < PICKEM_SPREAD:
            flags.append("pickem")
            reasons.append(
                f"主客接近(Δ{abs(imp['home'] - imp['away']):.0%})——典型混战，热门光环虚"
            )

        fav_odds = tc[fav]
        if SOFT_FAV_MIN <= fav_odds <= SOFT_FAV_MAX:
            flags.append("soft_fav")
            reasons.append(f"热门仅软热(@{fav_odds:.2f})，非锁")

        euro = m.euro_fair_prob or {}
        euro_gap: float | None = None
        value_to: float | None = None
        fade_to: str | None = None
        has_euro = all(euro.get(o) for o in OUTCOMES)
        if has_euro:
            euro_gap = imp[fav] - euro[fav]
            if euro_gap >= EURO_FADE_GAP:
                flags.append("euro_inflated")
                reasons.append(
                    f"体彩把热门灌水(体彩{imp[fav]:.0%} vs 欧赔{euro[fav]:.0%}, "
                    f"+{euro_gap:.0%})——sharp 不认"
                )
        # 触发器只有 pickem（真混战）或 euro_inflated（sharp 说热门是假的）。
        # soft_fav 太普通（几乎每个中等主队热门都落软热带），单独触发会糊成 monochrome
        # 噪声——它只当信心加成，不当触发器。
        if "pickem" not in flags and "euro_inflated" not in flags:
            continue

        if has_euro:
            vals = {o: euro[o] - imp[o] for o in OUTCOMES}
            best = max((o for o in OUTCOMES if o != fav), key=lambda o: vals[o])
            fade_to = best
            value_to = vals[best]
            if value_to >= EURO_VALUE_MIN:
                reasons.append(
                    f"欧赔看好被体彩低估的是{_LABEL[best]}(欧赔高{value_to:.0%})"
                )
        elif "pickem" in flags:
            fade_to = dog
        else:  # euro_inflated 但无欧赔不可能；兜底
            fade_to = "draw"

        if fade_to is None or fade_to == fav:
            continue

        score = ("euro_inflated" in flags) * 2 + ("pickem" in flags) + ("soft_fav" in flags)
        conf = "强反" if score >= 3 else "中反" if score == 2 else "弱反"

        reads.append(
            ContrarianRead(
                match_no=m.match_no, home=m.home, away=m.away,
                fade_from=_LABEL[fav], fade_to=_LABEL[fade_to],
                confidence=conf, flags=tuple(flags), reasons=reasons,
                euro_gap=euro_gap, value_to=value_to,
            )
        )

    reads.sort(key=lambda r: (_CONF_ORDER[r.confidence], -(r.euro_gap or 0.0)))
    return reads


def render_contrarian_section(reads: list[ContrarianRead]) -> str:
    """spec §34.2 — 渲染「§D 反面视角」并进 jczq-today 决策包。"""
    lines = ["## D. 反面视角（A 档放弃的不稳定场 · 逆向读盘）", ""]
    if not reads:
        lines.append("今晚无明显反面机会（盘面无 pick'em / 软热灌水信号）。照 §A 即可。")
        return "\n".join(lines)
    lines.append(
        "> 专打 A 档够不上的混战场：欧赔(独立 sharp) + pick'em/软热 找**被高估的热门**，"
        "站其反面。**非 edge、读盘视角**——但允许当一等候选、可上信心，不再只当彩票。"
    )
    lines.append("")
    lines.append("| 场次 | 站反面 | 信心 | 依据 |")
    lines.append("|---|---|---|---|")
    for r in reads:
        why = "；".join(r.reasons[:2])
        lines.append(
            f"| {r.match_no} {r.home} vs {r.away} | 站 **{r.fade_to}**（反 {r.fade_from}） "
            f"| {r.confidence} | {why} |"
        )
    strong = [r for r in reads if r.confidence == "强反"]
    if strong:
        top = strong[0]
        lines.append("")
        lines.append(
            f"> 🔴 今晚最锋利的反面：**{top.match_no} {top.home} vs {top.away} 站 "
            f"{top.fade_to}**（{'；'.join(top.reasons[:2])}）。"
        )
    return "\n".join(lines)
