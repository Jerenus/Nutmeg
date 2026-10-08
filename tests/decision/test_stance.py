from nutmeg.decision.stance import apply_tilt, research_belief, stance_faces, validate_stance

PRIOR = {"home": 0.52, "draw": 0.26, "away": 0.22}
DEAD_AWAY = {"away": {"verdict": "dead", "a_no_scoring_mechanism": True,
                      "b_precedent_carrier_gone": True, "c_anchor_pass": True}}


def _stance(**over) -> dict:
    base = {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
            "falsifier": "客队首发若有主力门将则本判断作废", "why_not_market": "none",
            "tilt": None, "alt_face": "1", "market_read": "agree"}
    base.update(over)
    return base


def test_stance_faces_orders_by_sporttery_convention():
    assert stance_faces(_stance()) == "31"
    assert stance_faces(_stance(structure="single")) == "3"
    assert stance_faces(_stance(structure="double", face="0", cover="1")) == "10"
    assert stance_faces(_stance(structure="full")) == "310"


def test_validate_accepts_market_follow_and_normalises():
    norm, issues = validate_stance(_stance(), confidence=3, death_three_proofs={})
    assert issues == [] and norm["faces"] == "31" and norm["tilt"] is None
    assert norm["normalized"] == []


def test_validate_flags_enum_cover_confidence_and_falsifier():
    _, issues = validate_stance(_stance(face="x", structure="double", cover="3", confidence=4,
                                        falsifier="短"), confidence=3, death_three_proofs={})
    msgs = " ".join(i.message for i in issues)
    assert "face" in msgs and "cover" in msgs and "confidence" in msgs and "falsifier" in msgs
    assert all(i.level == "ERROR" for i in issues)


def test_validate_normalises_why_not_market_against_the_tilt_and_forbids_dead_faces():
    """why_not_market 是 tilt/三证的派生标签；自相矛盾时改标签并留痕，不整份驳回
    （2026-09-26 周六006/010/015 因此丢了整份深研）。"""
    norm, issues = validate_stance(_stance(why_not_market="tilt_evidence"), confidence=3,
                                   death_three_proofs={})
    assert issues == [] and norm["why_not_market"] == "none"
    assert norm["normalized"] == ["why_not_market tilt_evidence→none（没有 tilt）"]
    norm, issues = validate_stance(_stance(why_not_market="structure"), confidence=3,
                                   death_three_proofs={})
    assert issues == [] and norm["why_not_market"] == "none"
    assert "没有面被判死" in norm["normalized"][0]
    tilt = {"face": "1", "expires_if": "x", "evidence": [
        {"tier": "inferred", "kind": "style_matchup", "pp": 2, "source": "s",
         "captured_at": "2026-09-26T10:00:00+08:00"}]}
    norm, issues = validate_stance(_stance(why_not_market="none", tilt=tilt), confidence=3,
                                   death_three_proofs={})
    assert issues == [] and norm["why_not_market"] == "tilt_evidence"
    _, issues = validate_stance(_stance(structure="double", face="3", cover="0"), confidence=3,
                                death_three_proofs=DEAD_AWAY)
    assert any("已判死" in i.message for i in issues)


def test_validate_tilt_rules_tier_range_kind_lexicon_and_will_only_toward_draw():
    tilt = {"face": "3", "expires_if": "官宣名单里 X 出场则撤回", "evidence": [
        {"tier": "official", "kind": "absence_official", "pp": 9, "source": "club",
         "captured_at": "2026-09-23T10:00:00+08:00"},
        {"tier": "will", "kind": "motivation_dead_rubber", "pp": 2, "source": "x",
         "captured_at": "2026-09-23T10:00:00+08:00"},
        {"tier": "inferred", "kind": "made_up_kind", "pp": 1, "source": "x",
         "captured_at": "2026-09-23T10:00:00+08:00"},
    ]}
    norm, issues = validate_stance(_stance(why_not_market="tilt_evidence", tilt=tilt),
                                   confidence=3, death_three_proofs={})
    msgs = [i.message for i in issues]
    # 2026-09-30：pp 超区间夹到上限并留痕，不再整份拒收（周一001/26134-14 各被拒两次）
    assert not any("pp 9" in m for m in msgs)
    assert any("official pp 9→8" in n for n in norm["normalized"])
    assert any("will" in m and "朝平" in m for m in msgs)
    assert any("made_up_kind" in m for m in msgs)


