# tests/decision/test_store.py
from nutmeg.decision.ontology import League, Team
from nutmeg.decision.store import DecisionStore


def test_upsert_is_idempotent_by_id(tmp_path):
    store = DecisionStore(tmp_path)
    t = Team(team_id="T-1", name_zh="甲")
    store.upsert(t)
    store.upsert(t)                    # 重复 upsert 同 id
    assert len(store.load(Team)) == 1


def test_upsert_replaces_same_id(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Team(team_id="T-1", name_zh="旧名"))
    store.upsert(Team(team_id="T-1", name_zh="新名"))
    loaded = store.load(Team)
    assert len(loaded) == 1 and loaded[0].name_zh == "新名"


def test_load_returns_typed_objects_and_get(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(League(league_id="L-1", name_zh="瑞超", season="2026"))
    got = store.get(League, "L-1")
    assert got is not None and got.season == "2026"
    assert store.get(League, "L-nope") is None


def test_separate_file_per_type(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Team(team_id="T-1"))
    assert (tmp_path / "teams.jsonl").exists()
    assert not (tmp_path / "leagues.jsonl").exists()


def test_corrupt_line_skipped(tmp_path):
    store = DecisionStore(tmp_path)
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "teams.jsonl").write_text(
        '{bad\n{"team_id":"T-1","name_zh":"甲"}\n'
    )
    assert len(store.load(Team)) == 1


def test_team_league_objects_roundtrip_via_store(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Team(
        team_id="swe-hammarby", name_zh="哈马比", name_en="Hammarby",
        aliases=["Hammarby IF"], competition_ids=["swe-allsvenskan"],
        profile_notes=[{"key": "home_fortress", "note": "主场20-5",
                        "evidence": "memory allsvenskan-2026-league-profile",
                        "at": "2026-07-07"}]))
    store.upsert(League(league_id="swe-allsvenskan", name_zh="瑞超",
                        name_en="Allsvenskan", country="Sweden", season="2026"))
    t = store.get(Team, "swe-hammarby")
    assert t.profile_notes[0]["key"] == "home_fortress"
    assert store.get(League, "swe-allsvenskan").name_zh == "瑞超"
    assert (tmp_path / "teams.jsonl").exists()
    assert (tmp_path / "leagues.jsonl").exists()
