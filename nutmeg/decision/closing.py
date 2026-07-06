"""收盘快照捕获——近开赛再抓欧赔 live 价 → kind=closing 快照(CLV 参照,spec §9 精化 1)。

closing = collect_bold_odds_apifootball_live 的欧赔去水 fair。欧赔缺 → 不落
（reconcile 遇缺则 CLV=null,绝不伪造）。live_fetcher 可注入替身供测试。
"""
from __future__ import annotations

from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot


def capture_closing(run_date: str, *, output_dir, taken_at: str, store,
                    live_fetcher=None) -> int:
    """再抓 live 欧赔 → 收盘欧赔快照入库。返回入库收盘快照数。"""
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    if live_fetcher is None:
        from nutmeg.services.jczq_apifootball_odds import (
            collect_bold_odds_apifootball_live,
        )
        live_fetcher = collect_bold_odds_apifootball_live
    bold = live_fetcher(value, run_date=run_date) or {}
    snaps = euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="closing", source="apifootball",
    )
    for s in snaps:
        store.upsert(s)
    return len(snaps)
