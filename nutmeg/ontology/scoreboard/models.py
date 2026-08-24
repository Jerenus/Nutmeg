"""Immutable rows for governed scoreboard observations and authority."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScoreboardObservationRow:
    scoreboard_observation_id: str
    group_key: str
    metric_key: str
    tally: str
    detail: str
    status: str
    numerator: float | None
    denominator: float | None
    value: float | None
    unit: str | None
    evidence_refs: list[dict[str, str]]
    effective_at: str
    recorded_at: str
    supersedes_observation_id: str | None
    action_id: str


@dataclass(frozen=True, slots=True)
class ScoreboardShadowReviewRow:
    scoreboard_shadow_review_id: str
    legacy_source_artifact_id: str
    legacy_sha256: str
    projection_version: str
    source_high_watermark: int
    classification: list[dict[str, object]]
    matched_count: int
    manual_count: int
    corrected_count: int
    unexplained_count: int
    status: str
    reviewed_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ScoreboardAuthorityRow:
    authority_id: str
    state: str
    projection_version: str | None
    source_high_watermark: int | None
    legacy_sha256: str | None
    shadow_review_id: str | None
    compatibility_export_sha256: str | None
    approved_at: str | None
    approved_by_action_id: str | None
    version: int
