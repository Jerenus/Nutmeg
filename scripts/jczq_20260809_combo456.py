"""2026-08-09 周日004/005/006 三场混合玩法高赔组合枚举(禁嘴算).

竞彩规则:同一场次在一张串关票里只能选**一种玩法的一个选项**,故 3串1 = 三场各选一项。
概率口径:**体彩自身赔率比例去水**(每个玩法独立去水),这是与下注同源的口径;
另用 dcfit.json 的 DC 矩阵对 crs/ttg/had/hhad 交叉验证(hafu 无 DC 口径,标 NA)。

输出:
  1) 每场逐玩法的 市场fair / DC / 差值,标出 DC 认为被体彩低估的选项
  2) 3串1 按赔率分档,每档给"联合命中概率"最高的组合
  3) 模态堆叠票(每腿押该玩法模态) vs 冷腿堆叠票 的对照
"""
import json
import math
from itertools import product
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUN_DATE = "2026-08-09"
SPORTTERY = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/sporttery_markets.json"
DCFIT = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/dcfit.json"
NUMS = ["周日004", "周日005", "周日006"]
NAME = {"周日004": "斯巴达-费耶诺德", "周日005": "圣保利-菲尔特", "周日006": "纽伦堡-德累斯顿"}
MAXG = 12


# ---------- DC 矩阵(复用 dcfit 的 λ/ρ) ----------
def pois(k, l):
    return math.exp(-l) * l ** k / math.factorial(k)


def tau(i, j, lh, la, r):
    if i == 0 and j == 0:
        return 1 - lh * la * r
    if i == 0 and j == 1:
        return 1 + lh * r
    if i == 1 and j == 0:
        return 1 + la * r
    if i == 1 and j == 1:
        return 1 - r
    return 1.0


def matrix(lh, la, r):
    m, s = {}, 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            p = max(0.0, tau(i, j, lh, la, r) * pois(i, lh) * pois(j, la))
            m[(i, j)] = p
            s += p
    return {k: v / s for k, v in m.items()}


def devig(odds_map):
    """比例去水: fair_i = (1/o_i) / Σ(1/o)。返回 (fair dict, margin)。"""
    inv = {k: 1.0 / v for k, v in odds_map.items()}
    tot = sum(inv.values())
    return {k: v / tot for k, v in inv.items()}, tot - 1.0


def parse_markets():
    raw = json.load(SPORTTERY.open(encoding="utf-8"))
    out = {}
    for blk in raw["matchInfoList"]:
        for m in blk["subMatchList"]:
            n = m.get("matchNumStr")
            if n not in NUMS:
                continue
            got = {}
            had = m["had"]
            got["had"] = {"主胜": float(had["h"]), "平局": float(had["d"]), "客胜": float(had["a"])}
            hh = m["hhad"]
            line = int(float(hh["goalLineValue"]))
            got["hhad"] = {f"让胜({line:+d})": float(hh["h"]),
                           f"让平({line:+d})": float(hh["d"]),
                           f"让负({line:+d})": float(hh["a"])}
            got["_line"] = line
            crs = {}
            for k, v in m["crs"].items():
                if k.endswith("f") or k in ("goalLine", "goalLineValue", "updateDate", "updateTime"):
                    continue
                if k.startswith("s") and "s" in k[1:]:
                    if k in ("s1sh", "s1sd", "s1sa"):
                        lbl = {"s1sh": "胜其他", "s1sd": "平其他", "s1sa": "负其他"}[k]
                        crs[lbl] = float(v)
                    else:
                        i, j = int(k[1:3]), int(k[4:6])
                        crs[f"{i}:{j}"] = float(v)
            got["crs"] = crs
            ttg = {}
            for k, v in m["ttg"].items():
                if k.endswith("f") or k in ("goalLine", "goalLineValue", "updateDate", "updateTime"):
                    continue
                n_goal = int(k[1:])
                ttg[f"{n_goal}球" + ("+" if n_goal == 7 else "")] = float(v)
            got["ttg"] = ttg
            hf = m["hafu"]
            lbl = {"h": "主", "d": "平", "a": "客"}
            hafu = {}
            for a in "hda":
                for b in "hda":
                    hafu[f"半{lbl[a]}/全{lbl[b]}"] = float(hf[a + b])
            got["hafu"] = hafu
            out[n] = got
    return out


