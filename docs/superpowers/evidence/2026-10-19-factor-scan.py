# ruff: noqa: E402, E501, E722, E731
# 2026-10-19 一次性扫描脚本存档（复现 evidence/2026-10-19-decision-table-factor-scan.md）；
# 读 strength_balance.underdog_path 之前的版本，标签相关段落见该文更正节。
import json
import math
import os

R = json.load(open(".nutmeg-data/jczq/jc-results.json"))
rows = []
for day in sorted(os.listdir(".nutmeg-data/jczq/daily")):
    d = f".nutmeg-data/jczq/daily/{day}"
    if day < "2026-09-19" or not os.path.exists(f"{d}/reads.json") or day not in R:
        continue
    reads = json.load(open(f"{d}/reads.json"))
    if not isinstance(reads, list):
        continue
    try:
        co = json.load(open(f"{d}/closing_odds.json"))
    except:
        co = {}
    try:
        lb = json.load(open(f"{d}/jczq-legs-base.json"))
        legs = lb.get("legs") or lb
        mid2code = {}
        if isinstance(legs, dict):
            for k, v in legs.items():
                if isinstance(v, dict) and v.get("match_id"):
                    mid2code[v["match_id"]] = v.get("code") or k
        else:
            for v in legs:
                if v.get("match_id"):
                    mid2code[v["match_id"]] = v.get("code") or v.get("key")
    except Exception:
        mid2code = {}
    for rd in reads:
        code = rd.get("code") or mid2code.get(rd.get("match_id"))
        res = R[day].get(code)
        if not res or res.get("ft_home") is None:
            continue
        rf = f"{d}/research-{code}.json"
        if not os.path.exists(rf):
            continue
        rs = json.load(open(rf))
        b = rd["belief"]
        p = rd["prior"]
        out = (
            "3"
            if res["ft_home"] > res["ft_away"]
            else ("1" if res["ft_home"] == res["ft_away"] else "0")
        )
        m = {"3": p["home"], "1": p["draw"], "0": p["away"]}
        s = {"3": b["home"], "1": b["draw"], "0": b["away"]}
        fav = max(m, key=m.get)
        hl = rs.get("hole_location") or {}
        up = rs.get("underdog_path") or {}
        st = rs.get("stance") or {}
        cl = co.get(code, {}).get("sharp") or {}
        drift = None
        if cl.get("opening_odds") and cl.get("odds"):
            try:
                oo = cl["opening_odds"]
                o = cl["odds"]
                k = {"3": "home", "1": "draw", "0": "away"}[fav]

                def dv(x):
                    inv = {kk: 1 / v for kk, v in x.items()}
                    t = sum(inv.values())
                    return {kk: v / t for kk, v in inv.items()}

                drift = (dv(o)[k] - dv(oo)[k]) * 100
            except:
                drift = None
        hs = hl.get("side")
        hrel = (
            "fav"
            if (hs == "home" and fav == "3") or (hs == "away" and fav == "0")
            else ("dog" if hs in ("home", "away") else hs)
        )
        rows.append(
            dict(
                day=day,
                code=code,
                hrel=hrel,
                out=out,
                m=m,
                s=s,
                fav=fav,
                pfav=m[fav],
                sfav=s[fav],
                delta=(s[fav] - m[fav]) * 100,
                anchor=rs.get("anchor_side"),
                integ=rs.get("anchor_integrity"),
                hside=hl.get("side"),
                hunit=hl.get("unit"),
                priced=hl.get("priced_in"),
                upstr=up.get("strength"),
                upside=up.get("side"),
                mread=st.get("market_read"),
                face=st.get("face"),
                cover=st.get("cover"),
                verdict=(rs.get("strength_balance") or {}).get("verdict"),
                drift=drift,
                d3=(
                    (rs.get("death_three_proofs") or {}).get("home" if fav == "0" else "away") or {}
                ).get("proof_count"),
            )
        )
