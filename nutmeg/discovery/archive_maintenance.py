"""Deterministic, read-only archive proposals; D4 remains the decision authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nutmeg.discovery.contracts import load_pilot_contract


@dataclass(frozen=True, slots=True)
class ArchivePolicy:
    policy_revision_id: str
    lineage_id: str
    actions: frozenset[str]
    eligible: bool
    parent_registered: bool


@dataclass(frozen=True, slots=True)
class ArchiveProposal:
    winner_id: str
    admit_ids: tuple[str, ...]
    evict_ids: tuple[str, ...]


def propose_archive(
    existing: tuple[ArchivePolicy, ...],
    candidates: tuple[ArchivePolicy, ...],
    *,
    winner_id: str,
) -> ArchiveProposal:
    pilot = load_pilot_contract(
        Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    capacity = pilot.archive.capacity
    max_per_lineage = pilot.archive.max_per_lineage
    minimum_action_jaccard_distance = pilot.archive.minimum_action_jaccard_distance
    if len(existing) > capacity or len({item.policy_revision_id for item in existing}) != len(
        existing
    ):
        raise ValueError("existing archive exceeds frozen capacity or has duplicates")
    retained = list(existing)
    evicted: list[str] = []
    admitted: list[str] = []
    for candidate in sorted(candidates, key=lambda item: item.policy_revision_id):
        if not candidate.eligible or not candidate.actions:
            raise ValueError("only eligible reproducible policies can enter archive")
        if not candidate.parent_registered:
            raise ValueError("archive candidate needs a registered parent")
        if candidate.policy_revision_id == winner_id:
            raise ValueError("winner cannot be admitted as stepping stone")
        if candidate.policy_revision_id in {item.policy_revision_id for item in retained}:
            raise ValueError("duplicate archive admission")
        if sum(item.lineage_id == candidate.lineage_id for item in retained) >= max_per_lineage:
            raise ValueError("archive per-lineage cap exceeded")
        for item in retained:
            distance = 1 - len(item.actions & candidate.actions) / len(
                item.actions | candidate.actions
            )
            if distance < minimum_action_jaccard_distance:
                raise ValueError("archive action distance below frozen minimum")
        if len(retained) >= capacity:
            clones = sorted(
                (item for item in retained if item.actions < candidate.actions),
                key=lambda item: item.policy_revision_id,
            )
            # Retain unique stepping stones; without a dominated clone there is no
            # evidence-based automatic eviction proposal.
            if not clones:
                raise ValueError("archive full without dominated clone")
            victim = clones[0]
            retained.remove(victim)
            evicted.append(victim.policy_revision_id)
        retained.append(candidate)
        admitted.append(candidate.policy_revision_id)
    return ArchiveProposal(winner_id, tuple(admitted), tuple(evicted))
