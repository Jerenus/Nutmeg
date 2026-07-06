"""周日073 南非 vs 加拿大 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚：国际去水 fair 1X2 + 大小球 2.5。拟合 (λ_home, λ_away, rho) 复现市场，
然后确定性导出：比分矩阵模态 / 体彩 hhad +1 三路 / 总进球桶。
"""
import math
from itertools import product

# ---- targets (de-juiced fair, bold_odds.json 周日073) ----
P_HOME = 0.177175   # 南非胜 (home)
P_DRAW = 0.265422
P_AWAY = 0.557403   # 加拿大胜 (away)
P_OVER = 0.439982   # 大 2.5
P_UNDER = 0.560018

MAXG = 12

def pois(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)

def dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return 1 - lh*la*rho
    if i == 0 and j == 1:
        return 1 + lh*rho
    if i == 1 and j == 0:
        return 1 + la*rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0

def matrix(lh, la, rho):
    m = {}
    s = 0.0
    for i in range(MAXG+1):
        for j in range(MAXG+1):
            p = dc_tau(i, j, lh, la, rho) * pois(i, lh) * pois(j, la)
            if p < 0:
                p = 0.0
            m[(i, j)] = p
            s += p
    for k in m:
        m[k] /= s
    return m

def outcomes(m):
    ph = sum(p for (i, j), p in m.items() if i > j)   # home win = SA
    pd = sum(p for (i, j), p in m.items() if i == j)
    pa = sum(p for (i, j), p in m.items() if i < j)   # away win = Canada
    over = sum(p for (i, j), p in m.items() if i+j >= 3)
    return ph, pd, pa, over

def loss(params):
    lh, la, rho = params
    if lh <= 0.01 or la <= 0.01 or abs(rho) > 0.5:
        return 1e9
    m = matrix(lh, la, rho)
    ph, pd, pa, over = outcomes(m)
    return ((ph-P_HOME)**2 + (pd-P_DRAW)**2 + (pa-P_AWAY)**2)*3 + (over-P_OVER)**2*2

# ---- coarse-to-fine grid search (no scipy dependency) ----
best = None
lh = 0.9; la = 1.4; rho = -0.05
step = 0.4
for _ in range(8):
    improved = True
    while improved:
        improved = False
        for dlh, dla, drho in product([-1,0,1],[-1,0,1],[-1,0,1]):
            cand = (lh+dlh*step, la+dla*step*1.0, rho+drho*step*0.1)
            l = loss(cand)
            if best is None or l < best[0]:
                best = (l, cand); lh, la, rho = cand; improved = True
    step *= 0.5

l, (lh, la, rho) = best
m = matrix(lh, la, rho)
ph, pd, pa, over = outcomes(m)

print(f"FIT: lambda_SA(home)={lh:.3f}  lambda_CAN(away)={la:.3f}  rho={rho:.3f}  loss={l:.2e}")
print(f"  reproduced 1X2: SA {ph*100:.1f}% / draw {pd*100:.1f}% / CAN {pa*100:.1f}%   (target {P_HOME*100:.1f}/{P_DRAW*100:.1f}/{P_AWAY*100:.1f})")
print(f"  reproduced O2.5: {over*100:.1f}%   (target {P_OVER*100:.1f}%)")

# ---- top scorelines ----
top = sorted(m.items(), key=lambda kv: -kv[1])[:10]
print("\nTOP SCORELINES (SA-CAN):")
for (i, j), p in top:
    print(f"  {i}:{j}  {p*100:5.1f}%")

# ---- 体彩 hhad goalLineValue=+1 (SA 受让 1 球) — 3 路, 禁亚盘口径 ----
# 受让主胜 = SA+1 > CAN  => SA score >= CAN score  (SA 胜 或 平)
# 让平     = SA+1 == CAN => CAN 恰好赢 1 球 (j-i==1)
# 让负     = SA+1 < CAN  => CAN 赢 2+ (j-i>=2)
recv_win = sum(p for (i, j), p in m.items() if i >= j)
recv_draw = sum(p for (i, j), p in m.items() if j-i == 1)
recv_loss = sum(p for (i, j), p in m.items() if j-i >= 2)
print("\n体彩 HHAD +1 (3路, SA受让1球):")
print(f"  受让主胜 SA胜或平   {recv_win*100:5.1f}%   体彩@2.19 -> 隐含 {100/2.19:.1f}%")
print(f"  让平 CAN恰好赢1球    {recv_draw*100:5.1f}%   体彩@3.23 -> 隐含 {100/3.23:.1f}%")
print(f"  让负 CAN赢2球+       {recv_loss*100:5.1f}%   体彩@2.75 -> 隐含 {100/2.75:.1f}%")

# ---- 对比: 如果误用亚盘 +1 口径 (CAN赢1球退款) ----
asian_sa = recv_win / (recv_win + recv_loss)  # 去掉 push 后的 SA+1 胜率
print(f"\n[对比] 亚盘口径 SA+1 (CAN赢1球退款) 名义胜率 {asian_sa*100:.1f}%  <- 比体彩受让主胜高 {(asian_sa-recv_win)*100:.0f}pp (系统性高估陷阱)")

# ---- total goals buckets ----
print("\n总进球桶:")
for g in range(0, 6):
    pg = sum(p for (i, j), p in m.items() if i+j == g)
    print(f"  {g} 球   {pg*100:5.1f}%")
pg6 = sum(p for (i, j), p in m.items() if i+j >= 6)
print(f"  6+球   {pg6*100:5.1f}%")
under25 = sum(p for (i, j), p in m.items() if i+j <= 2)
print(f"  小2.5 (0-2球)  {under25*100:.1f}%   体彩对应大小球")

# ---- had 体彩 odds value check (90min) ----
print("\n体彩 had (90分钟) value:")
for name, prob, odd in [("南非胜", ph, 5.8), ("平", pd, 3.45), ("加拿大胜", pa, 1.50)]:
    print(f"  {name:8s} 模型{prob*100:5.1f}%  @{odd}  EV={prob*odd-1:+.1%}")
