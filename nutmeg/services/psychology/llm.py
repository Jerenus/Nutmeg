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


@dataclass(slots=True)
class PortkeyLLMCompleter:
    """Production LLMCompleter wrapping PortkeySynthesisProvider."""

    portkey_provider: object

    def complete(self, *, system: str, user: str) -> str:
        try:
            text = self.portkey_provider._complete_raw(system=system, user=user)  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise LLMCompletionError("Portkey provider lacks _complete_raw") from exc
        except Exception as exc:  # noqa: BLE001 - normalize provider exceptions
            raise LLMCompletionError(str(exc)) from exc
        return str(text)
