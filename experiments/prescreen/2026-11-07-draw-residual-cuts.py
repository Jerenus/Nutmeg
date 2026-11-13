# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""平局分段校准与项目样本切分（2026-11-07，Jun：今天各场平局发生面深度分析后排序，26161 分析包 §1g）。

问题一：26160 用全段一条直线校准平局价（斜率 1.13），低价带是否失真？按 12 个价带看外部样本，再在 24% 处分段拟合。
问题二：项目样本里还有没有能改排序的量？度量＝平局残差（实开−收盘平局 P），比赛日整簇自助。
切分：足彩/非足彩、期内平局价排位、开→收平价变动、研究表态与信念、热门近 5 天踢欧战、热门少休。
切分都是看完数据后做的，未事前登记，只展示。欧战记录来自样本表 competition，覆盖不全。
用法：python experiments/prescreen/2026-11-07-draw-residual-cuts.py <12季根目录> <SWE.csv>
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
spec=importlib.util.spec_from_file_location('ds','experiments/prescreen/2026-11-06-draw-signals.py'); ds=importlib.util.module_from_spec(spec); sys.modules['ds']=ds; spec.loader.exec_module(ds)
G=ds.load(sys.argv[1],sys.argv[2]); ds.PRIOR=ds.prior_table(G); F=ds.features(G)
print('F',len(F),F[0]['d'],F[-1]['d'])
print('leagues',sorted({r['l'] for r in F}))
p=np.array([r['p1'] for r in F]); y=np.array([r['draw'] for r in F]); S4=np.array([r['S4'] for r in F])
days=sorted({r['d'] for r in F}); di={d:i for i,d in enumerate(days)}; dd=np.array([di[r['d']] for r in F]); D=len(days)
X=np.c_[np.ones(len(p)),p,S4]; print('beta p+S4',np.linalg.lstsq(X,y,rcond=None)[0])
X1=np.c_[np.ones(len(p)),p]; b1=np.linalg.lstsq(X1,y,rcond=None)[0]; print('beta p',b1)
# 分段：每个 p 带实开 vs 市场，比赛日整簇自助
rng=np.random.default_rng(7)
bands=[(0,.12),(.12,.14),(.14,.16),(.16,.18),(.18,.20),(.20,.22),(.22,.24),(.24,.26),(.26,.28),(.28,.30),(.30,.33),(.33,1)]
W=[np.bincount(rng.integers(0,D,D),minlength=D)[dd].astype(float) for _ in range(1000)]
print('band n 市场 实开 差 CI 线性校准 p+S4校准')
out=[]
bb=np.linalg.lstsq(X,y,rcond=None)[0]
for a,b in bands:
    m=(p>=a)&(p<b); 
    est=[(w[m]*(y[m]-p[m])).sum()/w[m].sum() for w in W]
    lo,hi=np.percentile(est,[2.5,97.5])
    out.append((a,b,int(m.sum()),p[m].mean(),y[m].mean(),lo,hi))
    print(f'{a:.2f}-{b:.2f} n={m.sum():>6} 市场 {p[m].mean()*100:5.1f} 实开 {y[m].mean()*100:5.1f} 差 {(y[m].mean()-p[m].mean())*100:+.1f} [{lo*100:+.1f},{hi*100:+.1f}] 线性 {(b1[0]+b1[1]*p[m].mean())*100:.1f} 三参 {(X[m]@bb).mean()*100:.1f}')
# 单边支线：只看五大/二级；近三季稳定性
for name,mk in (('后三季',np.array([r['s']>'2223' for r in F])),('前八季',np.array([r['s']<='2223' for r in F]))):
    for a,b in ((0,.16),(.16,.20),(.20,.24),(.24,.27),(.27,.30),(.30,1)):
        m=mk&(p>=a)&(p<b)
        print(name,f'{a:.2f}-{b:.2f} n={m.sum()} 市场 {p[m].mean()*100:.1f} 实开 {y[m].mean()*100:.1f}')
# 全板排序力：同比赛日内，平局 P 高的一半 vs 低的一半（高价带内 ≥24% 还有没有排序力）
m=p>=.24
Xh=np.c_[np.ones(m.sum()),p[m]]; print('≥24% 内斜率',np.linalg.lstsq(Xh,y[m],rcond=None)[0], 'n',m.sum())
sl=[]
idx=np.where(m)[0]
for w in W[:600]:
    sw=np.sqrt(w[idx]); sl.append(np.linalg.lstsq(np.c_[sw,sw*p[idx]],sw*y[idx],rcond=None)[0][1])
