from nutmeg.decision.rsi_grading import (
    PROSPECTIVE_ADAPTERS,
    grade_f5_prospective,
    grade_f9_prospective,
)


def _row(key, actual, fair, *, src="zucai", issue=None, date="2026-09-20", belief=None):
    return {
        "key": key, "actual": actual, "fair": fair, "src": src, "issue": issue, "date": date,
        "belief": belief or fair, "belief_moved": belief is not None and belief != fair,
        "provably_prospective": True,
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
    unproven = {**rows[0], "provably_prospective": None}      # 2026-10-19：证明不了早于开球不收
    assert grade_f9_prospective([unproven], window={"date_from": "2026-09-20"}).n_cum == 0


def test_adapter_registry_names_match_experiments():
    # 2026-09-30：F13（崩塌叙事锚方）、F14（表态面集合命中率）登记并接入
    # 2026-10-01：F15（终盘大热校准）、G1（gym 结构规则 fav_pairs ROI）登记并接入
    # 2026-10-02：K1（判断 rubric 两读 kappa）登记并接入
    # 2026-10-09：F16（赛程负荷，损耗台账）、F17（名气热卖，Polymarket 关注度）登记并接入
    # 2026-10-14：F18（单关许可证，26140 §10b）登记并接入
    # 2026-10-19：F14b（表态 vs 市场 top-k 逐场配对）、K2（逐项 κ）登记并接入
    # 2026-10-20：F19（真实＝已定价，10-16 登记）判据对象化后接入
    assert set(PROSPECTIVE_ADAPTERS) == {"F5", "F9", "F10", "F11", "F13", "F14", "F14b", "F15",
                                         "F16", "F17", "F18", "F19", "G1", "K1", "K2"}


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


def test_adapters_drop_rows_after_the_window_end():
    """2026-10-19 起新登记带 date_to：截止之后的行不再入账。"""
    from nutmeg.decision.rsi_grading import grade_f10_prospective

    fav = {"home": 0.70, "draw": 0.20, "away": 0.10}
    rows = [_row("a", "3", fav, date="2026-12-31"), _row("b", "3", fav, date="2027-01-01")]
    g = grade_f10_prospective(rows, window={"date_from": "2026-10-20", "date_to": "2026-12-31"})
    assert g.n_cum == 1 and g.selected_keys == ("a",)


def _f19_row(key, actual, *, weak="away", strength="real", face="3", cover="1",
             drift=None, priced_in=True, hole="home", date="2026-10-18"):
    row = _row(key, actual, STRONG, date=date)
    row["labels"] = {"underdog_side": weak, "underdog_strength": strength,
                     "stance_face": face, "stance_cover": cover,
                     "hole_location_priced_in": priced_in, "hole_location_side": hole}
    if drift is not None:
        row["intl_drift_pp"] = drift
    return row


def test_f19_class_follows_the_frozen_priced_and_unpriced_rules():
    from nutmeg.decision.rsi_grading import f19_class
    flat = {"home": 0.5, "draw": -0.2, "away": -0.3}            # 弱方+平 −0.5 ≤ 0
    moved = {"home": -1.5, "draw": 0.6, "away": 0.9}            # 弱方+平 +1.5 ≥ +1
    assert f19_class(_f19_row("a", "1", drift=flat)) == ("价内", "1")   # 研究答已价内
    assert f19_class(_f19_row("b", "1", drift=flat, priced_in=False)) == ("未价", "1")
    assert f19_class(_f19_row("c", "1", drift=moved, priced_in=False)) == ("价内", "1")
    assert f19_class(_f19_row("d", "1", drift=flat, priced_in=False, hole="away")) == ("价内", "1")
    assert f19_class(_f19_row("e", "0", drift=flat, face="0", cover=None)) == ("价内", "0")
    assert f19_class(_f19_row("f", "1", drift=flat, cover=None)) is None      # 无剧本「—」
    assert f19_class(_f19_row("g", "1")) is None                               # 无国际盘「?」
    assert f19_class(_f19_row("h", "1", drift=flat, strength="weak")) is None  # 标弱另计


def test_f19_grades_priced_group_and_reports_unpriced_as_contrast():
    from nutmeg.decision.rsi_grading import grade_f19_prospective
    flat = {"home": 0.5, "draw": -0.2, "away": -0.3}
    rows = [_f19_row("p1", "1", drift=flat), _f19_row("p2", "3", drift=flat),
            _f19_row("u1", "1", drift=flat, priced_in=False),
            _f19_row("early", "1", drift=flat, date="2026-10-16")]
    g = grade_f19_prospective(rows, window={"date_from": "2026-10-17"}, boots=200)
    assert g.n_cum == 2 and g.selected_keys == ("p1", "p2")
    assert round(g.metric_value_pp, 6) == round(((1 - 0.2) + (0 - 0.2)) / 2 * 100, 6)
    assert round(g.cost_axis_pp, 6) == 80.0
    rows[0]["provably_prospective"] = False
    assert grade_f19_prospective(rows, window={"date_from": "2026-10-17"}, boots=200).n_cum == 1
