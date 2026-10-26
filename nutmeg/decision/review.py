"""审票（2026-10-01 定位：机器＝风控官+账房+实验员，人＝下注者）。

人出方案，机器给三类意见：**否决**（有实证的坏结构）、**警告**、**数字**。否决只有两条，
都来自 403 天回放与复盘账：
- V1 期望回报率 < 0.5——"中了也亏"的帽内 max-P 形状（任九 −58%、竞彩 max-P −20%，CI 不含 0）；
- V2 与已购票共享裸单——假分散（26122 联死 73.8%、26133 ≈60%、09-28 五票同死 004）；
  2026-10-14 起**所有票同时排掉的 ≥30% 面**计为同类项（26138 2·0、26139 3·10/8·31、26140 6·3/8·0
  四期全灭都死在这里，§8a 第 4 条连续四期 ✗）。
V3 倍投/重注只警告（证据不够硬：26121 ×50 中过一次）。
V4 渠道不可购（2026-10-12 Jun：任九 >9 场的「容错」复式目前渠道不支持）——注数算法支持 >9 场，
但买不到的票不该过预审。

足彩的期望回报用**奖金模型**（`scripts/zucai_prize_model.py`，2026-10-01）：任九奖金与板面意外度
corr 0.95、log(prize)=a+b·S 且 b≈1——市场口径下任何票面形状的期望回报都≈返奖率，差别只在
「判断溢价」Π_i Σ_{A_i} q/p（判断概率 q 与市场 p 不同的面）。全局中位数口径会把热板票高估十倍
（帽内 max-P 42 期中 11 次，中时奖金中位 ¥215 vs 全局中位 ¥4,098）。
"""
from __future__ import annotations

import json
import math
import statistics
from itertools import combinations
from pathlib import Path

from nutmeg.decision.betslip import RENJIU_PICK, BetSlip, SlipLeg
from nutmeg.decision.faces import FACES
from nutmeg.decision.reconcile import normalize_selection

VETO_RATIO = 0.5
WARN_RATIO = 0.65
WARN_MULTIPLIER = 10
WARN_STAKE_SHARE = 0.5          # 单票 > 日帽一半
BOARD_MATCHES = 14
ZUCAI = ("renjiu", "shengfucai")
PACK_MIN_FACE = 0.25            # 包只给三面都 ≥25% 的硬币场（票形字典 2026-10-12）
BOLD_MODAL = 0.55               # 排掉 ≥55% 模态面＝博胆（§3a 第 3 条；26137–26147 n=5 全死）
_CN = {"home": "3", "draw": "1", "away": "0"}


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


def prize_model(data_dir: Path) -> dict[str, dict]:
    """→ {renjiu: {median, a, b, resid_sd, n}, shengfucai: {…}}。

    有 `zucai/prize-model.json`（`scripts/zucai_prize_model.py --write`）时带系数；
    没有就只有中位数，V1 退回中位数口径并在文案里标明。
    """
    medians = prize_medians(data_dir)
    out: dict[str, dict] = {ch: {"median": medians[ch]} for ch in ZUCAI}
    path = Path(data_dir) / "zucai" / "prize-model.json"
    try:
        channels = json.loads(path.read_text(encoding="utf-8")).get("channels") or {}
    except (OSError, ValueError):
        return out
    for ch, row in channels.items():
        if ch not in out or not all(k in row for k in ("a", "b", "resid_sd")):
            continue
        out[ch].update({"a": float(row["a"]), "b": float(row["b"]),
                        "resid_sd": float(row["resid_sd"]), "n": int(row.get("n") or 0)})
        if out[ch]["median"] is None and row.get("prize_median"):
            out[ch]["median"] = float(row["prize_median"])
    return out


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


