"""周二077/078/079 三场 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).

科特迪瓦vs挪威 / 法国vs瑞典 / 墨西哥vs厄瓜多尔。锚=国际去水 fair 1X2 + 大小球。
拟合 (lh,la,rho) 复现市场 → 比分矩阵模态 / 体彩 hhad 三路(非亚盘) / 总进球桶 / had EV。
GL 支持 -1(主让) 与 +1(主受让)。
"""
import math
from itertools import product

MAXG = 12

def pois(k, l): return math.exp(-l) * l**k / math.factorial(k)

def tau(i, j, lh, la, r):
    if i == 0 and j == 0: return 1 - lh*la*r
    if i == 0 and j == 1: return 1 + lh*r
    if i == 1 and j == 0: return 1 + la*r
    if i == 1 and j == 1: return 1 - r
    return 1.0

def matrix(lh, la, r):
    m = {}; s = 0.0
    for i in range(MAXG+1):
        for j in range(MAXG+1):
            p = max(0.0, tau(i, j, lh, la, r)*pois(i, lh)*pois(j, la))
            m[(i, j)] = p; s += p
    return {k: v/s for k, v in m.items()}

def totals(m):
    t = {}
    for (i, j), p in m.items():
        t[i+j] = t.get(i+j, 0.0) + p
    return t

def over_eff(m, line):
    t = totals(m)
    def ge(n): return sum(p for k, p in t.items() if k >= n)
    def eq(n): return t.get(n, 0.0)
    if abs(line*2 % 2 - 1) < 1e-9:          # x.5 (2.5)
        return ge(math.ceil(line))
    if abs(line - round(line*4)/4) < 1e-9 and abs(line*4 % 4 - 1) < 1e-9:  # x.25
        lo = int(line - 0.25)
        return 0.5*(ge(lo+1) + 0.5*eq(lo)) + 0.5*ge(lo+1)
    hi = int(line + 0.25)
    return 0.5*ge(hi) + 0.5*(ge(hi+1) + 0.5*eq(hi))

def outcomes(m):
    ph = sum(p for (i, j), p in m.items() if i > j)
    pd = sum(p for (i, j), p in m.items() if i == j)
    pa = sum(p for (i, j), p in m.items() if i < j)
    return ph, pd, pa

def loss(params, tg):
    lh, la, r = params
    if lh <= 0.01 or la <= 0.01 or abs(r) > 0.5: return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    ov = over_eff(m, tg['line'])
    return ((ph-tg['ph'])**2 + (pd-tg['pd'])**2 + (pa-tg['pa'])**2)*3 + (ov-tg['over'])**2*2

def fit(tg, lh0, la0):
    best = None; lh, la, r = lh0, la0, -0.06; step = 0.4
    for _ in range(9):
        improved = True
        while improved:
            improved = False
            for dh, da, dr in product([-1, 0, 1], repeat=3):
                cand = (lh+dh*step, la+da*step, r+dr*step*0.1)
                l = loss(cand, tg)
                if best is None or l < best[0]:
                    best = (l, cand); lh, la, r = cand; improved = True
        step *= 0.5
    return best

MATCHES = [
    {"name": "科特迪瓦 vs 挪威 (周二077)", "home": "科特迪瓦", "away": "挪威",
     "ph": 0.268852, "pd": 0.277914, "pa": 0.453234, "line": 2.5, "over": 0.496197,
     "had": (3.55, 3.35, 1.82), "hhad": (1.78, 3.55, 3.50), "gl": +1, "lh0": 1.0, "la0": 1.35},
    {"name": "法国 vs 瑞典 (周二078)", "home": "法国", "away": "瑞典",
     "ph": 0.741286, "pd": 0.163388, "pa": 0.095326, "line": 2.5, "over": 0.646788,
     "had": (1.16, 5.80, 10.50), "hhad": (1.60, 3.95, 3.98), "gl": -1, "lh0": 2.1, "la0": 0.8},
    {"name": "墨西哥 vs 厄瓜多尔 (周二079)", "home": "墨西哥", "away": "厄瓜多尔",
     "ph": 0.432007, "pd": 0.325313, "pa": 0.24268, "line": 2.5, "over": 0.323064,
     "had": (1.94, 2.70, 4.10), "hhad": (4.45, 3.27, 1.67), "gl": -1, "lh0": 1.05, "la0": 0.8},
]

for M in MATCHES:
    l, (lh, la, r) = fit(M, M["lh0"], M["la0"])
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    ov = over_eff(m, M["line"])
    print("="*64)
    print(M["name"])
    print(f"FIT lh({M['home']})={lh:.3f} la({M['away']})={la:.3f} rho={r:.3f} loss={l:.1e}")
    print(f"  1X2 复现: 主 {ph*100:.1f}/平 {pd*100:.1f}/客 {pa*100:.1f}  (锚 {M['ph']*100:.1f}/{M['pd']*100:.1f}/{M['pa']*100:.1f})")
    print(f"  大{M['line']} 复现 {ov*100:.1f}%  (锚 {M['over']*100:.1f}%)")
    top = sorted(m.items(), key=lambda kv: -kv[1])[:8]
    print("  模态比分(主:客):", "  ".join(f"{i}:{j}={p*100:.1f}%" for (i, j), p in top))
    hh = M["hhad"]
    if M["gl"] == -1:
        cw = sum(p for (i, j), p in m.items() if i-j >= 2)   # 让主胜 主赢2+
        cd = sum(p for (i, j), p in m.items() if i-j == 1)   # 让平 主赢1
        cl = sum(p for (i, j), p in m.items() if i <= j)     # 让负 客不败
        lab = (f"让主胜(主赢2+) {cw*100:.1f}% @{hh[0]} EV{cw*hh[0]-1:+.0%}",
               f"让平(主赢1) {cd*100:.1f}% @{hh[1]} EV{cd*hh[1]-1:+.0%}",
               f"让负(客不败) {cl*100:.1f}% @{hh[2]} EV{cl*hh[2]-1:+.0%}")
    else:  # gl == +1 主受让
        cw = sum(p for (i, j), p in m.items() if i >= j)     # 让主胜 主不败
        cd = sum(p for (i, j), p in m.items() if j-i == 1)   # 让平 客赢1
        cl = sum(p for (i, j), p in m.items() if j-i >= 2)   # 让负 客赢2+
        lab = (f"让主胜(主不败) {cw*100:.1f}% @{hh[0]} EV{cw*hh[0]-1:+.0%}",
               f"让平(客赢1) {cd*100:.1f}% @{hh[1]} EV{cd*hh[1]-1:+.0%}",
               f"让负(客赢2+) {cl*100:.1f}% @{hh[2]} EV{cl*hh[2]-1:+.0%}")
    print(f"  体彩hhad(GL{M['gl']:+d}): " + " | ".join(lab))
    t = totals(m)
    tb = "  ".join(f"{g}球{t.get(g,0)*100:.0f}%" for g in range(5))
    u25 = sum(p for k, p in t.items() if k <= 2)
    print(f"  总进球: {tb}  5+={sum(p for k,p in t.items() if k>=5)*100:.0f}% | 小2.5(0-2) {u25*100:.0f}%")
    had = M["had"]
    print(f"  had EV(90min): 主胜 {ph*100:.0f}%@{had[0]} {ph*had[0]-1:+.0%} | "
          f"平 {pd*100:.0f}%@{had[1]} {pd*had[1]-1:+.0%} | 客胜 {pa*100:.0f}%@{had[2]} {pa*had[2]-1:+.0%}")
