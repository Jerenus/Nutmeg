# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""平局信号回测（2026-11-06，Jun：今天各场平局面深度分析后排序）。

问题：除了收盘价给的平局 P，还有哪些赛前可见的量能预测平局？度量＝平局残差（实开−收盘平局 P）。
外部样本 football-data 主表 + 瑞超；比赛日整簇自助。前八季开发、后三季验证（1516–2223 / 2324–2526+2627），
只有两段同号且后段区间不含 0 才算有信息。信号（全部只用本场之前的同季数据，两队各 ≥6 场）：
  S1 两队本季平局率均值  S2 两队场均总进球均值（低＝小球）  S3 大小球收盘隐含 P(<2.5)
  S4 主客接近度 1−|p3−p0|  S5 联赛本季此前平局率
用法：python experiments/prescreen/2026-11-06-draw-signals.py <12季根目录> <SWE.csv>
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


def num(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def rd(ds):
    fmt = "%d/%m/%Y" if len(ds.split("/")[-1]) == 4 else "%d/%m/%y"
    return datetime.strptime(ds, fmt).date()


def load(root, swe):
    G = []
    for p in sorted(Path(root).glob("*/*.csv")):
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                if not (r.get("Date") or "").strip() or r.get("FTR") not in "HDA" or not r.get("FTR"):
                    continue
                o = next(([num(r.get(a + s)) for s in "HDA"] for a in ("PSC", "AvgC", "B365C")
                          if all(num(r.get(a + s)) for s in "HDA")), None)
                ou = next(((num(r.get(a + ">2.5")), num(r.get(a + "<2.5"))) for a in ("PC", "AvgC")
                           if num(r.get(a + ">2.5")) and num(r.get(a + "<2.5"))), None)
                try:
                    G.append(dict(s=p.parent.name, l=p.stem, d=rd(r["Date"]), h=r["HomeTeam"], a=r["AwayTeam"],
                                  hg=int(float(r["FTHG"])), ag=int(float(r["FTAG"])), o=o, ou=ou))
                except (ValueError, KeyError, TypeError):
                    pass
    with open(swe, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("Res") not in ("H", "D", "A"):
                continue
            o = next(([num(r.get(a + s)) for s in "HDA"] for a in ("PSC", "AvgC", "B365C")
                      if all(num(r.get(a + s)) for s in "HDA")), None)
            yy = str(r["Season"])[-2:]
            ss = f"{int(yy) - 1:02d}{yy}"
            G.append(dict(s=ss, l="SWE", d=rd(r["Date"]), h=r["Home"], a=r["Away"], hg=int(float(r["HG"])),
                          ag=int(float(r["AG"])), o=o, ou=None))
    G.sort(key=lambda g: g["d"])
    return G


def prior_table(G):
    """(联赛, 季) → 该联赛此前所有完整赛季的 平局率、场均总进球；首季无基准。"""
    agg = defaultdict(lambda: [0, 0, 0])
    for g in G:
        a = agg[(g["l"], g["s"])]
        a[0] += 1
        a[1] += g["hg"] == g["ag"]
        a[2] += g["hg"] + g["ag"]
    out = {}
    for (l, s) in agg:
        prev = [v for (l2, s2), v in agg.items() if l2 == l and s2 < s]
        n = sum(v[0] for v in prev)
        if n >= 200:
            out[(l, s)] = (sum(v[1] for v in prev) / n, sum(v[2] for v in prev) / n)
    return out


def features(G):
    T = defaultdict(lambda: [0, 0, 0])
    L = defaultdict(lambda: [0, 0])
    out = []
    hist = defaultdict(lambda: [0, 0, 0])   # (联赛) → 已完赛各季累计 场/平/进球
    done = set()
    for g in G:
        lk = (g["s"], g["l"])
        th, ta = T[(g["s"], g["l"], g["h"])], T[(g["s"], g["l"], g["a"])]
        lg = L[(g["s"], g["l"])]
        if g["o"] and th[0] >= 6 and ta[0] >= 6 and lg[0] >= 40 and g["d"].isoformat() < "2026-10-23":
            inv = [1 / x for x in g["o"]]
            s = sum(inv)
            p3, p1, p0 = (x / s for x in inv)
            pu = None
            if g["ou"]:
                a, b = 1 / g["ou"][0], 1 / g["ou"][1]
                pu = b / (a + b)
            ph = PRIOR.get((g["l"], g["s"]))
            if ph is None:
                continue
            out.append(dict(s=g["s"], l=g["l"], d=g["d"], draw=float(g["hg"] == g["ag"]), p1=p1, p3=p3, p0=p0,
                            base_S1=ph[0], base_S5=ph[0], base_S2=ph[1],
                            S1=(th[1] / th[0] + ta[1] / ta[0]) / 2, S2=(th[2] / th[0] + ta[2] / ta[0]) / 2,
                            S3=pu, S4=1 - abs(p3 - p0), S5=lg[1] / lg[0], tot=g["hg"] + g["ag"]))
        d = g["hg"] == g["ag"]
        for t in (th, ta):
            t[0] += 1
            t[1] += d
            t[2] += g["hg"] + g["ag"]
        lg[0] += 1
        lg[1] += d
    return out


def tercile_gap(rows, key, B=2000):
    """高三分位减低三分位的平局残差（分联赛季内分位，去掉联赛水平差）。"""
    rows = [r for r in rows if r[key] is not None]
    # 不按赛季内分位切：同季分位用到赛季后段，累计量会被机械地算成「均值回归」（S1/S5 首跑的 −8pp 即此假象）。
    # 改为减去该联赛此前各季的平局率/进球（赛前可见的固定基准）后全池分位。
    v = np.array([r[key] - r.get("base_" + key, 0) for r in rows])
    res = np.array([r["draw"] - r["p1"] for r in rows])
    rank = (v.argsort().argsort() + .5) / len(v)
    hi, lo = rank > 2 / 3, rank < 1 / 3
    days = sorted({r["d"] for r in rows})
    di = {d: i for i, d in enumerate(days)}
    dd = np.array([di[r["d"]] for r in rows])
    D = len(days)
    pt = res[hi].mean() - res[lo].mean()
    rng = np.random.default_rng(3)
    bs = []
    for _ in range(B):
        w = np.bincount(rng.integers(0, D, D), minlength=D)[dd].astype(float)
        bs.append((w[hi] * res[hi]).sum() / w[hi].sum() - (w[lo] * res[lo]).sum() / w[lo].sum())
    return len(rows), res[hi].mean(), res[lo].mean(), pt, np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def main():
    global PRIOR
    G = load(sys.argv[1], sys.argv[2])
    PRIOR = prior_table(G)
    F = features(G)
    dev = [r for r in F if r["s"] <= "2223"]
    val = [r for r in F if r["s"] > "2223"]
    print("开发", len(dev), "验证", len(val))
    res = {}
    for name, rows in (("开发", dev), ("验证", val)):
        print(f"\n== {name}（高三分位 − 低三分位，平局残差，pp）")
        for k, lab in (("S1", "两队本季平局率"), ("S2", "两队场均总进球"), ("S3", "收盘隐含小球P"), ("S4", "主客接近度"), ("S5", "联赛本季平局率")):
            n, h, l, g, a, b = tercile_gap(rows, k)
            print(f"{lab:<10} n={n:>6} 高 {h*100:+.2f} 低 {l*100:+.2f} 差 {g*100:+.2f} [{a*100:+.2f},{b*100:+.2f}]")
            res[f"{name}_{k}"] = [n, h, l, g, a, b]
    print("\n== 收盘平局 P 校准（全样本）")
    allr = np.array([[r["p1"], r["draw"]] for r in F])
    for a, b in ((0, .2), (.2, .24), (.24, .26), (.26, .28), (.28, .30), (.30, .33), (.33, 1)):
        m = (allr[:, 0] >= a) & (allr[:, 0] < b)
        print(f"{a:.2f}-{b:.2f} n={m.sum():>6} 市场 {allr[m,0].mean()*100:.1f}% 实开 {allr[m,1].mean()*100:.1f}%")
    json.dump(res, open("experiments/prescreen/2026-11-06-draw-signals.json", "w"), indent=0)


if __name__ == "__main__":
    main()
