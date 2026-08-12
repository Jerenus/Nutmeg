"""2026-08-06 全板 15 场扫描 — 找"没被抽水吃掉"的选项,再组 10 倍以上串关(禁嘴算)。

锚口径:
- 周四001-005:欧赔去水 fair(apifootball) + 体彩 ttg → DC 拟合(最 sharp)
- 周五001-010:仅体彩去水 fair had + ttg → DC 拟合(无国际锚,标记 anchor=tc)

对每场每个选项算:DC 命中率 p、体彩赔率 o、回本线 1/p、EV=p*o。
EV≥1 = 该选项在我们的信念下不亏抽水;这是组串的唯一入选资格。
"""
import json
import math
from itertools import combinations, product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
RUN = "2026-08-06"
DAY = ROOT / f".nutmeg-data/jczq/daily/{RUN}"
SNAPS = ROOT / ".nutmeg-data/jczq/decision/snapshots.jsonl"


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


def totals(m):
    t = {}
    for (i, j), p in m.items():
        t[i + j] = t.get(i + j, 0.0) + p
    return t


def outcomes(m):
    return (sum(p for (i, j), p in m.items() if i > j),
            sum(p for (i, j), p in m.items() if i == j),
            sum(p for (i, j), p in m.items() if i < j))


def ttg_bands(m):
    t = totals(m)
    b = {f"total_{k}": t.get(k, 0.0) for k in range(7)}
    b["total_7"] = sum(v for kk, v in t.items() if kk >= 7)
    return b


def loss(params, tg):
    lh, la, r = params
    if lh <= 0.05 or la <= 0.05 or abs(r) > 0.5:
        return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    out = ((ph - tg["ph"]) ** 2 + (pd - tg["pd"]) ** 2 + (pa - tg["pa"]) ** 2) * 3
    bands = ttg_bands(m)
    for k, v in (tg.get("ttg") or {}).items():
        out += (bands[k] - v) ** 2
    return out


def fit(tg):
    lh, la, r = 1.3, 1.1, -0.06
    best = (loss((lh, la, r), tg), (lh, la, r))
    step = 0.4
    for _ in range(12):
        improved = True
        while improved:
            improved = False
            for dh, da, dr in product([-1, 0, 1], repeat=3):
                cand = (lh + dh * step, la + da * step, r + dr * step * 0.1)
                val = loss(cand, tg)
                if val < best[0] - 1e-12:
                    best = (val, cand)
                    lh, la, r = cand
                    improved = True
        step /= 2
    return best[1]


def hhad_cover(m, line):
    return (sum(p for (i, j), p in m.items() if i + line > j),
            sum(p for (i, j), p in m.items() if i + line == j),
            sum(p for (i, j), p in m.items() if i + line < j))


def board():
    v = json.loads((DAY / "sporttery_markets.json").read_text(encoding="utf-8"))
    out = []
    for day in v.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if raw.get("homeTeamAbbName"):
                out.append(raw)
    return out


