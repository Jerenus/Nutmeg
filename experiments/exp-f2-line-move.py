"""因子 2 —— 让球线的**离散位移**（初盘 → 终盘）。

机制（先写死，再跑）：**改赔率**是连续微调、成本近零；**改线**是把标的换成另一个
离散档位，是一次承诺。已证伪的「位移动量」（2026-09-15 两轮，扩样后符号翻转）测的
是赔率漂移；本因子测的是**线本身是否跨档**——两者不是同一个量。

预注册预测：线朝主队方向移动（``line_move>0``，主队让得更多）→ **主胜面残差为正**，
且该信息**未被终盘欧赔完全吸收**（残差相对 t7 终盘共识计算）。
辅助变量：``moved_share`` = 改线书商占比 = 承诺强度。

**否决线**：加权残差 <5pp；或分档不单调（机制检验②）；或 bootstrap CI 含 0。
"""
import json
import random
import statistics
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
HC = json.load(open(Z / "t7-handicap.json"))
T7 = json.load(open(Z / "t7-backfill.json"))
RES = json.load(open(Z / "official-results.json"))
FACE = {"3": "home", "1": "draw", "0": "away"}
KEYS = ("home", "draw", "away")

rows = []
for issue, ms in HC.items():
    if issue not in RES:
        continue
    out = RES[issue].split()
    if len(out) != 14:
        continue
    for no, c in ms.items():
        fair = T7.get(issue, {}).get(no, {}).get("fair")
        if not fair:
            continue
        rows.append({"issue": issue, "no": no, "fair": fair,
                     "move": c["line_move"], "moved_share": c["moved_share"],
                     "open": c["opening_median"], "close": c["closing_median"],
                     "actual": FACE[out[int(no) - 1]]})
print(f"样本 n={len(rows)}  期={len({r['issue'] for r in rows})}")
mv = [r["move"] for r in rows]
print(f"线位移分布：不动 {sum(1 for x in mv if x==0)}／"
      f"向主 {sum(1 for x in mv if x>0)}／向客 {sum(1 for x in mv if x<0)}；"
      f"|位移|最大 {max(abs(x) for x in mv)}")


def resid(sub, face):
    act = sum(1 for r in sub if r["actual"] == face) / len(sub)
    exp = statistics.fmean(r["fair"][face] for r in sub)
    return act - exp, act, exp


print("\n① 按线位移分档 × 主胜面残差（预注册：向主移动 → 主胜残差为正）")
print(f"{'位移档':16} {'n':>4} {'主胜期望':>8} {'主胜实开':>8} {'残差':>9} {'权重':>9}")
buckets = [("向客 ≤-0.25", lambda x: x <= -0.25), ("不动 0", lambda x: x == 0),
           ("向主 +0.25", lambda x: 0 < x <= 0.25), ("向主 ≥+0.5", lambda x: x >= 0.5)]
cells = []
for label, fn in buckets:
    sub = [r for r in rows if fn(r["move"])]
    if len(sub) < 12:
        print(f"{label:16} {len(sub):>4}   样本不足")
        continue
    r_, a_, e_ = resid(sub, "home")
    w_ = r_ * len(sub) / (len(sub) + 10)
    cells.append(r_)
    flag = "" if abs(w_) >= 0.05 else "  ←<5pp 归零"
    print(f"{label:16} {len(sub):>4} {e_*100:>7.1f}% {a_*100:>7.1f}% "
          f"{r_*100:>+8.1f}pp {w_*100:>+8.1f}pp{flag}")

if len(cells) >= 3:
    diffs = [cells[i+1] - cells[i] for i in range(len(cells)-1)]
    same = max(sum(1 for x in diffs if x > 0), sum(1 for x in diffs if x < 0))
    span = abs(cells[-1] - cells[0])
    peak = max(abs(c) for c in cells)
    trend_ok = same >= 2 * len(diffs) / 3 and span >= peak
    print(f"\n机制检验②真趋势：同向 {same}/{len(diffs)}，跨度 {span*100:.1f}pp vs "
          f"最大|残差| {peak*100:.1f}pp → "
          f"{'通过' if trend_ok else '❌不通过'}")

