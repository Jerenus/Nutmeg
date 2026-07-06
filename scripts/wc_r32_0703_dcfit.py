"""周四083/084/085 三场 R32 — Dixon-Coles fit from de-juiced fair (禁嘴算).
西班牙vs奥地利 / 葡萄牙vs克罗地亚 / 瑞士vs阿尔及利亚。锚=国际去水fair 1X2+大小球。全 -1 让球线。
北京 2026-07-03 03:00/07:00/11:00 = 美东 07-02 15:00/19:00/23:00。"""
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
 {"name":"西班牙 vs 奥地利 (周四083)","home":"西班牙","away":"奥地利","ph":0.7216,"pd":0.1850,"pa":0.0933,"over":0.5261,
  "had":(1.23,4.75,9.40),"hhad":(1.85,3.55,3.25),
  "ttg":{0:13.0,1:5.2,2:3.6,3:3.45,4:5.1,5:8.5,6:16.0,7:24.0},
  "crs":{(2,0):5.1,(1,0):6.25,(2,1):7.0,(3,0):7.0,(1,1):9.0,(3,1):9.5,(0,0):13.0},
  "hafu":{"hh":1.70,"dh":3.75,"dd":7.20},
  "lh0":1.9,"la0":0.6},
 {"name":"葡萄牙 vs 克罗地亚 (周四084)","home":"葡萄牙","away":"克罗地亚","ph":0.5434,"pd":0.2655,"pa":0.1911,"over":0.4857,
  "had":(1.59,3.40,4.85),"hhad":(3.11,3.12,2.05),
  "ttg":{0:11.0,1:4.7,2:3.5,3:3.5,4:5.4,5:10.0,6:18.0,7:26.0},
  "crs":{(2,1):5.8,(1,1):6.5,(1,0):7.0,(2,0):7.5,(0,0):11.0,(3,1):11.0,(0,1):13.0},
  "hafu":{"hh":2.35,"dh":4.20,"dd":5.60},
  "lh0":1.35,"la0":0.85},
 {"name":"瑞士 vs 阿尔及利亚 (周四085)","home":"瑞士","away":"阿尔及利亚","ph":0.4714,"pd":0.2911,"pa":0.2375,"over":0.4427,
  "had":(1.80,3.05,4.06),"hhad":(3.73,3.30,1.79),
  "ttg":{0:8.5,1:4.2,2:3.0,3:3.75,4:6.2,5:14.0,6:25.0,7:40.0},
  "crs":{(1,1):5.2,(1,0):6.0,(2,1):7.0,(2,0):7.5,(0,0):8.5,(0,1):10.0,(1,2):12.0},
  "hafu":{"hh":2.90,"dh":4.60,"dd":4.75},
  "lh0":1.25,"la0":0.9},
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
    print("  ttg EV:","  ".join(f"{g}球{t.get(g,0)*100:.0f}%@{o}={t.get(g,0)*o-1:+.0%}" for g,o in M["ttg"].items() if g<=5))
    print("  crs EV:","  ".join(f"{i}:{j} {m.get((i,j),0)*100:.1f}%@{o}={m.get((i,j),0)*o-1:+.0%}" for (i,j),o in M["crs"].items()))
    had=M["had"]
    print(f"  had EV(90min): 主{ph*100:.0f}%@{had[0]} {ph*had[0]-1:+.0%} | 平{pd*100:.0f}%@{had[1]} {pd*had[1]-1:+.0%} | 客{pa*100:.0f}%@{had[2]} {pa*had[2]-1:+.0%}")
    # 半全场关键三项(hh/dh/dd)用独立半场泊松近似: 上半场λ*0.44, 下半场λ*0.56
    lh1,la1=lh*0.44,la*0.44; lh2,la2=lh*0.56,la*0.56
    m1=matrix(lh1,la1,r); m2=matrix(lh2,la2,0.0)
    def half_res(mm):
        h=sum(p for (i,j),p in mm.items() if i>j); d=sum(p for (i,j),p in mm.items() if i==j); a=sum(p for (i,j),p in mm.items() if i<j)
        return h,d,a
    h1,d1,a1=half_res(m1)
    # P(半X全Y) 近似: 需联合分布,用蒙特卡洛小样本替代? 改用解析: 全场=上半+下半卷积
    # P(hh)=P(上半主领先 且 全场主胜)≈ Σ_{i1>j1} P1(i1,j1) * P(下半 i2,j2: i1+i2>j1+j2)
    def joint(first_cond,final_cond):
        tot=0.0
        for (i1,j1),p1 in m1.items():
            if not first_cond(i1,j1): continue
            for (i2,j2),p2 in m2.items():
                if final_cond(i1+i2,j1+j2): tot+=p1*p2
        return tot
    phh=joint(lambda i,j:i>j, lambda i,j:i>j)
    pdh=joint(lambda i,j:i==j, lambda i,j:i>j)
    pdd=joint(lambda i,j:i==j, lambda i,j:i==j)
    hf=M["hafu"]
    print(f"  半全场: 胜胜{phh*100:.1f}%@{hf['hh']} EV{phh*hf['hh']-1:+.0%} | 平胜{pdh*100:.1f}%@{hf['dh']} EV{pdh*hf['dh']-1:+.0%} | 平平{pdd*100:.1f}%@{hf['dd']} EV{pdd*hf['dd']-1:+.0%}")
