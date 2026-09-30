from nutmeg.decision.rsi_grading import (
    PROSPECTIVE_ADAPTERS,
    grade_f3_prospective,
    grade_f5_prospective,
    grade_f9_prospective,
)


def _row(key, actual, fair, *, src="zucai", issue=None, date="2026-09-20", belief=None):
    return {
        "key": key, "actual": actual, "fair": fair, "src": src, "issue": issue, "date": date,
        "belief": belief or fair, "belief_moved": belief is not None and belief != fair,
    }


STRONG = {"home": 0.65, "draw": 0.2, "away": 0.15}
COIN = {"home": 0.4, "draw": 0.3, "away": 0.3}
BAND = {"home": 0.45, "draw": 0.3, "away": 0.25}  # gap12 = 15pp → F5a band


def test_f3_counts_only_window_issues_and_top1_at_least_60():
    rows = [
        _row("26125-1", "3", STRONG, issue="26125"),
        _row("26130-2", "0", STRONG, issue="26130"),
        _row("26124-3", "3", STRONG, issue="26124"),  # before window
        _row("26137-4", "3", STRONG, issue="26137"),  # after window
        _row("26126-5", "3", COIN, issue="26126"),  # top1 < 60
        _row("j1", "3", STRONG, src="jczq"),  # wrong lane
    ]
    g = grade_f3_prospective(rows, window={"issue_from": "26125", "issue_to": "26136"})
    assert g.stratum == "zucai" and g.n_cum == 2
    assert round(g.metric_value_pp, 1) == round((0.5 - 0.65) * 100, 1)
    assert g.computed_by.endswith("grade_f3_prospective")
    assert g.inputs_hash == grade_f3_prospective(
        rows, window={"issue_from": "26125", "issue_to": "26136"}
    ).inputs_hash


def test_f5_uses_gap_band_across_lanes_and_respects_date_from():
    rows = [
        _row("z1", "3", BAND, date="2026-09-19"),
        _row("j1", "0", BAND, src="jczq", date="2026-09-21"),
        _row("j2", "3", BAND, src="jczq", date="2026-09-18"),  # before window
        _row("j3", "3", STRONG, src="jczq", date="2026-09-21"),  # gap 45pp, outside band
    ]
    pooled = grade_f5_prospective(rows, window={"date_from": "2026-09-19"})
    assert pooled.stratum == "pooled" and pooled.n_cum == 2
    assert round(pooled.metric_value_pp, 1) == round((0.5 - 0.45) * 100, 1)
    jczq = grade_f5_prospective(rows, window={"date_from": "2026-09-19"}, stratum="jczq")
    assert jczq.stratum == "jczq" and jczq.n_cum == 1


def test_f9_brier_delta_is_positive_when_belief_beats_market_and_zero_without_moves():
    better = {"home": 0.8, "draw": 0.1, "away": 0.1}
    rows = [
        _row("m1", "3", COIN, belief=better),  # belief nearer the outcome
        _row("m2", "3", COIN),  # no move → excluded
        _row("m3", "3", COIN, belief=better, date="2026-09-19"),  # before window
    ]
    g = grade_f9_prospective(rows, window={"date_from": "2026-09-20"}, boots=200)
    assert g.n_cum == 1 and g.metric_value_pp > 0
    empty = grade_f9_prospective(rows[1:2], window={"date_from": "2026-09-20"})
    assert empty.n_cum == 0 and empty.metric_value_pp == 0.0


def test_adapter_registry_names_match_experiments():
    # 2026-09-30：F13（崩塌叙事锚方）、F14（表态面集合命中率）登记并接入
    assert set(PROSPECTIVE_ADAPTERS) == {"F3", "F5", "F9", "F10", "F11", "F13", "F14"}
