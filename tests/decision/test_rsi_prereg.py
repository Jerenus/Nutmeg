# tests/decision/test_rsi_prereg.py
import json
from copy import deepcopy

import pytest

from nutmeg.decision.rsi_prereg import load_registry_doc, render_instrument

GOOD = {
    "exp_id": "F2", "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["a"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record",
                               "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json"}],
}


def test_load_accepts_a_well_formed_doc(tmp_path):
    p = tmp_path / "F2.json"
    p.write_text(json.dumps(GOOD), encoding="utf-8")
    doc = load_registry_doc(p)
    assert doc["exp_id"] == "F2" and doc["duties"][0]["name"] == "f2-observation"


@pytest.mark.parametrize("bad,msg", [
    ({"falsifier": {**GOOD["falsifier"], "bound": "point"}}, "bound"),
    ({"window": {}}, "window"),
    ({"registered_at": "9/14"}, "registered_at"),
    ({"duties": [{"name": "x", "scope": "day", "deadline_rule": "whenever",
                  "instrument": [], "artifact_glob": "y"}]}, "deadline_rule"),
    ({"duties": [{"name": "x", "scope": "day", "deadline_rule": "earliest_kickoff",
                  "instrument": ["python", "x.py"], "artifact_glob": "y"}]}, "instrument"),
])
def test_load_rejects_malformed_docs(tmp_path, bad, msg):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({**GOOD, **bad}), encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        load_registry_doc(p)


def test_render_instrument_fills_placeholders():
    argv = render_instrument(["python", "x.py", "--issue", "{issue}", "--day", "{day}"],
                             issue="26129", day="2026-09-19")
    assert argv == ["python", "x.py", "--issue", "26129", "--day", "2026-09-19"]
    with pytest.raises(ValueError, match="issue"):
        render_instrument(["--issue", "{issue}"], issue=None, day="2026-09-19")


def test_pending_instrument_duty_allows_todo_without_placeholder(tmp_path):
    doc = deepcopy(GOOD)
    doc["duties"][0] = {
        **doc["duties"][0],
        "status": "pending_instrument",
        "instrument": ["TODO"],
    }
    path = tmp_path / "pending.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    loaded = load_registry_doc(path)

    assert loaded["duties"][0]["status"] == "pending_instrument"


def test_unknown_duty_status_is_rejected(tmp_path):
    doc = deepcopy(GOOD)
    doc["duties"][0]["status"] = "blocked"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError, match="duty.status"):
        load_registry_doc(path)
