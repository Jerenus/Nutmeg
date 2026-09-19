from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictOperatorContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VersionedOperatorContract(StrictOperatorContract):
    schema_version: Literal['1'] = '1'


class OperatorLane(StrEnum):
    JCZQ = 'jczq'
    ZUCAI = 'zucai'


class OperatorStage(StrEnum):
    JCZQ_AM = "jczq_am"
    JCZQ_DECISION = "jczq_decision"
    JCZQ_DECISION_RECOVERY = "jczq_decision_recovery"
    JCZQ_PRECLOSE_CHECK = "jczq_preclose_check"
    JCZQ_CLOSE = "jczq_close"
    JCZQ_CLOSE_VERIFY = "jczq_close_verify"
    JCZQ_SETTLE = "jczq_settle"
    JCZQ_SETTLEMENT_RETRY = "jczq_settlement_retry"
    ZUCAI_PREP = "zucai_prep"
    ZUCAI_PREP_REVISION = "zucai_prep_revision"
    ZUCAI_AFTERNOON = "zucai_afternoon"
    ZUCAI_REVISION = "zucai_revision"


class OperatorRecoveryCode(StrEnum):
    """Closed recovery vocabulary exposed by operator-facing contracts."""

    OFFICIAL_SCHEDULE_MISSING = "official_schedule_missing"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_STALE = "evidence_stale"
    EVIDENCE_CONFLICT = "evidence_conflict"
    SOURCE_CONTRACT_INVALID = "source_contract_invalid"
    TASK_SNAPSHOT_CHANGED = "task_snapshot_changed"
    AUDIT_ERROR = "audit_error"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    TELEGRAM_UPDATE_OWNER_CONFLICT = "telegram_update_owner_conflict"
    TELEGRAM_OWNER_MISSING = "telegram_owner_missing"
    TELEGRAM_OWNER_HEARTBEAT_EXPIRED = "telegram_owner_heartbeat_expired"
    TELEGRAM_OWNER_CLOCK_SKEW = "telegram_owner_clock_skew"
    TELEGRAM_OWNER_UNAVAILABLE = "telegram_owner_unavailable"
    DIAGNOSTIC_UNAVAILABLE = "diagnostic_unavailable"
    PLACEMENT_LEDGER_INTEGRITY = "placement_ledger_integrity"
    RESULT_SOURCE_MISSING = "result_source_missing"
    RESULT_PENDING = "result_pending"
    RESULT_SOURCE_CONFLICT = "result_source_conflict"
    PROJECTION_STALE = "projection_stale"
    PROJECTION_UNAVAILABLE = "projection_unavailable"
    SCOREBOARD_AUTHORITY_UNAVAILABLE = "scoreboard_authority_unavailable"
    APP_INSTANCE_CONFLICT = "app_instance_conflict"
    ONTOLOGY_MAINTENANCE_CONFLICT = "ontology_maintenance_conflict"
    COMMAND_UNAVAILABLE = "command_unavailable"
    OFFICIAL_HISTORY_UNAVAILABLE = "official_history_unavailable"
    PROTECTED_ARTIFACT_BINDING_MISSING = "protected_artifact_binding_missing"
    PROTECTED_ARTIFACT_MISSING = "protected_artifact_missing"
    SELECTED_CANDIDATE_MISSING = "selected_candidate_missing"
    OPERATOR_TASK_BLOCKED = "operator_task_blocked"
    OPERATOR_INPUTS_MISSING = "operator_inputs_missing"

    # Legacy read-only surfaces still emit these stable codes.
    ODDS_SNAPSHOT_STALE = "odds_snapshot_stale"
    TICKET_AUDIT_BLOCKED = "ticket_audit_blocked"
    WAITING_FOR_SOURCE = "waiting_for_source"


class SchedulerOwnershipClaimV1(StrictOperatorContract):
    owner_kind: Literal["openclaw", "launchd"]
    business_label: str = Field(min_length=1, max_length=200)
    stage: OperatorStage
    enabled: bool | None = None
    loaded: bool | None = None
    last_run_at: AwareDatetime | None = None
    last_status: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_owner_state(self) -> "SchedulerOwnershipClaimV1":
        expected = (self.enabled is not None, self.loaded is not None)
        if self.owner_kind == "openclaw" and expected != (True, False):
            raise ValueError("OpenClaw ownership requires only enabled state")
        if self.owner_kind == "launchd" and expected != (False, True):
            raise ValueError("launchd ownership requires only loaded state")
        return self

    @property
    def active(self) -> bool:
        return bool(self.enabled if self.owner_kind == "openclaw" else self.loaded)


class SchedulerStageSummaryV1(StrictOperatorContract):
    stage: OperatorStage
    claim_count: int = Field(ge=0)
    conflict: bool

    @model_validator(mode="after")
    def _validate_conflict(self) -> "SchedulerStageSummaryV1":
        if self.conflict != (self.claim_count > 1):
            raise ValueError("scheduler conflict must reflect the active claim count")
        return self


class TelegramTransportStatusV1(StrictOperatorContract):
    state: Literal["available", "diagnostic_unavailable"]
    configured: bool | None = None
    running: bool | None = None
    connected: bool | None = None
    last_connected_at: AwareDatetime | None = None
    last_started_at: AwareDatetime | None = None
    last_transport_activity_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validate_transport_state(self) -> "TelegramTransportStatusV1":
        facts = (self.configured, self.running, self.connected)
        timestamps = (
            self.last_connected_at,
            self.last_started_at,
            self.last_transport_activity_at,
        )
        if self.state == "available" and any(value is None for value in facts):
            raise ValueError("available Telegram transport requires all state facts")
        if self.state == "diagnostic_unavailable" and any(
            value is not None for value in facts + timestamps
        ):
            raise ValueError("unavailable Telegram transport cannot infer state facts")
        return self


class TelegramOwnerStatusV1(StrictOperatorContract):
    kind: Literal["telegram_owner_status_v1"] = "telegram_owner_status_v1"
    owner_mode: Literal["openclaw", "native_distinct_token", "unavailable", "conflict"]
    configured: bool
    last_heartbeat_at: AwareDatetime | None = None
    heartbeat_state: Literal[
        "available",
        "missing",
        "expired",
        "clock_skew",
        "conflict",
        "unavailable",
    ]
    confirmation_available: bool
    blocking_code: OperatorRecoveryCode | None = None
    recovery_label: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def _validate_confirmation_state(self) -> "TelegramOwnerStatusV1":
        if self.confirmation_available != (self.heartbeat_state == "available"):
            raise ValueError("confirmation availability must reflect heartbeat state")
        if self.confirmation_available and self.blocking_code is not None:
            raise ValueError("available confirmation cannot have a blocking code")
        if not self.confirmation_available and self.blocking_code is None:
            raise ValueError("unavailable confirmation requires a blocking code")
        return self


class OperatorMaintenanceResponseV1(VersionedOperatorContract):
    as_of: AwareDatetime
    diagnostic_state: Literal["available", "diagnostic_unavailable"]
    diagnostic_code: Literal["diagnostic_unavailable"] | None = None
    claims: list[SchedulerOwnershipClaimV1] = Field(max_length=2000)
    stages: list[SchedulerStageSummaryV1] = Field(max_length=len(OperatorStage))
    telegram_owner: TelegramOwnerStatusV1
    telegram_transport: TelegramTransportStatusV1
    recovery_label: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def _validate_diagnostic_state(self) -> "OperatorMaintenanceResponseV1":
        if self.diagnostic_state == "available":
            if self.diagnostic_code is not None or self.recovery_label is not None:
                raise ValueError("available maintenance diagnostic cannot have recovery")
            if (
                len(self.stages) != len(OperatorStage)
                or {item.stage for item in self.stages} != set(OperatorStage)
            ):
                raise ValueError("available maintenance diagnostic requires every stage")
            active_counts = {
                stage: sum(claim.active and claim.stage is stage for claim in self.claims)
                for stage in OperatorStage
            }
            if any(
                item.claim_count != active_counts[item.stage] for item in self.stages
            ):
                raise ValueError("maintenance stage count must reflect active claims")
        elif (
            self.diagnostic_code != "diagnostic_unavailable"
            or self.claims
            or self.stages
            or self.recovery_label is None
        ):
            raise ValueError("unavailable maintenance diagnostic must fail closed")
        return self


class OperatorAuditLineageItemV1(StrictOperatorContract):
    relation: str = Field(min_length=1, max_length=100)
    object_type: str = Field(min_length=1, max_length=100)
    object_id: str = Field(min_length=1, max_length=1000)
    revision_id: str | None = Field(default=None, min_length=1, max_length=1000)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_by_action_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
    )
    source_payload_location: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )


