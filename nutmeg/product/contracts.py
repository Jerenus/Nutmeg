"""Strict, versioned DTOs exposed by the local Nutmeg application."""
from __future__ import annotations

import base64
import binascii
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Literal['1'] = '1'


class StrictContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VersionedContract(StrictContract):
    schema_version: Literal['1'] = SCHEMA_VERSION


class ObjectRefContract(StrictContract):
    object_type: str
    object_id: str


class EvidenceSpanSummary(ObjectRefContract):
    artifact_id: str | None = None
    artifact_retrieval_id: str | None = None
    quote: str | None = None
    locator: str | None = None


class ScenarioSummary(StrictContract):
    label: str
    mechanism: str
    probability: float | None = Field(default=None, ge=0.0, le=1.0)


class CopilotFactorDraft(StrictContract):
    factor_definition_id: str
    delta: dict[str, float]
    scope_entity_ids: list[str] = Field(default_factory=list)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class CopilotDraft(StrictContract):
    summary: str = Field(min_length=1)
    scenarios: list[ScenarioSummary]
    proposed_belief: dict[str, float] | None = None
    factors: list[CopilotFactorDraft]
    falsifier: str | None = None
    citations: list[ObjectRefContract] = Field(min_length=1)
    conflicts: list[str]
    missing_evidence: list[str]


class CopilotRequest(VersionedContract):
    idempotency_key: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=4000)
    as_of: datetime


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
    evidence_count: int = 0
    workflow_state: str = 'unread'
    next_action: str = 'inspect'
    flag_count: int = 0


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
    spans: list[EvidenceSpanSummary] = Field(default_factory=list)


class ObservationSummary(StrictContract):
    observation_id: str
    observation_type: str
    subject_type: str
    subject_id: str
    value: dict[str, object]
    observed_at: str
    recorded_at: str
    verification_method: str
    source_retrieval_ids: list[str] = Field(default_factory=list)


class EvidenceConflictSummary(StrictContract):
    conflict_id: str
    predicate: str
    claim_ids: list[str]
    statuses: list[str]
    blocking: bool


class EvidenceSummary(StrictContract):
    claims: list[ClaimSummary] = Field(default_factory=list)
    observations: list[ObservationSummary] = Field(default_factory=list)
    conflicts: list[EvidenceConflictSummary] = Field(default_factory=list)


class MatchContextSummary(StrictContract):
    match_revision_id: str
    competition_id: str | None = None
    competition_edition_id: str | None = None
    competition: str | None = None
    round_label: str | None = None
    venue_id: str | None = None
    scheduled_at: str | None = None
    schedule_status: str
    status: str
    home_team_id: str
    home_team: str
    away_team_id: str
    away_team: str


class EvidenceBundleSummary(StrictContract):
    evidence_bundle_id: str
    frozen_at: str
    information_cutoff_at: str
    market_snapshot_id: str | None = None
    prior_distribution: dict[str, float]
    identity_resolution_version: str | None = None
    source_coverage: dict[str, object]
    freshness: dict[str, object]
    content_hash: str
    item_refs: list[ObjectRefContract] = Field(default_factory=list)


class FlagInstanceSummary(StrictContract):
    flag_instance_id: str
    flag_type: str
    match_id: str
    direction: str | None = None
    strength: float
    evidence_refs: list[ObjectRefContract] = Field(default_factory=list)
    predicted_face: str | None = None
    status: str
    created_at: str


class PredictionSummary(StrictContract):
    prediction_id: str
    match_id: str
    claim: str
    falsifier: str
    status: str
    outcome: str | None = None
    registered_at: str
    settled_at: str | None = None


class PrecedentLinkSummary(StrictContract):
    precedent_link_id: str
    subject_type: str
    subject_id: str
    precedent_match_id: str
    scope: str
    evidence_refs: list[ObjectRefContract] = Field(default_factory=list)
    created_at: str


class AdjudicationSummary(StrictContract):
    adjudication_id: str
    subject_type: str
    subject_id: str
    decision: str
    actor_id: str
    reason: str
    evidence_rejected: list[ObjectRefContract] = Field(default_factory=list)
    alternative: dict[str, object] = Field(default_factory=dict)
    created_at: str
    supersedes_adjudication_id: str | None = None


