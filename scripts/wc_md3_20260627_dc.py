"""DC fit to de-vig fair (1X2 + O/U2.5) for 2026-06-27 MD3 board. 禁嘴算."""
import json, math
from itertools import product
from scipy.optimize import minimize
import numpy as np

bo = json.load(open('.nutmeg-data/jczq/daily/2026-06-27/bold_odds.json'))
MAXG = 12
MATCHES = {
 "067 克vs加": ("周六067", -1),   # Croatia -1
 "068 巴vs英": ("周六068", +2),   # Panama +2 / England -2
 "069 哥vs葡": ("周六069", +1),   # Colombia +1 / Portugal -1
 "070 刚vs乌": ("周六070", -1),   # Congo -1
 "071 阿vs奥": ("周六071", +1),   # Algeria +1 / Austria -1
 "072 约vs阿": ("周六072", +2),   # Jordan +2 / Argentina -2
}

def dc_tau(i,j,lh,la,rho):
    if i==0 and j==0: return 1-lh*la*rho
    if i==0 and j==1: return 1+lh*rho
    if i==1 and j==0: return 1+la*rho
    if i==1 and j==1: return 1-rho
    return 1.0

def matrix(lh,la,rho):
    M=np.zeros((MAXG+1,MAXG+1))
    for i in range(MAXG+1):
        for j in range(MAXG+1):
            p=math.exp(-lh)*lh**i/math.factorial(i)*math.exp(-la)*la**j/math.factorial(j)
            M[i,j]=p*max(dc_tau(i,j,lh,la,rho),1e-6)
    return M/M.sum()

def probs(M):
    n=M.shape[0]
    home=sum(M[i,j] for i in range(n) for j in range(n) if i>j)
    draw=sum(M[i,i] for i in range(n))
    away=sum(M[i,j] for i in range(n) for j in range(n) if i<j)
    over=sum(M[i,j] for i in range(n) for j in range(n) if i+j>=3)
    return home,draw,away,over

def fit(fh,fd,fa,fover):
    def loss(x):
        lh,la,rho=x
        if lh<=0 or la<=0: return 1e9
        rho=max(min(rho,0.18),-0.18)
        h,d,a,o=probs(matrix(lh,la,rho))
        return (h-fh)**2+(d-fd)**2+(a-fa)**2+0.5*(o-fover)**2
    best=None
    for lh0 in [0.6,1.0,1.4,1.8,2.2]:
        for la0 in [0.6,1.0,1.4,1.8]:
            r=minimize(loss,[lh0,la0,0.0],method='Nelder-Mead',
                       options={'xatol':1e-6,'fatol':1e-10,'maxiter':4000})
            if best is None or r.fun<best.fun: best=r
    return best.x, best.fun

for name,(key,line) in MATCHES.items():
    m=bo[key]; mw=m['match_winner']['fair_probability']
    ou=m.get('over_under',{}); oufp=ou.get('fair_probability',{})
    oline=ou.get('line')
    fh,fd,fa=mw['home'],mw['draw'],mw['away']
    fover=oufp.get('over',0.45)
    (lh,la,rho),err=fit(fh,fd,fa,fover)
    M=matrix(lh,la,rho); n=M.shape[0]
    h,d,a,o=probs(M)
    # modal scores
    flat=sorted(((M[i,j],i,j) for i in range(n) for j in range(n)),reverse=True)[:6]
    # net margin (home - away)
    from collections import defaultdict
    nm=defaultdict(float)
    for i in range(n):
        for j in range(n):
            nm[i-j]+=M[i,j]
    # 3-way hhad at line. line = handicap added to HOME score? In 体彩, goalLine是让球数 for home.
    # goalLineValue e.g. Croatia -1 => home -1. Panama +2 => home +2.
    # hhad: 让胜 = home+line > away ; 让平 = home+line == away ; 让负 = home+line < away
    win=draw=lose=0.0
    for i in range(n):
        for j in range(n):
            adj=i+line
            if adj>j: win+=M[i,j]
            elif adj==j: draw+=M[i,j]
            else: lose+=M[i,j]
    # ttg
    ttg=defaultdict(float)
    for i in range(n):
        for j in range(n):
            ttg[min(i+j,7)]+=M[i,j]
    print(f"\n===== {name}  (line home {line:+d}) λ主={lh:.2f} λ客={la:.2f} rho={rho:.2f} err={err:.1e} =====")
    print(f"  拟合 1X2: 主{h:.1%}/平{d:.1%}/客{a:.1%}  (target 主{fh:.1%}/平{fd:.1%}/客{fa:.1%})  over2.5={o:.1%}")
    print(f"  模态比分: " + "  ".join(f"{i}:{j}={p:.1%}" for p,i,j in flat))
    print(f"  净胜分布: " + "  ".join(f"{k:+d}:{nm[k]:.0%}" for k in sorted(nm) if -3<=k<=4 and nm[k]>=0.03))
    print(f"  体彩3路让球[{line:+d}]: 让胜{win:.1%}  让平{draw:.1%}  让负{lose:.1%}")
    print(f"  总进球: " + "  ".join(f"{k}球{ttg[k]:.0%}" for k in range(0,6)))