class OperatorAuditProjectionV1(StrictOperatorContract):
    projection_name: str = Field(min_length=1, max_length=100)
    state: Literal["ready", "stale", "unavailable"]
    projection_version: str | None = Field(default=None, min_length=1, max_length=200)
    source_action_high_watermark: int | None = Field(default=None, ge=0, strict=True)
    current_action_high_watermark: int = Field(ge=0, strict=True)
    built_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validate_projection_state(self) -> "OperatorAuditProjectionV1":
        provenance = (
            self.projection_version,
            self.source_action_high_watermark,
            self.built_at,
        )
        if self.state == "unavailable":
            if any(value is not None for value in provenance):
                raise ValueError("unavailable projection cannot claim provenance")
            return self
        if any(value is None for value in provenance):
            raise ValueError("available projection requires complete provenance")
        source = self.source_action_high_watermark
        if source is None:
            raise ValueError("available projection requires a source high-water mark")
        if source > self.current_action_high_watermark:
            raise ValueError("projection high-water mark cannot lead the Action log")
        expected_state = (
            "ready" if source == self.current_action_high_watermark else "stale"
        )
        if self.state != expected_state:
            raise ValueError("projection state must reflect its exact high-water marks")
        return self


class OperatorAuditEnvelopeV1(VersionedOperatorContract):
    kind: Literal["operator_audit_envelope_v1"] = "operator_audit_envelope_v1"
    as_of: AwareDatetime
    title: str = Field(min_length=1, max_length=500)
    task_label: str = Field(min_length=1, max_length=300)
    work_item_label: str = Field(min_length=1, max_length=300)
    return_href: str = Field(pattern=r"^/", min_length=1, max_length=500)
    task_id: str = Field(min_length=1, max_length=500)
    work_item_id: str = Field(min_length=1, max_length=1000)
    task_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_override_ticket_batch_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    lineage: list[OperatorAuditLineageItemV1] = Field(min_length=1, max_length=1000)
    projection: OperatorAuditProjectionV1


class WorkItemProgressViewV1(StrictOperatorContract):
    completed_count: int = Field(ge=0, strict=True)
    required_count: int = Field(ge=0, strict=True)
    progress_label: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _validate_progress(self) -> "WorkItemProgressViewV1":
        if self.completed_count > self.required_count:
            raise ValueError("completed work cannot exceed required work")
        return self


class WorkItemActionViewV1(StrictOperatorContract):
    action_code: str = Field(min_length=1, max_length=100)
    action_label: str = Field(min_length=1, max_length=200)
    enabled: bool
    recovery_link: str = Field(pattern=r"^/", min_length=1, max_length=500)


class OperatorBlockViewV1(StrictOperatorContract):
    code: OperatorRecoveryCode
    message: str = Field(min_length=1, max_length=500)
    repair_owner: str = Field(min_length=1, max_length=200)
    reevaluate_at: AwareDatetime | None = None
    recovery_link: str = Field(pattern=r"^/", min_length=1, max_length=500)


class OfferMarketViewV1(StrictOperatorContract):
    market_code: str = Field(min_length=1, max_length=100)
    market_label: str = Field(min_length=1, max_length=200)
    settlement_policy_label: str = Field(min_length=1, max_length=200)


class OfficialOfferViewV1(StrictOperatorContract):
    kind: Literal["official_offer_v1"] = "official_offer_v1"
    official_match_no: str = Field(min_length=1, max_length=20)
    match_label: str = Field(min_length=1, max_length=300)
    competition_label: str = Field(min_length=1, max_length=200)
    kickoff_at: AwareDatetime
    sale_opens_at: AwareDatetime
    sale_deadline_at: AwareDatetime
    offer_state: Literal["upcoming", "open", "closed", "cancelled"]
    markets: list[OfferMarketViewV1] = Field(max_length=100)
    evidence_complete_count: int = Field(ge=0, strict=True)
    evidence_required_count: int = Field(ge=0, strict=True)
    next_action: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _validate_offer(self) -> "OfficialOfferViewV1":
        if self.sale_opens_at >= self.sale_deadline_at:
            raise ValueError("sale opening must precede deadline")
        if self.evidence_complete_count > self.evidence_required_count:
            raise ValueError("complete evidence cannot exceed required evidence")
        return self


class OfficialSaleSlateViewV1(StrictOperatorContract):
    kind: Literal["official_sale_slate_v1"] = "official_sale_slate_v1"
    lane: OperatorLane
    business_key: str = Field(min_length=1, max_length=100)
    revision_no: int = Field(gt=0, strict=True)
    state: Literal["current", "superseded", "invalid"]
    published_at: AwareDatetime
    retrieved_at: AwareDatetime
    next_deadline_at: AwareDatetime | None = None
    total_offer_count: int = Field(ge=0, strict=True)
    open_offer_count: int = Field(ge=0, strict=True)
    offers: list[OfficialOfferViewV1] = Field(max_length=100)

    @model_validator(mode="after")
    def _validate_slate_counts(self) -> "OfficialSaleSlateViewV1":
        if self.total_offer_count != len(self.offers):
            raise ValueError("slate offer count must match returned offers")
        visible_open = sum(item.offer_state in {"upcoming", "open"} for item in self.offers)
        if self.open_offer_count != visible_open:
            raise ValueError("slate open count must match actionable offers")
        return self


WorkItemScopeKind = Literal["sale_wave", "artifact", "ticket", "review"]
WorkItemPhase = Literal[
    "prepare_evidence",
    "judge_matches",
    "compare_tickets",
    "audit_deployment",
    "await_confirmation",
    "await_result",
    "review",
    "complete",
    "blocked",
]
DeploymentOutcome = Literal[
    "pending",
    "placed",
    "partially_placed",
    "no_ticket",
    "expired",
]

_PHASE_INDEX = {
    "prepare_evidence": 0,
    "judge_matches": 1,
    "compare_tickets": 2,
    "audit_deployment": 3,
    "await_confirmation": 4,
    "await_result": 5,
    "review": 6,
    "complete": 7,
}


def _validate_scope_phase_outcome(
    *,
    scope_kind: str,
    phase: str,
    deployment_outcome: str | None,
) -> None:
    if phase == "blocked":
        phase_allowed = True
    elif scope_kind == "sale_wave":
        phase_allowed = phase in _PHASE_INDEX
    elif scope_kind == "artifact":
        phase_allowed = phase in _PHASE_INDEX and _PHASE_INDEX[phase] >= 4
    elif scope_kind == "ticket":
        phase_allowed = phase in _PHASE_INDEX and _PHASE_INDEX[phase] >= 5
    else:
        phase_allowed = phase in {"review", "complete"}
    if not phase_allowed:
        raise ValueError("phase is not legal for the work-item scope")

    if scope_kind in {"ticket", "review"}:
        if deployment_outcome is not None:
            raise ValueError("ticket and review work items have no deployment outcome")
        return
    if deployment_outcome is None:
        raise ValueError("sale and artifact work items require a deployment outcome")
    if scope_kind == "artifact" and deployment_outcome == "partially_placed":
        raise ValueError("an artifact cannot be partially placed")


class OperatorWorkItemViewV1(StrictOperatorContract):
    kind: Literal["operator_work_item_v1"] = "operator_work_item_v1"
    work_item_key: str = Field(pattern=r"^[a-z][a-z0-9-]{8,100}$")
    scope_kind: WorkItemScopeKind
    scope_label: str = Field(min_length=1, max_length=300)
    phase: WorkItemPhase
    deployment_outcome: DeploymentOutcome | None
    next_deadline_at: AwareDatetime | None = None
    is_current: bool
    snapshot_token: str = Field(min_length=1, max_length=8192)
    progress: WorkItemProgressViewV1
    blocking_reason: OperatorBlockViewV1 | None = None
    next_action: WorkItemActionViewV1 | None = None
    audit_href: str | None = Field(
        default=None,
        pattern=r"^/operator-next/audit/",
        min_length=1,
        max_length=9000,
    )

    @model_validator(mode="after")
    def _validate_work_item(self) -> "OperatorWorkItemViewV1":
        _validate_scope_phase_outcome(
            scope_kind=self.scope_kind,
            phase=self.phase,
            deployment_outcome=self.deployment_outcome,
        )
        return self


