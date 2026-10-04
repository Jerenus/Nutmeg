"""Machine-readable B5c tiers, narrowable faces, and board wind."""
from __future__ import annotations

FACES = ("home", "draw", "away")

# RULEBOOK B5c/C14 constants. Changes require the governed RSI deployment path.
C14_CHEAP_LINE = 0.15
C14_VARIANCE_LINE = 0.20
NARROW_MIN_PROOFS = 2
TIER_MAX_NARROWINGS = {"T1": 2, "T2": 1, "T3": 0, "T4": 0}
TICKET_MAX_NARROWINGS = 3
COIN_TOP1 = 0.45
HOT_TOP1 = 0.60
COLD_DRAW = 0.29


def license_score(questions: dict | None) -> int:
    questions = questions or {}
    return (
        int(bool(questions.get("q1_spine")))
        + int(bool(questions.get("q2_route")))
        + int(not questions.get("q3a_opponent_scores", True))
        + int(bool(questions.get("q4_no_context_flag")))
    )


def _alive(leg: dict) -> list[str]:
    face_status = leg.get("face_status") or {}
    return [
        face
        for face in FACES
        if (face_status.get(face) or {}).get("state", "alive") == "alive"
    ]


def tier_of(leg: dict) -> str:
    score = license_score(leg.get("license_questions"))
    integrity = str(leg.get("anchor_integrity") or "").lower()
    if score == 4 and integrity == "pass" and not leg.get("crash_markers"):
        return "T1"
    if (
        score >= 3
        and integrity in ("pass", "symmetric_damage")
        and not leg.get("crash_markers")
    ):
        return "T2"
    fair = leg.get("fair") or {}
    if len(_alive(leg)) == 3 and fair and max(float(value) for value in fair.values()) < COIN_TOP1:
        return "T4"
    return "T3"


def _d3_count(leg: dict, face: str) -> int:
    doc = (leg.get("_d3") or {}).get(face)
    if doc is None:
        doc = ((leg.get("face_status") or {}).get(face) or {}).get("proofs") or {}
    return sum(int(bool(doc.get(key))) for key in ("a", "b", "c"))


def narrowable_faces(leg: dict) -> list[str]:
    fair = leg.get("fair") or {}
    return [
        face
        for face in _alive(leg)
        if float(fair.get(face, 1.0)) <= C14_CHEAP_LINE
        and _d3_count(leg, face) >= NARROW_MIN_PROOFS
    ]


