# tests/decision/test_store.py
from nutmeg.decision.ontology import Match, Read
from nutmeg.decision.store import DecisionStore


def test_upsert_is_idempotent_by_id(tmp_path):
    store = DecisionStore(tmp_path)
    m = Match(match_id="M-1", kickoff_at="t", home="A", away="B")
    store.upsert(m)
    store.upsert(m)                    # 重复 upsert 同 id
    assert len(store.load(Match)) == 1


def test_upsert_replaces_same_id(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Match(match_id="M-1", kickoff_at="t1", home="A", away="B"))
    store.upsert(Match(match_id="M-1", kickoff_at="t2", home="A", away="B"))
    loaded = store.load(Match)
    assert len(loaded) == 1 and loaded[0].kickoff_at == "t2"


def test_load_returns_typed_objects_and_get(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Read(read_id="R-1", match_id="M-1", snapshot_id="S-1",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.5, "draw": 0.3, "away": 0.2}, shadow=True))
    got = store.get(Read, "R-1")
    assert got is not None and got.market == "had"
    assert store.get(Read, "R-nope") is None


def test_separate_file_per_type(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Match(match_id="M-1", kickoff_at="t", home="A", away="B"))
    assert (tmp_path / "matches.jsonl").exists()
    assert not (tmp_path / "reads.jsonl").exists()


def test_corrupt_line_skipped(tmp_path):
    store = DecisionStore(tmp_path)
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "matches.jsonl").write_text(
        '{bad\n{"match_id":"M-1","kickoff_at":"t","home":"A","away":"B"}\n'
    )
    assert len(store.load(Match)) == 1