class TodayWorkItemViewV1(StrictOperatorContract):
    kind: Literal["today_work_item_v1"] = "today_work_item_v1"
    lane: OperatorLane
    business_key: str = Field(min_length=1, max_length=100)
    task_label: str = Field(min_length=1, max_length=300)
    scope_kind: WorkItemScopeKind
    scope_label: str = Field(min_length=1, max_length=300)
    phase: WorkItemPhase
    deployment_outcome: DeploymentOutcome | None
    next_deadline_at: AwareDatetime | None = None
    progress: WorkItemProgressViewV1
    blocking_reason: OperatorBlockViewV1 | None = None
    next_action: WorkItemActionViewV1

    @model_validator(mode="after")
    def _validate_today_work_item(self) -> "TodayWorkItemViewV1":
        _validate_scope_phase_outcome(
            scope_kind=self.scope_kind,
            phase=self.phase,
            deployment_outcome=self.deployment_outcome,
        )
        return self


class LaneScheduleRecoveryViewV1(StrictOperatorContract):
    kind: Literal["lane_schedule_recovery_v1"] = "lane_schedule_recovery_v1"
    lane: OperatorLane
    shanghai_check_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    recovery_key: str = Field(min_length=1, max_length=200)
    phase: Literal["waiting_schedule"] = "waiting_schedule"
    last_check_state: str | None = Field(default=None, min_length=1, max_length=100)
    last_checked_at: AwareDatetime | None = None
    last_source_run_state: str | None = Field(default=None, min_length=1, max_length=100)
    blocking_reason: OperatorBlockViewV1
    next_action: WorkItemActionViewV1


TodayQueueEntryV1 = Annotated[
    TodayWorkItemViewV1 | LaneScheduleRecoveryViewV1,
    Field(discriminator="kind"),
]


class OperatorTodayResponseV1(VersionedOperatorContract):
    kind: Literal["operator_today_v1"] = "operator_today_v1"
    as_of: AwareDatetime
    next_action: TodayQueueEntryV1 | None
    entries: list[TodayQueueEntryV1]

    @model_validator(mode="after")
    def _validate_next_action(self) -> "OperatorTodayResponseV1":
        expected = self.entries[0] if self.entries else None
        if self.next_action != expected:
            raise ValueError("today next action must be the first queue entry")
        return self


class OperatorTaskSummaryV1(StrictOperatorContract):
    kind: Literal["operator_task_summary_v1"] = "operator_task_summary_v1"
    lane: OperatorLane
    business_key: str = Field(min_length=1, max_length=100)
    task_label: str = Field(min_length=1, max_length=300)
    task_state: Literal["current", "archive"]
    current_slate: OfficialSaleSlateViewV1
    work_items: list[OperatorWorkItemViewV1]

    @model_validator(mode="after")
    def _validate_task_lane(self) -> "OperatorTaskSummaryV1":
        if self.current_slate.lane is not self.lane:
            raise ValueError("task and current slate must use the same lane")
        if self.current_slate.business_key != self.business_key:
            raise ValueError("task and current slate must use the same business key")
        return self


class OperatorLaneResponseV1(VersionedOperatorContract):
    kind: Literal["operator_lane_v1"] = "operator_lane_v1"
    lane: OperatorLane
    as_of: AwareDatetime
    focus_business_key: str | None = Field(default=None, min_length=1, max_length=100)
    current_tasks: list[OperatorTaskSummaryV1]
    archive_tasks: list[OperatorTaskSummaryV1]

    @model_validator(mode="after")
    def _validate_lane_tasks(self) -> "OperatorLaneResponseV1":
        tasks = self.current_tasks + self.archive_tasks
        if any(task.lane is not self.lane for task in tasks):
            raise ValueError("lane response cannot contain tasks from another lane")
        if any(task.task_state != "current" for task in self.current_tasks):
            raise ValueError("current task list contains an archive task")
        if any(task.task_state != "archive" for task in self.archive_tasks):
            raise ValueError("archive task list contains a current task")
        keys = [task.business_key for task in tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("lane response cannot repeat a business key")
        if self.focus_business_key is not None and self.focus_business_key not in keys:
            raise ValueError("lane focus must name a returned task")
        return self


class OperatorTaskState(StrEnum):
    WAITING_DATA = 'waiting_data'
    PREPARE = 'prepare'
    JUDGE_MATCHES = 'judge_matches'
    CONSTRUCT_TICKET = 'construct_ticket'
    AUDIT_DEPLOYMENT = 'audit_deployment'
    AWAIT_CONFIRMATION = 'await_confirmation'
    AWAIT_LEDGER = 'await_ledger'
    AWAIT_RESULT = 'await_result'
    REVIEW = 'review'
    COMPLETE = 'complete'
    BLOCKED = 'blocked'


class OperatorTaskSummary(StrictOperatorContract):
    task_id: str = Field(min_length=1)
    lane: OperatorLane
    business_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    state: OperatorTaskState
    deadline_at: AwareDatetime | None = None
    waiting_until: AwareDatetime | None = None
    is_actionable: bool
    next_action_label: str = Field(min_length=1)
    priority_rank: int = Field(ge=0)
    block_reason_code: str | None = None


class TaskProgressSummary(StrictOperatorContract):
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    label: str


class BusinessEvidenceSummary(StrictOperatorContract):
    label: str
    value: str
    source_label: str | None = None
    freshness_label: str | None = None
    severity: Literal['info', 'warn', 'error'] = 'info'
    evidence_href: str | None = None


class EvidenceFieldSummary(StrictOperatorContract):
    label: str
    value: str


class OperatorEvidenceResponse(VersionedOperatorContract):
    task_id: str
    evidence_key: str
    title: str
    source_label: str
    observed_at: AwareDatetime | None = None
    freshness_label: str | None = None
    fields: list[EvidenceFieldSummary]
    audit_href: str | None = None


class PrescriptionDifferenceSummary(StrictOperatorContract):
    match_no: int = Field(ge=1, le=14)
    prescribed_faces: str
    candidate_faces: str
    registered_rule_ids: list[str] = Field(default_factory=list)


class OperatorRecoverySummary(StrictOperatorContract):
    code: OperatorRecoveryCode
    missing: str
    impact: str
    action_label: str
    retry_at: AwareDatetime | None = None
    href: str | None = None


class WaitingDataStep(StrictOperatorContract):
    kind: Literal['waiting_data'] = 'waiting_data'
    task_id: str
    title: str
    recovery: OperatorRecoverySummary


class PrepareStep(StrictOperatorContract):
    kind: Literal['prepare'] = 'prepare'
    task_id: str
    title: str
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    recovery: OperatorRecoverySummary


class EvidenceRequirementSummary(StrictOperatorContract):
    requirement_id: Literal["E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC"]
    label: str = Field(min_length=1)
    state: Literal["complete", "missing", "stale", "conflict"]
    detail: str = Field(min_length=1)


class MatchEvidenceChecklist(StrictOperatorContract):
    official_match_no: str = Field(min_length=1)
    match_label: str = Field(min_length=1)
    complete: bool
    completed_requirement_count: int = Field(ge=0)
    required_requirement_count: int = Field(gt=0)
    requirements: list[EvidenceRequirementSummary]


class PrepareEvidenceStep(StrictOperatorContract):
    kind: Literal["prepare_evidence"] = "prepare_evidence"
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    gate_state: Literal["complete", "missing", "stale", "conflict"]
    freeze_state: Literal["not_requested", "queued", "linked", "failed"]
    complete_match_count: int = Field(ge=0)
    required_match_count: int = Field(ge=0)
    matches: list[MatchEvidenceChecklist]
    new_evidence_available: bool = False
    freeze_command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    requirement_revision_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )


class JudgmentFaceView(StrictOperatorContract):
    face_code: str = Field(min_length=1, max_length=50)
    face_label: str = Field(min_length=1, max_length=100)
    prior_probability_decimal: str = Field(pattern=r"^(?:0|1)\.\d{12}$")
    movement_pp_decimal: str = Field(pattern=r"^-?\d+\.\d{12}$")
    belief_probability_decimal: str = Field(pattern=r"^(?:0|1)\.\d{12}$")


class JudgmentFactorView(StrictOperatorContract):
    factor_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    scope_key: str = Field(min_length=1, max_length=200)
    evidence_ref_tokens: list[str] = Field(min_length=1, max_length=100)


class JudgmentRuleView(StrictOperatorContract):
    rule_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)


class JudgmentFaceBundleView(StrictOperatorContract):
    bundle_code: str = Field(min_length=1, max_length=100)
    face_codes: list[str] = Field(min_length=1, max_length=100)


class MatchJudgmentEditorView(StrictOperatorContract):
    official_match_no: str = Field(min_length=1, max_length=20)
    match_label: str = Field(min_length=1, max_length=300)
    competition_label: str = Field(min_length=1, max_length=200)
    kickoff_at: AwareDatetime
    sale_deadline_at: AwareDatetime
    market_code: str = Field(min_length=1, max_length=100)
    market_label: str = Field(min_length=1, max_length=200)
    evidence: list[BusinessEvidenceSummary]
    evidence_ref_tokens: list[str] = Field(min_length=1, max_length=500)
    faces: list[JudgmentFaceView] = Field(min_length=2, max_length=100)
    factors: list[JudgmentFactorView] = Field(max_length=100)
    rules: list[JudgmentRuleView] = Field(max_length=100)
    face_bundles: list[JudgmentFaceBundleView] = Field(min_length=1, max_length=100)