def dc_probs(num, dc, line):
    lh, la, r = dc[num]["lambda"]
    m = matrix(lh, la, r)
    p = {}
    p["had"] = {"主胜": sum(v for (i, j), v in m.items() if i > j),
                "平局": sum(v for (i, j), v in m.items() if i == j),
                "客胜": sum(v for (i, j), v in m.items() if i < j)}
    p["hhad"] = {f"让胜({line:+d})": sum(v for (i, j), v in m.items() if i + line > j),
                 f"让平({line:+d})": sum(v for (i, j), v in m.items() if i + line == j),
                 f"让负({line:+d})": sum(v for (i, j), v in m.items() if i + line < j)}
    p["ttg"] = {f"{k}球": sum(v for (i, j), v in m.items() if i + j == k) for k in range(7)}
    p["ttg"]["7球+"] = sum(v for (i, j), v in m.items() if i + j >= 7)
    p["_matrix"] = m
    return p


def crs_dc(m, labels):
    """把 DC 矩阵映射到体彩 crs 标签集(含 胜/平/负其他)。"""
    listed = set()
    out = {}
    for lbl in labels:
        if lbl in ("胜其他", "平其他", "负其他"):
            continue
        i, j = map(int, lbl.split(":"))
        out[lbl] = m.get((i, j), 0.0)
        listed.add((i, j))
    out["胜其他"] = sum(v for (i, j), v in m.items() if i > j and (i, j) not in listed)
    out["平其他"] = sum(v for (i, j), v in m.items() if i == j and (i, j) not in listed)
    out["负其他"] = sum(v for (i, j), v in m.items() if i < j and (i, j) not in listed)
    return out


