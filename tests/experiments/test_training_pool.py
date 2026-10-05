from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "experiments" / "training_pool.py"
_SPEC = importlib.util.spec_from_file_location("training_pool", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
training_pool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(training_pool)


def test_power_follows_the_verdict_rule_and_is_mostly_inconclusive_when_underpowered():
    reading = {"n": 400, "value_pp": 5.5, "ci": [1.2, 9.7]}
    w = training_pool.power(reading, {"n_min": 150, "threshold_pp": 0.0,
                                      "direction": "lt_means_falsified"})
    assert w["p_falsified"] < 0.01
    assert 0.3 < w["p_survived"] < 0.4 and w["p_inconclusive"] > 0.6
    assert 400 < w["n_decisive_80"] < 600
    # gt_means_falsified mirrors the sides: an effect far below the threshold survives
    mirrored = training_pool.power({"n": 300, "value_pp": -12.0, "ci": [-17.0, -7.0]},
                                   {"n_min": 120, "threshold_pp": -2.0,
                                    "direction": "gt_means_falsified"})
    assert mirrored["p_survived"] > 0.5 and mirrored["p_falsified"] < 0.01
    assert training_pool.power({"n": 3, "value_pp": 1.0, "ci": [0.0, 2.0]},
                               {"n_min": 10, "threshold_pp": 0.0,
                                "direction": "lt_means_falsified"}) is None


def test_call_proxy_turns_pre_stance_zucai_calls_into_unproven_stance_labels():
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    rows = [
        {"key": "26120-1", "src": "zucai", "date": "2026-09-01", "call": "31", "fair": fair,
         "actual": "1", "labels": {"anchor_side": "home"}, "provably_prospective": True},
        {"key": "26120-2", "src": "zucai", "date": "2026-09-01", "call": "310", "fair": fair,
         "actual": "3"},
        {"key": "26120-3", "src": "zucai", "date": "2026-09-01", "call": "跟市场", "fair": fair,
         "actual": "3"},
        {"key": "26130-1", "src": "zucai", "date": "2026-09-24", "call": "3", "fair": fair,
         "actual": "3"},
        {"key": "j", "src": "jczq", "date": "2026-09-01", "call": "3", "fair": fair, "actual": "3"},
    ]
    proxy = training_pool.call_proxy_rows(rows, before="2026-09-23")
    assert [r["key"] for r in proxy] == ["26120-1"]
    labels = proxy[0]["labels"]
    assert (labels["stance_structure"], labels["stance_face"], labels["stance_cover"]) == (
        "double", "3", "1")
    assert labels["anchor_side"] == "home" and proxy[0]["provably_prospective"] is None