class BaselineEnvelopeOfferView(StrictOperatorContract):
    official_match_no: str = Field(min_length=1, max_length=20)
    match_label: str = Field(min_length=1, max_length=300)
    market_code: str = Field(min_length=1, max_length=100)
    market_label: str = Field(min_length=1, max_length=200)
    face_bundles: list[JudgmentFaceBundleView] = Field(min_length=1, max_length=100)
    omission_available: bool


class BaselineEnvelopeStructureView(StrictOperatorContract):
    kind: Literal["jczq_pass", "zucai_group"]
    structure_code: str = Field(min_length=1, max_length=100)
    structure_label: str = Field(min_length=1, max_length=200)
    eligible_official_match_nos: list[str] = Field(min_length=1, max_length=100)
    pass_size: int | None = Field(default=None, gt=0)
    required_offer_count: int = Field(gt=0)
    maximum_groups: int = Field(gt=0)


class BaselineEnvelopeEditorView(StrictOperatorContract):
    lane: OperatorLane
    ticket_kinds: list[Literal["jczq_pass", "sfc", "renjiu"]]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    capital_cap_minor: int = Field(gt=0)
    maximum_ticket_count: int = Field(gt=0)
    maximum_exhaustive_candidate_count: int = Field(gt=0)
    offers: list[BaselineEnvelopeOfferView] = Field(min_length=1, max_length=100)
    structures: list[BaselineEnvelopeStructureView] = Field(min_length=1, max_length=100)


class JudgeMatchesStep(StrictOperatorContract):
    kind: Literal['judge_matches'] = 'judge_matches'
    task_id: str
    item_key: str
    title: str
    prompt: str
    options: list[str]
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    mode: Literal[
        "legacy",
        "baseline_envelope",
        "match_judgment",
        "prescription_ready",
    ] = "legacy"
    comparison_only: bool = False
    completed_match_count: int = Field(default=0, ge=0)
    required_match_count: int = Field(default=0, ge=0)
    envelope: BaselineEnvelopeEditorView | None = None
    editor: MatchJudgmentEditorView | None = None
    envelope_command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    judgment_command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    prescription_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    judgment_revision_tokens: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _validate_editor_mode(self) -> "JudgeMatchesStep":
        if self.completed_match_count > self.required_match_count:
            raise ValueError("completed match count cannot exceed required match count")
        if self.mode == "baseline_envelope":
            if self.envelope is None or self.envelope_command_token is None:
                raise ValueError("baseline envelope mode requires editor and command token")
        elif self.mode == "match_judgment":
            if self.editor is None or self.judgment_command_token is None:
                raise ValueError("match judgment mode requires editor and command token")
        elif self.mode == "prescription_ready":
            if self.prescription_command_token is None or not self.judgment_revision_tokens:
                raise ValueError("prescription mode requires current judgments and command token")
        return self


class TicketVersionSummary(StrictOperatorContract):
    candidate_id: str
    label: str
    faces: dict[str, str]
    notes: int = Field(gt=0)
    cost_yuan: int = Field(gt=0)
    p_all: float = Field(ge=0, le=1)
    expected_broken: float = Field(ge=0)
    within_cap: bool | None = None
    common_dead_faces: list[str] = Field(default_factory=list)
    prescription_differences: list[PrescriptionDifferenceSummary] = Field(
        default_factory=list
    )


class CandidateAuditFindingView(StrictOperatorContract):
    audit_kind: Literal["legs", "prescription_difference", "budget", "deployment"]
    finding_code: str = Field(min_length=1, max_length=100)
    severity: Literal["WARN", "ERROR"]
    message: str = Field(min_length=1, max_length=1000)
    rule_id: str | None = Field(default=None, min_length=1, max_length=100)


class CandidateCompositionView(StrictOperatorContract):
    singles: list[str] = Field(default_factory=list, max_length=100)
    doubles: list[str] = Field(default_factory=list, max_length=100)
    full_covers: list[str] = Field(default_factory=list, max_length=100)
    omissions: list[str] = Field(default_factory=list, max_length=100)
    pass_groups: list[str] = Field(default_factory=list, max_length=100)


class CandidateComparisonView(StrictOperatorContract):
    code: str = Field(min_length=1, max_length=100)
    partition: Literal["eligible", "audit_blocked", "over_cap"]
    rank: int | None = Field(default=None, gt=0)
    selectable: bool
    deployable: bool
    candidate_token: str | None = Field(default=None, min_length=1, max_length=8192)
    composition: CandidateCompositionView
    ticket_count: int = Field(gt=0)
    distinct_note_count: int = Field(gt=0)
    paid_note_unit_count: int = Field(gt=0)
    stake_minor: int = Field(gt=0)
    capital_utilization_decimal: str = Field(pattern=r"^\d+\.\d{12}$")
    objective_label: str = Field(min_length=1, max_length=200)
    objective_probability_decimal: str = Field(pattern=r"^(?:0|1)\.\d{12}$")
    expected_broken_legs_decimal: str = Field(pattern=r"^\d+\.\d{12}$")
    break_even_bonus_minor: int | None = Field(default=None, gt=0)
    break_even_to_official_median_decimal: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d{12}$",
    )
    common_dead_faces: list[str] = Field(default_factory=list, max_length=500)
    prescription_differences: list[PrescriptionDifferenceSummary] = Field(
        default_factory=list,
        max_length=100,
    )
    audit_findings: list[CandidateAuditFindingView] = Field(
        default_factory=list,
        max_length=500,
    )
    market_difference: str | None = Field(default=None, max_length=500)
    odds_band: Literal["10x", "20x", "50x", "100x"] | None = None
    target_odds_min_decimal: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d{12}$",
    )
    target_odds_max_decimal: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d{12}$",
    )
    combined_decimal_odds: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d{12}$",
    )
    parent_candidate_revision_id: str | None = Field(
        default=None,
        min_length=1,
    )
    delta_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _validate_partition(self) -> "CandidateComparisonView":
        if self.partition == "eligible":
            if self.rank is None:
                raise ValueError("eligible candidate requires rank")
        elif self.rank is not None:
            raise ValueError("ineligible candidate cannot have rank")
        if self.deployable and self.partition != "eligible":
            raise ValueError("only eligible candidates can be deployable")
        if self.partition == "over_cap" and self.selectable:
            raise ValueError("over-cap candidates cannot be selected")
        if self.selectable != (self.candidate_token is not None):
            raise ValueError("only selectable candidates receive a selection token")
        band_values = (
            self.odds_band,
            self.target_odds_min_decimal,
            self.target_odds_max_decimal,
            self.combined_decimal_odds,
        )
        if any(value is not None for value in band_values) and any(
            value is None for value in band_values
        ):
            raise ValueError("candidate odds band metadata must be complete")
        if self.odds_band is not None:
            minimum = Decimal(self.target_odds_min_decimal or "0")
            maximum = Decimal(self.target_odds_max_decimal or "0")
            combined = Decimal(self.combined_decimal_odds or "0")
            if not minimum <= combined < maximum:
                raise ValueError("candidate combined odds are outside the target interval")
        if (self.parent_candidate_revision_id is None) != (self.delta_reason is None):
            raise ValueError("candidate parent and delta reason must be paired")
        return self


class CandidateBandOutcomeView(StrictOperatorContract):
    odds_band: Literal["10x", "20x", "50x", "100x"]
    status: Literal["candidates", "no_feasible_candidate"]
    candidate_count: int = Field(ge=0)
    reason_code: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_outcome(self) -> "CandidateBandOutcomeView":
        if self.status == "candidates":
            if self.candidate_count < 1 or self.reason_code is not None:
                raise ValueError("populated odds band must report candidates")
        elif self.candidate_count != 0 or self.reason_code is None:
            raise ValueError("empty odds band requires a reason code")
        return self


class JczqBoardProgressV1(VersionedOperatorContract):
    kind: Literal["jczq_board_progress_v1"] = "jczq_board_progress_v1"
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    total: int = Field(ge=0)
    researched: int = Field(ge=0)
    rejected: int = Field(ge=0)
    price_only: int = Field(ge=0)
    match_ids: list[str]

    @model_validator(mode="after")
    def _validate_reconciliation(self) -> "JczqBoardProgressV1":
        if self.total != self.researched + self.rejected + self.price_only:
            raise ValueError("board terminal-state counts do not reconcile")
        if self.total != len(self.match_ids) or len(set(self.match_ids)) != self.total:
            raise ValueError("board terminal-state match ids do not reconcile")
        return self


