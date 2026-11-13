# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""防御宽度与资金（2026-11-07，Jun：很多票面过度防御，需要防的比赛一般最多 7–8 场）。

问题一：14 场里非一赔几场；事前按一赔 P 从低到高防，要防到第几场才把它们全包住。
问题二：任九 9 场 s单(9−s)双 各形的命中、回报、中且回本、最长空窗、最大回撤（市场口径，官方任九奖金）。
问题三：Jun 实票的双和包，事后有多少白防、防到、防穿。
未事前登记，只展示。用法：uv run python experiments/prescreen/2026-11-07-defense-width.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from nutmeg.decision.crowd_model import load_observations
from nutmeg.gym.prizes import load_prizes

spec = importlib.util.spec_from_file_location("rs", "scripts/renjiu_shape_backtest.py")
rs = importlib.util.module_from_spec(spec); sys.modules["rs"] = rs; spec.loader.exec_module(rs)
Z = Path(".nutmeg-data/zucai")
MAP = {"home": "3", "draw": "1", "away": "0"}


def depth_stats(obs):
    clean = [o for o in obs if "*" not in o.results]
    non, dep, dep2 = [], [], []
    for o in clean:
        ms = sorted(o.board, key=rs.mp)            # 一赔 P 从低到高＝最该防的在前
        miss = [i + 1 for i, m in enumerate(ms) if o.results[m.no - 1] != rs.order(m)[0]]
        third = [i + 1 for i, m in enumerate(ms) if o.results[m.no - 1] == rs.order(m)[2]]
        non.append(len(miss))
        dep.append(max(miss) if miss else 0)
        dep2.append(len(third))
    n = len(clean)
    print("期数", n, "非一赔 均 %.2f 中位 %d" % (np.mean(non), np.median(non)))
    print("非一赔场数累计：", {k: round(sum(x <= k for x in non) / n * 100) for k in (4, 5, 6, 7, 8, 9)})
    print("要防到第几场才全包住（按一赔 P 从低到高）分布：", sorted(Counter(dep).items()))
    print("防 k 场全包住的期占比：", {k: round(sum(x <= k for x in dep) / n * 100, 1) for k in (7, 8, 9, 10, 11, 12, 13, 14)})
    print("其中还要求不开三赔的期（双＝一二赔）：", {k: round(sum(a <= k and b == 0 for a, b in zip(dep, dep2)) / n * 100, 1) for k in (7, 8, 10, 12, 14)})
    # 防 8 场时，非一赔落在防区内外
    ins, out, th = [], [], []
    for o in clean:
        ms = sorted(o.board, key=rs.mp)
        m8 = ms[:8]
        ins.append(sum(o.results[m.no - 1] != rs.order(m)[0] for m in m8))
        out.append(sum(o.results[m.no - 1] != rs.order(m)[0] for m in ms[8:]))
        th.append(sum(o.results[m.no - 1] == rs.order(m)[2] for m in m8))
    print("防最不稳 8 场：区内非一赔 %.2f（其中三赔穿透 %.2f）区外非一赔 %.2f；区外全是一赔的期 %.1f%%" % (
        np.mean(ins), np.mean(th), np.mean(out), sum(x == 0 for x in out) / n * 100))
    # 任九 9 场
    non9 = []
    for o in clean:
        ms = sorted(o.board, key=lambda m: -rs.mp(m))[:9]
        non9.append(sum(o.results[m.no - 1] != rs.order(m)[0] for m in ms))
    print("任九最稳 9 场里非一赔 均 %.2f" % np.mean(non9), sorted(Counter(non9).items()))


