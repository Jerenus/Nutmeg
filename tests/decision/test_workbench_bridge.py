# tests/decision/test_workbench_bridge.py
from nutmeg.decision.ontology import Match, Read
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import read_events
from nutmeg.decision.workbench_bridge import bridge_day


def _seed(tmp_path, date="2026-07-08"):
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Match(match_id=f"M-{date}-a-b", kickoff_at="t", home="哈马比",
                       away="卡尔马", competition="瑞超"))
    store.upsert(Read(
        read_id="R1", match_id=f"M-{date}-a-b", snapshot_id="S1", made_at="t",
        judge="claude", market="had",
        prior={"home": 0.52, "draw": 0.27, "away": 0.21},
        belief={"home": 0.46, "draw": 0.31, "away": 0.23},
        factors=[{"factor_id": "league_bias", "scope_key": "swe-allsvenskan",
                  "direction": "draw", "weight_pp": 6, "evidence": [{"url": "u"}]}],
        confidence=3, note="偏移判读"))
    return store, tmp_path, date


def test_bridge_projects_attention_and_judgment(tmp_path):
    store, out, date = _seed(tmp_path)
    n = bridge_day(store, out, date)
    assert n == 2
    evs = read_events(out, date)
    kinds = [e["kind"] for e in evs]
    assert "attention" in kinds and "judgment" in kinds
    att = next(e for e in evs if e["kind"] == "attention")
    assert att["group"] == "偏移读数" and "哈马比" in att["match"]
    assert att["id"] == f"M-{date}-a-b"
    jud = next(e for e in evs if e["kind"] == "judgment")
    assert jud["obj_id"] == f"M-{date}-a-b"
    assert jud["payload"]["belief"]["draw"] == 0.31
    assert jud["payload"]["committed"] is True


def test_bridge_follow_market_group(tmp_path):
    """无因子 → 跟市场组;shadow/ttg 不投影。"""
    store = DecisionStore(tmp_path / "decision")
    date = "2026-07-08"
    store.upsert(Match(match_id=f"M-{date}-c-d", kickoff_at="t", home="A", away="B"))
    store.upsert(Read(read_id="R2", match_id=f"M-{date}-c-d", snapshot_id="S",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.4, "draw": 0.3, "away": 0.3},
                      belief={"home": 0.4, "draw": 0.3, "away": 0.3}))
    # ttg + shadow 都不该投影
    store.upsert(Read(read_id="R3", match_id=f"M-{date}-c-d", snapshot_id="S",
                      made_at="t", judge="claude", market="ttg",
                      prior={"total_2": 1.0}, belief={"total_2": 1.0}))
    n = bridge_day(store, tmp_path, date)
    assert n == 2  # 只 R2 的 attention+judgment
    att = next(e for e in read_events(tmp_path, date) if e["kind"] == "attention")
    assert att["group"] == "跟市场"


def test_bridge_idempotent(tmp_path):
    store, out, date = _seed(tmp_path)
    assert bridge_day(store, out, date) == 2
    assert bridge_day(store, out, date) == 0  # 第二次不重复投影
    juds = [e for e in read_events(out, date) if e["kind"] == "judgment"]
    assert len(juds) == 1
