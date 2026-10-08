"""Derive first-order alive/dead/never status for each outcome face."""
from __future__ import annotations

from nutmeg.decision.faces import CODE_OF, FACES

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
    digit = CODE_OF[face]
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


def proven_dead(research: dict | None) -> set[str]:
    """研究以三证 3/3 判死的面（home/draw/away）。不足 3 证的「dead」不算死面——
    `attach_face_status` 对它直接拒收，这里同一口径。"""
    out = set()
    for face in FACES:
        doc = ((research or {}).get("death_three_proofs") or {}).get(face)
        if (str((doc or {}).get("verdict") or "alive").lower() == "dead"
                and sum(_proofs(doc).values()) == 3):
            out.add(face)
    return out


def derive_faces(face_status: dict) -> str:
    return "".join(CODE_OF[face] for face in FACES if face_status[face]["state"] == "alive")


def attach_face_status(
    leg: dict,
    research: dict,
    *,
    source: str,
    basis: str | None = None,
) -> dict:
    """Attach face status in place and require any written faces to match it."""
    resolved_basis = basis or ("researched" if research else "default")
    if resolved_basis not in {"researched", "default"}:
        raise FaceStatusError(f"unknown face_status basis: {resolved_basis}")
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
            "basis": resolved_basis,
        }

    derived = derive_faces(out)
    written = str(leg.get("faces") or "")
    bought_dead = set(written) - set(derived)
    if bought_dead:
        raise FaceStatusError(
            f"written faces={written!r} buy dead/never faces {sorted(bought_dead)} "
            f"(alive={derived!r})"
        )
    leg["face_status"] = out
    leg["_d3"] = d3
    # strength-v2（2026-09-26）：活面集是事实层，不再强制票面；收窄是第二序的表达，
    # 保留书面面集并记下两者的差，供复盘看「排掉的活面」开出率。
    if written and set(written) != set(derived):
        leg["faces_vs_alive"] = {"written": written, "alive": derived}
    else:
        leg["faces"] = derived
    return out
