"""竞彩只放判断腿（Jun 2026-09-27）。

以往按 10/20/50/100 倍赔率档凑腿：合法判断腿不够时就塞进市场最可能的总进球档，
那些腿没有任何判断（09-26 J3 死于 015 总进球 2）。本模块只做确定性算术：
- 腿 = 当天**深研过且未开球**的场次（market-anchor 不进）；
- 玩法 = 胜平负单/双选（概率＝belief）+ 让球单选（由 belief 与体彩总进球形状拟合比分矩阵）；
  不含总进球——我们对进球轴没有结构化判断；
- 排序 = 判断概率 P 降序；不设赔率目标，报每元回报（按各腿判断概率较高面的赔率 ÷ 注数）。
⛔不产生判断，不推荐注金。
"""
from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.dcfit import fit_match

_FACE_KEY = {"3": "home", "1": "draw", "0": "away"}
_HAD_ODDS = {"3": "h", "1": "d", "0": "a"}


def _code(read: dict) -> str:
    return str(read.get("note") or "")[1:].split("|")[0]


def judgment_legs(*, day: str, jczq_dir: Path, now: str) -> list[dict]:
    day_dir = Path(jczq_dir) / "daily" / day
    reads = json.loads((day_dir / "reads.json").read_text(encoding="utf-8"))
    board = json.loads((day_dir / "sporttery_markets.json").read_text(encoding="utf-8"))
    rows = {row["matchNumStr"]: row for group in board.get("matchInfoList") or []
            for row in group.get("subMatchList") or []}
    current = datetime.fromisoformat(now)
    legs: list[dict] = []
    for read in reads:
        code = _code(read)
        row = rows.get(code)
        if read.get("judgment_tier") != "deep_research" or not row or not row.get("had"):
            continue
        kickoff = datetime.fromisoformat(f"{row['matchDate']}T{row['matchTime']}+08:00")
        if kickoff <= current:
            continue
        belief = read["belief"]
        options = []
        for faces in ("3", "1", "0", "31", "30", "10"):
            modal = max(faces, key=lambda f: belief[_FACE_KEY[f]])
            options.append({
                "market": "had", "faces": faces,
                "p": sum(belief[_FACE_KEY[f]] for f in faces),
                "odds": [float(row["had"][_HAD_ODDS[f]]) for f in faces],
                # 双选的回报取判断概率较高那一面的赔率（不取两面里更高的赔率——那是高估）
                "modal_odds": float(row["had"][_HAD_ODDS[modal]]),
            })
        hhad, ttg = row.get("hhad") or {}, row.get("ttg") or {}
        if hhad.get("goalLine") and all(f"s{i}" in ttg for i in range(8)):
            raw = {f"total_{i}": 1 / float(ttg[f"s{i}"]) for i in range(8)}
            total = sum(raw.values())
            cover = fit_match(belief, ttg_fair={k: v / total for k, v in raw.items()},
                              hhad_line=hhad["goalLine"])["hhad_cover"]
            for face, key in (("3", "让胜"), ("1", "让平"), ("0", "让负")):
                options.append({"market": "hhad", "faces": face, "line": hhad["goalLine"],
                                "p": cover[key], "odds": [float(hhad[_HAD_ODDS[face]])],
                                "modal_odds": float(hhad[_HAD_ODDS[face]])})
        legs.append({"code": code, "name": row.get("homeTeamAbbName", "") + "-"
                     + row.get("awayTeamAbbName", ""), "kickoff": kickoff.isoformat(),
                     "belief": belief, "prior": read["prior"], "options": options})
    return legs


def enumerate_combos(legs: list[dict], *, max_legs: int = 4, max_notes: int = 4,
                     top: int = 10, max_pool: int | None = None) -> list[dict]:
    """按判断概率 P 降序列前 `top` 个组合。

    `max_pool`：只在判断概率最高的 `max_pool` 条腿里枚举（按每条腿最优选项的 p 排）。
    2026-10-25：周末 23 场板 9 选项/腿 → 5,900 万候选，`research verdict` 把它们全部建成
    dict 留在内存里排序——10-17 跑了 19 小时、10-24 两次吃光内存被 SIGKILL（exit 137）；
    周中 11 场只有 230 万。候选数 ~ C(n,4)×9⁴，裁腿是唯一有效的刀；结果只留 `top` 个用堆维护，
    不再把全部候选留在内存。`None`＝不裁（gym 回放保持原语义）。
    """
    import heapq

    if max_pool is not None and len(legs) > max_pool:
        legs = heapq.nlargest(max_pool, legs,
                              key=lambda leg: max(o["p"] for o in leg["options"]))
    heap: list[tuple[float, int, dict]] = []
    seq = 0
    for k in range(2, min(max_legs, len(legs)) + 1):
        for group in itertools.combinations(legs, k):
            for choice in itertools.product(*(leg["options"] for leg in group)):
                notes = 1
                p = 1.0
                odds = 1.0
                for option in choice:
                    notes *= len(option["odds"])
                    p *= option["p"]
                    odds *= option["modal_odds"]
                if notes > max_notes:
                    continue
                if len(heap) >= top and p <= heap[0][0]:
                    continue
                combo = {
                    "legs": [{"code": leg["code"], "name": leg["name"], **option}
                             for leg, option in zip(group, choice, strict=True)],
                    "p": p, "notes": notes, "odds": odds, "return_per_yuan": odds / notes,
                }
                seq -= 1  # 同 P 时先枚举到的排前，与原 sort 的稳定序一致
                if len(heap) < top:
                    heapq.heappush(heap, (p, seq, combo))
                else:
                    heapq.heapreplace(heap, (p, seq, combo))
    return [item[2] for item in sorted(heap, key=lambda item: (-item[0], -item[1]))]
