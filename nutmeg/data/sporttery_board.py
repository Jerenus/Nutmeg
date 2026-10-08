"""体彩计算器快照（`matchInfoList` → `subMatchList`）的遍历（2026-10-08 复查）。

此前「在售 + 业务日」过滤手写了 4 份（`fetch` 的漏场分母、内核入库、titan007 与 API-Football 两个
赔率源），彼此的说明都写着「口径必须一致」；摊平也写了 2 份。一份快照可能含**多个业务日**，
不按 `businessDate` 过滤会把次日的场当成今天的。
"""
from __future__ import annotations


def flatten(value: dict) -> list[dict]:
    """摊平全部场次（不管状态与业务日）；不是 dict 的组 / 行跳过。"""
    rows = []
    for day in (value or {}).get("matchInfoList") or []:
        if not isinstance(day, dict):
            continue
        rows += [raw for raw in day.get("subMatchList") or [] if isinstance(raw, dict)]
    return rows


def selling_rows(value: dict, business_date: str | None) -> list[tuple[dict, str]]:
    """在售（`matchStatus=Selling`）且属于 `business_date` 的场次 → [(原始行, 该行业务日)]。

    行上没写业务日就用组上的；`business_date` 为空或行上查不到业务日时不过滤（不猜）。"""
    out = []
    for day in (value or {}).get("matchInfoList") or []:
        if not isinstance(day, dict):
            continue
        for raw in day.get("subMatchList") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            row_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if business_date and row_date and row_date != business_date:
                continue
            out.append((raw, row_date))
    return out
