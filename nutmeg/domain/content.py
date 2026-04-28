from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ContentCandidate:
    match_id: str
    match_no: int
    match_name: str
    competition: str
    match_time: str | None
    attention_score: float
    content_score: float
    model_stability_score: float
    compliance_score: float
    final_content_priority: float
    selection_reason: str
    source_recommendation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ComplianceChecklistItem:
    question: str
    status: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ComplianceAssessment:
    risk_level: str
    risk_reasons: list[str]
    checklist: list[ComplianceChecklistItem]
    publish_recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "risk_reasons": self.risk_reasons,
            "checklist": [item.to_dict() for item in self.checklist],
            "publish_recommendation": self.publish_recommendation,
        }


@dataclass(slots=True, frozen=True)
class ContentArtifacts:
    json_path: str | None = None
    markdown_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ContentPack:
    match_id: str
    match_name: str
    competition: str
    match_time: str | None
    content_priority: float
    selection_reason: str
    risk_level: str
    risk_reasons: list[str]
    compliance_checklist: list[ComplianceChecklistItem]
    titles: list[str]
    short_video_script: str
    long_article: str
    key_observation_points: list[str]
    uncertainty_factors: list[str]
    disclaimer: str
    publish_recommendation: str
    llm_provider: str
    llm_status: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "match_name": self.match_name,
            "competition": self.competition,
            "match_time": self.match_time,
            "content_priority": self.content_priority,
            "selection_reason": self.selection_reason,
            "risk_level": self.risk_level,
            "risk_reasons": self.risk_reasons,
            "titles": self.titles,
            "short_video_script": self.short_video_script,
            "long_article": self.long_article,
            "compliance_checklist": [item.to_dict() for item in self.compliance_checklist],
            "key_observation_points": self.key_observation_points,
            "uncertainty_factors": self.uncertainty_factors,
            "disclaimer": self.disclaimer,
            "publish_recommendation": self.publish_recommendation,
            "llm_provider": self.llm_provider,
            "llm_status": self.llm_status,
            "warnings": self.warnings,
        }


@dataclass(slots=True, frozen=True)
class ContentBatch:
    source_report_path: str
    generated_at: str
    llm_provider: str
    candidates: list[ContentCandidate]
    packs: list[ContentPack]
    artifacts: ContentArtifacts
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_report_path": self.source_report_path,
            "generated_at": self.generated_at,
            "llm_provider": self.llm_provider,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "packs": [pack.to_dict() for pack in self.packs],
            "artifacts": self.artifacts.to_dict(),
            "warnings": self.warnings,
        }
