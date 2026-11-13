# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""赛程损耗格样本外回测（2026-11-06，Jun：「尝试用更多的往期数据来进行回测」）。

假说来自 26153–26159 七期 98 场回看（26160 分析包 §1f），定义在跑本脚本前冻结，训练窗（≥2026-10-23）不进样本外。

冻结定义（对一场，开球日 D，热门＝收盘 sharp 去水 主/客 较大者）：
  休 r ＝ D − 上一场日期；场数 n ＝ 窗口 W 天内出场数（相邻 ≤1 天并为一场）；主口径 W=10，敏感性 W=7/14。
  少休·热门  ：r热 ≤4 且 r弱−r热 ≥2       多赛·热门：n热−n弱 ≥1
  少休·对手  ：r弱 ≤4 且 r热−r弱 ≥2       多赛·对手：n弱−n热 ≥1
  格：混合（两边都触发）/ 热门少休 / 热门只多赛 / 对手更累 / 双方密集（都未触发且 max(r)≤3）/ 双方轻（其余）。
冻结方向：H1 热门少休 不吃亏（≥0）；H2 热门只多赛 <0；H3 对手更累 >0；H4 双方密集 <0。
度量：热门胜残差＝实开−收盘 P；「调整残差」再减同价位带在「双方轻」格的平均残差，与训练窗口径（和双方轻比）一致。
区间：按比赛日整簇自助 2 万次。四条假说，通过线＝95% 区间不含 0 且方向对，再看 98.75%（Bonferroni）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from nutmeg.decision.team_load import build_index

CELLS = ["热门少休", "热门只多赛", "对手更累", "双方密集", "双方轻", "混合"]
BANDS = [(0, .45), (.45, .55), (.55, .65), (.65, .80), (.80, 1.01)]
TRAIN_FROM = "2026-10-23"
_FACE = {"胜": "3", "平": "1", "负": "0"}


def collapse(days):
    out = []
    for d in sorted(days):
        if out and (d - out[-1]).days <= 1:
            continue
        out.append(d)
    return out


def feat(days, on, w):
    before = [d for d in days if d <= on - timedelta(days=2)]
    if not before:
        return None
    return (on - before[-1]).days, sum(1 for d in before if d >= on - timedelta(days=w))


def cell(rf, nf, rd, nd):
    short_f, more_f = rf <= 4 and rd - rf >= 2, nf - nd >= 1
    short_d, more_d = rd <= 4 and rf - rd >= 2, nd - nf >= 1
    against, forr = short_f or more_f, short_d or more_d
    if against and forr:
        return "混合"
    if short_f:
        return "热门少休"
    if more_f:
        return "热门只多赛"
    if forr:
        return "对手更累"
    return "双方密集" if max(rf, rd) <= 3 else "双方轻"


def history_rows(data: Path):
    H = json.load(open(data / "jczq" / "jc-history.json"))
    rows = {}
    for day in sorted(H):
        p = data / "jczq" / "daily" / day / "closing_odds.json"
        cl = json.load(open(p)) if p.exists() else {}
        for code, m in H[day].items():
            o = ((m.get("sp") or {}).get("had") or {}).get("outcome")
            f = ((cl.get(code) or {}).get("sharp") or {}).get("fair_probability")
            if o in _FACE and f and m.get("home") and m.get("away"):
                rows[f"{day}|{code}"] = dict(date=day, home=m["home"], away=m["away"], face=_FACE[o],
                                             p3=f["home"], p1=f["draw"], p0=f["away"], src="jc", zucai=None)
    for line in open("experiments/decision-samples-v1.jsonl"):
        r = json.loads(line)
        pc = r.get("price_closing")
        if not (r.get("result") and pc and pc.get("fair")):
            continue
        z = r["zucai"]["issue"] if isinstance(r.get("zucai"), dict) else None
        k = r["key"]
        if k in rows:
            rows[k]["zucai"] = z
            continue
        f = pc["fair"]
        dup = f"{r['date']}|{r.get('jczq_code')}" in rows
        if dup:
            rows[f"{r['date']}|{r.get('jczq_code')}"]["zucai"] = z
            continue
        rows[k] = dict(date=r["date"], home=r["home"], away=r["away"], face=r["result"]["face"],
                       p3=f["3"], p1=f["1"], p0=f["0"], src="samples", zucai=z)
    return list(rows.values())


def enrich(rows, idx, w):
    cache = {}
    def days(name):
        k = idx.key(name)
        if k not in cache:
            cache[k] = collapse(idx._days.get(k, ()))
        return cache[k]
    out = []
    for r in rows:
        on = date.fromisoformat(r["date"])
        H, A = feat(days(r["home"]), on, w), feat(days(r["away"]), on, w)
        if H is None or A is None or max(H[0], A[0]) > 30:
            continue
        fh = r["p3"] >= r["p0"]
        pf, pd = (r["p3"], r["p0"]) if fh else (r["p0"], r["p3"])
        (rf, nf), (rd, nd) = (H, A) if fh else (A, H)
        face_f = "3" if fh else "0"
        res = "胜" if r["face"] == face_f else "平" if r["face"] == "1" else "负"
        out.append({**r, "fh": fh, "pf": pf, "pd": pd, "pdraw": r["p1"], "res": res,
                    "rf": rf, "nf": nf, "rd": rd, "nd": nd, "cell": cell(rf, nf, rd, nd)})
    return out


