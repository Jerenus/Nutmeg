"""因子 1b —— 陈盘污染（F1 的反方向机制，重新预注册）。

**为什么重来一次。** F1 预注册的机制是「分歧度=共识置信度低→向均匀收缩」，
实测**方向相反**：分歧越大，大热开得越多（Q3 +8.2pp / Q4 +6.4pp，低分歧 Q1 −5.4pp），
且在四个 top1 档里全部存活（``corr(disp, top1)=0.143``，不是价格代理）。
我拒绝把「反着用」当成结论——那是事后择向。本文件改为**先给反方向一个机制，
再测它自己的可分辨预测**。

机制 F1b：分歧度不是置信度，是**陈盘占比**。不更新的软盘把共识往**开盘价**拖回去；
开盘价已实测更差（t7 开盘 Brier 0.5694 vs 终盘 0.5561）。因此高分歧 = 共识被污染。

三个可分辨的预注册预测：
  ① **陈盘半数**的共识比**新鲜半数**的共识更贴近开盘共识（这是「陈盘=持旧价」的定义性检验）
  ② 只用新鲜半数重算的共识，Brier 优于陈盘半数（**同等书目数**，排除样本量混杂）
  ③ ② 的增益在高分歧场最大

**否决线**：② 的 bootstrap CI 下界 ≤ 0；或 ① 方向相反；或 ③ 无单调。
"""
import json
import random
import statistics
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
DISP = json.load(open(Z / "t7-dispersion.json"))
RES = json.load(open(Z / "official-results.json"))
FACE = {"3": "home", "1": "draw", "0": "away"}
KEYS = ("home", "draw", "away")

rows = []
for issue, ms in DISP.items():
    if issue not in RES:
        continue
    out = RES[issue].split()
    if len(out) != 14:
        continue
    for no, c in ms.items():
        cons = c.get("consensus") or {}
        if not all(cons.get(k) for k in ("all", "fresh_half", "stale_half")):
            continue
        if not c.get("consensus_opening"):
            continue
        rows.append({"issue": issue, "no": no, "disp": c["current"]["dispersion"],
                     "cons": cons, "open": c["consensus_opening"],
                     "n": c.get("n_recent", {}),
                     "actual": FACE[out[int(no) - 1]]})
print(f"样本 n={len(rows)}  期={len({r['issue'] for r in rows})}")
if len(rows) < 100:
    raise SystemExit("样本不足，等采集完成再跑")
print(f"书目：全量中位 {statistics.median(r['n']['all'] for r in rows):.0f}，"
      f"新鲜半 {statistics.median(r['n']['fresh_half'] for r in rows):.0f}，"
      f"陈盘半 {statistics.median(r['n']['stale_half'] for r in rows):.0f}")


def dist(a, b):
    return sum(abs(a[k] - b[k]) for k in KEYS) / 2.0      # 总变差距离


print("\n① 陈盘半数是否更贴近开盘共识（机制的定义性检验）")
fresh_d = [dist(r["cons"]["fresh_half"], r["open"]) for r in rows]
stale_d = [dist(r["cons"]["stale_half"], r["open"]) for r in rows]
closer = sum(1 for f, s in zip(fresh_d, stale_d, strict=True) if s < f)
print(f"  新鲜半 距开盘 {statistics.fmean(fresh_d)*100:.2f}pp   "
      f"陈盘半 距开盘 {statistics.fmean(stale_d)*100:.2f}pp   "
      f"陈盘更近的场次 {closer}/{len(rows)} ({closer/len(rows)*100:.0f}%)")
ok1 = statistics.fmean(stale_d) < statistics.fmean(fresh_d)
print(f"  → 预测① {'✅成立' if ok1 else '❌方向相反'}")


def brier(p, a):
    return sum((p[k] - (1.0 if k == a else 0.0))**2 for k in KEYS)


print("\n② 新鲜半 vs 陈盘半（同等书目数）")
bf = statistics.fmean(brier(r["cons"]["fresh_half"], r["actual"]) for r in rows)
bs_ = statistics.fmean(brier(r["cons"]["stale_half"], r["actual"]) for r in rows)
ba = statistics.fmean(brier(r["cons"]["all"], r["actual"]) for r in rows)
bo = statistics.fmean(brier(r["open"], r["actual"]) for r in rows)
print(f"  开盘共识 {bo:.5f} │ 陈盘半 {bs_:.5f} │ 全量 {ba:.5f} │ 新鲜半 {bf:.5f}")
print(f"  BSS(新鲜半 vs 陈盘半) {(1-bf/bs_)*100:+.2f}%   "
      f"BSS(新鲜半 vs 全量) {(1-bf/ba)*100:+.2f}%")
