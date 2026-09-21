"""Closed, pure structural-candidate continuation with frozen audit semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic_ns
from typing import Callable

from nutmeg.discovery.contracts import PilotContract
from nutmeg.discovery.online_inputs import StructuralInputSnapshot, snapshot_payload
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.product.operator_candidates import (
    BandCandidateGenerationResult,
    CandidateSpaceLimitError,
    enumerate_band_candidates,
)
from nutmeg.product.operator_workers import _audit_candidate


@dataclass(frozen=True, slots=True)
class ShardExecution:
    template_ids: tuple[str, ...]
    status: str
    artifact_manifest: dict[str, object]
    artifact_hash: str
    diagnostic_codes: tuple[str, ...]
    resource_cost: dict[str, int | None]
    evaluation: dict[str, object] | None
    selectable: bool


def execute_template_shard(
    snapshot: StructuralInputSnapshot,
    template_ids: tuple[str, ...],
    *,
    pilot: PilotContract | None = None,
    enumerate_fn: Callable = enumerate_band_candidates,
    max_wall_seconds: int | None = None,
    candidate_count_limit: int | None = None,
) -> ShardExecution:
    if not template_ids or len(set(template_ids)) != len(template_ids):
        raise ValueError("template shard must be unique and nonempty")
    if not set(template_ids).issubset(snapshot.template_ids):
        raise ValueError("unregistered template shard")
    if canonical_hash(snapshot_payload(snapshot)) != snapshot.manifest_hash:
        raise ValueError("snapshot manifest hash mismatch")
    if not snapshot.audit_offers:
        raise ValueError("frozen audit context is missing")
    if candidate_count_limit is not None and candidate_count_limit < 1:
        raise ValueError("candidate count limit must be positive")
    from pathlib import Path

    from nutmeg.discovery.contracts import load_pilot_contract

    contract = pilot or load_pilot_contract(
        Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    inputs = replace(
        snapshot.candidate_input,
        templates=tuple(
            template
            for template in snapshot.candidate_input.templates
            if template.structure_code in template_ids
        ),
        maximum_exhaustive_candidate_count=min(
            snapshot.candidate_input.maximum_exhaustive_candidate_count,
            contract.budgets.max_candidate_generation_count,
            candidate_count_limit or contract.budgets.max_candidate_generation_count,
        ),
    )
    started = monotonic_ns()
    status = "failed"
    diagnostics: tuple[str, ...] = ()
    evaluation = None
    selectable = False
    generated_count: int | None = None
    payload: dict[str, object] = {
        "snapshot_hash": snapshot.manifest_hash,
        "template_ids": template_ids,
    }
    try:
        result = enumerate_fn(
            inputs,
            set_kind="judgment_bound",
            generator_version="operator-candidate-v2-bands",
            audit_candidate=lambda draft: _audit_candidate(
                draft,
                lane=inputs.lane,
                offers=snapshot.audit_offers,
                capital_cap_minor=inputs.capital_cap_minor,
            ),
        )
        if not isinstance(result, BandCandidateGenerationResult):
            raise ValueError("candidate generation result is invalid")
        generated_count = result.calculated_candidate_count
        if any(
            len(band.candidates) > contract.evaluator.candidate_count_cap_per_band
            for band in result.by_band.values()
        ):
            status, diagnostics = "failed", ("over_cap",)
        else:
            selectable_candidates = tuple(
                item
                for item in result.candidates
                if item.deployable
                and not any(finding.severity == "ERROR" for finding in item.audit_findings)
            )
            selectable = bool(selectable_candidates)
            valid_hashes = {item.content_hash for item in selectable_candidates}
            status = "complete" if selectable else "no_solution"
            diagnostics = () if selectable else ("no_feasible_candidate",)
            evaluation = {
                "eligible_band_count": sum(
                    any(item.content_hash in valid_hashes for item in band.candidates)
                    for band in result.by_band.values()
                ),
                "best_objective_probability_by_band": {
                    band: max(
                        (
                            item.objective_probability_decimal
                            for item in outcome.candidates
                            if item.content_hash in valid_hashes
                        ),
                        default=None,
                    )
                    for band, outcome in sorted(result.by_band.items())
                },
                "distinct_valid_candidate_count_capped": min(
                    len(selectable_candidates), contract.evaluator.candidate_count_cap_per_band
                ),
            }
            payload["candidate_hashes"] = [item.content_hash for item in result.candidates]
            payload["band_status"] = {
                band: outcome.status for band, outcome in sorted(result.by_band.items())
            }
    except CandidateSpaceLimitError:
        diagnostics = ("candidate_space_over_cap",)
    except Exception as exc:
        diagnostics = ("adapter_error", type(exc).__name__)

    elapsed_ms = max(0, (monotonic_ns() - started) // 1_000_000)
    if max_wall_seconds is not None and elapsed_ms > max_wall_seconds * 1000:
        status, diagnostics, selectable = "failed", ("timeout",), False
        evaluation = None
    payload["status"] = status
    payload["diagnostic_codes"] = diagnostics
    content_hash = canonical_hash(payload)
    return ShardExecution(
        template_ids=template_ids,
        status=status,
        artifact_manifest={**payload, "content_hash": content_hash},
        artifact_hash=content_hash,
        diagnostic_codes=diagnostics,
        resource_cost={"wall_ms": elapsed_ms, "candidate_generation_count": generated_count},
        evaluation=evaluation,
        selectable=selectable,
    )
