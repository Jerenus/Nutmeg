"""2026-08-09 周日004/005/006 成型组合方案 + 复式覆盖(禁嘴算).

在 jczq_20260809_combo456.py 的去水底座上,构造若干成型方案:
  - 单注 3串1 的赔率/命中/长期回报率
  - 复式(每场多选)的注数/总成本/覆盖率/最低与最高回报
  - 显式拆出"抽水成本"来源:had/hhad 12.9% << ttg/hafu 20.4% << crs 33.9%
"""
import json
from itertools import product
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUN_DATE = "2026-08-09"
BOOK = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/combo456.json"
NUMS = ["周日004", "周日005", "周日006"]
SHORT = {"周日004": "004斯巴达-费耶", "周日005": "005圣保利-菲尔特", "周日006": "006纽伦堡-德累"}


def load():
    raw = json.load(BOOK.open(encoding="utf-8"))["legs"]
    idx = {}
    for num in NUMS:
        idx[num] = {}
        for market, rows in raw[num].items():
            for r in rows:
                idx[num][(market, r["label"])] = r
    return idx


IDX = load()


def leg(num, market, label):
    r = IDX[num].get((market, label))
    if r is None:
        raise KeyError(f"{num} {market} {label} 不存在")
    return r


def single(name, picks, note=""):
    """picks = [(num, market, label), ...] 三场各一"""
    rs = [leg(*p) for p in picks]
    od = 1.0
    pm = 1.0
    for r in rs:
        od *= r["odds"]
        pm *= r["mkt"]
    print(f"\n【{name}】{note}")
    for p, r in zip(picks, rs):
        print(f"    {SHORT[p[0]]:<16} {r['market']:<5} {r['label']:<10} @{r['odds']:>6.2f}  市场{r['mkt']*100:5.2f}%")
    print(f"    → 总赔率 {od:8.1f}x   联合命中 {pm*100:7.4f}%   长期回报率 {od*pm*100:5.1f}%"
          f"   ¥10 本金期望回收 ¥{od*pm*10:.2f}")
    return {"name": name, "odds": od, "p": pm, "ev": od * pm}


def multi(name, picks_per_match, unit=2.0, note=""):
    """picks_per_match = {num: [(market,label),...]} 复式,枚举全部注。"""
    pools = []
    for num in NUMS:
        pools.append([(num, m, l) for (m, l) in picks_per_match[num]])
    tickets = []
    for combo in product(*pools):
        rs = [leg(*p) for p in combo]
        od = 1.0
        pm = 1.0
        for r in rs:
            od *= r["odds"]
            pm *= r["mkt"]
        tickets.append({"combo": combo, "odds": od, "p": pm})
    n = len(tickets)
    cost = n * unit
    cover = sum(t["p"] for t in tickets)          # 恰好命中某一注的总概率
    ev = sum(t["p"] * t["odds"] * unit for t in tickets)
    lo = min(t["odds"] for t in tickets) * unit
    hi = max(t["odds"] for t in tickets) * unit
    print(f"\n【{name}】{note}")
    for num in NUMS:
        sel = " / ".join(f"{m}·{l}@{leg(num,m,l)['odds']:.2f}" for m, l in picks_per_match[num])
        print(f"    {SHORT[num]:<16} {sel}")
    print(f"    → {n} 注 × ¥{unit:.0f} = ¥{cost:.0f}   覆盖率(至少中一注) {cover*100:6.3f}%")
    print(f"      单注回收区间 ¥{lo:.0f} ~ ¥{hi:.0f}   总期望回收 ¥{ev:.2f}   回报率 {ev/cost*100:.1f}%")
    print(f"      回本门槛: 命中的那注赔率需 ≥ {cost/unit:.0f}x")
    return {"name": name, "n": n, "cost": cost, "cover": cover, "ev": ev}


print("=" * 96)
print("PART A · 抽水结构（这决定了所有高赔方案的性价比上限）")
print("=" * 96)
MARG = {}
for market, m004 in (("had", 0.1295), ("hhad", 0.1290), ("ttg", 0.2047), ("crs", 0.3381), ("hafu", 0.2040)):
    MARG[market] = m004
print("  单场抽水:  had 12.9%   hhad 12.9%   ttg 20.4%   hafu 20.4%   crs 33.8%")
print("  3串1 长期回报率 = 1 / Π(1+抽水)  —— 与你选哪个选项无关，只由你用了哪些玩法决定：")
for combo in (("had", "had", "had"), ("hhad", "hhad", "hhad"), ("ttg", "ttg", "ttg"),
              ("hafu", "hafu", "hafu"), ("crs", "crs", "crs"),
              ("had", "had", "ttg"), ("had", "ttg", "crs"), ("hhad", "crs", "crs")):
    r = 1.0
    for m in combo:
        r /= (1 + MARG[m])
    print(f"    {'+'.join(combo):<22} → {r*100:5.1f}%")

print("\n" + "=" * 96)
print("PART B · 成型单注方案（赔率由低到高）")
print("=" * 96)

single("B1 基准·三条模态锚", [("周日004", "hhad", "让胜(+1)"), ("周日005", "had", "主胜"),
                          ("周日006", "hhad", "让负(-1)")],
       "全用低抽水玩法,不追赔率,作为一切高赔方案的对照基准")

