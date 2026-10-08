"""赔率 → 概率的唯一去水实现（2026-10-08 第二轮瘦身 B5）。

此前 decision/market_data、decision/jczq_board、data/fcom500、decision/microstructure 各一份；
jczq_board 那份遇 0 赔率直接除零。
"""
from __future__ import annotations


def devig(odds: dict) -> dict[str, float]:
    """任意键赔率 → 去水 fair 概率（1/赔率 归一，和≈1）。

    不可解析或非正的赔率剔除；全部不可用 → {}。需要三面齐全的调用方自己检查键。"""
    inverse: dict[str, float] = {}
    for key, value in (odds or {}).items():
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            inverse[key] = 1.0 / price
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {key: value / total for key, value in inverse.items()}
