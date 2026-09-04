"""Immutable operator-domain persistence rows."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = [
    "EvidenceCoverageReceiptRow",
    "EvidenceIntakeObjectRow",
    "EvidenceIntakeReceiptRow",
    "EvidenceIntakeResult",
    "OfficialOfferFamilyRow",
    "OfficialOfferRevisionRow",
    "OfficialSaleSlateRevisionRow",
    "OfficialScheduleCheckReceiptRow",
    "SaleImportCountReceiptRow",
    "SaleImportResult",
]
