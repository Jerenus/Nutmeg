"""market_data — 决策系统的确定性盘口数据层(唯一外部数据形状适配点)。

M0 复用 jczq_market_kernel 的纯数学基元(附录 A.1),对外用干净命名重导出;
净化版 snapshots_from_sporttery(Task 6)产 MarketSnapshot,不带 tags/信号字段。
M2 删旧 kernel 时把 A.1 基元物理搬入本文件。**结构性禁止**引入 A.3 信号打分符号。
"""
from __future__ import annotations

from nutmeg.services.jczq_market_kernel import (
    OUTCOMES,
    _crs_from_pool,
    _devig_map,
    _fair_from_odds,
    _had_from_pool,
    _signed_float,
    _ttg_from_pool,
)

__all__ = [
    "OUTCOMES",
    "devig",
    "euro_snapshot_from_bold_odds",
    "fair_1x2",
    "snapshots_from_sporttery",
]


def devig(odds: dict[str, float]) -> dict[str, float]:
    """任意键赔率 → 去水 fair 概率(和≈1)。空/不可用 → 空 dict。"""
    return _devig_map(odds)


def fair_1x2(had_odds: dict[str, float]) -> dict[str, float]:
    """胜平负三路赔率 → 去水 fair(home/draw/away)。"""
    return _fair_from_odds(had_odds)


def _snapshot_id(match_no: str, taken_at: str, kind: str) -> str:
    """确定性 id:同场同时刻同 kind 只产一条(store 幂等靠它)。"""
    return f"S-{kind}-{match_no}-{taken_at}"


def snapshots_from_sporttery(
    value: dict, *, run_date: str, taken_at: str, source: str, kind: str,
) -> list:
    """sporttery getMatchCalculatorV1 的 value → MarketSnapshot 列表(净化版)。

    附录 A.2:同 bold_matches_from_sporttery 的解析逻辑,但产 MarketSnapshot、
    fair 逐市场去水、**不产 tags/信号字段**、不调 _strong_favorite_tags。
    只保留在售且 businessDate==run_date 的场;每市场有可用赔率才写 fair。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(
                raw.get("businessDate") or day.get("businessDate") or ""
            )
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            hhad_pool = raw.get("hhad") or {}
            had_odds = _had_from_pool(raw.get("had") or {})
            hhad_odds = _had_from_pool(hhad_pool)
            ttg_odds = _ttg_from_pool(raw.get("ttg") or {})
            crs_odds = _crs_from_pool(raw.get("crs") or {})
            if not (len(had_odds) >= 3 or len(hhad_odds) >= 3 or ttg_odds or crs_odds):
                continue
            raw_odds: dict[str, dict[str, float]] = {}
            fair: dict[str, dict[str, float]] = {}
            if len(had_odds) >= 3:
                raw_odds["had"] = had_odds
                fair["had"] = fair_1x2(had_odds)
            if len(hhad_odds) >= 3:
                raw_odds["hhad"] = hhad_odds
                fair["hhad"] = fair_1x2(hhad_odds)
            if ttg_odds:
                raw_odds["ttg"] = ttg_odds
                fair["ttg"] = devig(ttg_odds)
            if crs_odds:
                raw_odds["crs"] = crs_odds
                fair["crs"] = devig(crs_odds)
            hhad_line = (
                _signed_float(hhad_pool.get("goalLineValue"))
                or _signed_float(hhad_pool.get("goalLine")) or 0.0
            )
            snaps.append(MarketSnapshot(
                snapshot_id=_snapshot_id(match_no, taken_at, kind),
                match_id=f"M-{run_date}-{match_no}",
                taken_at=taken_at, kind=kind, source=source,
                fair=fair, raw_odds=raw_odds,
                lines={"hhad_line": hhad_line},
            ))
    return snaps


def euro_snapshot_from_bold_odds(
    bold_odds: dict, *, run_date: str, taken_at: str, kind: str, source: str,
) -> list:
    """欧赔 bold_odds（{竞彩号: {market: MarketOdds}}）→ MarketSnapshot 列表。

    只取 match_winner 的去水 fair_probability（欧赔已去水，是最 sharp 三路估计），
    作为 had 市场的 fair。空 fair 的场跳过。不产 tags/信号字段（净化不变）。
    收盘快照(kind=closing)与读时锚(kind=read_time)共用本构造器。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for match_no, markets in bold_odds.items():
        mw = markets.get("match_winner")
        fair = dict(getattr(mw, "fair_probability", {}) or {}) if mw else {}
        if not fair or abs(sum(fair.values())) < 1e-9:
            continue
        snaps.append(MarketSnapshot(
            snapshot_id=_snapshot_id(match_no, taken_at, kind),
            match_id=f"M-{run_date}-{match_no}",
            taken_at=taken_at, kind=kind, source=source,
            fair={"had": fair}, raw_odds={},
            lines={},
        ))
    return snaps