class JczqDecisionTerminalV1(VersionedOperatorContract):
    kind: Literal["selected", "no_ticket"]
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    selection_revision_id: str | None = None
    no_ticket_revision_id: str | None = None
    candidate_set_revision_id: str | None = None
    audit_complete: bool

    @model_validator(mode="after")
    def _validate_terminal(self) -> "JczqDecisionTerminalV1":
        if self.kind == "selected":
            if (
                self.selection_revision_id is None
                or self.candidate_set_revision_id is None
                or self.no_ticket_revision_id is not None
            ):
                raise ValueError("selected terminal lineage is incomplete")
        elif (
            self.no_ticket_revision_id is None
            or self.selection_revision_id is not None
            or self.candidate_set_revision_id is not None
        ):
            raise ValueError("no-ticket terminal lineage is incomplete")
        return self


class CandidateSetComparisonView(StrictOperatorContract):
    label: str = Field(min_length=1, max_length=200)
    comparison_only: bool
    candidates: list[CandidateComparisonView]
    band_outcomes: list[CandidateBandOutcomeView] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_comparison_only(self) -> "CandidateSetComparisonView":
        if self.band_outcomes:
            expected = {"10x", "20x", "50x", "100x"}
            if (
                {outcome.odds_band for outcome in self.band_outcomes} != expected
                or len(self.band_outcomes) != len(expected)
            ):
                raise ValueError("candidate set requires one outcome for every odds band")
            counts = {
                band: sum(candidate.odds_band == band for candidate in self.candidates)
                for band in expected
            }
            if any(
                outcome.candidate_count != counts[outcome.odds_band]
                for outcome in self.band_outcomes
            ):
                raise ValueError("candidate band outcome count does not reconcile")
        elif not self.candidates:
            raise ValueError("candidate set requires candidates or band outcomes")
        if self.comparison_only and any(
            candidate.selectable
            or candidate.deployable
            or candidate.candidate_token is not None
            for candidate in self.candidates
        ):
            raise ValueError("comparison-only candidates cannot be selected or deployed")
        if not self.comparison_only:
            for candidate in self.candidates:
                expected_deployable = candidate.partition == "eligible"
                if candidate.deployable != expected_deployable:
                    raise ValueError("judgment candidates have invalid deployment state")
        return self


class ConstructTicketStep(StrictOperatorContract):
    kind: Literal['construct_ticket'] = 'construct_ticket'
    task_id: str
    mode: Literal["legacy", "candidate_request", "candidate_comparison"] = "legacy"
    prescription: dict[str, str] = Field(default_factory=dict)
    candidates: list[TicketVersionSummary] = Field(default_factory=list)
    request_generation_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    market_prior_baseline_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    baseline_envelope_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    judgment_prescription_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    selection_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    selection_completed: bool = False
    selected_candidate_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    candidate_sets: list[CandidateSetComparisonView] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_mode(self) -> "ConstructTicketStep":
        if self.mode == "candidate_request":
            request_tokens = (
                self.request_generation_token,
                self.market_prior_baseline_token,
                self.baseline_envelope_token,
                self.judgment_prescription_token,
            )
            if (
                any(token is None for token in request_tokens)
                or self.selection_command_token is not None
                or self.selection_completed
                or self.selected_candidate_code is not None
                or self.candidate_sets
            ):
                raise ValueError("candidate request mode requires exact lineage tokens")
        elif self.mode == "candidate_comparison":
            request_tokens = (
                self.request_generation_token,
                self.market_prior_baseline_token,
                self.baseline_envelope_token,
                self.judgment_prescription_token,
            )
            if self.selection_completed:
                selected_codes = {
                    candidate.code
                    for candidate_set in self.candidate_sets
                    if not candidate_set.comparison_only
                    for candidate in candidate_set.candidates
                }
                invalid_selection_state = (
                    self.selection_command_token is not None
                    or self.selected_candidate_code not in selected_codes
                    or any(
                        candidate.selectable
                        or candidate.candidate_token is not None
                        for candidate_set in self.candidate_sets
                        for candidate in candidate_set.candidates
                    )
                )
            else:
                invalid_selection_state = (
                    self.selection_command_token is None
                    or self.selected_candidate_code is not None
                    or any(
                        candidate.selectable
                        != (candidate.partition != "over_cap")
                        for candidate_set in self.candidate_sets
                        if not candidate_set.comparison_only
                        for candidate in candidate_set.candidates
                    )
                )
            if (
                not self.candidate_sets
                or invalid_selection_state
                or any(token is not None for token in request_tokens)
            ):
                raise ValueError("candidate comparison mode requires persisted candidate sets")
        return self


class DeploymentCandidateSummary(StrictOperatorContract):
    label: str = Field(min_length=1, max_length=100)
    ticket_count: int = Field(gt=0)
    stake_minor: int = Field(gt=0)
    objective_label: str = Field(min_length=1, max_length=200)
    objective_probability_decimal: str = Field(pattern=r"^(?:0|1)\.\d{12}$")


class DeploymentAuditFindingSummary(StrictOperatorContract):
    severity: Literal["warn", "error"]
    label: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=1000)
    evidence_href: str | None = None
    finding_token: str | None = Field(default=None, min_length=1, max_length=8192)


class DeploymentRuleOption(StrictOperatorContract):
    label: str = Field(min_length=1, max_length=200)
    token: str = Field(min_length=1, max_length=8192)


class NoTicketControl(StrictOperatorContract):
    state: Literal["available", "recorded"]
    command_token: str = Field(min_length=1, max_length=8192)
    no_ticket_revision_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    comparison_candidate_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    rule_options: list[DeploymentRuleOption] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _validate_state(self) -> "NoTicketControl":
        if (self.state == "recorded") != (self.no_ticket_revision_token is not None):
            raise ValueError("recorded no-ticket requires its current revision token")
        return self


class AuditDeploymentStep(StrictOperatorContract):
    kind: Literal['audit_deployment'] = 'audit_deployment'
    surface_version: Literal["1", "2"] = "1"
    task_id: str
    candidate: TicketVersionSummary | DeploymentCandidateSummary
    gate_candidate_id: str | None = None
    gate_candidate_cost_yuan: int | None = Field(default=None, gt=0)
    audit_state: Literal['pass', 'warn', 'error']
    findings: list[BusinessEvidenceSummary | DeploymentAuditFindingSummary]
    deployment_state: Literal['pass', 'review', 'reduce_or_empty'] | None = None
    capital_utilization: float | None = Field(default=None, ge=0)
    median_bonus: float | None = Field(default=None, ge=0)
    break_even_to_median: float | None = Field(default=None, ge=0)
    allowed_decisions: list[str] = Field(default_factory=list)
    mode: Literal[
        "legacy",
        "create_ticket_batch",
        "adjudicate_audit_warn",
        "approve_ticket_batch",
        "request_confirmation",
        "supersede_no_ticket",
        "blocked",
    ] = "legacy"
    command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    candidate_selection_token: str | None = Field(default=None, min_length=1, max_length=8192)
    ticket_batch_token: str | None = Field(default=None, min_length=1, max_length=8192)
    audit_override_ticket_batch_token: str | None = Field(
        default=None,
        exclude=True,
        min_length=1,
        max_length=8192,
    )
    ticket_artifact_token: str | None = Field(default=None, min_length=1, max_length=8192)
    no_ticket_command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    no_ticket_revision_token: str | None = Field(default=None, min_length=1, max_length=8192)
    comparison_candidate_token: str | None = Field(default=None, min_length=1, max_length=8192)
    rule_options: list[DeploymentRuleOption] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _validate_surface(self) -> "AuditDeploymentStep":
        if self.surface_version == "1":
            required = (
                self.gate_candidate_id,
                self.gate_candidate_cost_yuan,
                self.deployment_state,
                self.capital_utilization,
                self.median_bonus,
                self.break_even_to_median,
            )
            if self.mode != "legacy" or any(value is None for value in required):
                raise ValueError("legacy deployment requires the complete deployment gate")
            return self
        if self.mode == "legacy" or self.no_ticket_command_token is None:
            raise ValueError("v2 deployment requires a named mode and no-ticket command")
        required_by_mode = {
            "create_ticket_batch": self.candidate_selection_token,
            "adjudicate_audit_warn": self.ticket_batch_token,
            "approve_ticket_batch": self.ticket_batch_token,
            "request_confirmation": self.ticket_artifact_token,
            "supersede_no_ticket": self.no_ticket_revision_token,
        }
        required = required_by_mode.get(self.mode)
        if self.mode != "blocked" and (self.command_token is None or required is None):
            raise ValueError("v2 deployment mode is missing its exact command tokens")
        if self.audit_override_ticket_batch_token is not None and not (
            self.mode == "blocked" and self.audit_state == "error"
        ):
            raise ValueError(
                "audit override token is restricted to a blocked v2 ERROR deployment"
            )
        return self


