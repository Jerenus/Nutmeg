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


@dataclass(slots=True, frozen=True)
class HookCandidate:
    hook_type: str
    text: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TacticalBeat:
    beat_id: str
    start_seconds: float
    end_seconds: float
    title: str
    explanation: str
    home_shape: list[str]
    away_shape: list[str]
    arrows: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class NarrativeSegment:
    segment_id: str
    start_seconds: float
    end_seconds: float
    scene_type: str
    voiceover_text: str
    subtitle_text: str
    screen_card_text: str
    visual_intent: str
    tactical_focus: str
    transition_to_next: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class NarrativeTimeline:
    duration_seconds: float
    segments: list[NarrativeSegment]

    def voiceover_text(self) -> str:
        return "".join(segment.voiceover_text for segment in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(slots=True, frozen=True)
class DirectorShot:
    shot_id: str
    visual_owner: str
    start_seconds: float
    end_seconds: float
    purpose: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class MoodShotSpec:
    task_key: str
    prompt: str
    duration: int
    placement_start_seconds: float
    placement_end_seconds: float
    quality_constraints: list[str]
    provider: str = "volcengine-ark"
    model: str = "doubao-seedance-2-0-260128"
    ratio: str = "9:16"
    resolution: str = "720p"
    status: str = "draft"
    provider_task_id: str | None = None
    output_video_url: str | None = None
    local_video_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class RemotionTimelineSpec:
    composition_id: str
    fps: int
    width: int
    height: int
    duration_seconds: float
    props_path: str
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class QualityGateResult:
    gate: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ProductionPacketV2:
    match_id: str
    style_profile: str
    hook_candidates: list[HookCandidate]
    selected_hook: str
    main_contradiction: str
    voiceover_script: str
    tactical_beats: list[TacticalBeat]
    director_shots: list[DirectorShot]
    mood_shots: list[MoodShotSpec]
    narrative_timeline: NarrativeTimeline
    remotion_timeline: RemotionTimelineSpec
    quality_gates: list[QualityGateResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "style_profile": self.style_profile,
            "hook_candidates": [hook.to_dict() for hook in self.hook_candidates],
            "selected_hook": self.selected_hook,
            "main_contradiction": self.main_contradiction,
            "voiceover_script": self.voiceover_script,
            "tactical_beats": [beat.to_dict() for beat in self.tactical_beats],
            "director_shots": [shot.to_dict() for shot in self.director_shots],
            "mood_shots": [shot.to_dict() for shot in self.mood_shots],
            "narrative_timeline": self.narrative_timeline.to_dict(),
            "remotion_timeline": self.remotion_timeline.to_dict(),
            "quality_gates": [gate.to_dict() for gate in self.quality_gates],
        }
