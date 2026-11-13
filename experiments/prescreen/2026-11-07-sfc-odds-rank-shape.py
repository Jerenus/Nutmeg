# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""胜负彩一二三赔分布预筛（2026-11-07，Jun：500 赛果表左下角「一赔=7 二赔=3 三赔=4」，能否开新分析线）。

问题一：一二三赔个数是否稳定，能否预测（对照逐场价格算出的分布）。
问题二：票形上限——帽内笛卡尔复式 vs 任何缩水过滤的上界（前 N 个最可能的 14 元组）。
问题三：官方奖金结构——一等奖 45% 销量 + 滚存、单注封顶 500 万，二等奖 19.2% 销量；每注 ¥2。
一赔＝zgzcw europeSp 去水后 P 最大的面。样本＝官方赛果 + 板面齐全的期，有作废场的期只进问题一之外的统计时剔除。
探索性预筛，未事前登记，只展示。用法：uv run python experiments/prescreen/2026-11-07-sfc-odds-rank-shape.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from nutmeg.decision.crowd_model import load_observations
from nutmeg.gym.prizes import load_prizes

Z = Path(".nutmeg-data/zucai")
CAPS = (32, 64, 128, 200, 256, 400)     # 注数；¥400＝200 注，¥800＝400 注
FACES = ("3", "1", "0")


def sorted_probs(board):
    """→ 14×3 概率（按 P 降序）与每场面的顺序。"""
    order = [sorted(FACES, key=lambda f: -m.p[f]) for m in board]
    return np.array([[m.p[f] for f in o] for m, o in zip(board, order)]), order


def pb(ps):
    pmf = np.zeros(len(ps) + 1)
    pmf[0] = 1
    for p in ps:
        pmf[1:] = pmf[1:] * (1 - p) + pmf[:-1] * p
        pmf[0] *= 1 - p
    return pmf


def best_cartesian(P, n):
    """帽内最大 P 的复式：每场选 前1/前2/全包，注数 2^d·3^t ≤ n；DP。→ (P, 每场选几面)。"""
    state = {(0, 0): (0.0, [])}
    gains = np.log(np.c_[P[:, 0], P[:, :2].sum(1), np.ones(len(P))])
    for g in gains:
        nxt = {}
        for (d, t), (v, path) in state.items():
            for k, nd, nt in ((1, d, t), (2, d + 1, t), (3, d, t + 1)):
                if 2 ** nd * 3 ** nt > n:
                    continue
                val = v + g[k - 1]
                if (nd, nt) not in nxt or val > nxt[(nd, nt)][0]:
                    nxt[(nd, nt)] = (val, path + [k])
        state = nxt
    v, path = max(state.values(), key=lambda x: x[0])
    return math.exp(v), path


