"""胜负彩 26095 复式覆盖优化 + 平局位置审计 + 翻面-vs-加宽对比 + 任九构造（禁嘴算, Phase 5）.

信念来自 .nutmeg-data/zucai/26095-reads.json（14 场并行 jczq-match-analyst 深研
→ 主循环判读落 Read：1 条偏移[场14] + 13 条跟市场）。脚本只做确定性算术：
3^14 尺寸向量全枚举最大化 P(14中)、二等 P(≥13)、平局位置审计、翻面(收单)与
加宽(扩列)的等预算对比、任九选9构造。判断永不烤进脚本。
"""
import json
from itertools import product
from pathlib import Path

ROOT = Path(__file__).parents[1]
READS = json.loads((ROOT / ".nutmeg-data/zucai/26095-reads.json").read_text())

NAMES = {
 1: "代格福什vs佐加顿斯", 2: "卡尔马vs米亚尔比", 3: "克里斯vs斯达",
 4: "玛丽港vsAC奥卢", 5: "库奥皮奥vs瓦萨", 6: "巴拉竞vs巴国际",
 7: "桑托斯vs沙佩科", 8: "达伽马vs米拉索", 9: "纽红牛vs夏洛特",
 10: "休斯敦vs奥斯汀", 11: "明尼苏vs温哥华", 12: "圣路易vs科罗拉",
 13: "圣迭戈vs达拉斯", 14: "圣何塞vs洛银河",
}
KEYS = ["home", "draw", "away"]
SYM = {"home": "3", "draw": "1", "away": "0"}

belief = {}
for r in READS:
    no = int(r["read_id"].rsplit("-", 1)[1])
    b = r["belief"]
    total = sum(b.values())
    belief[no] = {k: b[k] / total for k in KEYS}

MATCHES = sorted(belief)
BUDGET_BETS = 200  # ¥400 / ¥2

def best_subset(no, size):
    ordered = sorted(KEYS, key=lambda k: -belief[no][k])
    return tuple(ordered[:size])

def subset_p(no, subset):
    return sum(belief[no][k] for k in subset)

def optimize(cap, overrides=None):
    """overrides: {no: 固定子集}（判断层裁定）; 其余场按尺寸取最优子集."""
    overrides = overrides or {}
    free = [n for n in MATCHES if n not in overrides]
    base_bets = 1
    for n in overrides:
        base_bets *= len(overrides[n])
    best = None
    for sizes in product((1, 2, 3), repeat=len(free)):
        bets = base_bets
        for s in sizes:
            bets *= s
            if bets > cap:
                break
        if bets > cap:
            continue
        p = 1.0
        for n in overrides:
            p *= subset_p(n, overrides[n])
        for n, s in zip(free, sizes):
            p *= subset_p(n, best_subset(n, s))
        if best is None or p > best[0]:
            best = (p, dict(zip(free, sizes)), bets)
    p, szmap, bets = best
    alloc = dict(overrides)
    for n, s in szmap.items():
        alloc[n] = best_subset(n, s)
    return alloc, bets

def p_at_least_13(alloc):
    cover = [subset_p(no, alloc[no]) for no in MATCHES]
    p14 = 1.0
    for c in cover:
        p14 *= c
    p13 = 0.0
    for i, c in enumerate(cover):
        term = (1 - c)
        for j, c2 in enumerate(cover):
            if j != i:
                term *= c2
        p13 += term
    return p14, p14 + p13

def show(tag, alloc, bets):
    p14, p13p = p_at_least_13(alloc)
    print(f"\n== {tag} == {bets}注 ¥{bets*2} | P(14中)={p14:.3%} | P(≥13中)={p13p:.3%}")
    print("  票面 " + " ".join(f"{n}:{''.join(SYM[k] for k in alloc[n])}" for n in MATCHES))
    for no in MATCHES:
        sub = alloc[no]
        pv = " ".join(f"{SYM[k]}={belief[no][k]:.0%}" for k in KEYS)
        print(f"  {no:>2} {NAMES[no]:<12s} 盖[{''.join(SYM[k] for k in sub)}] "
              f"盖率{subset_p(no, sub):.0%} | {pv}")
    return p14, p13p

# ---- 初稿：命中优先, ¥400 硬顶 3^14 全枚举 ----
alloc_opt, bets_opt = optimize(BUDGET_BETS)
show("初稿·命中优先(≤200注)", alloc_opt, bets_opt)

# ---- 备选注数档 ----
print("\n== 备选注数档（同信念,纯最优） ==")
tier_allocs = {}
for cap in (162, 128, 96, 64, 48, 32):
    a2, b2 = optimize(cap)
    p14b, p13b = p_at_least_13(a2)
    tier_allocs[cap] = (a2, b2)
    picks = " ".join(f"{n}:{''.join(SYM[k] for k in a2[n])}" for n in MATCHES)
    print(f"  ≤{cap:>3}注 → {b2:>3}注 ¥{b2*2:<4} P(14)={p14b:.3%} P(≥13)={p13b:.3%}")
    print(f"      {picks}")