class ConfirmationStep(StrictOperatorContract):
    kind: Literal['await_confirmation'] = 'await_confirmation'
    surface_version: Literal["1", "2"] = "1"
    task_id: str
    ticket_artifact_id: str | None = None
    amount: float | None = Field(default=None, gt=0)
    amount_minor: int | None = Field(default=None, gt=0, strict=True)
    currency: str
    deadline_at: AwareDatetime
    confirmation_state: Literal['not_issued', 'open', 'expired']
    confirmation_expires_at: AwareDatetime | None = None
    command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    ticket_artifact_token: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def _validate_surface(self) -> "ConfirmationStep":
        if self.surface_version == "1":
            if (
                self.ticket_artifact_id is None
                or self.amount is None
                or self.amount_minor is not None
                or self.command_token is not None
                or self.ticket_artifact_token is not None
            ):
                raise ValueError("legacy confirmation requires its artifact and decimal amount")
            return self
        if self.ticket_artifact_id is not None or self.amount is not None:
            raise ValueError("v2 confirmation cannot expose an artifact ID or float amount")
        if self.amount_minor is None:
            raise ValueError("v2 confirmation requires an integer minor-unit amount")
        if self.confirmation_state == "not_issued" and (
            self.command_token is None or self.ticket_artifact_token is None
        ):
            raise ValueError("requestable confirmation requires exact signed tokens")
        if self.confirmation_state != "not_issued" and (
            self.command_token is not None or self.ticket_artifact_token is not None
        ):
            raise ValueError("non-requestable confirmation cannot expose command tokens")
        return self


class LedgerStep(StrictOperatorContract):
    kind: Literal['await_ledger'] = 'await_ledger'
    task_id: str
    ticket_artifact_id: str
    placement_state: Literal['unplaced', 'placed', 'shadow']
    amount: float
    currency: str
    external_reference: str | None = None


class ResultSourceSummary(StrictOperatorContract):
    source_label: str = Field(min_length=1, max_length=100)
    state: Literal["available", "missing", "invalid"]
    result_label: str | None = Field(default=None, min_length=1, max_length=100)
    captured_at: AwareDatetime | None = None
    source_kind: Literal[
        "api_football",
        "sporttery_game90",
        "okooo_manual",
    ] | None = None
    source_disposition: Literal[
        "played_90",
        "postponed",
        "official_void",
    ] | None = None
    home_90: int | None = Field(default=None, ge=0)
    away_90: int | None = Field(default=None, ge=0)
    invalid_code: Literal[
        "artifact_unreadable",
        "schema_mismatch",
        "invalid_score",
        "source_identity_mismatch",
        "unsupported_status",
    ] | None = None

    @model_validator(mode="after")
    def _validate_source_state(self) -> "ResultSourceSummary":
        if self.state == "missing" and (
            self.result_label is not None or self.captured_at is not None
        ):
            raise ValueError("a missing result source has no captured result")
        return self


class ResultMatchSummary(StrictOperatorContract):
    official_match_no: str = Field(min_length=1, max_length=20)
    match_label: str = Field(min_length=1, max_length=300)
    agreement_state: Literal["missing", "conflict", "agreed"]
    result_disposition: Literal["played_90", "postponed", "official_void"] | None = None
    home_90: int | None = Field(default=None, ge=0)
    away_90: int | None = Field(default=None, ge=0)
    sources: list[ResultSourceSummary] = Field(min_length=3, max_length=3)
    outcome_state: Literal["waiting", "committed", "corrected"] = "waiting"

    @model_validator(mode="after")
    def _validate_normalized_result(self) -> "ResultMatchSummary":
        scores = (self.home_90, self.away_90)
        if self.agreement_state != "agreed":
            if self.result_disposition is not None or any(score is not None for score in scores):
                raise ValueError("an unagreed result cannot expose a normalized result")
            return self
        if self.result_disposition is None:
            raise ValueError("an agreed result requires a disposition")
        if self.result_disposition == "played_90":
            if any(score is None for score in scores):
                raise ValueError("a played result requires both 90-minute scores")
        elif any(score is not None for score in scores):
            raise ValueError("a non-played result cannot have a score")
        return self

    @property
    def score_label(self) -> str | None:
        if self.result_disposition != "played_90":
            return None
        return f"{self.home_90} - {self.away_90}"

    @property
    def available_source_count(self) -> int:
        return sum(source.state == "available" for source in self.sources)


class ResultPrizeTierSummary(StrictOperatorContract):
    tier_label: str = Field(min_length=1, max_length=100)
    tier_code: Literal["sfc_first", "sfc_second", "renjiu_first"] | None = None
    ticket_kind: Literal["sfc", "renjiu"] | None = None
    required_correct_count: int = Field(ge=0)
    official_winning_note_count: int = Field(ge=0)
    payout_minor_per_winning_note: int = Field(ge=0)


class SettlementCashEntrySummary(StrictOperatorContract):
    transaction_kind: Literal["payout", "payout_reversal"]
    amount_minor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    replaces_prior_payout: bool


class SettlementLegSummary(StrictOperatorContract):
    match_label: str = Field(min_length=1, max_length=300)
    market_label: str = Field(min_length=1, max_length=100)
    selection_label: str = Field(min_length=1, max_length=100)
    result_label: str = Field(min_length=1, max_length=100)
    grade: Literal["won", "lost", "void"]
    leg_index: int = Field(default=0, ge=0)
    official_match_no: str | None = Field(default=None, min_length=1, max_length=20)
    market_code: str | None = Field(default=None, min_length=1, max_length=100)
    selection_code: str | None = Field(default=None, min_length=1, max_length=100)
    result_disposition: Literal[
        "played_90",
        "postponed",
        "official_void",
    ] | None = None
    market_result_code: str | None = Field(default=None, min_length=1, max_length=100)
    leg_grade: Literal["won", "lost", "void"] | None = None
    booked_decimal_odds: str | None = Field(default=None, min_length=1, max_length=100)
    settlement_parameter_decimal: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )


class SettlementNoteSummary(StrictOperatorContract):
    note_number: int = Field(ge=1)
    structure_label: str = Field(min_length=1, max_length=100)
    grade: Literal["won", "lost", "void"]
    unit_count: int = Field(gt=0)
    correct_leg_count: int = Field(ge=0)
    void_leg_count: int = Field(ge=0)
    prize_label: str | None = Field(default=None, min_length=1, max_length=100)
    payout_minor: int = Field(ge=0)
    legs: list[SettlementLegSummary]
    note_index: int = Field(default=0, ge=0)
    group_label: str | None = Field(default=None, min_length=1, max_length=100)
    note_grade: Literal["won", "lost", "void"] | None = None
    winning_unit_count: int = Field(default=0, ge=0)
    void_unit_count: int = Field(default=0, ge=0)
    stake_minor: int = Field(default=0, ge=0)
    prize_tier_code: Literal[
        "sfc_first",
        "sfc_second",
        "renjiu_first",
    ] | None = None


