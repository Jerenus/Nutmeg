from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.schemas import OverrideCandidate


@dataclass(slots=True)
class ConvictionGate:
    threshold: float = 0.7

    def apply(self, candidates: list[OverrideCandidate]) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        accepted: list[OverrideCandidate] = []
        rejected: list[tuple[OverrideCandidate, str]] = []
        for candidate in candidates:
            if candidate.conviction >= self.threshold:
                accepted.append(candidate)
            else:
                rejected.append((candidate, f"below_conviction({candidate.conviction:.2f}<{self.threshold:.2f})"))
        return accepted, rejected


@dataclass(slots=True)
class BudgetGuard:
    max_reversals: int = 1

    def apply(self, candidates: list[OverrideCandidate]) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        ranked = sorted(candidates, key=lambda candidate: candidate.conviction, reverse=True)
        accepted = ranked[: self.max_reversals]
        rejected = [(candidate, "budget_exhausted") for candidate in ranked[self.max_reversals :]]
        return accepted, rejected
