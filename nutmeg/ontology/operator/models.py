"""Immutable operator-domain persistence rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import ActionOutcome


@dataclass(frozen=True, slots=True)
class OfficialSaleSlateRevisionRow:
    slate_revision_id: str
    slate_family_id: str
    lane: str
    business_key: str
    revision_no: int
    source_artifact_retrieval_id: str
    published_at: str
    retrieved_at: str
    valid_from: str
    supersedes_slate_revision_id: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class OfficialOfferFamilyRow:
    official_offer_family_id: str
    lane: str
    business_key: str
    official_match_no: str
    match_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class OfficialOfferRevisionRow:
    official_offer_revision_id: str
    official_offer_family_id: str
    slate_revision_id: str
    match_id: str
    official_match_no: str
    market_definition_ids: tuple[str, ...]
    sale_opens_at: str
    sale_deadline_at: str
    status: str


@dataclass(frozen=True, slots=True)
class OfficialScheduleCheckReceiptRow:
    schedule_check_id: str
    action_id: str
    lane: str
    shanghai_check_date: str
    checked_at: str
    source_run_id: str
    check_state: str
    parser_contract_version: str | None
    official_source_content_hash: str | None
    official_source_artifact_retrieval_id: str | None
    observed_business_keys: tuple[str, ...]
    imported_business_keys: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class SaleImportCountReceiptRow:
    slate_revision_count: int
    offer_family_count: int
    offer_revision_count: int
    created_slate_revision_count: int
    created_offer_family_count: int
    created_offer_revision_count: int


@dataclass(frozen=True, slots=True)
class SaleImportResult:
    outcome: ActionOutcome
    slate: OfficialSaleSlateRevisionRow | None
    offers: tuple[OfficialOfferRevisionRow, ...]
    counts: SaleImportCountReceiptRow


@dataclass(frozen=True, slots=True)
class EvidenceIntakeReceiptRow:
    intake_receipt_id: str
    action_id: str
    lane: str
    business_key: str
    slate_revision_id: str
    task_snapshot_hash: str
    captured_at: str
    manifest_sha256: str
    source_retrieval_ids: tuple[str, ...]
    committed_count: int
    rejected_count: int
    skipped_count: int
    persisted_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceIntakeObjectRow:
    intake_object_id: str
    intake_receipt_id: str
    match_id: str
    object_kind: str
    object_id: str
    object_index: int
    observed_at: str
    source_retrieval_ids: tuple[str, ...]
    source_kinds: tuple[str, ...]
    source_identities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceCoverageReceiptRow:
    coverage_receipt_id: str
    intake_receipt_id: str
    match_id: str
    requirement_id: str
    subject_scope: str
    evidence_ref_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceIntakeResult:
    outcome: ActionOutcome
    receipt: EvidenceIntakeReceiptRow | None


@dataclass(frozen=True, slots=True)
class EvidenceFreezeMatchPlan:
    match_id: str
    market_snapshot_id: str | None
    prior_distribution: dict[str, float]
    candidate_observation_ids: tuple[str, ...]
    caveat_claim_ids: tuple[str, ...]
    requirement_states: tuple[tuple[str, str], ...]
    requirement_ref_tokens: tuple[str, ...]
    market_prior_ref_tokens: tuple[str, ...]
    conflicts_cleared_ref_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceFreezeGate:
    task_family_id: str
    lane: str
    business_key: str
    slate_revision_id: str
    task_snapshot_hash: str
    requirement_revision_token: str
    information_cutoff_at: datetime
    policy_version: str
    ready: bool
    required_match_count: int
    matches: tuple[EvidenceFreezeMatchPlan, ...]


@dataclass(frozen=True, slots=True)
class EvidenceFreezeRequestRow:
    evidence_freeze_request_id: str
    action_id: str
    task_family_id: str
    lane: str
    business_key: str
    slate_revision_id: str
    task_snapshot_hash: str
    requirement_revision_token: str
    information_cutoff_at: str
    policy_version: str
    dependency_fingerprint: str
    requested_at: str


@dataclass(frozen=True, slots=True)
class OperatorWorkerJobRow:
    worker_job_id: str
    job_kind: str
    source_object_type: str
    source_object_id: str
    state: str
    lease_owner: str | None
    lease_expires_at: str | None
    attempt_count: int
    available_at: str
    last_error_code: str | None
    result_action_id: str | None
    result_object_type: str | None
    result_object_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class FrozenEvidenceBundleActionRow:
    action_id: str
    action_type: str
    actor_role: str
    status: str
    policy_version: str
    evidence_bundle_id: str
    match_id: str
    information_cutoff_at: str
    market_snapshot_id: str | None
    prior_distribution: dict[str, float]
    evidence_ref_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskEvidenceBundleItemRow:
    task_evidence_bundle_item_id: str
    task_evidence_bundle_revision_id: str
    item_index: int
    match_id: str
    evidence_bundle_id: str
    freeze_bundle_action_id: str
    requirement_states: tuple[tuple[str, str], ...]
    requirement_ref_tokens: tuple[str, ...]
    market_prior_ref_tokens: tuple[str, ...]
    conflicts_cleared_ref_tokens: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class TaskEvidenceBundleRevisionRow:
    task_evidence_bundle_revision_id: str
    task_family_id: str
    lane: str
    business_key: str
    revision_no: int
    evidence_freeze_request_id: str
    link_action_id: str
    slate_revision_id: str
    task_snapshot_hash: str
    requirement_revision_token: str
    information_cutoff_at: str
    policy_version: str
    dependency_fingerprint: str
    required_match_count: int
    bundle_count: int
    item_count: int
    conflicts_cleared_count: int
    content_hash: str
    frozen_at: str
    supersedes_revision_id: str | None


@dataclass(frozen=True, slots=True)
class MarketPriorBaselineRevisionRow:
    market_prior_baseline_revision_id: str
    market_prior_baseline_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    information_cutoff_at: str
    policy_version: str
    arithmetic_version: str
    probability_precision: int
    comparison_only: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class MarketPriorBaselineProbabilityRow:
    market_prior_baseline_probability_id: str
    market_prior_baseline_revision_id: str
    item_index: int
    match_id: str
    official_offer_revision_id: str
    market_definition_id: str
    face_code: str
    probability_decimal: str
    market_snapshot_id: str
    quote_id: str
    booked_decimal_odds: str
    quote_captured_at: str
    settlement_parameter_decimal: str | None


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeRevisionRow:
    baseline_envelope_revision_id: str
    baseline_envelope_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    ticket_kind: str
    capital_cap_minor: int
    currency: str
    maximum_ticket_count: int
    maximum_exhaustive_candidate_count: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeOfferConstraintRow:
    baseline_envelope_offer_constraint_id: str
    baseline_envelope_revision_id: str
    constraint_index: int
    official_match_no: str
    market_code: str
    omission_allowed: int


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeFaceBundleRow:
    baseline_envelope_face_bundle_id: str
    baseline_envelope_offer_constraint_id: str
    bundle_index: int
    bundle_code: str


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeBundleFaceRow:
    baseline_envelope_bundle_face_id: str
    baseline_envelope_face_bundle_id: str
    face_index: int
    face_code: str


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeStructureTemplateRow:
    baseline_envelope_structure_template_id: str
    baseline_envelope_revision_id: str
    template_index: int
    kind: str
    structure_code: str
    pass_size: int | None
    required_offer_count: int
    maximum_groups: int


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeTemplateOfferRow:
    baseline_envelope_template_offer_id: str
    baseline_envelope_structure_template_id: str
    offer_index: int
    official_match_no: str


@dataclass(frozen=True, slots=True)
class OperatorMatchJudgmentRevisionRow:
    operator_match_judgment_revision_id: str
    operator_match_judgment_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    match_id: str
    official_offer_revision_id: str
    market_definition_id: str
    forecast_revision_id: str
    falsifier: str
    rationale: str
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class OperatorMatchJudgmentStructureFacts:
    """锚方完整度 + 逐面先例生死：C5/C7/C13/C14 唯一的操作员输入。

    ``face_precedents`` 元素形如 ``(face_code, precedent_ref, "alive" | "dead")``，
    顺序与操作员登记顺序一致；没有登记过结构事实的历史修订读回 ``unknown`` 与空元组。
    """

    anchor_integrity: str
    face_precedents: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class JudgmentPrescriptionRevisionRow:
    judgment_prescription_revision_id: str
    judgment_prescription_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    required_match_count: int
    judgment_count: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class JudgmentPrescriptionItemRow:
    operator_judgment_prescription_item_id: str
    judgment_prescription_revision_id: str
    item_index: int
    match_id: str
    operator_match_judgment_revision_id: str


@dataclass(frozen=True, slots=True)
class CandidateGenerationRequestRow:
    generation_request_id: str
    action_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    fixed_prize_policy_revision_id: str | None
    dependency_fingerprint: str
    expected_current_revision_no: int
    content_hash: str
    requested_at: str


@dataclass(frozen=True, slots=True)
class TicketCandidateSetRevisionRow:
    candidate_set_revision_id: str
    candidate_set_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    generation_request_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    set_kind: str
    comparison_only: int
    generator_version: str
    audit_policy_version: str
    candidate_count: int
    eligible_count: int
    audit_blocked_count: int
    over_cap_count: int
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TicketCandidateRow:
    candidate_revision_id: str
    candidate_set_revision_id: str
    candidate_index: int
    candidate_code: str
    partition: str
    rank: int | None
    eligible: int
    deployable: int
    leg_audit_completed: int
    prescription_audit_completed: int
    budget_check_completed: int
    deployment_report_completed: int
    content_hash: str
    odds_band: str | None = None
    target_odds_min_decimal: str | None = None
    target_odds_max_decimal: str | None = None
    combined_decimal_odds: str | None = None
    parent_candidate_revision_id: str | None = None
    delta_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateBandOutcomeRow:
    candidate_band_outcome_id: str
    candidate_set_revision_id: str
    odds_band: str
    status: str
    candidate_count: int
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class JczqBoardResearchStateRow:
    board_research_state_id: str
    business_date: str
    match_id: str
    official_match_no: str
    status: str
    source_run_id: str | None
    artifact_id: str | None
    captured_at: str | None
    kickoff_at: str
    historical_replay: int
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CandidateMetricRow:
    candidate_metric_id: str
    candidate_revision_id: str
    currency: str
    ticket_count: int
    distinct_note_count: int
    paid_note_unit_count: int
    stake_minor: int
    capital_utilization_decimal: str
    probability_kind: str
    objective_probability_decimal: str
    expected_broken_legs_decimal: str
    break_even_bonus_minor: int | None
    break_even_to_official_median_decimal: str | None


@dataclass(frozen=True, slots=True)
class CandidateDeadFaceRow:
    candidate_dead_face_id: str
    candidate_revision_id: str
    dead_face_index: int
    official_match_no: str
    face_code: str


@dataclass(frozen=True, slots=True)
class CandidateAuditFindingRow:
    candidate_audit_finding_id: str
    candidate_revision_id: str
    finding_index: int
    audit_kind: str
    finding_code: str
    severity: str
    message: str
    official_match_no: str | None
    rule_id: str | None


@dataclass(frozen=True, slots=True)
class CandidateSelectionRow:
    candidate_selection_id: str
    candidate_selection_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    candidate_set_revision_id: str
    candidate_revision_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    reason: str
    content_hash: str
    action_id: str
    selected_at: str


@dataclass(frozen=True, slots=True)
class TicketDecisionLineageRevisionRow:
    lineage_revision_id: str
    lineage_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    ticket_batch_revision_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    candidate_set_revision_id: str
    candidate_selection_id: str
    candidate_revision_id: str
    audit_policy_version: str
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TicketDecisionLineageItemRow:
    lineage_item_id: str
    lineage_revision_id: str
    item_index: int
    candidate_ticket_id: str
    ticket_index: int
    candidate_ticket_leg_id: str
    leg_index: int
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    market_prior_baseline_probability_id: str
    operator_match_judgment_revision_id: str
    forecast_revision_id: str


@dataclass(frozen=True, slots=True)
class TicketAuditOverrideReceiptRow:
    ticket_audit_override_receipt_id: str
    action_id: str
    receipt_index: int
    adjudication_id: str
    ticket_batch_revision_id: str
    lineage_revision_id: str
    candidate_revision_id: str
    candidate_content_hash: str
    candidate_audit_finding_id: str
    finding_code: str
    audit_policy_version: str
    reason: str
    rule_ids: tuple[str, ...]
    evidence_rejected: tuple[dict[str, str], ...]
    recorded_at: str


@dataclass(frozen=True, slots=True)
class CandidateGenerationOverrideLinkRow:
    candidate_generation_override_link_id: str
    generation_request_id: str
    override_receipt_id: str
    link_index: int
    created_at: str


@dataclass(frozen=True, slots=True)
class NoTicketRevisionRow:
    no_ticket_revision_id: str
    no_ticket_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    action_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    reason_code: str
    reason_basis: str
    reason_text: str
    rule_ids: tuple[str, ...]
    phase: str
    requirement_snapshot_hash: str | None
    missing_requirement_ids: tuple[str, ...]
    stale_requirement_ids: tuple[str, ...]
    conflicting_requirement_ids: tuple[str, ...]
    market_prior_baseline_revision_id: str | None
    baseline_envelope_revision_id: str | None
    candidate_set_revision_id: str | None
    comparison_candidate_revision_id: str | None
    deployment_outcome: str
    content_hash: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class NoTicketOfferScopeRow:
    no_ticket_offer_scope_id: str
    no_ticket_revision_id: str
    scope_index: int
    official_offer_revision_id: str
    effective_cutoff_at: str


@dataclass(frozen=True, slots=True)
class NoTicketArtifactScopeRow:
    no_ticket_artifact_scope_id: str
    no_ticket_revision_id: str
    scope_index: int
    ticket_artifact_id: str
    effective_cutoff_at: str


@dataclass(frozen=True, slots=True)
class NoTicketCommandReceiptRow:
    no_ticket_command_receipt_id: str
    action_id: str
    command_kind: str
    no_ticket_revision_id: str | None
    task_family_id: str
    work_item_id: str
    submitted_task_snapshot_hash: str
    resolved_task_snapshot_hash: str
    result: str
    received_at: str


@dataclass(frozen=True, slots=True)
class ArtifactWorkItemLinkRow:
    artifact_work_item_link_id: str
    ticket_artifact_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    action_id: str
    linked_at: str


@dataclass(frozen=True, slots=True)
class ProtectedArtifactBindingRow:
    protected_artifact_binding_id: str
    ticket_artifact_id: str
    lineage_revision_id: str
    candidate_revision_id: str
    candidate_ticket_id: str
    ticket_index: int
    ticket_kind: str
    stake_minor: int
    currency: str
    composition_hash: str
    fixed_prize_policy_revision_id: str | None
    frozen_deadline_at: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProtectedArtifactOfferRevisionLinkRow:
    protected_artifact_offer_revision_link_id: str
    ticket_artifact_id: str
    offer_index: int
    official_offer_revision_id: str


@dataclass(frozen=True, slots=True)
class ConfirmationChallengeRevisionRow:
    challenge_revision_id: str
    challenge_family_id: str
    legacy_confirmation_id: str | None
    revision_no: int
    supersedes_revision_id: str | None
    ticket_artifact_id: str
    artifact_composition_hash: str
    lineage_revision_id: str
    nonce_hash: str
    issued_at: str
    effective_cutoff_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ConfirmationChallengeHeadRow:
    ticket_artifact_id: str
    challenge_revision_id: str
    challenge_family_id: str
    revision_no: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class ArtifactTerminalReceiptRow:
    artifact_terminal_receipt_id: str
    ticket_artifact_id: str
    challenge_revision_id: str | None
    terminal_kind: str
    terminal_reason: str
    effective_cutoff_at: str
    terminal_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ReviewEligibilityFactRow:
    review_eligibility_fact_id: str
    action_id: str
    fact_index: int
    terminal_trigger: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    no_ticket_revision_id: str | None
    artifact_terminal_receipt_id: str | None
    market_prior_baseline_revision_id: str | None
    review_kind: str
    readiness_condition: str
    content_hash: str
    created_at: str
    settlement_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ZucaiFixedPrizePolicyRevisionRow:
    fixed_prize_policy_revision_id: str
    fixed_prize_policy_family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    policy_version: str
    ticket_kind: str
    currency: str
    standard_unit_stake_minor: int
    official_void_rule: str
    effective_at: str
    content_hash: str
    action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ZucaiFixedPrizePolicyTierRow:
    fixed_prize_policy_tier_id: str
    fixed_prize_policy_revision_id: str
    tier_index: int
    tier_code: str
    required_correct_count: int


@dataclass(frozen=True, slots=True)
class CandidateTicketRow:
    candidate_ticket_id: str
    candidate_revision_id: str
    ticket_index: int
    ticket_kind: str
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    composition_hash: str
    fixed_prize_policy_revision_id: str | None


@dataclass(frozen=True, slots=True)
class CandidateTicketLegRow:
    candidate_ticket_leg_id: str
    candidate_ticket_id: str
    leg_index: int
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    quote_id: str | None
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None


__all__ = [
    "ArtifactTerminalReceiptRow",
    "ArtifactWorkItemLinkRow",
    "BaselineEnvelopeBundleFaceRow",
    "BaselineEnvelopeFaceBundleRow",
    "BaselineEnvelopeOfferConstraintRow",
    "BaselineEnvelopeRevisionRow",
    "BaselineEnvelopeStructureTemplateRow",
    "BaselineEnvelopeTemplateOfferRow",
    "CandidateAuditFindingRow",
    "CandidateBandOutcomeRow",
    "JczqBoardResearchStateRow",
    "CandidateDeadFaceRow",
    "CandidateGenerationRequestRow",
    "CandidateGenerationOverrideLinkRow",
    "CandidateMetricRow",
    "CandidateSelectionRow",
    "CandidateTicketLegRow",
    "CandidateTicketRow",
    "ConfirmationChallengeHeadRow",
    "ConfirmationChallengeRevisionRow",
    "EvidenceCoverageReceiptRow",
    "EvidenceFreezeGate",
    "EvidenceFreezeMatchPlan",
    "EvidenceFreezeRequestRow",
    "EvidenceIntakeObjectRow",
    "EvidenceIntakeReceiptRow",
    "EvidenceIntakeResult",
    "FrozenEvidenceBundleActionRow",
    "JudgmentPrescriptionItemRow",
    "JudgmentPrescriptionRevisionRow",
    "MarketPriorBaselineProbabilityRow",
    "MarketPriorBaselineRevisionRow",
    "NoTicketArtifactScopeRow",
    "NoTicketCommandReceiptRow",
    "NoTicketOfferScopeRow",
    "NoTicketRevisionRow",
    "OfficialOfferFamilyRow",
    "OfficialOfferRevisionRow",
    "OfficialSaleSlateRevisionRow",
    "OfficialScheduleCheckReceiptRow",
    "OperatorWorkerJobRow",
    "ProtectedArtifactBindingRow",
    "ProtectedArtifactOfferRevisionLinkRow",
    "ReviewEligibilityFactRow",
    "OperatorMatchJudgmentRevisionRow",
    "SaleImportCountReceiptRow",
    "SaleImportResult",
    "TaskEvidenceBundleItemRow",
    "TaskEvidenceBundleRevisionRow",
    "TicketCandidateRow",
    "TicketCandidateSetRevisionRow",
    "TicketAuditOverrideReceiptRow",
    "TicketDecisionLineageItemRow",
    "TicketDecisionLineageRevisionRow",
    "ZucaiFixedPrizePolicyRevisionRow",
    "ZucaiFixedPrizePolicyTierRow",
]
