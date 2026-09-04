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


__all__ = [
    "EvidenceCoverageReceiptRow",
    "EvidenceFreezeGate",
    "EvidenceFreezeMatchPlan",
    "EvidenceFreezeRequestRow",
    "EvidenceIntakeObjectRow",
    "EvidenceIntakeReceiptRow",
    "EvidenceIntakeResult",
    "FrozenEvidenceBundleActionRow",
    "OfficialOfferFamilyRow",
    "OfficialOfferRevisionRow",
    "OfficialSaleSlateRevisionRow",
    "OfficialScheduleCheckReceiptRow",
    "OperatorWorkerJobRow",
    "SaleImportCountReceiptRow",
    "SaleImportResult",
    "TaskEvidenceBundleItemRow",
    "TaskEvidenceBundleRevisionRow",
]
