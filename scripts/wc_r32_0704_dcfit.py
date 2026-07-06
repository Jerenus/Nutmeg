"""周五086/087/088 三场 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).
澳大利亚vs埃及 / 阿根廷vs佛得角 / 哥伦比亚vs加纳。锚=国际去水fair 1X2+大小球2.5。
让球线各异: 086 澳+1 / 087 阿-2 / 088 哥-1。
北京 2026-07-04 02:00/06:00/09:30 = 美东 07-03 14:00/18:00/21:30。
"""
import json
import math
from itertools import product

MAXG = 12


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


def over25(m):
    t = totals(m)
    return sum(p for k, p in t.items() if k >= 3)


def outcomes(m):
    ph = sum(p for (i, j), p in m.items() if i > j)
    pd = sum(p for (i, j), p in m.items() if i == j)
    pa = sum(p for (i, j), p in m.items() if i < j)
    return ph, pd, pa


def loss(params, tg):
    lh, la, r = params
    if lh <= 0.01 or la <= 0.01 or abs(r) > 0.5:
        return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    ov = over25(m)
    return ((ph - tg["ph"]) ** 2 + (pd - tg["pd"]) ** 2 + (pa - tg["pa"]) ** 2) * 3 + (ov - tg["over"]) ** 2 * 2


def fit(tg, lh0, la0):
    best = None
    lh, la, r = lh0, la0, -0.06
    step = 0.4
    for _ in range(9):
        improved = True
        while improved:
            improved = False
            for dh, da, dr in product([-1, 0, 1], repeat=3):
                cand = (lh + dh * step, la + da * step, r + dr * step * 0.1)
                l = loss(cand, tg)
                if best is None or l < best[0]:
                    best = (l, cand)
                    lh, la, r = cand
                    improved = True
        step *= 0.5
    return best


FAIR = json.load(open(".nutmeg-data/jczq/daily/2026-07-03/bold_odds.json"))

MATCHES = [
    {"num": "周五086", "name": "澳大利亚 vs 埃及 (周五086)", "home": "澳大利亚", "away": "埃及",
     "had": (3.15, 2.65, 2.30), "hhad": (1.48, 3.55, 5.80), "gl": +1,
     "ttg": {0: 6.00, 1: 3.35, 2: 2.90, 3: 4.20, 4: 8.50, 5: 22.0},
     "crs": {(0, 0): 6.00, (0, 1): 5.75, (1, 1): 4.75, (1, 0): 7.30, (0, 2): 10.0, (1, 2): 7.50, (2, 1): 9.50, (2, 2): 16.0},
     "hafu": {"hh": 5.70, "dh": 6.50, "dd": 3.90, "da": 5.20, "aa": 4.15},
     "lh0": 0.85, "la0": 1.05},
    {"num": "周五087", "name": "阿根廷 vs 佛得角 (周五087)", "home": "阿根廷", "away": "佛得角",
     "had": None, "hhad": (2.13, 3.62, 2.62), "gl": -2,
     "ttg": {0: 18.0, 1: 6.30, 2: 4.00, 3: 3.30, 4: 4.40, 5: 7.50},
     "crs": {(2, 0): 4.50, (3, 0): 4.80, (1, 0): 6.70, (4, 0): 8.00, (2, 1): 10.0, (3, 1): 11.0, (1, 1): 13.0, (5, 0): 14.0},
     "hafu": {"hh": 1.32, "dh": 3.84, "dd": 12.0},
     "lh0": 2.3, "la0": 0.5},
    {"num": "周五088", "name": "哥伦比亚 vs 加纳 (周五088)", "home": "哥伦比亚", "away": "加纳",
     "had": (1.29, 4.20, 8.60), "hhad": (2.20, 2.95, 2.98), "gl": -1,
     "ttg": {0: 9.50, 1: 4.05, 2: 3.15, 3: 3.60, 4: 6.20, 5: 13.0},
     "crs": {(1, 0): 5.25, (2, 0): 5.00, (2, 1): 5.25, (1, 1): 7.55, (3, 0): 7.50, (0, 0): 9.50, (3, 1): 12.5, (0, 1): 17.5},
     "hafu": {"hh": 1.90, "dh": 3.50, "dd": 5.80},
     "lh0": 1.7, "la0": 0.75},
]

