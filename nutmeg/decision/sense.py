"""sense — 拉盘口→去水→存 Match+Snapshot(spec §3 动词一)。

M0:从已存 sporttery 快照 replay(不打网,对齐 verify skill replay 配方)。
live 抓取(fetch_sporttery_value_with_fallback + 500.com 备源)在 M1 编排接入。
"""
from __future__ import annotations

import logging

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import (
    load_sporttery_snapshot,
    snapshots_from_sporttery,
)
from nutmeg.decision.ontology import Match

logger = logging.getLogger(__name__)


def _match_for_snapshot(snapshot, value: dict, run_date: str, *,
                        team_table=None, league_table=None) -> Match:
    """按 canonical 反查队名/竞彩号/联赛名(snapshot.match_id 现为 canonical),
    并策展式 resolve 实体 id(命中填,未命中 None——绝不伪造/模糊匹配)。"""
    from nutmeg.decision.entities import (
        load_league_alias_table,
        load_team_alias_table,
        resolve_league,
        resolve_team,
    )

    if team_table is None:
        team_table = load_team_alias_table()
    if league_table is None:
        league_table = load_league_alias_table()
    home = away = match_no = league = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            if canonical_match_id(h, a, run_date) == snapshot.match_id:
                home, away = h, a
                match_no = str(raw.get("matchNumStr") or "")
                league = str(raw.get("leagueAbbName") or "")
    return Match(
        match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
        home=home, away=away, competition=league,
        channel_refs={"jczq_match_no": match_no},
        home_team_id=resolve_team(home, team_table),
        away_team_id=resolve_team(away, team_table),
        competition_id=resolve_league(league, league_table),
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
    from nutmeg.decision.market_data import load_bold_odds_snapshot
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
    )

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
    from nutmeg.decision.entities import load_league_alias_table, load_team_alias_table

    team_table = load_team_alias_table()
    league_table = load_league_alias_table()
    misses: set[str] = set()
    for s in tc_snaps:
        m = _match_for_snapshot(s, value, run_date,
                                team_table=team_table, league_table=league_table)
        if m.home and m.home_team_id is None:
            misses.add(m.home)
        if m.away and m.away_team_id is None:
            misses.add(m.away)
        upsert_match_merged(store, m)
        store.upsert(s)
    if misses:   # 绝不静默:未命中照常入库(*_id=null),聚合一行可见
        logger.info("sense resolve 未命中别名表(照常入库,*_id=null): %s",
                    "、".join(sorted(misses)))
    bold = _load_euro_bold_odds(run_date, output_dir)
    # 血统表按场覆盖源名(2026-09-14 换源后 bold_odds 是 titan007+apifootball 合并
    # 产物)。换源前的历史日子没有这个文件,回落 apifootball——那些日子的欧赔确实
    # 全部来自它,回落是事实正确的。
    from nutmeg.decision.market_data import load_bold_odds_provenance
    euro_provenance = load_bold_odds_provenance(run_date, output_dir)
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="read_time", source="apifootball", source_by_match=euro_provenance,
    ):
        # 欧赔快照仍产竞彩号 match_id(队名不在 bold_odds),此处改写为 canonical。
        # 只落今天体彩盘在售场的欧赔锚——bold_odds 常含次日场(跨日竞彩号),
        # 否则会给非今日场产孤儿欧赔快照→被 backfill_shadows 误补 shadow。
        no = s.match_id.rsplit("-", 1)[-1]
        canonical = no_to_canonical.get(no)
        if canonical and canonical in today_match_ids:
            store.upsert(replace(s, match_id=canonical))
    return len(tc_snaps)
