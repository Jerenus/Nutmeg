"""收盘快照捕获——近开赛再抓欧赔 live 价 → kind=closing 快照(CLV 参照,spec §9 精化 1)。

closing = ``fetch._default_euro_fetcher`` 的欧赔去水 fair,即与开盘链**同一个源**
(2026-09-14 起 titan007 主、API-Football 补缺)。开盘用一源、收盘用另一源会让 CLV
轴两端不可比,故此处刻意复用同一入口而非另起。

换源前 CLV 轴是饿着的:970 条已结 Read 只有 69 条有 clv_pp,收盘快照 122 条 vs
读时快照 2264 条(5.4%)——因为旧源受 100 次/天配额所限,收盘那一抓常常抓不到。

欧赔缺 → 不落(reconcile 遇缺则 CLV=null,绝不伪造)。live_fetcher 可注入替身供测试。
"""
from __future__ import annotations

from dataclasses import replace

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import (
    euro_snapshot_from_bold_odds,
    load_sporttery_snapshot,
)


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
        from nutmeg.decision.fetch import _default_euro_fetcher
        live_fetcher = _default_euro_fetcher
    from nutmeg.decision.fetch import unpack_euro_result
    bold, provenance = unpack_euro_result(live_fetcher(value, run_date=run_date))
    # 欧赔快照产竞彩号 match_id(队名不在 bold_odds),此处按体彩盘改写为 canonical——
    # 否则收盘快照 match_id 与 canonical Read 对不上,CLV 无从算(2026-07-06 修)。
    no_to_canonical = _no_to_canonical(value, run_date)
    n = 0
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="closing", source="apifootball", source_by_match=provenance,
    ):
        no = s.match_id.rsplit("-", 1)[-1]
        canonical = no_to_canonical.get(no)
        store.upsert(replace(s, match_id=canonical) if canonical else s)
        n += 1
    return n
