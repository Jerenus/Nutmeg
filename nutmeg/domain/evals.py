from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class EvalCase:
    case_id: str
    category: str
    query: str
    expected_keywords: list[str]
    output_text: str | None = None
    fixture_id: str | None = None


@dataclass(slots=True, frozen=True)
class EvalCaseResult:
    case_id: str
    category: str
    passed: bool
    missing_keywords: list[str]
    output_text: str


@dataclass(slots=True, frozen=True)
class EvalRunResult:
    dataset: str
    generated_at: datetime
    total_cases: int
    passed_cases: int
    failed_cases: int
    results: list[EvalCaseResult] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class PredictionReviewSummary:
    total_predictions: int
    resolved_predictions: int
    average_brier_score: float | None
    pick_accuracy: float | None

