"""Deterministic comparison arithmetic for operator-supplied Zucai tickets.

The main loop supplies fair probabilities and candidate face sets. This module
validates that structure and compares it; it never generates or recommends a ticket.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
FAIR_KEYS = frozenset(FACE_KEYS.values())
FAIR_SUM_TOLERANCE = Decimal("0.001")


class OptimizerInputError(ValueError):
    """The supplied optimizer document does not satisfy its input contract."""


def _as_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise OptimizerInputError(f"{field} must be a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OptimizerInputError(f"{field} must be a number") from exc
    if not result.is_finite():
        raise OptimizerInputError(f"{field} must be finite")
    return result


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OptimizerInputError(f"{field} must be a positive integer")
    return value


def _sorted_faces(faces: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(faces.items(), key=lambda item: int(item[0]))


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OptimizerInputError("root must be an object")
    issue = payload.get("issue")
    if not isinstance(issue, str) or not issue.strip():
        raise OptimizerInputError("issue must be a non-empty string")

    price_per_note = _positive_int(payload.get("price_per_note", 2), field="price_per_note")
    budget = payload.get("budget_yuan")
    if budget is not None:
        budget = _positive_int(budget, field="budget_yuan")

    raw_fair = payload.get("fair")
    if not isinstance(raw_fair, dict) or not raw_fair:
        raise OptimizerInputError("fair must be a non-empty object")
    fair: dict[str, dict[str, Decimal]] = {}
    for match_no, raw_probabilities in raw_fair.items():
        if not isinstance(match_no, str) or not match_no.isdigit() or int(match_no) <= 0:
            raise OptimizerInputError(f"invalid fair match number: {match_no!r}")
        if not isinstance(raw_probabilities, dict) or set(raw_probabilities) != FAIR_KEYS:
            raise OptimizerInputError(
                f"fair[{match_no}] must contain exactly home/draw/away"
            )
        probabilities = {
            key: _as_decimal(value, field=f"fair[{match_no}].{key}")
            for key, value in raw_probabilities.items()
        }
        if any(value < 0 or value > 1 for value in probabilities.values()):
            raise OptimizerInputError(f"fair[{match_no}] values must be between 0 and 1")
        if abs(sum(probabilities.values(), Decimal(0)) - Decimal(1)) > FAIR_SUM_TOLERANCE:
            raise OptimizerInputError(f"fair[{match_no}] probabilities must sum to 1")
        fair[match_no] = probabilities

    raw_versions = payload.get("versions")
    if not isinstance(raw_versions, list) or not raw_versions:
        raise OptimizerInputError("versions must be a non-empty array")
    versions = []
    version_ids: set[str] = set()
    for position, raw_version in enumerate(raw_versions):
        if not isinstance(raw_version, dict):
            raise OptimizerInputError(f"versions[{position}] must be an object")
        version_id = raw_version.get("id")
        if not isinstance(version_id, str) or not version_id.strip():
            raise OptimizerInputError(f"versions[{position}].id must be a non-empty string")
        if version_id in version_ids:
            raise OptimizerInputError(f"duplicate version id: {version_id}")
        version_ids.add(version_id)

        raw_faces = raw_version.get("faces")
        if not isinstance(raw_faces, dict) or not raw_faces:
            raise OptimizerInputError(f"version {version_id} faces must be a non-empty object")
        faces: dict[str, str] = {}
        for match_no, selected in raw_faces.items():
            if match_no not in fair:
                raise OptimizerInputError(
                    f"version {version_id} references unknown fair match {match_no}"
                )
            if (
                not isinstance(selected, str)
                or not selected
                or any(face not in FACE_KEYS for face in selected)
                or len(set(selected)) != len(selected)
            ):
                raise OptimizerInputError(
                    f"version {version_id} match {match_no} faces must be unique 3/1/0"
                )
            faces[match_no] = selected
        versions.append({"id": version_id, "faces": faces})

    return {
        "issue": issue,
        "price_per_note": price_per_note,
        "budget_yuan": budget,
        "baseline_id": payload.get("baseline_id"),
        "fair": fair,
        "versions": versions,
        "groups": payload.get("groups", []),
    }


def _version_stats(
    version: dict[str, Any],
    fair: dict[str, dict[str, Decimal]],
    price_per_note: int,
) -> tuple[dict[str, Any], Decimal, Decimal]:
    probability = Decimal(1)
    expected_broken = Decimal(0)
    notes = 1
    ordered_faces = _sorted_faces(version["faces"])
    for match_no, faces in ordered_faces:
        coverage = sum((fair[match_no][FACE_KEYS[face]] for face in faces), Decimal(0))
        probability *= coverage
        expected_broken += Decimal(1) - coverage
        notes *= len(faces)
    result = {
        "id": version["id"],
        "faces": dict(ordered_faces),
        "notes": notes,
        "cost_yuan": notes * price_per_note,
        "p_all": float(probability),
        "expected_broken": float(expected_broken),
    }
    return result, probability, expected_broken


def optimize(payload: object) -> dict[str, Any]:
    """Validate and compare supplied candidates without making a betting decision."""
    data = _validate_payload(payload)
    versions = [
        _version_stats(version, data["fair"], data["price_per_note"])[0]
        for version in data["versions"]
    ]
    return {
        "issue": data["issue"],
        "price_per_note": data["price_per_note"],
        "budget_yuan": data["budget_yuan"],
        "versions": versions,
    }
