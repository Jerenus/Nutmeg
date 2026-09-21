"""Pure, explicit per-world replay scoring for frozen structural tournaments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ReplayCellEvidence:
    trace_hash: str
    expected_trace_hash: str
    selected_evaluations: tuple[Mapping[str, object], ...]
    node_count: int
    rounds: int
    retries: int
    wall_seconds: str | None
    candidate_generation_count: int | None
    effective_parallelism: str | None
    failure_codes: tuple[str, ...] = ()
    branch_unavailable: bool = False
    permission_breach: bool = False
    protected_action: bool = False
    leakage: bool = False
    invalid_selected: bool = False
    unused_budget: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ScoredCell:
    score_vector: dict[str, object]
    disqualified: bool
    exclusion_reason: str | None


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid replay score value")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid replay score value") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("replay scores must be finite and nonnegative")
    return number


def score_replay(evidence: ReplayCellEvidence) -> ScoredCell:
    """Score only recorded evidence; unknown costs stay unknown."""
    safety_reason = next(
        (
            name
            for name in ("permission_breach", "protected_action", "leakage")
            if getattr(evidence, name)
        ),
        None,
    )
    reason = safety_reason
    if reason is None and evidence.trace_hash != evidence.expected_trace_hash:
        reason = "trace_hash_mismatch"
    if reason is None and evidence.invalid_selected:
        reason = "invalid_selected"

    bands: dict[str, Decimal] = {}
    eligible = Decimal(0)
    distinct = Decimal(0)
    try:
        for evaluation in evidence.selected_evaluations:
            eligible = max(eligible, _decimal(evaluation["eligible_band_count"]))
            distinct = max(distinct, _decimal(evaluation["distinct_valid_candidate_count_capped"]))
            probabilities = evaluation["best_objective_probability_by_band"]
            if not isinstance(probabilities, dict):
                raise ValueError("invalid band probability map")
            for band, value in probabilities.items():
                if not isinstance(band, str) or not band:
                    raise ValueError("invalid band label")
                if value is not None:
                    probability = _decimal(value)
                    if probability > 1:
                        raise ValueError("probability exceeds one")
                    bands[band] = max(bands.get(band, Decimal(0)), probability)
    except (KeyError, TypeError, ValueError):
        eligible = distinct = None
        bands = {}
        if reason is None:
            reason = "invalid_output"
    try:
        node_count = _decimal(evidence.node_count)
        rounds = _decimal(evidence.rounds)
        retries = _decimal(evidence.retries)
        wall_seconds = None if evidence.wall_seconds is None else _decimal(evidence.wall_seconds)
        generated = (
            None
            if evidence.candidate_generation_count is None
            else _decimal(evidence.candidate_generation_count)
        )
        parallel = (
            None
            if evidence.effective_parallelism is None
            else _decimal(evidence.effective_parallelism)
        )
    except (TypeError, ValueError):
        node_count = rounds = retries = wall_seconds = generated = parallel = None
        if reason is None:
            reason = "invalid_output"

    disqualified = reason is not None
    if reason is None and not evidence.selected_evaluations:
        reason = "branch_unavailable" if evidence.branch_unavailable else "no_solution"
    recovered = bool(evidence.selected_evaluations) and not disqualified
    score = {
        "invariant_violation_count": "1" if safety_reason else "0",
        "invalid_selected_count": "1" if evidence.invalid_selected else "0",
        "eligible_band_count": None if eligible is None else str(eligible),
        "best_objective_probability_by_band": {band: str(bands[band]) for band in sorted(bands)},
        "distinct_valid_candidate_count_capped": None if distinct is None else str(distinct),
        "failure_recovery_rate": "1" if recovered else "0",
        "node_count": None if node_count is None else str(node_count),
        "rounds": None if rounds is None else str(rounds),
        "retry_count": None if retries is None else str(retries),
        "wall_seconds": None if wall_seconds is None else str(wall_seconds),
        "candidate_generation_count": None if generated is None else str(generated),
        "effective_parallelism": None if parallel is None else str(parallel),
        "unused_budget": dict(evidence.unused_budget or {}),
        "failure_codes": list(evidence.failure_codes),
    }
    return ScoredCell(score, disqualified, reason)
