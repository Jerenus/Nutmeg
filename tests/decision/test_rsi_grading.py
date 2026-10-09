import json

import pytest

from nutmeg.decision.rsi_grading import (
    GradeResult,
    LeakError,
    bootstrap_residual_pp,
    grade_f2_prospective,
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


def _row(date, fair, actual, structure=None):
    labels = {"stance_structure": structure} if structure else {}
    return {"src": "jczq", "date": date, "fair": fair, "actual": actual, "labels": labels}


def test_f10_grades_the_modal_face_of_60_to_80_favourites_inside_the_window():
    from nutmeg.decision.rsi_grading import grade_f10_prospective

    fav = {"home": 0.70, "draw": 0.20, "away": 0.10}
    rows = [_row("2026-09-27", fav, "3"), _row("2026-09-27", fav, "1"),
            _row("2026-09-26", fav, "3"),                                  # 窗外
            _row("2026-09-27", {"home": 0.5, "draw": 0.3, "away": 0.2}, "3")]  # 档外
    g = grade_f10_prospective(rows, window={"date_from": "2026-09-27"})
    assert g.n_cum == 2 and round(g.metric_value_pp, 6) == round((0.5 - 0.70) * 100, 6)


def test_f11_compares_favourite_crash_residual_by_research_insurance_call():
    from nutmeg.decision.rsi_grading import grade_f11_prospective

    fav = {"home": 0.60, "draw": 0.25, "away": 0.15}
    rows = [_row("2026-09-27", fav, "1", "double"), _row("2026-09-27", fav, "0", "double"),
            _row("2026-09-27", fav, "3", "single"), _row("2026-09-27", fav, "3", "single")]
    g = grade_f11_prospective(rows, window={"date_from": "2026-09-27"})
    # 翻车残差：保险组 (1−0.40) 均值 0.60，单选组 (0−0.40) 均值 −0.40 → 差 100pp
    assert g.n_cum == 4 and round(g.metric_value_pp, 6) == 100.0


def test_f13_selects_failed_anchors_with_a_collapse_narrative_tilted_against():
    from nutmeg.decision.rsi_grading import grade_f13_prospective

    fair = {"home": 0.60, "draw": 0.25, "away": 0.15}

    def row(actual, *, integrity="fail", flags=("dressing_room_turmoil",), belief_home=0.56,
            date="2026-10-02"):
        return {"src": "jczq", "date": date, "fair": fair, "actual": actual,
                "belief": {"home": belief_home, "draw": 0.25 + (0.60 - belief_home),
                           "away": 0.15},
                "labels": {"anchor_side": "home", "anchor_integrity": integrity,
                           "nondirectional_flags": list(flags), "crash_markers": []}}

    rows = [row("3"), row("0"),
            row("3", integrity="pass"),        # 完整度 PASS：没有崩塌叙事
            row("3", flags=()),                # 无旗无标记
            row("3", belief_home=0.60),        # 没拨离锚方
            row("3", date="2026-09-30")]       # 窗外
    g = grade_f13_prospective(rows, window={"date_from": "2026-10-01"})
    assert g.n_cum == 2 and round(g.metric_value_pp, 6) == round((0.5 - 0.60) * 100, 6)


def test_f14_scores_stance_face_sets_against_their_market_coverage():
    from nutmeg.decision.rsi_grading import grade_f14_prospective

    fair = {"home": 0.50, "draw": 0.30, "away": 0.20}

    def row(actual, structure, face="3", cover="1", date="2026-10-02"):
        return {"src": "jczq", "date": date, "fair": fair, "actual": actual,
                "labels": {"stance_structure": structure, "stance_face": face,
                           "stance_cover": cover}}

    rows = [row("3", "double"),                 # 31 命中，覆盖 0.80 → +0.20
            row("0", "double"),                 # 31 未中 → −0.80
            row("3", "single"),                 # 3 命中，覆盖 0.50 → +0.50
            row("3", "full"),                   # 全包不算选择
            row("3", "double", date="2026-09-30")]  # 窗外
    g = grade_f14_prospective(rows, window={"date_from": "2026-10-01"})
    assert g.n_cum == 3 and round(g.metric_value_pp, 6) == round((0.20 - 0.80 + 0.50) / 3 * 100, 6)


def _load_row(key, diff, actual, *, captured="2026-10-10T12:30:00+08:00",
              kickoff="2026-10-10T20:00:00+08:00", day="2026-10-10"):
    return {"key": key, "date": day, "actual": actual,
            "fair": {"home": 0.50, "draw": 0.25, "away": 0.25},
            "team_load": {"captured_at": captured, "kickoff": kickoff, "load_diff_14": diff}}


def test_f16_grades_the_more_loaded_side_when_the_14_day_gap_is_at_least_two():
    """F16（2026-10-09 登记稿）：负荷差 ≥2 → 更密一方取胜的残差；只认开球前冻结的台账。"""
    from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS, grade_f16_prospective

    rows = [
        _load_row("a", 3, "1"),      # 主更密、没赢 → 1{胜}=0 − 0.50
        _load_row("b", -2, "0"),     # 客更密、客胜 → 1 − 0.25
        _load_row("c", 1, "3"),      # 差 1：不触发
        _load_row("d", 4, "3", captured="2026-10-10T21:00:00+08:00"),   # 开球后才冻结：不算
        _load_row("e", 2, "3", day="2026-10-01"),                       # 窗口外
        {"key": "f", "date": "2026-10-10", "actual": "3",
         "fair": {"home": 0.5, "draw": 0.25, "away": 0.25}},            # 没挂台账
    ]
    g = grade_f16_prospective(rows, window={"date_from": "2026-10-09"})
    assert g.n_cum == 2 and g.selected_keys == ("a", "b")
    assert abs(g.metric_value_pp - ((0 - 0.50) + (1 - 0.25)) / 2 * 100) < 1e-9
    assert PROSPECTIVE_ADAPTERS["F16"] is grade_f16_prospective      # 2026-10-09 登记


def _pm_row(key, volume, actual, fav=0.70, *, fetched="2026-10-10T12:00:00+08:00",
            day="2026-10-10"):
    rest = (1 - fav) / 2
    return {"key": key, "date": day, "actual": actual,
            "fair": {"home": fav, "draw": rest, "away": rest},
            "polymarket": {"volume": volume, "fetched_at": fetched,
                           "kickoff": "2026-10-10T20:00:00+08:00"}}


def test_f17_grades_hyped_favourites_by_pre_kickoff_polymarket_volume():
    """F17（2026-10-09 登记）：赛前成交 ≥$50k × 模态面 ≥60% → 模态面残差。"""
    from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS, grade_f17_prospective

    rows = [
        _pm_row("a", 80_000, "3"),                 # 热门开出 → 1 − 0.70
        _pm_row("b", 60_000, "1"),                 # 热门没开 → 0 − 0.70
        _pm_row("c", 30_000, "3"),                 # 成交不够
        _pm_row("d", 90_000, "3", fav=0.55),       # 不够热
        _pm_row("e", 90_000, "3", fetched="2026-10-10T21:00:00+08:00"),   # 开球后快照
        {"key": "f", "date": "2026-10-10", "actual": "3",
         "fair": {"home": 0.7, "draw": 0.15, "away": 0.15}},              # 没挂快照
    ]
    g = grade_f17_prospective(rows, window={"date_from": "2026-10-10"})
    assert g.n_cum == 2 and g.selected_keys == ("a", "b")
    assert abs(g.metric_value_pp - ((1 - 0.70) + (0 - 0.70)) / 2 * 100) < 1e-9
    assert PROSPECTIVE_ADAPTERS["F17"] is grade_f17_prospective      # 2026-10-09 登记
