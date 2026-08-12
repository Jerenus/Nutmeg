# tests/decision/test_entities.py
import json

import pytest

from nutmeg.decision.entities import (
    add_profile_note,
    export_entities_to_seed,
    load_league_alias_table,
    load_seed_entities,
    load_team_alias_table,
    merge_profile_notes,
    profiles_for_board,
    resolve_league,
    resolve_team,
    slugify,
    sync_entities,
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


def test_league_aliases_cover_board_name_variants():
    """回归:uefa-qualifiers 的 name_zh 是'欧战资格赛',但板面写'欧冠'——
    没有 aliases 时该实体的画像挂不到任何一场比赛(2026-08-05 由别名审计发现)。"""
    table = load_league_alias_table()
    assert resolve_league("欧冠", table) == "uefa-qualifiers"
    assert resolve_league("欧联", table) == "uefa-qualifiers"
    assert resolve_league("欧战资格赛", table) == "uefa-qualifiers"
    assert resolve_league("荷甲", table) == "ned-eredivisie"
    assert resolve_league("葡超", table) == "por-primeira"


def test_new_league_seeds_match_board_names_exactly():
    """联赛 name_zh 必须精确等于体彩 leagueAbbName,否则 competition_id 恒为 null。"""
    _, leagues = load_seed_entities()
    by_id = {lg.league_id: lg for lg in leagues}
    assert by_id["ned-eredivisie"].name_zh == "荷甲"
    assert by_id["por-primeira"].name_zh == "葡超"
    assert by_id["bra-copa-do-brasil"].name_zh == "巴西杯"


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


def test_sync_entities_idempotent_and_lands_on_empty_store(tmp_path):
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    first = sync_entities(store)
    second = sync_entities(store)
    assert first["added"] > 0 and first["updated"] == 0
    assert second["added"] == 0 and second["updated"] == 0    # 幂等:第二次全 unchanged
    assert second["unchanged"] == first["added"]
    assert store.get(League, "swe-allsvenskan") is not None


def test_sync_entities_adds_new_league_to_non_empty_store(tmp_path):
    """回归 2026-08-05 缺口:非空 store 也必须能收新联赛(旧实现恒 no-op)。"""
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(League(league_id="zzz-preexisting", name_zh="占位"))
    stats = sync_entities(store)
    assert stats["added"] > 0
    assert store.get(League, "swe-allsvenskan") is not None
    assert store.get(League, "zzz-preexisting") is not None   # 现场实体不被种子清掉


def test_sync_entities_merges_notes_without_losing_either_side(tmp_path):
    """store 现场追加的笔记与种子笔记双向保留;同 key 取 at 更新的。"""
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(League(
        league_id="swe-allsvenskan", name_zh="瑞超",
        profile_notes=[
            {"key": "field_note", "note": "现场追加", "evidence": "settlements",
             "at": "2026-08-01"},
            {"key": "home_away_split", "note": "更新版", "evidence": "x", "at": "2099-01-01"},
        ],
    ))
    sync_entities(store)
    notes = {n["key"]: n for n in store.get(League, "swe-allsvenskan").profile_notes}
    assert notes["field_note"]["note"] == "现场追加"          # 种子没有 → 保留
    assert notes["home_away_split"]["note"] == "更新版"       # at 更新 → 现场版胜出
    assert "xg_divergence" in notes                          # 种子独有 → 带进来


def test_export_entities_to_seed_reconciles_drift(tmp_path):
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"_comment": "x", "leagues": [], "teams": []}), encoding="utf-8")
    store = DecisionStore(tmp_path / "store")
    store.upsert(League(
        league_id="only-in-store", name_zh="只在库里",
        profile_notes=[{"key": "k", "note": "n", "evidence": "e", "at": "2026-08-05"}]))
    written = export_entities_to_seed(store, seed)
    data = json.loads(seed.read_text(encoding="utf-8"))
    assert written["leagues"] == 1
    assert data["leagues"][0]["league_id"] == "only-in-store"
    assert data["_comment"] == "x"                            # 注释键不被冲掉


def test_add_profile_note_requires_evidence_and_existing_entity(tmp_path):
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(League(league_id="ned-eredivisie", name_zh="荷甲"))
    with pytest.raises(ValueError, match="evidence"):
        add_profile_note(store, league_id="ned-eredivisie", key="k", note="n",
                         evidence="  ", at="2026-08-05")
    with pytest.raises(ValueError, match="不在 store"):
        add_profile_note(store, league_id="unknown-league", key="k", note="n",
                         evidence="https://x", at="2026-08-05")
    add_profile_note(store, league_id="ned-eredivisie", key="k", note="n",
                     evidence="https://x", at="2026-08-05")
    assert store.get(League, "ned-eredivisie").profile_notes[0]["key"] == "k"


def test_merge_profile_notes_prefers_later_at():
    merged = merge_profile_notes(
        [{"key": "a", "note": "旧", "at": "2026-01-01"}],
        [{"key": "a", "note": "新", "at": "2026-08-05"}, {"key": "b", "note": "新增"}],
    )
    assert [n["key"] for n in merged] == ["a", "b"]
    assert merged[0]["note"] == "新"


def test_profiles_for_board_returns_notes_and_flags_unresolved_league(tmp_path):
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    sync_entities(store)
    payload = profiles_for_board(store, ["瑞超", "火星联赛"], ["哈马比", "无名队"])
    assert [lg["league_id"] for lg in payload["leagues"]] == ["swe-allsvenskan"]
    assert payload["leagues"][0]["profile_notes"]
    assert payload["unresolved_leagues"] == ["火星联赛"]
    assert [t["team_id"] for t in payload["teams"]] == ["swe-hammarby"]