def devig(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def euro_fairs():
    out = {}
    for line in SNAPS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        if s.get("source") != "apifootball" or s.get("kind") != "read_time":
            continue
        if RUN not in s.get("taken_at", ""):
            continue
        num = s["snapshot_id"].split("-")[3]
        if (s.get("fair") or {}).get("had"):
            out[num] = s["fair"]["had"]
    return out


def main():
    euro = euro_fairs()
    rows, legs = [], []
    for raw in board():
        num = str(raw.get("matchNumStr"))
        had, hhad = raw.get("had") or {}, raw.get("hhad") or {}
        name = f"{raw['homeTeamAbbName']}-{raw['awayTeamAbbName']}"
        league = raw.get("leagueAbbName")
        ttg_pool = raw.get("ttg") or {}
        tc_ttg = None
        if ttg_pool.get("s0"):
            o = [float(ttg_pool[f"s{k}"]) for k in range(8)]
            p = devig(o)
            tc_ttg = {f"total_{k}": p[k] for k in range(8)}
        if had.get("h"):
            oh, od, oa = float(had["h"]), float(had["d"]), float(had["a"])
            tc = devig([oh, od, oa])
        else:
            oh = od = oa = None
            tc = None
        if num in euro:
            src, ph, pd, pa = "euro", euro[num]["home"], euro[num]["draw"], euro[num]["away"]
        elif tc:
            src, (ph, pd, pa) = "tc", tc
        else:
            continue
        if not tc_ttg:
            continue
        lh, la, r = fit({"ph": ph, "pd": pd, "pa": pa, "ttg": tc_ttg})
        m = matrix(lh, la, r)
        dh, dd, da = outcomes(m)
        rows.append({"num": num, "name": name, "league": league, "anchor": src,
                     "dc": [round(dh, 4), round(dd, 4), round(da, 4)]})
        if oh:
            for sel, p, o in (("主胜", dh, oh), ("平局", dd, od), ("客胜", da, oa)):
                legs.append({"num": num, "name": name, "league": league, "market": "had",
                             "sel": sel, "p": p, "odds": o, "ev": p * o, "anchor": src})
        if hhad.get("h") and hhad.get("goalLine") not in (None, ""):
            line = int(hhad["goalLine"])
            w, pu, lo = hhad_cover(m, line)
            for sel, p, o in ((f"让胜{line:+d}", w, float(hhad["h"])),
                              (f"让平{line:+d}", pu, float(hhad["d"])),
                              (f"让负{line:+d}", lo, float(hhad["a"]))):
                legs.append({"num": num, "name": name, "league": league, "market": "hhad",
                             "sel": sel, "p": p, "odds": o, "ev": p * o, "anchor": src})
    legs.sort(key=lambda x: -x["ev"])
    print("=== 全板选项按 EV(=DC命中率×体彩赔率) 排序,前 18 ===")
    print(f"{'竞彩号':<8}{'对阵':<20}{'玩法':<9}{'赔率':>6}{'DC命中':>8}{'回本线':>8}{'EV':>7}  锚")
    for x in legs[:18]:
        print(f"{x['num']:<8}{x['name'][:18]:<20}{x['sel']:<9}{x['odds']:>6.2f}"
              f"{x['p']:>8.3f}{1/x['p']:>8.2f}{x['ev']:>7.3f}  {x['anchor']}")
    qual = [x for x in legs if x["ev"] >= 0.98]
    print(f"\n=== 入选池(EV≥0.98):{len(qual)} 条 ===")
    for x in qual:
        print(f"  {x['num']} {x['name']} {x['sel']} @{x['odds']} p={x['p']:.3f} EV={x['ev']:.3f}")

    print("\n=== 10 倍以上组合(池内互不同场,按 EV 排序) ===")
    combos = []
    for k in (2, 3, 4):
        for c in combinations(qual, k):
            if len({x["num"] for x in c}) != k:
                continue
            odds = 1.0
            p = 1.0
            for x in c:
                odds *= x["odds"]
                p *= x["p"]
            if odds < 10:
                continue
            combos.append({"legs": c, "odds": odds, "p": p, "ev": p * odds, "k": k})
    combos.sort(key=lambda x: (-x["ev"], -x["p"]))
    for c in combos[:12]:
        tag = " / ".join(f"{x['num']}{x['sel']}" for x in c["legs"])
        print(f"  {c['k']}串1 {c['odds']:>7.2f}倍 命中 {100*c['p']:>5.2f}% EV={c['ev']:.3f} | {tag}")
    (DAY / "scan.json").write_text(json.dumps(
        {"rows": rows, "legs": legs[:40],
         "combos": [{"odds": round(c["odds"], 2), "p": round(c["p"], 5),
                     "ev": round(c["ev"], 4),
                     "legs": [f"{x['num']}{x['sel']}@{x['odds']}" for x in c["legs"]]}
                    for c in combos[:20]]}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
