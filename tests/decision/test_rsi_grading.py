import json

import pytest

from nutmeg.decision.rsi_grading import (
    GradeResult,
    LeakError,
    bootstrap_residual_pp,
    c14_line_harness,
    dream,
    grade_f2_prospective,
    grade_f4,
    inputs_hash,
)


def _ledger(tmp_path, *, captured="2026-09-15T19:30:05", issue="26126"):
    led = {"issues": {issue: {"prospective": True, "captured_at": captured, "graded_at": "x",
                              "rows": [
        {"no": "1", "bucket": "向主 ≥+0.5", "fair": {"home": 0.50, "draw": 0.26, "away": 0.24},
         "moved_share": 0.9, "actual": "home"},
        {"no": "2", "bucket": "向主 ≥+0.5", "fair": {"home": 0.55, "draw": 0.24, "away": 0.21},
         "moved_share": 1.0, "actual": "draw"},
        {"no": "3", "bucket": "不动 0", "fair": {"home": 0.40, "draw": 0.30, "away": 0.30},
         "moved_share": 0.1, "actual": "away"},
    ]}}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(led), encoding="utf-8")
    (tmp_path / f"{issue}-issue.json").write_text(json.dumps({"issue_id": issue, "matches": [
        {"match_no": 1, "kickoff_bj": "2026-09-16T02:00:00"},
        {"match_no": 2, "kickoff_bj": "2026-09-16T03:00:00"}]}), encoding="utf-8")
    return p


def test_bootstrap_residual_is_deterministic_and_brackets_the_point_estimate():
    rows = ([{"fair": {"home": 0.5}, "actual": "home"}] * 30
            + [{"fair": {"home": 0.5}, "actual": "draw"}] * 10)
    r = bootstrap_residual_pp(rows, face="home", seed=7)
    assert r.n == 40 and abs(r.value_pp - 25.0) < 1e-9          # 实开 75% − 期望 50%
    assert r.ci_low_pp <= r.value_pp <= r.ci_high_pp
    assert bootstrap_residual_pp(rows, face="home", seed=7) == r   # 同 seed 同结果


def test_f2_prospective_grade_uses_only_the_primary_bucket_and_hashes_inputs(tmp_path):
    led = _ledger(tmp_path)
    g = grade_f2_prospective(ledger_path=led, zucai_dir=tmp_path, primary_bucket="向主 ≥+0.5")
    assert isinstance(g, GradeResult) and g.n_cum == 2 and g.stratum == "zucai"
    assert g.inputs_hash == inputs_hash(led.read_bytes())
    assert g.as_of_policy == "earliest_kickoff"


def test_rows_captured_after_earliest_kickoff_are_refused_not_dropped(tmp_path):
    led = _ledger(tmp_path, captured="2026-09-16T02:30:00")   # 首场 02:00 已开
    with pytest.raises(LeakError, match="26126"):
        grade_f2_prospective(ledger_path=led, zucai_dir=tmp_path, primary_bucket="向主 ≥+0.5")


def test_dream_ranks_variants_and_reports_how_many_were_tried():
    corpus = [{"gap": g, "fair": {"home": 0.5}, "actual": "home" if g < 12 else "draw"}
              for g in range(0, 24)]

    def harness(rows, variant):
        lo, hi = variant["band"]
        sub = [r for r in rows if lo <= r["gap"] < hi]
        return bootstrap_residual_pp(sub, face="home", seed=1)

    table = dream(corpus, harness,
                  variants=[{"band": (0, 12)}, {"band": (12, 24)}, {"band": (5, 10)}])
    assert table["variants_tried"] == 3
    assert table["ranked"][0]["variant"] == {"band": (0, 12)}          # 最正残差排第一
    assert all("ci_low_pp" in r for r in table["ranked"])


def test_grade_f4_bootstraps_the_median_gate_cost_over_plans():
    plans = [
        {"issue": issue, "gate_cost_pp": gate}
        for issue, gate in (
            ("26129", 24.5),
            ("26130", 8.0),
            ("26131", 12.0),
            ("26132", None),
            ("26133", 6.0),
        )
    ]
    grade = grade_f4(plans)
    assert grade.n_cum == 4 and grade.stratum == "zucai"
    assert grade.as_of_policy == "per_issue_plan"
    assert grade.ci_low_pp <= grade.metric_value_pp <= grade.ci_high_pp
    assert 6.0 <= grade.metric_value_pp <= 24.5


def test_c14_line_harness_only_scores_excluded_faces_under_the_line():
    rows = [
        {"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "home"},
        {"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "away"},
        {"fair": {"home": 0.5, "draw": 0.3, "away": 0.20}, "actual": "home"},
    ]
    assert c14_line_harness(rows, {"line": 0.15}).n == 2
    assert c14_line_harness(rows, {"line": 0.25}).n == 3
