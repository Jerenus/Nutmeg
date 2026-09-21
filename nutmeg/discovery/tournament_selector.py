"""Deterministic safety-first comparison of complete frozen tournament matrices."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.selection_contract import FieldComparator, SelectionContract
from nutmeg.ontology.discovery.models import canonical_hash


@dataclass(frozen=True, slots=True)
class SelectionCell:
    policy_revision_id: str
    world_id: str
    pool_role: str
    strata: tuple[str, ...]
    score_vector: Mapping[str, object]
    disqualified: bool
    exclusion_reason: str | None
    trace_hash: str


@dataclass(frozen=True, slots=True)
class SelectionResult:
    winner_policy_revision_id: str
    proof_hash: str
    disqualification_reasons: dict[str, str]
    comparison_reasons: dict[str, str]


def _number(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _metric(cells: tuple[SelectionCell, ...], field: str) -> Decimal | dict[str, Decimal] | None:
    values = [cell.score_vector.get(field) for cell in cells]
    if not values or any(value is None for value in values):
        return None
    if field == "best_objective_probability_by_band":
        if any(not isinstance(value, dict) for value in values):
            return None
        bands = set().union(*(value.keys() for value in values))
        if not bands or any(set(value) != bands for value in values):
            return None
        output: dict[str, Decimal] = {}
        for band in sorted(bands):
            numbers = [_number(value[band]) for value in values]
            if any(item is None for item in numbers):
                return None
            output[band] = sum(numbers) / len(numbers)
        return output
    numbers = [_number(value) for value in values]
    if any(item is None for item in numbers):
        return None
    return sum(numbers) / len(numbers)


def summarize_strata(
    contract: SelectionContract, cells: tuple[SelectionCell, ...]
) -> dict[str, dict[str, dict[str, str | dict[str, str] | None]]]:
    quality = next(tier for tier in contract.within_tier if tier.tier == "discovery_quality")
    summary = {}
    for label in sorted({label for cell in cells for label in cell.strata}):
        summary[label] = {}
        for policy_id in sorted({cell.policy_revision_id for cell in cells}):
            scoped = tuple(
                cell
                for cell in cells
                if cell.policy_revision_id == policy_id and label in cell.strata
            )
            metrics = {}
            for field in quality.fields:
                value = _metric(scoped, field.name)
                metrics[field.name] = (
                    {band: str(number) for band, number in value.items()}
                    if isinstance(value, dict)
                    else str(value)
                    if value is not None
                    else None
                )
            summary[label][policy_id] = metrics
    return summary


def _compare(
    incumbent: Decimal | dict[str, Decimal] | None,
    challenger: Decimal | dict[str, Decimal] | None,
    field: FieldComparator,
) -> int:
    if challenger is None:
        return -1 if incumbent is not None else 0
    if incumbent is None:
        return 0  # Missing incumbent evidence cannot certify a promotion.
    if isinstance(incumbent, dict) or isinstance(challenger, dict):
        if not isinstance(incumbent, dict) or not isinstance(challenger, dict):
            return -1
        if set(incumbent) != set(challenger):
            return -1
        deltas = tuple(
            (challenger[key] - incumbent[key]) * (1 if field.direction == "max" else -1)
            for key in sorted(incumbent)
        )
        if any(delta < 0 for delta in deltas):
            return -1
        return 1 if any(delta >= field.materiality and delta > 0 for delta in deltas) else 0
    delta = (challenger - incumbent) * (1 if field.direction == "max" else -1)
    if delta < 0:
        return -1
    return 1 if delta >= field.materiality and delta > 0 else 0


def _role_cells(
    cells: tuple[SelectionCell, ...], policy_id: str, role: str
) -> tuple[SelectionCell, ...]:
    return tuple(
        cell for cell in cells if cell.policy_revision_id == policy_id and cell.pool_role == role
    )


def _wins_role(
    contract: SelectionContract,
    incumbent: tuple[SelectionCell, ...],
    challenger: tuple[SelectionCell, ...],
) -> bool:
    for tier in contract.within_tier:
        for field in tier.fields:
            comparison = _compare(
                _metric(incumbent, field.name), _metric(challenger, field.name), field
            )
            if comparison < 0:
                return False
            if comparison > 0:
                return True
    return False


def _no_worse_role(
    contract: SelectionContract,
    baseline: tuple[SelectionCell, ...],
    challenger: tuple[SelectionCell, ...],
) -> bool:
    return all(
        _compare(_metric(baseline, field.name), _metric(challenger, field.name), field) >= 0
        for tier in contract.within_tier
        for field in tier.fields
    )


def _worst_stratum_safe(
    contract: SelectionContract,
    cells: tuple[SelectionCell, ...],
    incumbent_id: str,
    challenger_id: str,
) -> bool:
    quality = next(tier for tier in contract.within_tier if tier.tier == "discovery_quality")
    for label in contract.worst_stratum.strata:
        baseline = tuple(
            cell
            for cell in cells
            if cell.policy_revision_id == incumbent_id and label in cell.strata
        )
        challenger = tuple(
            cell
            for cell in cells
            if cell.policy_revision_id == challenger_id and label in cell.strata
        )
        if not baseline:
            continue
        for field in quality.fields:
            left = _metric(baseline, field.name)
            right = _metric(challenger, field.name)
            if left is None or right is None:
                return False
            if isinstance(left, dict) and isinstance(right, dict):
                if set(left) != set(right) or any(
                    right[key] + contract.worst_stratum.max_decline < left[key] for key in left
                ):
                    return False
            elif isinstance(left, Decimal) and isinstance(right, Decimal):
                if right + contract.worst_stratum.max_decline < left:
                    return False
            else:
                return False
    return True


def select_winner(
    contract: SelectionContract,
    incumbent_policy_revision_id: str,
    candidate_ids: tuple[str, ...],
    cells: tuple[SelectionCell, ...],
) -> SelectionResult:
    if (
        not candidate_ids
        or incumbent_policy_revision_id not in candidate_ids
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise ValueError("tournament requires one registered incumbent")
    world_roles: dict[str, str] = {}
    world_strata: dict[str, tuple[str, ...]] = {}
    for cell in cells:
        if cell.pool_role not in {"development", "holdout"} or (
            cell.world_id in world_roles and world_roles[cell.world_id] != cell.pool_role
        ):
            raise ValueError("tournament matrix has invalid world role")
        if cell.world_id in world_strata and world_strata[cell.world_id] != cell.strata:
            raise ValueError("tournament matrix world strata differ across policies")
        world_roles[cell.world_id] = cell.pool_role
        world_strata[cell.world_id] = cell.strata
    expected = {(policy, world) for policy in candidate_ids for world in world_roles}
    actual = {(cell.policy_revision_id, cell.world_id) for cell in cells}
    if (
        actual != expected
        or len(cells) != len(expected)
        or set(world_roles.values()) != {"development", "holdout"}
    ):
        raise ValueError("tournament requires complete development/holdout matrix")
    ordered = tuple(sorted(cells, key=lambda item: (item.policy_revision_id, item.world_id)))
    disqualified: dict[str, str] = {}
    comparisons: dict[str, str] = {}
    for policy_id in candidate_ids:
        safety = next(
            (
                cell
                for cell in ordered
                if cell.policy_revision_id == policy_id
                and (
                    (value := _number(cell.score_vector.get("invariant_violation_count"))) is None
                    or value > 0
                )
            ),
            None,
        )
        if safety is not None:
            disqualified[policy_id] = "safety_isolation"
            continue
        validity = next(
            (
                cell
                for cell in ordered
                if cell.policy_revision_id == policy_id
                and (
                    (value := _number(cell.score_vector.get("invalid_selected_count"))) is None
                    or value > 0
                )
            ),
            None,
        )
        if validity is not None:
            disqualified[policy_id] = "invalid_selected"
            continue
        invalid = next(
            (
                cell
                for cell in ordered
                if cell.policy_revision_id == policy_id and cell.disqualified
            ),
            None,
        )
        if invalid is not None:
            disqualified[policy_id] = invalid.exclusion_reason or "disqualified"
    if incumbent_policy_revision_id in disqualified:
        raise ValueError("incumbent is disqualified; tournament cannot select a winner")
    winner = incumbent_policy_revision_id
    for candidate_id in sorted(set(candidate_ids) - {incumbent_policy_revision_id}):
        if candidate_id in disqualified:
            continue
        incumbent_dev = _role_cells(ordered, incumbent_policy_revision_id, "development")
        candidate_dev = _role_cells(ordered, candidate_id, "development")
        incumbent_hold = _role_cells(ordered, incumbent_policy_revision_id, "holdout")
        candidate_hold = _role_cells(ordered, candidate_id, "holdout")
        if not _wins_role(contract, incumbent_dev, candidate_dev):
            comparisons[candidate_id] = "development_not_materially_better"
        elif not _worst_stratum_safe(contract, ordered, incumbent_policy_revision_id, candidate_id):
            comparisons[candidate_id] = "worst_stratum_decline"
        elif not _wins_role(contract, incumbent_hold, candidate_hold):
            comparisons[candidate_id] = "holdout_not_materially_better"
        else:
            current_dev = _role_cells(ordered, winner, "development")
            current_hold = _role_cells(ordered, winner, "holdout")
            if winner == incumbent_policy_revision_id or (
                _wins_role(contract, current_dev, candidate_dev)
                and _no_worse_role(contract, current_hold, candidate_hold)
            ):
                winner = candidate_id
                comparisons[candidate_id] = "selected"
            else:
                comparisons[candidate_id] = "outperformed_by_challenger"
    proof = canonical_hash(
        {
            "selection_contract_hash": contract_hash(contract),
            "incumbent_policy_revision_id": incumbent_policy_revision_id,
            "candidate_ids": sorted(candidate_ids),
            "cells": [asdict(cell) for cell in ordered],
            "winner_policy_revision_id": winner,
            "disqualification_reasons": disqualified,
            "comparison_reasons": comparisons,
        }
    )
    return SelectionResult(winner, proof, disqualified, comparisons)
