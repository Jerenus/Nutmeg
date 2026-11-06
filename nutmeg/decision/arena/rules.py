"""规则：封闭 JSON，只读赛前字段。选腿统一，选手只能改筛选和排序。"""
from __future__ import annotations

import itertools
from math import prod

TIERS = ([10, 20], [20, 50], [50, 100])
STAKE_YUAN = 10
TOP_LEGS = 8
_RANGE = {"sp", "p_fair", "ret", "gap", "hours_to_kickoff"}
_MEMBER = {"market", "face", "line", "league_group", "weekday"}
_BOOL = {"is_fav", "is_dog", "stance_match"}
_SCORE = {"sp", "p_fair", "ret", "gap"}


def tier_label(tier: list[int]) -> str:
    return f"{tier[0]}-{tier[1]}"


def validate_rule(rule: dict) -> list[str]:
    """不合规的原因；空列表＝合规。白名单外的字段（含一切赛后字段）一律拒绝。"""
    errors = []
    if not rule.get("id"):
        errors.append("缺 id")
    if rule.get("tier") not in TIERS:
        errors.append(f"tier 只能是 {TIERS}")
    if rule.get("score") not in _SCORE:
        errors.append(f"score 只能是 {sorted(_SCORE)}")
    for key in ("mechanism", "falsify"):
        if not str(rule.get(key) or "").strip():
            errors.append(f"缺 {key}")
    span = rule.get("legs")
    if not (isinstance(span, list) and len(span) == 2 and 2 <= span[0] <= span[1] <= 5):
        errors.append("legs 须为 [最少, 最多]，范围 2–5")
    for field, cond in (rule.get("filter") or {}).items():
        if field in _RANGE:
            if not (isinstance(cond, list) and len(cond) == 2):
                errors.append(f"{field} 须为 [下限, 上限]")
        elif field in _MEMBER:
            if not isinstance(cond, list):
                errors.append(f"{field} 须为列表")
        elif field in _BOOL:
            if not isinstance(cond, bool):
                errors.append(f"{field} 须为布尔")
        else:
            errors.append(f"字段不在白名单：{field}")
    return errors


def _passes(leg: dict, conds: dict) -> bool:
    for field, cond in conds.items():
        if field in _RANGE:
            if not cond[0] <= leg[field] <= cond[1]:
                return False
        elif field in _MEMBER:
            if leg[field] not in cond:
                return False
        elif leg[field] is not cond:
            return False
    return True


def pick_legs(legs: list[dict], rule: dict) -> list[dict] | None:
    """按 score 取前 8 条腿，在档内组合里取联合概率最高的一张（左闭右开）；没有 → None。"""
    lo, hi = rule["tier"]
    score = rule["score"]
    pool = sorted((x for x in legs if _passes(x, rule.get("filter") or {})),
                  key=lambda x: (-x[score], x["code"], x["face"]))[:TOP_LEGS]
    best, best_key = None, None
    for k in range(rule["legs"][0], rule["legs"][1] + 1):
        for combo in itertools.combinations(pool, k):
            if len({x["code"] for x in combo}) < k or not lo <= prod(x["sp"] for x in combo) < hi:
                continue
            key = (prod(x["p_fair"] for x in combo), sum(x[score] for x in combo) / k)
            if best_key is None or key > best_key:
                best, best_key = combo, key
    return sorted(best, key=lambda x: (x["code"], x["face"])) if best else None


def make_ticket(rule: dict, day: str, picked: list[dict], frozen_at: str) -> dict:
    return {
        "ticket_id": f"{day}:{rule['id']}", "day": day, "track": rule["id"],
        "season": rule.get("season"), "tier": tier_label(rule["tier"]), "stake": STAKE_YUAN,
        "odds": round(prod(x["sp"] for x in picked), 4),
        "p_joint": round(prod(x["p_fair"] for x in picked), 6),
        "frozen_at": frozen_at, "first_kickoff": min(x["kickoff"] for x in picked),
        "legs": [{k: x[k] for k in ("code", "name", "market", "face", "line", "sp", "p_fair",
                                    "kickoff")} for x in picked],
    }
