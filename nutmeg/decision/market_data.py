"""market_data — 决策系统的确定性盘口数据层(唯一外部数据形状适配点)。

M0 复用 jczq_market_kernel 的纯数学基元(附录 A.1),对外用干净命名重导出;
净化版 snapshots_from_sporttery(Task 6)产 MarketSnapshot,不带 tags/信号字段。
M2 删旧 kernel 时把 A.1 基元物理搬入本文件。**结构性禁止**引入 A.3 信号打分符号。
"""
from __future__ import annotations

from nutmeg.services.jczq_market_kernel import (
    OUTCOMES,
    _devig_map,
    _fair_from_odds,
)

__all__ = ["OUTCOMES", "devig", "fair_1x2"]


def devig(odds: dict[str, float]) -> dict[str, float]:
    """任意键赔率 → 去水 fair 概率(和≈1)。空/不可用 → 空 dict。"""
    return _devig_map(odds)


def fair_1x2(had_odds: dict[str, float]) -> dict[str, float]:
    """胜平负三路赔率 → 去水 fair(home/draw/away)。"""
    return _fair_from_odds(had_odds)
