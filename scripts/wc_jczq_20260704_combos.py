"""2026-07-04 判读层意见票组合算术（禁嘴算，Phase 5）.

底座 = dcfit-20260704.json（DC 锚 29 家去水 fair）；override 概率来自 11 场
jczq-match-analyst 深研（状态/战意层，来源见 judge PDF），在此只做确定性算术。
引擎 A/E 票的 DC 命中率也在此算（诚实公示用），与意见票永不合账。
"""
import json
from itertools import product
from pathlib import Path

DAILY = Path(__file__).parents[1] / ".nutmeg-data/jczq/daily/2026-07-04"
DC = json.loads((DAILY / "dcfit-20260704.json").read_text())

# ---------- 判读层意见票 ¥40 ----------
# (票名, 注金, [(场次, 玩法, 赔率, DC基准率, override率, override一句话)])
TICKETS = [
    ("评判员单关·法国可控2球", 15, [
        ("周六090", "让平@3.50(法恰净胜2)", 3.50, DC["周六090"]["margin"]["客净胜2"], 0.24,
         "露天104°F+新鲜铁桶压右尾,2-0模态;Alderete缺阵防跌到≤1"),
    ]),
    ("世界杯体能对冲·单关", 10, [
        ("周六089", "让胜@2.08(加拿大+1不败)", 2.08, DC["周六089"]["hhad_3way"]["让胜"], 0.515,
         "摩洛哥120min+点球疲劳+无正印9号;加拿大更鲜;判读模态1-1"),
    ]),
    ("韩职天克让平·单关", 5, [
        ("周六201", "让平@3.75(浦项恰净胜1)", 3.75, DC["周六201"]["hhad_3way"]["让平"], 0.24,
         "浦项=安养天克(近4交手3胜0平)+李镐宰单核1-0模板+梅雨压进球"),
    ]),
    ("北欧主队不败锚·2串1", 10, [
        ("周六205", "让胜@1.49(哈尔姆+1不败)", 1.49, DC["周六205"]["hhad_3way"]["让胜"], 0.60,
         "降级区主场死斗vs升班马无压;客胜钱流=过度反应"),
        ("周六206", "让胜@1.60(代格福什+1不败)", 1.60, DC["周六206"]["hhad_3way"]["让胜"], 0.58,
         "马尔默临时教练+Christiansen/Jansson/García缺;铁桶主队40%平局率"),
    ]),
]

print("== 判读层意见票 ¥40（与引擎注金永不合账）==")
total_stake = sum(s for _, s, _ in TICKETS)
evs = []
for name, stake, legs in TICKETS:
    odds = 1.0
    p_dc = 1.0
    p_ov = 1.0
    for _, _, o, pd, po, _ in legs:
        odds *= o
        p_dc *= pd
        p_ov *= po
    ret = stake * odds
    ev_dc, ev_ov = p_dc * odds, p_ov * odds
    evs.append((name, stake, odds, ret, p_dc, p_ov))
    print(f"\n▶ {name} ¥{stake} · 合成赔率 {odds:.2f} · 回报 ¥{ret:.1f}")
    for m, play, o, pd, po, why in legs:
        print(f"   {m} {play} | DC {pd:.1%} → override {po:.1%} | {why}")
    print(f"   命中率: DC口径 {p_dc:.1%} / 深研口径 {p_ov:.1%} | 期望回收率 {ev_dc:.2f}/{ev_ov:.2f}")

# 情景矩阵（哪些票同时中）
print("\n== 情景矩阵（判读层 ¥%d 整体盈亏, 深研口径概率）==" % total_stake)
names = [t[0] for t in TICKETS]
probs = [
    (lambda t: (lambda p: p)(1.0))(t) for t in TICKETS
]
tick_p = []
tick_ret = []
for name, stake, legs in TICKETS:
    p = 1.0
    o = 1.0
    for _, _, oo, _, po, _ in legs:
        p *= po
        o *= oo
    tick_p.append(p)
    tick_ret.append(stake * o)

exp_total = 0.0
rows = []
for outcome in product([1, 0], repeat=len(TICKETS)):
    p = 1.0
    ret = 0.0
    for i, hit in enumerate(outcome):
        p *= tick_p[i] if hit else (1 - tick_p[i])
        ret += tick_ret[i] if hit else 0.0
    pnl = ret - total_stake
    exp_total += p * pnl
    if p >= 0.02:
        label = "+".join(n.split("·")[0] for i, n in enumerate(names) if outcome[i]) or "全空"
        rows.append((p, label, pnl))
for p, label, pnl in sorted(rows, reverse=True):
    print(f"  {p:5.1%}  {label:<28s} {pnl:+8.1f}")
print(f"  判读层整体期望盈亏: {exp_total:+.1f} 元（负值=娱乐成本,如实公示）")

# ---------- 引擎票 DC 诚实公示 ----------
print("\n== 引擎票面 DC 口径命中率（勿改腿,只公示;整张可不买）==")
A = [("周六207", "had胜", 1.61, DC["周六207"]["model_1x2"][0]),
     ("周六209", "让胜(-1)", 1.71, DC["周六209"]["hhad_3way"]["让胜"])]
pa = 1.0
oa = 1.0
for m, pl, o, p in A:
    pa *= p
    oa *= o
print(f" A 2串1 @ {oa:.2f}: " + " × ".join(f"{m}{pl}{p:.0%}" for m, pl, o, p in A) +
      f" → 整票 {pa:.1%} · 期望回收率 {pa*oa:.2f}")
E = [("周六201", "让负", 6.30, DC["周六201"]["hhad_3way"]["让负"]),
     ("周六203", "让胜", 5.30, DC["周六203"]["hhad_3way"]["让胜"]),
     ("周六205", "让负", 4.95, DC["周六205"]["hhad_3way"]["让负"]),
     ("周六204", "让胜", 4.50, DC["周六204"]["hhad_3way"]["让胜"]),
     ("周六206", "让负", 4.20, DC["周六206"]["hhad_3way"]["让负"])]
pe = 1.0
oe = 1.0
for m, pl, o, p in E:
    pe *= p
    oe *= o
print(f" E 5串1 @ {oe:.0f}: " + " × ".join(f"{m}{pl}{p:.0%}" for m, pl, o, p in E) +
      f" → 整票 {pe:.4%} · 期望回收率 {pe*oe:.2f}")