def band(p):
    return next(i for i, (a, b) in enumerate(BANDS) if a <= p < b)


def table(rows, B=20000, seed=7):
    """rows → 每格 n、胜平负、残差、调整残差及 95%/98.75% 区间（比赛日整簇自助）。"""
    n = len(rows)
    win = np.array([x["res"] == "胜" for x in rows], float)
    pf = np.array([x["pf"] for x in rows])
    bd = np.array([band(x["pf"]) for x in rows])
    cl = np.array([CELLS.index(x["cell"]) for x in rows])
    dates = sorted({x["date"] for x in rows})
    di = {d: i for i, d in enumerate(dates)}
    dd = np.array([di[x["date"]] for x in rows])
    base = CELLS.index("双方轻")

    def stat(w):
        """w＝每行权重。返回 每格 残差、调整残差。"""
        res = win - pf
        adj = np.zeros(len(BANDS))
        for b in range(len(BANDS)):
            m = (bd == b) & (cl == base)
            s = w[m].sum()
            adj[b] = (w[m] * res[m]).sum() / s if s else 0
        r2 = res - adj[bd]
        a, c = [], []
        for i in range(len(CELLS)):
            m = cl == i
            s = w[m].sum() or 1
            a.append((w[m] * res[m]).sum() / s)
            c.append((w[m] * r2[m]).sum() / s)
        return np.array(a), np.array(c)

    pt_r, pt_a = stat(np.ones(n))
    rng = np.random.default_rng(seed)
    bs = []
    D = len(dates)
    for _ in range(B):
        cnt = np.bincount(rng.integers(0, D, D), minlength=D)
        bs.append(stat(cnt[dd].astype(float))[1])
    bs = np.array(bs)
    out = {}
    for i, c in enumerate(CELLS):
        m = cl == i
        sub = [x for x, y in zip(rows, m) if y]
        out[c] = dict(n=int(m.sum()), w=sum(x["res"] == "胜" for x in sub), d=sum(x["res"] == "平" for x in sub),
                      l=sum(x["res"] == "负" for x in sub), hit=float(win[m].mean()) if m.any() else None,
                      mkt=float(pf[m].mean()) if m.any() else None, resid=float(pt_r[i]), adj=float(pt_a[i]),
                      ci95=[float(np.percentile(bs[:, i], 2.5)), float(np.percentile(bs[:, i], 97.5))],
                      ci9875=[float(np.percentile(bs[:, i], .625)), float(np.percentile(bs[:, i], 99.375))])
    return out


def show(title, t):
    print(f"\n== {title}")
    print(f"{'格':<8}{'n':>6} {'胜/平/负':>14} {'胜率':>6} {'市场':>6} {'残差pp':>8} {'调整pp':>8}  95%CI            98.75%CI")
    for c, s in t.items():
        if not s["n"]:
            print(c, 0)
            continue
        print(f"{c:<8}{s['n']:>6} {s['w']:>5}/{s['d']}/{s['l']:<5} {s['hit']*100:>5.1f}% {s['mkt']*100:>5.1f}% "
              f"{s['resid']*100:>+7.1f} {s['adj']*100:>+7.1f}  [{s['ci95'][0]*100:+.1f},{s['ci95'][1]*100:+.1f}]  "
              f"[{s['ci9875'][0]*100:+.1f},{s['ci9875'][1]*100:+.1f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".nutmeg-data")
    ap.add_argument("--no-schedule", action="store_true")
    ap.add_argument("--B", type=int, default=20000)
    ap.add_argument("--out", default="experiments/prescreen/2026-11-06-load-cells-oos.json")
    a = ap.parse_args()
    data = Path(a.data_dir)
    idx = build_index(data)
    rows = history_rows(data)
    print("候选场次", len(rows), min(r["date"] for r in rows), max(r["date"] for r in rows))
    res = {}
    for w in (10, 7, 14):
        E = enrich(rows, idx, w)
        oos = [x for x in E if x["date"] < TRAIN_FROM]
        tr = [x for x in E if x["date"] >= TRAIN_FROM]
        print(f"W={w}: 可分格 {len(E)}（样本外 {len(oos)}，训练窗 {len(tr)}）")
        t = table(oos, a.B)
        show(f"样本外 W={w}", t)
        res[f"oos_w{w}"] = t
        if w == 10:
            for name, f in (("足彩场", lambda x: x["zucai"]),
                            ("2025-26 赛季", lambda x: x["date"] < "2026-06-01"),
                            ("2026 夏后", lambda x: x["date"] >= "2026-06-01"),
                            ("热门 ≥50%", lambda x: x["pf"] >= .5),
                            ("热门 <50%", lambda x: x["pf"] < .5)):
                sub = [x for x in oos if f(x)]
                print(name, len(sub))
                t2 = table(sub, min(a.B, 5000))
                show(f"样本外 W=10 · {name}", t2)
                res[f"oos_w10_{name}"] = t2
            t3 = table(tr, min(a.B, 5000))
            show("训练窗（≥10-23，同一代码复算）", t3)
            res["train_w10"] = t3
            base = sum(x["res"] == "胜" for x in oos) / len(oos), sum(x["pf"] for x in oos) / len(oos)
            print("样本外全体热门胜率/市场", base)
    json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
