"""Read-only behavior comparison; a signal is not a brake Action or winner."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from nutmeg.ontology.discovery.models import canonical_hash


@dataclass(frozen=True, slots=True)
class DriftSample:
    world_id: str
    stratum: str
    quality: float
    nodes: int
    rounds: int
    effective_parallelism: float
    failure_recovery: float
    solution_diversity: int
    invariant_code: str | None
    quality_vector: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class DriftReport:
    state: str
    comparison_hash: str
    metrics: dict[str, object]
    brake_code: str | None = None
    winner_id: None = None


def assess_drift(
    previous: tuple[DriftSample, ...],
    current: tuple[DriftSample, ...],
    *,
    min_samples: int = 3,
    material_quality_gain: float = 0.05,
    max_branch_growth_without_gain: float = 0.2,
    worst_stratum_max_decline: float = 0.1,
    registered_hard_invariants: tuple[str, ...] = (),
) -> DriftReport:
    if min_samples < 1 or material_quality_gain <= 0 or max_branch_growth_without_gain < 0:
        raise ValueError("invalid frozen drift limits")
    proof = canonical_hash(
        {
            "previous": [asdict(item) for item in previous],
            "current": [asdict(item) for item in current],
        }
    )
    codes = sorted(
        {
            item.invariant_code
            for item in current
            if item.invariant_code in registered_hard_invariants
        }
    )
    brake = codes[0] if codes else None
    if not previous or not current:
        return DriftReport("unavailable", proof, {}, brake)
    if len(previous) < min_samples or len(current) < min_samples:
        return DriftReport("insufficient_sample", proof, {}, brake)

    def average(items: tuple[DriftSample, ...], name: str) -> float:
        return sum(getattr(item, name) for item in items) / len(items)

    metric_names = (
        "quality",
        "nodes",
        "rounds",
        "effective_parallelism",
        "failure_recovery",
        "solution_diversity",
    )
    metrics: dict[str, object] = {
        name: {"previous": average(previous, name), "current": average(current, name)}
        for name in metric_names
    }
    old_strata = {item.stratum for item in previous}
    new_strata = {item.stratum for item in current}
    metrics["strata"] = {
        label: {
            "previous": average(
                tuple(item for item in previous if item.stratum == label), "quality"
            ),
            "current": average(tuple(item for item in current if item.stratum == label), "quality"),
        }
        for label in sorted(old_strata & new_strata)
    }
    if old_strata != new_strata:
        return DriftReport("insufficient_sample", proof, metrics, brake)
    old_quality = average(previous, "quality")
    new_quality = average(current, "quality")
    vector_gain = new_quality - old_quality >= material_quality_gain
    if all(item.quality_vector for item in (*previous, *current)):
        sizes = {len(item.quality_vector) for item in (*previous, *current)}
        if len(sizes) == 1:
            vector_gain = False
            for index in range(next(iter(sizes))):
                before = sum(item.quality_vector[index] for item in previous) / len(previous)
                after = sum(item.quality_vector[index] for item in current) / len(current)
                if before - after >= material_quality_gain:
                    break
                if after - before >= material_quality_gain:
                    vector_gain = True
                    break
    growth = (average(current, "nodes") - average(previous, "nodes")) / max(
        average(previous, "nodes"), 1
    )
    decline = any(
        pair["previous"] - pair["current"] > worst_stratum_max_decline
        for pair in metrics["strata"].values()
    )
    hold = decline or growth > max_branch_growth_without_gain and not vector_gain
    return DriftReport("hold_for_review" if hold else "observed", proof, metrics, brake)
