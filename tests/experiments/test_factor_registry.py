import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).parents[2] / "experiments" / "factor_registry.py"
_SPEC = importlib.util.spec_from_file_location("factor_registry", _PATH)
assert _SPEC and _SPEC.loader
factor_registry = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(factor_registry)


def test_registry_is_valid_and_covers_every_audit_code():
    registry = factor_registry.load_registry()
    assert factor_registry.validate(registry) == []
    assert all(f["current_weight_pp"] == 0.0 for f in registry["factors"])
    assert registry["weight_change_rule"]["n_min"] == 60


def test_validate_rejects_fact_with_weight_band_and_missing_owner():
    registry = factor_registry.load_registry()
    broken = json.loads(json.dumps(registry))
    broken["factors"][0]["weight_band"] = [-5.0, 5.0]  # c7 is fact
    broken["expression_rules"] = []
    problems = factor_registry.validate(broken)
    assert any("weight_band" in p for p in problems)
    assert any("without an owner" in p for p in problems)


def _rows(n, *, factor_on, hit_rate_on, hit_rate_off, fair=0.5):
    rows = []
    for i in range(n):
        on = i % 2 == 0 if factor_on is None else factor_on
        rate = hit_rate_on if on else hit_rate_off
        rows.append(
            {
                "date": f"2026-09-{(i % 28) + 1:02d}",
                "actual": "3" if (i * 7919) % 100 < rate * 100 else "0",
                "fair": {"home": fair, "draw": 0.3, "away": 0.2},
                "labels": {"anchor_integrity": "pass" if on else "fail"},
                "provably_prospective": True,
            }
        )
    return rows


def test_propose_zero_path_is_reachable_and_never_writes(tmp_path):
    registry = factor_registry.load_registry()
    rows = _rows(120, factor_on=None, hit_rate_on=0.5, hit_rate_off=0.5)
    before = factor_registry.REGISTRY.read_bytes()
    result = factor_registry.propose(registry, "anchor_integrity", rows, n_perm=50)
    assert factor_registry.REGISTRY.read_bytes() == before
    assert result["writes_weights"] is False
    assert result["strict"]["n"] == 120
    assert result["decision"] == "propose_zero"
    assert result["proposed_weight_pp"] == 0.0


def test_hold_when_n_below_minimum_and_record_only_for_fact():
    registry = factor_registry.load_registry()
    small = _rows(20, factor_on=None, hit_rate_on=0.9, hit_rate_off=0.1)
    held = factor_registry.propose(registry, "anchor_integrity", small, n_perm=50)
    assert held["decision"] == "hold" and "n_min" in held["reason"]
    fact = factor_registry.propose(registry, "modal_face_dropped", small, n_perm=50)
    assert fact["decision"] == "record_only"



def test_propose_runs_rubric_item_factors_through_their_own_row_builder():
    """闭环 `rsi weights propose --all` 会对每个 probability 因子调 analyze；
    rubric 逐项因子的行构造器在 experiments.rubric_rows（2026-10-02 曾 KeyError）。"""
    registry = factor_registry.load_registry()
    ids = [f["factor_id"] for f in registry["factors"] if f["factor_id"].startswith("rubric_")]
    assert len(ids) == 11
    rows = [{"key": f"k{i}", "actual": "0" if i % 2 else "3",
             "fair": {"home": .5, "draw": .3, "away": .2}, "provably_prospective": True,
             "labels": {"rubric_version": "r1",
                        "rubric": {"F_absence_home": {"answer": "yes" if i % 3 else "no",
                                                      "p": .9 if i % 3 else .1}}}}
            for i in range(30)]
    before = factor_registry.REGISTRY.read_bytes()
    for fid in ids:
        result = factor_registry.propose(registry, fid, rows, n_perm=20)
        assert result["writes_weights"] is False and result["decision"] in ("hold", "propose_zero",
                                                                           "propose_change")
    assert factor_registry.REGISTRY.read_bytes() == before
    hit = factor_registry.propose(registry, "rubric_F_absence_home", rows, n_perm=20)
    assert hit["strict"]["n"] == 30 and hit["decision"] == "hold"        # n < 60 → hold
