from __future__ import annotations

from dataclasses import asdict

import pytest

from nutmeg.agents.router import QueryIntent
from nutmeg.agents.workflow import MatchAnalysisAgentResult
from nutmeg.domain.analysis import AnalysisEvidenceSummary, AnalysisJudgment, FixtureAnalysisResult
from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.interfaces.bot.adapter import BotAdapter, UnsupportedBotCommandError, parse_bot_message


def test_parse_bot_message_supports_brief_command() -> None:
    command = parse_bot_message('/brief epl-001 Should I back Arsenal?')

    assert command.name == 'brief'
    assert command.fixture_id == 'epl-001'
    assert command.query == 'Should I back Arsenal?'
    assert command.raw_text == '/brief epl-001 Should I back Arsenal?'


def test_parse_bot_message_rejects_unsupported_or_incomplete_messages() -> None:
    with pytest.raises(UnsupportedBotCommandError, match='Unsupported bot command'):
        parse_bot_message('/odds epl-001')
    with pytest.raises(UnsupportedBotCommandError, match='requires a fixture id and query'):
        parse_bot_message('/brief epl-001')


def test_bot_adapter_renders_match_brief_response() -> None:
    fixture = sample_fixtures('epl')[0]

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status='succeeded',
                nodes=['classify_intent', 'analyze_match', 'synthesize_result'],
                executor='deterministic',
                generated_synthesis='Lean Arsenal pre-match. Confidence: medium.',
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=['Arsenal can press high.'],
                        snapshot_summary=['Arsenal squad edge.'],
                        odds_summary=['Market fair view leans Arsenal.'],
                        market_shape_summary=[],
                        caveats=['Derby variance remains elevated.'],
                    ),
                    judgment=AnalysisJudgment(
                        verdict='Lean Arsenal pre-match.',
                        core_reasons=['Pressing edge'],
                        counterargument='Tottenham transition threat remains live.',
                        confidence='medium',
                    ),
                    conflict_state='aligned',
                    generated_at=fixture.kickoff_at,
                ),
            )

    adapter = BotAdapter(workflow=StubWorkflow())
    response = adapter.handle_message('/brief epl-001 Should I back Arsenal?')

    assert response.status == 'succeeded'
    assert 'Arsenal vs Tottenham Hotspur' in response.text
    assert 'Lean Arsenal pre-match.' in response.text
    assert 'Confidence: medium' in response.text
    assert 'Pressing edge' in response.text
    assert 'Derby variance remains elevated.' in response.text
    assert 'classify_intent -> analyze_match -> synthesize_result' in response.text
    assert response.payload['fixture_id'] == 'epl-001'


def test_bot_adapter_returns_failure_response_for_workflow_errors() -> None:
    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status='failed',
                nodes=['classify_intent', 'analyze_match'],
                error='Not enough evidence for a direct call.',
            )

    response = BotAdapter(workflow=StubWorkflow()).handle_message(
        '/brief epl-001 Should I back Arsenal?'
    )

    assert response.status == 'failed'
    assert response.error == 'Not enough evidence for a direct call.'
    assert 'Not enough evidence for a direct call.' in response.text
    assert asdict(response)['payload']['sections'] == {}


def test_bot_adapter_uses_fallback_for_unsupported_natural_language() -> None:
    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):  # pragma: no cover
            raise AssertionError('workflow should not run for unsupported natural language')

    class StubFallback:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def respond(self, message: str, *, error: str | None = None) -> str:
            self.calls.append((message, error))
            return '今晚优先看热门比赛列表，然后用 /brief fixture_id 提问。'

    fallback = StubFallback()
    response = BotAdapter(workflow=StubWorkflow(), fallback_provider=fallback).handle_message(
        '今天有哪些热门比赛？'
    )

    assert response.status == 'succeeded'
    assert '热门比赛列表' in response.text
    assert response.payload['mode'] == 'llm_fallback'
    assert fallback.calls == [
        (
            '今天有哪些热门比赛？',
            'Unsupported bot command. Try `/brief <fixture_id> <query>`.',
        )
    ]


def test_bot_adapter_start_returns_deterministic_help_without_fallback() -> None:
    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):  # pragma: no cover
            raise AssertionError('workflow should not run for /start')

    response = BotAdapter(workflow=StubWorkflow()).handle_message('/start')

    assert response.status == 'succeeded'
    assert '/brief <fixture_id> <query>' in response.text
    assert 'popular-matches' in response.text
    assert 'telegram-bot-run' in response.text
    assert response.payload['mode'] == 'help'
