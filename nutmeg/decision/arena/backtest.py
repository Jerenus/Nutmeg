"""历史回放、开发包和封存验证。窗口写死，投稿期不随手改。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nutmeg.decision.arena.floor import floor_tickets
from nutmeg.decision.arena.legs import build_legs
from nutmeg.decision.arena.rules import STAKE_YUAN, make_ticket, pick_legs, tier_label
from nutmeg.decision.arena.settle import gross, void_codes
from nutmeg.decision.bj_time import aware
from nutmeg.decision.files import read_json
from nutmeg.decision.match_results import board_outcomes

DEV = ("2026-05-19", "2026-09-15")
SEALED = ("2026-09-16", "2026-11-05")
MIN_SEALED_TICKETS = 15


@dataclass
class Day:
    day: str
    legs: list[dict]
    outcomes: dict
    voids: set


def history_days(data_dir, start: str, end: str) -> list[Day]:
    """窗口内有快照、国际盘和赛果的板面日。历史 ref 取快照更新时点。"""
    root = Path(data_dir) / "jczq" / "daily"
    out = []
    for path in sorted(root.glob("20*")):
        day = path.name
        if not start <= day <= end:
            continue
        value = read_json(path / "sporttery_markets.json", None)
        odds = read_json(path / "bold_odds.json", None)
        outcomes = board_outcomes(data_dir, day)
        if not value or not odds or not outcomes:
            continue
        ref = aware(value.get("lastUpdateTime") or f"{day} 21:50:00")
        legs = [x for x in build_legs(value, odds, day, ref=ref) if x["code"] in outcomes]
        if legs:
            out.append(Day(day, legs, outcomes, void_codes(data_dir, day)))
    return out


def replay(rule: dict, days: list[Day]) -> list[dict]:
    """每天按规则出一张并算派奖倍数，同实盘的选腿。"""
    out = []
    for item in days:
        picked = pick_legs(item.legs, rule)
        if not picked:
            continue
        ticket = make_ticket(rule, item.day, picked, f"{item.day}T00:00:00+08:00")
        out.append({"day": item.day, "tier": ticket["tier"], "odds": ticket["odds"],
                    "p_joint": ticket["p_joint"],
                    "gross": gross(ticket["legs"], item.outcomes, item.voids)})
    return out


def _floor_roi(tier: list[int], days: list[Day]) -> float | None:
    grosses = [gross(t["legs"], d.outcomes, d.voids)
               for d in days for t in floor_tickets(d.day, d.legs, tier)]
    return sum(grosses) / len(grosses) - 1 if grosses else None


def summarize(rule: dict, days: list[Day]) -> dict:
    rows = replay(rule, days)
    picked = {r["day"] for r in rows}
    floor = _floor_roi(rule["tier"], [d for d in days if d.day in picked])
    roi = sum(r["gross"] for r in rows) / len(rows) - 1 if rows else None
    return {"track": rule["id"], "tier": tier_label(rule["tier"]), "tickets": len(rows),
            "won": sum(1 for r in rows if r["gross"]),
            "avg_p": sum(r["p_joint"] for r in rows) / len(rows) if rows else None,
            "avg_odds": sum(r["odds"] for r in rows) / len(rows) if rows else None,
            "roi": roi, "floor_roi": floor, "stake_each": STAKE_YUAN}


def check_admission(rule: dict, days: list[Day]) -> dict:
    """封存段的粗门：出票够数，且 ROI 不低于同日同档地板。"""
    result = summarize(rule, days)
    if result["tickets"] < MIN_SEALED_TICKETS:
        return result | {"admitted": False, "reason": f"封存段出票不足 {MIN_SEALED_TICKETS} 张"}
    if result["floor_roi"] is not None and result["roi"] < result["floor_roi"]:
        return result | {"admitted": False, "reason": "封存段 ROI 低于同档地板"}
    return result | {"admitted": True, "reason": "通过"}


def dev_pack(data_dir, out_dir) -> Path:
    """选手用的开发包：只含开发窗口，不含封存日。"""
    days = history_days(data_dir, *DEV)
    pack = {"window": DEV, "days": {d.day: {"legs": d.legs, "outcomes": d.outcomes,
                                            "voids": sorted(d.voids)} for d in days}}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "dev-pack.json"
    path.write_text(json.dumps(pack, ensure_ascii=False), "utf-8")
    return path
