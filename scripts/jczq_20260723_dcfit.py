"""2026-07-23 全 7 场 — Dixon-Coles fit from de-juiced fair (禁嘴算).

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

# 体彩让球线（主队 + line 口径，3 路）
TICAI_LINE = {
    "周四201": -1, "周四202": -1, "周四203": -1, "周四204": 1,
    "周四205": -1, "周四206": -1, "周四207": -1,
}
MATCH = {
    "周四201": ("M-2026-07-23-科林蒂安-里莫", "科林蒂安 vs 里莫"),
    "周四202": ("M-2026-07-23-博塔弗戈-维多利亚", "博塔弗戈 vs 维多利亚"),
    "周四203": ("M-2026-07-23-哈马比-安德莱", "哈马比 vs 安德莱赫特"),
    "周四204": ("M-2026-07-23-圣加仑-本菲卡", "圣加仑 vs 本菲卡"),
    "周四205": ("M-2026-07-23-贝西克塔-中日德兰", "贝西克塔斯 vs 中日德兰"),
    "周四206": ("M-2026-07-23-特温特-费伦茨", "特温特 vs 费伦茨瓦罗斯"),
    "周四207": ("M-2026-07-23-斯海杜克-帕福斯", "海杜克 vs 帕福斯"),
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
    for raw in SNAPS.read_text().splitlines():
        s = json.loads(raw)
        for num, (mid, _) in MATCH.items():
            if s.get("match_id") == mid and s.get("source") == "sporttery" and "2026-07-23" in s.get("taken_at", ""):
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
        over25 = sum(v for kk, v in totals(m).items() if kk >= 3)
        report[num] = {
            "name": name,
            "lambda": [round(lh, 3), round(la, 3), round(r, 3)],
            "fit_loss": round(l, 6),
            "fair_had": {k: round(v, 3) for k, v in fair["had"].items()},
            "dc_had": [round(ph, 3), round(pd, 3), round(pa, 3)],
            "top_scores": [[f"{i}:{j}", round(p, 4)] for (i, j), p in top],
            "ttg_bands": {k: round(v, 3) for k, v in bands.items()},
            "over25": round(over25, 3),
            "hhad_line": line,
            "hhad_cover": {"让胜": round(w, 3), "让平": round(pu, 3), "让负": round(lo, 3)},
            "margin": {str(k): round(v, 3) for k, v in sorted(md.items()) if -4 <= k <= 4},
            "win_by_2plus": round(sum(v for kk, v in md.items() if kk >= 2), 3),
        }
    out = ROOT / ".nutmeg-data/jczq/daily/2026-07-23/dcfit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for num, r in report.items():
        print(f"{num} {r['name']} λ={r['lambda']} fair={r['fair_had']}")
        print(f"   模态: {r['top_scores'][:4]} | 大2.5球={r['over25']} | 净胜≥2={r['win_by_2plus']}")
        print(f"   hhad({r['hhad_line']}): {r['hhad_cover']}")


if __name__ == "__main__":
    main()
