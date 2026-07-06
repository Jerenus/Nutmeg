"""审核用户 07-02 两张票（周四083/084/085）— 概率来自 wc_r32_0703_dcfit.py 同款 DC 拟合（锚去水fair，禁嘴算）。
票1: 比分3串1 5倍 ¥480 = 083{2:0,2:1,3:0} × 084{2:0,2:1,1:1,2:2} × 085{1:0,2:0,0:0,1:1}
票2: 2串1 50倍 ¥100 = 083让胜@1.81 × 085平@3.10"""
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
# 拟合参数直接取 wc_r32_0703_dcfit.py 输出（同一锚）
M083=matrix(2.148,0.633,-0.032)
M084=matrix(1.695,0.922,-0.111)
M085=matrix(1.469,0.978,-0.111)

# ── 票1: 比分 3串1, 每注¥2×5倍=¥10/combo ──
S083={(2,0):5.10,(2,1):7.00,(3,0):7.00}
S084={(2,0):7.50,(2,1):5.80,(1,1):6.50,(2,2):13.00}
S085={(1,0):6.00,(2,0):7.50,(0,0):8.50,(1,1):5.20}
def cover(m,sel): return sum(m.get(k,0) for k in sel)
def evmult(m,sel): return sum(m.get(k,0)*o for k,o in sel.items())
def report_t1(name,s083,s084,s085,unit=10):
    n=len(s083)*len(s084)*len(s085); stake=n*unit
    c1,c2,c3=cover(M083,s083),cover(M084,s084),cover(M085,s085)
    hit=c1*c2*c3
    ev=unit*evmult(M083,s083)*evmult(M084,s084)*evmult(M085,s085)
    mn=unit*min(s083.values())*min(s084.values())*min(s085.values())
    mx=unit*max(s083.values())*max(s084.values())*max(s085.values())
    print(f"{name}: {n}注×¥{unit}=¥{stake}")
    print(f"  覆盖率 083={c1*100:.1f}% 084={c2*100:.1f}% 085={c3*100:.1f}% → 整票命中={hit*100:.2f}%")
    print(f"  奖金范围 ¥{mn:.0f}~¥{mx:.0f} | 期望回收 ¥{ev:.0f} (EV {ev/stake-1:+.0%})")
    return hit,ev,stake
print("="*70); print("【票1 原方案】")
report_t1("原票",S083,S084,S085)
print()
print("  各场被漏掉的高概率比分:")
for tag,m,sel in [("083",M083,S083),("084",M084,S084),("085",M085,S085)]:
    top=sorted(m.items(),key=lambda kv:-kv[1])[:6]
    miss=[(k,p) for k,p in top if k not in sel]
    inn=[(k,m.get(k,0)) for k in sel]
    print(f"  {tag} 已选:"+" ".join(f"{i}:{j}={p*100:.1f}%" for (i,j),p in inn)+"  |漏:"+" ".join(f"{i}:{j}={p*100:.1f}%" for (i,j),p in miss))
print()
print("【票1 优化变体】(换掉低概率腿,补模态)")
# 变体A: 083 3:0→1:0; 084 2:2→1:0; 085 0:0→2:1
A083={(2,0):5.10,(2,1):7.00,(1,0):6.25}
A084={(2,0):7.50,(2,1):5.80,(1,1):6.50,(1,0):7.00}
A085={(1,0):6.00,(2,0):7.50,(2,1):7.00,(1,1):5.20}
report_t1("变体A(3:0→1:0, 2:2→1:0, 0:0→2:1)",A083,A084,A085)
# 变体B: 同A但 1倍(¥96)
report_t1("变体B=A且倍数5→1",A083,A084,A085,unit=2)

# ── 票2: 2串1 083让胜1.81 × 085平3.10, ¥100 ──
print("="*70); print("【票2 原方案】 083让胜@1.81 × 085平@3.10 ¥100")
p_hcov=sum(p for (i,j),p in M083.items() if i-j>=2)   # 西净胜2+
p_hexact1=sum(p for (i,j),p in M083.items() if i-j==1)
p_draw85=sum(p for (i,j),p in M085.items() if i==j)
p_home85=sum(p for (i,j),p in M085.items() if i>j)
p_away85=sum(p for (i,j),p in M085.items() if i<j)
hit2=p_hcov*p_draw85; ret2=100*1.81*3.10
print(f"  腿1 西净胜2+ = {p_hcov*100:.1f}% | 腿2 瑞阿平局 = {p_draw85*100:.1f}%")
print(f"  整票命中 {hit2*100:.1f}% | 中了拿 ¥{ret2:.0f} | 期望回收 ¥{ret2*hit2:.0f} (EV {ret2*hit2/100-1:+.0%})")
print("  变体(同¥100):")
for name,o2,p2 in [("085让负@1.79(平或阿胜,含爆冷)",1.79,p_draw85+p_away85),
                   ("085主胜@1.80(顺判读:瑞士赢)",1.80,p_home85),
                   ("085主胜@1.80且状态override 52%",1.80,0.52)]:
    h=p_hcov*p2; r=100*1.81*o2
    print(f"   → {name}: 命中{h*100:.1f}% 拿¥{r:.0f} 期望¥{r*h:.0f} (EV{r*h/100-1:+.0%})")

# ── 组合视角: 两票联合 ¥580 ──
print("="*70); print("【两票联合 ¥580 关键情景】")
scen=[("西1-0小胜(让平)",p_hexact1),("西不胜",1-p_hcov-p_hexact1)]
print(f"  西班牙恰胜1球概率={p_hexact1*100:.1f}% → 票2死;票1的083仅盖2:0/2:1/3:0,1-0也死 → ¥580 全灭")
print(f"  西不胜概率={(1-p_hcov-p_hexact1)*100:.1f}% → 两票同样全灭")
both_dead=(p_hexact1+(1-p_hcov-p_hexact1))
print(f"  即: 只要西班牙没净胜2+({(1-p_hcov)*100:.1f}%), ¥580 里至少票2的¥100死, 且083若非2:0/2:1/3:0则¥480也死")
# 083交集: 票1 083选集 ∩ 让胜 = {2:0,3:0} ∪ 2:1(让平)…—— 2:1 是净胜1!
print(f"  ⚠️ 注意: 票1的083选了2:1(净胜1=让平), 票2要净胜2+ → 两票在083上并非完全同生死, 2:1时票1活票2死")
