from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.agents.router import QueryIntent
from nutmeg.domain.fixtures import Fixture


@dataclass(slots=True, frozen=True)
class AnalysisEvidenceSummary:
    tactical_summary: list[str]
    snapshot_summary: list[str]
    odds_summary: list[str]
    market_shape_summary: list[str]
    caveats: list[str]


@dataclass(slots=True, frozen=True)
class AnalysisJudgment:
    verdict: str
    core_reasons: list[str]
    counterargument: str
    confidence: str


@dataclass(slots=True, frozen=True)
class FixtureAnalysisResult:
    fixture: Fixture
    intent: QueryIntent
    query: str
    evidence: AnalysisEvidenceSummary
    judgment: AnalysisJudgment
    conflict_state: str
    generated_at: datetime
