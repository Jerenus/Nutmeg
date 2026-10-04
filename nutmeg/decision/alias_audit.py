"""别名覆盖审计——未命中 = 该场丢国际欧赔锚,prior 静默退化成体彩去水。

2026-08-05 发现:8/04 板面 7 场每场都有队名未命中 → ``bold_odds.json`` 根本没生成,
而 ``anchor.resolve_prior`` 会安静地回落到 sporttery fair(CLV 两端不再自洽)。
静默降级是最贵的那种坏——这里把它变成一行可见清单。

两套别名各管一段,都要审:
- 采集侧(``jczq_apifootball_odds.load_team_aliases``):中文 → API-Football 英文名,
  决定这场**能不能拿到国际欧赔**。双边都命中才有 fair 锚。
- 实体侧(``entities.load_*_alias_table``):中文 → ``team_id`` / ``league_id``,
  决定 Read 的 ``scope_key`` 挂不挂得上。球队未解析是策展设计(不报警),
  联赛未解析则意味着 league scope 因子无处可挂(报警)。
"""
from __future__ import annotations

from nutmeg.decision.identity import norm_team


def board_matches(value: dict) -> list[dict]:
    """体彩快照 → 扁平场次列表(与 sense 同口径:matchInfoList/subMatchList)。"""
    out: list[dict] = []
    for day in value.get("matchInfoList") or []:
        if not isinstance(day, dict):
            continue
        for raw in day.get("subMatchList") or []:
            if isinstance(raw, dict) and raw.get("homeTeamAbbName"):
                out.append(raw)
    return out


def audit_board(value: dict) -> dict:
    """审计一份体彩板面快照的别名覆盖。纯函数,不打网、不读盘。"""
    from nutmeg.decision.entities import load_league_alias_table, load_team_alias_table
    from nutmeg.services.jczq_apifootball_odds import load_team_aliases

    odds_aliases = {norm_team(k): v for k, v in load_team_aliases().items()}
    team_table = load_team_alias_table()
    league_table = load_league_alias_table()

    matches = board_matches(value)
    missing_odds: dict[str, dict] = {}
    missing_leagues: dict[str, int] = {}
    covered = 0
    for raw in matches:
        league = str(raw.get("leagueAbbName") or "")
        names = [
            str(raw.get("homeTeamAbbName") or ""),
            str(raw.get("awayTeamAbbName") or ""),
        ]
        hits = 0
        for name in names:
            if norm_team(name) in odds_aliases:
                hits += 1
                continue
            row = missing_odds.setdefault(
                name, {"name": name, "league": league, "count": 0,
                       "has_entity": norm_team(name) in team_table}
            )
            row["count"] += 1
        if hits == len(names):
            covered += 1
        if league and norm_team(league) not in league_table:
            missing_leagues[league] = missing_leagues.get(league, 0) + 1

    return {
        "n_matches": len(matches),
        "odds_alias": {
            "covered_matches": covered,
            "missing_teams": sorted(
                missing_odds.values(), key=lambda r: (-r["count"], r["name"])
            ),
        },
        "entity_alias": {
            "missing_leagues": [
                {"name": name, "count": n} for name, n in sorted(
                    missing_leagues.items(), key=lambda kv: (-kv[1], kv[0])
                )
            ],
        },
    }


def audit_day(run_date: str, output_dir) -> dict:
    """读当日已存体彩快照做审计。无快照 → ``n_matches=0``(不算失败)。"""
    from nutmeg.decision.market_data import load_sporttery_snapshot

    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return {"n_matches": 0, "odds_alias": {"covered_matches": 0, "missing_teams": []},
                "entity_alias": {"missing_leagues": []}, "note": "无体彩快照"}
    return audit_board(value)