print('≥24% 斜率 CI',np.percentile(sl,[2.5,97.5]))
m=p<.24
Xl=np.c_[np.ones(m.sum()),p[m]]; print('<24% 斜率',np.linalg.lstsq(Xl,y[m],rcond=None)[0],'n',m.sum())
X2=np.c_[np.ones(len(p)),p,np.maximum(p-.24,0)]; print('分段 beta（24% 处）',np.linalg.lstsq(X2,y,rcond=None)[0])
rows=[json.loads(l) for l in open('experiments/decision-samples-v1.jsonl')]
S=[r for r in rows if r.get('result') and r['result'].get('face') and r.get('price_closing') and r['price_closing'].get('fair')]
print('样本',len(S), S[0]['date'], S[-1]['date'])
def cb(idx,y,p,dates,B=4000,seed=5):
    ds=sorted(set(dates)); di={d:i for i,d in enumerate(ds)}; dd=np.array([di[d] for d in dates]); D=len(ds)
    res=y-p; rng=np.random.default_rng(seed); out=[]
    idx=np.asarray(idx)
    for _ in range(B):
        w=np.bincount(rng.integers(0,D,D),minlength=D)[dd].astype(float)
        s=w[idx].sum()
        if s: out.append((w[idx]*res[idx]).sum()/s)
    return (res[idx].mean(),np.percentile(out,2.5),np.percentile(out,97.5)) if len(out)>10 else (float('nan'),)*3
p=np.array([r['price_closing']['fair']['1'] for r in S]); y=np.array([float(r['result']['face']=='1') for r in S]); dt=[r['date'] for r in S]
print('全样本 平 %.1f 收盘 %.1f'%(y.mean()*100,p.mean()*100), ['%.2f'%(x*100) for x in cb(np.ones(len(S),bool),y,p,dt)])
z=np.array([bool(r.get('zucai')) for r in S]); print('足彩 n',z.sum(),'平 %.1f 收盘 %.1f'%(y[z].mean()*100,p[z].mean()*100),['%.2f'%(x*100) for x in cb(z,y,p,dt)])
ji=np.array([not bool(r.get('zucai')) for r in S]); print('非足彩 n',ji.sum(),'平 %.1f 收盘 %.1f'%(y[ji].mean()*100,p[ji].mean()*100),['%.2f'%(x*100) for x in cb(ji,y,p,dt)])
for a,b in ((0,.16),(.16,.20),(.20,.24),(.24,.27),(.27,.30),(.30,1)):
    m=(p>=a)&(p<b); print(f'{a:.2f}-{b:.2f} n={m.sum()} 收盘 {p[m].mean()*100:.1f} 实开 {y[m].mean()*100:.1f}',['%.1f'%(x*100) for x in cb(m,y,p,dt)])
# 期内排序力
iss=defaultdict(list)
for r in S:
    if r.get('zucai'): iss[r['zucai']['issue']].append(r)
T=Counter(); N=Counter(); E=Counter()
full=[i for i,v in iss.items() if len(v)>=12]
print('足彩期数',len(full))
for i in full:
    v=sorted(iss[i],key=lambda r:-r['price_closing']['fair']['1'])
    n=len(v)
    for k,r in enumerate(v):
        g='前3' if k<3 else ('后3' if k>=n-3 else ('前4-7' if k<7 else '中后'))
        T[g]+=r['result']['face']=='1'; N[g]+=1; E[g]+=r['price_closing']['fair']['1']
