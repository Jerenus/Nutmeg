"""每日冻结：只用开球晚于冻结 30 分钟的比赛。失败不补票，同日重跑不重复。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from nutmeg.decision.arena.floor import floor_tickets
from nutmeg.decision.arena.ledger import append_jsonl, arena_dir, load_rules, read_jsonl
from nutmeg.decision.arena.legs import build_legs
from nutmeg.decision.arena.rules import TIERS, make_ticket, pick_legs, tier_label
from nutmeg.decision.bj_time import aware

_LEAD = timedelta(minutes=30)


def freeze_day(data_dir, day: str, value: dict, odds: dict, *, now: datetime, source: str,
               stances: dict[str, str] | None = None) -> dict:
    root = arena_dir(data_dir)
    if any(row["day"] == day for row in read_jsonl(root / "days.jsonl")):
        return {"status": "already", "day": day}
    legs = [x for x in build_legs(value, odds, day, ref=now, stances=stances)
            if aware(x["kickoff"]) > now + _LEAD]
    frozen_at = now.isoformat(timespec="seconds")
    tickets, empty = [], []
    for rule in load_rules(data_dir):
        picked = pick_legs(legs, rule)
        if picked:
            tickets.append(make_ticket(rule, day, picked, frozen_at))
        else:
            empty.append(rule["id"])
    (root / "legs").mkdir(parents=True, exist_ok=True)
    (root / "floor").mkdir(parents=True, exist_ok=True)
    (root / "legs" / f"{day}.json").write_text(json.dumps(legs, ensure_ascii=False), "utf-8")
    floors = {tier_label(t): floor_tickets(day, legs, t) for t in TIERS}
    (root / "floor" / f"{day}.json").write_text(json.dumps(floors, ensure_ascii=False), "utf-8")
    for ticket in tickets:
        append_jsonl(root / "tickets.jsonl", ticket)
    summary = {"day": day, "frozen_at": frozen_at, "source": source,
               "candidates": len({x["code"] for x in legs}), "tickets": len(tickets),
               "empty": empty}
    append_jsonl(root / "days.jsonl", summary)
    return summary | {"status": "frozen"}