random.seed(7)
dd = [brier(r["cons"]["stale_half"], r["actual"]) - brier(r["cons"]["fresh_half"], r["actual"])
      for r in rows]
boot = sorted(sum(random.choice(dd) for _ in dd) / len(dd) / bs_ * 100 for _ in range(4000))
w = sum(1 for x in dd if x > 1e-12)
print(f"  bootstrap CI95[{boot[100]:+.2f},{boot[3899]:+.2f}]  配对 {w}:{len(dd)-w}")
print(f"  → 闸：CI 下界 {'>0 ✅过闸' if boot[100] > 0 else '≤0 ❌不过闸'}")

print("\n③ 增益是否集中在高分歧场")
d = sorted(r["disp"] for r in rows)
cuts = [d[len(d) * i // 3] for i in (1, 2)]
cells = []
for b in range(3):
    sub = [r for r in rows if sum(1 for c in cuts if r["disp"] >= c) == b]
    if len(sub) < 20:
        continue
    f_ = statistics.fmean(brier(r["cons"]["fresh_half"], r["actual"]) for r in sub)
    s_ = statistics.fmean(brier(r["cons"]["stale_half"], r["actual"]) for r in sub)
    cells.append((1 - f_ / s_) * 100)
    print(f"  分歧 {'低中高'[b]}  n={len(sub):<4} BSS(新鲜 vs 陈盘) {(1-f_/s_)*100:+6.2f}%")
mono = len(cells) == 3 and (cells[2] > cells[1] > cells[0])
print(f"  → 预测③ {'✅单调递增' if mono else '❌不单调'}")

print("\n④ 可部署性：新鲜半 vs **生产在用的锐盘白名单共识**（6-7 家）")
T7 = json.load(open(Z / "t7-backfill.json"))
pairs = [(r, T7.get(r["issue"], {}).get(r["no"], {}).get("fair")) for r in rows]
pairs = [(r, f) for r, f in pairs if f]
print(f"   可比 n={len(pairs)}")
bsharp = statistics.fmean(brier(f, r["actual"]) for r, f in pairs)
bfresh = statistics.fmean(brier(r["cons"]["fresh_half"], r["actual"]) for r, _ in pairs)
ball = statistics.fmean(brier(r["cons"]["all"], r["actual"]) for r, _ in pairs)
bq = statistics.fmean(brier(r["cons"]["fresh_quarter"], r["actual"])
                      for r, _ in pairs if r["cons"].get("fresh_quarter"))
print(f"   锐盘白名单(生产) {bsharp:.5f} │ 全量 {ball:.5f} │ "
      f"新鲜半 {bfresh:.5f} │ 新鲜四分之一 {bq:.5f}")
print(f"   BSS(新鲜半 vs 锐盘白名单) {(1-bfresh/bsharp)*100:+.2f}%")
random.seed(7)
dd2 = [brier(f, r["actual"]) - brier(r["cons"]["fresh_half"], r["actual"])
       for r, f in pairs]
b2 = sorted(sum(random.choice(dd2) for _ in dd2)/len(dd2)/bsharp*100 for _ in range(4000))
w2 = sum(1 for x in dd2 if x > 1e-12)
print(f"   bootstrap CI95[{b2[100]:+.2f},{b2[3899]:+.2f}]  配对 {w2}:{len(dd2)-w2}")
verdict = ("✅可替换生产 prior 的 t7 侧" if b2[100] > 0
           else "❌不优于现有锐盘白名单，不换生产")
print(f"   → {verdict}")

print("\n⑤ 准入分档（沿用 zucai_loop 三档口径）")
se = (b2[3899] - b2[100]) / 2 / 1.96
mde80 = 2.80 * se
bss2 = statistics.fmean(dd2)/bsharp*100
print(f"   方向分 {w2/len(dd2)*100:.1f}  信息量 |BSS|/MDE80 = "
      f"{abs(bss2)/mde80 if mde80 else 0:.2f}  (MDE80={mde80:.2f}%)")
