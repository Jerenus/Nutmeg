from __future__ import annotations

import pytest

from nutmeg.services.psychology.signals.base import (
    SignalContext,
    SignalProvider,
    SignalProviderError,
)
from nutmeg.services.psychology.schemas import SignalReading


def test_signal_provider_is_protocol() -> None:
    class DummyProvider:
        name = "dummy"

        def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
            return []

    provider: SignalProvider = DummyProvider()
    assert provider.name == "dummy"
    assert provider.evaluate(SignalContext(date="2026-04-29", fixtures=[], snapshots={}, odds={})) == []


def test_signal_context_is_immutable() -> None:
    ctx = SignalContext(date="2026-04-29", fixtures=[], snapshots={}, odds={})
    with pytest.raises(Exception):
        ctx.date = "2026-04-30"  # type: ignore[misc]


def test_signal_provider_error_inherits_runtime() -> None:
    err = SignalProviderError("boom")
    assert isinstance(err, RuntimeError)
