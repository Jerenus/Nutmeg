# tests/decision/test_rsi_prereg.py
import json
from copy import deepcopy
from pathlib import Path

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


_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "experiments" / "registry"


def test_all_registry_docs_load_and_keep_their_original_registration_dates():
    """（2026-10-08 由一次性迁移脚本 rsi_migrate_preregs 的测试移来：它钉的是现役注册表。）"""
    docs = {
        p.stem: load_registry_doc(p)
        for p in sorted(_REGISTRY.glob("*.json"))
        if not p.name.startswith("_draft_")
    }
    # 2026-10-02：K1（判断 rubric 两读 kappa）登记
    assert set(docs) == {"F1c", "F10", "F11", "F13", "F14", "F15", "F2", "F3", "F4", "F5", "F8",
                         "F9", "G1", "K1", "R0", "R1"}
    # F13/F14：2026-09-30 登记（崩塌叙事锚方 / 表态面集合命中率）
    assert docs["F13"]["registered_at"] == docs["F14"]["registered_at"] == "2026-09-30"
    # R1：并集样本池深研覆盖（Jun 2026-09-27），R0 冻结不动
    assert (docs["R1"]["registered_at"], docs["R1"]["population"]) == ("2026-09-27", "both")
    assert docs["F2"]["registered_at"] == "2026-09-14"
    assert docs["F1c"]["registered_at"] == "2026-09-14"
    assert docs["F4"]["registered_at"] == "2026-09-18"
    assert docs["F5"]["registered_at"] == "2026-09-18"
    assert docs["F8"]["registered_at"] == "2026-09-19"
    assert docs["F9"]["registered_at"] == "2026-09-19"
    # 在跑的窗口不重新索引（U9-②）
    assert docs["F2"]["window"] == {"issue_from": "26126", "issue_to": "26137"}
    assert docs["F1c"]["window"] == {"issue_from": "26129", "issue_to": "26140"}
    # 每份都指回旧文件
    for d in docs.values():
        # 原件冻结不改；source_doc 允许「文件 + 空格 + 片段」（F13/F14 指向 scoreboard 的键）
        assert (_ROOT / d["source_doc"].split(" ")[0]).exists(), d["source_doc"]
    # F1c/F2 各带一条按日义务；结构专项接线后 F4 由资金方案 commit 产观察。
    assert [x["name"] for x in docs["F2"]["duties"]] == ["f2-observation"]
    assert [x["name"] for x in docs["F1c"]["duties"]] == ["dispersion-observation"]
    assert docs["F4"]["tier"] == "observation"
    assert [(x["name"], x["scope"]) for x in docs["F4"]["duties"]] == [
        ("capital-plan", "day")
    ]
    assert [(x["name"], x["scope"], x["deadline_rule"]) for x in docs["F5"]["duties"]] == [
        ("price-band-observation", "match", "match_kickoff")
    ]