class SettlementTicketSummary(StrictOperatorContract):
    ticket_number: int = Field(ge=1)
    ticket_kind_label: str = Field(min_length=1, max_length=100)
    settlement_state: Literal["settled", "corrected"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    stake_minor: int = Field(gt=0)
    paid_note_unit_count: int = Field(gt=0)
    winning_note_unit_count: int = Field(ge=0)
    void_note_unit_count: int = Field(ge=0)
    payout_minor: int = Field(ge=0)
    notes: list[SettlementNoteSummary] = Field(min_length=1)
    ticket_label: str | None = Field(default=None, min_length=1, max_length=200)
    revision_no: int = Field(default=1, ge=1)
    corrected: bool = False
    settlement_method_label: str | None = Field(default=None, min_length=1, max_length=100)
    rounding_policy_label: str | None = Field(default=None, min_length=1, max_length=100)
    distinct_note_count: int = Field(default=0, ge=0)
    cash_entries: list[SettlementCashEntrySummary] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ticket_counts(self) -> "SettlementTicketSummary":
        if (
            self.winning_note_unit_count + self.void_note_unit_count
            > self.paid_note_unit_count
        ):
            raise ValueError("winning and void units cannot exceed paid units")
        return self


class TaskSettlementSkipSummary(StrictOperatorContract):
    ticket_label: str = Field(min_length=1, max_length=200)
    reason_code: Literal[
        "already_current",
        "result_not_ready",
        "prize_not_ready",
        "placement_integrity_blocked",
    ]


class TaskSettlementRunSummary(StrictOperatorContract):
    requested_ticket_count: int = Field(ge=0)
    eligible_ticket_count: int = Field(ge=0)
    settled_ticket_count: int = Field(ge=0)
    skipped_ticket_count: int = Field(ge=0)
    persisted_settlement_count: int = Field(ge=0)
    skips: list[TaskSettlementSkipSummary] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_run_counts(self) -> "TaskSettlementRunSummary":
        if self.requested_ticket_count != (
            self.eligible_ticket_count + self.skipped_ticket_count
        ):
            raise ValueError("requested settlements must reconcile to eligible and skipped")
        if self.eligible_ticket_count != self.settled_ticket_count:
            raise ValueError("eligible settlements must reconcile to settled")
        if self.persisted_settlement_count != self.settled_ticket_count:
            raise ValueError("persisted settlements must reconcile to settled")
        if len(self.skips) != self.skipped_ticket_count:
            raise ValueError("settlement skip rows must reconcile to skipped count")
        return self


class AwaitResultStep(StrictOperatorContract):
    kind: Literal['await_result'] = 'await_result'
    task_id: str
    title: str
    expected_at: AwareDatetime | None = None
    surface_version: Literal["1", "2"] = "1"
    result_state: Literal[
        "not_imported",
        "missing",
        "conflict",
        "postponed",
        "ready",
        "corrected",
    ] | None = None
    result_matches: list[ResultMatchSummary] = Field(default_factory=list)
    prize_state: Literal["not_applicable", "missing", "ready"] | None = None
    prize_published_at: AwareDatetime | None = None
    prize_tiers: list[ResultPrizeTierSummary] = Field(default_factory=list)
    settlement_state: Literal[
        "not_requested",
        "queued",
        "result_waiting",
        "prize_waiting",
        "integrity_blocked",
        "settled",
        "corrected",
        "not_applicable",
    ] | None = None
    settlement_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    total_stake_minor: int = Field(default=0, ge=0)
    total_payout_minor: int = Field(default=0, ge=0)
    tickets: list[SettlementTicketSummary] = Field(default_factory=list)
    result_cutoff_at: AwareDatetime | None = None
    settlement_ready: bool = False
    request_state: Literal[
        "not_requested",
        "queued",
        "completed",
        "rejected",
    ] = "not_requested"
    placed_ticket_count: int = Field(default=0, ge=0)
    settled_ticket_count: int = Field(default=0, ge=0)
    blocking_codes: list[
        Literal[
            "already_current",
            "result_not_ready",
            "prize_not_ready",
            "placement_integrity_blocked",
        ]
    ] = Field(default_factory=list)
    last_run: TaskSettlementRunSummary | None = None

    @model_validator(mode="after")
    def _validate_v2_surface(self) -> "AwaitResultStep":
        if self.surface_version == "1":
            return self
        if self.result_state is None or self.prize_state is None or self.settlement_state is None:
            raise ValueError("v2 result view requires result, prize, and settlement states")
        request_ready = (
            self.result_state in {"ready", "corrected"}
            and self.prize_state in {"not_applicable", "ready"}
            and self.settlement_state == "not_requested"
        )
        if self.settlement_command_token is not None and not request_ready:
            raise ValueError("settlement command is not available for the current state")
        if self.settlement_state == "not_applicable" and (
            self.currency is not None
            or self.total_stake_minor != 0
            or self.total_payout_minor != 0
            or self.tickets
        ):
            raise ValueError("not-applicable settlement must contain no money or tickets")
        if self.settlement_state in {"settled", "corrected"}:
            if self.currency is None or not self.tickets:
                raise ValueError("a completed settlement requires currency and ticket rows")
            if any(ticket.currency != self.currency for ticket in self.tickets):
                raise ValueError("settled tickets must use the summary currency")
        if self.settlement_ready != (self.settlement_command_token is not None):
            raise ValueError("settlement readiness must reflect command availability")
        if self.settled_ticket_count > self.placed_ticket_count:
            raise ValueError("settled ticket count cannot exceed placed ticket count")
        if self.last_run is not None and (
            self.last_run.settled_ticket_count != self.settled_ticket_count
        ):
            raise ValueError("last run and settlement ticket counts must agree")
        return self


class ReviewItemSummary(StrictOperatorContract):
    item_type: Literal['prediction', 'adjudication', 'factor_verdict']
    item_id: str
    title: str
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    allowed_outcomes: list[str]


class ReviewForecastSummary(StrictOperatorContract):
    title: str = Field(min_length=1, max_length=500)
    falsifier: str = Field(min_length=1, max_length=2000)
    state: Literal["pending", "hit", "miss", "na"]
    prediction_review_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    grade_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )

    @model_validator(mode="after")
    def _validate_grade_control(self) -> "ReviewForecastSummary":
        controls = (self.prediction_review_token, self.grade_command_token)
        if self.state == "pending" and sum(value is None for value in controls) == 1:
            raise ValueError("prediction grade controls must be present together")
        if self.state != "pending" and any(value is not None for value in controls):
            raise ValueError("settled prediction cannot expose a grade control")
        return self


class ReviewMoneySummary(StrictOperatorContract):
    state: Literal["not_applicable", "settled", "corrected"]
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    stake_minor: int = Field(default=0, ge=0)
    payout_minor: int = Field(default=0, ge=0)
    pnl_minor: int = 0
    ticket_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_money_shape(self) -> "ReviewMoneySummary":
        if self.pnl_minor != self.payout_minor - self.stake_minor:
            raise ValueError("review P&L must reconcile to payout less stake")
        if self.state == "not_applicable":
            if (
                self.currency is not None
                or self.stake_minor
                or self.payout_minor
                or self.pnl_minor
                or self.ticket_count
            ):
                raise ValueError("not-applicable review money must be empty")
        elif self.currency is None or self.ticket_count == 0:
            raise ValueError("settled review money requires currency and tickets")
        return self


class ReviewEvidenceOptionSummary(StrictOperatorContract):
    label: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=8192)


class ReviewShadowOptionSummary(StrictOperatorContract):
    label: str = Field(min_length=1, max_length=500)
    state: Literal["ready", "not_ready"]
    token: str = Field(min_length=1, max_length=8192)


class ReviewInterventionSummary(StrictOperatorContract):
    disposition: Literal["undecided", "effect_required", "no_effect"]
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    required_metric_keys: list[str] = Field(default_factory=list, max_length=100)
    linked_metric_keys: list[str] = Field(default_factory=list, max_length=100)
    review_token: str = Field(min_length=1, max_length=8192)
    disposition_token: str | None = Field(default=None, min_length=1, max_length=8192)
    effect_command_token: str | None = Field(default=None, min_length=1, max_length=8192)
    observation_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    completion_command_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=8192,
    )
    evidence_options: list[ReviewEvidenceOptionSummary] = Field(
        default_factory=list,
        max_length=500,
    )
    shadow_options: list[ReviewShadowOptionSummary] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def _validate_disposition_shape(self) -> "ReviewInterventionSummary":
        required = self.required_metric_keys
        linked = self.linked_metric_keys
        if required != sorted(set(required)) or linked != sorted(set(linked)):
            raise ValueError("review metric keys must be sorted and unique")
        if any(key not in required for key in linked):
            raise ValueError("linked metrics must belong to the required metric set")
        if self.disposition == "undecided":
            if self.reason is not None or required or self.disposition_token is not None:
                raise ValueError("undecided review cannot contain a disposition")
        elif self.reason is None or self.disposition_token is None:
            raise ValueError("recorded disposition requires its reason and opaque token")
        if self.disposition == "effect_required" and not required:
            raise ValueError("effect-required review needs metric keys")
        if self.disposition == "no_effect" and (required or linked):
            raise ValueError("no-effect review cannot contain metric keys")
        return self


class ReviewCompletionGateSummary(StrictOperatorContract):
    gate: Literal["legacy_update", "observations", "shadow_reconciliation"]
    label: str = Field(min_length=1, max_length=300)
    state: Literal["pending", "complete", "not_required"]
    detail: str = Field(min_length=1, max_length=1000)


class ReviewAdjudicationSummary(StrictOperatorContract):
    decision: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    rejected_evidence_count: int = Field(ge=0, strict=True)
    created_at: AwareDatetime


