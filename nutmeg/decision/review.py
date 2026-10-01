"""审票（2026-10-01 定位：机器＝风控官+账房+实验员，人＝下注者）。

人出方案，机器给三类意见：**否决**（有实证的坏结构）、**警告**、**数字**。否决只有两条，
都来自 403 天回放与复盘账：
- V1 期望回报率 < 0.5——"中了也亏"的帽内 max-P 形状（任九 −58%、竞彩 max-P −20%，CI 不含 0）；
- V2 与已购票共享裸单——假分散（26122 联死 73.8%、26133 ≈60%、09-28 五票同死 004）。
V3 倍投/重注只警告（证据不够硬：26121 ×50 中过一次）。
"""
from __future__ import annotations

import json
import statistics
from itertools import combinations
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.reconcile import normalize_selection

VETO_RATIO = 0.5
WARN_RATIO = 0.65
WARN_MULTIPLIER = 10
WARN_STAKE_SHARE = 0.5          # 单票 > 日帽一半


def prize_medians(data_dir: Path) -> dict[str, float | None]:
    """官方奖金缓存 → 任九/胜负彩一等奖每注奖金中位数（没有缓存 → None，不猜）。"""
    path = Path(data_dir) / "zucai" / "official-prizes.json"
    try:
        issues = json.loads(path.read_text(encoding="utf-8")).get("issues") or {}
    except (OSError, ValueError):
        return {"renjiu": None, "shengfucai": None}
    rj = [v["renjiu"]["stake_amount"] for v in issues.values()
          if (v.get("renjiu") or {}).get("stake_amount")]
    sfc = [v["sfc_first"]["stake_amount"] for v in issues.values()
           if (v.get("sfc_first") or {}).get("stake_amount")]
    return {"renjiu": statistics.median(rj) if rj else None,
            "shengfucai": statistics.median(sfc) if sfc else None}


def _modal_odds(leg: SlipLeg) -> float | None:
    """所选面里概率最高那面的赔率（缺 fair/odds → None）。"""
    if not leg.fair or not leg.odds or len(leg.odds) != len(leg.selections):
        return None
    best, best_p = None, -1.0
    for sel, odd in zip(leg.selections, leg.odds, strict=True):
        key = normalize_selection(leg.market, sel)
        p = float(leg.fair.get(key, 0.0)) if key else 0.0
        if p > best_p:
            best, best_p = float(odd), p
    return best


def expected_return_ratio(slip: BetSlip, *, prize_median: dict[str, float | None]) -> float | None:
    """E[派奖]/投入。竞彩：每串 P(全中)×模态赔率连乘；足彩：P(全对)×奖金中位数。缺数据 → None。"""
    if slip.channel in ("renjiu", "shengfucai"):
        p = slip.hit_probability
        prize = prize_median.get(slip.channel)
        if p is None or prize is None or not slip.stake_yuan:
            return None
        return round(p * prize * slip.multiplier / slip.stake_yuan, 3)
    covs = [leg.coverage for leg in slip.legs]
    odds = [_modal_odds(leg) for leg in slip.legs]
    if not covs or any(c is None for c in covs) or any(o is None for o in odds):
        return None
    ev = 0.0
    idx = range(len(slip.legs))
    for m in (slip.combo_sizes or (len(slip.legs),)):
        for combo in combinations(idx, m):
            p = 1.0
            payout = 2.0 * slip.multiplier
            for i in combo:
                p *= covs[i]
                payout *= odds[i]
            ev += p * payout
    return round(ev / slip.stake_yuan, 3) if slip.stake_yuan else None


def review(slip: BetSlip, diagnosis: dict, *, prize_median: dict[str, float | None],
           cap_day: int = 400) -> dict:
    """→ {ratio, verdicts: [{code, level, text}], vetoed: bool, lines: [str]}。"""
    verdicts: list[dict] = []
    ratio = expected_return_ratio(slip, prize_median=prize_median)
    if ratio is None:
        verdicts.append({"code": "V1", "level": "info",
                         "text": "期望回报率缺数据（腿缺 fair/赔率或无奖金缓存），V1 未检"})
    elif ratio < VETO_RATIO:
        verdicts.append({"code": "V1", "level": "veto",
                         "text": f"期望回报率 {ratio:.2f} < {VETO_RATIO}：中了也亏的帽内 max-P 形状"
                                 "（403 天回放 max-P −20%、任九 −58%）"})
    elif ratio < WARN_RATIO:
        verdicts.append({"code": "V1", "level": "warn",
                         "text": f"期望回报率 {ratio:.2f}（抽水基准约 0.64–0.86），偏向大热堆叠"})
    else:
        verdicts.append({"code": "V1", "level": "info", "text": f"期望回报率 {ratio:.2f}"})
    shared = diagnosis.get("shared_naked") or []
    if shared:
        keys = "、".join(f"{r['key']}{r['face']}" for r in shared)
        joint = (diagnosis.get("joint_death") or {}).get("p_all_die_at_least")
        verdicts.append({"code": "V2", "level": "veto",
                         "text": f"与已购票共享裸单 {len(shared)} 条（{keys}）"
                                 + (f"，联死 ≥{joint * 100:.0f}%" if joint is not None else "")
                                 + "：假分散（26122/26133/09-28 三次全灭同一死法）——改双选或换场"})
    if slip.multiplier > WARN_MULTIPLIER:
        verdicts.append({"code": "V3", "level": "warn",
                         "text": f"倍数 {slip.multiplier}×：倍投只警告（26121 ×50 中过一次）"})
    if slip.channel == "jczq" and slip.stake_yuan > cap_day * WARN_STAKE_SHARE:
        verdicts.append({"code": "V3", "level": "warn",
                         "text": f"单票 ¥{slip.stake_yuan:,} > 日帽 ¥{cap_day} 的一半"})
    vetoed = any(v["level"] == "veto" for v in verdicts)
    mark = {"veto": "⛔", "warn": "⚠️", "info": "ℹ️"}
    lines = [f"{mark[v['level']]}{v['code']} {v['text']}" for v in verdicts]
    verdict = "**否决**（改票后再审）" if vetoed else "可出（人定，机器只否决已知坏结构）"
    lines.append("审票结论：" + verdict)
    return {"ratio": ratio, "verdicts": verdicts, "vetoed": vetoed, "lines": lines}