def zucai_return(slip: BetSlip, *, model: dict[str, dict],
                 market: dict[str, dict] | None = None) -> dict | None:
    """足彩期望回报（奖金模型）。

    E[奖金·1{中}] = e^{a+sd²/2} · Π_i Σ_{ω∈A_i} q_i(ω)·p_i(ω)^{−b}：q = 判断概率（腿的 fair），
    p = 市场概率（`market[no]`，缺则取 q），未选的场 A_i = 三面（市场分布缺则按均匀 1/3）。
    → {ratio（判断口径）, ratio_market（q=p 时）, premium（二者之比）, basis: "model"}；
    没有系数 → {ratio: P(全对)×中位数/投入, basis: "median"}；缺数据 → None。
    """
    coeffs = model.get(slip.channel) or {}
    stake = slip.stake_yuan
    if not stake:
        return None
    if "a" not in coeffs:
        p = slip.hit_probability
        median = coeffs.get("median")
        if p is None or median is None:
            return None
        return {"ratio": round(p * median * slip.multiplier / stake, 3), "basis": "median"}
    a, b, sd = coeffs["a"], coeffs["b"], coeffs["resid_sd"]
    market = market or {}
    belief_term = market_term = 1.0
    covered: set[str] = set()
    for leg in slip.legs:
        if leg.market != "had" or not leg.fair:
            return None
        keys = list(dict.fromkeys(normalize_selection("had", s) for s in leg.selections))
        if any(k is None for k in keys):
            return None
        q, p = leg.fair, market.get(leg.key) or leg.fair
        covered.add(leg.key)
        belief_term *= sum(float(q[k]) * float(p[k]) ** (-b) for k in keys)
        market_term *= sum(float(p[k]) ** (1 - b) for k in keys)
    free = 1.0
    seen = 0
    for no, p in market.items():
        if no in covered or seen >= BOARD_MATCHES - len(covered):
            continue
        free *= sum(float(p[f]) ** (1 - b) for f in FACES)
        seen += 1
    free *= (3 ** b) ** max(0, BOARD_MATCHES - len(covered) - seen)
    base = math.exp(a + sd * sd / 2) * free * slip.multiplier / stake
    ratio, ratio_market = base * belief_term, base * market_term
    return {"ratio": round(ratio, 3), "ratio_market": round(ratio_market, 3),
            "premium": round(ratio / ratio_market, 3) if ratio_market else None,
            "basis": "model"}


def expected_return_ratio(slip: BetSlip, *, prize_model: dict[str, dict],
                          market: dict[str, dict] | None = None) -> float | None:
    """E[派奖]/投入。竞彩：每串 P(全中)×模态赔率连乘；足彩：奖金模型（见 `zucai_return`）。"""
    if slip.channel in ZUCAI:
        out = zucai_return(slip, model=prize_model, market=market)
        return None if out is None else out["ratio"]
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


def _v1_text(ratio: float, detail: dict | None) -> str:
    text = f"期望回报率 {ratio:.2f}"
    if detail and detail.get("basis") == "model":
        text += (f"（市场口径 {detail['ratio_market']:.2f} × 判断溢价 {detail['premium']:.2f}；"
                 "奖金模型）")
    elif detail and detail.get("basis") == "median":
        text += "（奖金中位数口径，热板会高估；跑 scripts/zucai_prize_model.py --write）"
    return text


def structure_notes(slip: BetSlip) -> list[dict]:
    """V5 结构警告（2026-10-23 26147 复盘，只展示不否决）：
    包放在第三面 <25% 的场（26136–26147 实票 18 处包里 7 处）；
    一张票博胆 >1（排掉 ≥55% 模态面的单/双，26137–26147 n=5 全死、期望死 3.2）。"""
    if slip.channel not in ZUCAI:
        return []
    packs, bold = [], []
    for leg in slip.legs:
        if leg.market != "had" or not leg.fair:
            continue
        keys = {normalize_selection("had", s) for s in leg.selections} - {None}
        probs = {f: float(leg.fair.get(f, 0.0)) for f in FACES}
        modal = max(probs, key=probs.get)
        if len(keys) == 3:
            low = min(probs, key=probs.get)
            if probs[low] < PACK_MIN_FACE:
                packs.append(f"{leg.key}（{_CN[low]} 只有 {probs[low] * 100:.0f}%）")
        elif modal not in keys and probs[modal] >= BOLD_MODAL:
            bold.append(f"{leg.key}排{_CN[modal]} {probs[modal] * 100:.0f}%")
    out = []
    if packs:
        out.append({"code": "V5", "level": "warn",
                    "text": "包放在非硬币场 " + "、".join(packs)
                            + "：3 倍注买一个 <25% 的面（票形字典：包只给三面 ≥25% 的场）"})
    if len(bold) > 1:
        out.append({"code": "V5", "level": "warn",
                    "text": f"博胆 {len(bold)} 条（" + "、".join(bold)
                            + "）：每票博胆 ≤1（§3a 第 3 条；26137–26147 n=5 全死）"})
    return out