class AgentProposalSummary(StrictContract):
    agent_proposal_id: str
    subject_type: str
    subject_id: str
    proposal_type: str
    status: str
    version: int
    information_cutoff_at: str | None = None
    operator_prompt: str | None = None
    summary: str
    scenarios: list[ScenarioSummary] = Field(default_factory=list)
    proposed_belief: dict[str, float] | None = None
    factors: list[CopilotFactorDraft] = Field(default_factory=list)
    falsifier: str | None = None
    citations: list[EvidenceSpanSummary] = Field(default_factory=list)
    citation_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    model_name: str
    model_version: str
    created_at: str
    resolved_at: str | None = None
    resolved_by_action_id: str | None = None


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
    context: MatchContextSummary | None = None
    market_timeline: list[MarketSnapshotSummary] = Field(default_factory=list)
    evidence_bundles: list[EvidenceBundleSummary] = Field(default_factory=list)
    flag_instances: list[FlagInstanceSummary] = Field(default_factory=list)
    predictions: list[PredictionSummary] = Field(default_factory=list)
    precedent_links: list[PrecedentLinkSummary] = Field(default_factory=list)
    adjudications: list[AdjudicationSummary] = Field(default_factory=list)
    agent_proposals: list[AgentProposalSummary] = Field(default_factory=list)


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


class AlertSeverity(StrEnum):
    INFO = 'info'
    WARN = 'warn'
    ERROR = 'error'


class AlertSummary(StrictContract):
    alert_id: str
    severity: AlertSeverity
    code: str
    title: str
    detail: str
    observed_at: datetime
    object_ref: ObjectRefContract | None = None
    href: str | None = None


class SourceHealthSummary(StrictContract):
    source_name: str
    source_type: str
    status: str
    retrieval_count: int
    latest_retrieved_at: str | None = None
    age_seconds: int | None = None
    error_code: str | None = None
    error_detail: str | None = None


class IdentityQueueItem(StrictContract):
    entity_type: Literal['team']
    entity_id: str
    canonical_name: str
    resolution_status: str
    country: str | None = None
    created_at: str
    external_identifiers: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class OperationsMetrics(StrictContract):
    ontology_integrity: str
    ontology_schema_version: int
    action_high_watermark: int
    outbox_high_watermark: int
    projection_run_count: int
    unresolved_identity_count: int


class OperationsResponse(VersionedContract):
    as_of: datetime
    sources: list[SourceHealthSummary] = Field(default_factory=list)
    identities: list[IdentityQueueItem] = Field(default_factory=list)
    recent_failures: list[ActionView] = Field(default_factory=list)
    alerts: list[AlertSummary] = Field(default_factory=list)
    metrics: OperationsMetrics


class CommandCenterResponse(VersionedContract):
    board: BoardResponse
    health: HealthResponse
    alerts: list[AlertSummary] = Field(default_factory=list)
    readiness_counts: dict[str, int] = Field(default_factory=dict)
    pending_workflow_count: int = 0


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


class TicketLegCommand(StrictContract):
    leg_key: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    match_no: int = Field(ge=1)
    name: str = Field(min_length=1)
    market_definition_id: str = Field(min_length=1)
    selection_id: str = Field(min_length=1)
    outcome_key: Literal['home', 'draw', 'away']
    faces: str = Field(pattern=r'^[310]+$')
    forecast_revision_id: str = Field(min_length=1)
    entry_quote_id: str | None = None
    odds: float = Field(gt=1.0)
    line: str | None = None
    bucket: str = Field(min_length=1)
    fair: dict[str, float]
    confidence: int = Field(ge=0, le=5)
    directional_flags: list[tuple[str, str]] = Field(default_factory=list)
    nondirectional_flags: list[str] = Field(default_factory=list)
    anchor_integrity: Literal['pass', 'fail', 'symmetric_damage', 'unknown'] = 'unknown'
    precedents: list[tuple[str, str, str]] = Field(default_factory=list)


class TicketAuditFindingSummary(StrictContract):
    finding_id: str
    level: Literal['ERROR', 'WARN']
    code: str
    match_no: int | None = None
    message: str
    since: str
    adjudication_id: str | None = None
    adjudication_decision: str | None = None


class TicketSelection(StrictContract):
    market_definition_id: str
    selection_id: str
    outcome_key: str
    line: str | None = None
    quote_id: str | None = None
    odds: float | None = None
    captured_at: str | None = None
    provider: str | None = None
    eligible: bool
    block_reasons: list[str] = Field(default_factory=list)


