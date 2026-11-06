"""榜单：赛道 ROI 减同日同档地板；冠军线＝N 个随机选手里第一名成绩的 95 分位。"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from nutmeg.decision.arena.ledger import arena_dir, read_jsonl
from nutmeg.decision.arena.settle import gross, void_codes
from nutmeg.decision.match_results import board_outcomes


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def track_rows(entries: dict[str, list[dict]], floors: dict) -> list[dict]:
    """entries＝{赛道: [{day, tier, gross, fair}]}，fair＝联合概率×赔率。

    floors＝{(day, tier): [地板派奖倍数]}。

    主分含少吃抽水的结构优势，`edge`＝实际减国际概率期望，才看选腿有没有信息。按主分降序。"""
    rows = []
    for track, items in entries.items():
        matched = [x for x in items if floors.get((x["day"], x["tier"]))]
        bases = [_mean(floors[x["day"], x["tier"]]) for x in matched]
        rows.append({
            "track": track, "tier": items[0]["tier"], "tickets": len(items),
            "won": sum(1 for x in items if x["gross"] > 0),
            "roi": _mean([x["gross"] for x in items]) - 1,
            "edge": _mean([x["gross"] - x["fair"] for x in items]),
            "floor_roi": _mean(bases) - 1 if bases else None,
            "score": (_mean([x["gross"] - b for x, b in zip(matched, bases, strict=True)])
                      if matched else None),
        })
    return sorted(rows, key=lambda r: -(r["score"] if r["score"] is not None else -9e9))


def champion_line(tracks: list[tuple[str, list[str]]], floors: dict, sims: int = 2000,
                  seed: int = 7) -> float | None:
    """tracks＝[(档, 该赛道出票日)]。每届每条赛道都换成随机选手，取第一名，再取 95 分位。"""
    prepared = []
    for tier, days in tracks:
        usable = [(floors[d, tier], _mean(floors[d, tier])) for d in days if floors.get((d, tier))]
        if usable:
            prepared.append(usable)
    if not prepared:
        return None
    rng = random.Random(seed)
    bests = []
    for _ in range(sims):
        bests.append(max(sum(pool[int(rng.random() * len(pool))] - base for pool, base in usable)
                         / len(usable) for usable in prepared))
    bests.sort()
    return bests[int(0.95 * len(bests))]


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1%}"


def render_board(month: str, rows: list[dict], line: float | None, *, pending: int,
                 empty_days: int) -> str:
    winners = [r for r in rows if line is not None and (r["score"] or -9e9) > line]
    head = (f"有效冠军：{winners[0]['track']}" if winners else "本季无有效冠军")
    text = [f"# 竞彩虚拟规则赛榜单 {month}", "",
            "虚拟单，不进净值和止损账。榜单只作展示，不影响实票。", "",
            f"**{head}**。冠军线 {_pct(line)}，待结 {pending} 张，"
            f"无合规组合累计 {empty_days} 条次。",
            "", "主分＝ROI 减同日同档地板，含少吃抽水的结构优势。",
            "超预期＝ROI 减国际概率期望，才看选腿信息。",
            "", "| 排名 | 赛道 | 档 | 张 | 中 | ROI | 地板 ROI | 主分 | 超预期 |",
            "|---|---|---|---|---|---|---|---|---|"]
    for rank, row in enumerate(rows, 1):
        text.append(f"| {rank} | {row['track']} | {row['tier']} | {row['tickets']} | {row['won']} "
                    f"| {_pct(row['roi'])} | {_pct(row['floor_roi'])} | {_pct(row['score'])} "
                    f"| {_pct(row['edge'])} |")
    return "\n".join(text) + "\n"


def build_board(data_dir, month: str) -> Path:
    """读账本重算当月榜单，累计到当前，重复运行结果相同。"""
    root = arena_dir(data_dir)
    tickets = {t["ticket_id"]: t for t in read_jsonl(root / "tickets.jsonl")}
    settled = [s for s in read_jsonl(root / "settled.jsonl") if s["status"] != "rejected"]
    entries: dict[str, list[dict]] = defaultdict(list)
    for row in settled:
        ticket = tickets[row["ticket_id"]]
        entries[ticket["track"]].append({"day": ticket["day"], "tier": ticket["tier"],
                                         "gross": row["payout"] / ticket["stake"],
                                         "fair": ticket["p_joint"] * ticket["odds"]})
    floors: dict = {}
    for day in {x["day"] for items in entries.values() for x in items}:
        doc = json.loads((root / "floor" / f"{day}.json").read_text("utf-8"))
        outcomes, voids = board_outcomes(data_dir, day), void_codes(data_dir, day)
        for tier, rows in doc.items():
            values = [gross(t["legs"], outcomes, voids) for t in rows]
            floors[day, tier] = [v for v in values if v is not None]
    rows = track_rows(entries, floors)
    line = champion_line([(items[0]["tier"], [x["day"] for x in items])
                          for items in entries.values()], floors)
    empty = sum(len(r["empty"]) for r in read_jsonl(root / "days.jsonl"))
    pending = len(tickets) - len(read_jsonl(root / "settled.jsonl"))
    path = root / f"board-{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_board(month, rows, line, pending=pending, empty_days=empty), "utf-8")
    return path
