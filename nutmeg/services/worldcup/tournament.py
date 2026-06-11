"""世界杯 2026 赛制 — 静态数据模型、加载校验、排名与对阵规则(spec §2)。

纯函数、无 I/O 副作用(load 只读仓内静态 JSON)。所有随机平局裁决都由调用方
注入 ``random.Random``,保证模拟确定性。
"""
from __future__ import annotations

import json
import random as _random
import re
from dataclasses import dataclass, field
from datetime import date
from importlib import resources

STAGES = ("group", "r32", "r16", "qf", "sf", "third", "final")
_SLOT_RE = re.compile(r"^([12])([A-L])$|^3:([A-L]{2,12})$|^W(\d+)$")


@dataclass(frozen=True, slots=True)
class WcTeam:
    id: str
    zh: str
    group: str
    host: bool = False


@dataclass(frozen=True, slots=True)
class WcMatch:
    match_id: str
    stage: str
    date_utc: str
    venue_country: str
    group: str = ""
    home: str = ""
    away: str = ""
    home_slot: str = ""
    away_slot: str = ""


@dataclass(frozen=True, slots=True)
class Tournament:
    name: str
    window: tuple[str, str]
    teams: dict[str, WcTeam]
    groups: dict[str, list[str]]
    matches: list[WcMatch] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "Tournament":
        teams = {
            t["id"]: WcTeam(
                id=t["id"], zh=t["zh"], group=t["group"],
                host=bool(t.get("host", False)),
            )
            for t in raw["teams"]
        }
        groups: dict[str, list[str]] = {}
        for t in raw["teams"]:
            groups.setdefault(t["group"], []).append(t["id"])
        matches = [
            WcMatch(
                match_id=m["match_id"], stage=m["stage"],
                date_utc=m["date_utc"], venue_country=m["venue_country"],
                group=m.get("group", ""), home=m.get("home", ""),
                away=m.get("away", ""), home_slot=m.get("home_slot", ""),
                away_slot=m.get("away_slot", ""),
            )
            for m in raw["matches"]
        ]
        return cls(
            name=raw["tournament"],
            window=(raw["window"]["start"], raw["window"]["end"]),
            teams=teams, groups=groups, matches=matches,
        )


def load_tournament() -> Tournament:
    text = (
        resources.files("nutmeg.data")
        .joinpath("wc2026_tournament.json")
        .read_text(encoding="utf-8")
    )
    return Tournament.from_dict(json.loads(text))


def validate_tournament(t: Tournament) -> list[str]:
    """落库守门:队名/槽位引用闭合、日期可解析、stage 合法。返回错误清单。"""
    errors: list[str] = []
    match_ids = {m.match_id for m in t.matches}
    for m in t.matches:
        if m.stage not in STAGES:
            errors.append(f"{m.match_id}: 非法 stage {m.stage}")
        try:
            date.fromisoformat(m.date_utc)
        except ValueError:
            errors.append(f"{m.match_id}: 非法日期 {m.date_utc}")
        if m.stage == "group":
            for side in (m.home, m.away):
                if side not in t.teams:
                    errors.append(f"{m.match_id}: 未知队名 {side}")
            if m.group not in t.groups:
                errors.append(f"{m.match_id}: 未知小组 {m.group}")
        else:
            for slot in (m.home_slot, m.away_slot):
                mt = _SLOT_RE.match(slot)
                if mt is None:
                    errors.append(f"{m.match_id}: 非法槽位 {slot}")
                    continue
                if mt.group(2) and mt.group(2) not in t.groups:
                    errors.append(f"{m.match_id}: 槽位指向未知小组 {slot}")
                if mt.group(4) and f"M{int(mt.group(4)):02d}" not in match_ids:
                    errors.append(f"{m.match_id}: 槽位指向未知场次 {slot}")
    return errors


def _table_rows(
    teams: list[str], goals: dict[tuple[str, str], tuple[int, int]]
) -> dict[str, tuple[int, int, int]]:
    """每队 (pts, gd, gf) — 只统计 goals 里出现且双方都在 teams 的场次。"""
    rows = {t: [0, 0, 0] for t in teams}
    for (h, a), (gh, ga) in goals.items():
        if h not in rows or a not in rows:
            continue
        rows[h][1] += gh - ga
        rows[h][2] += gh
        rows[a][1] += ga - gh
        rows[a][2] += ga
        if gh > ga:
            rows[h][0] += 3
        elif gh < ga:
            rows[a][0] += 3
        else:
            rows[h][0] += 1
            rows[a][0] += 1
    return {t: tuple(v) for t, v in rows.items()}


def rank_group(
    teams: list[str],
    goals: dict[tuple[str, str], tuple[int, int]],
    rng: _random.Random,
) -> list[str]:
    """FIFA 小组排名:积分→净胜→进球→相互战绩(同序)→确定性伪随机抽签。"""
    rows = _table_rows(teams, goals)

    def overall_key(t: str) -> tuple:
        return rows[t]

    ordered = sorted(teams, key=overall_key, reverse=True)
    # 同 (pts,gd,gf) 的平局簇 → 用簇内相互战绩重排;仍平 → rng 抽签
    result: list[str] = []
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and overall_key(ordered[j]) == overall_key(ordered[i]):
            j += 1
        cluster = ordered[i:j]
        if len(cluster) > 1:
            sub = _table_rows(cluster, goals)
            cluster.sort(key=lambda t: (sub[t], rng.random()), reverse=True)
        result.extend(cluster)
        i = j
    return result


def rank_thirds(
    thirds: list[tuple[str, str, int, int, int]],
    rng: _random.Random,
) -> list[tuple[str, str, int, int, int]]:
    """thirds: [(group, team, pts, gd, gf)] → 按 pts/gd/gf/抽签 降序。"""
    return sorted(thirds, key=lambda r: (r[2], r[3], r[4], rng.random()), reverse=True)


def allocate_best_thirds(
    ranked: list[tuple[str, str, int, int, int]],
    slots: dict[str, str],
) -> dict[str, str]:
    """把排名前 len(slots) 的第三名分进槽位。

    slots: {slot_id: 允许的来源组字母串}。确定性贪心:按槽位 id 序,每个槽位取
    「允许组内排名最高且未用」的第三;无解时放宽到任意未用(官方表不可机读时的
    documented fallback,spec §2.1)。
    """
    pool = {g: t for g, t, *_ in ranked[: len(slots)]}
    order = [g for g, *_ in ranked if g in pool]
    alloc: dict[str, str] = {}
    used: set[str] = set()
    for slot_id in sorted(slots):
        allowed = [g for g in order if g not in used and g in slots[slot_id]]
        fallback = [g for g in order if g not in used]
        pick = (allowed or fallback)[0]
        used.add(pick)
        alloc[slot_id] = pool[pick]
    return alloc
