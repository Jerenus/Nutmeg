from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMCompletionError(RuntimeError):
    """Raised when the underlying LLM call fails or fake responses are exhausted."""


class LLMCompleter(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass(slots=True)
class FakeLLMCompleter:
    responses: list[str] = field(default_factory=list)

    def complete(self, *, system: str, user: str) -> str:
        if not self.responses:
            raise LLMCompletionError("FakeLLMCompleter responses exhausted")
        return self.responses.pop(0)
