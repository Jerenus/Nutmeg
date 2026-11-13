# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""胜负彩奖金结构与奖池滚存（2026-11-07，接 sfc-odds-rank-shape）。

一赔个数 vs 奖金、全国中奖注数泊松回归（含空奖期）、期初滚存 vs 当期全市场返奖率。
先跑 sfc-odds-rank-shape 生成逐期行。探索性，未事前登记，只展示。
"""
import json,math,sys
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
sys.path.insert(0,'.')
from nutmeg.decision.zucai_official import fetch_history,_num
R=json.load(open('experiments/prescreen/2026-11-07-sfc-rows.json'))
raw=fetch_history(page_size=135)
items=(raw.get('value') or raw).get('list') or raw.get('list') or []
print('history',len(items)); print([k for k in items[0].keys()][:30])
pool={}
for it in items:
    pool[str(it.get('lotteryDrawNum'))]=dict(after=_num(it.get('poolBalanceAfterdraw')),sale=_num(it.get('totalSaleAmount')),rj=_num(it.get('totalSaleAmountRj')))
json.dump(pool,open('experiments/prescreen/2026-11-07-sfc-pool.json','w'))
ks=sorted(pool); print(ks[0],ks[-1],len(ks)); print([ (k,pool[k]['after']) for k in ks[-10:]])
print('\n== 形状 vs 奖金')
by=defaultdict(list)
for r in R:
    g='≥10' if r['c1']>=10 else ('≤6' if r['c1']<=6 else str(r['c1']))
    by[g].append(r)
for g in ('≤6','7','8','9','≥10'):
    v=by[g]
    fa=[r['first'] for r in v if r['firstn']>0]; fn=[r['firstn'] for r in v]; sa=[r['second'] for r in v]; 
    print(g,'n',len(v),'空奖期',sum(1 for r in v if r['firstn']==0),'一等注数中位',np.median(fn),'一等奖中位 %.0f'%np.median(fa) if fa else None,'二等奖中位 %.0f'%np.median(sa),'S均 %.1f'%np.mean([r['S'] for r in v]))
print('销量中位',np.median([r['sale'] for r in R]))
# 泊松回归：全国一等奖注数 ~ S
def pois(S,y,off):
    X=np.c_[np.ones(len(S)),S]; b=np.array([np.log((y.sum()+.5)/np.exp(off).sum()),0.])
    for _ in range(200):
        eta=X@b+off; mu=np.exp(eta); W=mu; z=eta-off+(y-mu)/mu
        nb=np.linalg.solve((X.T*W)@X,(X.T*W)@z)
        if abs(nb-b).max()<1e-8: b=nb; break
        b=nb
    return b
S=np.array([r['S'] for r in R]); y1=np.array([r['firstn'] for r in R],float); y2=np.array([r['secondn'] for r in R],float); off=np.log(np.array([r['sale']/2 for r in R]))
b1=pois(S,y1,off); b2=pois(S,y2,off); print('一等泊松',b1,'二等泊松',b2)
n=len(R); h=n//2
print('前半',pois(S[:h],y1[:h],off[:h]),'后半',pois(S[h:],y1[h:],off[h:]))
print('ln(注数) 对 S 的 OLS(≥1):',np.polyfit(S[y1>0],np.log(y1[y1>0]/np.exp(off[y1>0])),1))
for a,bb in ((0,10),(10,12),(12,13),(13,14),(14,15),(15,16),(16,18),(18,30)):
    m=(S>=a)&(S<bb)
    if m.sum(): print(f'S {a}-{bb} n={m.sum()} 一等注中位 {np.median(y1[m]):.0f} 空奖 {(y1[m]==0).sum()} 模型λ {np.exp(b1[0]+b1[1]*S[m].mean()+off[m].mean()):.1f} 概率口径 {np.exp(-S[m].mean()+off[m].mean()):.1f} 一等额中位 {np.median([r["first"] for r,k in zip(R,m) if k and r["firstn"]>0] or [0]):.0f}')
# 派奖率
t=[]
for i,r in enumerate(R):
    pay=r['first']*r['firstn']+r['second']*r['secondn']
    t.append(pay/r['sale'])
t=np.array(t); print('期返奖率 均 %.3f 中位 %.3f max %.2f'%(t.mean(),np.median(t),t.max()))
print('二等池/销量',np.median([r['second']*r['secondn']/r['sale'] for r in R]),'一等池/销量(未封顶)',np.median([r['first']*r['firstn']/r['sale'] for r in R if 0<r['first']<4.9e6]))
# 滚存
iss=[r['issue'] for r in R]
prev={}
ks=sorted(pool)
for a,b in zip(ks[:-1],ks[1:]): prev[b]=pool[a]['after']
xs=[];ts=[];ss=[]
for r,x in zip(R,t):
    if prev.get(r['issue']) is not None:
        xs.append(prev[r['issue']]/r['sale']); ts.append(x); ss.append(r['sale'])
xs=np.array(xs);ts=np.array(ts)
print('期初滚存/销量 中位 %.2f max %.2f n %d'%(np.median(xs),xs.max(),len(xs)))
for a,b in ((0,.05),(.05,.2),(.2,.5),(.5,1),(1,100)):
    m=(xs>=a)&(xs<b)
    if m.sum(): print(f'滚存/销量 {a}-{b} n={m.sum()} 平均返奖率 {ts[m].mean():.2f} 中位 {np.median(ts[m]):.2f}')
print('滚存绝对值(近12期):',[ (k,round((pool[k]['after'] or 0)/1e4)) for k in ks[-12:]])
json.dump(dict(b1=b1.tolist(),b2=b2.tolist()),open('experiments/prescreen/2026-11-07-sfc-fit.json','w'))