def test_apply_tilt_expresses_small_moves_caps_and_drops_post_kickoff_evidence():
    # strength-v2（2026-09-26）：<5pp 不再归零——小而真实的利好利空如实表达。
    ev = lambda tier, pp, at="2026-09-23T10:00:00+08:00": {  # noqa: E731
        "tier": tier, "kind": "absence_official", "pp": pp, "source": "s", "captured_at": at}
    small = {"face": "3", "expires_if": "",
             "evidence": [ev("confirmed_structural", 3), ev("inferred", 2)]}
    r = apply_tilt(PRIOR, small, kickoff="2026-09-23T19:30:00+08:00")
    assert not r.zeroed and r.applied_pp == 5
    assert round(r.belief["home"], 2) == 0.57 and round(sum(r.belief.values()), 6) == 1.0
    big = {"face": "3", "expires_if": "",
           "evidence": [ev("official", 8), ev("confirmed_structural", 6), ev("inferred", 2)]}
    r = apply_tilt(PRIOR, big, kickoff="2026-09-23T19:30:00+08:00")
    assert r.applied_pp == 15 and not r.zeroed
    assert r.tiers == ["official", "confirmed_structural", "inferred"]
    assert round(r.belief["home"], 2) == 0.67 and round(sum(r.belief.values()), 6) == 1.0
    assert round(r.belief["draw"] / r.belief["away"], 3) == round(
        PRIOR["draw"] / PRIOR["away"], 3)
    late = {"face": "3", "expires_if": "",
            "evidence": [ev("official", 8, "2026-09-23T20:00:00+08:00")]}
    r = apply_tilt(PRIOR, late, kickoff="2026-09-23T19:30:00+08:00")
    assert r.zeroed and "开球后" in r.reason
    nooff = {"face": "1", "expires_if": "",
             "evidence": [ev("confirmed_structural", 6), ev("confirmed_structural", 6)]}
    assert apply_tilt(PRIOR, nooff).applied_pp == 10  # 无官宣封顶 10


def _ev(tier="inferred", kind="style_matchup", pp=2):
    return {"tier": tier, "kind": kind, "pp": pp, "source": "s",
            "captured_at": "2026-09-23T10:00:00+08:00"}


def test_apply_tilt_shift_moves_several_faces_and_keeps_the_sum():
    tilt = {"shift": {"3": -1, "1": 3, "0": -2}, "expires_if": "",
            "evidence": [_ev(tier="confirmed_structural", kind="lineup_confirmed", pp=3),
                         _ev(tier="state", kind="form_state", pp=1)]}
    r = apply_tilt(PRIOR, tilt)
    assert not r.zeroed and r.applied_pp == 3
    expected = {"home": 0.51, "draw": 0.29, "away": 0.20}
    assert {k: round(v, 4) for k, v in r.belief.items()} == expected


def test_apply_tilt_shift_is_capped_per_face_without_official_evidence():
    evidence = [_ev(tier="confirmed_structural", kind="absence_official", pp=6),
                _ev(tier="confirmed_structural", kind="goalkeeper_change", pp=6), _ev(pp=2)]
    tilt = {"shift": {"3": 14, "1": -7, "0": -7}, "expires_if": "", "evidence": evidence}
    r = apply_tilt(PRIOR, tilt)
    assert r.applied_pp == 10 and "单面上限" in r.reason
    assert round(r.belief["home"], 4) == 0.62 and round(sum(r.belief.values()), 6) == 1.0


