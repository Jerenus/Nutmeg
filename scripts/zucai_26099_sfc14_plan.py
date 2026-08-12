"""胜负彩/任九 26099 组合优化（禁嘴算, Phase5）.

信念来自 14 场并行 jczq-match-analyst 深研 → 判决表落位（.tmp/26099-agents/*.md）。
脚本只做确定性算术：按判决表允许的表达级别（单/双/全包）枚举尺寸向量，
在注数帽内最大化 P14 / P9，并给期望断腿数。判断永不烤进脚本。

belief 主口径 = 国际盘去水 fair（agent 实查，抽水 5-7% 远低于体彩 12.9%）；
无国际盘的三场（12/13/14）退回体彩去水。体彩口径作敏感性对照。
"""
import json
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).parents[1]
FAIR = json.loads((ROOT / ".tmp/26099-fair.json").read_text())
SPORT = {int(k): v for k, v in FAIR["sporttery"].items()}
INTL = {int(k): v for k, v in FAIR["intl"].items()}
def _norm(v):
    t = sum(v)
    return [x / t for x in v]


BELIEF = {n: _norm(INTL.get(n, SPORT[n])) for n in range(1, 15)}

NAME = {1: "布鲁马-马尔默", 2: "哥德堡-代格福什", 3: "AIK-厄尔格里特", 4: "佐加顿斯-韦斯特罗斯",
        5: "哈尔姆-天狼星", 6: "奥勒松-特罗姆瑟", 7: "KFUM-克里斯蒂安松", 8: "莫尔德-萨尔普斯堡",
        9: "布兰-罗森博格", 10: "瓦萨-图尔库", 11: "AC奥卢-伊尔韦斯", 12: "SJK-赫尔辛基",
        13: "米拉索尔-格雷米奥", 14: "巴拉竞技-维多利亚"}
IDX = {"3": 0, "1": 1, "0": 2}

# 判决表允许级别：match_no -> [(faces...)] 压缩优先序，**最后一项 = 处方级**
# 每场的禁区已烤进级别表（禁止出现的面组合直接不列）
LEVELS = {
    # conf2 + 3方向性旗全指平 + 1无方向旗 + top1 43.2%<45% → 降格全包；被迫两面只许 3+0（禁 3 单选）
    1:  [("3", "0"), ("3", "1", "0")],
    # conf3 禁单选；处方=模态3+旗面1；回退全包
    2:  [("3", "1"), ("3", "1", "0")],
    # conf4 + 0 无方向旗 + fair≥60% → m条允许单选；保险档 31
    3:  [("3",), ("3", "1")],
    # conf3 禁单选 → 31（0 旗但 conf3 硬禁）
    4:  [("3", "1"), ("3", "1", "0")],
    # conf4 + 0 旗 + fair≥60% → 单选 0；降格线=Ure 不首发→双选 0+1
    5:  [("0",), ("0", "1")],
    # conf2 + 两条方向相反的方向性旗 + top1 49.5% → 双选 模态客+旗面平
    6:  [("0", "1"), ("3", "1", "0")],
    # conf3 + self_made_tail(→平) → 31
    7:  [("3", "1"), ("3", "1", "0")],
    # conf3 + two_way_instability(无方向旗) → 降格全包；被迫两面 3+1（砍 0）
    8:  [("3", "1"), ("3", "1", "0")],
    # conf3 + 0 旗 → 双选，第二面按 fair 序取客；fallback 31（差 1.2-3.1pp 噪音带内）
    9:  [("3", "0"), ("3", "1"), ("3", "1", "0")],
    # conf2 + top1 36.6%<45% → 降格全包；被迫两面 31（**禁 3+0 弃平**）
    10: [("3", "1"), ("3", "1", "0")],
    # conf2 + source_disagreement(无方向旗) + top1 41.8%<45% 双触发 → 降格全包；
    # 被迫两面 30（**禁 31**：31 盖第3项露第2项 = 26093 同队同主场应验过的反向隔壁陷阱）
    11: [("3", "0"), ("3", "1", "0")],
    # conf3 + 0 旗 → 双选 模态客+主（弃平，高 λ 盘压低平局占比）
    12: [("0", "3"), ("3", "1", "0")],
    # conf3 + dressing_room_turmoil(无方向旗) → 降格全包；被迫两面 31
    13: [("3", "1"), ("3", "1", "0")],
    # conf3 + 2条方向性旗(→平) + fair 59.8%<60% → 31
    14: [("3", "1"), ("3", "1", "0")],
}
# 处方级显式声明（不能由 LEVELS 位置推导：场3/场5 的处方恰是"单选"，双选反而是降格回退）
PRESCRIPTION = {
    1: ("3", "1", "0"), 2: ("3", "1"), 3: ("3",), 4: ("3", "1"), 5: ("0",),
    6: ("0", "1"), 7: ("3", "1"), 8: ("3", "1", "0"), 9: ("3", "0"),
    10: ("3", "1", "0"), 11: ("3", "1", "0"), 12: ("0", "3"),
    13: ("3", "1", "0"), 14: ("3", "1"),
}