def main():
    mk = parse_markets()
    dc = json.load(DCFIT.open(encoding="utf-8"))
    book = {}          # num -> {market -> [(label, odds, fair_mkt, p_dc)]}
    for num in NUMS:
        line = mk[num]["_line"]
        d = dc_probs(num, dc, line)
        mdl_crs = crs_dc(d["_matrix"], mk[num]["crs"].keys())
        legs = {}
        for market in ("had", "hhad", "crs", "ttg", "hafu"):
            odds = mk[num][market]
            fair, margin = devig(odds)
            rows = []
            for lbl, o in odds.items():
                if market == "crs":
                    pdc = mdl_crs.get(lbl)
                elif market == "hafu":
                    pdc = None
                else:
                    pdc = d[market].get(lbl)
                rows.append({"label": lbl, "odds": o, "mkt": fair[lbl], "dc": pdc,
                             "market": market})
            rows.sort(key=lambda r: -r["mkt"])
            legs[market] = {"rows": rows, "margin": margin}
        book[num] = legs

    # ---------- 1. 逐场逐玩法明细 ----------
    print("=" * 100)
    print("PART 1 · 逐场逐玩法：体彩赔率 / 比例去水市场fair / DC模型 / 差值(DC−市场,pp)")
    print("=" * 100)
    for num in NUMS:
        print(f"\n### {num} {NAME[num]}")
        for market in ("had", "hhad", "ttg", "crs", "hafu"):
            blk = book[num][market]
            print(f"  [{market}] 抽水 {blk['margin']*100:.2f}%")
            for r in blk["rows"]:
                if r["mkt"] < 0.012 and market in ("crs",):
                    continue
                dcs = f"{r['dc']*100:6.2f}" if r["dc"] is not None else "   NA "
                diff = f"{(r['dc']-r['mkt'])*100:+6.2f}" if r["dc"] is not None else "   NA "
                print(f"     {r['label']:<12} @{r['odds']:>7.2f}  市场{r['mkt']*100:6.2f}%  DC{dcs}%  差{diff}pp")

    # ---------- 2. 3串1 枚举 ----------
    pool = {num: [r for market in ("had", "hhad", "ttg", "crs", "hafu")
                  for r in book[num][market]["rows"]] for num in NUMS}
    combos = []
    for a, b, c in product(pool[NUMS[0]], pool[NUMS[1]], pool[NUMS[2]]):
        od = a["odds"] * b["odds"] * c["odds"]
        pm = a["mkt"] * b["mkt"] * c["mkt"]
        pd = None
        if a["dc"] is not None and b["dc"] is not None and c["dc"] is not None:
            pd = a["dc"] * b["dc"] * c["dc"]
        combos.append({"legs": (a, b, c), "odds": od, "p_mkt": pm, "p_dc": pd,
                       "ev_mkt": od * pm, "ev_dc": (od * pd) if pd else None})

    def fmt(cb):
        a, b, c = cb["legs"]
        s = " | ".join(f"{n[-3:]}·{r['market']}·{r['label']}@{r['odds']:.2f}"
                       for n, r in zip(NUMS, (a, b, c)))
        pdc = f"{cb['p_dc']*100:6.3f}%" if cb["p_dc"] else "   NA  "
        edc = f"{cb['ev_dc']:.3f}" if cb["ev_dc"] else " NA  "
        return (f"  {cb['odds']:8.1f}x  命中(市场){cb['p_mkt']*100:6.3f}%  (DC){pdc}"
                f"  回报率(市场){cb['ev_mkt']:.3f} (DC){edc}\n      {s}")

    BANDS = [(10, 25), (25, 50), (50, 100), (100, 250), (250, 600), (600, 1500), (1500, 1e9)]
    print("\n" + "=" * 100)
    print("PART 2 · 3串1 按赔率分档，每档取【联合命中概率最高】的 3 条")
    print("=" * 100)
    for lo, hi in BANDS:
        sel = [c for c in combos if lo <= c["odds"] < hi]
        if not sel:
            continue
        sel.sort(key=lambda c: -c["p_mkt"])
        print(f"\n--- {lo}x ~ {hi if hi < 1e9 else '∞'}x  (该档共 {len(sel)} 种组合) ---")
        for c in sel[:3]:
            print(fmt(c))

    # ---------- 3. 结构对照 ----------
    print("\n" + "=" * 100)
    print("PART 3 · 结构对照：模态堆叠 vs 冷腿堆叠（同赔率区间）")
    print("=" * 100)
    modal = {}
    for num in NUMS:
        modal[num] = {m: max(book[num][m]["rows"], key=lambda r: r["mkt"])
                      for m in ("had", "hhad", "ttg", "crs", "hafu")}
    for mkt_name in ("crs", "ttg", "hafu", "hhad", "had"):
        legs = tuple(modal[n][mkt_name] for n in NUMS)
        od = legs[0]["odds"] * legs[1]["odds"] * legs[2]["odds"]
        pm = legs[0]["mkt"] * legs[1]["mkt"] * legs[2]["mkt"]
        pd = None
        if all(l["dc"] is not None for l in legs):
            pd = legs[0]["dc"] * legs[1]["dc"] * legs[2]["dc"]
        cb = {"legs": legs, "odds": od, "p_mkt": pm, "p_dc": pd,
              "ev_mkt": od * pm, "ev_dc": (od * pd) if pd else None}
        print(f"\n[三场同押 {mkt_name} 的市场模态]")
        print(fmt(cb))

    # 全场最高命中率的 3串1（不限赔率）
    print("\n[全枚举中命中率最高的 3串1]")
    best = max(combos, key=lambda c: c["p_mkt"])
    print(fmt(best))

    # DC 相对市场最被低估的单腿（只在有 DC 口径的玩法里找）
    print("\n" + "=" * 100)
    print("PART 4 · DC 相对体彩去水【被低估】的单腿（差值 ≥ +1.0pp，按差值降序）")
    print("=" * 100)
    edges = []
    for num in NUMS:
        for market in ("had", "hhad", "ttg", "crs"):
            for r in book[num][market]["rows"]:
                if r["dc"] is None:
                    continue
                d = r["dc"] - r["mkt"]
                if d >= 0.01:
                    edges.append((d, num, r))
    edges.sort(key=lambda x: -x[0])
    for d, num, r in edges[:18]:
        print(f"  {num} {r['market']:<5} {r['label']:<12} @{r['odds']:>7.2f}  "
              f"市场{r['mkt']*100:6.2f}%  DC{r['dc']*100:6.2f}%  差 {d*100:+5.2f}pp  "
              f"DC口径回报率 {r['odds']*r['dc']:.3f}")

    out = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/combo456.json"
    out.write_text(json.dumps({
        "generated_for": NUMS,
        "note": "概率=体彩比例去水;DC=从fair反推的Dixon-Coles;hafu无DC口径",
        "legs": {n: {m: [{k: v for k, v in r.items()} for r in book[n][m]["rows"]]
                     for m in ("had", "hhad", "ttg", "crs", "hafu")} for n in NUMS},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
