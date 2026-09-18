import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

DOC = {
    "exp_id": "F2", "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record",
                               "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json"}],
}


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "zucai").mkdir(parents=True)
    (d / "zucai" / "26129-issue.json").write_text(json.dumps({"issue_id": "26129", "matches": [
        {"match_no": 4, "kickoff_bj": "2026-09-19T00:30:00"},
        {"match_no": 1, "kickoff_bj": "2026-09-19T03:00:00"}]}), encoding="utf-8")
    return d


def test_register_schedule_due_status_round_trip(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    assert "F2" in r.output and "frozen" in r.output
    r = CliRunner().invoke(app, ["rsi", "schedule", "--day", "2026-09-19", "--issue", "26129",
                                 "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(app, ["rsi", "due", "--day", "2026-09-19", "--data-dir", str(d),
                                 "--now", "2026-09-18T20:00:00+08:00"])
    assert "f2-observation" in r.output and "00:30" in r.output
    assert "scripts/zucai_f2_observe.py record --issue 26129" in r.output   # 占位已填
    r = CliRunner().invoke(app, ["rsi", "status", "--data-dir", str(d)])
    assert r.exit_code == 0 and "F2" in r.output and "registered" in r.output


def test_verdict_before_n_min_exits_nonzero_with_the_shortfall(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "verdict", "--exp", "F2", "--data-dir", str(d)])
    assert r.exit_code == 1 and "prospective" in r.output


def test_register_twice_is_refused(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 1 and "已登记" in r.output
