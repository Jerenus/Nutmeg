"""实体解析(策展式)+ 实体种子——队名/联赛名 → 稳定 *_id(实体层提案 §P2/§P3)。

别名来源(政策即数据,DRY 不新建第三个文件):
- jczq_national_team_aliases.json(复用): 中文名 → API-Football 英文名;id=slugify(英文)。
- decision_entities_seed.json: 策展 Team/League;aliases+name_zh+name_en 自动进表。
未命中 → None(调用方记 log,*_id=null 照常入库)。绝不模糊匹配、绝不自动造对象
——防几百支无知识球队污染 store;Team/League 只为"我们对它有知识"的实体而生。
"""
from __future__ import annotations

import json
import re
from importlib import resources

from nutmeg.decision.identity import norm_team
from nutmeg.decision.ontology import League, Team

_ENTITIES_RESOURCE = "decision_entities_seed.json"
_NATIONAL_RESOURCE = "jczq_national_team_aliases.json"


def slugify(name: str) -> str:
    """稳定 id 片段:casefold + 非词字符折叠成 '-'。重音保留(对齐 API-Football 拼写)。"""
    return re.sub(r"[\W_]+", "-", (name or "").casefold(), flags=re.UNICODE).strip("-")


def _load_json(resource: str) -> dict:
    return json.loads(
        resources.files("nutmeg.data").joinpath(resource).read_text(encoding="utf-8")
    )


def load_seed_entities() -> tuple[list[Team], list[League]]:
    data = _load_json(_ENTITIES_RESOURCE)
    teams = [Team.from_dict(t) for t in data.get("teams") or []]
    leagues = [League.from_dict(lg) for lg in data.get("leagues") or []]
    return teams, leagues


def load_team_alias_table() -> dict[str, str]:
    """{norm_team(alias): team_id}。国家队表 ⊕ 种子实体,种子优先(setdefault 序)。"""
    table: dict[str, str] = {}
    teams, _ = load_seed_entities()
    for t in teams:
        for alias in [t.name_zh, t.name_en, *t.aliases]:
            if alias:
                table.setdefault(norm_team(alias), t.team_id)
    for zh, en in _load_json(_NATIONAL_RESOURCE).items():
        if zh.startswith("_"):
            continue                                 # "_comment" 注释键
        table.setdefault(norm_team(zh), slugify(en))
        table.setdefault(norm_team(en), slugify(en))
    return table


def load_league_alias_table() -> dict[str, str]:
    table: dict[str, str] = {}
    _, leagues = load_seed_entities()
    for lg in leagues:
        for alias in [lg.name_zh, lg.name_en]:
            if alias:
                table.setdefault(norm_team(alias), lg.league_id)
    return table


def resolve_team(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def resolve_league(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def seed_entities_if_empty(store) -> int:
    """store 无 Team 且无 League 时落种子(幂等,同 seed_factors_if_empty 模式)。"""
    if store.load(Team) or store.load(League):
        return 0
    teams, leagues = load_seed_entities()
    store.upsert_many(teams)
    store.upsert_many(leagues)
    return len(teams) + len(leagues)
