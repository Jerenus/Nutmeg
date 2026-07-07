# tests/decision/test_entities.py
from nutmeg.decision.entities import (
    load_league_alias_table,
    load_seed_entities,
    load_team_alias_table,
    resolve_league,
    resolve_team,
    seed_entities_if_empty,
    slugify,
)
from nutmeg.decision.identity import norm_team


def test_slugify_stable_and_unicode_safe():
    assert slugify("Bosnia & Herzegovina") == "bosnia-herzegovina"
    assert slugify("Türkiye") == "türkiye"          # 重音保留(与 API-Football 拼写对齐)
    assert slugify("USA") == "usa"
    assert slugify("South Korea") == "south-korea"


def test_national_aliases_fold_into_team_table():
    """复用 jczq_national_team_aliases.json:中文/英文都解析到 slug(英文)。"""
    table = load_team_alias_table()
    assert table[norm_team("荷兰")] == "netherlands"
    assert table[norm_team("Netherlands")] == "netherlands"
    assert "_comment" not in table                   # 注释键跳过


def test_seed_entities_feed_alias_tables():
    """种子实体的 aliases/name_zh/name_en 自动进别名表(DRY,无第三个文件)。"""
    team_table = load_team_alias_table()
    assert resolve_team("哈马比", team_table) == "swe-hammarby"
    assert resolve_team("Hammarby", team_table) == "swe-hammarby"
    league_table = load_league_alias_table()
    assert resolve_league("瑞超", league_table) == "swe-allsvenskan"
    assert resolve_league("法甲", league_table) == "fra-ligue1"


def test_resolve_miss_returns_none_never_fuzzy():
    assert resolve_team("不存在的队", load_team_alias_table()) is None
    assert resolve_team("", load_team_alias_table()) is None
    assert resolve_league("不存在联赛", load_league_alias_table()) is None


def test_seed_entities_have_evidence_notes():
    """Tier 2 验收:memory 联赛画像已迁入本体(profile_notes 证据式)。"""
    teams, leagues = load_seed_entities()
    by_id = {lg.league_id: lg for lg in leagues}
    assert "swe-allsvenskan" in by_id
    assert any("主客分裂" in n["note"] for n in by_id["swe-allsvenskan"].profile_notes)
    assert all(n.get("evidence") for lg in leagues for n in lg.profile_notes)
    assert all(n.get("evidence") for t in teams for n in t.profile_notes)


def test_seed_entities_if_empty_idempotent(tmp_path):
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    n1 = seed_entities_if_empty(store)
    n2 = seed_entities_if_empty(store)
    assert n1 > 0 and n2 == 0
    assert store.get(League, "swe-allsvenskan") is not None
