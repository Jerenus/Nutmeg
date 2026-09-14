"""市场微结构 —— 从逐家报价里算出的可观测量(数据层,不作判断)。

2026-09-14 换源后才第一次可得。API-Football 基础 ``/odds`` 不给初赔、也不给对齐的
逐家报价,所以下面三个量在旧源上要么恒为 0(drift)、要么根本算不出(离散度、返还率
位移)。titan007 每场给 152 家的**初赔 + 即时赔**,这些量才有了原料。

**只算不判**。这里出的是 pp 数,不是「信号」也不是「因子」——某个量到多少算数、指向
哪一面,必须走 Factor 的 probation → 双轴校准 → 生死流程,由样本说话。把阈值写进数据层
等于绕过那条流程。

**缺测量绝不补 0**：没有初赔就不出 ``drift_*`` 键,而不是写 0。前者是「没测」,后者是
「测了没动」——混淆这两者,判读层会把旧源日子的静默当成真静默。
"""

from __future__ import annotations

import statistics

__all__ = ["market_microstructure"]

_OUTCOME_KEYS = ("home", "draw", "away")


def _fair(odds: dict[str, float]) -> dict[str, float]:
    """去水:1/赔率 归一。任一路缺失/非正 → 空(不猜)。"""
    inverse = {k: 1.0 / v for k, v in (odds or {}).items() if v and v > 0}
    if len(inverse) < len(_OUTCOME_KEYS) or not inverse:
        return {}
    total = sum(inverse.values())
    return {k: v / total for k, v in inverse.items()} if total > 0 else {}


def _payout(odds: dict[str, float]) -> float | None:
    """返还率 % = 1/Σ(1/赔率)。三路不齐 → None。"""
    inverse = [1.0 / v for k, v in (odds or {}).items() if k in _OUTCOME_KEYS and v and v > 0]
    if len(inverse) != len(_OUTCOME_KEYS):
        return None
    total = sum(inverse)
    return round(100.0 / total, 2) if total > 0 else None


def _aligned_per_book(per_book: dict[str, list[float]] | None) -> list[dict[str, float]]:
    """``{路: [各家赔率]}`` → ``[{路: 赔率}, ...]`` 逐家。

    只有三路列表**等长**时才对齐——titan007 的逐家报价天然等长(同一批入选书目),
    但 API-Football 的是各路独立聚合、家数可以不等。错位的家凑出来的离散度是假的,
    宁可不出。
    """
    if not per_book:
        return []
    lengths = {len(per_book.get(k) or []) for k in _OUTCOME_KEYS}
    if len(lengths) != 1:
        return []
    (count,) = lengths
    if count < 2:
        return []
    return [
        {k: per_book[k][i] for k in _OUTCOME_KEYS}
        for i in range(count)
    ]


def market_microstructure(market) -> dict[str, float]:
    """``MarketOdds`` → 微结构可观测量。无可算量返回 ``{}``。

    出的键（缺原料就整键不出，绝不补 0）:

    ``payout_current`` / ``payout_open``
        返还率 %(=1/overround)。抽水越窄庄家越笃定。

    ``payout_delta_pp``
        即时 − 初盘的返还率位移。正 = 抽水收窄。

    ``drift_{home,draw,away}_pp`` / ``drift_pp``
        初赔 fair → 即时 fair 的**带符号**逐路位移,以及最大绝对位移。
        **旧源上恒为 0 的就是这一组**。

    ``books``
        入选共识的家数。

    ``dispersion_pp``
        逐家 fair 在**当前热门那一路**上的标准差 ×100 = 跨家分歧度。
    """
    if market is None:
        return {}
    odds = dict(getattr(market, "odds", {}) or {})
    if not odds:
        return {}

    micro: dict[str, float] = {}

    payout_current = _payout(odds)
    if payout_current is not None:
        micro["payout_current"] = payout_current

    opening = dict(getattr(market, "opening_odds", {}) or {})
    if opening:
        payout_open = _payout(opening)
        if payout_open is not None:
            micro["payout_open"] = payout_open
            if payout_current is not None:
                micro["payout_delta_pp"] = round(payout_current - payout_open, 2)

        fair_now, fair_open = _fair(odds), _fair(opening)
        if fair_now and fair_open:
            moves = {
                key: round((fair_now[key] - fair_open[key]) * 100, 2)
                for key in _OUTCOME_KEYS
                if key in fair_now and key in fair_open
            }
            for key, value in moves.items():
                micro[f"drift_{key}_pp"] = value
            if moves:
                micro["drift_pp"] = max(moves.values(), key=abs)

    books = int(getattr(market, "bookmaker_count", 0) or 0)
    if books:
        micro["books"] = books

    per_book = _aligned_per_book(getattr(market, "per_book_odds", None) or {})
    if per_book:
        micro["books"] = len(per_book)
        fair_now = _fair(odds)
        if fair_now:
            favourite = max(fair_now, key=fair_now.get)
            per_book_fair = [
                _fair(row).get(favourite) for row in per_book
            ]
            values = [v for v in per_book_fair if v is not None]
            if len(values) >= 2:
                micro["dispersion_pp"] = round(statistics.pstdev(values) * 100, 2)
    return micro
