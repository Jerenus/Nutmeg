"""sense — 拉盘口→去水→存 Match+Snapshot(spec §3 动词一)。

M0:从已存 sporttery 快照 replay(不打网,对齐 verify skill replay 配方)。
live 抓取(fetch_sporttery_value_with_fallback + 500.com 备源)在 M1 编排接入。
"""
from __future__ import annotations

from nutmeg.decision.identity import canonical_match_id
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
        upsert_match_merged(store, _match_for_snapshot(s, value, run_date))
        store.upsert(s)
    return len(snaps)


def _match_for_snapshot(snapshot, value: dict, run_date: str) -> Match:
    """按 canonical 反查队名/竞彩号(snapshot.match_id 现为 canonical)。"""
    home = away = match_no = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            if canonical_match_id(h, a, run_date) == snapshot.match_id:
                home, away = h, a
                match_no = str(raw.get("matchNumStr") or "")
    return Match(
        match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
        home=home, away=away, competition="",
        channel_refs={"jczq_match_no": match_no},
    )


def upsert_match_merged(store, match) -> None:
    """落 Match 前合并 channel_refs——同一 canonical 比赛被第二通道 sense 时,
    不覆盖对方通道号(spec §2 一场多通道);已解析的实体 id/联赛名同理不被
    未解析通道的空值 clobber(实体层提案 §P3)。"""
    from dataclasses import replace

    existing = store.get(Match, match.match_id)
    if existing is not None:
        match = replace(
            match,
            channel_refs={**existing.channel_refs, **match.channel_refs},
            competition=match.competition or existing.competition,
            home_team_id=match.home_team_id or existing.home_team_id,
            away_team_id=match.away_team_id or existing.away_team_id,
            competition_id=match.competition_id or existing.competition_id,
        )
    store.upsert(match)


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
    from dataclasses import replace

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
    today_match_ids = {s.match_id for s in tc_snaps}
    # 体彩盘的 竞彩号→canonical 映射(欧赔快照按此对齐到 canonical 身份)
    no_to_canonical: dict[str, str] = {}
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            no_to_canonical[str(raw.get("matchNumStr") or "")] = canonical_match_id(
                h, a, run_date
            )
    for s in tc_snaps:
        upsert_match_merged(store, _match_for_snapshot(s, value, run_date))
        store.upsert(s)
    bold = _load_euro_bold_odds(run_date, output_dir)
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="read_time", source="apifootball",
    ):
        # 欧赔快照仍产竞彩号 match_id(队名不在 bold_odds),此处改写为 canonical。
        # 只落今天体彩盘在售场的欧赔锚——bold_odds 常含次日场(跨日竞彩号),
        # 否则会给非今日场产孤儿欧赔快照→被 backfill_shadows 误补 shadow。
        no = s.match_id.rsplit("-", 1)[-1]
        canonical = no_to_canonical.get(no)
        if canonical and canonical in today_match_ids:
            store.upsert(replace(s, match_id=canonical))
    return len(tc_snaps)
