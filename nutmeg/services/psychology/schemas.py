from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LeanDirection = Literal["agree_data", "neutral", "diverge_data"]
LeanTag = Literal["data", "psychology", "neutral"]
ConvictionTag = Literal["low", "medium", "high"]
Provenance = Literal["data", "psychology", "inspiration_forced"]
ParseMethod = Literal["llm", "regex_fallback"]


@dataclass(frozen=True, slots=True)
class OutcomeView:
    market: str
    outcome: str
    conviction: float


@dataclass(frozen=True, slots=True)
class SignalReading:
    provider: str
    fixture_id: str
    market: str
    outcome_view: str | None
    conviction: float
    evidence: list[str]
    source_refs: list[str]
    abstain_reason: str | None


@dataclass(frozen=True, slots=True)
class PsychologyVerdict:
    fixture_id: str
    market_views: dict[str, OutcomeView]
    conviction: float
    lean_direction: LeanDirection
    contributing_readings: list[SignalReading]


@dataclass(frozen=True, slots=True)
class DataLeg:
    leg_id: str
    fixture_id: str
    market: str
    outcome: str
    odds: float


@dataclass(frozen=True, slots=True)
class FinalLeg:
    leg_id: str
    fixture_id: str
    market: str
    outcome: str
    odds: float
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class Scheme:
    name: str
    legs: list[DataLeg]


@dataclass(frozen=True, slots=True)
class FinalScheme:
    legs: list[FinalLeg]
    confidence: str
    notes: list[str]


@dataclass(frozen=True, slots=True)
class OverrideCandidate:
    leg_id: str
    fixture_id: str
    market: str
    from_outcome: str
    to_outcome: str
    conviction: float
    reasoning: list[str]
    source_provider: str


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    accepted: list[OverrideCandidate]
    rejected: list[tuple[OverrideCandidate, str]]
    guardrail_state: dict[str, str]


@dataclass(frozen=True, slots=True)
class InspirationTags:
    lean: LeanTag
    conviction: ConvictionTag
    focus: list[str]
    force_psychology: bool
    force_data: bool


@dataclass(frozen=True, slots=True)
class InspirationNote:
    date: str
    raw_text: str
    parsed_tags: InspirationTags
    parse_method: ParseMethod
    timestamp: str


@dataclass(frozen=True, slots=True)
class DashboardRow:
    fixture_id: str
    data_pick: str
    psych_pick: str | None
    conflict: bool
    final_pick: str
    conviction: float


@dataclass(frozen=True, slots=True)
class DualSchemeReport:
    data_scheme: Scheme
    psychology_scheme: Scheme
    final_scheme: FinalScheme
    dashboard_rows: list[DashboardRow]
    inspiration: InspirationNote | None
    guardrail: GuardrailDecision