single("B2 ttg 模态堆叠", [("周日004", "ttg", "3球"), ("周日005", "ttg", "3球"),
                        ("周日006", "ttg", "3球")],
       "三场都押各自的进球模态档——赔率来自玩法本身,不是来自押冷门")

single("B3 三平堆叠", [("周日004", "had", "平局"), ("周日005", "had", "平局"),
                    ("周日006", "had", "平局")],
       "三场全平。用最低抽水的 had 表达,是 50x 档里回报率最高的结构")

single("B4 had 三冷腿", [("周日004", "had", "主胜"), ("周日005", "had", "客胜"),
                      ("周日006", "had", "客胜")],
       "⚠️历史档案点名的必死形态:3条冷腿堆赔率")

single("B5 低比分平·crs 混合", [("周日004", "had", "平局"), ("周日005", "crs", "1:1"),
                            ("周日006", "crs", "1:1")],
       "一条低抽水锚 + 两条 crs,220x 档")

single("B6 crs 模态堆叠", [("周日004", "crs", "1:2"), ("周日005", "crs", "2:1"),
                        ("周日006", "crs", "1:1")],
       "三场都押各自 crs 模态。330x,但要付 33.8%×3 的抽水")

single("B7 三场 1:1", [("周日004", "crs", "1:1"), ("周日005", "crs", "1:1"),
                     ("周日006", "crs", "1:1")],
       "全部低比分平。460x")

single("B8 三场 0:0", [("周日004", "crs", "0:0"), ("周日005", "crs", "0:0"),
                     ("周日006", "crs", "0:0")],
       "极端低进球。5400x —— 但注意 006 的 λ 恰等于德乙基线,0:0 没有额外理由")

single("B9 hafu 高赔混合", [("周日004", "hafu", "半主/全客"), ("周日005", "hafu", "半平/全主"),
                         ("周日006", "hafu", "半平/全平")],
       "半全场三串。'先落后再赢'是本批比赛的真实剧本形态")

single("B10 极限赔率", [("周日004", "crs", "0:5"), ("周日005", "crs", "5:1"),
                     ("周日006", "crs", "4:0")],
       "⚠️纯为展示上限,概率已到十万分之一量级")

print("\n" + "=" * 96)
print("PART C · 复式覆盖方案（每场多选，注数=各场选项数相乘）")
print("=" * 96)

multi("C1 三场 crs 各选2（模态+次模态）",
      {"周日004": [("crs", "1:2"), ("crs", "1:1")],
       "周日005": [("crs", "2:1"), ("crs", "1:1")],
       "周日006": [("crs", "1:1"), ("crs", "2:1")]},
      unit=2.0, note="8注。覆盖三场各自最厚的两个比分格")

multi("C2 三场 crs 各选3（含平局格）",
      {"周日004": [("crs", "1:2"), ("crs", "1:1"), ("crs", "2:2")],
       "周日005": [("crs", "2:1"), ("crs", "1:1"), ("crs", "2:2")],
       "周日006": [("crs", "1:1"), ("crs", "2:1"), ("crs", "2:2")]},
      unit=2.0, note="27注。三场都把'高比分平'格纳入")

multi("C3 平局轴复式（had平 + crs两个平格）",
      {"周日004": [("had", "平局")],
       "周日005": [("crs", "1:1"), ("crs", "2:2"), ("crs", "0:0")],
       "周日006": [("crs", "1:1"), ("crs", "2:2"), ("crs", "0:0")]},
      unit=2.0, note="9注。004 用低抽水的 had 平锚住,德乙两场用 crs 打平局格")

multi("C4 ttg 复式（每场2-3球带）",
      {"周日004": [("ttg", "2球"), ("ttg", "3球")],
       "周日005": [("ttg", "2球"), ("ttg", "3球")],
       "周日006": [("ttg", "2球"), ("ttg", "3球")]},
      unit=2.0, note="8注。三场都锁在模态带,不赌方向")

multi("C5 混合高赔（004让球锚 + 005/006 crs各选3）",
      {"周日004": [("hhad", "让胜(+1)")],
       "周日005": [("crs", "1:1"), ("crs", "2:1"), ("crs", "1:0")],
       "周日006": [("crs", "1:1"), ("crs", "2:1"), ("crs", "1:0")]},
      unit=2.0, note="9注。用 004 最厚的一格锚住,把赔率全押在德乙两场的比分上")

print("\n" + "=" * 96)
print("PART D · 跨盘源价差（唯一合法的筛腿信号，非 DC 重分配）")
print("=" * 96)
print("  体彩去水 − 国际欧赔去水，单位 pp（负 = 体彩这一面相对便宜）")
print("  004  主 -1.32 | 平 -1.59 | 客 +2.91     ← 体彩把水抽在客胜(费耶诺德)那一面")
print("  005  主 +2.30 | 平 -0.74 | 客 -1.56     ← 体彩把水抽在主胜(圣保利)那一面")
print("  006  主 -1.72 | 平 +0.70 | 客 +0.92     ← 体彩主胜相对便宜(005/006国际盘为实查非API)")
print("  ⇒ 同赔率下优先取: 004 平/主, 005 客, 006 主。三条全部 <3pp,不构成盘源分歧旗。")