class TicketWorkbenchMatch(StrictContract):
    match_id: str
    match_revision_id: str
    match_no: int = Field(ge=1)
    home_team: str
    away_team: str
    competition: str | None = None
    kickoff_at: str
    market_definition_id: str
    forecast_revision_id: str | None = None
    forecast_revision_no: int | None = None
    belief_distribution: dict[str, float] | None = None
    selections: list[TicketSelection] = Field(default_factory=list)
    eligible: bool
    block_reasons: list[str] = Field(default_factory=list)


class TicketBatchRevisionSummary(StrictContract):
    ticket_batch_revision_id: str
    ticket_batch_id: str
    revision_no: int = Field(ge=1)
    supersedes_revision_id: str | None = None
    run_date: date
    channel: str
    account_id: str
    currency: str
    deadline_at: str
    state: Literal['draft', 'empty', 'approved', 'approved_empty']
    content_hash: str
    source_artifact_id: str
    created_at: str
    created_by_action_id: str
    legs: list[TicketLegCommand] = Field(default_factory=list)
    composition: dict[str, object] = Field(default_factory=dict)
    audit_state: Literal['clean', 'warn', 'error']
    audit_findings: list[TicketAuditFindingSummary] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    added_leg_keys: list[str] = Field(default_factory=list)
    removed_leg_keys: list[str] = Field(default_factory=list)
    changed_leg_keys: list[str] = Field(default_factory=list)


class TicketWorkbenchResponse(VersionedContract):
    date: date
    as_of: datetime
    matches: list[TicketWorkbenchMatch] = Field(default_factory=list)
    batch_revisions: list[TicketBatchRevisionSummary] = Field(default_factory=list)


class TicketBatchHistoryResponse(VersionedContract):
    ticket_batch_id: str
    revisions: list[TicketBatchRevisionSummary] = Field(default_factory=list)


class TicketArtifactDetail(VersionedContract):
    ticket_artifact_id: str
    ticket_batch_revision_id: str
    ticket_index: int = Field(ge=0)
    ticket_hash: str
    source_artifact_id: str
    amount: float = Field(gt=0)
    currency: str
    channel: str
    deadline_at: str
    payload: dict[str, object]
    approved_at: str
    approved_by_action_id: str
    confirmation_state: Literal['not_issued', 'open', 'expired', 'consumed']
    confirmation_id: str | None = None
    confirmation_expires_at: str | None = None
    placement_state: Literal['unplaced', 'placed']
    ticket_placement_id: str | None = None
    ticket_id: str | None = None
    placement_mode: str | None = None
    external_reference: str | None = None
    receipt_artifact_id: str | None = None
    receipt_retrieval_id: str | None = None
    placed_at: str | None = None


class CreateTicketBatchCommand(VersionedContract):
    run_date: date
    channel: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    deadline_at: AwareDatetime
    legs: list[TicketLegCommand]
    idempotency_key: str = Field(min_length=1, max_length=200)


class RemoveTicketLegCommand(VersionedContract):
    leg_key: str = Field(min_length=1)
    expected_revision_no: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ApproveTicketBatchCommand(VersionedContract):
    expected_revision_no: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class IssueConfirmationCommand(VersionedContract):
    idempotency_key: str = Field(min_length=1, max_length=200)


class IssueConfirmationResponse(ProductActionResponse):
    confirmation_id: str | None = None
    nonce: str | None = None
    expires_at: str | None = None


class ConfirmPlacementCommand(VersionedContract):
    confirmation_id: str = Field(min_length=1)
    nonce: str = Field(min_length=1)
    ticket_hash: str = Field(min_length=1)
    amount: float = Field(gt=0)
    currency: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    placement_mode: Literal['manual', 'connector']
    external_reference: str = Field(min_length=1)
    receipt_base64: str = Field(min_length=1)
    receipt_content_type: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator('amount')
    @classmethod
    def amount_must_be_whole_fen(cls, value: float) -> float:
        try:
            amount = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError('amount must be representable as whole fen') from error
        if amount * 100 != (amount * 100).to_integral_value():
            raise ValueError('amount must be representable as whole fen')
        return value

    @field_validator('receipt_base64')
    @classmethod
    def receipt_must_be_valid_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError('receipt_base64 must be valid base64') from error
        if not decoded:
            raise ValueError('receipt_base64 must contain non-empty receipt bytes')
        return value
