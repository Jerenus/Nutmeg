"""双轴计分(spec §5)——纯函数,无 I/O。

轴一 Brier-对-赛果(慢,真理):Σ(belief−onehot)²,越小越好。
  brier_delta_vs_prior<0 = 你的偏移改善了市场先验(Metaculus Baseline 直译)。
轴二 CLV-对-收盘(快,信息含量):(belief−prior)·(closing−prior) 方向命中,
  >0 = 偏移朝收盘移动(含真实信息),开赛即可结,方差远小于赛果。
"""
from __future__ import annotations


def brier(probs: dict[str, float], actual: str) -> float:
    """Σ over outcomes of (prob − 1{outcome==actual})²。actual 不在键中按 0 处理。"""
    total = 0.0
    keys = set(probs) | {actual}
    for k in keys:
        p = probs.get(k, 0.0)
        target = 1.0 if k == actual else 0.0
        total += (p - target) ** 2
    return total


def brier_delta_vs_prior(belief: dict[str, float], prior: dict[str, float],
                         actual: str) -> float:
    """brier(belief) − brier(prior)。负 = 偏移改善了市场先验。"""
    return brier(belief, actual) - brier(prior, actual)


def clv_pp(belief: dict[str, float], prior: dict[str, float],
           closing: dict[str, float]) -> float:
    """(belief−prior)·(closing−prior) 点积。>0 = 偏移朝收盘方向(信息含量)。"""
    keys = set(belief) | set(prior) | set(closing)
    return sum(
        (belief.get(k, 0.0) - prior.get(k, 0.0))
        * (closing.get(k, 0.0) - prior.get(k, 0.0))
        for k in keys
    )
