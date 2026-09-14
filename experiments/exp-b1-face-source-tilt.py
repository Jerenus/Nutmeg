"""B1 面级源倾斜：500广口径均值 vs titan007锐盘子集，逐面系统差 + 残差跟随方向。"""
import json
import math
import random
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
t7 = json.load(open(Z/"t7-backfill.json"))
res = json.load(open(Z/"official-results.json"))
FACE = {"3":"home","1":"draw","0":"away"}

def load_500(path):
    """500.com 基线：兼容 {matches:[...]} 与 {场号: {...}} 两种历史形状。"""
    d = json.load(open(path))
    raw = d.get("matches", d)
    items = raw.items() if isinstance(raw, dict) else (
        (str(m.get("match_no")), m) for m in raw)
    out = {}
    for k, v in items:
        if isinstance(v, dict) and all(x in v for x in ("home", "draw", "away")):
            out[str(k)] = v
    return out

rows, skipped = [], 0
for issue, matches in t7.items():
    op = Z/f"{issue}-odds.json"
    if not op.exists() or issue not in res:
        continue
    five = load_500(op)
    outcomes = res[issue].split()
    if len(outcomes) != 14:
        continue
    for no, rec in matches.items():
        m5 = five.get(no)
        if not m5:
            skipped += 1
            continue
        try:
            a = {k: 1.0/float(m5[k]) for k in ("home","draw","away")}
        except (TypeError, ValueError, ZeroDivisionError):
            skipped += 1
            continue
        s = sum(a.values())
        if not (0.97 < s < 1.03):
            skipped += 1
            continue   # 500 页已去水;偏离即脏数据
        a = {k: v/s for k, v in a.items()}
        rows.append({"issue":issue,"no":no,"a":a,"b":rec["fair"],
                     "actual":FACE[outcomes[int(no)-1]]})
print(f"可比样本 n={len(rows)}  期数={len({r['issue'] for r in rows})}")

# ① 面级系统差 500 − t7
print("\n① 面级系统差（500 广口径 − t7 锐盘），正=500 定价更高")
for f in ("home","draw","away"):
    d = [r["a"][f]-r["b"][f] for r in rows]
    mean = sum(d)/len(d)
    sd = math.sqrt(sum((x-mean)**2 for x in d)/(len(d)-1))
    se = sd/math.sqrt(len(d))
    print(f"  {f:5s} Δ均值 {mean*100:+6.2f}pp  SE {se*100:.2f}  t={mean/se:+6.2f}"
          f"  |Δ|中位 {sorted(abs(x) for x in d)[len(d)//2]*100:5.2f}pp")

# ② 实际跟随谁：只看两源分歧 >=2pp 的面，看实开率更接近哪一侧
print("\n② 分歧面上，实际开出率跟随哪一侧（分歧 ≥2pp 的面）")
for f in ("home","draw","away"):
    sub = [r for r in rows if abs(r["a"][f]-r["b"][f]) >= 0.02]
    if len(sub) < 20:
        print(f"  {f:5s} n={len(sub)} 样本不足")
        continue
    act = sum(1 for r in sub if r["actual"]==f)/len(sub)
    pa = sum(r["a"][f] for r in sub)/len(sub)
    pb = sum(r["b"][f] for r in sub)/len(sub)
    print(f"  {f:5s} n={len(sub):3d}  实开 {act*100:5.1f}%  "
          f"500 预期 {pa*100:5.1f}%(残差{(act-pa)*100:+5.1f})  "
          f"t7 预期 {pb*100:5.1f}%(残差{(act-pb)*100:+5.1f})")

# ③ 面级权重扫描：只在该面上偏向 t7，其余面等权，重归一后比 Brier
def brier(p, actual):
    return sum((p[k]-(1.0 if k==actual else 0.0))**2 for k in ("home","draw","away"))
def mix(r, wb):                     # wb = dict face->t7 权重
    p = {k: (1-wb[k])*r["a"][k] + wb[k]*r["b"][k] for k in ("home","draw","away")}
    s = sum(p.values())
    return {k: v/s for k, v in p.items()}
base = {k:0.5 for k in ("home","draw","away")}
b0 = sum(brier(mix(r, base), r["actual"]) for r in rows)/len(rows)
print(f"\n③ 面级倾斜扫描（基线=三面等权 0.5，Brier {b0:.5f}）")
for face in ("draw","home","away"):
    line = [f"  {face:5s}"]
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        wb = dict(base)
        wb[face] = w
        b = sum(brier(mix(r, wb), r["actual"]) for r in rows)/len(rows)
        line.append(f"w={w:.2f}:{(1-b/b0)*100:+6.2f}%")
    print("  ".join(line))

# ④ 最佳面级方案的 bootstrap CI（对比等权）
random.seed(7)
best = {"home":0.5,"draw":1.0,"away":0.5}
d = [brier(mix(r,base),r["actual"]) - brier(mix(r,best),r["actual"]) for r in rows]
boots = []
for _ in range(4000):
    s = [random.choice(d) for _ in d]
    boots.append(sum(s)/len(s)/b0*100)
boots.sort()
mean = sum(d)/len(d)/b0*100
win = sum(1 for x in d if x > 1e-12)
lose = sum(1 for x in d if x < -1e-12)
print(f"\n④ 平局面全偏 t7（w_draw=1.0）vs 等权：BSS {mean:+.2f}% "
      f"CI95[{boots[100]:+.2f},{boots[3899]:+.2f}]  配对 {win}:{lose}")

# ⑤ 事后观察(非预注册):胜负两面同时偏 t7
print("\n⑤ ⚠️事后方向(非预注册):home+away 同时偏 t7")
for w in (0.75, 1.0):
    cand = {"home":w,"draw":0.5,"away":w}
    d2 = [brier(mix(r,base),r["actual"]) - brier(mix(r,cand),r["actual"]) for r in rows]
    m2 = sum(d2)/len(d2)/b0*100
    bs = sorted(sum(random.choice(d2) for _ in d2)/len(d2)/b0*100 for _ in range(4000))
    w_, l_ = sum(1 for x in d2 if x>1e-12), sum(1 for x in d2 if x<-1e-12)
    print(f"  w={w:.2f}  BSS {m2:+.2f}%  CI95[{bs[100]:+.2f},{bs[3899]:+.2f}]  配对 {w_}:{l_}")