print("\n② 承诺强度（改线书商占比）× 模态面残差")
ms = sorted(r["moved_share"] for r in rows)
cuts = [ms[len(ms)*i//3] for i in (1, 2)]
for b in range(3):
    sub = [r for r in rows if sum(1 for c in cuts if r["moved_share"] >= c) == b]
    if len(sub) < 20:
        continue
    act = sum(1 for r in sub if r["actual"] == max(r["fair"], key=r["fair"].get)) / len(sub)
    exp = statistics.fmean(max(r["fair"].values()) for r in sub)
    med = statistics.median(r["moved_share"] for r in sub)
    print(f"  改线占比{'低中高'[b]}  n={len(sub):<4} 中位 {med:.2f}"
          f"  top1 残差 {(act-exp)*100:>+6.1f}pp")


def brier(p, a):
    return sum((p[k] - (1.0 if k == a else 0.0))**2 for k in KEYS)


print("\n③ 把线位移做成偏移策略（每 0.25 线位移给主胜 k pp）并扫描")
b0 = statistics.fmean(brier(r["fair"], r["actual"]) for r in rows)
best = None
for k in (0.0, 0.01, 0.02, 0.03, 0.05, -0.02, -0.05):
    tot = 0.0
    for r in rows:
        shift = k * (r["move"] / 0.25)
        p = {"home": r["fair"]["home"] + shift, "draw": r["fair"]["draw"],
             "away": r["fair"]["away"] - shift}
        p = {x: max(0.001, v) for x, v in p.items()}
        s = sum(p.values())
        tot += brier({x: v/s for x, v in p.items()}, r["actual"])
    b = tot / len(rows)
    bss = (1 - b/b0) * 100
    print(f"  k={k:+.2f}  BSS {bss:+.2f}%")
    if best is None or bss > best[1]:
        best = (k, bss)
k = best[0]
if k != 0.0:
    random.seed(7)
    dd = []
    for r in rows:
        shift = k * (r["move"] / 0.25)
        p = {"home": max(.001, r["fair"]["home"]+shift), "draw": r["fair"]["draw"],
             "away": max(.001, r["fair"]["away"]-shift)}
        s = sum(p.values())
        shifted = {x: v / s for x, v in p.items()}
        dd.append(brier(r["fair"], r["actual"]) - brier(shifted, r["actual"]))
    boot = sorted(sum(random.choice(dd) for _ in dd)/len(dd)/b0*100 for _ in range(4000))
    print(f"\n  最优 k={k:+.2f}：BSS {statistics.fmean(dd)/b0*100:+.2f}% "
          f"CI95[{boot[100]:+.2f},{boot[3899]:+.2f}]")
    print(f"  闸：CI 下界 {'>0 ✅过闸' if boot[100] > 0 else '≤0 ❌不过闸'}")
else:
    print("\n  最优 k=0 → 线位移不带可用信息，不过闸")

print("\n④ ⚠️混杂控制：`向主≥+0.5` 档 top1 期望 65.7%——正是 F3（top1≥60）的地盘。")
print("   分离检验：在**固定 top1 档**内，线位移是否还带信息？")
print(f"{'top1 档':14} " + "".join(f"{b:>20}" for b, _ in
      [('线不动/向客',0), ('线向主',0)]))
for lo, hi in ((0, .45), (.45, .60), (.60, 1.01)):
    cells = []
    for is_up in (False, True):
        sub = [r for r in rows if lo <= max(r["fair"].values()) < hi
               and (r["move"] > 0) == is_up]
        if len(sub) < 15:
            cells.append(f"{'n='+str(len(sub)):>20}")
            continue
        a = sum(1 for r in sub if r["actual"] == max(r["fair"], key=r["fair"].get))/len(sub)
        e = statistics.fmean(max(r["fair"].values()) for r in sub)
        cells.append(f"n={len(sub):<4}{(a-e)*100:>+8.1f}pp{'':4}")
    print(f"[{lo*100:.0f},{hi*100:.0f})%{'':6} " + "".join(cells))

print("\n   corr(|线位移|, top1) =",
      round(statistics.correlation([abs(r['move']) for r in rows],
                                   [max(r['fair'].values()) for r in rows]), 3))
print("   corr(线位移, top1) =",
      round(statistics.correlation([r['move'] for r in rows],
                                   [max(r['fair'].values()) for r in rows]), 3))
