from __future__ import annotations

import httpx


def test_synthesis_provider_builder_is_default_off_without_flag_or_key() -> None:
    from nutmeg.agents.llm_provider import build_synthesis_provider
    from nutmeg.config.settings import AppSettings

    assert build_synthesis_provider(AppSettings()) is None
    assert build_synthesis_provider(AppSettings(agent_synthesis_enabled=True)) is None
    assert build_synthesis_provider(AppSettings(portkey_api_key='demo-key')) is None


def test_bot_fallback_provider_builder_is_default_off_without_flag_or_key(monkeypatch) -> None:
    from nutmeg.agents.llm_provider import build_bot_fallback_provider
    from nutmeg.config.settings import AppSettings

    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('NUTMEG_OPENAI_API_KEY', raising=False)

    assert build_bot_fallback_provider(AppSettings(_env_file=None)) is None
    assert (
        build_bot_fallback_provider(
            AppSettings(_env_file=None, bot_llm_fallback_enabled=True)
        )
        is None
    )
    assert (
        build_bot_fallback_provider(AppSettings(_env_file=None, openai_api_key='demo-key'))
        is None
    )


def test_openai_bot_fallback_provider_posts_responses_payload() -> None:
    from nutmeg.agents.llm_provider import OpenAiBotFallbackProvider

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={'output_text': '用 /renjiu 获取今天任九方案。'})

    client = httpx.Client(
        base_url='https://api.openai.test',
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAiBotFallbackProvider(
        base_url='https://api.openai.test',
        api_key='openai-secret',
        model='gpt-5.5',
        client=client,
    )

    text = provider.respond('今天有哪些热门比赛？')

    assert text == '用 /renjiu 获取今天任九方案。'
    assert requests[0].url.path == '/responses'
    assert requests[0].headers['authorization'] == 'Bearer openai-secret'
    payload = json_from_request(requests[0])
    assert payload['model'] == 'gpt-5.5'
    assert '今天有哪些热门比赛？' in str(payload['input'])
    assert 'openai-secret' not in str(payload)


def test_synthesis_provider_builder_returns_configured_portkey_client() -> None:
    from nutmeg.agents.llm_provider import PortkeySynthesisProvider, build_synthesis_provider
    from nutmeg.config.settings import AppSettings

    provider = build_synthesis_provider(
        AppSettings(
            _env_file=None,
            agent_synthesis_enabled=True,
            portkey_api_key='demo-key',
            anthropic_model='claude-test',
        )
    )

    assert isinstance(provider, PortkeySynthesisProvider)
    assert provider._model == 'claude-test'
    assert provider._api_key == 'demo-key'
    provider.close()


def test_portkey_synthesis_provider_extracts_chat_completion_text() -> None:
    from nutmeg.agents.llm_provider import PortkeySynthesisProvider

    client = httpx.Client(
        base_url='https://portkey.test',
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': []})),
    )
    provider = PortkeySynthesisProvider(
        base_url='https://portkey.test',
        api_key='demo-key',
        model='claude-test',
        client=client,
    )

    assert provider._extract_text({'choices': [{'message': {'content': ' hello '}}]}) == 'hello'
    assert provider._extract_text({'choices': [{'text': 'plain'}]}) == 'plain'
    assert provider._extract_text({'choices': []}) is None
    assert provider._extract_text('not-a-dict') is None


def json_from_request(request: httpx.Request) -> dict[str, object]:
    import json

    return json.loads(request.content.decode('utf-8'))
