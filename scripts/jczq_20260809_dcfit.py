"""2026-08-09 周日001-011(21:00 前早场) — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚口径:had 优先用**国际欧赔去水 fair**(apifootball);若该场无欧赔锚,退化用体彩去水
had(标 degraded=True,报告须显式标注 prior 已退化)。ttg 分布只有体彩有。
输出: λ/ρ、模态比分、净胜分布、体彩 3 路让球 cover、大 2.5 球、跨盘源价差。

复用 scripts/jczq_20260807_dcfit.py 的拟合器,只改锚来源与场次表。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
SNAPS = ROOT / ".nutmeg-data/jczq/decision/snapshots.jsonl"
RUN_DATE = "2026-08-09"

TICAI_LINE = {                      # 体彩让球线(主队 + line 口径,3 路)
    "周日001": 1, "周日002": 1, "周日003": -1, "周日004": 1, "周日005": -1,
    "周日006": -1, "周日007": -1, "周日008": -1, "周日009": 1, "周日010": -1,
    "周日011": -1,
}
MATCH = {
    "周日001": ("M-2026-08-09-东京绿茵-川崎前锋", "东京绿茵 vs 川崎前锋(日职) 17:00"),
    "周日002": ("M-2026-08-09-长崎航海-京都", "长崎航海 vs 京都(日职) 18:00"),
    "周日003": ("M-2026-08-09-山形山神-枥木城", "山形山神 vs 枥木城(日乙) 18:00"),
    "周日004": ("M-2026-08-09-鹿斯巴达-费耶诺德", "鹿特丹斯巴达 vs 费耶诺德(荷甲) 18:15"),
    "周日005": ("M-2026-08-09-圣保利-菲尔特", "圣保利 vs 菲尔特(德乙) 19:30"),
    "周日006": ("M-2026-08-09-纽伦堡-德累斯顿", "纽伦堡 vs 德累斯顿(德乙) 19:30"),
    "周日007": ("M-2026-08-09-哈马比-赫根", "哈马比 vs 赫根(瑞超) 20:00"),
    "周日008": ("M-2026-08-09-库奥皮奥-tps图尔", "库奥皮奥 vs TPS图尔(芬超) 20:00"),
    "周日009": ("M-2026-08-09-兹沃勒-阿贾克斯", "兹沃勒 vs 阿贾克斯(荷甲) 20:30"),
    "周日010": ("M-2026-08-09-格罗宁根-乌德勒支", "格罗宁根 vs 乌德勒支(荷甲) 20:30"),
    "周日011": ("M-2026-08-09-利勒斯特-罗森博格", "利勒斯特罗姆 vs 罗森博格(挪超) 20:30"),
}


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
    bands = ttg_bands(m)
    for k, v in tg["ttg"].items():
        out += (bands[k] - v) ** 2
    return out


def fit(tg, lh0=1.3, la0=1.1):
    best = (loss((lh0, la0, -0.06), tg), (lh0, la0, -0.06))
    lh, la, r = lh0, la0, -0.06
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
    return best[1], best[0]


def hhad_cover(m, line):
    return (sum(p for (i, j), p in m.items() if i + line > j),
            sum(p for (i, j), p in m.items() if i + line == j),
            sum(p for (i, j), p in m.items() if i + line < j))


def margin_dist(m):
    d = {}
    for (i, j), p in m.items():
        d[i - j] = d.get(i - j, 0.0) + p
    return d


def load_fairs():
    """取当日**最新**读时快照: euro had / ticai had / ticai ttg。"""
    euro, tc_had, tc_ttg = {}, {}, {}
    stamp = {}
    for raw in SNAPS.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        s = json.loads(raw)
        if s.get("kind") != "read_time" or RUN_DATE not in (s.get("taken_at") or ""):
            continue
        for num, (mid, _) in MATCH.items():
            if s.get("match_id") != mid:
                continue
            fair = s.get("fair") or {}
            at = s.get("taken_at")
            if s.get("source") == "apifootball" and fair.get("had"):
                if at >= stamp.get(("e", num), ""):
                    euro[num] = fair["had"]
                    stamp[("e", num)] = at
            if s.get("source") == "sporttery":
                if fair.get("had") and at >= stamp.get(("th", num), ""):
                    tc_had[num] = fair["had"]
                    stamp[("th", num)] = at
                if fair.get("ttg") and at >= stamp.get(("tt", num), ""):
                    tc_ttg[num] = fair["ttg"]
                    stamp[("tt", num)] = at
    return euro, tc_had, tc_ttg


def main():
    euro, tc_had, tc_ttg = load_fairs()
    report = {}
    for num in sorted(MATCH):
        name = MATCH[num][1]
        if num not in tc_ttg:
            print(f"{num} 缺体彩 ttg,跳过")
            continue
        degraded = num not in euro
        had = tc_had[num] if degraded else euro[num]
        tg = {"ph": had["home"], "pd": had["draw"], "pa": had["away"], "ttg": tc_ttg[num]}
        (lh, la, r), fit_loss = fit(tg)
        m = matrix(lh, la, r)
        ph, pd, pa = outcomes(m)
        md = margin_dist(m)
        line = TICAI_LINE[num]
        w, pu, lo = hhad_cover(m, line)
        # 跨盘源价差(唯一许可的筛腿信号): 体彩去水 fair − 国际欧赔 fair,单位 pp
        spread = None
        if not degraded and num in tc_had:
            spread = {k: round((tc_had[num][k] - euro[num][k]) * 100, 2)
                      for k in ("home", "draw", "away")}
        report[num] = {
            "name": name,
            "anchor": "sporttery(DEGRADED·无国际欧赔)" if degraded else "apifootball欧赔",
            "lambda": [round(lh, 3), round(la, 3), round(r, 3)],
            "fit_loss": round(fit_loss, 6),
            "fair_had": {k: round(v, 4) for k, v in had.items()},
            "fair_had_ticai": ({k: round(v, 4) for k, v in tc_had[num].items()}
                               if num in tc_had else None),
            "cross_book_spread_pp": spread,
            "dc_had": [round(ph, 4), round(pd, 4), round(pa, 4)],
            "top_scores": [[f"{i}:{j}", round(p, 4)]
                           for (i, j), p in sorted(m.items(), key=lambda kv: -kv[1])[:6]],
            "ttg_bands": {k: round(v, 4) for k, v in ttg_bands(m).items()},
            "over25": round(sum(v for kk, v in totals(m).items() if kk >= 3), 4),
            "hhad_line": line,
            "hhad_cover": {"让胜": round(w, 4), "让平": round(pu, 4), "让负": round(lo, 4)},
            "margin": {str(k): round(v, 4) for k, v in sorted(md.items()) if -4 <= k <= 4},
            "home_by_2plus": round(sum(v for kk, v in md.items() if kk >= 2), 4),
            "away_by_2plus": round(sum(v for kk, v in md.items() if kk <= -2), 4),
        }
    out = ROOT / f".nutmeg-data/jczq/daily/{RUN_DATE}/dcfit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for num in sorted(report):
        r = report[num]
        f = r["fair_had"]
        top1 = max(f.values())
        print(f"\n{num} {r['name']}  [{r['anchor']}]")
        print(f"   fair 主/平/客 = {f['home']:.3f}/{f['draw']:.3f}/{f['away']:.3f}"
              f"  top1={top1:.3f} | λ={r['lambda']} loss={r['fit_loss']}")
        if r["cross_book_spread_pp"]:
            print(f"   跨盘源价差(体彩−国际,pp) = {r['cross_book_spread_pp']}")
        print(f"   模态比分: {r['top_scores'][:5]}")
        print(f"   大2.5球={r['over25']:.3f} | 主净胜≥2={r['home_by_2plus']:.3f} | "
              f"客净胜≥2={r['away_by_2plus']:.3f}")
        print(f"   净胜分布: {r['margin']}")
        print(f"   体彩让球({r['hhad_line']:+d}): {r['hhad_cover']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
