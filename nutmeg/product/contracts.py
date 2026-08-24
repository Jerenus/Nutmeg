"""Strict, versioned DTOs exposed by the local Nutmeg application."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal['1'] = '1'


class StrictContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VersionedContract(StrictContract):
    schema_version: Literal['1'] = SCHEMA_VERSION


class ObjectRefContract(StrictContract):
    object_type: str
    object_id: str


class ReadinessLevel(StrEnum):
    READY = 'ready'
    DEGRADED = 'degraded'
    BLOCKED = 'blocked'


class ReadinessIssue(StrictContract):
    code: str
    message: str
    object_ref: ObjectRefContract | None = None
    observed_at: datetime | None = None


class ReadinessState(StrictContract):
    level: ReadinessLevel
    issues: list[ReadinessIssue] = Field(default_factory=list)


class ProductError(StrictContract):
    code: str
    message: str
    action_id: str | None = None
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    retryable: bool = False
    current_version: int | None = None
    details: dict[str, object] = Field(default_factory=dict)


class MarketSnapshotSummary(StrictContract):
    market_snapshot_id: str
    market_definition_id: str
    as_of: str
    devig_distribution: dict[str, float]


class MatchSummary(StrictContract):
    match_id: str
    home_team: str
    away_team: str
    competition: str | None = None
    kickoff_at: str | None = None
    latest_snapshot_at: str | None = None
    readiness: ReadinessState


class BoardResponse(VersionedContract):
    date: date
    as_of: datetime
    matches: list[MatchSummary] = Field(default_factory=list)


class ClaimSummary(StrictContract):
    claim_id: str
    subject_type: str
    subject_id: str
    predicate: str
    value: dict[str, object]
    status: str
    created_at: str


class ObservationSummary(StrictContract):
    observation_id: str
    observation_type: str
    subject_type: str
    subject_id: str
    value: dict[str, object]
    observed_at: str
    recorded_at: str
    verification_method: str


class EvidenceSummary(StrictContract):
    claims: list[ClaimSummary] = Field(default_factory=list)
    observations: list[ObservationSummary] = Field(default_factory=list)


class ForecastSummary(StrictContract):
    forecast_revision_id: str
    forecast_series_id: str
    revision_no: int
    status: str
    made_at: str
    information_cutoff_at: str | None = None
    prior_snapshot_id: str | None = None
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    evidence_bundle_id: str | None = None
    evidence_status: Literal['bundled', 'legacy_unbundled']
    commitment_tier: str


class WorkflowObjectSummary(StrictContract):
    object_ref: ObjectRefContract
    workflow_type: str
    status: str
    created_at: str


class MatchDetail(VersionedContract):
    match: MatchSummary
    market_snapshot: MarketSnapshotSummary | None = None
    evidence: EvidenceSummary
    forecasts: list[ForecastSummary] = Field(default_factory=list)
    workflow: list[WorkflowObjectSummary] = Field(default_factory=list)
    as_of: datetime


class LineageEdge(StrictContract):
    relation: str
    source: ObjectRefContract
    target: ObjectRefContract


class LineageResponse(VersionedContract):
    object_ref: ObjectRefContract
    edges: list[LineageEdge] = Field(default_factory=list)


class ActionView(StrictContract):
    action_id: str
    action_type: str
    actor_id: str
    actor_role: str
    requested_at: str
    status: str
    result_refs: list[ObjectRefContract] = Field(default_factory=list)
    error_code: str | None = None
    committed_at: str | None = None


class ActionPage(VersionedContract):
    items: list[ActionView] = Field(default_factory=list)
    next_cursor: str | None = None


class OutboxEventView(StrictContract):
    sequence: int
    event_id: str
    action_id: str
    topic: str
    object_type: str | None = None
    object_id: str | None = None
    payload: dict[str, object]
    occurred_at: str


class EventPage(VersionedContract):
    items: list[OutboxEventView] = Field(default_factory=list)
    next_cursor: int


class HealthResponse(VersionedContract):
    initialized: bool
    ontology_schema_version: int
    integrity_check: str
    pending_migrations: list[int] = Field(default_factory=list)
    action_counts: dict[str, int] = Field(default_factory=dict)
    outbox_event_count: int
    outbox_latest_sequence: int


class ProductActionRequest(VersionedContract):
    action_type: str
    idempotency_key: str
    payload: dict[str, object]
    expected_versions: dict[str, int] = Field(default_factory=dict)
    policy_version: str = 'governance-v1'


class ProductActionResponse(VersionedContract):
    action_id: str
    action_type: str
    status: str
    result_refs: list[ObjectRefContract] = Field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    committed_at: str | None = None
