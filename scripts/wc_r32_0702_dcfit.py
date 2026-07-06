"""周三080/081/082 三场 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).
英格兰vs刚果金 / 比利时vs塞内加尔 / 美国vs波黑。锚=国际去水fair 1X2+大小球。全 -1 让球线。"""
import math
from itertools import product
MAXG=12
def pois(k,l): return math.exp(-l)*l**k/math.factorial(k)
def tau(i,j,lh,la,r):
    if i==0 and j==0: return 1-lh*la*r
    if i==0 and j==1: return 1+lh*r
    if i==1 and j==0: return 1+la*r
    if i==1 and j==1: return 1-r
    return 1.0
def matrix(lh,la,r):
    m={};s=0.0
    for i in range(MAXG+1):
        for j in range(MAXG+1):
            p=max(0.0,tau(i,j,lh,la,r)*pois(i,lh)*pois(j,la)); m[(i,j)]=p; s+=p
    return {k:v/s for k,v in m.items()}
def totals(m):
    t={}
    for (i,j),p in m.items(): t[i+j]=t.get(i+j,0.0)+p
    return t
def over25(m):
    t=totals(m); return sum(p for k,p in t.items() if k>=3)
def outcomes(m):
    ph=sum(p for (i,j),p in m.items() if i>j); pd=sum(p for (i,j),p in m.items() if i==j); pa=sum(p for (i,j),p in m.items() if i<j)
    return ph,pd,pa
def loss(params,tg):
    lh,la,r=params
    if lh<=0.01 or la<=0.01 or abs(r)>0.5: return 1e9
    m=matrix(lh,la,r); ph,pd,pa=outcomes(m); ov=over25(m)
    return ((ph-tg['ph'])**2+(pd-tg['pd'])**2+(pa-tg['pa'])**2)*3+(ov-tg['over'])**2*2
def fit(tg,lh0,la0):
    best=None; lh,la,r=lh0,la0,-0.06; step=0.4
    for _ in range(9):
        improved=True
        while improved:
            improved=False
            for dh,da,dr in product([-1,0,1],repeat=3):
                cand=(lh+dh*step,la+da*step,r+dr*step*0.1); l=loss(cand,tg)
                if best is None or l<best[0]: best=(l,cand); lh,la,r=cand; improved=True
        step*=0.5
    return best
MATCHES=[
 {"name":"英格兰 vs 刚果金 (周三080)","home":"英格兰","away":"刚果金","ph":0.743,"pd":0.182,"pa":0.075,"over":0.477,
  "had":(1.16,5.35,12.50),"hhad":(1.65,3.65,4.01),"lh0":2.0,"la0":0.55},
 {"name":"比利时 vs 塞内加尔 (周三081)","home":"比利时","away":"塞内加尔","ph":0.436,"pd":0.294,"pa":0.270,"over":0.457,
  "had":(1.99,2.95,3.47),"hhad":(4.15,3.60,1.64),"lh0":1.2,"la0":1.0},
 {"name":"美国 vs 波黑 (周三082)","home":"美国","away":"波黑","ph":0.690,"pd":0.197,"pa":0.113,"over":0.526,
  "had":(1.26,4.55,8.60),"hhad":(1.90,3.50,3.15),"lh0":1.75,"la0":0.75},
]
for M in MATCHES:
    l,(lh,la,r)=fit(M,M["lh0"],M["la0"]); m=matrix(lh,la,r); ph,pd,pa=outcomes(m); ov=over25(m)
    print("="*64); print(M["name"])
    print(f"FIT lh({M['home']})={lh:.3f} la({M['away']})={la:.3f} rho={r:.3f} loss={l:.1e}")
    print(f"  1X2复现 主{ph*100:.1f}/平{pd*100:.1f}/客{pa*100:.1f} (锚{M['ph']*100:.1f}/{M['pd']*100:.1f}/{M['pa']*100:.1f}) | 大2.5复现{ov*100:.1f}% (锚{M['over']*100:.1f}%)")
    top=sorted(m.items(),key=lambda kv:-kv[1])[:8]
    print("  模态比分(主:客):","  ".join(f"{i}:{j}={p*100:.1f}%" for (i,j),p in top))
    hh=M["hhad"]
    cw=sum(p for (i,j),p in m.items() if i-j>=2); cd=sum(p for (i,j),p in m.items() if i-j==1); cl=sum(p for (i,j),p in m.items() if i<=j)
    print(f"  体彩hhad(主-1): 让胜(主赢2+){cw*100:.1f}% @{hh[0]} EV{cw*hh[0]-1:+.0%} | 让平(主赢1){cd*100:.1f}% @{hh[1]} EV{cd*hh[1]-1:+.0%} | 让负(客不败){cl*100:.1f}% @{hh[2]} EV{cl*hh[2]-1:+.0%}")
    t=totals(m); tb="  ".join(f"{g}球{t.get(g,0)*100:.0f}%" for g in range(5)); u25=sum(p for k,p in t.items() if k<=2)
    print(f"  总进球 {tb} 5+={sum(p for k,p in t.items() if k>=5)*100:.0f}% | 小2.5(0-2){u25*100:.0f}%")
    had=M["had"]
    print(f"  had EV(90min): 主{ph*100:.0f}%@{had[0]} {ph*had[0]-1:+.0%} | 平{pd*100:.0f}%@{had[1]} {pd*had[1]-1:+.0%} | 客{pa*100:.0f}%@{had[2]} {pa*had[2]-1:+.0%}")
