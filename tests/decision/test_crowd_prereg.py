import json

import pytest

from nutmeg.decision.rsi_prereg import load_registry_doc

CR = {
    "exp_id": "CR1", "claim": "c", "mechanism": "m", "tier": "deploy_eligible",
    "layer": "structural",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26136", "issue_to": "26999"},
    "replay_window": {"issue_from": "26035", "issue_to": "26089"},
    "falsifier": {"metric": "crowd_prize_pct_per_face", "stratum": "zucai", "n_min": 30,
                  "bound": "ci_lower", "threshold_pp": 0.0, "direction": "lt_means_falsified"},
    "stop_rule": "s", "quota_slot": False, "buckets": [], "rule_ids": [],
    "source_doc": "docs/superpowers/specs/2026-10-07-zucai-crowd-notebook-design.md",
    "registered_at": "2026-10-07", "label_cn": "全国人群多买平局",
    "trigger": {"field": "face", "op": "==", "v": "1"}, "crowd_bias": "over",
}


def _load(tmp_path, doc):
    p = tmp_path / "CR1.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return load_registry_doc(p)


def test_valid_cr_doc_loads(tmp_path):
    assert _load(tmp_path, CR)["crowd_bias"] == "over"


@pytest.mark.parametrize("patch, msg", [
    ({"crowd_bias": "maybe"}, "crowd_bias"),
    ({"trigger": {"field": "gap", "op": ">=", "v": 1}}, "未知字段"),
    ({"layer": "judgment", "tier": "observation"}, "structural"),
    ({"replay_window": {"issue_from": "26035"}}, "replay_window"),
])
def test_invalid_cr_doc_is_refused(tmp_path, patch, msg):
    with pytest.raises(ValueError, match=msg):
        _load(tmp_path, dict(CR, **patch))


def test_missing_cr_field_is_refused(tmp_path):
    doc = dict(CR)
    doc.pop("trigger")
    with pytest.raises(ValueError, match="trigger"):
        _load(tmp_path, doc)