print(
    "rows", len(rows), "days", len({r["day"] for r in rows}), "first", min(r["day"] for r in rows)
)


def brier(r, key):
    return sum((r[key][f] - (1 if r["out"] == f else 0)) ** 2 for f in "310")


def rep(name, groups):
    print(f"\n## {name}")
    print(
        f"{'bucket':<22}{'n':>5}{'热门实开%':>9}{'市场%':>7}{'系统%':>7}{'残差vs市':>9}{'±SE':>6}{'Brier系−市':>11}{'表态面命中%':>11}{'市场盖%':>8}"
    )
    for g, rs_ in sorted(groups.items(), key=lambda x: str(x[0])):
        n = len(rs_)
        if n < 8:
            continue
        hit = sum(r["out"] == r["fav"] for r in rs_) / n
        pm = sum(r["pfav"] for r in rs_) / n
        ps = sum(r["sfav"] for r in rs_) / n
        se = math.sqrt(hit * (1 - hit) / n) * 100
        bd = sum(brier(r, "s") - brier(r, "m") for r in rs_) / n
        fh = [r for r in rs_ if (r["face"] or "") in ("3", "1", "0")]
        fhit = sum(r["out"] == r["face"] for r in fh) / max(1, len(fh))
        fcov = sum(r["m"][r["face"]] for r in fh) / max(1, len(fh))
        print(
            f"{str(g):<22}{n:>5}{hit * 100:>9.1f}{pm * 100:>7.1f}{ps * 100:>7.1f}{(hit - pm) * 100:>+9.1f}{se:>6.1f}{bd:>+11.4f}{fhit * 100:>11.1f}{fcov * 100:>8.1f}"
        )


G = lambda key: {k: [r for r in rows if r.get(key) == k] for k in {r.get(key) for r in rows}}
rep("全部", {"all": rows})


def db(x):
    if x <= -5:
        return "a ≤−5"
    if x <= -3:
        return "b −5..−3"
    if x < 3:
        return "c −3..+3"
    if x < 5:
        return "d +3..+5"
    return "e ≥+5"


rep(
    "系统−市场 偏离（热门面，pp）",
    {db(r["delta"]): [x for x in rows if db(x["delta"]) == db(r["delta"])] for r in rows},
)
rep("锚方 anchor_side", G("anchor"))
rep("锚方完整度 anchor_integrity", G("integ"))
rep("洞在谁 hole.side（折算 fav=洞在热门 / dog=洞在弱方）", G("hrel"))
rep("洞单位 hole.unit", G("hunit"))
rep("洞 priced_in", G("priced"))
rep("弱方路径 strength", G("upstr"))
rep("市场读 market_read", G("mread"))
rep("强弱天平 verdict", G("verdict"))
rep("死亡三证(弱方) proof_count", G("d3"))


def pb(p):
    return "≥65" if p >= 0.65 else ("55–65" if p >= 0.55 else ("45–55" if p >= 0.45 else "<45"))


rep(
    "市场热门带", {pb(r["pfav"]): [x for x in rows if pb(x["pfav"]) == pb(r["pfav"])] for r in rows}
)
# combos
rep(
    "洞在谁 × 热门带",
    {
        (r["hrel"], pb(r["pfav"])): [
            x for x in rows if (x["hrel"], pb(x["pfav"])) == (r["hrel"], pb(r["pfav"]))
        ]
        for r in rows
        if r["hrel"] in ("fav", "dog")
    },
)
rep(
    "锚方fail × 系统下拨≤−3",
    {
        (r["integ"], r["delta"] <= -3): [
            x for x in rows if (x["integ"], x["delta"] <= -3) == (r["integ"], r["delta"] <= -3)
        ]
        for r in rows
    },
)


def drb(x):
    if x is None:
        return None
    return "盘走向热门≥+2" if x >= 2 else ("盘走离热门≤−2" if x <= -2 else "盘不动")


