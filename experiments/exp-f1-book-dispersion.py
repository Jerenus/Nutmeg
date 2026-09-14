"""因子 1 —— 书商分歧度（连续量）。

机制（先写死，再跑）：分歧度是**共识置信度**的度量，**不是价格的函数**。150 家书商
的模型与敞口不一致时，共识点估计的信息量低，真实分布比共识声称的更宽 →
三面应向均匀收缩：**大热被高估、冷门与平局被低估**。

现有 RULEBOOK 里最接近的是「旗-无方向」词典的 `盘源分歧≥3pp`：那是**体彩 vs 国际
两源**的二值旗，只驱动动作（降格全包），从未量成概率残差。本因子问的是另一件事：
**同一时刻 150 家书商彼此差多少**。

预注册预测：按分歧度分档，高分歧档的 **top1 残差为负**，低分歧档接近 0。
**否决线**：档间不单调（机制检验②真趋势），或最优收缩策略 BSS 的 CI 下界 ≤ 0。
"""
import json
import random
import statistics
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
DISP = json.load(open(Z / "t7-dispersion.json"))
T7 = json.load(open(Z / "t7-backfill.json"))
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
    for no, cell in ms.items():
        base = T7.get(issue, {}).get(no, {}).get("fair")
        if not base:
            continue
        rows.append({"issue": issue, "no": no, "fair": base,
                     "disp": cell["current"]["dispersion"],
                     "n_books": cell["current"]["n_books"],
                     "actual": FACE[out[int(no) - 1]]})
print(f"样本 n={len(rows)}  期={len({r['issue'] for r in rows})}  "
      f"书目中位={statistics.median(r['n_books'] for r in rows):.0f}")

d = sorted(r["disp"] for r in rows)
cuts = [d[len(d) * i // 4] for i in (1, 2, 3)]
print(f"分歧度四分位切点: {[f'{c*100:.2f}pp' for c in cuts]}")


def band(x):
    return sum(1 for c in cuts if x >= c)


print("\n① 分歧度分档 × top1 残差（预注册预测：高档为负）")
print(f"{'档':6} {'n':>4} {'分歧中位':>9} {'top1 期望':>9} {'top1 实开':>9} {'残差':>9}"
      f"  {'平局残差':>9}")
cells = []
for b in range(4):
    sub = [r for r in rows if band(r["disp"]) == b]
    if not sub:
        continue
    exp = statistics.fmean(max(r["fair"].values()) for r in sub)
    act = sum(1 for r in sub
              if r["actual"] == max(r["fair"], key=r["fair"].get)) / len(sub)
    dexp = statistics.fmean(r["fair"]["draw"] for r in sub)
    dact = sum(1 for r in sub if r["actual"] == "draw") / len(sub)
    cells.append(act - exp)
    print(f"Q{b+1:<5} {len(sub):>4} {statistics.median(r['disp'] for r in sub)*100:>8.2f}pp"
          f" {exp*100:>8.1f}% {act*100:>8.1f}% {(act-exp)*100:>+8.1f}pp"
          f"  {(dact-dexp)*100:>+8.1f}pp")

diffs = [cells[i+1] - cells[i] for i in range(len(cells)-1)]
same = max(sum(1 for x in diffs if x > 0), sum(1 for x in diffs if x < 0))
span = abs(cells[-1] - cells[0])
ok2 = same >= 2 and span >= max(abs(c) for c in cells)
print(f"\n机制检验②真趋势：相邻差分同向 {same}/{len(diffs)}，首尾跨度 "
      f"{span*100:.1f}pp vs 最大|残差| {max(abs(c) for c in cells)*100:.1f}pp → "
      f"{'通过' if ok2 else '❌不通过'}")


def brier(p, a):
    return sum((p[k] - (1.0 if k == a else 0.0))**2 for k in KEYS)


def shrink(fair, disp, k):
    """按分歧度向均匀收缩：disp 越大，越往 1/3 拉。"""
    lam = min(1.0, k * disp)
    p = {x: (1 - lam) * fair[x] + lam / 3.0 for x in KEYS}
    s = sum(p.values())
    return {x: v / s for x, v in p.items()}


b0 = statistics.fmean(brier(r["fair"], r["actual"]) for r in rows)
print(f"\n② 按分歧度收缩扫描（基线 = t7 锐盘共识，Brier {b0:.5f}）")
best = None
for k in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0):
    b = statistics.fmean(brier(shrink(r["fair"], r["disp"], k), r["actual"])
                         for r in rows)
    bss = (1 - b / b0) * 100
    print(f"  k={k:<4} λ中位={min(1.0, k*statistics.median(r['disp'] for r in rows)):.3f}"
          f"  BSS {bss:+.2f}%")
    if best is None or bss > best[1]:
        best = (k, bss)

k, _ = best
random.seed(7)
dd = [brier(r["fair"], r["actual"]) - brier(shrink(r["fair"], r["disp"], k), r["actual"])
      for r in rows]
bs = sorted(sum(random.choice(dd) for _ in dd) / len(dd) / b0 * 100 for _ in range(4000))
w = sum(1 for x in dd if x > 1e-12)
print(f"\n③ 最优 k={k}：BSS {statistics.fmean(dd)/b0*100:+.2f}% "
      f"CI95[{bs[100]:+.2f},{bs[3899]:+.2f}]  配对 {w}:{len(dd)-w}")
print(f"   闸：CI 下界 {'>0 → 可入候选' if bs[100] > 0 else '≤0 → 不过闸'}")
