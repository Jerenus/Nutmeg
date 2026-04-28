from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class InternalAnalysis:
    opening_read: str
    football_factors: list[str]
    market_factors: list[str]
    key_risks: list[str]
    internal_lean: str
    confidence: str
    responsible_use_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PublicScript:
    title_candidates: list[str]
    hook: str
    body: list[str]
    closing: str
    voiceover_text: str
    forbidden_terms_removed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VideoSegment:
    segment_no: int
    duration_seconds: int
    narration: str
    visual_direction: str
    camera_direction: str
    tactical_overlay: str
    subtitle_text: str
    seedance_prompt_zh: str
    seedance_prompt_en: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VideoStoryboard:
    style_profile_id: str
    ratio_primary: str
    ratio_secondary: str
    segment_count: int
    segments: list[VideoSegment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_profile_id": self.style_profile_id,
            "ratio_primary": self.ratio_primary,
            "ratio_secondary": self.ratio_secondary,
            "segment_count": self.segment_count,
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(slots=True, frozen=True)
class SeedanceTaskSpec:
    task_key: str
    provider: str
    model: str
    content: list[dict[str, Any]]
    resolution: str
    ratio: str
    duration: int
    seed: int
    camera_fixed: bool
    watermark: bool
    generate_audio: bool
    safety_identifier: str
    status: str = "draft"
    provider_task_id: str | None = None
    output_video_url: str | None = None
    local_video_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class MatchContentPack:
    match_id: str
    match_no: str
    competition: str
    home_team: str
    away_team: str
    kickoff_time: str
    popularity_score: float
    focus_level: str
    internal_analysis: InternalAnalysis
    public_script: PublicScript
    storyboard: VideoStoryboard
    seedance_specs: dict[str, list[SeedanceTaskSpec]]
    compliance: dict[str, Any]
    evidence: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "match_no": self.match_no,
            "competition": self.competition,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "kickoff_time": self.kickoff_time,
            "popularity_score": self.popularity_score,
            "focus_level": self.focus_level,
            "internal_analysis": self.internal_analysis.to_dict(),
            "public_script": self.public_script.to_dict(),
            "storyboard": self.storyboard.to_dict(),
            "seedance_specs": {
                key: [task.to_dict() for task in tasks]
                for key, tasks in self.seedance_specs.items()
            },
            "compliance": self.compliance,
            "evidence": self.evidence,
            "warnings": self.warnings,
        }


@dataclass(slots=True, frozen=True)
class DailyContentArtifacts:
    run_dir: str | None = None
    json_path: str | None = None
    markdown_path: str | None = None
    pdf_path: str | None = None
    seedance_manifest_path: str | None = None
    status_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class DailyContentRun:
    run_id: str
    run_date: str
    generated_at: str
    provider: str
    scope: str
    style_profile: str
    matches: list[MatchContentPack]
    artifacts: DailyContentArtifacts = field(default_factory=DailyContentArtifacts)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_date": self.run_date,
            "generated_at": self.generated_at,
            "provider": self.provider,
            "scope": self.scope,
            "style_profile": self.style_profile,
            "matches": [match.to_dict() for match in self.matches],
            "artifacts": self.artifacts.to_dict(),
            "warnings": self.warnings,
        }
