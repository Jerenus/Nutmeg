from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from nutmeg.services.psychology.schemas import SignalReading


class SignalProviderError(RuntimeError):
    """Raised when a signal provider fails irrecoverably."""


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Bundle of inputs every provider receives. Providers ignore unused fields."""

    date: str
    fixtures: list[dict[str, Any]]
    snapshots: dict[str, dict[str, Any]]
    odds: dict[str, dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SignalProvider(Protocol):
    name: str

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        """Return one or more readings, degrading partial-source failures to abstain."""
