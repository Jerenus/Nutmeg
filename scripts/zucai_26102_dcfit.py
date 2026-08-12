"""26102 期 — Dixon-Coles fit from de-vigged fair (禁嘴算).

锚口径:had 一律用 **国际 14-15 家即时均值去水 fair**(26102-euro.json)。
⚠️ 体彩 had 不作锚:全板凯利扫描证实体彩在热门档单边砍价(场9/13/14 被砍 4.7-9.7pp),
且场1/3/4/6 的体彩板冻结在 2026-08-07(陈盘)。体彩只贡献 ttg 分布做形状约束。

输出: λ/ρ、模态比分、总进球带、净胜分布、大 2.5 球、体彩 3 路让球 cover(若有线)。
拟合器复用 scripts/zucai_26101_dcfit.py(函数体不变)。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
ISSUE = "26102"
RUN_DATE = "2026-08-09"

# 足彩场次号 -> 体彩 matchNum
ZC2SP = {1: "7010", 2: "7009", 3: "7015", 4: "7018", 5: "7020", 6: "7021", 7: "7022",
         8: "7014", 9: "7013", 10: "7011", 11: "7016", 12: "7019", 13: "7012", 14: "7017"}


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
    bands = {f"total_{k}": t.get(k, 0.0) for k in range(7)}
    bands["total_7"] = sum(v for kk, v in t.items() if kk >= 7)
    return bands


def loss(params, tg):
    lh, la, r = params
    if lh <= 0.05 or la <= 0.05 or abs(r) > 0.5:
        return 1e9
    m = matrix(lh, la, r)
    ph, pd, pa = outcomes(m)
    out = ((ph - tg["ph"]) ** 2 + (pd - tg["pd"]) ** 2 + (pa - tg["pa"]) ** 2) * 3
    if tg.get("ttg"):
        bands = ttg_bands(m)
        for k, v in tg["ttg"].items():
            out += (bands[k] - v) ** 2
    return out


def fit(tg, lh0=1.4, la0=1.2, fix_rho=None):
    r0 = -0.06 if fix_rho is None else fix_rho
    best = (loss((lh0, la0, r0), tg), (lh0, la0, r0))
    lh, la, r = lh0, la0, r0
    step = 0.4
    for _ in range(12):
        improved = True
        while improved:
            improved = False
            deltas = product([-1, 0, 1], [-1, 0, 1], [0] if fix_rho is not None else [-1, 0, 1])
            for dh, da, dr in deltas:
                cand = (lh + dh * step, la + da * step, r + dr * step * 0.1)
                val = loss(cand, tg)
                if val < best[0] - 1e-12:
                    best = (val, cand)
                    lh, la, r = cand
                    improved = True
        step /= 2
    return best[1], best[0]


def margin_dist(m):
    d = {}
    for (i, j), p in m.items():
        d[i - j] = d.get(i - j, 0.0) + p
    return d


def load_sporttery():
    """{足彩场次号: {'ttg': fair, 'hhad_line': str|None, 'stale': bool}}"""
    from nutmeg.decision.market_data import devig
    path = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/sporttery_markets.json"
    raw = json.loads(path.read_text("utf-8"))
    by_num = {}
    for day in raw["matchInfoList"]:
        for m in day["subMatchList"]:
            by_num[str(m.get("matchNum"))] = m
    out = {}
    for no, num in ZC2SP.items():
        m = by_num.get(num)
        if not m:
            continue
        rec = {"ttg": None, "hhad_line": None, "had_date": None}
        ttg = m.get("ttg") or {}
        keys = [("s0", "total_0"), ("s1", "total_1"), ("s2", "total_2"), ("s3", "total_3"),
                ("s4", "total_4"), ("s5", "total_5"), ("s6", "total_6"), ("s7", "total_7")]
        odds = {dst: float(ttg[src]) for src, dst in keys if ttg.get(src)}
        if len(odds) == 8:
            rec["ttg"] = devig(odds)
        hh = m.get("hhad") or {}
        if hh.get("goalLine"):
            rec["hhad_line"] = hh["goalLine"]
        had = m.get("had") or {}
        rec["had_date"] = had.get("updateDate")
        out[no] = rec
    return out


def main():
    euro = json.loads((ROOT / f".nutmeg-data/zucai/{ISSUE}-euro.json").read_text("utf-8"))
    sp = load_sporttery()
    report = {}
    for no in range(1, 15):
        e = euro[str(no)]
        had = e["euro_live"]
        s = sp.get(no, {})
        ttg = s.get("ttg")
        tg = {"ph": had["home"], "pd": had["draw"], "pa": had["away"], "ttg": ttg}
        (lh, la, r), fit_loss = fit(tg, fix_rho=None if ttg else -0.06)
        mx = matrix(lh, la, r)
        ph, pd, pa = outcomes(mx)
        md = margin_dist(mx)
        line = s.get("hhad_line")
        cover = None
        if line:
            n = int(float(line))  # 主队让 n 球(负数)或受让(正数)
            cover = {
                "line": line,
                "让胜": round(sum(v for k, v in md.items() if k + n > 0), 4),
                "让平": round(sum(v for k, v in md.items() if k + n == 0), 4),
                "让负": round(sum(v for k, v in md.items() if k + n < 0), 4),
            }
        report[str(no)] = {
            "name": e["name"], "league": e["league"],
            "ttg_anchor": bool(ttg), "sporttery_had_date": s.get("had_date"),
            "lambda": [round(lh, 3), round(la, 3), round(r, 3)],
            "fit_loss": round(fit_loss, 6),
            "fair_had_euro": {k: round(v, 4) for k, v in had.items()},
            "dc_had": [round(ph, 4), round(pd, 4), round(pa, 4)],
            "top_scores": [[f"{i}:{j}", round(p, 4)]
                           for (i, j), p in sorted(mx.items(), key=lambda kv: -kv[1])[:6]],
            "ttg_bands": {k: round(v, 4) for k, v in ttg_bands(mx).items()},
            "over25": round(sum(v for kk, v in totals(mx).items() if kk >= 3), 4),
            "margin": {str(k): round(v, 4) for k, v in sorted(md.items()) if -4 <= k <= 4},
            "home_by_2plus": round(sum(v for kk, v in md.items() if kk >= 2), 4),
            "away_by_2plus": round(sum(v for kk, v in md.items() if kk <= -2), 4),
            "hhad_cover": cover,
        }
    out = ROOT / f".nutmeg-data/zucai/{ISSUE}-dcfit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for no, rr in report.items():
        f = rr["fair_had_euro"]
        flag = "ttg锚" if rr["ttg_anchor"] else "无ttg锚"
        stale = " ⚠️陈盘" if rr["sporttery_had_date"] == "2026-08-07" else ""
        print(f"\n{no:>2} {rr['name']}({rr['league']}) [{flag}]{stale}")
        print(f"   λ={rr['lambda']} loss={rr['fit_loss']} | 欧赔fair "
              f"{f['home']*100:.1f}/{f['draw']*100:.1f}/{f['away']*100:.1f}")
        print(f"   模态: {rr['top_scores'][:4]} | 大2.5={rr['over25']:.3f}")
        b = rr["ttg_bands"]
        band = sorted(b.items(), key=lambda kv: -kv[1])[:2]
        print(f"   进球模态带: {band} | 主净胜≥2={rr['home_by_2plus']:.3f} 客净胜≥2={rr['away_by_2plus']:.3f}")
        if rr["hhad_cover"]:
            c = rr["hhad_cover"]
            print(f"   体彩让球线={c['line']} → 让胜{c['让胜']*100:.1f}/让平{c['让平']*100:.1f}/让负{c['让负']*100:.1f}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
