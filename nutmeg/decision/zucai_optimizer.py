"""Deterministic comparison arithmetic for operator-supplied Zucai tickets.

The main loop supplies fair probabilities and candidate face sets. This module
validates that structure and compares it; it never generates or recommends a ticket.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import combinations
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


def _coverage(probabilities: dict[str, Decimal], faces: set[str]) -> Decimal:
    if faces == set(FACE_KEYS):
        return Decimal(1)
    return sum((probabilities[FACE_KEYS[face]] for face in faces), Decimal(0))


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

    baseline_id = payload.get("baseline_id")
    if baseline_id is not None and baseline_id not in version_ids:
        raise OptimizerInputError(f"unknown baseline_id: {baseline_id}")

    raw_groups = payload.get("groups", [])
    if not isinstance(raw_groups, list):
        raise OptimizerInputError("groups must be an array")
    groups = []
    group_ids: set[str] = set()
    for position, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise OptimizerInputError(f"groups[{position}] must be an object")
        group_id = raw_group.get("id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise OptimizerInputError(f"groups[{position}].id must be a non-empty string")
        if group_id in group_ids:
            raise OptimizerInputError(f"duplicate group id: {group_id}")
        group_ids.add(group_id)
        members = raw_group.get("version_ids")
        if not isinstance(members, list) or not members:
            raise OptimizerInputError(f"group {group_id} version_ids must be a non-empty array")
        if any(not isinstance(member, str) for member in members):
            raise OptimizerInputError(f"group {group_id} version_ids must be strings")
        if len(set(members)) != len(members):
            raise OptimizerInputError(f"group {group_id} has duplicate version_ids")
        unknown = [member for member in members if member not in version_ids]
        if unknown:
            raise OptimizerInputError(f"group {group_id} references unknown versions: {unknown}")
        groups.append({"id": group_id, "version_ids": members})

    return {
        "issue": issue,
        "price_per_note": price_per_note,
        "budget_yuan": budget,
        "baseline_id": baseline_id,
        "fair": fair,
        "versions": versions,
        "groups": groups,
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
        coverage = _coverage(fair[match_no], set(faces))
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


def _intersection_probability(
    versions: tuple[dict[str, Any], ...],
    fair: dict[str, dict[str, Decimal]],
) -> Decimal:
    probability = Decimal(1)
    match_nos = set().union(*(version["faces"] for version in versions))
    for match_no in match_nos:
        constraints = [
            set(version["faces"][match_no])
            for version in versions
            if match_no in version["faces"]
        ]
        allowed = set.intersection(*constraints)
        if not allowed:
            return Decimal(0)
        coverage = _coverage(fair[match_no], allowed)
        probability *= coverage
    return probability


def _group_stats(
    group: dict[str, Any],
    versions_by_id: dict[str, dict[str, Any]],
    fair: dict[str, dict[str, Decimal]],
) -> dict[str, Any]:
    members = [versions_by_id[version_id] for version_id in group["version_ids"]]
    probability = Decimal(0)
    for size in range(1, len(members) + 1):
        sign = 1 if size % 2 else -1
        for subset in combinations(members, size):
            probability += sign * _intersection_probability(subset, fair)

    common_matches = set.intersection(*(set(member["faces"]) for member in members))
    common_dead_faces = []
    for match_no in sorted(common_matches, key=int):
        covered = set().union(*(set(member["faces"][match_no]) for member in members))
        dead = "".join(face for face in FACE_KEYS if face not in covered)
        if dead:
            common_dead_faces.append({"match_no": match_no, "faces": dead})
    return {
        "id": group["id"],
        "version_ids": group["version_ids"],
        "p_any_all": float(probability),
        "common_dead_faces": common_dead_faces,
    }


def optimize(payload: object) -> dict[str, Any]:
    """Validate and compare supplied candidates without making a betting decision."""
    data = _validate_payload(payload)
    calculated = [
        _version_stats(version, data["fair"], data["price_per_note"])
        for version in data["versions"]
    ]
    internal = {
        public["id"]: (public, probability, expected_broken)
        for public, probability, expected_broken in calculated
    }
    baseline = internal.get(data["baseline_id"])
    for public, probability, expected_broken in calculated:
        public["within_cap"] = (
            None
            if data["budget_yuan"] is None
            else public["cost_yuan"] <= data["budget_yuan"]
        )
        if baseline is not None:
            baseline_public, baseline_probability, baseline_broken = baseline
            public["delta_vs_baseline"] = {
                "notes": public["notes"] - baseline_public["notes"],
                "cost_yuan": public["cost_yuan"] - baseline_public["cost_yuan"],
                "p_all_pp": float((probability - baseline_probability) * 100),
                "expected_broken": float(expected_broken - baseline_broken),
            }

    candidates = [
        item
        for item in calculated
        if data["budget_yuan"] is None or item[0]["within_cap"]
    ]
    candidates.sort(key=lambda item: (-item[1], item[0]["cost_yuan"], item[0]["id"]))
    ranking = [item[0]["id"] for item in candidates]
    versions_by_id = {version["id"]: version for version in data["versions"]}
    groups = [
        _group_stats(group, versions_by_id, data["fair"])
        for group in data["groups"]
    ]
    return {
        "issue": data["issue"],
        "price_per_note": data["price_per_note"],
        "budget_yuan": data["budget_yuan"],
        "baseline_id": data["baseline_id"],
        "versions": [item[0] for item in calculated],
        "ranking": ranking,
        "best_within_cap_id": ranking[0] if ranking else None,
        "groups": groups,
    }
