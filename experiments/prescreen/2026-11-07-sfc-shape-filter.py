# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""胜负彩一赔个数过滤回测（2026-11-07，接 sfc-odds-rank-shape）。

问题：帽内 N 注，目标从「最大中奖概率」换成「中了值钱」时，P、高奖 P、模型回报率、实际回报各多少；奖池滚存期有没有不同。
策略：max-P 单式（前 N 元组）、一赔≤9 / ≤8 过滤后的 max-P 单式、笛卡尔复式、按一等奖模型 EV 取前 N。
全国注数模型：log λ(t) = α + β·S(t) + log(销量/2)，泊松回归，含空奖期。一等池＝44.8% 销量 + 期初滚存，单注封顶 500 万；二等池 19.2%。
α β 在全样本拟合，属样本内，回报率只作量级。未事前登记，只展示。
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from nutmeg.decision.crowd_model import load_observations
from nutmeg.gym.prizes import load_prizes

spec = importlib.util.spec_from_file_location("sh", "experiments/prescreen/2026-11-07-sfc-odds-rank-shape.py")
sh = importlib.util.module_from_spec(spec); sys.modules["sh"] = sh; spec.loader.exec_module(sh)
Z = Path(".nutmeg-data/zucai")
CAP = 5e6
fit = json.load(open("experiments/prescreen/2026-11-07-sfc-fit.json"))
A1, B1 = fit["b1"]
A2, B2 = fit["b2"]
pool = json.load(open("experiments/prescreen/2026-11-07-sfc-pool.json"))
ks = sorted(pool)
prev = {b: pool[a]["after"] for a, b in zip(ks[:-1], ks[1:])}
GRID = np.exp(np.linspace(-14, 11, 260))


def efirst_table(F):
    """E[min(封顶, F/(1+W))]，W~泊松(λ)，在 λ 网格上。"""
    out = []
    for lam in GRID:
        if lam > 400:
            out.append(min(CAP, F / (1 + lam)))
            continue
        w = np.arange(0, int(lam + 12 * math.sqrt(lam + 1) + 20))
        logpm = w * math.log(lam) - lam - np.cumsum(np.r_[0, np.log(np.maximum(w[1:], 1))])
        out.append(float((np.exp(logpm) * np.minimum(CAP, F / (1 + w))).sum()))
    return np.array(out)


def digits(idx):
    d = np.zeros((len(idx), 14), dtype=np.int8)
    x = idx.copy()
    for i in range(13, -1, -1):
        d[:, i] = x % 3
        x //= 3
    return d


def main():
    prizes = load_prizes(Z)
    obs = [o for o in load_observations(Z) if "*" not in o.results]
    Ns = (200, 400)
    names = ("maxP", "一赔≤9", "一赔≤8", "EV一等")
    res = {(k, n): [] for k in names for n in Ns}
    for o in obs:
        P, order = sh.sorted_probs(o.board)
        lp = np.log(P)
        r = [order[i].index(o.results[i]) for i in range(14)]
        pr = prizes[o.issue]
        sale = pr.get("sale_amount_sfc") or 0
        roll = prev.get(o.issue) or 0.0
        F, G = .448 * sale + roll, .192 * sale
        tab = efirst_table(F)
        arr, c1 = np.zeros(1), np.zeros(1, dtype=np.int8)
        for row in lp:
            arr = np.add.outer(arr, row).ravel()
            c1 = np.add.outer(c1, np.array([1, 0, 0], dtype=np.int8)).ravel()
        lam = np.exp(A1 + B1 * (-arr) + math.log(sale / 2))
        e1 = np.interp(np.log(lam), np.log(GRID), tab)
        ev1 = np.exp(arr) * e1 / 2
        # 实际赛果
        idx_a = 0
        for i in range(14):
            idx_a = idx_a * 3 + r[i]
        fa, sa = (pr.get("sfc_first") or {}).get("stake_amount") or 0, (pr.get("sfc_second") or {}).get("stake_amount") or 0
        pw3 = 3 ** np.arange(13, -1, -1)
        nei = [idx_a + (k - r[i]) * pw3[i] for i in range(14) for k in range(3) if k != r[i]]
        for n in Ns:
            for name in names:
                if name == "maxP":
                    score, mask = arr, None
                elif name == "EV一等":
                    score, mask = ev1, None
                else:
                    score, mask = arr, c1 <= (9 if name.endswith("9") else 8)
                s = score if mask is None else np.where(mask, score, -np.inf)
                sel = np.argpartition(-s, n - 1)[:n]
                sel = sel[np.isfinite(s[sel])]
                d = digits(sel)
                ps = np.exp(arr[sel])
                # 二等模型：逐张票 28 个邻居
                base = lp[np.arange(14), d]
                ev2 = 0.0
                sumlp = base.sum(1)
                for i in range(14):
                    for dk in (1, 2):
                        k = (d[:, i] + dk) % 3
                        ly = sumlp - base[:, i] + lp[i, k]
                        lam2 = np.exp(A2 + B2 * (-ly) + math.log(sale / 2))
                        ev2 += float((np.exp(ly) * G / (1 + lam2)).sum())
                ev = float((ps * e1[sel]).sum()) + ev2
                hi = float(ps[e1[sel] >= 5e5].sum())
                S_ = set(sel.tolist())
                hit = int(idx_a in S_)
                sec = sum(1 for x in nei if int(x) in S_)
                res[(name, n)].append(dict(issue=o.issue, P=float(ps.sum()), hi=hi, ev=ev / (2 * len(sel)), hit=hit, sec=sec,
                                           pay=hit * fa + sec * sa, cost=2 * len(sel), roll=roll / sale, c1med=float(np.median(c1[sel]))))
    json.dump({f"{k}|{n}": v for (k, n), v in res.items()}, open("experiments/prescreen/2026-11-07-sfc-filter.json", "w"), ensure_ascii=False)
    rng = np.random.default_rng(9)
    for n in Ns:
        print(f"\n== {n} 注 ¥{2*n}")
        for name in names:
            v = res[(name, n)]
            pay = np.array([x["pay"] for x in v]); cost = np.array([x["cost"] for x in v], float)
            bs = []
            for _ in range(4000):
                i = rng.integers(0, len(v), len(v))
                bs.append(pay[i].sum() / cost[i].sum())
            ev = np.array([x["ev"] for x in v]); ro = np.array([x["roll"] for x in v])
            print(f"{name:<6} 均P {np.mean([x['P'] for x in v])*100:.3f}% 高奖P {np.mean([x['hi'] for x in v])*100:.3f}% 模型回报 {ev.mean():.2f} 滚存≥20% {ev[ro>=.2].mean():.2f} 无滚存 {ev[ro<.05].mean():.2f} | 实中 {sum(x['hit'] for x in v)} 二等 {sum(x['sec'] for x in v)} 派 {pay.sum():,.0f} 回报 {pay.sum()/cost.sum():.2f} [{np.percentile(bs,2.5):.2f},{np.percentile(bs,97.5):.2f}] 票面一赔中位 {np.mean([x['c1med'] for x in v]):.1f}")


if __name__ == "__main__":
    main()