def test_shift_peak_cannot_exceed_the_evidence_budget():
    """Jun 2026-09-30：shift 是研究自由写的数字，峰值不得超过证据能支撑的 pp。"""
    tilt = {"shift": {"3": 4, "1": -2, "0": -2}, "expires_if": "",
            "evidence": [_ev(tier="confirmed_structural", kind="absence_official", pp=3)]}
    r = apply_tilt(PRIOR, tilt)
    assert r.applied_pp == 3 and "证据预算 3pp" in r.reason
    assert round(r.belief["home"], 4) == 0.55


def test_form_state_evidence_counts_at_most_one_pp():
    """同组交叉/单场状态 每条最多 1pp：09-28 三处 form_state 拨动 2pp 全反。"""
    state2 = _ev(tier="state", kind="form_state", pp=2)
    anchor = _ev(tier="confirmed_structural", kind="absence_official", pp=3)
    r = apply_tilt(PRIOR, {"shift": {"3": 5, "1": -3, "0": -2}, "expires_if": "",
                           "evidence": [anchor, state2]})
    assert r.applied_pp == 4 and "证据预算 4pp" in r.reason   # 3 + form_state 只计 1
    face_only = apply_tilt(PRIOR, {"face": "3", "expires_if": "", "evidence": [anchor, state2]})
    assert face_only.applied_pp == 4


def test_tilt_without_official_or_structural_evidence_is_zeroed():
    """Jun 2026-09-30：状态/推断级证据只能写进研究，不能挪 belief。"""
    r = apply_tilt(PRIOR, {"shift": {"3": 2, "1": -1, "0": -1}, "expires_if": "",
                           "evidence": [_ev(pp=2), _ev(tier="state", kind="form_state", pp=1)]})
    assert r.zeroed and r.applied_pp == 0 and "无官宣/确证结构级证据" in r.reason
    assert r.belief == PRIOR and r.tiers == ["inferred", "state"]
    face_only = apply_tilt(PRIOR, {"face": "1", "expires_if": "", "evidence": [_ev(pp=2)]})
    assert face_only.zeroed


def test_validate_shift_must_sum_to_zero_and_use_the_strength_lexicon():
    good = {"shift": {"3": 2, "1": -1, "0": -1}, "expires_if": "",
            "evidence": [_ev(kind="underdog_path"), _ev(tier="state", kind="form_state", pp=3)]}
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence", tilt=good), confidence=3,
                                death_three_proofs={})
    assert issues == []
    bad = {"shift": {"3": 2, "1": 0, "0": 0}, "expires_if": "", "evidence": [_ev()]}
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence", tilt=bad), confidence=3,
                                death_three_proofs={})
    assert any("shift" in i.message and "0" in i.message for i in issues)


def test_research_belief_follows_market_when_the_tilt_is_zeroed_and_keeps_prior_as_given():
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief, result = research_belief(prior, None)
    assert belief == prior and belief is not prior and result.zeroed
    state_only = {"shift": {"3": 2, "1": 0, "0": -2}, "evidence": [_ev(tier="state",
                                                                       kind="form_state")]}
    assert research_belief(prior, state_only)[0] == prior        # 无锚证据：归零


def test_research_belief_zeroes_dead_faces_after_the_tilt():
    tilt = {"shift": {"3": 3, "1": 0, "0": -3}, "expires_if": "",
            "evidence": [_ev(tier="confirmed_structural", kind="lineup_confirmed", pp=3)]}
    moved, result = research_belief(PRIOR, tilt)
    assert not result.zeroed and moved["home"] > PRIOR["home"]
    alive_only, _ = research_belief(PRIOR, tilt, alive=["home", "draw"])
    assert alive_only["away"] == 0.0
    assert abs(alive_only["home"] / alive_only["draw"] - moved["home"] / moved["draw"]) < 1e-12
    assert abs(sum(alive_only.values()) - 1.0) < 1e-12
    untilted, _ = research_belief(PRIOR, None, alive=["home", "draw"])
    mass = 0.52 + 0.26 + 0.0
    assert untilted == {"home": 0.52 / mass, "draw": 0.26 / mass, "away": 0.0}
    try:
        research_belief(PRIOR, None, alive=[])
    except ValueError as exc:
        assert "活面" in str(exc)
    else:
        raise AssertionError("no alive face must raise")
