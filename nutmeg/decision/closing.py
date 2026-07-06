"""收盘快照捕获——近开赛再抓欧赔 live 价 → kind=closing 快照(CLV 参照,spec §9 精化 1)。

closing = collect_bold_odds_apifootball_live 的欧赔去水 fair。欧赔缺 → 不落
（reconcile 遇缺则 CLV=null,绝不伪造）。live_fetcher 可注入替身供测试。
"""
from __future__ import annotations

from dataclasses import replace

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot


def _no_to_canonical(value: dict, run_date: str) -> dict[str, str]:
    """体彩盘 竞彩号→canonical 映射(收盘欧赔快照据此对齐 canonical 身份)。"""
    out: dict[str, str] = {}
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            out[str(raw.get("matchNumStr") or "")] = canonical_match_id(h, a, run_date)
    return out


def capture_closing(run_date: str, *, output_dir, taken_at: str, store,
                    live_fetcher=None) -> int:
    """再抓 live 欧赔 → 收盘欧赔快照入库(canonical 身份)。返回入库数。"""
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    if live_fetcher is None:
        from nutmeg.services.jczq_apifootball_odds import (
            collect_bold_odds_apifootball_live,
        )
        live_fetcher = collect_bold_odds_apifootball_live
    bold = live_fetcher(value, run_date=run_date) or {}
    # 欧赔快照产竞彩号 match_id(队名不在 bold_odds),此处按体彩盘改写为 canonical——
    # 否则收盘快照 match_id 与 canonical Read 对不上,CLV 无从算(2026-07-06 修)。
    no_to_canonical = _no_to_canonical(value, run_date)
    n = 0
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="closing", source="apifootball",
    ):
        no = s.match_id.rsplit("-", 1)[-1]
        canonical = no_to_canonical.get(no)
        store.upsert(replace(s, match_id=canonical) if canonical else s)
        n += 1
    return n
