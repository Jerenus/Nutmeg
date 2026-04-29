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


def test_portkey_completer_uses_existing_provider_client_without_raw_method() -> None:
    from types import SimpleNamespace

    from nutmeg.services.psychology.llm import PortkeyLLMCompleter

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": " psychology json "}}]}

    class Client:
        def __init__(self) -> None:
            self.posts: list[dict] = []

        def post(self, path: str, *, headers: dict, json: dict) -> Response:
            self.posts.append({"path": path, "headers": headers, "json": json})
            return Response()

    client = Client()
    provider = SimpleNamespace(
        _api_key="pk-test",
        _model="model-test",
        _client=client,
        _extract_text=lambda payload: payload["choices"][0]["message"]["content"].strip(),
    )

    text = PortkeyLLMCompleter(portkey_provider=provider).complete(system="sys", user="usr")

    assert text == "psychology json"
    assert client.posts[0]["path"] == "/chat/completions"
    assert client.posts[0]["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
