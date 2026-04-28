from __future__ import annotations

from datetime import UTC, datetime

import httpx

from nutmeg.agents.router import QueryIntent
from nutmeg.domain.analysis import (
    AnalysisEvidenceSummary,
    AnalysisJudgment,
    FixtureAnalysisResult,
)
from nutmeg.domain.fixtures import sample_fixtures


def _analysis() -> FixtureAnalysisResult:
    fixture = sample_fixtures('epl')[0]
    return FixtureAnalysisResult(
        fixture=fixture,
        intent=QueryIntent.DECISIONAL,
        query='Should I back Arsenal?',
        evidence=AnalysisEvidenceSummary(
            tactical_summary=['Arsenal can press high.'],
            snapshot_summary=['Arsenal squad edge'],
            odds_summary=['Market fair view leans Arsenal.'],
            market_shape_summary=['Market shape points to an open game.'],
            caveats=['Bookmaker disagreement is capped.'],
        ),
        judgment=AnalysisJudgment(
            verdict='Lean Arsenal pre-match.',
            core_reasons=['Arsenal can press high.'],
            counterargument='Spurs transition threat remains live.',
            confidence='medium',
        ),
        conflict_state='aligned',
        generated_at=datetime(2026, 4, 25, 12, tzinfo=UTC),
    )


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
        return httpx.Response(200, json={'output_text': '用 /brief epl-001 获取赛前简报。'})

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

    assert text == '用 /brief epl-001 获取赛前简报。'
    assert requests[0].url.path == '/responses'
    assert requests[0].headers['authorization'] == 'Bearer openai-secret'
    payload = json_from_request(requests[0])
    assert payload['model'] == 'gpt-5.5'
    assert '今天有哪些热门比赛？' in str(payload['input'])
    assert 'openai-secret' not in str(payload)


def test_portkey_synthesis_provider_posts_grounded_analysis_payload() -> None:
    from nutmeg.agents.llm_provider import PortkeySynthesisProvider

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'message': {
                            'content': 'Lean Arsenal pre-match. Confidence: medium. Pressing edge.'
                        }
                    }
                ]
            },
        )

    client = httpx.Client(base_url='https://portkey.test', transport=httpx.MockTransport(handler))
    provider = PortkeySynthesisProvider(
        base_url='https://portkey.test',
        api_key='demo-key',
        model='claude-test',
        client=client,
    )

    text = provider.synthesize(_analysis())

    assert text == 'Lean Arsenal pre-match. Confidence: medium. Pressing edge.'
    assert requests[0].url.path == '/chat/completions'
    assert requests[0].headers['authorization'] == 'Bearer demo-key'
    payload = json_from_request(requests[0])
    assert payload['model'] == 'claude-test'
    assert 'Lean Arsenal pre-match.' in payload['messages'][1]['content']
    assert 'Bookmaker disagreement is capped.' in payload['messages'][1]['content']


def test_portkey_synthesis_provider_raises_on_missing_text() -> None:
    from nutmeg.agents.llm_provider import PortkeySynthesisError, PortkeySynthesisProvider

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

    try:
        provider.synthesize(_analysis())
    except PortkeySynthesisError as exc:
        assert 'did not return synthesis text' in str(exc)
    else:  # pragma: no cover
        raise AssertionError('expected PortkeySynthesisError')


def json_from_request(request: httpx.Request) -> dict[str, object]:
    import json

    return json.loads(request.content.decode('utf-8'))
