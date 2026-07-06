"""MD3 2026-06-24 三串1 组合：从 DC 模型概率 + 体彩 had/hhad 赔率，
确定性算每个三串的 合并赔率 × 联合命中(近独立) × 期望回收(禁嘴算)。
腿池只含可辩护腿(剔除胜平负冷门/让胜net2+ longshot)。"""
from itertools import combinations

# (标签, 场号, 体彩赔率, DC模型命中概率)  —— prob 来自 wc_md3_20260624_crs.py
POOL = [
 ("049 加拿大+1 受让",  "049", 1.49, 0.590),
 ("049 瑞士胜",         "049", 2.25, 0.410),
 ("050 波黑胜",         "050", 1.30, 0.670),
 ("050 波黑-1 让胜",    "050", 2.00, 0.441),
 ("051 巴西胜",         "051", 1.21, 0.690),
 ("051 巴西-1 让胜",    "051", 1.79, 0.439),
 ("052 海地+2 受让",    "052", 2.35, 0.414),
 ("052 摩洛哥-2 让胜",  "052", 2.25, 0.360),
 ("053 韩国胜",         "053", 1.50, 0.560),
 ("053 南非+1 受让",    "053", 2.22, 0.440),
 ("054 捷克+1 受让",    "054", 1.74, 0.510),
 ("054 平(捷墨)",       "054", 3.36, 0.254),
]

def treble_stats(legs):
    odds = 1.0; p = 1.0
    for _,_,o,pr in legs:
        odds *= o; p *= pr
    return odds, p, p*odds  # 合并赔率, 联合命中, 期望回收(每1元)

# 枚举：每场最多一腿
cands = []
for combo in combinations(POOL, 3):
    matches = [c[1] for c in combo]
    if len(set(matches)) < 3:  # 同场不能两腿
        continue
    odds, p, ev = treble_stats(combo)
    cands.append((p, odds, ev, combo))

print("=== 按联合命中率排序 Top 12 可辩护三串 ===")
print(f"{'联合命中':>7} {'合并赔率':>7} {'期望/1元':>7}  腿")
for p, odds, ev, combo in sorted(cands, key=lambda x:-x[0])[:12]:
    legs = " + ".join(c[0] for c in combo)
    print(f"{p*100:6.1f}% {odds:7.2f} {ev:7.2f}  {legs}")

print("\n=== 按期望回收排序 Top 8(都<1=负期望,看哪些抽水最轻) ===")
for p, odds, ev, combo in sorted(cands, key=lambda x:-x[2])[:8]:
    legs = " + ".join(c[0] for c in combo)
    print(f"{p*100:6.1f}% {odds:7.2f} {ev:7.2f}  {legs}")

# 我精选的 3 组(命中优先 / 让球受让 / 平衡 fade)
print("\n" + "="*70)
print("精选 3 组：")
picks = {
 "① 最稳·命中优先(短赔正路+受让)": [POOL[2], POOL[4], POOL[0]],   # 波黑胜 巴西胜 加拿大+1
 "② 让球受让三连(实证最准玩法,fade无动机热门)": [POOL[0], POOL[10], POOL[9]],  # 加拿大+1 捷克+1 南非+1
 "③ 平衡·锚+fade(短赔锚+受让+受让)": [POOL[4], POOL[10], POOL[6]],  # 巴西胜 捷克+1 海地+2
}
for name, legs in picks.items():
    odds, p, ev = treble_stats(legs)
    stake = 10
    print(f"\n{name}")
    for l in legs: print(f"   · {l[0]:18} @{l[2]:.2f}  (模型{l[3]*100:.0f}%)")
    print(f"   合并赔率 {odds:.2f}x | 联合命中 {p*100:.1f}% | ¥{stake}→中{stake*odds:.0f} | 期望回收 {ev*100:.0f}%(每1元)")
