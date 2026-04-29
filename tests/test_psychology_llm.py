from __future__ import annotations

from nutmeg.services.psychology.llm import FakeLLMCompleter, LLMCompleter, LLMCompletionError


def test_fake_completer_returns_canned_response() -> None:
    fake = FakeLLMCompleter(responses=["abc"])
    assert fake.complete(system="s", user="u") == "abc"


def test_fake_completer_pops_responses_in_order() -> None:
    fake = FakeLLMCompleter(responses=["one", "two"])
    assert fake.complete(system="", user="") == "one"
    assert fake.complete(system="", user="") == "two"


def test_fake_completer_raises_when_exhausted() -> None:
    fake = FakeLLMCompleter(responses=[])
    try:
        fake.complete(system="", user="")
    except LLMCompletionError as exc:
        assert "exhausted" in str(exc)
    else:
        raise AssertionError("expected LLMCompletionError")


def test_protocol_is_satisfied_by_callable_wrapper() -> None:
    class Direct:
        def complete(self, *, system: str, user: str) -> str:
            return system + user

    completer: LLMCompleter = Direct()
    assert completer.complete(system="a", user="b") == "ab"
