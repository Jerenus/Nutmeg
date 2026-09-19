"""Derive first-order alive/dead/never status for each outcome face."""
from __future__ import annotations

FACES = ("home", "draw", "away")
FACE_DIGIT = {"home": "3", "draw": "1", "away": "0"}
_PROOF_KEYS = (
    ("a_no_scoring_mechanism", "a"),
    ("b_precedent_carrier_gone", "b"),
    ("c_anchor_pass", "c"),
)


class FaceStatusError(ValueError):
    pass


def _proofs(doc: dict | None) -> dict[str, bool]:
    doc = doc or {}
    return {short: bool(doc.get(long, doc.get(short, False))) for long, short in _PROOF_KEYS}


def _precedent_status(leg: dict, face: str) -> str:
    digit = FACE_DIGIT[face]
    statuses = {
        str(precedent[2])
        for precedent in leg.get("precedents") or []
        if len(precedent) >= 3 and str(precedent[0]) == digit
    }
    if "alive" in statuses:
        return "alive"
    if "dead" in statuses:
        return "dead"
    return "none"


def derive_faces(face_status: dict) -> str:
    return "".join(FACE_DIGIT[face] for face in FACES if face_status[face]["state"] == "alive")


def attach_face_status(leg: dict, research: dict, *, source: str) -> dict:
    """Attach face status in place and require any written faces to match it."""
    death_three_proofs = (research or {}).get("death_three_proofs") or {}
    never = set(leg.get("never_faces") or [])
    out: dict[str, dict] = {}
    d3: dict[str, dict] = {}
    for face in FACES:
        doc = death_three_proofs.get(face)
        proofs = _proofs(doc)
        d3[face] = {**proofs, "detail": str((doc or {}).get("detail") or "")}
        count = sum(proofs.values())
        verdict = str((doc or {}).get("verdict") or "alive").lower()
        if face in never:
            state = "never"
        elif verdict == "dead":
            if count < 3:
                raise FaceStatusError(
                    f"{face} declared dead with only {count}/3 proofs; dead requires 3/3"
                )
            state = "dead"
        else:
            state = "alive"
        out[face] = {
            "state": state,
            "proofs": proofs,
            "precedent": _precedent_status(leg, face),
            "source": f"{source}#death_three_proofs.{face}",
        }

    derived = derive_faces(out)
    written = str(leg.get("faces") or "")
    if written and set(written) != set(derived):
        raise FaceStatusError(f"written faces={written!r} disagree with derived faces={derived!r}")
    leg["face_status"] = out
    leg["_d3"] = d3
    leg["faces"] = derived
    return out
