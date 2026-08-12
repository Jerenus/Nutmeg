"""26101 期 — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚口径:had 用 **500 百家欧指 14-15 家即时均值去水 fair**(见 26101-odds.json,
已剔除体彩官方指数行);ttg 只有体彩有,故对同时挂在 8/08 竞彩板面的 10 场额外
用 sporttery ttg 全分布 0..7+ 联合拟合,其余 4 场固定 ρ=-0.06 只拟合 1X2。

输出: λ/ρ、模态比分、总进球带、净胜分布、大 2.5 球、体彩 3 路让球 cover(若有线)。
拟合器复用 scripts/jczq_20260807_dcfit.py(函数体不变)。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
SNAPS = ROOT / ".nutmeg-data/jczq/decision/snapshots.jsonl"
ISSUE = "26101"
RUN_DATE = "2026-08-08"


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


def load_issue():
    issue = json.loads((ROOT / f".nutmeg-data/zucai/{ISSUE}-issue.json").read_text("utf-8"))
    odds = json.loads((ROOT / f".nutmeg-data/zucai/{ISSUE}-odds.json").read_text("utf-8"))
    by_no = {m["match_no"]: m for m in odds["matches"]}
    return issue, by_no


def canonical(m):
    from nutmeg.decision.identity import canonical_match_id
    return canonical_match_id(m["home_team"], m["away_team"], m["match_date"])


def load_sporttery_ttg():
    """{canonical_match_id: 体彩 ttg fair} —— 当日读时快照。"""
    out = {}
    if not SNAPS.exists():
        return out
    for raw in SNAPS.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        s = json.loads(raw)
        if s.get("kind") != "read_time" or s.get("source") != "sporttery":
            continue
        if RUN_DATE not in (s.get("taken_at") or ""):
            continue
        fair = (s.get("fair") or {}).get("ttg")
        if fair:
            out[s.get("match_id")] = fair
    return out


def main():
    from nutmeg.decision.market_data import fair_1x2
    issue, odds_by_no = load_issue()
    ttg_map = load_sporttery_ttg()
    report = {}
    for m in issue["matches"]:
        no = m["match_no"]
        o = odds_by_no[no]
        had = fair_1x2({"home": o["home"], "draw": o["draw"], "away": o["away"]})
        mid = canonical(m)
        ttg = ttg_map.get(mid)
        tg = {"ph": had["home"], "pd": had["draw"], "pa": had["away"], "ttg": ttg}
        (lh, la, r), fit_loss = fit(tg, fix_rho=None if ttg else -0.06)
        mx = matrix(lh, la, r)
        ph, pd, pa = outcomes(mx)
        md = margin_dist(mx)
        report[str(no)] = {
            "name": f"{m['home_team']} vs {m['away_team']}({m['competition']})",
            "match_id": mid,
            "ttg_anchor": bool(ttg),
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
        }
    out = ROOT / f".nutmeg-data/zucai/{ISSUE}-dcfit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for no, r in report.items():
        f = r["fair_had_euro"]
        flag = "ttg锚" if r["ttg_anchor"] else "无ttg锚(ρ固定)"
        print(f"\n{no:>2} {r['name']}  [{flag}]")
        print(f"   λ={r['lambda']} loss={r['fit_loss']} | 欧赔fair 主/平/客="
              f"{f['home']*100:.1f}/{f['draw']*100:.1f}/{f['away']*100:.1f}")
        print(f"   模态比分: {r['top_scores'][:5]}")
        print(f"   大2.5={r['over25']:.3f} | 主净胜≥2={r['home_by_2plus']:.3f} | "
              f"客净胜≥2={r['away_by_2plus']:.3f}")
        print(f"   净胜分布: {r['margin']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
