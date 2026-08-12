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


def audit_history(output_dir) -> dict:
    """把 ``daily/*/sporttery_markets.json`` 全部板面跑一遍覆盖率——加完别名后的验收口径。

    2026-08-05 首跑:1099 场里只有 45.9% 双边命中(瑞超/挪超/韩职/日职 100% 丢锚),
    对应 526 条结算里只有 21 条(4%)有 CLV——closing 端"欧赔缺就不落",
    别名缺失等于把双轴里的快信息轴整根打空。
    """
    import json as _json
    from pathlib import Path

    per_league: dict[str, dict] = {}
    missing: dict[str, int] = {}
    total = covered = 0
    for path in sorted(Path(output_dir).glob("daily/*/sporttery_markets.json")):
        try:
            value = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        report = audit_board(value)
        total += report["n_matches"]
        covered += report["odds_alias"]["covered_matches"]
        for row in report["odds_alias"]["missing_teams"]:
            missing[row["name"]] = missing.get(row["name"], 0) + row["count"]
        for raw in board_matches(value):
            league = str(raw.get("leagueAbbName") or "?")
            slot = per_league.setdefault(league, {"n": 0, "covered": 0})
            slot["n"] += 1
        for raw, ok in _covered_flags(value):
            slot = per_league[str(raw.get("leagueAbbName") or "?")]
            slot["covered"] += int(ok)
    return {
        "n_days": len(list(Path(output_dir).glob("daily/*/sporttery_markets.json"))),
        "n_matches": total,
        "covered_matches": covered,
        "coverage_pct": round(100 * covered / total, 1) if total else 0.0,
        "by_league": dict(sorted(
            ((k, v) for k, v in per_league.items() if v["n"] > v["covered"]),
            key=lambda kv: kv[1]["covered"] - kv[1]["n"],
        )),
        "missing_teams": dict(sorted(missing.items(), key=lambda kv: -kv[1])),
    }


def _covered_flags(value: dict):
    """(场次, 双边是否命中) —— audit_history 按联赛累计用。"""
    from nutmeg.services.jczq_apifootball_odds import load_team_aliases

    odds = {norm_team(k) for k in load_team_aliases()}
    for raw in board_matches(value):
        names = (str(raw.get("homeTeamAbbName") or ""), str(raw.get("awayTeamAbbName") or ""))
        yield raw, all(norm_team(n) in odds for n in names)


def format_history(report: dict) -> str:
    head = (f"decision-alias-audit --history: {report['n_days']} 天 / "
            f"{report['n_matches']} 场 | 欧赔别名双边命中 "
            f"{report['covered_matches']} = {report['coverage_pct']}%")
    if not report["by_league"]:
        return head + " | 全覆盖"
    lines = [head, "  仍有缺口的联赛(丢锚场次/总场次):"]
    for league, slot in report["by_league"].items():
        lines.append(f"    {league}: {slot['n'] - slot['covered']}/{slot['n']}")
    top = list(report["missing_teams"].items())[:20]
    if top:
        lines.append("  未命中队名 Top20:" + "、".join(f"{k}×{v}" for k, v in top))
    return "\n".join(lines)


def format_audit(run_date: str, report: dict) -> str:
    """一行摘要 + 缺口清单。命中率 100% 时只有一行。"""
    n = report["n_matches"]
    covered = report["odds_alias"]["covered_matches"]
    missing = report["odds_alias"]["missing_teams"]
    missing_leagues = report["entity_alias"]["missing_leagues"]
    head = (f"decision-alias-audit {run_date}: 板面 {n} 场 | "
            f"欧赔别名双边命中 {covered}/{n}")
    if not missing and not missing_leagues:
        return head + " | 无缺口"
    lines = [head]
    if missing:
        lines.append(
            "  ⚠️ 采集侧未命中(丢国际欧赔锚,prior 退化成体彩去水): "
            + "、".join(
                f"{r['name']}[{r['league']}]" + ("" if r["has_entity"] else "*")
                for r in missing
            )
        )
        lines.append(
            "     修法:API-Football /teams?search= 核对官方拼写 → "
            "nutmeg/data/jczq_club_team_aliases.json(* = 实体表同样缺)"
        )
    if missing_leagues:
        lines.append(
            "  ⚠️ 实体侧联赛未解析(league scope_key 无处可挂): "
            + "、".join(f"{r['name']}×{r['count']}" for r in missing_leagues)
        )
        lines.append(
            "     修法:decision_entities_seed.json 建 League(name_zh 必须精确等于"
            "体彩 leagueAbbName)→ nutmeg decision-entities-sync"
        )
    return "\n".join(lines)
