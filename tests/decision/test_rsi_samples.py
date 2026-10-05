"""样本账：前瞻样本首次入选即冻结，语料重建只能加样本（2026-10-05）。"""
import json

import pytest
from typer.testing import CliRunner

from nutmeg.decision import rsi_samples
from nutmeg.decision.rsi_grading import grade_f5_prospective, grade_f9_prospective
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import rsi as rsi_cli

BAND = {"home": 0.45, "draw": 0.3, "away": 0.25}  # gap12 = 15pp → F5 带内
WIDE = {"home": 0.65, "draw": 0.2, "away": 0.15}  # gap12 = 45pp → 带外
WINDOW = {"date_from": "2026-09-19"}
AT = "2026-10-06T10:45:00+08:00"


def _row(key, actual="3", fair=BAND, *, src="jczq", titan=None, date="2026-09-24", **extra):
    return {"key": key, "src": src, "date": date, "actual": actual, "fair": fair,
            "belief": extra.pop("belief", fair), "belief_moved": extra.pop("moved", False),
            "titan007_id": titan, **extra}


def _grade(ledger, rows, adapter=grade_f5_prospective, exp="F5", window=WINDOW):
    return rsi_samples.grade(ledger, exp, rows, adapter, window=window, at=AT)


def test_first_selection_is_frozen_and_survives_a_lane_swap():
    ledger = rsi_samples.empty()
    g, events = _grade(ledger, [_row("2026-09-24-周四003", titan="1"), _row("j2", fair=WIDE)])
    assert g.n_cum == 1 and [e["kind"] for e in events] == ["admitted"]

    # 足彩期结算：竞彩行被足彩孪生行替换，价格掉出带——已结账的样本不许跟着走
    twin = _row("26132-1", fair=WIDE, src="zucai", titan="1",
                twin_keys=["2026-09-24-周四003"])
    g2, events2 = _grade(ledger, [twin])
    assert g2.n_cum == 1
    assert [(e["kind"], e["detail"]) for e in events2] == [
        ("superseded", {"current_key": "26132-1"})]
    assert _grade(ledger, [twin])[1] == []  # 同一漂移只记一次


def test_twin_found_by_absorbed_key_when_titan_id_is_missing():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("2026-09-19-周六030", titan="9")])
    twin = _row("26129-8", src="zucai", twin_keys=["2026-09-19-周六030"])
    g, events = _grade(ledger, [twin])
    assert g.n_cum == 1 and [e["kind"] for e in events] == ["superseded"]


def test_missing_member_still_counts_and_is_logged():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", titan="1"), _row("b", titan="2")])
    g, events = _grade(ledger, [_row("a", titan="1")])
    assert g.n_cum == 2 and [(e["kind"], e["key"]) for e in events] == [("missing", "b")]


def test_rewritten_values_keep_the_frozen_row_but_bookkeeping_is_not_drift():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", titan="1")])
    g, events = _grade(ledger, [_row("a", titan="1", twin_keys=["x"])])
    assert events == [] and g.n_cum == 1
    g, events = _grade(ledger, [_row("a", fair=WIDE, belief=BAND, titan="1")])
    assert g.n_cum == 1  # 冻结值仍在带内
    assert events[0]["kind"] == "changed" and events[0]["detail"]["fields"] == ["fair"]


def test_same_key_result_correction_is_applied_and_logged():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", actual="3", titan="1")])
    g, events = _grade(ledger, [_row("a", actual="1", titan="1")])
    assert [e["kind"] for e in events] == ["actual_corrected"]
    assert events[0]["detail"] == {"from": "3", "to": "1"}
    assert round(g.metric_value_pp, 1) == round((0.0 - 0.45) * 100, 1)


def test_duplicate_match_in_corpus_counts_once():
    ledger = rsi_samples.empty()
    rows = [_row("2026-09-19-周日001", titan="7", date="2026-09-19"),
            _row("2026-09-20-周日001", titan="7", date="2026-09-20")]
    g, events = _grade(ledger, rows)
    assert g.n_cum == 1
    assert sorted(e["kind"] for e in events) == ["admitted", "duplicate_in_corpus"]


def test_member_the_adapter_no_longer_selects_is_logged_as_deselected():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", titan="1")])
    g, events = _grade(ledger, [_row("a", titan="1")], window={"date_from": "2026-10-01"})
    assert g.n_cum == 0 and [e["kind"] for e in events] == ["deselected"]


