"""sense — 拉盘口→去水→存 Match+Snapshot(spec §3 动词一)。

M0:从已存 sporttery 快照 replay(不打网,对齐 verify skill replay 配方)。
live 抓取(fetch_sporttery_value_with_fallback + 500.com 备源)在 M1 编排接入。
"""
from __future__ import annotations

from nutmeg.decision.market_data import snapshots_from_sporttery
from nutmeg.decision.ontology import Match
from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot


def sense_from_snapshot(run_date: str, *, output_dir, taken_at: str,
                        store) -> int:
    """已存 sporttery 快照 → MarketSnapshot + Match 入库。返回入库场数。"""
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    snaps = snapshots_from_sporttery(
        value, run_date=run_date, taken_at=taken_at,
        source="sporttery", kind="read_time",
    )
    for s in snaps:
        # 从 value 里回捞队名建 Match(snapshot 已带 match_id)
        store.upsert(_match_for_snapshot(s, value, run_date))
        store.upsert(s)
    return len(snaps)


def _match_for_snapshot(snapshot, value: dict, run_date: str) -> Match:
    match_no = snapshot.match_id.rsplit("-", 1)[-1]
    home = away = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchNumStr") or "") == match_no:
                home = str(raw.get("homeTeamAbbName") or "")
                away = str(raw.get("awayTeamAbbName") or "")
    return Match(
        match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
        home=home, away=away, competition="",
        channel_refs={"jczq_match_no": match_no},
    )
