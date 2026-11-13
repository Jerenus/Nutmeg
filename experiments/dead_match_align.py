"""§1e 近期死亡场同构对位 —— 26152 首铺（2026-10-28 Jun：
「参考近期死亡的比赛，找到和今天相同结构比赛」，
与 §1c 翻车面 / §1d 结构对准放在一起，常驻 A 三屏）。

用法：
    uv run python experiments/dead_match_align.py --issue 26152 \
        [--recent 7] [--samples …] [--out 路径.md]

做什么：
  1. 「死」＝机器研究票形被开出排除面（双选）或单选未开（单死）——
     与 §2 死法清单同一口径，不是「热门没开」；
  2. 本期每场按 档 × 锚方完整度(pass/fail/symmetric_damage) × 洞位 × 价态 × 标签 定位
     （比 §1d 多「锚方完整度」一维、
     少「单位」一维），列出目标期之前最近 N 期足彩同格的每一场
     （☠ 死 / ✗ 翻车但票活 / ✓ 开热门）；同格近 N 期为空时
     退到 档 × 锚方完整度 × 洞位；右列给全前瞻样本同格的 n · 翻车率 · 排除面开率作底；
  3. 死法形状：按票形（单 / 双·排非热门胜 / 双·排平 / 双·排热门）统计近 N 期与全前瞻的死亡率，
     对照排除面的市场 P 均值。
只展示，不改任何默认动作，不进六条件；n 都小，它只回答「今天哪几场长得像最近刚死过的那种」。
样本＝`experiments/decision-samples-v1.jsonl` 只取 `research.prospective=True` 行；
**出包前先重建**样本表
（`decision_samples_build.py --to <今日>`），本期 14 行与上一期赛果都从那里来；
缺官方开奖的期赛果不全，表头会写出缺口。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("structure_align", _HERE / "structure_align.py")
_sa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_sa)
priced_class, rel_outcome = _sa.priced_class, _sa.rel_outcome

FACES = ("3", "1", "0")
MARK = {"dead": "☠", "upset": "✗", "fav": "✓"}


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("research") or {}).get("prospective") is not True:
                continue
            if (row.get("belief") or {}).get("market") is None:
                continue
            rows.append(row)
    return rows


def sig(row: dict, depth: int = 5) -> tuple:
    der = row.get("derived") or {}
    rs = row.get("research") or {}
    key = (
        str(der.get("band") or "?"),
        str(rs.get("anchor_integrity") or "unknown"),
        str(der.get("hole_rel") or (rs.get("hole") or {}).get("rel") or "none"),
        priced_class(der.get("hole_priced", (rs.get("hole") or {}).get("priced_in"))),
        str(rs.get("upset_label") or "none"),
    )
    return key[:depth]


def ticket(row: dict) -> tuple[str, set[str]] | None:
    """研究票形 → (single|double|full, 面集合)；未知/不完整表态返回 None。"""
    rs = row.get("research") or {}
    structure = rs.get("stance_structure")
    if structure == "full":
        return "full", set(FACES)
    face = rs.get("stance_face")
    if face not in FACES:
        return None
    if structure == "single":
        return "single", {face}
    cover = rs.get("stance_cover")
    if structure == "double" and cover in FACES and cover != face:
        return "double", {face, cover}
    return None


def death(row: dict) -> str | None:
    """None＝票活或无赛果；'单死' / '排除面开'。"""
    t = ticket(row)
    res = (row.get("result") or {}).get("face")
    if t is None or res not in FACES:
        return None
    kind, faces = t
    if res in faces:
        return None
    return "单死" if kind == "single" else "排除面开"


def outcome_mark(row: dict) -> str | None:
    if (row.get("result") or {}).get("face") not in FACES:
        return None
    if death(row):
        return MARK["dead"]
    return MARK["upset"] if rel_outcome(row) != "fav" else MARK["fav"]


def ticket_form(row: dict) -> tuple[str, str | None]:
    """票形 → (类别, 排除面)。单选排除面不唯一，返回 None。"""
    t = ticket(row)
    if t is None:
        return "", None
    kind, faces = t
    if kind == "full":
        return "包", None
    if kind == "single" or len(faces) != 2:
        return "单", None
    excluded = next(f for f in FACES if f not in faces)
    fav = (row.get("derived") or {}).get("fav")
    if excluded == "1":
        return "双·排平", excluded
    if excluded == fav:
        return "双·排热门", excluded
    return "双·排非热门胜", excluded


def recent_issues(rows: list[dict], issue: str, n: int) -> list[str]:
    seen = {
        str((r.get("zucai") or {}).get("issue"))
        for r in rows
        if (r.get("zucai") or {}).get("issue") and (r.get("result") or {}).get("face") in FACES
    }
    return sorted(i for i in seen if i < issue)[-n:]


def _label(row: dict) -> str:
    z = row.get("zucai") or {}
    t = ticket(row)
    tk = "".join(sorted(t[1], key=FACES.index)) if t else "—"
    p = (row.get("derived") or {}).get("p_fav") or 0.0
    return (f"{outcome_mark(row)} {z.get('issue')}-{z.get('no')} "
            f"{row.get('home')}-{row.get('away')}"
            f" {p:.0%} 票{tk} 开{(row.get('result') or {}).get('face')}")


def _cell_stats(pool: list[dict]) -> str:
    done = [r for r in pool if (r.get("result") or {}).get("face") in FACES]
    if not done:
        return "n=0"
    up = sum(1 for r in done if rel_outcome(r) != "fav")
    known = [r for r in done if ticket(r) is not None]
    dd = sum(1 for r in known if death(r))
    rate = f"{dd / len(known):.0%}" if known else "—"
    return (f"n={len(done)} · 翻车 {up / len(done):.0%} · 排除面开/单死 "
            f"{dd}/{len(known)}（{rate}；未知票形 {len(done) - len(known)}）")


def render(issue: str, target: list[dict], recent: list[dict], everything: list[dict],
           window: list[str]) -> str:
    dead_recent = [r for r in recent if death(r)]
    gaps = sum(1 for r in recent if (r.get("result") or {}).get("face") not in FACES)
    faces_opened = Counter((r.get("result") or {}).get("face") for r in dead_recent)
    lines = [
        f"## §1e 近期死亡场同构对位 · {issue}（近 {len(window)} 期 {window[0] if window else '—'}–"
        f"{window[-1] if window else '—'}；样本表前瞻行）",
        "",
        f"口径：近 {len(window)} 期 {len(recent)} 行，有赛果 {len(recent) - gaps} 行"
        + (f"（**赛果缺口 {gaps} 行**，先 `zucai-official` 再重建）" if gaps else "")
        + f"；「死」＝机器研究票形被开出排除面或单选未开，共 {len(dead_recent)} 场"
        f"（开 3/1/0 ＝ {faces_opened.get('3', 0)}/{faces_opened.get('1', 0)}"
        f"/{faces_opened.get('0', 0)}）。"
        "结构键＝档·锚方完整度·洞位·价态·标签；只展示，不改默认动作。",
        "",
        "| 场 | 结构键 | 票形 | 近期同格：☠ 死 / ✗ 翻车票活 / ✓ 开热门 | 全前瞻同格 |",
        "|---|---|---|---|---|",
    ]
    by_sig: dict[tuple, list[dict]] = defaultdict(list)
    all_by_sig: dict[tuple, list[dict]] = defaultdict(list)
    for depth in (5, 3):
        for r in recent:
            if outcome_mark(r):                      # 无赛果的行不进同格清单
                by_sig[sig(r, depth)].append(r)
        for r in everything:
            all_by_sig[sig(r, depth)].append(r)
    for r in sorted(target, key=lambda x: int((x.get("zucai") or {}).get("no") or 0)):
        no = (r.get("zucai") or {}).get("no")
        key = sig(r)
        same = by_sig.get(key, [])
        depth = 5
        if not same:
            key, depth = sig(r, 3), 3
            same = by_sig.get(key, [])
        form, _ = ticket_form(r)
        listing = "<br>".join(_label(x) for x in same) or "近期无同格"
        layer = "" if depth == 5 else "（退到 档·锚方完整度·洞位）"
        lines.append(f"| {no} {r.get('home')}-{r.get('away')} | {'·'.join(key)}{layer}"
                     f" | {form or '—'}"
                     f" | {listing} | {_cell_stats(all_by_sig.get(key, []))} |")
    lines += ["", "**死法形状（按票形；排除面市场 P 均值 → 实开）**", "",
              "| 票形 | 近期 n / 死 | 市场 P → 实开 | 全前瞻 n / 死 | 市场 P → 实开 |",
              "|---|---|---|---|---|"]
    forms = ("单", "双·排非热门胜", "双·排平", "双·排热门")
    cols = []
    for pool in (recent, everything):
        agg: dict[str, list[tuple[float | None, int]]] = defaultdict(list)
        for r in pool:
            if (r.get("result") or {}).get("face") not in FACES:
                continue
            form, excluded = ticket_form(r)
            if not form:
                continue
            p = (((r.get("belief") or {}).get("market") or {}).get(excluded)
                 if excluded else None)
            agg[form].append((p, 1 if death(r) else 0))
        cols.append(agg)
    for form in forms:
        cells = []
        for agg in cols:
            v = agg.get(form, [])
            if not v:
                cells += ["0 / 0", "—"]
                continue
            d = sum(x for _, x in v)
            ps = [p for p, _ in v if p is not None]
            cells.append(f"{len(v)} / {d}（{d / len(v):.0%}）")
            cells.append(f"{statistics.fmean(ps):.1%} → {d / len(v):.1%}" if ps else "—")
        lines.append(f"| {form} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("读法：排除面「实开」减「市场 P」是这类票形在样本里多死/少死几个点；"
                 "n<60 或差值在一个标准误内只记格。"
                 "它与 §1c 翻车面（翻车长什么样）、§1d 结构对准（同格历史开出分布）同屏读，"
                 "三者都不改默认动作。")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--issue", required=True)
    ap.add_argument("--recent", type=int, default=7)
    ap.add_argument("--samples", default=str(_HERE / "decision-samples-v1.jsonl"))
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = load_rows(Path(a.samples))
    target = [r for r in rows if str((r.get("zucai") or {}).get("issue")) == a.issue]
    if not target:
        raise SystemExit(f"样本表里没有 {a.issue} 的前瞻行"
                         "——先 decision_samples_build.py --to <今日>")
    window = recent_issues(rows, a.issue, a.recent)
    recent = [r for r in rows if str((r.get("zucai") or {}).get("issue")) in window]
    everything = [r for r in rows if (r.get("result") or {}).get("face") in FACES
                  and str((r.get("zucai") or {}).get("issue")) != a.issue]
    md = render(a.issue, target, recent, everything, window)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
