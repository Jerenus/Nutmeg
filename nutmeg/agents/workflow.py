from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from nutmeg.domain.analysis import FixtureAnalysisResult
from nutmeg.services.analysis import InsufficientEvidenceError

try:  # optional dependency; fallback keeps Phase 1 runnable without ai extras.
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - exercised when optional extra is absent.
    END = None
    StateGraph = None

LANGGRAPH_AVAILABLE = StateGraph is not None


class SynthesisProvider(Protocol):
    def synthesize(self, analysis: FixtureAnalysisResult) -> str:
        ...


@dataclass(slots=True, frozen=True)
class MatchAnalysisAgentResult:
    fixture_id: str
    query: str
    status: str
    nodes: list[str]
    analysis: FixtureAnalysisResult | None = None
    error: str | None = None
    executor: str = 'deterministic'
    generated_synthesis: str | None = None


class MatchAnalysisAgentState(TypedDict, total=False):
    fixture_id: str
    query: str
    nodes: list[str]
    analysis: FixtureAnalysisResult
    error: str
    status: str
    generated_synthesis: str


class MatchAnalysisAgentWorkflow:
    def __init__(
        self,
        *,
        analysis_service,
        synthesis_provider: SynthesisProvider | None = None,
        prefer_langgraph: bool = True,
    ) -> None:
        self._analysis_service = analysis_service
        self._synthesis_provider = synthesis_provider
        self._prefer_langgraph = prefer_langgraph
        self._graph = self._compile_graph() if prefer_langgraph and StateGraph is not None else None

    def run(self, *, fixture_id: str, query: str) -> MatchAnalysisAgentResult:
        initial: MatchAnalysisAgentState = {
            'fixture_id': fixture_id,
            'query': query,
            'nodes': [],
        }
        state = (
            self._graph.invoke(initial)
            if self._graph is not None
            else self._run_fallback(initial)
        )
        return MatchAnalysisAgentResult(
            fixture_id=fixture_id,
            query=query,
            status=state.get('status', 'failed'),
            nodes=state.get('nodes', []),
            analysis=state.get('analysis'),
            error=state.get('error'),
            executor='langgraph' if self._graph is not None else 'deterministic',
            generated_synthesis=state.get('generated_synthesis'),
        )

    def _compile_graph(self):
        graph = StateGraph(MatchAnalysisAgentState)
        graph.add_node('classify_intent', self._classify_intent)
        graph.add_node('analyze_match', self._analyze_match)
        graph.add_node('synthesize_result', self._synthesize_result)
        graph.add_node('guard_synthesis', self._guard_synthesis)
        graph.add_node('synthesis_skipped', self._skip_synthesis)
        graph.set_entry_point('classify_intent')
        graph.add_edge('classify_intent', 'analyze_match')
        graph.add_conditional_edges(
            'analyze_match',
            self._route_after_analysis,
            {'synthesize_result': 'synthesize_result', 'end': END},
        )
        graph.add_conditional_edges(
            'synthesize_result',
            self._route_after_synthesis_result,
            {'guard_synthesis': 'guard_synthesis', 'synthesis_skipped': 'synthesis_skipped'},
        )
        graph.add_edge('guard_synthesis', END)
        graph.add_edge('synthesis_skipped', END)
        return graph.compile()

    def _run_fallback(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        state = self._classify_intent(state)
        state = self._analyze_match(state)
        if state.get('status') == 'failed':
            return state
        state = self._synthesize_result(state)
        if self._synthesis_provider is None:
            return self._skip_synthesis(state)
        return self._guard_synthesis(state)

    def _classify_intent(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        return {**state, 'nodes': [*state.get('nodes', []), 'classify_intent']}

    def _analyze_match(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        nodes = [*state.get('nodes', []), 'analyze_match']
        try:
            analysis = self._analysis_service.analyze_match(
                state['fixture_id'],
                query=state['query'],
            )
        except InsufficientEvidenceError as exc:
            return {**state, 'nodes': nodes, 'status': 'failed', 'error': str(exc)}
        return {**state, 'nodes': nodes, 'analysis': analysis}

    def _synthesize_result(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        return {
            **state,
            'nodes': [*state.get('nodes', []), 'synthesize_result'],
            'status': 'succeeded',
        }

    def _skip_synthesis(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        return {**state, 'nodes': [*state.get('nodes', []), 'synthesis_skipped']}

    def _guard_synthesis(self, state: MatchAnalysisAgentState) -> MatchAnalysisAgentState:
        nodes = [*state.get('nodes', []), 'guard_synthesis']
        analysis = state.get('analysis')
        if analysis is None or self._synthesis_provider is None:
            return {
                **state,
                'nodes': nodes,
                'status': 'failed',
                'error': 'Synthesis guard missing analysis.',
            }
        generated = self._synthesis_provider.synthesize(analysis)
        if not self._passes_synthesis_guard(generated, analysis):
            return {
                **state,
                'nodes': nodes,
                'status': 'failed',
                'error': 'Generated synthesis failed evidence guard.',
            }
        return {**state, 'nodes': nodes, 'generated_synthesis': generated}

    def _passes_synthesis_guard(self, generated: str, analysis: FixtureAnalysisResult) -> bool:
        normalized = generated.casefold()
        verdict = analysis.judgment.verdict.casefold()
        confidence = analysis.judgment.confidence.casefold()
        return verdict in normalized and confidence in normalized

    def _route_after_analysis(self, state: MatchAnalysisAgentState) -> str:
        if state.get('status') == 'failed':
            return 'end'
        return 'synthesize_result'

    def _route_after_synthesis_result(self, state: MatchAnalysisAgentState) -> str:
        if self._synthesis_provider is None:
            return 'synthesis_skipped'
        return 'guard_synthesis'
