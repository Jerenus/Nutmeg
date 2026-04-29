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
            response = self.portkey_provider._client.post(  # type: ignore[attr-defined]
                "/chat/completions",
                headers={
                    "authorization": f"Bearer {self.portkey_provider._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self.portkey_provider._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
            text = self.portkey_provider._extract_text(response.json())
        except AttributeError as exc:
            raise LLMCompletionError("Portkey provider lacks raw completion internals") from exc
        except Exception as exc:  # noqa: BLE001 - normalize provider exceptions
            raise LLMCompletionError(str(exc)) from exc
        if not text:
            raise LLMCompletionError("Portkey provider returned no text")
        return str(text)
