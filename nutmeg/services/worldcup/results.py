"""世界杯赛果摄取 — Fixture(API-Football)→ WcResult(90 分钟口径,spec §2.2)。

匹配规则:双方队名都是世界杯 48 队 + 容忍主客翻转(对齐 jczq_apifootball_odds 的
容错惯例)。幂等:同 match_id 不重复入账。绝不猜测:对不上的 fixture 直接忽略。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from nutmeg.domain.fixtures import Fixture, FixtureStatus

from .tournament import Tournament


@dataclass(frozen=True, slots=True)
class WcResult:
    match_id: str
    home: str
    away: str
    status: str               # FT / AET / PEN
    outcome_90: str           # home / draw / away(竞彩口径)
    goals_h_90: int | None    # 仅 FT 可知
    goals_a_90: int | None
    advanced: str | None      # 淘汰赛晋级方;小组赛 None


def _outcome(gh: int, ga: int) -> str:
    return "home" if gh > ga else "away" if gh < ga else "draw"


def ingest_results(
    fixtures: list[Fixture], tournament: Tournament, *, existing: list[WcResult]
) -> list[WcResult]:
    known = {r.match_id for r in existing}
    by_pair: dict[frozenset[str], str] = {}
    knockout: dict[str, bool] = {}
    for m in tournament.matches:
        if m.stage == "group":
            by_pair[frozenset((m.home, m.away))] = m.match_id
            knockout[m.match_id] = False
    # 淘汰赛场次队名运行时才定,用「双方都是 WC 队 + 日期在窗口」兜底:
    # 按 date_utc 找当天未占用的淘汰赛槽位场次。
    ko_by_date: dict[str, list] = {}
    for m in tournament.matches:
        if m.stage != "group":
            ko_by_date.setdefault(m.date_utc, []).append(m)

    out = list(existing)
    for fx in fixtures:
        if fx.status is not FixtureStatus.FINISHED:
            continue
        if fx.home_team not in tournament.teams or fx.away_team not in tournament.teams:
            continue
        pair = frozenset((fx.home_team, fx.away_team))
        match_id = by_pair.get(pair)
        if match_id is None:
            day = fx.kickoff_at.date().isoformat()
            candidates = [
                m for m in ko_by_date.get(day, []) if m.match_id not in known
            ]
            if not candidates:
                continue
            match_id = candidates[0].match_id
            knockout[match_id] = True
        if match_id in known:
            continue
        gh, ga = fx.home_goals or 0, fx.away_goals or 0
        if fx.status_short == "FT":
            rec = WcResult(match_id, fx.home_team, fx.away_team, "FT",
                           _outcome(gh, ga), gh, ga,
                           None if not knockout.get(match_id) else
                           (fx.home_team if gh > ga else fx.away_team if ga > gh
                            else None))
        elif fx.status_short == "AET":
            adv = fx.home_team if gh > ga else fx.away_team
            rec = WcResult(match_id, fx.home_team, fx.away_team, "AET",
                           "draw", None, None, adv)
        elif fx.status_short == "PEN":
            ph, pa = fx.penalty_home or 0, fx.penalty_away or 0
            adv = fx.home_team if ph > pa else fx.away_team
            rec = WcResult(match_id, fx.home_team, fx.away_team, "PEN",
                           "draw", None, None, adv)
        else:
            continue
        known.add(match_id)
        out.append(rec)
    return out


def load_results(path: Path) -> list[WcResult]:
    if not path.exists():
        return []
    return [WcResult(**r) for r in json.loads(path.read_text(encoding="utf-8"))]


def save_results(path: Path, results: list[WcResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