rep(
    "国际盘开→终 位移 × 系统偏离",
    {
        (drb(r["drift"]), db(r["delta"])[0]): [
            x
            for x in rows
            if (drb(x["drift"]), db(x["delta"])[0]) == (drb(r["drift"]), db(r["delta"])[0])
        ]
        for r in rows
        if r["drift"] is not None
    },
)
rep(
    "研究 cover 面",
    {("cover=" + str(r["cover"])): [x for x in rows if x["cover"] == r["cover"]] for r in rows},
)
# cover face realized vs market
print("\n## 研究 cover 面实开 vs 市场（翻车面有没有形状）")
cv = [
    r
    for r in rows
    if (r["cover"] or "") in ("3", "1", "0")
    and (r["face"] or "") in ("3", "1", "0")
    and r["cover"] != r["face"]
]
hit = sum(r["out"] == r["cover"] for r in cv) / len(cv)
pm = sum(r["m"][r["cover"]] for r in cv) / len(cv)
print(
    f"n={len(cv)} cover 实开 {hit * 100:.1f}% vs 市场 {pm * 100:.1f}% 残差 {(hit - pm) * 100:+.1f} ±{math.sqrt(hit * (1 - hit) / len(cv)) * 100:.1f}"
)
# when fav loses: which face
fl = [r for r in rows if r["out"] != r["fav"] and r["pfav"] >= 0.55]
dr = sum(r["out"] == "1" for r in fl)
print(
    f"热门≥55 翻车 n={len(fl)}：平 {dr} / 第三面 {len(fl) - dr}；市场条件概率 平 {sum(r['m']['1'] / (1 - r['pfav']) for r in fl) / len(fl) * 100:.1f}%"
)

# even verdict detail + 下拨≤-5 detail
ev = [r for r in rows if r["verdict"] == "even"]
print("\n## verdict=even 明细（热门带分布）")
from collections import Counter

print(
    Counter(pb(r["pfav"]) for r in ev),
    "实开 热门/平/弱方:",
    Counter(
        ("fav" if r["out"] == r["fav"] else ("draw" if r["out"] == "1" else "dog")) for r in ev
    ),
)
dd = [r for r in rows if r["delta"] <= -5]
print("\n## 系统下拨≤−5 明细")
for r in dd:
    print(
        r["day"],
        r["code"],
        "市",
        round(r["pfav"] * 100),
        "系",
        round(r["sfav"] * 100),
        "开",
        r["out"],
        "热门" + ("✓" if r["out"] == r["fav"] else "✗"),
        r["integ"],
        r["mread"],
    )
print("\n## 有多少天/场有 reads+research+结果：", sorted(Counter(r["day"] for r in rows).items()))


def per(d):
    return (
        "1 09-19..09-25"
        if d < "2026-09-26"
        else ("2 09-26..10-04" if d < "2026-10-05" else "3 ≥10-05")
    )


rep(
    "系统下拨 ≤−5 × 时段（reads 口径）",
    {
        per(r["day"]): [x for x in rows if x["delta"] <= -5 and per(x["day"]) == per(r["day"])]
        for r in rows
        if r["delta"] <= -5
    },
)
rep(
    "verdict=even × 时段",
    {
        per(r["day"]): [
            x for x in rows if x["verdict"] == "even" and per(x["day"]) == per(r["day"])
        ]
        for r in rows
        if r["verdict"] == "even"
    },
)
rep(
    "anchor_side=none × 时段",
    {
        per(r["day"]): [x for x in rows if x["anchor"] == "none" and per(x["day"]) == per(r["day"])]
        for r in rows
        if r["anchor"] == "none"
    },
)
rep(
    "洞在弱方 × 时段",
    {
        per(r["day"]): [x for x in rows if x["hrel"] == "dog" and per(x["day"]) == per(r["day"])]
        for r in rows
        if r["hrel"] == "dog"
    },
)
