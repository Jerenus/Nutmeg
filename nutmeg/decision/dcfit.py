"""Dixon-Coles 比分矩阵 —— 从去水 fair 反推 λ/ρ 的确定性算术(禁嘴算)。

这是 `scripts/zucai_<issue>_dcfit.py` 系列脚本里逐期复制的那段拟合器的模块化版本,
函数体与既有脚本一致(同参同解),只是把 per-issue 的硬编码(期号、场次映射、文件路径)
剥离出去,让备料任务能对任意一期复用。

**只做算术,不做判断**:输入 = 市场去水 fair(had 三路)+ 可选的体彩 ttg 分布做形状约束,
输出 = 模态比分 / 总进球带 / 净胜分布 / 让球三路 cover。哪一面该押、要不要买保险,
一律不在这里,也不该在任何脚本里。
"""
from __future__ import annotations

import math
from itertools import product

MAXG = 12
"""比分矩阵单边截断。12 球足以覆盖 ~1e-9 以下的尾部,再高只是浪费。"""


def pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def tau(i: int, j: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles 低分格校正:只动 0:0 / 0:1 / 1:0 / 1:1 四格。"""
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def matrix(lh: float, la: float, rho: float) -> dict[tuple[int, int], float]:
    m, s = {}, 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            p = max(0.0, tau(i, j, lh, la, rho) * pois(i, lh) * pois(j, la))
            m[(i, j)] = p
            s += p
    return {k: v / s for k, v in m.items()}


def totals(m: dict) -> dict[int, float]:
    t: dict[int, float] = {}
    for (i, j), p in m.items():
        t[i + j] = t.get(i + j, 0.0) + p
    return t


def outcomes(m: dict) -> tuple[float, float, float]:
    """→ (主胜, 平, 客胜)"""
    return (sum(p for (i, j), p in m.items() if i > j),
            sum(p for (i, j), p in m.items() if i == j),
            sum(p for (i, j), p in m.items() if i < j))


def ttg_bands(m: dict) -> dict[str, float]:
    t = totals(m)
    bands = {f"total_{k}": t.get(k, 0.0) for k in range(7)}
    bands["total_7"] = sum(v for kk, v in t.items() if kk >= 7)
    return bands


def margin_dist(m: dict) -> dict[int, float]:
    d: dict[int, float] = {}
    for (i, j), p in m.items():
        d[i - j] = d.get(i - j, 0.0) + p
    return d


def loss(params: tuple[float, float, float], target: dict) -> float:
    lh, la, rho = params
    if lh <= 0.05 or la <= 0.05 or abs(rho) > 0.5:
        return 1e9
    m = matrix(lh, la, rho)
    ph, pd, pa = outcomes(m)
    out = ((ph - target["ph"]) ** 2 + (pd - target["pd"]) ** 2
           + (pa - target["pa"]) ** 2) * 3
    if target.get("ttg"):
        bands = ttg_bands(m)
        for k, v in target["ttg"].items():
            out += (bands[k] - v) ** 2
    return out


def fit(target: dict, lh0: float = 1.4, la0: float = 1.2,
        fix_rho: float | None = None) -> tuple[tuple[float, float, float], float]:
    """坐标下降 + 步长折半。确定性:同输入必同输出,无随机初始化。"""
    r0 = -0.06 if fix_rho is None else fix_rho
    best = (loss((lh0, la0, r0), target), (lh0, la0, r0))
    lh, la, rho = lh0, la0, r0
    step = 0.4
    for _ in range(12):
        improved = True
        while improved:
            improved = False
            deltas = product([-1, 0, 1], [-1, 0, 1],
                             [0] if fix_rho is not None else [-1, 0, 1])
            for dh, da, dr in deltas:
                cand = (lh + dh * step, la + da * step, rho + dr * step * 0.1)
                val = loss(cand, target)
                if val < best[0] - 1e-12:
                    best = (val, cand)
                    lh, la, rho = cand
                    improved = True
        step /= 2
    return best[1], best[0]


def hhad_cover(md: dict[int, float], line: str | None) -> dict | None:
    """体彩让球三路 cover。line 形如 "-1"(主队让 1 球)/"+1"(主队受让)。

    ⚠️体彩 hhad 是三路胜平负,不是亚盘 —— 整数盘热门胜 1 球落入「让平」档。
    """
    if not line:
        return None
    n = int(float(line))
    return {
        "line": line,
        "让胜": round(sum(v for k, v in md.items() if k + n > 0), 4),
        "让平": round(sum(v for k, v in md.items() if k + n == 0), 4),
        "让负": round(sum(v for k, v in md.items() if k + n < 0), 4),
    }


def fit_match(fair_had: dict, *, ttg_fair: dict | None = None,
              hhad_line: str | None = None) -> dict:
    """单场:去水 fair(+可选 ttg 形状约束)→ 完整确定性算术包。

    ``fair_had`` 需含 home/draw/away 三键(和为 1)。``ttg_fair`` 为体彩总进球
    去水分布(键 total_0..total_7),缺失时 ρ 固定在 -0.06(无形状信息可拟)。
    """
    target = {"ph": fair_had["home"], "pd": fair_had["draw"], "pa": fair_had["away"],
              "ttg": ttg_fair}
    (lh, la, rho), fit_loss = fit(target, fix_rho=None if ttg_fair else -0.06)
    mx = matrix(lh, la, rho)
    ph, pd, pa = outcomes(mx)
    md = margin_dist(mx)
    return {
        "ttg_anchor": bool(ttg_fair),
        "lambda": [round(lh, 3), round(la, 3), round(rho, 3)],
        "fit_loss": round(fit_loss, 6),
        "fair_had": {k: round(v, 4) for k, v in fair_had.items()},
        "dc_had": [round(ph, 4), round(pd, 4), round(pa, 4)],
        "top_scores": [[f"{i}:{j}", round(p, 4)]
                       for (i, j), p in sorted(mx.items(), key=lambda kv: -kv[1])[:6]],
        "ttg_bands": {k: round(v, 4) for k, v in ttg_bands(mx).items()},
        "over25": round(sum(v for kk, v in totals(mx).items() if kk >= 3), 4),
        "margin": {str(k): round(v, 4) for k, v in sorted(md.items()) if -4 <= k <= 4},
        "home_by_2plus": round(sum(v for kk, v in md.items() if kk >= 2), 4),
        "away_by_2plus": round(sum(v for kk, v in md.items() if kk <= -2), 4),
        "hhad_cover": hhad_cover(md, hhad_line),
    }
