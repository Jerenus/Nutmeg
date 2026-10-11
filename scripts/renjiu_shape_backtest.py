"""任九票形回测（2026-10-12）：固定 (单,双,包) 形 + 按四档自适应策略，在市场口径下看 102 期的
命中 / 奖金 / ROI。只测票形的底色（没有判断溢价）；奖金模型 b≈1 ⇒ 任何形的期望都≈返奖率，
所以读表只看「哪种装置系统性低于模型」，不拿它选形追 ROI。
证据：docs/superpowers/evidence/2026-10-12-renjiu-shape-backtest.md。

    uv run python scripts/renjiu_shape_backtest.py [--data-dir .nutmeg-data]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from itertools import combinations
from pathlib import Path

from nutmeg.decision.crowd_model import load_observations

ALL = ("3", "1", "0")
FIXED = [(9, 0, 0), (6, 3, 0), (5, 4, 0), (4, 5, 0), (3, 6, 0), (2, 7, 0), (1, 8, 0),
         (5, 3, 1), (4, 4, 1), (3, 5, 1), (2, 6, 1), (5, 2, 2), (4, 3, 2), (3, 4, 2), (2, 5, 2),
         (4, 2, 3), (3, 3, 3)]
BOOTS = 2000


def mp(m) -> float:
    return max(m.p.values())


def order(m) -> list[str]:
    return sorted(m.p, key=lambda k: -m.p[k])


def notes(counts: list[int]) -> int:
    return sum(math.prod(counts[i] for i in sub) for sub in combinations(range(len(counts)), 9))


def p_win(cover: list[float]) -> float:
    """P(至少 9 场被盖住)。"""
    dp = [1.0] + [0.0] * len(cover)
    for c in cover:
        for k in range(len(cover), 0, -1):
            dp[k] = dp[k] * (1 - c) + dp[k - 1] * c
        dp[0] *= 1 - c
    return sum(dp[9:])


def evaluate(o, legs, pm: dict) -> tuple[float, float, float, bool, float]:
    """→ (成本, 派奖, 奖金模型期望派奖, 是否命中, P(中))。模型期望按 14 场全板：
    E[prize·hit] = e^{a+sd²/2}·Π_{票内} Σ_{A_i} q^{1−b}·Π_{票外} Σ q^{1−b}。"""
    a, b, sd = pm["a"], pm["b"], pm["resid_sd"]
    counts = [len(fs) for _, fs in legs]
    hit = [(o.results[m.no - 1] == "*") or (o.results[m.no - 1] in fs) for m, fs in legs]
    cost = 2 * notes(counts)
    won = sum(1 for sub in combinations(range(len(legs)), 9) if all(hit[i] for i in sub))
    inside = {m.no for m, _ in legs}
    outside = math.prod(sum(q ** (1 - b) for q in m.p.values()) for m in o.board if m.no not in inside)
    e = 0.0
    for sub in combinations(range(len(legs)), 9):
        rest = [i for i in range(len(legs)) if i not in sub]
        e += math.exp(a + sd ** 2 / 2) * outside \
            * math.prod(sum(legs[i][0].p[f] ** (1 - b) for f in legs[i][1]) for i in sub) \
            * math.prod(sum(q ** (1 - b) for q in legs[i][0].p.values()) for i in rest)
    pw = p_win([sum(m.p[f] for f in fs) for m, fs in legs])
    return cost, won * math.exp(o.log_prize), e, won > 0, pw


def fixed(board, shape, dbl="top2"):
    """单=市场最大面概率最高的 s 场，双=其后 d 场（前两面 / 模态+平），包=再后 f 场。"""
    s, d, f = shape
    legs = []
    for i, m in enumerate(sorted(board, key=lambda m: -mp(m))[:s + d + f]):
        o = order(m)
        if i < s:
            fs = (o[0],)
        elif i < s + d:
            fs = (o[0], o[1]) if dbl == "top2" or o[0] == "1" else (o[0], "1")
        else:
            fs = ALL
        legs.append((m, fs))
    return legs


def adaptive(board, x_single, d_floor, coin, cap_notes=200):
    """单=最大面 ≥x_single；双=[d_floor, x_single)；硬币按 coin∈{double, full, true3} 补；
    超帽时按 p1/(p1+p2) 最高的双改单（再把包改双）。"""
    legs = []
    for m in sorted(board, key=lambda m: -mp(m))[:9]:
        o = order(m)
        if mp(m) >= x_single:
            fs = [o[0]]
        elif mp(m) >= d_floor or coin == "double" or (coin == "true3" and min(m.p.values()) < .25):
            fs = [o[0], o[1]]
        else:
            fs = list(ALL)
        legs.append([m, fs])

    def ratio(m):
        o = order(m)
        return m.p[o[0]] / (m.p[o[0]] + m.p[o[1]])

    while notes([len(fs) for _, fs in legs]) > cap_notes:
        cand = [i for i, (_, fs) in enumerate(legs) if len(fs) == 2]
        if cand:
            i = max(cand, key=lambda i: ratio(legs[i][0]))
            legs[i][1] = [order(legs[i][0])[0]]
            continue
        i = max((i for i, (_, fs) in enumerate(legs) if len(fs) == 3), key=lambda i: mp(legs[i][0]))
        legs[i][1] = order(legs[i][0])[:2]
    return [(m, tuple(fs)) for m, fs in legs]


def summarize(name, recs) -> dict:
    cost = sum(r[0] for r in recs)
    pay = sum(r[1] for r in recs)
    e = sum(r[2] for r in recs)
    boots = []
    for _ in range(BOOTS):
        smp = [random.choice(recs) for _ in recs]
        c = sum(r[0] for r in smp)
        boots.append((sum(r[1] for r in smp) - c) / c)
    boots.sort()
    prizes = sorted(r[1] for r in recs if r[3])
    top = prizes[-1] if prizes else 0
    return dict(name=name, n=len(recs), cost_mean=cost / len(recs), hits=len(prizes),
                roi=(pay - cost) / cost, ci=(boots[int(BOOTS * .025)], boots[int(BOOTS * .975)]),
                model_roi=(e - cost) / cost, roi_ex_top=(pay - top - cost) / cost,
                pw=statistics.mean(r[4] for r in recs), med_prize=statistics.median(prizes) if prizes else 0,
                top=top)


HDR = (f"{'策略':<28}{'均价':>7}{'中/期':>9}{'命中':>5}{'P(中)':>7}{'ROI':>8} {'CI95':>14}"
       f"{'模型ROI':>8}{'去最大':>9}{'中位奖':>9}{'最大奖':>9}")


def fmt(r: dict) -> str:
    return (f"{r['name']:<28}{r['cost_mean']:>7.0f}{r['hits']:>4}/{r['n']:<4}{r['hits'] / r['n']:>5.0%}"
            f"{r['pw']:>7.1%}{r['roi']:>8.0%} [{r['ci'][0]:>5.0%},{r['ci'][1]:>5.0%}]{r['model_roi']:>8.0%}"
            f"{r['roi_ex_top']:>9.0%}{r['med_prize']:>9.0f}{r['top']:>9.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".nutmeg-data")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    random.seed(args.seed)
    zdir = Path(args.data_dir) / "zucai"
    pm = json.load(open(zdir / "prize-model.json"))["channels"]["renjiu"]
    obs = load_observations(zdir)
    print(f"issues={len(obs)} {obs[0].issue}-{obs[-1].issue}; prize-model a={pm['a']} b={pm['b']} sd={pm['resid_sd']}")

    def cnt(o, lo, hi=1.01):
        return sum(1 for m in o.board if lo <= mp(m) < hi)
    for label, lo, hi in (("≥80", .80, 1.01), ("≥65", .65, 1.01), ("≥57", .57, 1.01), ("<45(硬币)", 0, .45)):
        print(f"每期场数分布 {label}:", sorted(Counter(cnt(o, lo, hi) for o in obs).items()))
    print("第 9 高场的最大面概率中位:",
          round(statistics.median(sorted((mp(m) for m in o.board), reverse=True)[8] for o in obs), 3))

    print("\n== 固定形（9 场；双=市场前两面 / 双=模态+平）==\n" + HDR)
    for shape in FIXED:
        for dbl in ("top2", "draw"):
            if shape[1] == 0 and dbl == "draw":
                continue
            print(fmt(summarize(f"{shape} 双={dbl}", [evaluate(o, fixed(o.board, shape, dbl), pm) for o in obs])))

    print("\n== 自适应（单≥X / 双∈[45%,X) / 硬币→双|真三面包|包 / 帽 200 注）==\n" + HDR)
    for x in (.70, .75, .80):
        for coin in ("double", "true3", "full"):
            print(fmt(summarize(f"单≥{x:.0%} 硬币→{coin}", [evaluate(o, adaptive(o.board, x, .45, coin), pm) for o in obs])))
    print("\n== 自适应 单≥X / 双≥57（中间档也包）==\n" + HDR)
    for x in (.70, .80):
        print(fmt(summarize(f"单≥{x:.0%} 双≥57 硬币→包", [evaluate(o, adaptive(o.board, x, .57, "full"), pm) for o in obs])))

    print("\n== 策略落成的格式频率（单,双,包）==")
    for x, coin in ((.75, "double"), (.75, "true3"), (.80, "double"), (.70, "double")):
        c = Counter(tuple(Counter(len(fs) for _, fs in adaptive(o.board, x, .45, coin))[k] for k in (1, 2, 3)) for o in obs)
        print(f"单≥{x:.0%} 硬币→{coin}:", ", ".join(
            f"{s}¥{2 * notes([1] * s[0] + [2] * s[1] + [3] * s[2])}×{n}" for s, n in c.most_common()))


if __name__ == "__main__":
    main()
