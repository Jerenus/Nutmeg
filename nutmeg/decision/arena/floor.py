"""随机地板：同一比赛池、同一赔率档的随机串。种子由日期和档位决定，可复现。"""
from __future__ import annotations

import random
from collections import defaultdict
from math import prod

from nutmeg.decision.arena.rules import tier_label

_MAX_DRAWS = 5000


def floor_tickets(day: str, legs: list[dict], tier: list[int], n: int = 30) -> list[dict]:
    by_match = defaultdict(list)
    for leg in legs:
        by_match[leg["code"]].append(leg)
    codes = sorted(by_match)
    if len(codes) < 2:
        return []
    rng = random.Random(f"{day}:{tier_label(tier)}")
    out: list[dict] = []
    for _ in range(_MAX_DRAWS):
        if len(out) >= n:
            break
        chosen = rng.sample(codes, rng.randint(2, min(5, len(codes))))
        combo = [rng.choice(by_match[code]) for code in chosen]
        odds = prod(x["sp"] for x in combo)
        if tier[0] <= odds < tier[1]:
            out.append({"odds": round(odds, 4),
                        "legs": [{k: x[k] for k in ("code", "market", "face", "line", "sp")}
                                 for x in combo]})
    return out
