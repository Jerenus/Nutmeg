"""spec §35 — 机会雷达底座：可插拔"读盘透镜"注册表。

背景：用户要求"持续增强决策系统的多元化与创造力，挖掘不被注意的机会，作为未来决策的底座"。
现状问题：系统只从**单一视角**（热门结构 + 反面）看盘，而机会是**多视角**的——同一盘面换
个透镜就看见别人没看见的东西，且系统**已经在算却没用上**的信号还有好几类（drift/dispersion/
大小球价值）。

本模块是**底座**，不是又一条规则：定义统一的 `Opportunity` + 透镜协议，每个透镜扫一遍盘、
喊出一类机会；决策包聚合呈现成「§D 机会雷达」。**加未来透镜 = 注册一个函数**，这就是
"持续增强多样性"的可扩展结构。

定位同 §34：**非 edge、非概率**，读盘视角——把多角度的机会摆上台面、可上信心，而不是
只会盯热门。纯确定性、无 LLM、无 I/O。

已落地透镜：
- **反面**（§34）：pickem / euro_inflated 找被高估的热门、站反面。
- **异动**（§35）：欧赔 opening→live 的 steam（sharp money 流向）+ 体彩 lag（没跟上=价值窗口）。
后续可挂：分歧盘（dispersion）、大小球价值（ttg vs 欧赔大小球）、平局价值、联赛进球偏差…
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable

from nutmeg.services.jczq_bold_combos import (
    OUTCOMES,
    BoldMatch,
    _devig_map,
    _fair_from_odds,
    aggregate_ttg_to_over_under,
    dispersion_score,
)
from nutmeg.services.jczq_contrarian import compute_contrarian_reads

_LABEL: dict[str, str] = {"home": "主胜", "draw": "平", "away": "客胜"}

# --- 异动透镜阈值（spec §35.2） ---
STEAM_MIN: float = 0.04       # 欧赔 implied 朝某边移动 ≥ 此 → 算 steam
STEAM_STRONG: float = 0.07    # 强 steam
LAG_MIN: float = 0.04         # 欧赔 live − 体彩 implied ≥ 此 → 体彩没跟上=价值窗口

# --- 大小球价值透镜阈值（spec §35.4） ---
TOTALS_MIN: float = 0.06      # |欧赔 P(over) − 体彩 P(over)| ≥ 此 → 算错价
TOTALS_STRONG: float = 0.10   # 强错价

# --- 平局价值透镜阈值（spec §35.5） ---
DRAW_VALUE_MIN: float = 0.05  # 欧赔 P(平) − 体彩 P(平) ≥ 此 → 体彩低估平局
DRAW_VALUE_STRONG: float = 0.08

# --- 分歧盘透镜阈值（spec §35.6）—— 注意：这是"谨慎"信号、非下注方向 ---
# 反思教训（05-30：绝对阈值标了 11/15 = 噪声）：改用**相对 + 封顶**——只标今晚
# 明显高于全场中位数、且最软的前 2 场，而不是"任何超过绝对线的场"。
DISPERSION_FLOOR: float = 0.13       # 绝对地板（再相对也得真高）
DISPERSION_REL_FACTOR: float = 1.30  # 须 ≥ 全场中位数 ×此（明显冒头）
DISPERSION_TOP_N: int = 2            # 最多标今晚最软的 2 场
DISPERSION_STRONG: float = 0.20


@dataclass(frozen=True, slots=True)
class Opportunity:
    """一个透镜在一场比赛上喊出的机会。"""

    lens: str          # 透镜名（反面 / 异动 / …）
    match_no: str
    home: str
    away: str
    pick: str          # 指向的方向标签（主胜/平/客胜）
    confidence: str    # 强 / 中 / 弱
    reason: str


# ---------------------------------------------------------------------------
# 透镜 1：反面（§34 适配）
# ---------------------------------------------------------------------------


def contrarian_lens(matches: list[BoldMatch]) -> list[Opportunity]:
    out: list[Opportunity] = []
    for r in compute_contrarian_reads(matches):
        conf = {"强反": "强", "中反": "中", "弱反": "弱"}.get(r.confidence, "弱")
        out.append(
            Opportunity(
                lens="反面", match_no=r.match_no, home=r.home, away=r.away,
                pick=r.fade_to, confidence=conf,
                reason=f"反{r.fade_from} · " + "；".join(r.reasons[:2]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 透镜 2：异动（steam + 体彩 lag）—— spec §35.2
# ---------------------------------------------------------------------------


def drift_lens(matches: list[BoldMatch]) -> list[Opportunity]:
    out: list[Opportunity] = []
    for m in matches:
        op = _fair_from_odds(m.euro_opening or {})
        lv = _fair_from_odds(m.euro_odds or {})
        if not op or not lv:
            continue
        move = {o: lv[o] - op[o] for o in OUTCOMES}
        side = max(OUTCOMES, key=lambda o: move[o])
        if move[side] < STEAM_MIN:
            continue
        tc = _fair_from_odds(m.tc_odds or {})
        lag = (lv[side] - tc[side]) if tc else 0.0
        strong_steam = move[side] >= STEAM_STRONG
        has_lag = lag >= LAG_MIN
        conf = "强" if (strong_steam and has_lag) else "中" if (strong_steam or has_lag) else "弱"
        reason = (
            f"欧赔开盘→现在朝{_LABEL[side]}移动 +{move[side]:.0%}（sharp money 流向）"
        )
        if has_lag:
            reason += f"；体彩没跟上(欧赔{lv[side]:.0%}>体彩{tc[side]:.0%})=价值窗口"
        out.append(
            Opportunity(
                lens="异动", match_no=m.match_no, home=m.home, away=m.away,
                pick=_LABEL[side], confidence=conf, reason=reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 透镜 3：大小球价值（体彩 ttg vs 欧赔大小球错价）—— spec §35.4
# ---------------------------------------------------------------------------


def totals_lens(matches: list[BoldMatch]) -> list[Opportunity]:
    """全新进球维度：把体彩 ttg 聚合到欧赔的大小球线，比 P(over)。欧赔比体彩更看好
    over → 价值在大球；反之小球。与胜平负维度正交，最大化雷达多样性。"""
    out: list[Opportunity] = []
    for m in matches:
        tc_ttg = _devig_map(m.ttg_odds or {})
        ou_fair = _devig_map(m.ou_odds or {})
        if not tc_ttg or not ou_fair or not m.ou_line:
            continue
        tc_ou = aggregate_ttg_to_over_under(tc_ttg, m.ou_line)
        tc_over = tc_ou.get("over")
        eu_over = ou_fair.get("over")
        if tc_over is None or eu_over is None:
            continue
        diff = eu_over - tc_over  # 欧赔 P(over) − 体彩 P(over)
        if abs(diff) < TOTALS_MIN:
            continue
        side = "大球" if diff > 0 else "小球"
        conf = "强" if abs(diff) >= TOTALS_STRONG else "中"
        reason = (
            f"欧赔大小球 vs 体彩 ttg 错价（线 {m.ou_line:g}）："
            f"欧赔 P(over)={eu_over:.0%} vs 体彩 {tc_over:.0%} → 价值在 {side}"
        )
        out.append(
            Opportunity(
                lens="大小球", match_no=m.match_no, home=m.home, away=m.away,
                pick=side, confidence=conf, reason=reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 透镜 4：平局价值（公众不爱押平 → 体彩系统性低估平局）—— spec §35.5
# ---------------------------------------------------------------------------


def draw_value_lens(matches: list[BoldMatch]) -> list[Opportunity]:
    """散户天然回避押平，体彩(散户驱动)系统性低估平局；欧赔(sharp)不会。比 P(平)：
    欧赔 − 体彩 ≥ 阈值 → 平局被低估。与反面不同——专扫平局、即使热门不虚也能发现平价值。"""
    out: list[Opportunity] = []
    for m in matches:
        tc = _fair_from_odds(m.tc_odds or {})
        euro = m.euro_fair_prob or {}
        if not tc or not all(euro.get(o) for o in OUTCOMES):
            continue
        gap = euro["draw"] - tc["draw"]
        if gap < DRAW_VALUE_MIN:
            continue
        conf = "强" if gap >= DRAW_VALUE_STRONG else "中"
        reason = (
            f"欧赔(sharp)看平 {euro['draw']:.0%} > 体彩 {tc['draw']:.0%}"
            f"（+{gap:.0%}）——公众不爱押平、体彩低估平局"
        )
        out.append(
            Opportunity(
                lens="平局", match_no=m.match_no, home=m.home, away=m.away,
                pick="平", confidence=conf, reason=reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 透镜 5：分歧盘（书商吵翻=盘面软）—— spec §35.6
# ⚠️ 诚实定位：这是"谨慎/高方差"**警示**，不是下注方向。pick="谨慎"。与 chaos 值
# (§3.5 已含 dispersion) 部分重叠——保留是因为它把"别把这场热门当稳腿"显式摆上台。
# ---------------------------------------------------------------------------


def dispersion_lens(matches: list[BoldMatch]) -> list[Opportunity]:
    scored: list[tuple[BoldMatch, float]] = []
    for m in matches:
        disp = dispersion_score(m.per_book_odds or {})
        vals = [disp[o] for o in OUTCOMES if disp.get(o)]
        if vals:
            scored.append((m, sum(vals) / len(vals)))
    if not scored:
        return []
    median = statistics.median(d for _m, d in scored)
    bar = max(DISPERSION_FLOOR, median * DISPERSION_REL_FACTOR)
    standout = sorted(
        (sm for sm in scored if sm[1] >= bar), key=lambda sm: sm[1], reverse=True
    )[:DISPERSION_TOP_N]
    out: list[Opportunity] = []
    for m, mean_disp in standout:
        conf = "强" if mean_disp >= DISPERSION_STRONG else "中"
        reason = (
            f"~29 家国际书商赔率分歧最大（均 {mean_disp:.0%}，今晚中位数 {median:.0%}）"
            "——盘面软、定价不可信，这场别把热门当稳腿/别重注"
        )
        out.append(
            Opportunity(
                lens="分歧", match_no=m.match_no, home=m.home, away=m.away,
                pick="谨慎·高方差", confidence=conf, reason=reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 注册表 + 扫描 + 渲染
# ---------------------------------------------------------------------------

# 加未来透镜 = 在这里追加一行 (名称, 函数)。这就是"持续增强多样性"的扩展点。
LENSES: list[tuple[str, Callable[[list[BoldMatch]], list[Opportunity]]]] = [
    ("反面", contrarian_lens),
    ("异动", drift_lens),
    ("大小球", totals_lens),
    ("平局", draw_value_lens),
    ("分歧", dispersion_lens),
]

_CONF_ORDER: dict[str, int] = {"强": 0, "中": 1, "弱": 2}


def scan_opportunities(matches: list[BoldMatch]) -> dict[str, list[Opportunity]]:
    """spec §35.1 — 跑全部透镜，按透镜名分组（每组按信心排序）。"""
    by_lens: dict[str, list[Opportunity]] = {}
    for name, fn in LENSES:
        ops = fn(matches)
        ops.sort(key=lambda o: _CONF_ORDER.get(o.confidence, 2))
        by_lens[name] = ops
    return by_lens


def render_opportunity_radar(by_lens: dict[str, list[Opportunity]]) -> str:
    """spec §35.3 — 渲染「§D 机会雷达」多视角段，并进 jczq-today 决策包。"""
    lines = ["## D. 机会雷达（多视角 · 挖不被注意的机会）", ""]
    total = sum(len(v) for v in by_lens.values())
    if total == 0:
        lines.append("今晚雷达无信号（无反面 / 异动机会）。照 §A 即可。")
        return "\n".join(lines)
    lines.append(
        "> 每个透镜从不同角度扫盘（热门结构外的机会）。**非 edge、读盘视角**——"
        "把多角度机会摆上台、可上信心，不只盯热门。"
    )
    for name, _fn in LENSES:
        ops = by_lens.get(name) or []
        if not ops:
            continue
        lines.append("")
        lines.append(f"### {name}（{len(ops)}）")
        lines.append("| 场次 | 指向 | 信心 | 依据 |")
        lines.append("|---|---|---|---|")
        for o in ops:
            lines.append(
                f"| {o.match_no} {o.home} vs {o.away} | **{o.pick}** | {o.confidence} | {o.reason} |"
            )
    # 跨透镜共振：同一场被 ≥2 个透镜指向同一边 → 最值得注意
    by_match: dict[str, list[Opportunity]] = {}
    for ops in by_lens.values():
        for o in ops:
            by_match.setdefault(o.match_no, []).append(o)
    resonance = [
        ops for ops in by_match.values()
        if len(ops) >= 2 and len({o.pick for o in ops}) == 1
    ]
    if resonance:
        lines.append("")
        for ops in resonance:
            o = ops[0]
            lenses = "+".join(x.lens for x in ops)
            lines.append(
                f"> 🔆 多视角共振：**{o.match_no} {o.home} vs {o.away} → {o.pick}**"
                f"（{lenses} 同时指向）——今晚最值得注意。"
            )
    return "\n".join(lines)