def cov(no, faces, belief=None):
    b = (belief or BELIEF)[no]
    return sum(b[IDX[f]] for f in faces)


def enum_best(matches, cap_bets, belief=None):
    """在注数帽内枚举各场级别，最大化 P(全中)。返回 (P, alloc, bets)"""
    opts = [[(len(f), cov(m, f, belief), f) for f in LEVELS[m]] for m in matches]
    best = None

    def dfs(i, bets, p, alloc):
        nonlocal best
        if bets > cap_bets:
            return
        if i == len(matches):
            if best is None or p > best[0]:
                best = (p, list(alloc), bets)
            return
        for size, c, f in opts[i]:
            alloc.append((matches[i], f))
            dfs(i + 1, bets * size, p * c, alloc)
            alloc.pop()

    dfs(0, 1, 1.0, [])
    return best


def ebl(alloc, belief=None):
    return sum(1 - cov(m, f, belief) for m, f in alloc)


def show(title, alloc, p, bets, belief=None):
    print(f"\n=== {title} ===")
    print(f"注数 {bets} = ¥{bets*2}  |  P(全中) {p*100:.3f}%  |  期望断腿 {ebl(alloc, belief):.2f}")
    for m, f in alloc:
        c = cov(m, f, belief)
        pres = "" if f == PRESCRIPTION[m] else f"  ← 压缩(处方 {''.join(PRESCRIPTION[m])})"
        print(f"  {m:>2} {NAME[m]:<20} {''.join(f):<4} 盖 {c*100:5.1f}%{pres}")


ALL = list(range(1, 15))

MIN_BETS = 1
for n in ALL:
    MIN_BETS *= min(len(f) for f in LEVELS[n])
print(f"### S1 判决表【最低合规级别】注数 = {MIN_BETS} 注 = ¥{MIN_BETS*2}")
print("    （= 每场都取本场允许的最窄表达；再窄就要违规裸单）\n")

print("### 判决表处方（未压缩）")
full_bets = 1
for n in ALL:
    full_bets *= len(PRESCRIPTION[n])
full_alloc = [(n, PRESCRIPTION[n]) for n in ALL]
full_p = 1.0
for n, f in full_alloc:
    full_p *= cov(n, f)
show("S1 处方级胜负彩（不压缩）", full_alloc, full_p, full_bets)
print(f"\n>>> 期望断腿 {ebl(full_alloc):.2f} —— 分流规则红线 2.0")

print("\n\n### 胜负彩 S1 在各注数帽下的最优压缩")
for cap in (162, 324, 512, 800):
    b = enum_best(ALL, cap)
    if b:
        show(f"S1 ≤{cap}注 (¥{cap*2})", b[1], b[0], b[2])

print("\n\n### 任九 R9：枚举所有 C(14,9)=2002 组合 × 级别，各注数帽下最大 P9")
for cap in (216, 324, 486, 648, 800):
    best = None
    for combo in combinations(ALL, 9):
        r = enum_best(list(combo), cap)
        if r and (best is None or r[0] > best[0]):
            best = (r[0], r[1], r[2], combo)
    if best:
        drop = [n for n in ALL if n not in best[3]]
        show(f"R9 ≤{cap}注 (¥{cap*2})  丢 {drop}", best[1], best[0], best[2])

print("\n\n### 敏感性：改用体彩去水口径重算处方级")
p2 = 1.0
for n, f in full_alloc:
    p2 *= cov(n, f, SPORT)
print(f"处方级 P14 体彩口径 {p2*100:.3f}% (国际口径 {full_p*100:.3f}%)，期望断腿 {ebl(full_alloc, SPORT):.2f}")