def main():
    prizes = load_prizes(Z)
    obs = load_observations(Z)
    print("期数", len(obs), obs[0].issue, obs[-1].issue)
    rows = []
    for o in obs:
        P, order = sorted_probs(o.board)
        if "*" in o.results:
            r = None
        else:
            r = [order[i].index(o.results[i]) for i in range(14)]
        rows.append(dict(o=o, P=P, order=order, r=r))
    clean = [x for x in rows if x["r"] is not None]
    print("无作废", len(clean))
    C = np.array([[x["r"].count(k) for k in range(3)] for x in clean])
    E = np.array([x["P"].sum(0) for x in clean])
    print("实开均值 一/二/三", C.mean(0).round(2), "价格期望", E.mean(0).round(2))
    print("一赔个数分布", sorted(Counter(C[:, 0].tolist()).items()))
    print("二赔个数分布", sorted(Counter(C[:, 1].tolist()).items()))
    print("三赔个数分布", sorted(Counter(C[:, 2].tolist()).items()))
    shapes = Counter(tuple(c) for c in C.tolist())
    print("最常见形状", shapes.most_common(8), "不同形状", len(shapes))
    print("7/3/4 期", [x["o"].issue for x, c in zip(clean, C) if tuple(c) == (7, 3, 4)])
    print("近 8 期形状", [(x["o"].issue, tuple(c)) for x, c in zip(clean[-8:], C[-8:].tolist())])
    # 分布宽度：实际方差 vs 泊松二项方差
    v = np.array([(x["P"][:, 0] * (1 - x["P"][:, 0])).sum() for x in clean])
    res = C[:, 0] - E[:, 0]
    print("一赔 残差均值 %.2f sd %.2f；价格给的 sd %.2f；z 方差比 %.2f" % (res.mean(), res.std(ddof=1), math.sqrt(v.mean()), (res ** 2 / v).mean()))
    # 可预测性
    y = C[:, 0].astype(float)
    print("corr(期望,实开) %.3f 斜率 %.2f" % (np.corrcoef(E[:, 0], y)[0, 1], np.polyfit(E[:, 0], y, 1)[0]))
    print("lag1 自相关 实开 %.3f  残差 %.3f" % (np.corrcoef(y[:-1], y[1:])[0, 1], np.corrcoef(res[:-1], res[1:])[0, 1]))
    mse_hist = np.mean([(y[i] - y[:i].mean()) ** 2 for i in range(20, len(y))])
    mse_lag = np.mean([(y[i] - y[i - 1]) ** 2 for i in range(20, len(y))])
    mse_px = np.mean([(y[i] - E[i, 0]) ** 2 for i in range(20, len(y))])
    print("一赔个数预测 MSE：历史均值 %.2f 上期 %.2f 本期价格 %.2f" % (mse_hist, mse_lag, mse_px))
    # 票形
    print("\n== 票形（前 N 元组＝任何缩水的上界）")
    res_rows = []
    for x in clean:
        P = x["P"]
        arr = np.zeros(1)
        lp = np.log(P)
        for row in lp:
            arr = np.add.outer(arr, row).ravel()
        o = x["o"]
        pr = prizes[o.issue]
        first = (pr.get("sfc_first") or {})
        second = (pr.get("sfc_second") or {})
        la = sum(lp[i, x["r"][i]] for i in range(14))
        nei = []
        for i in range(14):
            for k in range(3):
                if k != x["r"][i]:
                    nei.append(la - lp[i, x["r"][i]] + lp[i, k])
        rec = dict(issue=o.issue, S=-la, first=first.get("stake_amount") or 0, firstn=first.get("stake_count") or 0,
                   second=second.get("stake_amount") or 0, secondn=second.get("stake_count") or 0,
                   sale=pr.get("sale_amount_sfc") or 0, c1=x["r"].count(0))
        rec["p1"] = float(np.exp(lp[:, 0].sum()))
        s = np.sort(arr)[::-1][:max(CAPS)]
        cum = np.cumsum(np.exp(s))
        for n in CAPS:
            pc, path = best_cartesian(P, n)
            ways = 1
            for k in path:
                ways *= k
            wrong = [i for i in range(14) if x["r"][i] >= path[i]]
            sec = path[wrong[0]] if len(wrong) == 1 else 0    # 只错一场：错场选了几面就有几注中 13
            first_hit = 1 if len(wrong) == 0 else 0
            if first_hit:
                sec = sum(k - 1 for k in path)                # 全中：每场换一个已选面各得一注 13
            th = s[n - 1]
            rec[f"cart{n}"] = (pc, ways, first_hit, sec)
            hit_top = int(la >= th)
            sec_top = sum(1 for v_ in nei if v_ >= th)
            rec[f"top{n}"] = (float(cum[n - 1]), n, hit_top, sec_top)
        res_rows.append(rec)
    json.dump(res_rows, open("experiments/prescreen/2026-11-07-sfc-rows.json", "w"), ensure_ascii=False)
    n = len(res_rows)
    print("全一赔 1 注 均 P %.4f%%" % (np.mean([r["p1"] for r in res_rows]) * 100))
    for c in CAPS:
        for kind in ("cart", "top"):
            R = [r[f"{kind}{c}"] for r in res_rows]
            cost = sum(x[1] for x in R) * 2
            pay = sum(x[2] * r["first"] + x[3] * r["second"] for x, r in zip(R, res_rows))
            print(f"{kind}{c:<4} 均注 {np.mean([x[1] for x in R]):.0f} 均P {np.mean([x[0] for x in R])*100:.3f}% 预期中 {sum(x[0] for x in R):.2f} 实中一等 {sum(x[2] for x in R)} 二等注 {sum(x[3] for x in R):.0f} 成本 {cost} 派 {pay:,.0f} 回报率 {pay/cost:.2f}")


if __name__ == "__main__":
    main()
