from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.agents.router import QueryIntent
from nutmeg.domain.analysis import (
    AnalysisEvidenceSummary,
    AnalysisJudgment,
    FixtureAnalysisResult,
)
from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.services.analysis import InsufficientEvidenceError


class StubAnalysisService:
    def analyze_match(self, fixture_id: str, *, query: str):
        fixture = sample_fixtures('epl')[0]
        return FixtureAnalysisResult(
            fixture=fixture,
            intent=QueryIntent.DECISIONAL,
            query=query,
            evidence=AnalysisEvidenceSummary(
                tactical_summary=['Arsenal can press high.'],
                snapshot_summary=['Arsenal squad edge'],
                odds_summary=['Market fair view leans Arsenal.'],
                market_shape_summary=['Market shape points to an open game.'],
                caveats=[],
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


class FailingAnalysisService:
    def analyze_match(self, fixture_id: str, *, query: str):
        raise InsufficientEvidenceError('Not enough evidence for a direct call.')


def test_agent_workflow_returns_analysis_payload_and_node_trace() -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentWorkflow

    workflow = MatchAnalysisAgentWorkflow(analysis_service=StubAnalysisService())

    result = workflow.run(fixture_id='epl-001', query='Should I back Arsenal?')

    assert result.status == 'succeeded'
    assert result.fixture_id == 'epl-001'
    assert result.query == 'Should I back Arsenal?'
    assert result.analysis is not None
    assert result.analysis.judgment.verdict == 'Lean Arsenal pre-match.'
    assert result.nodes == [
        'classify_intent',
        'analyze_match',
        'synthesize_result',
        'synthesis_skipped',
    ]
    assert result.error is None


def test_agent_workflow_fails_truthfully_without_analysis_payload() -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentWorkflow

    workflow = MatchAnalysisAgentWorkflow(analysis_service=FailingAnalysisService())

    result = workflow.run(fixture_id='epl-001', query='Show me context')

    assert result.status == 'failed'
    assert result.analysis is None
    assert result.error == 'Not enough evidence for a direct call.'
    assert result.nodes == ['classify_intent', 'analyze_match']


class FakeSynthesisProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[FixtureAnalysisResult] = []

    def synthesize(self, analysis: FixtureAnalysisResult) -> str:
        self.calls.append(analysis)
        return self.text


def test_agent_workflow_records_guarded_generated_synthesis() -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentWorkflow

    provider = FakeSynthesisProvider(
        'Lean Arsenal pre-match. Confidence: medium. Arsenal can press high.'
    )
    workflow = MatchAnalysisAgentWorkflow(
        analysis_service=StubAnalysisService(),
        synthesis_provider=provider,
    )

    result = workflow.run(fixture_id='epl-001', query='Should I back Arsenal?')

    assert result.status == 'succeeded'
    assert result.generated_synthesis == provider.text
    assert result.nodes == [
        'classify_intent',
        'analyze_match',
        'synthesize_result',
        'guard_synthesis',
    ]
    assert provider.calls and provider.calls[0].judgment.verdict == 'Lean Arsenal pre-match.'


def test_agent_workflow_skips_generated_synthesis_without_provider() -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentWorkflow

    workflow = MatchAnalysisAgentWorkflow(analysis_service=StubAnalysisService())

    result = workflow.run(fixture_id='epl-001', query='Should I back Arsenal?')

    assert result.status == 'succeeded'
    assert result.generated_synthesis is None
    assert result.nodes[-1] == 'synthesis_skipped'


def test_agent_workflow_rejects_synthesis_that_omits_guard_terms() -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentWorkflow

    workflow = MatchAnalysisAgentWorkflow(
        analysis_service=StubAnalysisService(),
        synthesis_provider=FakeSynthesisProvider('A vague football paragraph.'),
    )

    result = workflow.run(fixture_id='epl-001', query='Should I back Arsenal?')

    assert result.status == 'failed'
    assert result.generated_synthesis is None
    assert result.analysis is not None
    assert result.error == 'Generated synthesis failed evidence guard.'
    assert result.nodes[-1] == 'guard_synthesis'
