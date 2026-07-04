"""2026-07-04 全 11 场 — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚 = bold_odds.json 国际去水 fair 1X2 + 大小球(各场线不同, 2/2.25/2.5/2.75/3)。
输出: λ/ρ、模态比分 Top6、净胜分布、体彩 3 路让球 cover(各场线)、ttg 带。
周六090 巴拉圭vs法国 体彩不开 had, 让球线 +2。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
DAILY = Path(__file__).parents[1] / ".nutmeg-data/jczq/daily/2026-07-04"

# 体彩让球线（3 路口径）
TICAI_LINE = {
    "周六089": 1, "周六090": 2, "周六201": 1, "周六202": -1, "周六203": -1,
    "周六204": -1, "周六205": 1, "周六206": 1, "周六207": -1, "周六208": 1,
    "周六209": -1,
}
NAMES = {
    "周六089": "加拿大 vs 摩洛哥", "周六090": "巴拉圭 vs 法国",
    "周六201": "安养FC vs 浦项制铁", "周六202": "大田市民 vs 富川FC",
    "周六203": "全北现代 vs 江原FC", "周六204": "拉赫蒂 vs 赫尔辛基火花",
    "周六205": "哈尔姆斯塔德 vs 韦斯特罗斯", "周六206": "代格福什 vs 马尔默",
    "周六207": "塞伊奈约基 vs TPS图尔库", "周六208": "雅罗 vs 坦佩雷山猫",
    "周六209": "瓦萨 vs 玛丽港",
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


def p_tot_ge(m, k):
    return sum(p for (i, j), p in m.items() if i + j >= k)


def over_quoted(m, line):
    """模型口径下、给定大小球线的『被报价 over』公平概率(整数线剔除 push)。"""
    if abs(line - 2.5) < 1e-9:
        return p_tot_ge(m, 3)
    if abs(line - 3.5) < 1e-9:
        return p_tot_ge(m, 4)
    if abs(line - 2.0) < 1e-9:
        t = totals(m)
        push = t.get(2, 0.0)
        return p_tot_ge(m, 3) / max(1e-9, 1 - push)
    if abs(line - 3.0) < 1e-9:
        t = totals(m)
        push = t.get(3, 0.0)
        return p_tot_ge(m, 4) / max(1e-9, 1 - push)
    if abs(line - 2.25) < 1e-9:
        return 0.5 * over_quoted(m, 2.0) + 0.5 * over_quoted(m, 2.5)
    if abs(line - 2.75) < 1e-9:
        return 0.5 * over_quoted(m, 2.5) + 0.5 * over_quoted(m, 3.0)
    raise ValueError(f"unsupported line {line}")


def outcomes(m):
    ph = sum(p for (i, j), p in m.items() if i > j)
    pd = sum(p for (i, j), p in m.items() if i == j)
    pa = sum(p for (i, j), p in m.items() if i < j)
    return ph, pd, pa


def loss(params, tg):
    lh, la, r = params
    if lh <= 0.05 or la <= 0.05 or abs(r) > 0.5:
        return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    l = ((ph - tg["ph"]) ** 2 + (pd - tg["pd"]) ** 2 + (pa - tg["pa"]) ** 2) * 3
    if tg.get("over") is not None:
        l += (over_quoted(m, tg["line"]) - tg["over"]) ** 2 * 2
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
    """体彩 3 路让球: 让胜/让平/让负 (主队+line 口径)。"""
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
    bold = json.loads((DAILY / "bold_odds.json").read_text())
    report = {}
    for num, name in NAMES.items():
        mw = bold[num]["match_winner"]["fair_probability"]
        ou = bold[num].get("over_under") or {}
        tg = {
            "ph": mw["home"], "pd": mw["draw"], "pa": mw["away"],
            "over": (ou.get("fair_probability") or {}).get("over"),
            "line": float(ou["line"]) if ou.get("line") else None,
        }
        (lh, la, r), l = fit(tg)
        m = matrix(lh, la, r)
        ph, pd, pa = outcomes(m)
        top = sorted(m.items(), key=lambda kv: -kv[1])[:6]
        t = totals(m)
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
            "ttg_bands": {str(k): round(t.get(k, 0.0), 3) for k in range(6)} | {"6+": round(sum(v for kk, v in t.items() if kk >= 6), 3)},
            "over_line": tg["line"],
            "model_over_quoted": round(over_quoted(m, tg["line"]), 3) if tg["line"] else None,
            "anchor_over": tg["over"],
            "ticai_hhad_line": line,
            "hhad_3way": {"让胜": round(w, 3), "让平": round(pu, 3), "让负": round(lo, 3)},
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
    out = DAILY / "dcfit-20260704.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for num, rec in report.items():
        print(f"\n== {num} {rec['match']} ==")
        print(f" λ {rec['lambda_home']}/{rec['lambda_away']} ρ {rec['rho']} loss {rec['fit_loss']}")
        print(f" 1x2 model {rec['model_1x2']} anchor {rec['anchor_1x2']}")
        print(f" 模态比分: {', '.join(rec['modal_scores'])}")
        print(f" ttg: {rec['ttg_bands']}")
        print(f" O/U{rec['over_line']}: model {rec['model_over_quoted']} anchor {rec['anchor_over']}")
        print(f" 体彩让球线 {rec['ticai_hhad_line']:+d}: {rec['hhad_3way']}")
        print(f" 净胜: {rec['margin']}")
    print(f"\nWROTE {out}")


if __name__ == "__main__":
    main()
