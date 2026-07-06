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


def _load_euro_bold_odds(run_date: str, output_dir) -> dict:
    """读时欧赔 bold_odds（现 SOP 已抓的 bold_odds.json，含去水 fair_probability）。
    缺文件/坏结构 → {}（优雅降级，只落体彩快照）。"""
    from nutmeg.services.jczq_market_kernel import load_bold_odds_snapshot
    try:
        return load_bold_odds_snapshot(run_date, output_dir) or {}
    except Exception:  # noqa: BLE001 — 欧赔缺不阻塞体彩落库
        return {}


def sense_day(run_date: str, *, output_dir, taken_at: str, store) -> int:
    """一天的读时感知：体彩快照(下注用) + 欧赔快照(先验锚+CLV) 一并落库。

    体彩从 sporttery_markets.json；欧赔从 bold_odds.json（现 SOP 已抓）。
    返回入库场数（以体彩为准）。M1 用已存快照 replay，不新增打网。
    """
    from nutmeg.decision.market_data import (
        euro_snapshot_from_bold_odds,
        snapshots_from_sporttery,
    )
    from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot

    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    tc_snaps = snapshots_from_sporttery(
        value, run_date=run_date, taken_at=taken_at,
        source="sporttery", kind="read_time",
    )
    for s in tc_snaps:
        store.upsert(_match_for_snapshot(s, value, run_date))
        store.upsert(s)
    bold = _load_euro_bold_odds(run_date, output_dir)
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="read_time", source="apifootball",
    ):
        store.upsert(s)
    return len(tc_snaps)