def test_retract_removes_a_member_for_good_with_a_trace():
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", titan="1"), _row("b", titan="2")])
    gone = rsi_samples.retract(ledger, "F5", "a", reason="赛果源错误", by="Jun", at=AT)
    assert gone["reason"] == "赛果源错误"
    g, _ = _grade(ledger, [_row("a", titan="1"), _row("b", titan="2")])
    assert g.n_cum == 1
    assert [e["kind"] for e in ledger["events"]].count("retracted") == 1
    with pytest.raises(KeyError):
        rsi_samples.retract(ledger, "F5", "zzz", reason="r", by="Jun", at=AT)


def test_f9_frozen_belief_is_not_replaced_by_the_twin_without_a_move():
    moved = {"home": 0.40, "draw": 0.35, "away": 0.25}
    ledger = rsi_samples.empty()
    jc = _row("2026-09-24-周四004", titan="3", belief=moved, moved=True)
    g, _ = _grade(ledger, [jc], adapter=grade_f9_prospective, exp="F9")
    twin = _row("26132-7", src="zucai", titan="3")
    g2, events = _grade(ledger, [twin], adapter=grade_f9_prospective, exp="F9")
    assert g.n_cum == g2.n_cum == 1 and g2.metric_value_pp == g.metric_value_pp
    assert [e["kind"] for e in events] == ["superseded"]


def test_ledger_round_trips_and_prunes_unused_rows(tmp_path):
    ledger = rsi_samples.empty()
    _grade(ledger, [_row("a", titan="1")])
    rsi_samples.retract(ledger, "F5", "a", reason="r", by="Jun", at=AT)
    path = tmp_path / "samples.json"
    rsi_samples.save(path, ledger)
    back = rsi_samples.load(path)
    assert back["experiments"]["F5"]["retracted"]["t:1"]["key"] == "a"
    assert len(back["rows"]) == 1
    assert rsi_samples.load(tmp_path / "none.json") == rsi_samples.empty()


F5_DOC = {
    "exp_id": "F5", "claim": "c", "mechanism": "m", "tier": "candidate", "layer": "structural",
    "population": "both", "min_tier": "price_only",
    "window": {"date_from": "2026-09-19", "n_min": 120},
    "falsifier": {"metric": "top1_resid_pp_gap12_10_20", "stratum": "pooled", "n_min": 120,
                  "bound": "ci_lower", "threshold_pp": -2.0, "direction": "gt_means_falsified"},
    "stop_rule": "n≥120", "quota_slot": False, "buckets": ["[10,20)"], "rule_ids": [],
    "source_doc": "experiments/prereg-26129-F5-price-bands.json", "registered_at": "2026-09-18",
    "duties": [],
}


def test_cli_grade_freezes_samples_and_samples_command_reports_and_retracts(tmp_path,
                                                                            monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    doc = tmp_path / "F5.json"
    doc.write_text(json.dumps(F5_DOC), encoding="utf-8")
    runner = CliRunner()
    registered = runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(data_dir)])
    assert registered.exit_code == 0, registered.output
    corpus, ledger = tmp_path / "corpus.json", tmp_path / "samples.json"
    monkeypatch.setattr(rsi_cli, "_CORPUS_V2", corpus)
    grade = ["rsi", "grade", "--exp", "F5", "--data-dir", str(data_dir),
             "--samples", str(ledger)]

    corpus.write_text(json.dumps({"rows": [_row("2026-09-24-周四003", titan="1"),
                                           _row("2026-09-24-周四005", titan="2")]}), "utf-8")
    first = runner.invoke(app, grade)
    assert first.exit_code == 0, first.output
    assert "admitted 2" in first.output and "n=2" in first.output

    corpus.write_text(json.dumps({"rows": [
        _row("26132-1", fair=WIDE, src="zucai", titan="1", twin_keys=["2026-09-24-周四003"]),
        _row("2026-09-24-周四005", titan="2")]}), "utf-8")
    second = runner.invoke(app, grade)
    assert second.exit_code == 0, second.output
    assert "n=2" in second.output and "superseded 1" in second.output

    shown = runner.invoke(app, ["rsi", "samples", "--exp", "F5", "--samples", str(ledger)])
    assert "成员 2" in shown.output and "superseded" in shown.output
    refused = runner.invoke(app, ["rsi", "samples", "--exp", "F5", "--retract", "26132-1",
                                  "--samples", str(ledger)])
    assert refused.exit_code == 1
    retracted = runner.invoke(app, ["rsi", "samples", "--exp", "F5", "--retract",
                                    "2026-09-24-周四003", "--reason", "测试", "--by", "Jun",
                                    "--samples", str(ledger)])
    assert retracted.exit_code == 0, retracted.output
    third = runner.invoke(app, grade)
    assert "n=1" in third.output
