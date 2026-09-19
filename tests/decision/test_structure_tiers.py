from nutmeg.decision.structure_tiers import (
    C14_CHEAP_LINE,
    C14_VARIANCE_LINE,
    board_wind,
    license_score,
    narrowable_faces,
    tier_of,
)

LQ4 = {
    "q1_spine": True,
    "q2_route": True,
    "q3a_opponent_scores": False,
    "q4_no_context_flag": True,
}
LQ3 = {**LQ4, "q4_no_context_flag": False}


def _fs(**states):
    return {
        face: {
            "state": states.get(face, "alive"),
            "proofs": {"a": False, "b": False, "c": False},
            "precedent": "none",
            "source": "x",
        }
        for face in ("home", "draw", "away")
    }


def _leg(lq=LQ4, integrity="pass", crash=(), fair=(0.6, 0.25, 0.15), d3=None, fs=None):
    d3 = d3 or {}
    return {
        "license_questions": lq,
        "anchor_integrity": integrity,
        "crash_markers": list(crash),
        "fair": dict(zip(("home", "draw", "away"), fair, strict=True)),
        "_d3": {
            face: {"a": count >= 1, "b": count >= 2, "c": count >= 3}
            for face, count in d3.items()
        },
        "face_status": fs or _fs(),
    }


def test_license_score_reads_four_questions_not_q3b():
    assert license_score(LQ4) == 4 and license_score(LQ3) == 3
    assert license_score({**LQ4, "q3a_opponent_scores": True}) == 3


def test_tiers_follow_the_b5c_matrix():
    assert tier_of(_leg()) == "T1"
    assert tier_of(_leg(crash=["opening_new_coach_debut"])) == "T3"
    assert tier_of(_leg(lq=LQ3)) == "T2"
    assert tier_of(_leg(lq=LQ3, integrity="symmetric_damage")) == "T2"
    assert tier_of(_leg(lq=LQ3, integrity="fail")) == "T3"
    assert tier_of(_leg(lq=LQ3, fair=(0.40, 0.30, 0.30), integrity="fail")) == "T4"


def test_tier_is_monotonic_in_license_score():
    assert tier_of(_leg(lq=LQ4, integrity="symmetric_damage")) == "T2"
    assert tier_of(_leg(lq=LQ4)) == "T1"
    assert tier_of(_leg(lq=LQ4, crash=["opening_new_coach_debut"])) == "T3"


def test_narrowable_face_needs_two_proofs_and_cheap_price():
    leg = _leg(fair=(0.6, 0.25, 0.15), d3={"away": 2})
    assert narrowable_faces(leg) == ["away"]
    assert narrowable_faces(_leg(fair=(0.6, 0.25, 0.15), d3={"away": 1})) == []
    assert narrowable_faces(_leg(fair=(0.6, 0.22, 0.18), d3={"away": 2})) == []
    assert narrowable_faces(_leg(fair=(0.5, 0.25, 0.25), d3={"away": 2})) == []
    assert C14_CHEAP_LINE == 0.15 and C14_VARIANCE_LINE == 0.20
    dead = _leg(fair=(0.6, 0.25, 0.15), d3={"away": 3}, fs=_fs(away="dead"))
    assert narrowable_faces(dead) == []


def test_board_wind_counts_tiers_and_names_the_regime():
    legs = {str(i): _leg(fair=(0.65, 0.2, 0.15)) for i in range(1, 6)}
    legs.update(
        {
            str(i): _leg(lq=LQ3, integrity="fail", fair=(0.4, 0.3, 0.3))
            for i in range(6, 15)
        }
    )
    wind = board_wind(legs)
    assert wind["regime"] == "hot" and wind["tiers"]["T1"] == 5
    assert wind["tiers"]["T4"] == 9
    assert wind["cap_band"] in ("low", "mid", "full")
