# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""白防线是不是近期正路多的假象（2026-11-08，Jun：0.8 白防可能是因为近期正路偏多；预警多时 0.8、0.85 以上也要提醒）。

① 外部样本：一条双（一赔+二赔）里一赔开出的条件概率，按 p1/(p1+p2) 分线、逐季看实开与价格。
② 项目前瞻样本：线 ≥0.80 的场按研究预警个数（不站热门/开双/锚方 fail/锚方洞未价/崩塌候选/读高估/轮换窗口）分组。
未事前登记，只展示。用法：uv run python experiments/prescreen/2026-11-08-white-line-regime.py <12季根目录> <SWE.csv>
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("ds", "experiments/prescreen/2026-11-06-draw-signals.py")
ds = importlib.util.module_from_spec(spec); sys.modules["ds"] = ds; spec.loader.exec_module(ds)


def external(root, swe):
    G = [g for g in ds.load(root, swe) if g["o"]]
    inv = np.array([[1 / x for x in g["o"]] for g in G]); P = inv / inv.sum(1, keepdims=True)
    Y = np.array([0 if g["hg"] > g["ag"] else (1 if g["hg"] == g["ag"] else 2) for g in G])
    o = np.argsort(-P, 1); p1 = P[np.arange(len(P)), o[:, 0]]; p2 = P[np.arange(len(P)), o[:, 1]]
    ratio = p1 / (p1 + p2); inside = (Y == o[:, 0]) | (Y == o[:, 1]); white = Y == o[:, 0]
    seasons = np.array([g["s"] for g in G])
    for lo, hi in ((.70, .75), (.75, .80), (.80, .85), (.85, 1.01)):
        m = (ratio >= lo) & (ratio < hi) & inside
        print(f"线 {lo:.2f}-{hi:.2f} 条件内 n={m.sum()} 价格 {ratio[m].mean()*100:.1f} 实开 {white[m].mean()*100:.1f}")
        per = []
        for s in sorted(set(seasons)):
            k = m & (seasons == s)
            if k.sum() >= 80:
                per.append((s, k.sum(), round(white[k].mean() * 100, 1), round(ratio[k].mean() * 100, 1)))
        lows = sorted(per, key=lambda x: x[2] - x[3])[:3]
        print("   各季实开−价格 范围 %+.1f 到 %+.1f；最差三季" % (min(x[2] - x[3] for x in per), max(x[2] - x[3] for x in per)), lows)


FLAGS = ("研究不站热门", "研究开双", "锚方 fail", "锚方洞未价", "崩塌候选", "研究读高估", "轮换窗口")


def flags_of(res, fav):
    rb = res.get("rubric") or {}
    lq = res.get("license_questions") or {}
    hole = res.get("hole") or {}
    out = []
    if res.get("stance_face") in ("3", "1", "0") and res.get("stance_face") != fav:
        out.append("研究不站热门")
    if res.get("stance_structure") == "double" or res.get("stance_cover") in ("3", "1", "0"):
        out.append("研究开双")
    if res.get("anchor_integrity") == "fail":
        out.append("锚方 fail")
    if hole.get("rel") == "fav" and hole.get("priced_in") is False:
        out.append("锚方洞未价")
    if (rb.get("S_crash_candidate") or {}).get("answer") == "yes":
        out.append("崩塌候选")
    if str(res.get("market_read") or (rb.get("M_market_read") or {}).get("answer") or "").startswith("overpriced"):
        out.append("研究读高估")
    if lq.get("q5_no_rotation_window") is False:
        out.append("轮换窗口")
    return out


def project():
    rows = [json.loads(l) for l in open("experiments/decision-samples-v1.jsonl")]
    S = [r for r in rows if r.get("research") and r["research"].get("prospective") and r.get("result")
         and r["result"].get("face") and (r.get("price_closing") or {}).get("fair")]
    by = defaultdict(list); per = defaultdict(list)
    for r in S:
        f = r["price_closing"]["fair"]; o = sorted("310", key=lambda k: -f[k])
        ratio = f[o[0]] / (f[o[0]] + f[o[1]]); a = r["result"]["face"]
        if ratio < .80 or a not in o[:2]:
            continue
        fl = flags_of(r["research"], o[0]); w = a == o[0]
        by[min(len(fl), 3)].append((w, ratio))
        for x in fl:
            per[x].append((w, ratio))
    print("\n项目前瞻 线 ≥0.80、开在一二赔内的场")
    for k in sorted(by):
        v = by[k]; print(f"  预警 {k}{'+' if k == 3 else ''} 个 n={len(v)} 白防 {np.mean([x[0] for x in v])*100:.1f}% 价格 {np.mean([x[1] for x in v])*100:.1f}%")
    for x in FLAGS:
        v = per.get(x) or []
        if v:
            print(f"  {x} n={len(v)} 白防 {np.mean([y[0] for y in v])*100:.1f}% 价格 {np.mean([y[1] for y in v])*100:.1f}%")


if __name__ == "__main__":
    external(sys.argv[1], sys.argv[2])
    project()
