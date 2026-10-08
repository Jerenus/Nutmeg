"""双轴计分(spec §5)——纯函数,无 I/O。

轴一 Brier-对-赛果(慢,真理):Σ(belief−onehot)²,越小越好。
  brier_delta_vs_prior<0 = 你的偏移改善了市场先验(Metaculus Baseline 直译)。
轴二 CLV-对-收盘(快,信息含量):(belief−prior)·(closing−prior) 方向命中,
  >0 = 偏移朝收盘移动(含真实信息),开赛即可结,方差远小于赛果。
"""
from __future__ import annotations

from nutmeg.decision.faces import FACE_OF, FACES


def brier(probs: dict[str, float], actual: str) -> float:
    """Σ over outcomes of (prob − 1{outcome==actual})²。actual 不在键中按 0 处理。

    `actual` 可以是 home/draw/away，也可以是竞彩码 3/1/0。唯一实现（2026-10-08 B5：signals、
    retro_encoder、rsi_grading 各有一份）。按 主/平/客 → 其余键（升序）的固定顺序累加：旧实现按
    set 遍历，浮点末位随进程的哈希种子变。"""
    actual = FACE_OF.get(str(actual), actual)
    keys = [*FACES, *sorted(k for k in probs if k not in FACES)]
    if actual not in keys:
        keys.append(actual)
    return sum((float(probs.get(k, 0.0)) - (1.0 if k == actual else 0.0)) ** 2 for k in keys)


def brier_delta_vs_prior(belief: dict[str, float], prior: dict[str, float],
                         actual: str) -> float:
    """brier(belief) − brier(prior)。负 = 偏移改善了市场先验。"""
    return brier(belief, actual) - brier(prior, actual)


