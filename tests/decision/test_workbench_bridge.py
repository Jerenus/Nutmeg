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


def test_bridge_attaches_ttg_axis_to_had_judgment(tmp_path):
    """同场 ttg 进球轴 Read 挂进 had judgment 的 payload.ttg（约束 h 判读可见）。"""
    store = DecisionStore(tmp_path / "decision")
    date = "2026-07-08"
    mid = f"M-{date}-a-b"
    store.upsert(Match(match_id=mid, kickoff_at="t", home="瑞士", away="哥伦比亚"))
    store.upsert(Read(read_id="Rh", match_id=mid, snapshot_id="S", made_at="t",
                      judge="claude", market="had",
                      prior={"home": 0.27, "draw": 0.31, "away": 0.42},
                      belief={"home": 0.27, "draw": 0.31, "away": 0.42}))
    store.upsert(Read(read_id="Rt", match_id=mid, snapshot_id="S", made_at="t",
                      judge="claude", market="ttg", confidence=3,
                      prior={"total_2": 0.26, "total_1": 0.19},
                      belief={"total_2": 0.26, "total_1": 0.19},
                      note="进球轴:模态2球"))
    bridge_day(store, tmp_path, date)
    jud = next(e for e in read_events(tmp_path, date) if e["kind"] == "judgment")
    assert "ttg" in jud["payload"]
    assert jud["payload"]["ttg"]["belief"]["total_2"] == 0.26
    assert "进球轴" in jud["payload"]["ttg"]["note"]


def test_bridge_emits_day_regime_event(tmp_path):
    """day-regime.json → 单个 day_regime 事件（日级盘面,舞台默认态）。"""
    import json
    date = "2026-07-08"
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Match(match_id=f"M-{date}-a-b", kickoff_at="t", home="A", away="B"))
    store.upsert(Read(read_id="R", match_id=f"M-{date}-a-b", snapshot_id="S",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.5, "draw": 0.3, "away": 0.2}))
    daily = tmp_path / "daily" / date
    daily.mkdir(parents=True)
    (daily / "day-regime.json").write_text(json.dumps(
        {"n_matches": 5, "n_heavy_fav": 3, "n_tossup": 2,
         "mean_expected_goals": 2.82, "note": "只攒样本不进决策"}), encoding="utf-8")
    bridge_day(store, tmp_path, date)
    evs = read_events(tmp_path, date)
    reg = [e for e in evs if e["kind"] == "day_regime"]
    assert len(reg) == 1 and reg[0]["payload"]["n_heavy_fav"] == 3
    # 幂等:再跑不重复
    bridge_day(store, tmp_path, date)
    assert len([e for e in read_events(tmp_path, date) if e["kind"] == "day_regime"]) == 1
