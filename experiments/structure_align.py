"""§1d 结构对准表 —— 把 26150 手工铺的「档×洞位×价态×标签×单位」格落成脚本。

用法：
    uv run python experiments/structure_align.py --issue 26150          # 足彩期（14 场）
    uv run python experiments/structure_align.py --day 2026-10-25        # 竞彩日板
    …  [--samples experiments/decision-samples-v1.jsonl] [--n-min 20] [--out 路径.md]
    uv run python experiments/structure_align.py --indicator-json '{"id":"F19_unpriced",
        "select":{"field":"research.hole.priced_in","equals":false},"face":"underdog"}'
    uv run python experiments/structure_align.py --indicator 指标.json [--json-out 预筛.json]

做什么：把本期每一场按五个结构维度定位，在决策样本表（只用 `research.prospective=True`
且有赛果的行）里**从最深一层往上找第一格 n≥n_min**，读该格的 热门/平/冷门 开出分布，
和市场热门概率比。末尾一行：要么「无一格改默认动作」，要么列出 |开出率−市场 p1|≥10pp
且 n≥n_min 的格——只展示，不改任何默认动作（2026-10-25 26150 首铺：480 格无一格 n≥20）。

维度（口径与样本表 `derived.*` 一致，band/hole 复用 decision_samples_build 的函数）：
  档 band        A≥80 / B65–79 / b57–64 / C45–56 / D<45（市场热门概率）
  洞位 rel       fav / dog / both / none（洞在热门方 / 弱方 / 两边 / 无）
  价态 priced    价内 / 未价 / ?（hole_location.priced_in）
  标签 label     none / weak / real / strong（strength_balance.underdog_path.strength）
  单位 unit      球员 {spine, goalkeeper} / 结构 {attack, creation, defense, both} / 无

指标两段式第一段（2026-10-26 RULEBOOK「〇」）：`--indicator` 回溯预筛——在同一批前瞻行上选出
指标命中行，算「指标面实开 − 市场该面 P」残差（按日整簇 bootstrap，与 rsi_grading 新实验默认
一致）和选择置换地板（固定 seed、随机抽同样 n 行、200 次；简单残差对 actual 置换不变）；
过地板且 |效应| ≥10pp 才给 suggested_n_min=60，否则只做展示列。
输出给 `nutmeg rsi register --prescreen`。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "decision_samples_build", _HERE / "decision_samples_build.py"
)
_builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_builder)
band_of, fav_of, tri, hole_from_research = (
    _builder.band_of, _builder.fav_of, _builder.tri, _builder.hole_from_research,
)

FACES = ("3", "1", "0")
FACE_WORDS = {"home": "3", "draw": "1", "away": "0", "3": "3", "1": "1", "0": "0"}
PRESCREEN_EFFECT_PP = 10.0      # |效应| ≥ 这个值才登记为拦截候选
PRESCREEN_N_MIN = 60            # 两段式前瞻确认的 n_min
N0_SEED, N0_PERMS = 20260920, 200   # 与 rsi_grading.grade_n0_prospective 同一地板构造
LAYERS = (
    ("档×洞位×价态×标签×单位", 5),
    ("档×洞位×价态×标签", 4),
    ("档×洞位×价态", 3),
    ("档×洞位", 2),
    ("档", 1),
)
PLAYER_UNITS = frozenset({"spine", "goalkeeper"})
STRUCT_UNITS = frozenset({"attack", "creation", "defense", "both"})


def unit_class(unit: object) -> str:
    unit = str(unit or "none")
    if unit in PLAYER_UNITS:
        return "球员"
    if unit in STRUCT_UNITS or "/" in unit:
        return "结构"
    return "无"


def priced_class(priced: object) -> str:
    if priced is True:
        return "价内"
    if priced is False:
        return "未价"
    return "?"


def cell_key(band: str, rel: str, priced: str, label: str, unit: str) -> tuple:
    return (band, rel, priced, label, unit)


def row_cell(row: dict) -> tuple | None:
    """样本表一行 → 五维格键；缺任一维返回 None（不进任何格）。"""
    der = row.get("derived") or {}
    rs = row.get("research") or {}
    band = der.get("band")
    if not band:
        return None
    rel = der.get("hole_rel") or (rs.get("hole") or {}).get("rel") or "none"
    priced = priced_class(der.get("hole_priced", (rs.get("hole") or {}).get("priced_in")))
    label = str(rs.get("upset_label") or "none")
    unit = unit_class(der.get("hole_unit") or (rs.get("hole") or {}).get("unit"))
    return cell_key(band, rel, priced, label, unit)


def rel_outcome(row: dict) -> str | None:
    """赛果相对热门：fav / draw / dog。"""
    face = (row.get("result") or {}).get("face")
    fav = (row.get("derived") or {}).get("fav")
    if face not in FACES or fav not in FACES:
        return None
    if face == fav:
        return "fav"
    if face == "1":
        return "draw"
    return "dog"


def load_samples(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("research") or {}).get("prospective") is not True:
                continue
            if rel_outcome(row) is None or (row.get("belief") or {}).get("market") is None:
                continue
            rows.append(row)
    return rows


def build_grid(rows: list[dict]) -> dict[int, dict[tuple, dict]]:
    """每层：格键前缀 → {n, fav, draw, dog, p_fav_sum}。"""
    grid: dict[int, dict[tuple, dict]] = {k: defaultdict(lambda: Counter()) for _, k in LAYERS}
    for row in rows:
        key = row_cell(row)
        if key is None:
            continue
        out = rel_outcome(row)
        p_fav = (row.get("derived") or {}).get("p_fav") or 0.0
        for _, depth in LAYERS:
            c = grid[depth][key[:depth]]
            c["n"] += 1
            c[out] += 1
            c["p_fav_sum"] += p_fav
    return grid


def locate(grid: dict, key: tuple, n_min: int) -> tuple[str, int, tuple, Counter] | None:
    for name, depth in LAYERS:
        c = grid[depth].get(key[:depth])
        if c and c["n"] >= n_min:
            return name, depth, key[:depth], c
    return None


# ---------------- 指标回溯预筛（两段式第一段）----------------

def _get(row: dict, path: str):
    cur = row
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _selected(row: dict, select: dict) -> bool:
    value = _get(row, select["field"])
    if "equals" in select:
        return value == select["equals"]
    if "in" in select:
        return value in select["in"]
    if "not_equals" in select:
        return value != select["not_equals"]
    raise ValueError("select 需要 equals / in / not_equals 之一")


def indicator_face(row: dict, face) -> str | None:
    """指标面 → 3/1/0。fav|modal＝市场热门；underdog|dog＝热门对面的那一边（不含平）；
    home/draw/away 字面；{"field": 路径} 从行里读（值可为 3/1/0 或 home/draw/away）。"""
    if isinstance(face, dict):
        return FACE_WORDS.get(str(_get(row, face["field"])))
    fav = (row.get("derived") or {}).get("fav")
    if face in ("fav", "modal"):
        return fav if fav in FACES else None
    if face in ("underdog", "dog"):
        return {"3": "0", "0": "3"}.get(fav)
    return FACE_WORDS.get(str(face))


def prescreen_indicator(rows: list[dict], spec: dict, *, n_perm: int = N0_PERMS,
                        seed: int = N0_SEED) -> dict:
    """回溯预筛：命中行的「指标面实开 − 市场 P」残差（pp，按日簇 bootstrap）与选择置换地板。

    地板：N0 打乱的是 actual；简单残差 mean(hit − p) 对 actual 置换不变（mean(hit) 不动），
    所以这里置换的是**选择**——从同一池子随机抽同样 n 行、算同一面的残差，重复 n_perm 次；
    指标残差落在该分布 2.5–97.5 之外才算「比随机选 n 行有区分」。"""
    import random
    import statistics

    from nutmeg.decision.rsi_grading import _cluster_boot_ci

    pool: list[tuple[str, float, float, bool]] = []     # (date, hit, market_p, selected)
    for row in rows:
        face = indicator_face(row, spec["face"])
        market = (row.get("belief") or {}).get("market") or {}
        if face is None or face not in market:
            continue
        actual = (row.get("result") or {}).get("face")
        pool.append((str(row.get("date")), 1.0 if actual == face else 0.0,
                     float(market[face]), _selected(row, spec["select"])))
    hits = [h for h in pool if h[3]]
    out = {"id": spec["id"], "select": spec["select"], "face": spec["face"], "n": len(hits),
           "pool": len(pool), "days": len({d for d, *_ in hits}),
           "effect_pp_threshold": PRESCREEN_EFFECT_PP}
    if len(hits) < 2 or len(pool) <= len(hits):
        out.update(residual_pp=0.0, ci=[0.0, 0.0], floor_pp=0.0, floor_low_pp=0.0,
                   passes_floor=False, effect_abs_pp=0.0, suggested_n_min=None,
                   note="命中行不足 2 或命中＝全池，无法预筛")
        return out
    groups: dict[str, list[float]] = {}
    for day, hit, p, _ in hits:
        groups.setdefault(day, []).append(hit - p)
    point, lo, hi = _cluster_boot_ci(groups, seed=7)
    rng = random.Random(seed)
    floor = []
    for _ in range(n_perm):
        picked = rng.sample(pool, len(hits))
        floor.append(statistics.fmean(h - p for _, h, p, _ in picked) * 100)
    floor.sort()
    p2 = floor[int(0.025 * (len(floor) - 1))]
    p97 = floor[int(0.975 * (len(floor) - 1))]
    residual_pp = point * 100
    passes = residual_pp > p97 or residual_pp < p2
    effect = abs(residual_pp)
    out.update(residual_pp=round(residual_pp, 2), ci=[round(lo * 100, 2), round(hi * 100, 2)],
               floor_pp=round(p97, 2), floor_low_pp=round(p2, 2), passes_floor=passes,
               effect_abs_pp=round(effect, 2),
               suggested_n_min=(PRESCREEN_N_MIN if passes and effect >= PRESCREEN_EFFECT_PP
                                else None))
    return out


def render_prescreen(r: dict) -> str:
    if r["n"] < 2:
        return f"**{r['id']}**：命中 {r['n']} 行，无法预筛。\n"
    verdict = "过地板" if r["passes_floor"] else "不过地板（与随机选同样 n 行分不开）"
    nxt = (f"登记拦截候选，n_min={r['suggested_n_min']}" if r["suggested_n_min"]
           else "只做展示列（不登记拦截候选）")
    return (
        f"**{r['id']}** 回溯预筛：命中 {r['n']}/{r['pool']} 行 · {r['days']} 日，"
        f"残差 {r['residual_pp']:+.1f}pp CI[{r['ci'][0]:+.1f},{r['ci'][1]:+.1f}]，"
        f"选择置换地板 [{r['floor_low_pp']:+.1f},{r['floor_pp']:+.1f}] → {verdict}；"
        f"|效应| {r['effect_abs_pp']:.1f}pp（阈 {r['effect_pp_threshold']:.0f}）→ {nxt}。\n"
    )


# ---------------- 本期场次 ----------------

def legs_of_issue(data_dir: Path, issue: str) -> list[tuple[str, dict]]:
    lb = json.loads((data_dir / "zucai" / f"{issue}-legs-base.json").read_text(encoding="utf-8"))
    legs = lb.get("legs") or lb
    if isinstance(legs, dict):
        return [(str(k), v) for k, v in sorted(legs.items(), key=lambda kv: int(kv[0]))]
    return [(str(i), v) for i, v in enumerate(legs, 1)]


def legs_of_day(data_dir: Path, day: str) -> list[tuple[str, dict]]:
    lb = json.loads(
        (data_dir / "jczq" / "daily" / day / "jczq-legs-base.json").read_text(encoding="utf-8")
    )
    legs = lb.get("legs") or {}
    return [(code, legs[code]) for code in sorted(legs)]


def leg_cell(leg: dict) -> tuple[tuple | None, dict | None, str]:
    """一条腿 → (五维格键, 市场三面, 热门面)。市场取 prior（足彩）或 fair（竞彩 r3＝市场）。"""
    market = tri(leg.get("prior")) or tri(leg.get("fair"))
    if not market:
        return None, None, ""
    fav = fav_of(market)
    hole = hole_from_research(leg, fav) or {}
    path = ((leg.get("strength_balance") or {}).get("underdog_path") or {})
    key = cell_key(
        band_of(market[fav]),
        hole.get("rel") or "none",
        priced_class(hole.get("priced_in")),
        str(path.get("strength") or "none"),
        unit_class(hole.get("unit")),
    )
    return key, market, fav


def render(legs: list[tuple[str, dict]], grid: dict, n_min: int, title: str) -> str:
    lines = [
        f"## §1d 结构对准表 · {title}（样本表前瞻行，n_min={n_min}）",
        "",
        "| 场 | 格（档·洞位·价态·标签·单位） | 落到哪层 | n | 开 热/平/冷 "
        "| 热门开出率 | 市场 p1 | 差 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    flagged = []
    for no, leg in legs:
        key, market, fav = leg_cell(leg)
        name = str(leg.get("name", ""))[:14]
        if key is None:
            lines.append(f"| {no} {name} | — | 无市场价 | | | | | |")
            continue
        hit = locate(grid, key, n_min)
        p1 = market[fav]
        if hit is None:
            lines.append(f"| {no} {name} | {'·'.join(key)} | 无一层 n≥{n_min} | | | | {p1:.0%} | |")
            continue
        layer, _, _, c = hit
        n = c["n"]
        rate = c["fav"] / n
        diff = (rate - p1) * 100
        lines.append(
            f"| {no} {name} | {'·'.join(key)} | {layer} | {n} | {c['fav']}/{c['draw']}/{c['dog']}"
            f" | {rate:.0%} | {p1:.0%} | {diff:+.0f}pp |"
        )
        if abs(diff) >= 10:
            flagged.append((no, name, layer, n, diff))
    lines.append("")
    if flagged:
        lines.append(f"**|差|≥10pp 且 n≥{n_min} 的格（只展示，不改默认动作）：**")
        for no, name, layer, n, diff in flagged:
            lines.append(f"- 场 {no} {name}：{layer} n={n} 差 {diff:+.0f}pp")
    else:
        lines.append("**无一格 |差|≥10pp → 无一格改默认动作。**")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--issue")
    ap.add_argument("--day")
    ap.add_argument("--samples", default=str(_HERE / "decision-samples-v1.jsonl"))
    ap.add_argument("--data-dir", default=str(_HERE.parent / ".nutmeg-data"))
    ap.add_argument("--n-min", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--indicator", help="指标定义 JSON 文件（两段式第一段：回溯预筛）")
    ap.add_argument("--indicator-json", help="内联指标定义 JSON")
    ap.add_argument("--json-out", help="预筛结果 JSON 落盘路径（喂 rsi register --prescreen）")
    a = ap.parse_args()
    if a.indicator or a.indicator_json:
        spec = json.loads(Path(a.indicator).read_text(encoding="utf-8") if a.indicator
                          else a.indicator_json)
        result = prescreen_indicator(load_samples(Path(a.samples)), spec)
        if a.json_out:
            Path(a.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        print(render_prescreen(result))
        print(json.dumps(result, ensure_ascii=False))
        return
    if bool(a.issue) == bool(a.day):
        ap.error("--issue 与 --day 二选一（或给 --indicator）")
    data_dir = Path(a.data_dir)
    legs = legs_of_issue(data_dir, a.issue) if a.issue else legs_of_day(data_dir, a.day)
    rows = load_samples(Path(a.samples))
    grid = build_grid(rows)
    deepest = grid[5]
    md = render(legs, grid, a.n_min, a.issue or a.day)
    md += (
        f"\n样本：前瞻有赛果 {len(rows)} 行；最深层已填 {len(deepest)} 格，"
        f"其中 n≥{a.n_min} 的 {sum(1 for c in deepest.values() if c['n'] >= a.n_min)} 格。\n"
    )
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
