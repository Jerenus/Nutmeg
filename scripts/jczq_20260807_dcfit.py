"""2026-08-07 周五001-010 — Dixon-Coles fit from de-juiced fair (禁嘴算).

锚口径:had 用**欧赔去水 fair**(apifootball,最 sharp,亦是 CLV 先验端);
ttg 分布只有体彩有,故用 sporttery ttg 全分布 0..7+。两者同为读时快照。
输出: λ/ρ、模态比分、净胜分布、体彩 3 路让球 cover、大 2.5 球概率。

复用 scripts/jczq_20260729_dcfit.py 的拟合器,只改锚来源与场次表。
"""
import json
import math
from itertools import product
from pathlib import Path

MAXG = 12
ROOT = Path(__file__).parents[1]
SNAPS = ROOT / ".nutmeg-data/jczq/decision/snapshots.jsonl"
RUN_DATE = "2026-08-07"

TICAI_LINE = {                      # 体彩让球线(主队 + line 口径,3 路)
    "周五001": 1, "周五002": -1, "周五003": -1, "周五004": -1, "周五005": -1,
    "周五006": 1, "周五007": -1, "周五008": -1, "周五009": -1, "周五010": 1,
}
MATCH = {
    "周五001": ("M-2026-08-07-横滨水手-鹿岛鹿角", "横滨水手 vs 鹿岛鹿角(日职)"),
    "周五002": ("M-2026-08-07-大阪钢巴-浦和红钻", "大阪钢巴 vs 浦和红钻(日职)"),
    "周五003": ("M-2026-08-07-塞伊奈-赫尔火花", "塞伊奈约基 vs 赫尔辛基火花(芬超)"),
    "周五004": ("M-2026-08-07-桑纳菲-奥斯kfum", "桑纳菲尤德 vs KFUM奥斯陆(挪超)"),
    "周五005": ("M-2026-08-07-坎布尔-sbv精英", "坎布尔 vs 精英队(荷甲首轮)"),
    "周五006": ("M-2026-08-07-奥斯-布雷达", "TOP奥斯 vs NAC布雷达(荷乙)"),
    "周五007": ("M-2026-08-07-埃门-罗达jc", "埃门 vs 罗达JC(荷乙)"),
    "周五008": ("M-2026-08-07-波鸿-柏林赫塔", "波鸿 vs 柏林赫塔(德乙)"),
    "周五009": ("M-2026-08-07-米堡-雷克斯", "米德尔斯堡 vs 雷克瑟姆(英联赛杯)"),
    "周五010": ("M-2026-08-07-埃斯托里-法马利康", "埃斯托里尔 vs 法马利康(葡超首轮)"),
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
    """{竞彩号: {"had": 欧赔fair, "ttg": 体彩fair}} —— 取当日最新读时快照。"""
    euro, tc = {}, {}
    for raw in SNAPS.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        s = json.loads(raw)
        if s.get("kind") != "read_time" or RUN_DATE not in s.get("taken_at", ""):
            continue
        for num, (mid, _) in MATCH.items():
            if s.get("match_id") != mid:
                continue
            fair = s.get("fair") or {}
            if s.get("source") == "apifootball" and fair.get("had"):
                euro[num] = fair["had"]
            if s.get("source") == "sporttery" and fair.get("ttg"):
                tc[num] = fair["ttg"]
    return euro, tc


def main():
    euro, tc = load_fairs()
    report = {}
    for num, (_mid, name) in MATCH.items():
        if num not in euro or num not in tc:
            print(f"{num} 缺锚(euro={num in euro} ttg={num in tc}),跳过")
            continue
        had = euro[num]
        tg = {"ph": had["home"], "pd": had["draw"], "pa": had["away"], "ttg": tc[num]}
        (lh, la, r), fit_loss = fit(tg)
        m = matrix(lh, la, r)
        ph, pd, pa = outcomes(m)
        md = margin_dist(m)
        line = TICAI_LINE[num]
        w, pu, lo = hhad_cover(m, line)
        report[num] = {
            "name": name,
            "lambda": [round(lh, 3), round(la, 3), round(r, 3)],
            "fit_loss": round(fit_loss, 6),
            "fair_had_euro": {k: round(v, 4) for k, v in had.items()},
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
    for num, r in report.items():
        f = r["fair_had_euro"]
        print(f"\n{num} {r['name']}")
        print(f"   λ={r['lambda']} 拟合损失={r['fit_loss']} | 欧赔fair 主/平/客="
              f"{f['home']:.3f}/{f['draw']:.3f}/{f['away']:.3f}")
        print(f"   模态比分: {r['top_scores'][:5]}")
        print(f"   大2.5球={r['over25']:.3f} | 主净胜≥2={r['home_by_2plus']:.3f} | "
              f"客净胜≥2={r['away_by_2plus']:.3f}")
        print(f"   净胜分布: {r['margin']}")
        print(f"   体彩让球({r['hhad_line']:+d}): {r['hhad_cover']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
