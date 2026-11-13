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
from nutmeg.decision.structure_tiers import COIN_TOP1

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


def arithmetic_ready(slip) -> bool:
    """整组算术只认「每注就是整张票」的足彩票：胜负彩 14 场、任九恰 9 场，且每场有 fair。
    任九选 >9 场是复式（中 9 即中），全对连乘不是它的中奖概率。"""
    from nutmeg.decision.betslip import RENJIU_PICK, SFC_MATCHES

    need = SFC_MATCHES if slip.channel == "shengfucai" else RENJIU_PICK
    return (slip.channel != "jczq" and len(slip.faces) == need
            and all(leg.fair for leg in slip.legs))


TICKETS_PER_ISSUE = 2
SECOND_TICKET_MIN = 0.03
"""一期最多两张，第二张至少中一张要多 ≥3pp（2026-11-08 Jun 批）：Jun 29 期足彩 25 期多票、多票期
均投入 ¥718 对单票期 ¥376；26160 T1+T2 只多 0.04pp。5 次全中里当期第三张以后的票一次没中。"""


def ticket_cap_check(others: list[dict], this: dict, fair: dict) -> str | None:
    """本期已有的票（实购 + 同组计划）→ 这张该不该买：第三张起否决；第二张增量 <3pp 否决。"""
    if len(others) >= TICKETS_PER_ISSUE:
        return (f"⛔两张上限：本期第 {len(others) + 1} 张（一期最多 {TICKETS_PER_ISSUE} 张）"
                "→ 只买前两张（人坚持就登记并另立裁决）")
    if not others:
        return None
    before, after = p_any(others, fair), p_any([*others, this], fair)
    if after - before >= SECOND_TICKET_MIN:
        return None
    return (f"⛔两张上限：第二张只把至少中一张从 {before * 100:.2f}% 提到 {after * 100:.2f}%"
            f"（+{(after - before) * 100:.2f}pp，<{SECOND_TICKET_MIN * 100:.0f}pp）"
            "→ 这组是一注，只买一张（换单和排除面后再审）")


SHARED_EXCLUDED_MIN = 0.30
"""跨票共享排除面的门槛（§8a 第 4 条，2026-10-14）：所有票同时排掉的 ≥30% 面＝共享裸单同类项。
26138 2·0(45%)、26139 3·10/8·31(25%/19%)、26140 两胆 6·3/8·0 的被排面——四期死因都在这里。"""


def is_coin(faces: dict) -> bool:
    """D 档（§1 五档：市场最大面 <45%）＝任九里该先丢、不该拉进来当双的场。"""
    return max(faces.values()) < COIN_TOP1


def death_list(tickets: list[dict], fair: dict,
               *, top: int = 5) -> tuple[list[tuple[str, str, float]], float]:
    """全组死法清单（§8b）：同死面按概率从大到小，前 `top` 条就是这组票先要过的门。
    → ([(场号, 面, P)] 降序, 前 top 条的联合通过率 ∏(1−P))。单张票＝它自己的被排面。"""
    _, points = co_death(tickets, fair)
    ordered = sorted(points, key=lambda x: (-x[2], int(x[0])))
    return ordered, prod(1 - p for _, _, p in ordered[:top])


def shared_excluded(tickets: list[dict], fair: dict,
                    threshold: float = SHARED_EXCLUDED_MIN) -> list[tuple[str, str, float]]:
    """所有票同时排掉、且概率 ≥ threshold 的面（26122/26133 共享裸单的另一种写法）。"""
    _, points = co_death(tickets, fair)
    return [pt for pt in points if pt[2] >= threshold - 1e-12]


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
                and not any((no, f) in naked for no, f in t.items())
                # 与基准同时排掉 ≥30% 的面也是 V2 同类项（2026-10-14），搜出来也没法买
                and not any(shared_excluded([b, t], fair) for b in base))

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


def death_list_lines(tickets: list[dict], fair: dict, *, top: int = 5) -> list[str]:
    """§8b 一行：「死法清单（按概率）：8开0 31%、6开0 24%｜前五联合通过 42%｜
    ⚠️共享排除面 ≥30%：8开0」。
    单张票就是它自己的被排面；多张票＝全组同死面。"""
    ordered, pass_through = death_list(tickets, fair, top=top)
    if not ordered:
        return ["   死法清单：无同死面（没有一场是所有票都没盖同一面）"]
    # 2026-10-28（26151 三张同死在 1开0 35%：D 档硬币被拉进任九当双）：D 档的面标出来，
    # 桥 §3 第一句要并列「死法清单第一行是哪格、是不是拉进来的 D 档」
    shown = "、".join(f"{no}开{f} {p * 100:.0f}%" + ("·D档" if is_coin(fair[no]) else "")
                     for no, f, p in ordered[:top])
    more = (f"（另 {len(ordered) - top} 条 <{ordered[top][2] * 100:.0f}%）"
            if len(ordered) > top else "")
    scope = "全组同死面" if len(tickets) > 1 else "本票被排面"
    line = (f"   死法清单（按概率，{scope}）：{shown}{more}"
            f"｜前{min(top, len(ordered))}条联合通过 {pass_through * 100:.1f}%")
    hot = shared_excluded(tickets, fair)
    if len(tickets) > 1 and hot:
        line += ("｜⚠️共享排除面 ≥30%："
                 + "、".join(f"{no}开{f}" for no, f, _ in hot) + "（§8a 第 4 条，V2 同类项）")
    return [line]


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
    if not alternatives and group:
        lines += death_list_lines([t for _, t in group], fair)
    if results:
        pinned = given(fair, results)
        cells = [f"{label} {pct(p_all([t], pinned))}" for label, t in group]
        if not alternatives and len(group) >= 2:
            cells.append(f"至少中一张 {pct(p_any([t for _, t in group], pinned))}")
        lines.append(f"若 {'、'.join(f'{no}开{c}' for no, c in results.items())}："
                     + "｜".join(cells))
    return lines
