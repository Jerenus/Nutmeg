"""多张足彩票一起看的算术（2026-10-09）：至少中一张、同死、给定赛果、互补副单搜索。

26136 那天这四样全是会话里手写脚本算的（同一推导写了六遍）。审票只看单张 P 与共享裸单，
看不到「两张票合起来盖住多少」——第一版副单照抄主单的选法，主副同死 73.7%，加了它至少中一张
只从 11.40% 升到 14.13%；反着选的副单同价同死 45.0%、合起来 16.27%。

票面＝{场号: 面集合}（"31"）；fair＝{场号: {home, draw, away}}。只算术、不判断、不写盘。
"""
from __future__ import annotations

import random
from itertools import combinations
from math import prod

from nutmeg.decision.faces import FACE_OF

SUBSETS = ("3", "1", "0", "31", "30", "10", "310")


def _mass(fair: dict, no: str, faces) -> float:
    return sum(fair[no][FACE_OF[c]] for c in faces)


def p_all(tickets: list[dict], fair: dict) -> float:
    """这几张票同时全对的概率：每场取所有含该场的票共同选中的面。"""
    p = 1.0
    for no in {no for t in tickets for no in t}:
        common = set.intersection(*(set(t[no]) for t in tickets if no in t))
        p *= _mass(fair, no, common)
    return p


def p_any(tickets: list[dict], fair: dict) -> float:
    """至少中一张（容斥，精确；票之间共享场次，不能相加）。"""
    return sum((-1) ** (r + 1) * p_all(list(group), fair)
               for r in range(1, len(tickets) + 1) for group in combinations(tickets, r))


def co_death(tickets: list[dict], fair: dict) -> tuple[float, list[tuple[str, str, float]]]:
    """同死点＝这几张票都选了的场里谁都没盖的面；任一开出它们一起死。
    → (至少一个同死点开出的概率, [(场号, 面, P)])。"""
    points = []
    for no in sorted({no for t in tickets for no in t}, key=int):
        if all(no in t for t in tickets):
            open_faces = "".join(c for c in "310" if all(c not in t[no] for t in tickets))
            if open_faces:
                points.append((no, open_faces, _mass(fair, no, open_faces)))
    return 1 - prod(1 - p for _, _, p in points), points


def given(fair: dict, results: dict[str, str]) -> dict:
    """把若干场钉成某个结果后的 fair（「若西汉姆打平，各票还剩多少」）。"""
    out = dict(fair)
    for no, code in results.items():
        out[no] = {face: float(face == FACE_OF[code]) for face in ("home", "draw", "away")}
    return out


def best_complement(base: list[dict], fair: dict, *, n_matches: int, max_notes: int,
                    fixed: dict[str, str] | None = None, restarts: int = 200,
                    seed: int = 0) -> tuple[float, dict] | None:
    """固定基准票，在注数帽内找一张让「至少中一张」最大的票。

    约束：恰好 `n_matches` 场、注数 ≤ `max_notes`、`fixed` 里的场按给定面、不与任何基准票
    共享裸单（V2 会否决的结构搜出来也没法买）。局部搜索 + 固定种子随机重启，不保证全局最优。
    → (合起来至少中一张, 票面)；无合法解 → None。"""
    fixed = fixed or {}
    nos = sorted(fair, key=int)
    naked = {(no, f) for t in base for no, f in t.items() if len(f) == 1}

    def legal(t: dict) -> bool:
        return (prod(len(f) for f in t.values()) <= max_notes
                and all(t.get(no) == f for no, f in fixed.items())
                and not any((no, f) in naked for no, f in t.items()))

    def score(t: dict) -> float:
        return p_any([*base, t], fair) if legal(t) else -1.0

    rnd = random.Random(seed)
    best: tuple[float, dict] | None = None
    free = [no for no in nos if no not in fixed]
    for _ in range(restarts):
        t = {**fixed, **{no: rnd.choice(SUBSETS)
                         for no in rnd.sample(free, n_matches - len(fixed))}}
        current = score(t)
        while True:
            moves = []
            for no in [no for no in t if no not in fixed]:
                moves += [{**t, no: f} for f in SUBSETS if f != t[no]]
                rest = {k: v for k, v in t.items() if k != no}
                moves += [{**rest, other: f} for other in free if other not in t
                          for f in SUBSETS]
            top = max(moves, key=score, default=None)
            if top is None or score(top) <= current + 1e-12:
                break
            t, current = top, score(top)
        if current >= 0 and (best is None or current > best[0] + 1e-12):
            best = (current, t)
    return best


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def death_text(tickets: list[dict], fair: dict) -> str:
    """「58.7%（1开0、2开0）」：同死概率与同死点。"""
    p, points = co_death(tickets, fair)
    return f"{p * 100:.1f}%（{'、'.join(f'{no}开{f}' for no, f, _ in points) or '无同死点'}）"


def report_lines(plan: list[tuple[str, dict]], registered: list[tuple[str, dict]], fair: dict,
                 *, issue: str, alternatives: bool, results: dict[str, str]) -> list[str]:
    """预审的整组算术。`plan`/`registered`＝[(标签, 票面)]；`alternatives`＝计划是互斥备选，
    每张只和已登记实购票合起来看；`results`＝钉住的赛果（`given`）。"""
    group = [*registered, *plan]
    lines = []
    if alternatives and registered:
        base = [t for _, t in registered]
        lines.append(f"互斥备选与已登记实购合起来（{issue}，已登记 {len(registered)} 张，"
                     f"至少中一张 {pct(p_any(base, fair))}）")
        for label, t in plan:
            lines.append(f"   【{label}】至少中一张 {pct(p_any([*base, t], fair))}｜" + "；".join(
                f"与 {other} 同死 {death_text([rt, t], fair)}" for other, rt in registered))
    elif not alternatives and len(group) >= 2:
        head = f"计划 {len(plan)} 张" + (f" + 已登记实购 {len(registered)} 张" if registered
                                       else "")
        lines.append(f"整组算术（{issue}，{head}）：至少中一张 "
                     f"{pct(p_any([t for _, t in group], fair))}"
                     f"（单张最高 {pct(max(p_all([t], fair) for _, t in group))}）")
        lines += [f"   同死 {la}×{lb} {death_text([ta, tb], fair)}"
                  for (la, ta), (lb, tb) in combinations(group, 2)]
    if results:
        pinned = given(fair, results)
        cells = [f"{label} {pct(p_all([t], pinned))}" for label, t in group]
        if not alternatives and len(group) >= 2:
            cells.append(f"至少中一张 {pct(p_any([t for _, t in group], pinned))}")
        lines.append(f"若 {'、'.join(f'{no}开{c}' for no, c in results.items())}："
                     + "｜".join(cells))
    return lines
