"""2026-07-20 全 4 场 — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚 = 决策 store 当日 sporttery 快照去水 fair（had 1X2 + ttg 全分布 0..7+）。
输出: λ/ρ、模态比分 Top6、净胜分布、体彩 3 路让球 cover、ttg 带、大 2.5 球概率。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
SNAPS = ROOT / ".nutmeg-data/jczq/decision/snapshots.jsonl"
DAILY = ROOT / ".nutmeg-data/jczq/daily/2026-07-20"

# 体彩让球线（主队 + line 口径，3 路）
TICAI_LINE = {"周一201": 1, "周一202": 1, "周一203": 1, "周一204": -1}
MATCH = {
    "周一201": ("M-2026-07-20-tps图尔-坦山猫", "TPS图尔库 vs 伊尔维斯"),
    "周一202": ("M-2026-07-20-玛丽港-拉赫蒂", "玛丽港 vs 拉赫蒂"),
    "周一203": ("M-2026-07-20-厄格里特-佐加顿斯", "厄格里特 vs 佐加顿斯"),
    "周一204": ("M-2026-07-20-卡尔马-马尔默", "卡尔马 vs 马尔默"),
}


def pois(k, l):
    return math.exp(-l) * l ** k / math.factorial(k)


def tau(i, j, lh, la, r):
    if i == 0 and j == 0:
        return 1 - lh * la * r
    if i == 0 and j == 1:
        return 1 + lh * r
    if i == 1 and j == 0:
        return 1 + la * r
    if i == 1 and j == 1:
        return 1 - r
    return 1.0


def matrix(lh, la, r):
    m = {}
    s = 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            p = max(0.0, tau(i, j, lh, la, r) * pois(i, lh) * pois(j, la))
            m[(i, j)] = p
            s += p
    return {k: v / s for k, v in m.items()}


def totals(m):
    t = {}
    for (i, j), p in m.items():
        t[i + j] = t.get(i + j, 0.0) + p
    return t


def outcomes(m):
    ph = sum(p for (i, j), p in m.items() if i > j)
    pd = sum(p for (i, j), p in m.items() if i == j)
    pa = sum(p for (i, j), p in m.items() if i < j)
    return ph, pd, pa


def ttg_bands(m):
    t = totals(m)
    bands = {f"total_{k}": t.get(k, 0.0) for k in range(7)}
    bands["total_7"] = sum(v for kk, v in t.items() if kk >= 7)
    return bands


def loss(params, tg):
    lh, la, r = params
    if lh <= 0.05 or la <= 0.05 or abs(r) > 0.5:
        return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    l = ((ph - tg["ph"]) ** 2 + (pd - tg["pd"]) ** 2 + (pa - tg["pa"]) ** 2) * 3
    bands = ttg_bands(m)
    for k, v in tg["ttg"].items():
        l += (bands[k] - v) ** 2
    return l


def fit(tg, lh0=1.3, la0=1.1):
    best = (loss((lh0, la0, -0.06), tg), (lh0, la0, -0.06))
    lh, la, r = lh0, la0, -0.06
    step = 0.4
    for _ in range(10):
        improved = True
        while improved:
            improved = False
            for dh, da, dr in product([-1, 0, 1], repeat=3):
                cand = (lh + dh * step, la + da * step, r + dr * step * 0.1)
                l = loss(cand, tg)
                if l < best[0] - 1e-12:
                    best = (l, cand)
                    lh, la, r = cand
                    improved = True
        step /= 2
    return best[1], best[0]


def hhad_cover(m, line):
    win = sum(p for (i, j), p in m.items() if i + line > j)
    push = sum(p for (i, j), p in m.items() if i + line == j)
    lose = sum(p for (i, j), p in m.items() if i + line < j)
    return win, push, lose


def margin_dist(m):
    d = {}
    for (i, j), p in m.items():
        d[i - j] = d.get(i - j, 0.0) + p
    return d


def main():
    fairs = {}
    for line in SNAPS.read_text().splitlines():
        s = json.loads(line)
        for num, (mid, _) in MATCH.items():
            if s.get("match_id") == mid and s.get("source") == "sporttery" and "2026-07-20" in s.get("taken_at", ""):
                fairs[num] = s["fair"]
    report = {}
    for num, (mid, name) in MATCH.items():
        fair = fairs[num]
        tg = {
            "ph": fair["had"]["home"], "pd": fair["had"]["draw"], "pa": fair["had"]["away"],
            "ttg": fair["ttg"],
        }
        (lh, la, r), l = fit(tg)
        m = matrix(lh, la, r)
        ph, pd, pa = outcomes(m)
        top = sorted(m.items(), key=lambda kv: -kv[1])[:6]
        bands = ttg_bands(m)
        line = TICAI_LINE[num]
        w, pu, lo = hhad_cover(m, line)
        md = margin_dist(m)
        rec = {
            "match": name,
            "lambda_home": round(lh, 3), "lambda_away": round(la, 3), "rho": round(r, 3),
            "fit_loss": round(l, 6),
            "model_1x2": [round(ph, 3), round(pd, 3), round(pa, 3)],
            "anchor_1x2": [round(tg["ph"], 3), round(tg["pd"], 3), round(tg["pa"], 3)],
            "modal_scores": [f"{i}:{j} {p:.1%}" for (i, j), p in top],
            "ttg_bands": {k: round(v, 3) for k, v in bands.items()},
            "p_over_2_5": round(sum(p for (i, j), p in m.items() if i + j >= 3), 3),
            "ticai_hhad_line": line,
            "hhad_3way": {"让胜": round(w, 3), "让平": round(pu, 3), "让负": round(lo, 3)},
            "anchor_hhad_fair": fair.get("hhad"),
            "margin": {
                "主净胜≥3": round(sum(p for k, p in md.items() if k >= 3), 3),
                "主净胜2": round(md.get(2, 0.0), 3),
                "主净胜1": round(md.get(1, 0.0), 3),
                "平": round(md.get(0, 0.0), 3),
                "客净胜1": round(md.get(-1, 0.0), 3),
                "客净胜2": round(md.get(-2, 0.0), 3),
                "客净胜≥3": round(sum(p for k, p in md.items() if k <= -3), 3),
            },
        }
        report[num] = rec
    out = DAILY / "dcfit-20260720.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for num, rec in report.items():
        print(f"\n== {num} {rec['match']} ==")
        print(f" λ {rec['lambda_home']}/{rec['lambda_away']} ρ {rec['rho']} loss {rec['fit_loss']}")
        print(f" 1x2 model {rec['model_1x2']} anchor {rec['anchor_1x2']}")
        print(f" 模态比分: {', '.join(rec['modal_scores'])}")
        print(f" ttg: {rec['ttg_bands']}")
        print(f" P(≥3球)={rec['p_over_2_5']}")
        print(f" 体彩让球线 {rec['ticai_hhad_line']:+d}: {rec['hhad_3way']} | anchor fair {rec['anchor_hhad_fair']}")
        print(f" 净胜: {rec['margin']}")
    print(f"\nWROTE {out}")


if __name__ == "__main__":
    main()