class ReviewScoreboardObservationSummary(StrictOperatorContract):
    metric_key: str = Field(min_length=1, max_length=200)
    tally: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2000)
    status: str = Field(min_length=1, max_length=100)
    numerator_decimal: str | None = Field(
        default=None,
        pattern=r"^-?\d+(?:\.\d+)?$",
    )
    denominator_decimal: str | None = Field(
        default=None,
        pattern=r"^-?\d+(?:\.\d+)?$",
    )
    value_decimal: str | None = Field(
        default=None,
        pattern=r"^-?\d+(?:\.\d+)?$",
    )
    unit: str | None = Field(default=None, min_length=1, max_length=100)
    effective_at: AwareDatetime


class ReviewStep(StrictOperatorContract):
    kind: Literal['review'] = 'review'
    surface_version: Literal["1", "2"] = "1"
    task_id: str
    title: str | None = Field(default=None, min_length=1, max_length=300)
    review_kind: Literal["operational_data_availability", "forecast_truth"] | None = None
    review_state: Literal["pending", "complete"] | None = None
    scoreboard_projection_state: Literal["ready", "stale", "unavailable"] | None = None
    hit_count: int | None = None
    total_count: int | None = None
    stake_yuan: float | None = None
    payout_yuan: float | None = None
    pnl_yuan: float | None = None
    calibration_summary: str | None = None
    current_item: ReviewItemSummary | None = None
    forecast_truth: list[ReviewForecastSummary] = Field(default_factory=list, max_length=500)
    money_ledger: ReviewMoneySummary | None = None
    intervention_quality: ReviewInterventionSummary | None = None
    adjudication_history: list[ReviewAdjudicationSummary] = Field(
        default_factory=list,
        max_length=500,
    )
    scoreboard_observation_history: list[ReviewScoreboardObservationSummary] = Field(
        default_factory=list,
        max_length=500,
    )
    completion_gates: list[ReviewCompletionGateSummary] = Field(
        default_factory=list,
        max_length=3,
    )
    maintenance_href: str | None = Field(
        default=None,
        pattern=r"^/",
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def _validate_surface(self) -> "ReviewStep":
        if self.surface_version == "1":
            if self.current_item is None:
                raise ValueError("legacy review requires a current item")
            return self
        legacy_values = (
            self.hit_count,
            self.total_count,
            self.stake_yuan,
            self.payout_yuan,
            self.pnl_yuan,
            self.calibration_summary,
            self.current_item,
        )
        if any(value is not None for value in legacy_values):
            raise ValueError("v2 review cannot contain legacy aggregate fields")
        if (
            self.title is None
            or self.review_kind is None
            or self.review_state is None
            or self.scoreboard_projection_state is None
            or self.money_ledger is None
            or self.intervention_quality is None
            or self.maintenance_href is None
        ):
            raise ValueError("v2 review requires the complete focused surface")
        expected_gates = [
            "legacy_update",
            "observations",
            "shadow_reconciliation",
        ]
        if [item.gate for item in self.completion_gates] != expected_gates:
            raise ValueError("v2 review completion gates must use the governed order")
        return self


class CompleteStep(StrictOperatorContract):
    kind: Literal['complete'] = 'complete'
    task_id: str
    title: str
    summary: str


class BlockedStep(StrictOperatorContract):
    kind: Literal['blocked'] = 'blocked'
    task_id: str
    title: str
    recovery: OperatorRecoverySummary
    correlation_id: str | None = None


StepView = Annotated[
    WaitingDataStep
    | PrepareStep
    | PrepareEvidenceStep
    | JudgeMatchesStep
    | ConstructTicketStep
    | AuditDeploymentStep
    | ConfirmationStep
    | LedgerStep
    | AwaitResultStep
    | ReviewStep
    | CompleteStep
    | BlockedStep,
    Field(discriminator='kind'),
]

_PHASE_BY_STEP_KIND = {
    "waiting_data": "prepare_evidence",
    "prepare": "prepare_evidence",
    "prepare_evidence": "prepare_evidence",
    "judge_matches": "judge_matches",
    "construct_ticket": "compare_tickets",
    "audit_deployment": "audit_deployment",
    "await_confirmation": "await_confirmation",
    "await_ledger": "blocked",
    "await_result": "await_result",
    "review": "review",
    "complete": "complete",
    "blocked": "blocked",
}


class OperatorTaskDetailV1(VersionedOperatorContract):
    """One task's executable phase without expanding lane-list summaries."""

    kind: Literal["operator_task_detail_v1"] = "operator_task_detail_v1"
    as_of: AwareDatetime
    task_id: str = Field(min_length=1, max_length=220)
    lane: OperatorLane
    business_key: str = Field(min_length=1, max_length=100)
    task_label: str = Field(min_length=1, max_length=300)
    task_state: Literal["current", "archive"]
    current_slate: OfficialSaleSlateViewV1
    work_items: list[OperatorWorkItemViewV1] = Field(min_length=1)
    active_work_item: OperatorWorkItemViewV1
    step: StepView
    no_ticket: NoTicketControl | None = None

    @model_validator(mode="after")
    def _validate_task_detail(self) -> "OperatorTaskDetailV1":
        expected_task_id = f"{self.lane.value}:{self.business_key}"
        if self.task_id != expected_task_id:
            raise ValueError("task detail ID must match its lane and business key")
        if self.current_slate.lane is not self.lane:
            raise ValueError("task detail and slate must use the same lane")
        if self.current_slate.business_key != self.business_key:
            raise ValueError("task detail and slate must use the same business key")
        if self.active_work_item not in self.work_items:
            raise ValueError("active work item must be present in the task")
        expected_phase = _PHASE_BY_STEP_KIND[self.step.kind]
        if self.active_work_item.phase != expected_phase:
            raise ValueError("active phase must match the rendered step")
        return self


class OperatorWorklistResponse(VersionedOperatorContract):
    as_of: AwareDatetime
    selected: OperatorTaskSummary | None
    tasks: list[OperatorTaskSummary]


class OperatorTaskResponse(VersionedOperatorContract):
    as_of: AwareDatetime
    mutation_token: str = Field(pattern=r'^[0-9a-f]{64}$')
    selected: OperatorTaskSummary
    alternatives: list[OperatorTaskSummary]
    progress: TaskProgressSummary
    step: StepView
    no_ticket: NoTicketControl | None = None


class OperatorMutationCommand(VersionedOperatorContract):
    expected_snapshot_token: str = Field(pattern=r'^[0-9a-f]{64}$')
    idempotency_key: str = Field(min_length=1, max_length=200)


class ResolveIssueAdjudicationCommand(OperatorMutationCommand):
    adjudication_key: str
    decision: str
    reason: str = Field(min_length=1)
    selected_option: str | None = None
    evidence_rejected: list[dict[str, str]] = Field(default_factory=list)


class PrescriptionDeviationCommand(StrictOperatorContract):
    match_no: int = Field(ge=1, le=14)
    rule_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class SelectTicketVersionCommand(OperatorMutationCommand):
    candidate_id: str
    reason: str = Field(min_length=1)
    deviations: list[PrescriptionDeviationCommand] = Field(default_factory=list)


class RecordDeploymentCommand(OperatorMutationCommand):
    candidate_id: str
    decision: Literal['keep', 'drop_match', 'change_structure', 'empty_position']
    reason: str = Field(min_length=1)


class RequestTelegramConfirmationCommand(OperatorMutationCommand):
    dry_run: bool = True


class GradePredictionCommand(OperatorMutationCommand):
    prediction_id: str = Field(min_length=1)
    outcome: Literal['hit', 'miss', 'na']
    reason: str = Field(min_length=1)


class TelegramConfirmationDispatch(VersionedOperatorContract):
    ticket_artifact_id: str
    confirmation_id: str
    expires_at: AwareDatetime
    dispatch_state: Literal['dry_run', 'sent']
    message_preview: str


class OperatorCommandReceipt(VersionedOperatorContract):
    command_kind: Literal[
        "freeze_evidence",
        "record_baseline_envelope",
        "commit_match_judgment",
        "freeze_judgment_prescription",
        "request_candidate_generation",
        "select_candidate",
        "record_no_ticket",
        "supersede_no_ticket",
        "create_ticket_batch",
        "adjudicate_audit_warn",
        "approve_ticket_batch",
        "request_confirmation",
        "request_settlement",
        "grade_prediction",
        "record_scoreboard_effect_disposition",
        "record_scoreboard_observation",
        "request_scoreboard_review_completion",
        "rebuild_scoreboard_projection",
    ]
    status: Literal["queued", "completed"]
    task_key: str | None = None
    source_high_watermark: int | None = Field(default=None, ge=0)
    projection_high_watermark: int | None = Field(default=None, ge=0)
    navigation_href: str | None = Field(
        default=None,
        pattern=r"^/operator-next(?:$|/)",
        max_length=500,
    )
