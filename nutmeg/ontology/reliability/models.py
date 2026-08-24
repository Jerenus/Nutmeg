"""Immutable rows for reliability evidence and release approvals."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReliabilityEvidenceRow:
    reliability_evidence_id: str
    evidence_kind: str
    workflow: str | None
    business_date: str | None
    observed_from: str
    observed_to: str
    status: str
    report: dict[str, object]
    source_refs: list[dict[str, str]]
    content_hash: str
    recorded_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ReleaseApprovalRow:
    release_approval_id: str
    release_version: str
    evidence_snapshot_sha256: str
    policy_version: str
    reason: str
    approved_at: str
    action_id: str
