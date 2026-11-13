# ruff: noqa —— 一次性预筛脚本，按当时原样归档，不再维护
"""让球 ±1 三路：用 had 面国际 fair 精确相加的两档——主让1 的「让负」＝主不胜；主受让1 的「让胜」＝主不败。回测实开 ROI、ret 带、体彩压主差、两串同日组合。"""
import json,os,random,itertools
from collections import defaultdict
root='.nutmeg-data/jczq'
res=json.load(open(f'{root}/jc-results.json'))
A=[]
for d in sorted(os.listdir(f'{root}/daily')):
    p=f'{root}/daily/{d}'
    if d not in res or not(os.path.exists(p+'/sporttery_markets.json') and os.path.exists(p+'/bold_odds.json')): continue
    try: v=json.load(open(p+'/sporttery_markets.json')); b=json.load(open(p+'/bold_odds.json'))
    except Exception: continue
    for day in v.get('matchInfoList') or []:
        for r in day.get('subMatchList') or []:
            if str(r.get('businessDate') or day.get('businessDate'))!=d: continue
            c=r.get('matchNumStr'); hh=r.get('hhad') or {}; h=r.get('had') or {}
            f=((b.get(c) or {}).get('match_winner') or {}).get('fair_probability'); rr=res[d].get(c)
            if not f or not rr or rr.get('ft_home') is None: continue
            try: line=float(hh.get('goalLineValue') or hh.get('goalLine')); sh,sd,sa=float(hh['h']),float(hh['d']),float(hh['a'])
            except Exception: continue
            g=rr['ft_home']-rr['ft_away']
            try: jh=[1/float(h[x]) for x in 'hda']; jc=jh[0]/sum(jh)
            except Exception: jc=None
            if line==-1:   # 让负＝主不胜
                A.append(dict(day=d,c=c,kind='主让1·让负(主不胜)',sp=sa,p=f['draw']+f['away'],win=g<1,fav=f['home'],gap=(jc-f['home']) if jc else None,lg=r.get('leagueAbbName')))
            if line==1:    # 让胜＝主不败；热门在客
                A.append(dict(day=d,c=c,kind='主受让1·让胜(主不败)',sp=sh,p=f['home']+f['draw'],win=g>-1,fav=f['away'],gap=None,lg=r.get('leagueAbbName')))
print(len(A),len({x['day'] for x in A}))
for x in A: x['ret']=x['sp']*x['p']
def boot(sel,n=1500):
    by=defaultdict(list)
    for x in sel: by[x['day']].append(x)
    ds=list(by); out=[]; rnd=random.Random(7)
    for _ in range(n):
        s=[x for _d in rnd.choices(ds,k=len(ds)) for x in by[_d]]
        if s: out.append(sum(x['sp'] if x['win'] else 0 for x in s)/len(s)-1)
    out.sort(); return out[int(.025*len(out))],out[int(.975*len(out))]
def show(name,sel):
    if not sel: print(name,0);return
    n=len(sel);w=sum(x['win'] for x in sel);roi=sum(x['sp'] if x['win'] else 0 for x in sel)/n-1;lo,hi=boot(sel)
    print(f"{name:40s} n={n:4d} 开{w:4d}({w/n:5.1%}) 市场P{sum(x['p'] for x in sel)/n:6.1%} 均SP{sum(x['sp'] for x in sel)/n:5.2f} ret{sum(x['ret'] for x in sel)/n:5.3f} ROI{roi:+6.1%} [{lo:+.1%},{hi:+.1%}]")
K1=[x for x in A if x['kind'].startswith('主让1')]; K2=[x for x in A if x['kind'].startswith('主受')]
show('主让1 让负 全部',K1); show('主受让1 让胜 全部',K2)
for b in [(0,.9),(.9,.95),(.95,1.0),(1.0,1.05),(1.05,9)]:
    show(f'主让1 让负 ret{b}',[x for x in K1 if b[0]<=x['ret']<b[1]])
for b in [(0,.9),(.9,.95),(.95,1.0),(1.0,9)]:
    show(f'主受让1 让胜 ret{b}',[x for x in K2 if b[0]<=x['ret']<b[1]])
for b in [(0,.5),(.5,.55),(.55,.65),(.65,1)]:
    show(f'主让1 让负 主fair{b}',[x for x in K1 if b[0]<=x['fav']<b[1]])
print()
for b in [(-1,-.01),(-.01,.02),(.02,.04),(.04,.06),(.06,1)]:
    show(f'主让1 让负 体彩压主差{b}',[x for x in K1 if x['gap'] is not None and b[0]<=x['gap']<b[1]])
ds=sorted({x['day'] for x in A}); mid=ds[len(ds)//2]; print('split',mid)
show('前半 让负 ret≥.97',[x for x in K1 if x['ret']>=.97 and x['day']<mid]); show('后半 让负 ret≥.97',[x for x in K1 if x['ret']>=.97 and x['day']>=mid])
show('前半 让负 压主差≥.03',[x for x in K1 if x['gap'] is not None and x['gap']>=.03 and x['day']<mid]); show('后半 让负 压主差≥.03',[x for x in K1 if x['gap'] is not None and x['gap']>=.03 and x['day']>=mid])
# 两串/三串：同日 ret≥.97 的让负腿全部两两组合
for k in (2,3):
    by=defaultdict(list)
    for x in K1:
        if x['ret']>=.97: by[x['day']].append(x)
    tk=[]
    for d,l in by.items():
        for co in itertools.combinations(l,k):
            o=1;w=True;pp=1
            for x in co: o*=x['sp'];w&=x['win'];pp*=x['p']
            tk.append(dict(day=d,sp=o,win=w,p=pp))
    for x in tk: x['ret']=x['sp']*x['p']
    show(f'{k}串 让负(ret≥.97)同日全组合',tk)

print('---- 地板')
sl=[x for x in K1 if x['gap'] is not None and x['gap']>=.03]
show('让负 压主差≥.03 全部',sl)
print(' 体彩隐含主不胜(用让负价粗估)均', round(sum(1/x['sp'] for x in sl)/len(sl)/1.139,3))
pool=[x for x in K1 if x['gap'] is not None]
rnd=random.Random(3); b=[]
for _ in range(2000):
    s=rnd.sample(pool,len(sl)); b.append(sum(x['sp'] if x['win'] else 0 for x in s)/len(s)-1)
b.sort(); print(' 同池随机抽同n ROI带',round(b[50],3),round(b[1950],3),'实',round(sum(x['sp'] if x['win'] else 0 for x in sl)/len(sl)-1,3))
for k in (2,3):
    by=defaultdict(list)
    for x in sl: by[x['day']].append(x)
    tk=[]
    for d,l in by.items():
        for co in itertools.combinations(l,k):
            o=1;w=True;pp=1
            for x in co:o*=x['sp'];w&=x['win'];pp*=x['p']
            tk.append(dict(day=d,sp=o,win=w,p=pp))
    for x in tk:x['ret']=x['sp']*x['p']
    show(f'{k}串 压主差≥.03 同日全组合',tk)
