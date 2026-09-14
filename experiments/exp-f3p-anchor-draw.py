"""因子 3 —— 锚方完整度 → **平局面**（而非胜面）。

**为什么重开这一题。** 2026-09-14 早些时候测过「完整度 PASS vs FAIL」，表面 49pp 的
差距在价格校正后归零——但那测的是**胜面**（锚方赢不赢）。价格把胜率调下去了，这一步
市场做得很好。

机制（先写死，再跑）：**脊柱受损不翻转胜者，它压缩净胜球**。中轴缺员让球队仍能控场、
仍是较强一方，但把大比分赢变成小比分赢、把小比分赢变成平。若市场只修正了「谁赢」
而没修足「赢多少」，错价就落在**平局面**上。

预测：``anchor_integrity=fail`` 的场次，平局面残差（实开平率 − fair 平均）为正。
**否决线**：价格分档后 |残差| < 5pp（加权残差框架的归零线），或 EB 收缩后归零。

⚠️选择偏差：9 腿票面的场次是主循环挑剩的（幸存者）。主分析只用 **14 腿全板文件**，
9 腿子集单列作对照。
"""
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
RES = json.load(open(Z / "official-results.json"))
FACE = {"3": "home", "1": "draw", "0": "away"}
FULL_BOARD = {"26107": "26107-legs-audit-S768.json", "26108": "26108-legs-audit-P14.json",
              "26109": "26109-legs-audit-P14.json", "26110": "26110-legs-audit-P14.json",
              "26111": "26111-legs-SFC486.json", "26112": "26112-legs-SFC256.json",
              "26113": "26113-legs-P14.json", "26118": "26118-legs-T1-SFC288.json",
              "26122": "26122-legs-T3.json", "26123": "26123-legs-base.json",
              "26124": "26124-legs-base.json"}
PARTIAL = {"26114": "26114-legs-U768.json", "26115": "26115-legs-R1-384.json",
           "26116": "26116-legs-B486.json", "26117": "26117-legs-K0-1728.json",
           "26119": "26119-legs-H1-1536.json", "26120": "26120-legs-H1-1152.json",
           "26121": "26121-legs-A-216.json", "26106": "26106-legs-audit-M864.json"}


def load(mapping):
    rows = []
    for issue, fname in mapping.items():
        path = Z / fname
        if not path.exists() or issue not in RES:
            continue
        outcomes = RES[issue].split()
        if len(outcomes) != 14:
            continue
        for no, leg in json.load(open(path)).get("legs", {}).items():
            ai = (leg or {}).get("anchor_integrity")
            fair = (leg or {}).get("fair")
            if ai in (None, "unknown") or not isinstance(fair, dict):
                continue
            if not all(k in fair for k in ("home", "draw", "away")):
                continue
            rows.append({"issue": issue, "no": no, "ai": ai, "fair": fair,
                         "actual": FACE[outcomes[int(no) - 1]]})
    return rows


def block(rows, label):
    print(f"\n{'='*66}\n{label}  n={len(rows)}")
    by = defaultdict(list)
    for r in rows:
        by[r["ai"]].append(r)
    print(f"{'完整度':12} {'n':>4} {'实开平':>7} {'fair平均':>8} {'残差':>8} "
          f"{'权重':>8}   胜面残差")
    for ai in sorted(by, key=lambda k: -len(by[k])):
        sub = by[ai]
        n = len(sub)
        act = sum(1 for r in sub if r["actual"] == "draw") / n
        exp = statistics.fmean(r["fair"]["draw"] for r in sub)
        resid = act - exp
        weight = resid * n / (n + 10)            # 加权残差框架的收缩
        # 对照：模态面（胜面）残差
        m_act = sum(1 for r in sub
                    if r["actual"] == max(r["fair"], key=r["fair"].get)) / n
        m_exp = statistics.fmean(max(r["fair"].values()) for r in sub)
        flag = "" if abs(weight) >= 0.05 else "  ←<5pp 归零"
        print(f"{ai:12} {n:>4} {act*100:>6.1f}% {exp*100:>7.1f}% "
              f"{resid*100:>+7.1f}pp {weight*100:>+7.1f}pp{flag}   "
              f"{(m_act-m_exp)*100:>+5.1f}pp")
    return by


def band_check(by, faces=("fail", "pass")):
    """价格分档：把平局面按 fair_draw 三分位切，看残差是否只是档位效应。"""
    print("\n价格分档（按 fair 平局值三分位），检验残差是否只是价格效应")
    allr = [r for k in faces if k in by for r in by[k]]
    if len(allr) < 30:
        print("  样本不足")
        return
    xs = sorted(r["fair"]["draw"] for r in allr)
    lo, hi = xs[len(xs)//3], xs[2*len(xs)//3]
    names = {0: f"低 (<{lo*100:.1f}%)", 1: "中", 2: f"高 (≥{hi*100:.1f}%)"}
    print(f"{'档':16} " + " ".join(f"{k:>18}" for k in faces))
    for b in (0, 1, 2):
        cells = []
        for k in faces:
            sub = [r for r in by.get(k, [])
                   if (0 if r["fair"]["draw"] < lo else 2 if r["fair"]["draw"] >= hi else 1) == b]
            if len(sub) < 8:
                cells.append(f"{'n='+str(len(sub)):>18}")
                continue
            a = sum(1 for r in sub if r["actual"] == "draw") / len(sub)
            e = statistics.fmean(r["fair"]["draw"] for r in sub)
            cells.append(f"{(a-e)*100:>+10.1f}pp n={len(sub):<3}")
        print(f"{names[b]:16} " + " ".join(cells))


def eb_shrink(by, tau=0.05):
    """经验贝叶斯收缩（τ=5pp 先验），与 F3 同一口径。"""
    print(f"\nEB 收缩（τ={tau*100:.0f}pp）")
    for ai in ("fail", "pass", "symmetric_damage"):
        sub = by.get(ai, [])
        if len(sub) < 10:
            continue
        n = len(sub)
        a = sum(1 for r in sub if r["actual"] == "draw") / n
        e = statistics.fmean(r["fair"]["draw"] for r in sub)
        se = math.sqrt(max(e * (1 - e), 1e-6) / n)
        k = tau**2 / (tau**2 + se**2)
        print(f"  {ai:18} 原始 {(a-e)*100:+6.1f}pp  SE {se*100:4.1f}pp  "
              f"收缩系数 {k:.2f}  → **{(a-e)*k*100:+6.1f}pp**")


main = load(FULL_BOARD)
by_main = block(main, "① 主分析：14 腿全板文件（无选择偏差）")
band_check(by_main)
eb_shrink(by_main)
part = load(PARTIAL)
block(part, "② 对照：9 腿票面文件（⚠️主循环挑剩的场次，有幸存者偏差）")
