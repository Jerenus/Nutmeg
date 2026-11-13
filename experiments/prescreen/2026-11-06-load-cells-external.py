# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""赛程损耗格外部样本（football-data.co.uk 12 季 20 级联赛，2026-11-06）。

只有联赛场：杯赛/欧战看不见。所以休 r 是真实休息的上界——「双方密集」（两边联赛都 ≤3 天）是精确的；
「少休」的一方也是真的，只是被比较的一方可能其实更累，方向上偏保守。「只多赛」量不到，不测。
定义与 2026-11-06-load-cells-oos.py 冻结一致：热门＝收盘（Pinnacle，缺则市场均值，再缺 B365）比例去水后主客较大者；
排除 r>30（赛季首战、冬歇）；训练窗 ≥2026-10-23 剔除。比赛日整簇自助。
用法：python experiments/prescreen/2026-11-06-load-cells-external.py <csv根目录>
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

CELLS = ["热门少休", "对手少休", "双方密集", "其余"]
BANDS = [0, .45, .55, .65, .80, 1.01]
TOP = {"E0", "D1", "I1", "SP1", "F1", "N1", "P1", "B1", "T1", "G1", "SC0"}


def num(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def load(root: Path):
    games = []
    bad = Counter()
    for p in sorted(root.glob("*/*.csv")):
        season, div = p.parent.name, p.stem
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                ds = (r.get("Date") or "").strip()
                if not ds or r.get("FTR") not in ("H", "D", "A"):
                    continue
                fmt = "%d/%m/%Y" if len(ds.split("/")[-1]) == 4 else "%d/%m/%y"
                try:
                    d = datetime.strptime(ds, fmt).date()
                except ValueError:
                    bad["date"] += 1
                    continue
                odds, src = None, None
                for pre in ("PSC", "AvgC", "B365C"):
                    o = [num(r.get(pre + s)) for s in "HDA"]
                    if all(o):
                        odds, src = o, pre
                        break
                games.append(dict(season=season, div=div, date=d, h=r["HomeTeam"], a=r["AwayTeam"], ftr=r["FTR"],
                                  odds=odds, src=src))
    return games, bad


def enrich(games):
    by = defaultdict(list)
    for i, g in enumerate(games):
        by[(g["season"], g["div"], g["h"])].append(i)
        by[(g["season"], g["div"], g["a"])].append(i)
    last = {}
    for k, ids in by.items():
        ids.sort(key=lambda i: games[i]["date"])
        prev = None
        for i in ids:
            last[(k[2], i)] = prev
            prev = games[i]["date"]
    out = []
    for i, g in enumerate(games):
        if not g["odds"] or g["date"].isoformat() >= "2026-10-23":
            continue
        ph, pa = last.get((g["h"], i)), last.get((g["a"], i))
        if ph is None or pa is None:
            continue
        rh, ra = (g["date"] - ph).days, (g["date"] - pa).days
        if max(rh, ra) > 30 or min(rh, ra) < 2:
            continue
        inv = [1 / x for x in g["odds"]]
        s = sum(inv)
        p3, p1, p0 = (x / s for x in inv)
        fh = p3 >= p0
        pf, pd = (p3, p0) if fh else (p0, p3)
        rf, rd = (rh, ra) if fh else (ra, rh)
        res = ("胜" if g["ftr"] == ("H" if fh else "A") else "平" if g["ftr"] == "D" else "负")
        c = ("热门少休" if rf <= 4 and rd - rf >= 2 else "对手少休" if rd <= 4 and rf - rd >= 2
             else "双方密集" if max(rf, rd) <= 3 else "其余")
        out.append(dict(g, pf=pf, pd=pd, pdraw=p1, fh=fh, rf=rf, rd=rd, res=res, cell=c))
    return out


def table(rows, B=4000, seed=7):
    n = len(rows)
    win = np.array([x["res"] == "胜" for x in rows], float)
    drw = np.array([x["res"] == "平" for x in rows], float)
    pf = np.array([x["pf"] for x in rows])
    pdr = np.array([x["pdraw"] for x in rows])
    bd = np.digitize(pf, BANDS) - 1
    cl = np.array([CELLS.index(x["cell"]) for x in rows])
    days = sorted({x["date"] for x in rows})
    di = {d: i for i, d in enumerate(days)}
    dd = np.array([di[x["date"]] for x in rows])
    nb, nc = len(BANDS) - 1, len(CELLS)
    base = CELLS.index("其余")
    res, dres = win - pf, drw - pdr

    def stat(w, y):
        m = cl == base
        s = np.bincount(bd[m], w[m], nb)
        a = np.bincount(bd[m], w[m] * y[m], nb) / np.where(s > 0, s, 1)
        adj = y - a[bd]
        tot = np.bincount(cl, w, nc)
        tot = np.where(tot > 0, tot, 1)
        return np.bincount(cl, w * y, nc) / tot, np.bincount(cl, w * adj, nc) / tot

    r0, a0 = stat(np.ones(n), res)
    d0, da0 = stat(np.ones(n), dres)
    rng = np.random.default_rng(seed)
    D = len(days)
    bs, bsd = np.zeros((B, nc)), np.zeros((B, nc))
    for b in range(B):
        w = np.bincount(rng.integers(0, D, D), minlength=D)[dd].astype(float)
        bs[b] = stat(w, res)[1]
        bsd[b] = stat(w, dres)[1]
    out = {}
    for i, c in enumerate(CELLS):
        m = cl == i
        out[c] = dict(n=int(m.sum()), hit=float(win[m].mean()), mkt=float(pf[m].mean()), resid=float(r0[i]), adj=float(a0[i]),
                      ci=[float(np.percentile(bs[:, i], 2.5)), float(np.percentile(bs[:, i], 97.5))],
                      draw=float(drw[m].mean()), mkt_draw=float(pdr[m].mean()), adj_draw=float(da0[i]),
                      ci_draw=[float(np.percentile(bsd[:, i], 2.5)), float(np.percentile(bsd[:, i], 97.5))])
    return out


def show(title, t):
    print(f"\n== {title}")
    for c, s in t.items():
        print(f"{c:<6} n={s['n']:>6} 热门胜率 {s['hit']*100:5.1f}% 市场 {s['mkt']*100:5.1f}% 残差 {s['resid']*100:+5.1f} "
              f"调整 {s['adj']*100:+5.2f} [{s['ci'][0]*100:+.2f},{s['ci'][1]*100:+.2f}] | "
              f"平 {s['draw']*100:4.1f}%/{s['mkt_draw']*100:4.1f}% 调整 {s['adj_draw']*100:+5.2f} "
              f"[{s['ci_draw'][0]*100:+.2f},{s['ci_draw'][1]*100:+.2f}]")


def main():
    games, bad = load(Path(sys.argv[1]))
    E = enrich(games)
    print("全部场次", len(games), "带收盘价可分格", len(E), Counter(x["src"] for x in E), bad)
    print(sorted(Counter(x["season"] for x in E).items()))
    res = {}
    for name, f in (("全部", lambda x: True), ("顶级联赛", lambda x: x["div"] in TOP), ("次级及以下", lambda x: x["div"] not in TOP),
                    ("2015-19", lambda x: x["season"] < "1920"), ("2019-22 疫情前后", lambda x: "1920" <= x["season"] < "2223"),
                    ("2022-26", lambda x: x["season"] >= "2223"), ("热门≥50%", lambda x: x["pf"] >= .5), ("热门<50%", lambda x: x["pf"] < .5),
                    ("热门在客场", lambda x: not x["fh"])):
        t = table([x for x in E if f(x)])
        show(name, t)
        res[name] = t
    json.dump(res, open("experiments/prescreen/2026-11-06-load-cells-external.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
