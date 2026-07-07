"""day_regime — 日级盘面热度诊断(2026-07-07 用户定:确定性算术攒样本,不进决策)。"""
import json

from nutmeg.decision.day_regime import compute_day_regime
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.verbs import run_day_regime

_M1 = "M-2026-07-08-强队-弱队"
_M2 = "M-2026-07-08-均势A-均势B"

_TTG_PROBS = (0.07, 0.18, 0.24, 0.22, 0.14, 0.08, 0.04, 0.03)
_TTG = {f"total_{k}": p for k, p in enumerate(_TTG_PROBS)}


def _seed(store):
    # M1:欧赔+体彩双源(有 gap 可算),重热门 0.70
    store.upsert(MarketSnapshot(
        snapshot_id="S-1e", match_id=_M1, taken_at="t1", kind="read_time",
        source="apifootball",
        fair={"had": {"home": 0.70, "draw": 0.20, "away": 0.10}}))
    store.upsert(MarketSnapshot(
        snapshot_id="S-1s", match_id=_M1, taken_at="t1", kind="read_time",
        source="sporttery",
        fair={"had": {"home": 0.75, "draw": 0.16, "away": 0.09},
              "ttg": dict(_TTG)}))
    # M2:仅体彩,真均势 0.40
    store.upsert(MarketSnapshot(
        snapshot_id="S-2s", match_id=_M2, taken_at="t1", kind="read_time",
        source="sporttery",
        fair={"had": {"home": 0.40, "draw": 0.29, "away": 0.31},
              "ttg": dict(_TTG)}))
    # 非当日快照不入统计
    store.upsert(MarketSnapshot(
        snapshot_id="S-x", match_id="M-2026-07-09-别日-场次", taken_at="t1",
        kind="read_time", source="sporttery",
        fair={"had": {"home": 0.5, "draw": 0.3, "away": 0.2}}))


def test_compute_day_regime_metrics(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store)
    r = compute_day_regime(store, run_date="2026-07-08")
    assert r["n_matches"] == 2
    assert r["n_heavy_fav"] == 1                     # M1 fav 0.70(锚优先欧赔)
    assert r["n_tossup"] == 1                        # M2 fav 0.40 < 0.45
    assert abs(r["mean_fav_prob"] - (0.70 + 0.40) / 2) < 1e-9
    m1 = next(m for m in r["matches"] if m["match_id"] == _M1)
    assert abs(m1["gap"] - 0.05) < 1e-9              # |0.75−0.70| 分量最大差
    assert m1["fav_side"] == "home"
    # 期望总进球 Σ k·p(体彩 ttg 去水)
    xg = sum(k * p for k, p in enumerate(_TTG_PROBS))
    assert abs(m1["expected_goals"] - xg) < 1e-6
    m2 = next(m for m in r["matches"] if m["match_id"] == _M2)
    assert m2["gap"] is None                         # 单源无 gap,不伪造


def test_run_day_regime_writes_daily_json(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    _seed(store)
    msg = run_day_regime("2026-07-08", tmp_path)
    out = tmp_path / "daily" / "2026-07-08" / "day-regime.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n_matches"] == 2 and "不进决策" in data["note"]
    assert "day-regime" in msg


def test_compute_day_regime_empty_day(tmp_path):
    store = DecisionStore(tmp_path)
    r = compute_day_regime(store, run_date="2026-07-08")
    assert r["n_matches"] == 0 and r["matches"] == []


def test_decision_day_regime_cli(tmp_path):
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    _seed(DecisionStore(tmp_path / "decision"))
    result = CliRunner().invoke(app, ["decision-day-regime", "--run-date", "2026-07-08",
                                      "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "2 场" in result.output
    assert (tmp_path / "daily" / "2026-07-08" / "day-regime.json").exists()
