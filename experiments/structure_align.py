"""§1d 结构对准表 —— 把 26150 手工铺的「档×洞位×价态×标签×单位」格落成脚本。

用法：
    uv run python experiments/structure_align.py --issue 26150          # 足彩期（14 场）
    uv run python experiments/structure_align.py --day 2026-10-25        # 竞彩日板
    …  [--samples experiments/decision-samples-v1.jsonl] [--n-min 20] [--out 路径.md]

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
    a = ap.parse_args()
    if bool(a.issue) == bool(a.day):
        ap.error("--issue 与 --day 二选一")
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
