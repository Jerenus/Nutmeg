# ruff: noqa: E501
"""因子/标签组合挖掘（2026-11-10，Jun：休赛日回顾近期分析，找更显著的指标组合）。只读，不进任何决策层。

四轮：
  R1 单因子扫描：每个「因子=取值」格，对 热门/平/弱方 三个面算残差（实开 − 市场 P），
     与同池其余行比（超额＝格残差 − 池残差），z 用无放回抽样方差，BH-FDR 控多重比较。
  R2 两两组合：R1 里 n≥MIN_N 的格两两取交集，同口径。
  R3 时间切分复核：前 60% 日期开发、后 40% 验证；两段同号且验证段 |z|≥1.96 才算「站住」。
     对 R1/R2 里 q≤0.2 的格再跑：按日整簇 bootstrap CI + 选择置换地板（与 structure_align 同口径）。
  R4 多变量：市场 logit 作 offset 的岭逻辑回归，按日期前滚（walk-forward），
     样本外 logloss 对比「市场」「市场+截距」——回答「这些标签合起来能不能比市场准」。

池：A＝research.prospective 且有赛果（研究标签）；B＝全部有赛果有市场价（只测价格/场景因子）。
用法：uv run python experiments/prescreen/2026-11-10-factor-mining.py [--json-out 路径]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "experiments" / "decision-samples-v1.jsonl"
MIN_N = 40            # 单格最少行
MIN_N_PAIR = 30       # 组合格最少行
TARGETS = ("fav", "draw", "dog")
SEED = 20261110

TOP5 = ("serie a", "la liga", "西甲", "premier league", "英超", "bundesliga", "德甲", "法甲", "ligue 1", "意甲")
SECOND = ("英冠", "championship", "法乙", "ligue 2", "德乙", "2. bundesliga", "j2", "eerste", "荷乙", "意乙", "西乙")
EURO = ("欧冠", "欧罗巴", "欧协联", "champions league", "europa", "conference")
NATIONAL = ("欧国联", "国际赛", "nations league", "世预", "友谊", "亚运", "世界杯", "欧洲杯", "非洲杯", "亚洲杯")


def comp_group(name: str | None) -> str | None:
    if not name:
        return None
    low = name.lower()
    if any(k in low for k in SECOND):
        return "second"
    if any(k in low for k in EURO):
        return "euro"
    if any(k in low for k in NATIONAL):
        return "national"
    if any(k in low for k in TOP5) and "brasil" not in low:
        return "top5"
    if "杯" in low or "cup" in low or "copa" in low:
        return "cup"
    return "other"


def g(row: dict, path: str):
    cur = row
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def rel_side(value, fav: str) -> str | None:
    """home/away/3/0 → fav/dog；其余原样。"""
    if value is None:
        return None
    v = str(value)
    m = {"home": "3", "away": "0", "draw": "1"}.get(v, v)
    if m in ("3", "0"):
        return "fav" if m == fav else "dog"
    if m == "1":
        return "draw"
    return v


def features(row: dict) -> tuple[dict, dict]:
    """→ (类别因子, 数值因子)。数值因子之后按池内三分位切。"""
    d, r = row.get("derived") or {}, row.get("research") or {}
    fav = d.get("fav")
    dog = {"3": "0", "0": "3"}.get(fav)
    cat: dict = {}
    num: dict = {}
    cat["band"] = d.get("band")
    cat["fav_side"] = {"3": "home", "0": "away"}.get(fav)
    cat["comp"] = comp_group(row.get("competition"))
    cat["src"] = "zucai" if row.get("zucai") else "jczq_only"
    ko = row.get("kickoff")
    if ko:
        t = datetime.fromisoformat(ko)
        cat["weekday"] = "weekend" if t.weekday() in (5, 6) or (t.weekday() == 0 and t.hour < 8) else "midweek"
        cat["hour"] = "night_0_8" if t.hour < 8 else ("day_8_20" if t.hour < 20 else "eve_20_24")
    mk = g(row, "belief.market") or {}
    if mk and dog:
        num["p_draw"] = mk.get("1")
        num["p_dog"] = mk.get(dog)
    sp = g(row, "price_sporttery.fair") or {}
    if sp and fav in sp and fav in mk:
        num["sporttery_minus_mkt_fav"] = (sp[fav] - mk[fav]) * 100
        if "1" in sp and "1" in mk:
            num["sporttery_minus_mkt_draw"] = (sp["1"] - mk["1"]) * 100
    rt, op = g(row, "price_read_time.fair") or {}, g(row, "price_read_time.opening") or {}
    if fav in rt and fav in op:
        num["open_to_read_fav"] = (rt[fav] - op[fav]) * 100
        if "1" in rt and "1" in op:
            num["open_to_read_draw"] = (rt["1"] - op["1"]) * 100
    idr = row.get("intl_drift") or {}
    if idr and fav in ("3", "0"):
        v = idr.get("drift_home_pp" if fav == "3" else "drift_away_pp")
        if v is not None:
            num["intl_drift_fav"] = v
        num["intl_dispersion"] = idr.get("dispersion_pp")
        num["intl_drift_draw"] = idr.get("drift_draw_pp")
    pm = row.get("polymarket") or {}
    if pm:
        num["pm_rank"] = pm.get("rank")
        vs = pm.get("vs_market_pp") or {}
        if fav in ("3", "0"):
            num["pm_vs_mkt_fav"] = vs.get("home" if fav == "3" else "away")
        num["pm_vs_mkt_draw"] = vs.get("draw")
    ld = row.get("load") or {}
    if ld and fav in ("3", "0"):
        f_, d_ = ("home", "away") if fav == "3" else ("away", "home")
        fr, dr = g(ld, f"{f_}.rest_days"), g(ld, f"{d_}.rest_days")
        if fr is not None and dr is not None and max(fr, dr) <= 30:
            num["rest_fav_minus_dog"] = fr - dr
            cat["fav_short_rest"] = "rest<=4" if fr <= 4 else "rest>=5"
        fm, dm = g(ld, f"{f_}.matches_14d"), g(ld, f"{d_}.matches_14d")
        if fm is not None and dm is not None:
            num["m14_fav_minus_dog"] = fm - dm
    if not r:
        return cat, num
    # —— 研究标签 ——
    cat["anchor"] = r.get("anchor_integrity")
    cat["market_read"] = r.get("market_read")
    cat["hole_rel"] = d.get("hole_rel")
    hu = d.get("hole_unit")
    cat["hole_unit"] = None if hu is None else ("player" if hu in ("spine", "goalkeeper") else
                                                 ("none" if hu == "none" else "struct"))
    hp = g(r, "hole.priced_in")
    cat["hole_priced"] = {True: "priced", False: "unpriced"}.get(hp) if isinstance(hp, bool) else None
    cat["upset_label"] = r.get("upset_label")
    if d.get("underdog_is_market_dog") is not None:
        cat["udog_is_mkt_dog"] = str(d.get("underdog_is_market_dog"))
    v = r.get("verdict")
    if v:
        cat["verdict"] = {"home_edge": rel_side("home", fav), "away_edge": rel_side("away", fav)}.get(v, v)
    cat["stance"] = rel_side(r.get("stance_face"), fav) if r.get("stance_face") else None
    cat["stance_structure"] = r.get("stance_structure")
    cat["stance_cover"] = rel_side(r.get("stance_cover"), fav) if r.get("stance_cover") else None
    lq = r.get("license_questions") or {}
    k = 0
    for q, val in lq.items():
        if val is None:
            continue
        cat[f"lq_{q}"] = str(val)
        k += 1 if val is True or val == 1 else 0
    if lq:
        cat["lq_k"] = f"k{k}"
    dp = r.get("death_proofs") or {}
    if dog and dp.get(dog) is not None:
        cat["death_dog"] = str(dp[dog])[:1]
    if dp.get("1") is not None:
        cat["death_draw"] = str(dp['1'])[:1]
    num["confidence"] = r.get("confidence")
    for f in ("directional_flags", "nondirectional_flags", "crash_markers", "underdog_routes"):
        if r.get(f) is not None:
            cat[f"has_{f}"] = "yes" if r.get(f) else "no"
    if r.get("premise_corrections_n") is not None:
        cat["has_premise_corr"] = "yes" if r["premise_corrections_n"] else "no"
    for item, cell in (r.get("rubric") or {}).items():
        if isinstance(cell, dict) and cell.get("answer") is not None and not cell.get("abstain"):
            cat[f"rb_{item}"] = rel_side(cell["answer"], fav)
    ka = g(row, "reader_b.kappa.agree")
    if ka is not None:
        num["kappa_agree"] = ka
    tags = r.get("team_tags") or {}
    if tags and fav in ("3", "0"):
        f_, d_ = ("home", "away") if fav == "3" else ("away", "home")
        cat["tags_fav"] = "yes" if tags.get(f_) else "no"
        cat["tags_dog"] = "yes" if tags.get(d_) else "no"
    return cat, num


def load() -> list[dict]:
    rows = []
    for line in SAMPLES.read_text(encoding="utf-8").splitlines():
        x = json.loads(line)
        d = x.get("derived") or {}
        mk = g(x, "belief.market") or {}
        face = g(x, "result.face")
        fav = d.get("fav")
        if not face or fav not in ("3", "0") or not all(f in mk for f in "310"):
            continue
        dog = "0" if fav == "3" else "3"
        cat, num = features(x)
        rows.append(dict(
            key=x["key"], date=x["date"], prospective=bool(g(x, "research.prospective")),
            res={"fav": (face == fav) - mk[fav], "draw": (face == "1") - mk["1"], "dog": (face == dog) - mk[dog]},
            p={"fav": mk[fav], "draw": mk["1"], "dog": mk[dog]},
            hit={"fav": face == fav, "draw": face == "1", "dog": face == dog},
            cat=cat, num=num))
    return rows


def add_terciles(rows: list[dict]) -> None:
    names = sorted({k for r in rows for k, v in r["num"].items() if v is not None})
    for name in names:
        vals = np.array([r["num"][name] for r in rows if r["num"].get(name) is not None], dtype=float)
        if len(vals) < 3 * MIN_N:
            continue
        lo, hi = np.quantile(vals, [1 / 3, 2 / 3])
        if lo == hi:      # 离散量（如 confidence）：按值分
            for r in rows:
                v = r["num"].get(name)
                if v is not None:
                    r["cat"][name] = f"={v:g}"
            continue
        for r in rows:
            v = r["num"].get(name)
            if v is not None:
                r["cat"][name] = (f"low(<{lo:.1f})" if v < lo else (f"high(>{hi:.1f})" if v > hi else "mid"))


def level_masks(rows: list[dict], min_n: int) -> dict[tuple, np.ndarray]:
    idx = defaultdict(list)
    for i, r in enumerate(rows):
        for k, v in r["cat"].items():
            if v is not None:
                idx[(k, str(v))].append(i)
    out = {}
    for key, ii in idx.items():
        if min_n <= len(ii) <= len(rows) - min_n:
            m = np.zeros(len(rows), bool)
            m[ii] = True
            out[key] = m
    return out


def z_excess(res: np.ndarray, mask: np.ndarray, var0: np.ndarray) -> tuple[float, float, float]:
    """格残差、相对池其余行的超额、z。方差用市场零假设下的 p(1−p)，不用样本方差——
    否则「一场没开」的小格样本方差≈0，z 会虚高到 −10（首跑踩过）。"""
    a, b = res[mask], res[~mask]
    ex = a.mean() - b.mean()
    se = math.sqrt(var0[mask].mean() / len(a) + var0[~mask].mean() / len(b))
    return a.mean(), ex, ex / se if se else 0.0


def p_of_z(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def bh(pvals: list[float]) -> list[float]:
    n = len(pvals)
    order = sorted(range(n), key=lambda i: pvals[i])
    q = [0.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * n / rank)
        q[i] = prev
    return q


def cluster_boot(res: np.ndarray, dates: np.ndarray, mask: np.ndarray, rng, n=2000) -> tuple[float, float]:
    by = defaultdict(list)
    for v, d in zip(res[mask], dates[mask], strict=True):
        by[d].append(v)
    groups = [np.array(v) for v in by.values()]
    sums = np.array([x.sum() for x in groups])
    cnts = np.array([len(x) for x in groups])
    pick = rng.integers(0, len(groups), size=(n, len(groups)))
    means = sums[pick].sum(1) / cnts[pick].sum(1)
    return float(np.quantile(means, .025)), float(np.quantile(means, .975))


def perm_floor(res: np.ndarray, k: int, rng, n=2000) -> tuple[float, float]:
    means = np.array([res[rng.choice(len(res), k, replace=False)].mean() for _ in range(n)])
    return float(np.quantile(means, .025)), float(np.quantile(means, .975))


def scan(rows: list[dict], label: str, pair: bool) -> list[dict]:
    masks = level_masks(rows, MIN_N)
    res = {t: np.array([r["res"][t] for r in rows]) for t in TARGETS}
    var0 = {t: np.array([r["p"][t] * (1 - r["p"][t]) for r in rows]) for t in TARGETS}
    dates = np.array([r["date"] for r in rows])
    order = np.argsort(dates, kind="stable")
    cut_date = dates[order][int(len(rows) * 0.6)]
    dev, val = dates < cut_date, dates >= cut_date
    cells: list[tuple[tuple, np.ndarray]] = [((k,), m) for k, m in masks.items()]
    if pair:
        cells = []
        for (ka, ma), (kb, mb) in itertools.combinations(sorted(masks.items()), 2):
            if ka[0] == kb[0]:
                continue
            m = ma & mb
            n = int(m.sum())
            # 交集要显著小于任一边，否则只是把单因子再数一遍
            if n >= MIN_N_PAIR and n <= 0.8 * min(ma.sum(), mb.sum()) and (~m).sum() >= MIN_N:
                cells.append(((ka, kb), m))
    out = []
    for keys, m in cells:
        for t in TARGETS:
            mean, ex, z = z_excess(res[t], m, var0[t])
            rec = dict(pool=label, cell=" & ".join(f"{k}={v}" for k, v in keys), target=t, n=int(m.sum()),
                       resid_pp=round(mean * 100, 1), excess_pp=round(ex * 100, 1), z=round(z, 2), p=p_of_z(z),
                       _mask=m)
            for nm, part in (("dev", dev), ("val", val)):
                mm = m & part
                if mm.sum() >= 10 and (part & ~m).sum() >= 10:
                    _, e2, z2 = z_excess(res[t][part], m[part], var0[t][part])
                    rec[nm] = dict(n=int(mm.sum()), excess_pp=round(e2 * 100, 1), z=round(z2, 2))
            out.append(rec)
    qs = bh([r["p"] for r in out])
    for r, q in zip(out, qs, strict=True):
        r["q"] = round(q, 3)
        d_, v_ = r.get("dev"), r.get("val")
        r["holds"] = bool(d_ and v_ and d_["excess_pp"] * v_["excess_pp"] > 0 and abs(v_["z"]) >= 1.96)
    return out


def confirm(rows: list[dict], recs: list[dict]) -> None:
    rng = np.random.default_rng(SEED)
    dates = np.array([r["date"] for r in rows])
    for rec in recs:
        res = np.array([r["res"][rec["target"]] for r in rows])
        lo, hi = cluster_boot(res, dates, rec["_mask"], rng)
        f_lo, f_hi = perm_floor(res, rec["n"], rng)
        rec["ci_pp"] = [round(lo * 100, 1), round(hi * 100, 1)]
        rec["floor_pp"] = [round(f_lo * 100, 1), round(f_hi * 100, 1)]
        rec["passes_floor"] = not (f_lo * 100 <= rec["resid_pp"] <= f_hi * 100)
        rec["days"] = int(len(set(dates[rec["_mask"]])))


# ——— R4 多变量 ———
def design(rows: list[dict], min_n: int = 60) -> tuple[np.ndarray, list[str]]:
    masks = level_masks(rows, min_n)
    names = [f"{k}={v}" for k, v in sorted(masks)]
    X = np.stack([masks[k].astype(float) for k in sorted(masks)], 1) if masks else np.zeros((len(rows), 0))
    return X, names


def fit_logit(X: np.ndarray, y: np.ndarray, off: np.ndarray, lam: float, iters: int = 60) -> np.ndarray:
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    pen = np.full(Xb.shape[1], lam)
    pen[0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(off + Xb @ w)))
        grad = Xb.T @ (p - y) + pen * w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(pen) + 1e-8 * np.eye(len(w))
        step = np.linalg.solve(H, grad)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def walk_forward(rows: list[dict], target: str, lams=(3.0, 10.0, 30.0, 100.0), folds: int = 5) -> dict:
    rows = sorted(rows, key=lambda r: r["date"])
    X, names = design(rows)
    y = np.array([float(r["hit"][target]) for r in rows])
    p = np.clip(np.array([r["p"][target] for r in rows]), 1e-4, 1 - 1e-4)
    off = np.log(p / (1 - p))
    dates = np.array([r["date"] for r in rows])
    uniq = sorted(set(dates))
    start = int(len(uniq) * 0.4)
    edges = np.linspace(start, len(uniq), folds + 1).astype(int)

    def ll(pred, yy):
        pred = np.clip(pred, 1e-6, 1 - 1e-6)
        return -(yy * np.log(pred) + (1 - yy) * np.log(1 - pred))

    per: dict[str, list[np.ndarray]] = defaultdict(list)
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        if a == b:
            continue
        tr, te = dates < uniq[a], (dates >= uniq[a]) & (dates <= uniq[b - 1])
        per["market"].append(ll(p[te], y[te]))
        w0 = fit_logit(np.zeros((tr.sum(), 0)), y[tr], off[tr], 0.0)
        per["market+intercept"].append(ll(1 / (1 + np.exp(-(off[te] + w0[0]))), y[te]))
        for lam in lams:
            w = fit_logit(X[tr], y[tr], off[tr], lam)
            pred = 1 / (1 + np.exp(-(off[te] + np.hstack([np.ones((te.sum(), 1)), X[te]]) @ w)))
            per[f"ridge λ={lam:g}"].append(ll(pred, y[te]))
    base = np.concatenate(per["market"])
    out = {"n_test": int(len(base)), "n_features": len(names), "market_logloss": round(float(base.mean()), 4)}
    rng = np.random.default_rng(SEED)
    for name, parts in per.items():
        if name == "market":
            continue
        diff = np.concatenate(parts) - base            # 负＝比市场好
        boots = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
        out[name] = dict(delta_logloss=round(float(diff.mean()), 4),
                         ci=[round(float(np.quantile(boots, .025)), 4), round(float(np.quantile(boots, .975)), 4)])
    w = fit_logit(X, y, off, 30.0)
    top = sorted(zip(names, w[1:], strict=True), key=lambda kv: -abs(kv[1]))[:8]
    out["top_coef_full_fit(λ=30)"] = [(n_, round(float(c), 3)) for n_, c in top]
    return out


def split_corr(recs: list[dict]) -> tuple[int, float, float]:
    """全体格：开发段超额 vs 验证段超额 的相关与同号率。有真结构→明显为正；全是噪声→≈0 / 50%。"""
    pts = [(r["dev"]["excess_pp"], r["val"]["excess_pp"]) for r in recs
           if r.get("dev") and r.get("val") and r["dev"]["n"] >= 15 and r["val"]["n"] >= 15]
    if len(pts) < 10:
        return len(pts), float("nan"), float("nan")
    a = np.array(pts)
    return len(pts), float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), float((a[:, 0] * a[:, 1] > 0).mean())


def show(title: str, recs: list[dict], k: int = 25) -> None:
    n_c, c, same = split_corr(recs)
    print(f"\n（开发段 vs 验证段超额：{n_c} 格，相关 r={c:+.2f}，同号率 {same:.0%}）")
    print(f"\n### {title}（共 {len(recs)} 个检验；q≤0.10: {sum(r['q'] <= .10 for r in recs)}，"
          f"q≤0.20: {sum(r['q'] <= .20 for r in recs)}，时间切分站住: {sum(r['holds'] for r in recs)}；"
          f"5% 水平期望假阳性 ≈{len(recs) * .05:.0f}）")
    print("| 格 | 面 | n | 残差 | 超额 | z | q | 开发段 | 验证段 | 站住 | 日簇 CI | 地板 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(recs, key=lambda r: r["p"])[:k]:
        d_, v_ = r.get("dev"), r.get("val")
        def f(s):
            return f"{s['excess_pp']:+.1f} (n{s['n']}, z{s['z']:+.1f})" if s else "—"
        ci = f"[{r['ci_pp'][0]:+.1f},{r['ci_pp'][1]:+.1f}]" if "ci_pp" in r else ""
        fl = (f"[{r['floor_pp'][0]:+.1f},{r['floor_pp'][1]:+.1f}] {'过' if r['passes_floor'] else '不过'}"
              if "floor_pp" in r else "")
        print(f"| {r['cell']} | {r['target']} | {r['n']} | {r['resid_pp']:+.1f} | {r['excess_pp']:+.1f} | "
              f"{r['z']:+.2f} | {r['q']:.3f} | {f(d_)} | {f(v_)} | {'✓' if r['holds'] else ''} | {ci} | {fl} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out")
    args = ap.parse_args()
    allrows = load()
    pools = {"A 前瞻研究": [r for r in allrows if r["prospective"]], "B 全量价格": allrows}
    report: dict = {}
    for label, rows in pools.items():
        if label.startswith("B"):          # B 池只留价格/场景因子
            keep = {"band", "fav_side", "comp", "src", "weekday", "hour"}
            for r in rows:
                r["cat"] = {k: v for k, v in r["cat"].items() if k in keep}
                r["num"] = {k: v for k, v in r["num"].items()
                            if k in ("p_draw", "p_dog", "sporttery_minus_mkt_fav", "sporttery_minus_mkt_draw",
                                     "open_to_read_fav", "open_to_read_draw")}
            rows = [dict(r, cat=dict(r["cat"])) for r in rows]
        else:
            rows = [dict(r, cat=dict(r["cat"])) for r in rows]
        add_terciles(rows)
        n_days = len({r["date"] for r in rows})
        base = {t: round(float(np.mean([r["res"][t] for r in rows])) * 100, 1) for t in TARGETS}
        print(f"\n## 池 {label}：n={len(rows)}，{n_days} 个比赛日，池残差 {base}")
        r1 = scan(rows, label, pair=False)
        r2 = scan(rows, label, pair=True)
        for recs in (r1, r2):
            confirm(rows, sorted(recs, key=lambda r: r["p"])[:25])
        show(f"R1 单因子 · {label}", r1)
        show(f"R2 两两组合 · {label}", r2)
        held = [r for r in r1 + r2 if r["holds"]]
        confirm(rows, [r for r in held if "ci_pp" not in r])
        show(f"R3 时间切分站住的格 · {label}", held, k=40)
        report[label] = dict(n=len(rows), days=n_days, pool_resid=base,
                             r1=[{k: v for k, v in r.items() if k != "_mask"} for r in sorted(r1, key=lambda r: r["p"])[:60]],
                             r2=[{k: v for k, v in r.items() if k != "_mask"} for r in sorted(r2, key=lambda r: r["p"])[:100]],
                             held=[{k: v for k, v in r.items() if k != "_mask"} for r in held],
                             tests=dict(r1=len(r1), r2=len(r2)))
        print(f"\n### R4 多变量前滚 · {label}")
        for t in TARGETS:
            wf = walk_forward(rows, t)
            report[label][f"r4_{t}"] = wf
            print(f"- {t}: " + json.dumps(wf, ensure_ascii=False))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
