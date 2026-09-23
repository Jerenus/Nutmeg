from nutmeg.decision.stance import apply_tilt, stance_faces, validate_stance

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


def test_validate_flags_enum_cover_confidence_and_falsifier():
    _, issues = validate_stance(_stance(face="x", structure="double", cover="3", confidence=4,
                                        falsifier="短"), confidence=3, death_three_proofs={})
    msgs = " ".join(i.message for i in issues)
    assert "face" in msgs and "cover" in msgs and "confidence" in msgs and "falsifier" in msgs
    assert all(i.level == "ERROR" for i in issues)


def test_validate_requires_tilt_and_why_to_agree_and_forbids_dead_faces():
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence"), confidence=3,
                                death_three_proofs={})
    assert any("tilt" in i.message for i in issues)
    _, issues = validate_stance(_stance(why_not_market="structure"), confidence=3,
                                death_three_proofs={})
    assert any("没有面被判死" in i.message for i in issues)
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
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence", tilt=tilt), confidence=3,
                                death_three_proofs={})
    msgs = [i.message for i in issues]
    assert any("pp 9" in m and "official" in m for m in msgs)
    assert any("will" in m and "朝平" in m for m in msgs)
    assert any("made_up_kind" in m for m in msgs)


def test_apply_tilt_zeroes_below_5pp_caps_and_drops_post_kickoff_evidence():
    ev = lambda tier, pp, at="2026-09-23T10:00:00+08:00": {  # noqa: E731
        "tier": tier, "kind": "absence_official", "pp": pp, "source": "s", "captured_at": at}
    small = {"face": "3", "expires_if": "", "evidence": [ev("inferred", 2), ev("inferred", 2)]}
    r = apply_tilt(PRIOR, small, kickoff="2026-09-23T19:30:00+08:00")
    assert r.zeroed and r.applied_pp == 0 and r.belief == PRIOR and "归零" in r.reason
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
