import pytest

from nutmeg.decision.face_status import FaceStatusError, attach_face_status, derive_faces

_PROOFS_ALIVE = {
    "a_no_scoring_mechanism": False,
    "b_precedent_carrier_gone": False,
    "c_anchor_pass": False,
    "proof_count": "0/3",
    "verdict": "alive",
    "detail": "...",
}
_PROOFS_DEAD = {
    "a_no_scoring_mechanism": True,
    "b_precedent_carrier_gone": True,
    "c_anchor_pass": True,
    "proof_count": "3/3",
    "verdict": "dead",
    "detail": "...",
}
_PROOFS_2OF3_DEAD_CLAIM = {
    **_PROOFS_DEAD,
    "b_precedent_carrier_gone": False,
    "proof_count": "2/3",
    "verdict": "dead",
}


def _research(**faces):
    return {
        "death_three_proofs": {
            face: faces.get(face, _PROOFS_ALIVE) for face in ("home", "draw", "away")
        }
    }


def _leg(faces="310", precedents=None, never=None):
    leg = {
        "faces": faces,
        "fair": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "precedents": precedents or [],
    }
    if never is not None:
        leg["never_faces"] = never
    return leg


def test_dead_requires_three_proofs_and_faces_becomes_derived():
    leg = _leg(faces="31")
    attach_face_status(leg, _research(away=_PROOFS_DEAD), source="26129-research-m3.json")
    fs = leg["face_status"]
    assert fs["away"]["state"] == "dead" and fs["home"]["state"] == "alive"
    assert fs["away"]["source"] == "26129-research-m3.json#death_three_proofs.away"
    assert all(leg["_d3"]["away"][key] for key in ("a", "b", "c"))
    assert derive_faces(fs) == "31" and leg["faces"] == "31"


def test_dead_claim_without_three_proofs_is_an_error_not_a_downgrade():
    leg = _leg(faces="31")
    with pytest.raises(FaceStatusError, match="3/3"):
        attach_face_status(leg, _research(away=_PROOFS_2OF3_DEAD_CLAIM), source="x")


def test_missing_proofs_mean_alive_burden_is_on_death():
    leg = _leg(faces="310")
    attach_face_status(leg, {"death_three_proofs": {}}, source="x")
    assert all(value["state"] == "alive" for value in leg["face_status"].values())


def test_never_only_from_explicit_declaration_not_from_no_precedent():
    leg = _leg(faces="310", precedents=[["0", "查无先例", "none"]])
    attach_face_status(leg, _research(), source="x")
    assert leg["face_status"]["away"]["state"] == "alive"
    assert leg["face_status"]["away"]["precedent"] == "none"
    leg2 = _leg(faces="31", never=["away"])
    attach_face_status(leg2, _research(), source="x")
    assert leg2["face_status"]["away"]["state"] == "never"


def test_hand_written_faces_that_disagree_with_derivation_are_an_error():
    leg = _leg(faces="3")
    with pytest.raises(FaceStatusError, match="faces"):
        attach_face_status(leg, _research(), source="x")