for M in MATCHES:
    fw = FAIR[M["num"]]["match_winner"]["fair_probability"]
    ou = FAIR[M["num"]]["over_under"]["fair_probability"]
    tg = {"ph": fw["home"], "pd": fw["draw"], "pa": fw["away"], "over": ou["over"]}
    l, (lh, la, r) = fit(tg, M["lh0"], M["la0"])
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    ov = over25(m)
    print("=" * 64)
    print(M["name"], f"| 让球线 主{M['gl']:+d}")
    print(f"FIT lh({M['home']})={lh:.3f} la({M['away']})={la:.3f} rho={r:.3f} loss={l:.1e}")
    print(f"  1X2复现 主{ph*100:.1f}/平{pd*100:.1f}/客{pa*100:.1f} (锚{tg['ph']*100:.1f}/{tg['pd']*100:.1f}/{tg['pa']*100:.1f}) | 大2.5复现{ov*100:.1f}% (锚{tg['over']*100:.1f}%)")
    top = sorted(m.items(), key=lambda kv: -kv[1])[:8]
    print("  模态比分(主:客):", "  ".join(f"{i}:{j}={p*100:.1f}%" for (i, j), p in top))
    # 净胜球分布 (主视角)
    md = {}
    for (i, j), p in m.items():
        d = i - j
        key = d if -3 < d < 4 else (4 if d >= 4 else -3)
        md[key] = md.get(key, 0.0) + p
    print("  净胜分布:", "  ".join(f"{'+' if k>0 else ''}{k}{'++' if k in (4,-3) else ''}={md.get(k,0)*100:.1f}%" for k in sorted(md, reverse=True)))
    gl = M["gl"]
    hh = M["hhad"]
    cw = sum(p for (i, j), p in m.items() if i + gl > j)
    cd = sum(p for (i, j), p in m.items() if i + gl == j)
    cl = sum(p for (i, j), p in m.items() if i + gl < j)
    print(f"  体彩hhad(主{gl:+d}): 让胜{cw*100:.1f}% @{hh[0]} EV{cw*hh[0]-1:+.0%} | 让平{cd*100:.1f}% @{hh[1]} EV{cd*hh[1]-1:+.0%} | 让负{cl*100:.1f}% @{hh[2]} EV{cl*hh[2]-1:+.0%}")
    t = totals(m)
    tb = "  ".join(f"{g}球{t.get(g,0)*100:.0f}%" for g in range(5))
    u25 = sum(p for k, p in t.items() if k <= 2)
    print(f"  总进球 {tb} 5+={sum(p for k,p in t.items() if k>=5)*100:.0f}% | 小2.5(0-2){u25*100:.0f}%")
    print("  ttg EV:", "  ".join(f"{g}球{t.get(g,0)*100:.0f}%@{o}={t.get(g,0)*o-1:+.0%}" for g, o in M["ttg"].items()))
    print("  crs EV:", "  ".join(f"{i}:{j} {m.get((i,j),0)*100:.1f}%@{o}={m.get((i,j),0)*o-1:+.0%}" for (i, j), o in M["crs"].items()))
    if M["had"]:
        had = M["had"]
        print(f"  had EV(90min): 主{ph*100:.0f}%@{had[0]} {ph*had[0]-1:+.0%} | 平{pd*100:.0f}%@{had[1]} {pd*had[1]-1:+.0%} | 客{pa*100:.0f}%@{had[2]} {pa*had[2]-1:+.0%}")
    # 半全场: 上半场λ*0.44, 下半场λ*0.56, 上下半独立卷积
    lh1, la1 = lh * 0.44, la * 0.44
    lh2, la2 = lh * 0.56, la * 0.56
    m1 = matrix(lh1, la1, r)
    m2 = matrix(lh2, la2, 0.0)

    def joint(first_cond, final_cond):
        tot = 0.0
        for (i1, j1), p1 in m1.items():
            if not first_cond(i1, j1):
                continue
            for (i2, j2), p2 in m2.items():
                if final_cond(i1 + i2, j1 + j2):
                    tot += p1 * p2
        return tot

    hf = M["hafu"]
    parts = []
    conds = {"h": lambda i, j: i > j, "d": lambda i, j: i == j, "a": lambda i, j: i < j}
    for key, o in hf.items():
        c1, c2 = conds[key[0]], conds[key[1]]
        p = joint(c1, c2)
        parts.append(f"{key} {p*100:.1f}%@{o} EV{p*o-1:+.0%}")
    print("  半全场:", " | ".join(parts))
