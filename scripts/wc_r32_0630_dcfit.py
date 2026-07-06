"""周一074/075/076 三场 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).

巴西vs日本 / 德国vs巴拉圭 / 荷兰vs摩洛哥。锚=国际去水 fair 1X2 + 大小球。
拟合 (lh,la,rho) 复现市场 → 比分矩阵模态 / 体彩 hhad 三路(非亚盘) / 总进球桶 / had EV。
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
    """Effective no-vig 'over' win prob for .5/.25/.75 lines (push = half)."""
    t = totals(m)
    def ge(n): return sum(p for k, p in t.items() if k >= n)
    def eq(n): return t.get(n, 0.0)
    if abs(line*2 % 2 - 1) < 1e-9:          # x.5 (2.5)
        return ge(math.ceil(line))
    if abs(line - round(line*4)/4) < 1e-9 and abs(line*4 % 4 - 1) < 1e-9:  # x.25 (2.25 -> 2.0/2.5)
        lo = int(line - 0.25)               # 2.0
        return 0.5*(ge(lo+1) + 0.5*eq(lo)) + 0.5*ge(lo+1)
    # x.75 (2.75 -> 2.5/3.0)
    hi = int(line + 0.25)                    # 3.0
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
    {"name": "巴西 vs 日本 (周一074)", "home": "巴西", "away": "日本",
     "ph": 0.559933, "pd": 0.253522, "pa": 0.186545, "line": 2.5, "over": 0.482203,
     "had": (1.56, 3.45, 5.05), "hhad": (2.84, 3.30, 2.11), "gl": -1, "lh0": 1.5, "la0": 0.9},
    {"name": "德国 vs 巴拉圭 (周一075)", "home": "德国", "away": "巴拉圭",
     "ph": 0.696417, "pd": 0.190771, "pa": 0.112812, "line": 2.75, "over": 0.512105,
     "had": (1.25, 4.75, 8.40), "hhad": (1.85, 3.60, 3.22), "gl": -1, "lh0": 1.8, "la0": 0.7},
    {"name": "荷兰 vs 摩洛哥 (周一076)", "home": "荷兰", "away": "摩洛哥",
     "ph": 0.44644, "pd": 0.294731, "pa": 0.258829, "line": 2.25, "over": 0.456981,
     "had": (1.89, 3.07, 3.64), "hhad": (3.82, 3.58, 1.70), "gl": -1, "lh0": 1.3, "la0": 1.0},
]

for M in MATCHES:
    l, (lh, la, r) = fit(M, M["lh0"], M["la0"])
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    ov = over_eff(m, M["line"])
    print("="*60)
    print(M["name"])
    print(f"FIT lh({M['home']})={lh:.3f} la({M['away']})={la:.3f} rho={r:.3f} loss={l:.1e}")
    print(f"  1X2 复现: 主 {ph*100:.1f}/平 {pd*100:.1f}/客 {pa*100:.1f}  (锚 {M['ph']*100:.1f}/{M['pd']*100:.1f}/{M['pa']*100:.1f})")
    print(f"  大{M['line']} 复现 {ov*100:.1f}%  (锚 {M['over']*100:.1f}%)")
    top = sorted(m.items(), key=lambda kv: -kv[1])[:8]
    print("  模态比分(主:客):", "  ".join(f"{i}:{j}={p*100:.1f}%" for (i, j), p in top))
    # 体彩 hhad GL=-1 (主队让1球) 3路
    by2 = sum(p for (i, j), p in m.items() if i-j >= 2)
    by1 = sum(p for (i, j), p in m.items() if i-j == 1)
    le0 = sum(p for (i, j), p in m.items() if i <= j)
    hh = M["hhad"]
    print(f"  体彩hhad(主-1): 让主胜(主赢2+) {by2*100:.1f}% @{hh[0]} EV{by2*hh[0]-1:+.0%} | "
          f"让平(主赢1) {by1*100:.1f}% @{hh[1]} EV{by1*hh[1]-1:+.0%} | "
          f"让负(客不败) {le0*100:.1f}% @{hh[2]} EV{le0*hh[2]-1:+.0%}")
    t = totals(m)
    tb = "  ".join(f"{g}球{t.get(g,0)*100:.0f}%" for g in range(5))
    u25 = sum(p for k, p in t.items() if k <= 2)
    print(f"  总进球: {tb}  6+={sum(p for k,p in t.items() if k>=6)*100:.0f}% | 小2.5(0-2) {u25*100:.0f}%")
    had = M["had"]
    print(f"  had EV(90min): 主胜 {ph*100:.0f}%@{had[0]} {ph*had[0]-1:+.0%} | "
          f"平 {pd*100:.0f}%@{had[1]} {pd*had[1]-1:+.0%} | 客胜 {pa*100:.0f}%@{had[2]} {pa*had[2]-1:+.0%}")
