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
from pathlib import Path

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
        for alias in [lg.name_zh, lg.name_en, *lg.aliases]:
            if alias:
                table.setdefault(norm_team(alias), lg.league_id)
    return table


def resolve_team(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def resolve_league(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def seed_path() -> Path:
    """种子文件的可写真身路径(回灌 store 漂移用)。"""
    return Path(str(resources.files("nutmeg.data").joinpath(_ENTITIES_RESOURCE)))


def merge_profile_notes(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """画像笔记按 key 合并:同 key 取 ``at`` 更新的一条,新 key 追加在后。
    两侧都不丢——store 里现场追加的笔记与种子里策展的笔记同为一等公民。"""
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for note in [*(existing or []), *(incoming or [])]:
        if not isinstance(note, dict):
            continue
        key = str(note.get("key") or note.get("note") or "")
        if key not in by_key:
            by_key[key] = note
            order.append(key)
        elif str(note.get("at") or "") >= str(by_key[key].get("at") or ""):
            by_key[key] = note
    return [by_key[k] for k in order]


def _merged_entity(cls, current, seed):
    """种子的非空标量覆盖 store,笔记按 key 合并。返回合并后对象(可能 == current)。"""
    payload = current.to_dict()
    for key, value in seed.to_dict().items():
        if key != "profile_notes" and value:
            payload[key] = value
    payload["profile_notes"] = merge_profile_notes(
        current.profile_notes, seed.profile_notes
    )
    return cls.from_dict(payload)


def sync_entities(store) -> dict[str, int]:
    """幂等 upsert 种子实体到 store(不再是"只在空库落种子")。

    旧 ``seed_entities_if_empty`` 在非空库上恒为 no-op,新增联赛/球队永远进不去
    ——这是 2026-08-05 发现的缺口。合并规则见 ``merge_profile_notes``:
    store 现场笔记与种子笔记双向保留,同 key 取更新的。
    """
    teams, leagues = load_seed_entities()
    stats = {"added": 0, "updated": 0, "unchanged": 0}
    for cls, seeds in ((Team, teams), (League, leagues)):
        by_id = {o.id: o for o in store.load(cls)}
        for seed in seeds:
            current = by_id.get(seed.id)
            if current is None:
                store.upsert(seed)
                stats["added"] += 1
                continue
            merged = _merged_entity(cls, current, seed)
            if merged == current:
                stats["unchanged"] += 1
            else:
                store.upsert(merged)
                stats["updated"] += 1
    return stats


def export_entities_to_seed(store, path: Path | None = None) -> dict[str, int]:
    """把 store 里领先的实体/笔记回灌种子文件——消除 store↔seed 漂移。

    (store 曾单向领先:``bra-serie-a`` 只在 store、``uefa-qualifiers`` store 3 条
    笔记 vs 种子 1 条。种子是可 review 的策展真身,漂移久了就没人知道谁对。)
    """
    target = path or seed_path()
    data = json.loads(target.read_text(encoding="utf-8"))
    written = {"teams": 0, "leagues": 0}
    for cls, field in ((Team, "teams"), (League, "leagues")):
        seeded = {row.get(f"{cls.__name__.lower()}_id"): row for row in data.get(field) or []}
        rows: list[dict] = []
        for obj in sorted(store.load(cls), key=lambda o: o.id):
            payload = obj.to_dict()
            prior = seeded.get(obj.id)
            if prior:
                payload["profile_notes"] = merge_profile_notes(
                    prior.get("profile_notes") or [], obj.profile_notes
                )
            rows.append(payload)
        data[field] = rows
        written[field] = len(rows)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return written


def add_profile_note(store, *, league_id: str | None = None, team_id: str | None = None,
                     key: str, note: str, evidence: str, at: str) -> str:
    """给已有 League/Team 追加一条画像笔记。同 key 覆盖(新的 at 更新)。

    ``evidence`` 必填且拒绝空值——画像是**证据式笔记**不是规则;没有证据的断言
    应该走 Read 的 factor 走双轴检验,而不是沉淀成永久画像。
    """
    if bool(league_id) == bool(team_id):
        raise ValueError("需且仅需一个 --league 或 --team")
    if not (key and note):
        raise ValueError("--key 与 --note 必填")
    if not evidence.strip():
        raise ValueError("--evidence 必填(画像是证据式笔记,无证据不落库)")
    cls = League if league_id else Team
    entity_id = league_id or team_id
    current = store.get(cls, entity_id)
    if current is None:
        raise ValueError(
            f"{cls.__name__} {entity_id} 不在 store——先在 decision_entities_seed.json "
            f"建实体(League 的 name_zh 必须精确等于体彩 leagueAbbName),"
            f"再跑 nutmeg decision-entities-sync"
        )
    payload = current.to_dict()
    payload["profile_notes"] = merge_profile_notes(
        current.profile_notes,
        [{"key": key, "note": note, "evidence": evidence, "at": at}],
    )
    store.upsert(cls.from_dict(payload))
    return f"{cls.__name__} {entity_id}: 笔记 {key} 已落库({len(payload['profile_notes'])} 条)"


def profiles_for_board(store, competitions, team_names) -> dict:
    """当日板面涉及的 League/Team 画像——判读前注入用(不注入 = 建了也读不到)。

    未解析的联赛/球队不报错(策展式:只为"我们有知识"的实体而生),
    但联赛未解析会出现在 ``unresolved_leagues``——那意味着 scope_key 无处可挂。
    """
    league_table = load_league_alias_table()
    team_table = load_team_alias_table()
    leagues_by_id = {lg.id: lg for lg in store.load(League)}
    teams_by_id = {t.id: t for t in store.load(Team)}

    out_leagues: dict[str, dict] = {}
    unresolved_leagues: list[str] = []
    for name in dict.fromkeys(competitions):
        league_id = resolve_league(name, league_table)
        if league_id is None:
            unresolved_leagues.append(name)
            continue
        entity = leagues_by_id.get(league_id)
        if entity is not None and league_id not in out_leagues:
            out_leagues[league_id] = {
                "league_id": league_id, "board_name": name,
                "name_zh": entity.name_zh, "season": entity.season,
                "profile_notes": entity.profile_notes,
            }
    out_teams: dict[str, dict] = {}
    for name in dict.fromkeys(team_names):
        team_id = resolve_team(name, team_table)
        entity = teams_by_id.get(team_id) if team_id else None
        if entity is not None and entity.profile_notes and team_id not in out_teams:
            out_teams[team_id] = {
                "team_id": team_id, "board_name": name,
                "name_zh": entity.name_zh,
                "profile_notes": entity.profile_notes,
            }
    return {
        "leagues": list(out_leagues.values()),
        "teams": list(out_teams.values()),
        "unresolved_leagues": unresolved_leagues,
    }
