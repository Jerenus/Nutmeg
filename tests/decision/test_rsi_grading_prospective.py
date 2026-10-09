from nutmeg.decision.rsi_grading import (
    PROSPECTIVE_ADAPTERS,
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
    # 2026-10-01：F15（终盘大热校准）、G1（gym 结构规则 fav_pairs ROI）登记并接入
    # 2026-10-02：K1（判断 rubric 两读 kappa）登记并接入
    # 2026-10-09：F16（赛程负荷，损耗台账）登记并接入
    assert set(PROSPECTIVE_ADAPTERS) == {"F5", "F9", "F10", "F11", "F13", "F14", "F15", "F16",
                                         "G1", "K1"}


def test_k1_pools_item_pairs_and_scores_full_agreement_as_100():
    from nutmeg.decision.rsi_grading import grade_k1_prospective

    def row(key, a, b, date="2026-10-03"):
        return {"key": key, "date": date, "actual": "3",
                "fair": {"home": .5, "draw": .3, "away": .2},
                "labels": {"rubric": a, "rubric_b": {"items": b}, "rubric_version": "r1"}}

    same = {"S_anchor_side": {"answer": "home", "p": 1},
            "F_absence_home": {"answer": "yes", "p": .9}}
    rows = [row("a", same, same), row("b", same, same)]
    g = grade_k1_prospective(rows, window={"date_from": "2026-10-02"}, boots=200)
    assert g.n_cum == 4 and g.metric_value_pp == 100.0 and g.ci_low_pp == 100.0
    diff = {"S_anchor_side": {"answer": "away", "p": 1},
            "F_absence_home": {"answer": "no", "p": .2}}
    g2 = grade_k1_prospective([row("a", same, diff), row("b", same, same)],
                              window={"date_from": "2026-10-02"}, boots=200)
    assert g2.n_cum == 4 and g2.metric_value_pp < 100.0
    assert grade_k1_prospective([row("x", same, same, date="2026-09-01")],
                                window={"date_from": "2026-10-02"}).n_cum == 0
    assert grade_k1_prospective([row("y", same, {})], window={"date_from": "2026-10-02"}).n_cum == 0


def test_f15_counts_only_closing_favourites_in_window():
    from nutmeg.decision.rsi_grading import grade_f15_prospective

    rows = [
        {"src": "jczq", "date": "2026-10-03", "actual": "3",
         "closing": {"sharp_fair": {"home": 0.75, "draw": 0.15, "away": 0.10}}},
        {"src": "jczq", "date": "2026-10-03", "actual": "0",
         "closing": {"sharp_fair": {"home": 0.72, "draw": 0.18, "away": 0.10}}},
        {"src": "jczq", "date": "2026-10-03", "actual": "3",
         "closing": {"sharp_fair": {"home": 0.55, "draw": 0.25, "away": 0.20}}},   # <0.70 不算
        {"src": "jczq", "date": "2026-09-30", "actual": "3",
         "closing": {"sharp_fair": {"home": 0.80, "draw": 0.12, "away": 0.08}}},   # 窗外
        {"src": "zucai", "date": "2026-10-03", "actual": "3", "fair": {"home": 0.8, "draw": 0.1,
                                                                        "away": 0.1}},
    ]
    g = grade_f15_prospective(rows, window={"date_from": "2026-10-02"})
    expected = ((1 - 0.75) + (0 - 0.72)) / 2 * 100
    assert g.n_cum == 2 and round(g.metric_value_pp, 1) == round(expected, 1)
    assert grade_f15_prospective([], window={"date_from": "2026-10-02"}).n_cum == 0


def test_g1_rois_the_gym_ledger_by_day():
    from nutmeg.decision.rsi_grading import grade_g1_prospective

    ledger = [
        {"policy": "jczq_fav_pairs", "key": "2026-10-03", "stake": 4, "net": 2.0},
        {"policy": "jczq_fav_pairs", "key": "2026-10-03", "stake": 2, "net": -2.0},
        {"policy": "jczq_fav_pairs", "key": "2026-10-04", "stake": 2, "net": 1.0},
        {"policy": "jczq_fav_pairs", "key": "2026-10-05", "stake": None, "net": None,
         "forced_flat": True},
        {"policy": "jczq_max_p", "key": "2026-10-03", "stake": 8, "net": -8.0},
    ]
    g = grade_g1_prospective([], window={"date_from": "2026-10-02"}, ledger=ledger)
    assert g.n_cum == 2 and round(g.metric_value_pp, 2) == round(1 / 8 * 100, 2)
    assert g.ci_low_pp <= g.metric_value_pp <= g.ci_high_pp
    assert grade_g1_prospective([], window={"date_from": "2026-10-02"}, ledger=[]).n_cum == 0
