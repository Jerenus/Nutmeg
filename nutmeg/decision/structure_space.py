"""Enumerate the bounded structural space without making football judgments."""
from __future__ import annotations

import hashlib
import itertools
import json

from nutmeg.decision.structure_tiers import (
    C14_CHEAP_LINE,
    C14_VARIANCE_LINE,
    TICKET_MAX_NARROWINGS,
    TIER_MAX_NARROWINGS,
    narrowable_faces,
    tier_of,
)

FACES = ("home", "draw", "away")
DIGIT = {"home": "3", "draw": "1", "away": "0"}
RENJIU_PICK = 9


class NoFaceStatusError(ValueError):
    pass


def _alive(leg: dict) -> list[str]:
    face_status = leg.get("face_status")
    if not face_status:
        raise NoFaceStatusError("legs-base has no face_status; run B4 zucai-build-reads first")
    return [face for face in FACES if face_status[face]["state"] == "alive"]


def _faces_str(faces: list[str]) -> str:
    return "".join(DIGIT[face] for face in FACES if face in faces)


def cover_options(leg: dict, *, mode: str) -> list[tuple[str, float]]:
    if mode not in ("matrix", "strict"):
        raise ValueError("mode must be matrix or strict")
    alive = _alive(leg)
    if not alive:
        return []
    fair = leg["fair"]
    full = (_faces_str(alive), sum(float(fair[face]) for face in alive))
    if mode == "strict":
        return [full]
    limit = TIER_MAX_NARROWINGS[tier_of(leg)]
    narrowable = narrowable_faces(leg)
    out = [full]
    max_excluded = min(limit, len(narrowable), len(alive) - 1)
    for count in range(1, max_excluded + 1):
        for excluded in itertools.combinations(narrowable, count):
            keep = [face for face in alive if face not in excluded]
            out.append((_faces_str(keep), sum(float(fair[face]) for face in keep)))
    return out


def _c14_band(probability: float) -> str:
    if probability <= C14_CHEAP_LINE:
        return "cheap"
    if probability <= C14_VARIANCE_LINE:
        return "grey"
    return "variance"


def frontier_hash(legs: dict, *, channel: str, cap_yuan: int, mode: str) -> str:
    material = json.dumps(
        {"legs": legs, "channel": channel, "cap": cap_yuan, "mode": mode},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def third_order_key(point: dict) -> tuple:
    """Prefer equal-P points that full-cover the lowest-top1 match."""
    fulls = [match_no for match_no, faces in point["chosen"] if len(faces) == 3]
    lowest_top1_full = min((point["top1"][match_no] for match_no in fulls), default=1.0)
    return (-round(point["p_all"], 12), lowest_top1_full, point["chosen"])


def _candidate(legs: dict, chosen: tuple[tuple[str, str], ...], probability: float) -> dict:
    return {
        "p_all": probability,
        "chosen": chosen,
        "top1": {
            match_no: max(float(value) for value in legs[match_no]["fair"].values())
            for match_no, _faces in chosen
        },
    }


def enumerate_frontier(
    legs: dict[str, dict], *, channel: str, cap_yuan: int, mode: str
) -> dict:
    if channel not in ("renjiu", "shengfucai"):
        raise ValueError("channel must be renjiu or shengfucai")
    cap_notes = cap_yuan // 2
    ordered = sorted(legs, key=int)
    options = {match_no: cover_options(legs[match_no], mode=mode) for match_no in ordered}
    alive_sets = {match_no: _alive(legs[match_no]) for match_no in ordered}
    combos = (
        itertools.combinations(ordered, RENJIU_PICK)
        if channel == "renjiu"
        else [tuple(ordered)]
    )
    best_cells: dict[tuple[int, int], tuple[float, tuple[tuple[str, str], ...]]] = {}

    for combo in combos:
        states: dict[tuple[int, int], tuple[float, tuple[tuple[str, str], ...]]] = {
            (1, 0): (1.0, ())
        }
        for match_no in combo:
            next_states: dict[tuple[int, int], tuple[float, tuple[tuple[str, str], ...]]] = {}
            for (notes, narrowings), (probability, chosen) in states.items():
                for faces, coverage in options[match_no]:
                    cell = (
                        notes * len(faces),
                        narrowings + len(alive_sets[match_no]) - len(faces),
                    )
                    if cell[0] > cap_notes or cell[1] > TICKET_MAX_NARROWINGS:
                        continue
                    value = (probability * coverage, chosen + ((match_no, faces),))
                    current = next_states.get(cell)
                    if current is None or third_order_key(
                        _candidate(legs, value[1], value[0])
                    ) < third_order_key(_candidate(legs, current[1], current[0])):
                        next_states[cell] = value
            states = next_states
            if not states:
                break
        for cell, value in states.items():
            current = best_cells.get(cell)
            if current is None or third_order_key(
                _candidate(legs, value[1], value[0])
            ) < third_order_key(_candidate(legs, current[1], current[0])):
                best_cells[cell] = value

    points = []
    for (notes, _marks), (probability, chosen) in best_cells.items():
        shape = {
            "singles": sum(len(faces) == 1 for _, faces in chosen),
            "doubles": sum(len(faces) == 2 for _, faces in chosen),
            "fulls": sum(len(faces) == 3 for _, faces in chosen),
        }
        narrowings = []
        for match_no, faces in chosen:
            for face in alive_sets[match_no]:
                if DIGIT[face] in faces:
                    continue
                proof_doc = (legs[match_no].get("_d3") or {}).get(face)
                if proof_doc is None:
                    proof_doc = legs[match_no]["face_status"][face].get("proofs") or {}
                face_probability = float(legs[match_no]["fair"][face])
                narrowings.append(
                    {
                        "match_no": match_no,
                        "excluded_face": face,
                        "fair": face_probability,
                        "d3_count": sum(bool(proof_doc.get(key)) for key in ("a", "b", "c")),
                        "c14_band": _c14_band(face_probability),
                    }
                )
        candidate = _candidate(legs, chosen, probability)
        points.append(
            {
                "faces": dict(chosen),
                "chosen": chosen,
                "notes": notes,
                "stake_yuan": notes * 2,
                "p_all": probability,
                "shape": shape,
                "narrowings": narrowings,
                "top1": candidate["top1"],
            }
        )
    points.sort(key=third_order_key)
    for index, point in enumerate(points):
        point["k"] = index
        point.pop("chosen")
        point.pop("top1")
    return {
        "frontier_hash": frontier_hash(
            legs, channel=channel, cap_yuan=cap_yuan, mode=mode
        ),
        "channel": channel,
        "mode": mode,
        "cap_yuan": cap_yuan,
        "max_p": points[0]["p_all"] if points else None,
        "n_points": len(points),
        "points": points,
    }