for g in ('前3','前4-7','中后','后3'): print(g,N[g],'实开 %.1f 收盘 %.1f'%(T[g]/N[g]*100,E[g]/N[g]*100))
last20=sorted(full)[-20:]
d=sum(r['result']['face']=='1' for i in last20 for r in iss[i]); e=sum(r['price_closing']['fair']['1'] for i in last20 for r in iss[i]); n=sum(len(iss[i]) for i in last20); var=sum(r['price_closing']['fair']['1']*(1-r['price_closing']['fair']['1']) for i in last20 for r in iss[i])
print('近20期',last20[0],last20[-1],'n',n,'开平',d,'期望 %.1f sd %.1f z %.2f'%(e,var**.5,(d-e)/var**.5))
# 研究侧
R=[r for r in S if r.get('research') and (r['research'].get('prospective'))]
print('前瞻研究 n',len(R))
pr=np.array([r['price_closing']['fair']['1'] for r in R]); yr=np.array([float(r['result']['face']=='1') for r in R]); dr=[r['date'] for r in R]
print('平 %.1f 收盘 %.1f'%(yr.mean()*100,pr.mean()*100),['%.2f'%(x*100) for x in cb(np.ones(len(R),bool),yr,pr,dr)])
sd=[(r['research'].get('rubric') or {}).get('S_draw_mode',{}) for r in R]
print(Counter(x.get('answer') for x in sd))
for lab,mk in (('S_draw yes',[x.get('answer')=='yes' for x in sd]),('S_draw no',[x.get('answer')=='no' for x in sd]),('S_draw unknown',[x.get('answer') not in('yes','no') for x in sd]),
    ('表态盖平',[ '1' in (str(r['research'].get('stance_face'))+str(r['research'].get('stance_cover'))) for r in R]),
    ('未盖平',[ '1' not in (str(r['research'].get('stance_face'))+str(r['research'].get('stance_cover'))) for r in R]),
    ('信念高收盘≥1.5',[ ((r.get('belief') or {}).get('system') or {}).get('1',0)-r['price_closing']['fair']['1']>=.015 for r in R]),
    ('弱方拖平路线',[ any(('拖平' in s or '铁桶' in s or '低位' in s) for s in (r['research'].get('underdog_routes') or [])) for r in R]),
    ('无拖平路线',[ not any(('拖平' in s or '铁桶' in s or '低位' in s) for s in (r['research'].get('underdog_routes') or [])) for r in R])):
    m=np.array(mk,bool)
    if m.sum()>=5: print(lab,m.sum(),'实开 %.1f 收盘 %.1f'%(yr[m].mean()*100,pr[m].mean()*100),['%.1f'%(x*100) for x in cb(m,yr,pr,dr)])
# 开→收漂移（titan，同今表口径）
D=[r for r in S if r['price_closing'].get('opening')]
pd=np.array([r['price_closing']['fair']['1'] for r in D]); po=np.array([r['price_closing']['opening']['1'] for r in D]); yd=np.array([float(r['result']['face']=='1') for r in D]); dd=[r['date'] for r in D]
df=pd-po
print('漂移 n',len(D),'sd %.2f'%(df.std()*100))
for lab,m in (('平价涨≥+1',df>=.01),('平价跌≥1',df<=-.01),('其余',abs(df)<.01)):
    print(lab,m.sum(),'实开 %.1f 收盘 %.1f'%(yd[m].mean()*100,pd[m].mean()*100),['%.1f'%(x*100) for x in cb(m,yd,pd,dd)])
# 热门少休/欧战
spec=importlib.util.spec_from_file_location('lc','experiments/prescreen/2026-11-06-load-cells-oos.py'); lc=importlib.util.module_from_spec(spec); sys.modules['lc']=lc; spec.loader.exec_module(lc)
EU=('欧冠','欧罗巴','欧协','欧会','欧联','UEFA','Champions','Europa','Conference')
eu=defaultdict(set)
for r in rows:
    if any(k in str(r.get('competition') or '') for k in EU):
        for t in (r.get('home'),r.get('away')):
            if t: eu[t].add(date.fromisoformat(r['date']))
print('欧战队',len(eu),sum(len(v) for v in eu.values()))
print('欧战队',len(eu))
idx=lc.build_index(Path('.nutmeg-data')) if lc.build_index.__code__.co_argcount>=1 else lc.build_index()
hr=lc.history_rows(Path('.nutmeg-data'))
E=lc.enrich(hr,idx,10)
print('enrich',len(E))
pdr=np.array([x['p1'] for x in E]); yd=np.array([float(x['face']=='1') for x in E]); dts=[x['date'] for x in E]; pf=np.array([x['pf'] for x in E]); rf=np.array([x['rf'] for x in E]); rdd=np.array([x['rd'] for x in E])
def fav(x): return x['home'] if x['fh'] else x['away']
def euro_recent(x):
    t=fav(x); on=date.fromisoformat(x['date'])
    return any(0<(on-d).days<=5 for d in eu.get(t,()))
er=np.array([euro_recent(x) for x in E])
for lab,m in (('热门≥55·休≤4',(pf>=.55)&(rf<=4)),('热门≥55·休≥5',(pf>=.55)&(rf>=5)),('热门≥55·近5天欧战',(pf>=.55)&er),('热门≥55·无欧战',(pf>=.55)&~er),('热门≥65·近5天欧战',(pf>=.65)&er),('全·近5天欧战',er)):
    print(lab,m.sum(),'实开平 %.1f 收盘 %.1f'%(yd[m].mean()*100,pdr[m].mean()*100),['%.1f'%(x*100) for x in cb(m,yd,pdr,dts)],'热门胜 %.1f vs %.1f'%(100*np.mean([x['res']=='胜' for x,k in zip(E,m) if k]),pf[m].mean()*100))
