"""结算：赛果只经 `match_results`，作废只读 `void-matches.json`（腿算中，赔率按 1）。"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.arena.ledger import append_jsonl, arena_dir, read_jsonl
from nutmeg.decision.bj_time import aware
from nutmeg.decision.files import read_json
from nutmeg.decision.match_results import board_outcomes


def void_codes(data_dir, day: str) -> set[str]:
    return set((read_json(Path(data_dir) / "jczq" / "void-matches.json", {}) or {}).get(day) or [])


def _won(leg: dict, outcome: dict) -> bool:
    diff = outcome["goals_h"] - outcome["goals_a"]
    return {"home": diff > 0, "draw": diff == 0, "away": diff < 0,
            "not_win": diff < 1, "not_lose": diff > -1}[leg["face"]]


def gross(legs: list[dict], outcomes: dict, voids: set[str]) -> float | None:
    """每投 1 元的派奖倍数；有腿没赛果 → None（不伪造派奖）。"""
    multiple = 1.0
    for leg in legs:
        if leg["code"] in voids:
            continue
        outcome = outcomes.get(leg["code"])
        if outcome is None:
            return None
        multiple *= leg["sp"] if _won(leg, outcome) else 0.0
    return multiple


def settle_ticket(ticket: dict, outcomes: dict, voids: set[str], settled_at: str) -> dict | None:
    """一张票的结算行；待结 → None。冻结不早于首场开球的票拒绝，不产派奖。"""
    base = {"ticket_id": ticket["ticket_id"], "day": ticket["day"],
            "track": ticket.get("track"), "tier": ticket.get("tier"), "settled_at": settled_at}
    if aware(ticket["frozen_at"]) >= aware(ticket["first_kickoff"]):
        return base | {"status": "rejected", "payout": None, "pnl": None}
    multiple = gross(ticket["legs"], outcomes, voids)
    if multiple is None:
        return None
    payout = round(ticket["stake"] * multiple, 2)
    return base | {"status": "won" if payout else "lost", "payout": payout,
                   "pnl": round(payout - ticket["stake"], 2)}


def settle_pending(data_dir, settled_at: str) -> dict:
    """结算全部未结票，只追加。"""
    root = arena_dir(data_dir)
    done = {row["ticket_id"] for row in read_jsonl(root / "settled.jsonl")}
    settled = pending = 0
    for ticket in read_jsonl(root / "tickets.jsonl"):
        if ticket["ticket_id"] in done:
            continue
        day = ticket["day"]
        row = settle_ticket(ticket, board_outcomes(data_dir, day), void_codes(data_dir, day),
                            settled_at)
        if row is None:
            pending += 1
            continue
        append_jsonl(root / "settled.jsonl", row)
        settled += 1
    return {"settled": settled, "pending": pending}