def review(slip: BetSlip, diagnosis: dict, *, prize_model: dict[str, dict],
           cap_day: int = 400, market: dict[str, dict] | None = None) -> dict:
    """→ {ratio, detail, verdicts: [{code, level, text}], vetoed: bool, lines: [str]}。"""
    verdicts: list[dict] = []
    detail = zucai_return(slip, model=prize_model, market=market) \
        if slip.channel in ZUCAI else None
    ratio = (detail["ratio"] if detail else None) if slip.channel in ZUCAI \
        else expected_return_ratio(slip, prize_model=prize_model)
    if ratio is None:
        verdicts.append({"code": "V1", "level": "info",
                         "text": "期望回报率缺数据（腿缺 fair/赔率或无奖金缓存），V1 未检"})
    elif ratio < VETO_RATIO:
        verdicts.append({"code": "V1", "level": "veto",
                         "text": _v1_text(ratio, detail) + f" < {VETO_RATIO}：中了也亏的形状"
                                 "（403 天回放 max-P −20%、任九 −58%）"})
    elif ratio < WARN_RATIO:
        verdicts.append({"code": "V1", "level": "warn",
                         "text": _v1_text(ratio, detail)
                                 + "（抽水基准约 0.64–0.86），偏向大热堆叠"})
    else:
        verdicts.append({"code": "V1", "level": "info", "text": _v1_text(ratio, detail)})
    shared = diagnosis.get("shared_naked") or []
    if shared:
        keys = "、".join(f"{r['key']}{r['face']}" for r in shared)
        joint = (diagnosis.get("joint_death") or {}).get("p_all_die_at_least")
        # 同伴是谁要说对：整组预审的计划票 id 以 `plan:` 开头（2026-10-08 一律写成「已购票」）
        others = {sid for r in shared for sid in r.get("slip_ids") or []} - {slip.slip_id}
        planned = {sid for sid in others if str(sid).startswith("plan:")}
        peer = ("同组计划票" if others and planned == others
                else "已购票/同组计划票" if planned else "已购票")
        verdicts.append({"code": "V2", "level": "veto",
                         "text": f"与{peer}共享裸单 {len(shared)} 条（{keys}）"
                                 + (f"，联死 ≥{joint * 100:.0f}%" if joint is not None else "")
                                 + "：假分散（26122/26133/09-28 三次全灭同一死法）——改双选或换场"})
    excluded = diagnosis.get("shared_excluded") or []
    if excluded:
        # 2026-10-14：所有票同时排掉的 ≥30% 面＝共享裸单同类项
        # （§8a 第 4 条；26138–26140 四期同死因）
        others = {sid for r in excluded for sid in r.get("slip_ids") or []} - {slip.slip_id}
        peer = ("同组计划票" if others and all(str(s).startswith("plan:") for s in others)
                else "已购票")
        verdicts.append({"code": "V2", "level": "veto",
                         "text": f"与{peer}共享排除面 {len(excluded)} 处（"
                                 + "、".join(f"{r['key']}开{r['face']} {r['p_face'] * 100:.0f}%"
                                             for r in excluded)
                                 + "）：所有票同时排掉 ≥30% 的面＝假分散——"
                                   "任九里直接丢这场，或一张票盖上它"})
    if slip.multiplier > WARN_MULTIPLIER:
        verdicts.append({"code": "V3", "level": "warn",
                         "text": f"倍数 {slip.multiplier}×：倍投只警告（26121 ×50 中过一次）"})
    if slip.channel == "jczq" and slip.stake_yuan > cap_day * WARN_STAKE_SHARE:
        verdicts.append({"code": "V3", "level": "warn",
                         "text": f"单票 ¥{slip.stake_yuan:,} > 日帽 ¥{cap_day} 的一半"})
    n_matches = len(slip.faces or slip.legs)          # 足彩票面在 faces，腿只是渲染/结算用
    if slip.channel == "renjiu" and n_matches > RENJIU_PICK:
        verdicts.append({"code": "V4", "level": "veto",
                         "text": f"任九选了 {n_matches} 场：>9 场的容错复式渠道不可购"
                                 "（2026-10-12）——改成 9 场"})
    verdicts.extend(structure_notes(slip))
    vetoed = any(v["level"] == "veto" for v in verdicts)
    mark = {"veto": "⛔", "warn": "⚠️", "info": "ℹ️"}
    lines = [f"{mark[v['level']]}{v['code']} {v['text']}" for v in verdicts]
    verdict = "**否决**（改票后再审）" if vetoed else "可出（人定，机器只否决已知坏结构）"
    lines.append("审票结论：" + verdict)
    return {"ratio": ratio, "detail": detail, "verdicts": verdicts, "vetoed": vetoed,
            "lines": lines}


def review_record(verdict: dict) -> dict:
    """随票入账的审票结论（2026-10-06）：否决与否、期望回报率、触发的否决/警告码。"""
    return {"vetoed": bool(verdict.get("vetoed")), "ratio": verdict.get("ratio"),
            "codes": [v["code"] for v in verdict.get("verdicts") or []
                      if v.get("level") in ("veto", "warn")]}