# ---- 平局位置审计（26093 沉淀：平局预算必须盖最贵的平） ----
print("\n== 平局位置审计（初稿） ==")
draw_rank = sorted(MATCHES, key=lambda n: -belief[n]["draw"])
covered = {n for n in MATCHES if "draw" in alloc_opt[n]}
for rank, n in enumerate(draw_rank, 1):
    mark = "✅盖" if n in covered else "❌露"
    sz = len(alloc_opt[n])
    print(f"  第{rank:>2}贵的平: 场{n:>2} {NAMES[n]:<12s} 平={belief[n]['draw']:.1%} {mark} (尺寸{sz})")

# ---- 翻面 vs 加宽：逐场"收窄成本"表 ----
# 对每场: 单选(模态)盖率 / 双选盖率 / 全包=1。收窄一场双选→单选省一半列,
# 损失盖率比 = 单/双。列出最"便宜"可收窄的场（损失最小）与最"贵"必须加宽的场。
print("\n== 翻面/收窄成本表（盖率损失比,越高越适合收成单选） ==")
rows = []
for n in MATCHES:
    s1 = subset_p(n, best_subset(n, 1))
    s2 = subset_p(n, best_subset(n, 2))
    rows.append((s1 / s2, n, s1, s2))
for ratio, n, s1, s2 in sorted(rows, reverse=True):
    d2 = "".join(SYM[k] for k in best_subset(n, 2))
    d1 = SYM[best_subset(n, 1)[0]]
    print(f"  场{n:>2} {NAMES[n]:<12s} 单[{d1}]{s1:.0%} / 双[{d2}]{s2:.0%} → 保留比 {ratio:.2f}")

# ---- 判断层结构对比：等预算下的翻面(收单)+容纳度(全包硬币)变体 ----
print("\n== 等预算结构对比（判断层候选,由主循环裁定采纳与否） ==")
VARIANTS = [
    ("V1 收2场中锚双→单,全包场2",  {2: tuple(KEYS)}, 200),
    ("V2 收窄,全包场2+场9",       {2: tuple(KEYS), 9: tuple(KEYS)}, 200),
    ("V3 收窄,全包场2+场13",      {2: tuple(KEYS), 13: tuple(KEYS)}, 200),
    ("V4 收窄,全包场2+场9+场13",  {2: tuple(KEYS), 9: tuple(KEYS), 13: tuple(KEYS)}, 200),
    ("V5 场13双选排平[30]",       {13: ("home", "away")}, 200),
]
for tag, ov, cap in VARIANTS:
    a, b = optimize(cap, overrides=ov)
    p14v, p13v = p_at_least_13(a)
    picks = " ".join(f"{n}:{''.join(SYM[k] for k in a[n])}" for n in MATCHES)
    print(f"  {tag}: {b}注 ¥{b*2} P(14)={p14v:.3%} P(≥13)={p13v:.3%}")
    print(f"      {picks}")

# ---- 任九·选9（丢 5 场最发散） ----
print("\n== 任九·选9 ==")
spread = sorted(MATCHES, key=lambda n: subset_p(n, best_subset(n, 2)))
drops = spread[:5]
keeps = [n for n in MATCHES if n not in drops]
print(f"  丢(双选盖率最低5场): {sorted(drops)} | keep: {keeps}")
for cap in (243, 192, 128, 64, 32, 1):
    b3 = None
    for sizes in product((1, 2, 3), repeat=9):
        bets = 1
        ok = True
        for s in sizes:
            bets *= s
            if bets > cap:
                ok = False
                break
        if not ok:
            continue
        p = 1.0
        for no, s in zip(keeps, sizes):
            p *= subset_p(no, best_subset(no, s))
        if b3 is None or p > b3[0]:
            b3 = (p, sizes, bets)
    p3, sizes3, bets3 = b3
    picks = " ".join(
        f"{n}:{''.join(SYM[k] for k in best_subset(n, s))}"
        for n, s in zip(keeps, sizes3))
    print(f"  ≤{cap:>3}注 → {bets3:>3}注 ¥{bets3*2:<4} P(9场全中)={p3:.2%}")
    print(f"      {picks}")

# ---- 落 judgment json（初稿口径,终稿由主循环判读后更新） ----
out = {
    "issue": "26095",
    "made_at": "2026-07-25",
    "method": "14场并行jczq-match-analyst深研+500.com 51家欧赔均值去水锚+1条偏移Read(场14 lineup_absence_gap/venue_neutralization/h2h_away_form)+3^14全枚举覆盖优化",
    "sale_stop": "2026-07-25 20:30 CST",
    "belief": {str(n): [round(belief[n][k], 4) for k in KEYS] for n in MATCHES},
    "draft_optimal": {
        "bets": bets_opt, "stake_yuan": bets_opt * 2,
        "p14": round(p_at_least_13(alloc_opt)[0], 5),
        "alloc": {str(n): "".join(SYM[k] for k in alloc_opt[n]) for n in MATCHES},
    },
}
(ROOT / ".nutmeg-data/zucai/26095-judgment.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print("\njudgment json written (draft).")
