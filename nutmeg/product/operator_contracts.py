from __future__ import annotations

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
    code: str
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


class ConstructTicketStep(StrictOperatorContract):
    kind: Literal['construct_ticket'] = 'construct_ticket'
    task_id: str
    prescription: dict[str, str]
    candidates: list[TicketVersionSummary]


class AuditDeploymentStep(StrictOperatorContract):
    kind: Literal['audit_deployment'] = 'audit_deployment'
    task_id: str
    candidate: TicketVersionSummary
    gate_candidate_id: str
    gate_candidate_cost_yuan: int = Field(gt=0)
    audit_state: Literal['pass', 'warn', 'error']
    findings: list[BusinessEvidenceSummary]
    deployment_state: Literal['pass', 'review', 'reduce_or_empty']
    capital_utilization: float = Field(ge=0)
    median_bonus: float = Field(ge=0)
    break_even_to_median: float = Field(ge=0)
    allowed_decisions: list[str]


class ConfirmationStep(StrictOperatorContract):
    kind: Literal['await_confirmation'] = 'await_confirmation'
    task_id: str
    ticket_artifact_id: str
    amount: float = Field(gt=0)
    currency: str
    deadline_at: AwareDatetime
    confirmation_state: Literal['not_issued', 'open', 'expired']
    confirmation_expires_at: AwareDatetime | None = None


class LedgerStep(StrictOperatorContract):
    kind: Literal['await_ledger'] = 'await_ledger'
    task_id: str
    ticket_artifact_id: str
    placement_state: Literal['unplaced', 'placed', 'shadow']
    amount: float
    currency: str
    external_reference: str | None = None


class AwaitResultStep(StrictOperatorContract):
    kind: Literal['await_result'] = 'await_result'
    task_id: str
    title: str
    expected_at: AwareDatetime | None = None


class ReviewItemSummary(StrictOperatorContract):
    item_type: Literal['prediction', 'adjudication', 'factor_verdict']
    item_id: str
    title: str
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    allowed_outcomes: list[str]


class ReviewStep(StrictOperatorContract):
    kind: Literal['review'] = 'review'
    task_id: str
    hit_count: int | None = None
    total_count: int | None = None
    stake_yuan: float | None = None
    payout_yuan: float | None = None
    pnl_yuan: float | None = None
    calibration_summary: str | None = None
    current_item: ReviewItemSummary


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
        "rebuild_scoreboard_projection",
    ]
    status: Literal["queued", "completed"]
    task_key: str | None = None
    source_high_watermark: int | None = Field(default=None, ge=0)
    projection_high_watermark: int | None = Field(default=None, ge=0)
