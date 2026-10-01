"""策略协议与注册表：`policy.decide(board.visible(), ctx) -> [BetSlip]`。

策略只拿 `visible()`（没有赛果、没有奖金）。注金帽与月度止损由运行器强制，不信策略自觉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from nutmeg.decision.betslip import BetSlip
from nutmeg.gym.board import JczqBoard, ZucaiIssue


@dataclass(frozen=True)
class Ctx:
    cap_jczq_day: int = 400          # 宪法 §4：竞彩日 ≤¥400
    cap_zucai_slip: int = 400        # 足彩复式 ≤¥400
    belief_source: str = "market"    # market | closing | read
    seed: int = 7
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Policy(Protocol):
    name: str
    version: str
    channels: tuple[str, ...]

    def decide(self, board: JczqBoard | ZucaiIssue, ctx: Ctx) -> list[BetSlip]: ...


REGISTRY: dict[str, Policy] = {}


def register(cls):
    """类装饰器：实例化并按 `name` 登记。"""
    instance = cls()
    REGISTRY[instance.name] = instance
    return cls


def get(name: str) -> Policy:
    import nutmeg.gym.policies  # noqa: F401 —— 导入即登记

    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown policy {name!r}; known: {sorted(REGISTRY)}") from exc


def names() -> list[str]:
    import nutmeg.gym.policies  # noqa: F401

    return sorted(REGISTRY)