def shapes(obs, pm):
    rng = np.random.default_rng(7)
    def heat(o):
        return sum(rs.mp(m) >= .65 for m in o.board)
    print("\n== 任九各形（最稳 9 场，单放最稳，其余前两面）")
    print("形 | 价 | 中/期 | 均P | 回报 [CI] | 去最大 | 中时中位奖 | 中且回本 | 最长空窗 | 最大回撤")
    out = {}
    for s in (0, 1, 2, 3, 4, 5, 6):
        rec = []
        for o in obs:
            legs = rs.fixed(o.board, (s, 9 - s, 0))
            c, pay, e, hit, pw = rs.evaluate(o, legs, pm)
            rec.append(dict(issue=o.issue, c=c, pay=pay, hit=hit, p=pw, heat=heat(o)))
        pay = np.array([r["pay"] for r in rec]); cost = np.array([r["c"] for r in rec], float)
        bs = [(lambda i: pay[i].sum() / cost[i].sum())(rng.integers(0, len(rec), len(rec))) for _ in range(4000)]
        ex = (pay.sum() - pay.max()) / cost.sum()
        hits = [r for r in rec if r["hit"]]
        run = best = 0
        for r in rec:
            run = 0 if r["hit"] else run + 1
            best = max(best, run)
        net = np.cumsum(pay - cost); dd = float((np.maximum.accumulate(np.r_[0, net])[1:] - net).max())
        back = sum(r["pay"] >= r["c"] for r in hits)
        med = statistics.median([r["pay"] for r in hits]) if hits else 0
        print(f"{s}单{9-s}双 | ¥{int(cost[0])} | {len(hits)}/{len(rec)} | {np.mean([r['p'] for r in rec])*100:.1f}% | {pay.sum()/cost.sum():.2f} [{np.percentile(bs,2.5):.2f},{np.percentile(bs,97.5):.2f}] | {ex:.2f} | ¥{med:,.0f} | {back}/{len(rec)} | {best} | ¥{dd:,.0f}")
        out[s] = rec
        for lab, f in (("热(≥5)", lambda h: h >= 5), ("中(3-4)", lambda h: 3 <= h <= 4), ("冷(≤2)", lambda h: h <= 2)):
            v = [r for r in rec if f(r["heat"])]
            hv = [r for r in v if r["hit"]]
            if v:
                print(f"    {lab} 期 {len(v)} 中 {len(hv)} 回本 {sum(r['pay']>=r['c'] for r in hv)} 回报 {sum(r['pay'] for r in v)/sum(r['c'] for r in v):.2f} 中时中位 ¥{(statistics.median([r['pay'] for r in hv]) if hv else 0):,.0f}")
    return out


def real_tickets(prizes):
    R = [json.loads(l) for l in open(".nutmeg-data/betslips.jsonl")]
    Z_ = [r for r in R if r.get("channel") in ("renjiu", "shengfucai") and r.get("purchased") is not False]
    cnt = Counter(); per = defaultdict(float); shapes_ = Counter(); hit9 = 0; n = 0; dead = []
    used_rows = []
    for r in Z_:
        pr = prizes.get(str(r.get("issue")))
        if not pr or not pr.get("results"):
            continue
        res = pr["results"].split()
        s = d = t = 0; wrong = 0; used = 0; wasted = 0; pierced = 0
        legs = r.get("legs") or []
        for leg in legs:
            try:
                i = int(leg["key"]) - 1
            except (KeyError, ValueError):
                continue
            sel = [MAP.get(x, x) for x in (leg.get("selections") or [])]
            fair = {MAP.get(k, k): v for k, v in (leg.get("fair") or {}).items()}
            top = max(fair, key=fair.get) if fair else None
            a = res[i]
            k = len(sel)
            s += k == 1; d += k == 2; t += k == 3
            ok = a in sel or a == "*"
            wrong += not ok
            if k >= 2:
                cat = "防穿" if not ok else ("白防" if a == top else "防到")
                cnt[("双" if k == 2 else "包", cat)] += 1
                used += cat == "防到"; wasted += cat == "白防"; pierced += cat == "防穿"
            else:
                cnt[("单", "对" if ok else "死")] += 1
        n += 1
        per[str(r.get("issue"))] += float(r.get("stake_yuan") or 0)
        shapes_[(s, d, t)] += 1
        dead.append(wrong)
        hit9 += wrong == 0
        used_rows.append((r.get("slip_id"), s, d, t, r.get("stake_yuan"), wrong, used, wasted, pierced))
    print("\n== Jun 实票", n, "张，全对", hit9, "；期均投入 %.0f，期数 %d，总 %.0f" % (np.mean(list(per.values())), len(per), sum(per.values())))
    print("死腿数分布", sorted(Counter(dead).items()), "均 %.2f" % np.mean(dead))
    print("形分布（单,双,包）", shapes_.most_common(10))
    print("逐腿", sorted(cnt.items(), key=str))
    a = np.array([[x[1], x[2], x[3], x[4] or 0, x[5], x[6], x[7], x[8]] for x in used_rows], float)
    for lab, m in (("防≥7场", a[:, 1] + a[:, 2] >= 7), ("防 5–6", (a[:, 1] + a[:, 2] >= 5) & (a[:, 1] + a[:, 2] <= 6)), ("防≤4", a[:, 1] + a[:, 2] <= 4)):
        if m.sum():
            print(lab, "张", int(m.sum()), "均价 %.0f 均死腿 %.2f 用到防守 %.2f 白防 %.2f 防穿 %.2f 全对 %d" % (a[m, 3].mean(), a[m, 4].mean(), a[m, 5].mean(), a[m, 6].mean(), a[m, 7].mean(), (a[m, 4] == 0).sum()))
    print("近 12 张", used_rows[-12:])


def main():
    obs = load_observations(Z)
    pm = json.load(open(Z / "prize-model.json"))["channels"]["renjiu"]
    depth_stats(obs)
    shapes(obs, pm)
    real_tickets(load_prizes(Z))


if __name__ == "__main__":
    main()
