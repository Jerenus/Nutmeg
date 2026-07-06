"""express — 组合枚举 + 赔率算术 + 预算闸(spec §6)。

预算是配置数据(decision_budget.json)非代码规则(数据>代码版本策略)。
复式注数/组合赔率一律代码算(禁嘴算)。M0 为骨架:算术 + 闸门,不含 PDF/推送。
空仓永远合法。
"""
from __future__ import annotations

import json
import math
from functools import reduce
from importlib import resources

_BUDGET_RESOURCE = "decision_budget.json"


def load_budget() -> dict:
    return json.loads(
        resources.files("nutmeg.data").joinpath(_BUDGET_RESOURCE)
        .read_text(encoding="utf-8")
    )


def renjiu_ticket_count(total: int, pick: int) -> int:
    """任九复式注数 = C(total, pick)。"""
    return math.comb(total, pick)


def parlay_odds(odds: list[float]) -> float:
    """串关组合赔率 = 各腿赔率连乘。"""
    return reduce(lambda a, b: a * b, odds, 1.0)


def within_budget(channel: str, bucket: str, stake_yuan: float) -> bool:
    budget = load_budget()
    cap = budget.get(channel, {}).get(bucket)
    return cap is not None and stake_yuan <= cap
