"""胜负彩 26094 复式覆盖优化 + 平局位置审计 + 任九构造算术（禁嘴算, Phase 5）.

信念来自 .nutmeg-data/zucai/26094-reads.json（14 场并行 jczq-match-analyst 深研
→ 主循环判读落 Read：4 条偏移 + 10 条跟市场）。脚本只做确定性算术：
3^14 尺寸向量全枚举最大化 P(14中)、二等 P(≥13)、平局位置审计、等成本换位对比、
任九选9构造。判断永不烤进脚本。
"""
import json
from itertools import product
from pathlib import Path

ROOT = Path(__file__).parents[1]
READS = json.loads((ROOT / ".nutmeg-data/zucai/26094-reads.json").read_text())

NAMES = {
 1: "萨巴赫vs库奥皮奥", 2: "奥胡斯vs波兹南", 3: "格拉茨vs哈茨",
 4: "哈马比vs安德莱", 5: "贝西克vs中日兰", 6: "特温特vs费伦茨",
 7: "圣加仑vs本菲卡", 8: "博德vs汉坎", 9: "利勒斯vs维京",
 10: "米内罗vs巴伊亚", 11: "沙佩科vs弗拉门", 12: "圣保罗vs巴拉竞",
 13: "博塔弗vs维多利", 14: "科林蒂vs里莫",
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

# ---- 3^14 尺寸向量全枚举（每尺寸取该场最优子集）----
best = None
for sizes in product((1, 2, 3), repeat=14):
    bets = 1
    for s in sizes:
        bets *= s
        if bets > BUDGET_BETS:
            break
    if bets > BUDGET_BETS:
        continue
    p = 1.0
    for no, s in zip(MATCHES, sizes):
        p *= subset_p(no, best_subset(no, s))
    if best is None or p > best[0]:
        best = (p, sizes, bets)

p_opt, sizes_opt, bets_opt = best

def render(sizes, overrides=None):
    """overrides: {no: subset} 结构性覆盖替换（判断层裁定, 等尺寸）."""
    overrides = overrides or {}
    alloc, p, bets = {}, 1.0, 1
    for no, s in zip(MATCHES, sizes):
        sub = overrides.get(no, best_subset(no, s))
        assert len(sub) == s
        alloc[no] = sub
        p *= subset_p(no, sub)
        bets *= s
    return alloc, p, bets

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

def show(tag, alloc, p, bets):
    p14, p13p = p_at_least_13(alloc)
    print(f"\n== {tag} == {bets}注 ¥{bets*2} | P(14中)={p14:.3%} | P(≥13中)={p13p:.3%}")
    row = []
    for no in MATCHES:
        picks = "".join(SYM[k] for k in alloc[no])
        row.append(f"{no}:{picks}")
    print("  票面 " + " ".join(row))
    for no in MATCHES:
        sub = alloc[no]
        pv = " ".join(f"{SYM[k]}={belief[no][k]:.0%}" for k in KEYS)
        print(f"  {no:>2} {NAMES[no]:<10s} 盖[{''.join(SYM[k] for k in sub)}] "
              f"盖率{subset_p(no, sub):.0%} | {pv}")

alloc_opt, p_chk, _ = render(sizes_opt)
show("纯最优(信念口径)", alloc_opt, p_opt, bets_opt)

# ---- 平局位置审计（26093 沉淀：平局预算必须盖最贵的平）----
print("\n== 平局位置审计 ==")
draw_rank = sorted(MATCHES, key=lambda n: -belief[n]["draw"])
covered = {n for n in MATCHES if "draw" in alloc_opt[n]}
for rank, n in enumerate(draw_rank, 1):
    mark = "✅盖" if n in covered else "❌露"
    print(f"  第{rank:>2}贵的平: 场{n:>2} {NAMES[n]:<10s} 平={belief[n]['draw']:.1%} {mark}")
exposed_expensive = [n for n in draw_rank[: len(covered)] if n not in covered]
if exposed_expensive:
    print(f"  ⚠️ 错配: 更贵的平被裸露 {exposed_expensive}（等成本换位候选）")
else:
    print("  ✅ 覆盖格与平局价格序对齐（前缀性质成立）")

# ---- 结构性替换对比（判断层裁定项的代价核算）----
print("\n== 结构性替换对比（等注数） ==")
for no, sub, why in [
    (4, ("home", "draw"), "场4改31(弃客保平): 分析员'双30=最差格'裁定 vs 信念 away>draw"),
    (9, ("away", "draw"), "场9改10(维京不败): 分析员方向倾斜 vs 两队零平体质双30"),
]:
    if len(alloc_opt.get(no, ())) == 2:
        alt = dict(alloc_opt)
        alt[no] = sub
        p14a, p13a = p_at_least_13(alt)
        p14o, _ = p_at_least_13(alloc_opt)
        print(f"  {why}: P(14) {p14o:.3%} → {p14a:.3%} (Δ{(p14a-p14o)/p14o:+.1%})")
    else:
        print(f"  场{no} 当前尺寸非双选, 无需对比")

# ---- 备选缩水结构 ----
print("\n== 备选注数档 ==")
for cap in (128, 96, 64):
    b2 = None
    for sizes in product((1, 2, 3), repeat=14):
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
        for no, s in zip(MATCHES, sizes):
            p *= subset_p(no, best_subset(no, s))
        if b2 is None or p > b2[0]:
            b2 = (p, sizes, bets)
    alloc2, _, bets2 = render(b2[1])
    p14b, p13b = p_at_least_13(alloc2)
    picks = " ".join(f"{n}:{''.join(SYM[k] for k in alloc2[n])}" for n in MATCHES)
    print(f"  ≤{cap}注 → {bets2}注 ¥{bets2*2} P(14)={p14b:.3%} P(≥13)={p13b:.3%}")
    print(f"    {picks}")

# ---- 任九 选9构造（丢 5 场最发散） ----
print("\n== 任九·选9 ==")
spread = sorted(MATCHES, key=lambda n: subset_p(n, best_subset(n, 2)))
drops = spread[:5]
keeps = [n for n in MATCHES if n not in drops]
print(f"  丢(最发散5场): {sorted(drops)} | keep: {keeps}")
for cap in (192, 128, 64):
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
    print(f"  ≤{cap}注 → {bets3}注 ¥{bets3*2} P(9场全中)={p3:.2%}")
    print(f"    {picks}")

# ---- 落 judgment json ----
out = {
    "issue": "26094",
    "made_at": "2026-07-21",
    "method": "14场并行jczq-match-analyst深研+500.com pjgl锚+4条偏移Read(season_rhythm_gap/lineup_news_gap)+3^14全枚举覆盖优化",
    "sale_stop": "2026-07-21 22:00 CST",
    "belief": {str(n): [round(belief[n][k], 4) for k in KEYS] for n in MATCHES},
    "optimal": {
        "bets": bets_opt, "stake_yuan": bets_opt * 2,
        "p14": round(p_opt, 5),
        "alloc": {str(n): "".join(SYM[k] for k in alloc_opt[n]) for n in MATCHES},
    },
}
(ROOT / ".nutmeg-data/zucai/26094-judgment.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print("\nWROTE .nutmeg-data/zucai/26094-judgment.json")
