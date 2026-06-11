"""世界杯 2026 赛制 — 静态数据模型、加载校验、排名与对阵规则(spec §2)。

纯函数、无 I/O 副作用(load 只读仓内静态 JSON)。所有随机平局裁决都由调用方
注入 ``random.Random``,保证模拟确定性。
"""
from __future__ import annotations

import json
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
