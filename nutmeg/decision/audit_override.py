"""Human-only conversion of disclosed audit ERRORs into typed Adjudications."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.legs_audit import (
    Finding,
    deviation_registrations,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, canonical_json
from nutmeg.ontology.actions.protected_ticket_actions import ticket_audit_finding_id
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest


class AuditOverrideError(RuntimeError):
    """The explicit operator override is incomplete or could not be recorded."""


@dataclass(frozen=True)
class AuditOverrideResult:
    error_count: int
    adjudication_count: int
    action_ids: tuple[str, ...]


def _finding_dict(finding: Finding) -> dict[str, object]:
    return {
        "level": finding.level,
        "code": finding.code,
        "match_no": finding.match_no,
        "message": finding.message,
        "since": finding.since,
    }


def record_user_overrides(
    payload: dict,
    findings: list[Finding],
    *,
    workflow_actions,
    requested_at: datetime,
) -> AuditOverrideResult:
    """Record one judge-operator Adjudication per ERROR match, exactly once."""
    errors = [finding for finding in findings if finding.level == "ERROR"]
    grouped: dict[int, list[Finding]] = defaultdict(list)
    for finding in errors:
        if finding.match_no is None:
            raise AuditOverrideError("票级 ERROR 不能按 user_naked_wheels 通道覆盖")
        grouped[finding.match_no].append(finding)
    if not grouped:
        return AuditOverrideResult(0, 0, ())

    registry = deviation_registrations(payload)
    issue = str(payload.get("issue", "")).strip()
    if not issue:
        raise AuditOverrideError("--user-override requires a nonblank issue")
    legs = payload.get("legs", {})
    prescription = payload.get("prescription", {})
    if not isinstance(legs, dict) or not isinstance(prescription, dict):
        raise AuditOverrideError("--user-override requires object legs and prescription")

    payload_digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    source_revision_id = f"manual-audit-{payload_digest[:32]}"
    prepared: list[tuple[int, RecordAdjudicationRequest]] = []
    for match_no, match_findings in sorted(grouped.items()):
        candidates = [
            item
            for item in registry.get(match_no, ())
            if item.user_override and item.reason and item.known_rule_ids
        ]
        if not candidates:
            raise AuditOverrideError(
                f"场{match_no} ERROR 缺完整 override 登记"
                "（需 user_override=true、reason、已登记 rule_ids）"
            )
        registration = candidates[0]
        leg = legs.get(str(match_no))
        ticket_faces = str(leg.get("faces", "")) if isinstance(leg, dict) else ""
        prescription_faces = str(prescription.get(str(match_no), ""))
        finding_rows = [_finding_dict(finding) for finding in match_findings]
        evidence_rejected = [
            {
                "object_type": "ticket_audit_finding",
                "object_id": ticket_audit_finding_id(source_revision_id, finding),
            }
            for finding in finding_rows
        ]
        subject_material = {
            "source_revision_id": source_revision_id,
            "match_no": match_no,
            "finding_ids": [item["object_id"] for item in evidence_rejected],
        }
        subject_digest = hashlib.sha256(
            canonical_json(subject_material).encode("utf-8")
        ).hexdigest()
        subject_id = f"tao-{subject_digest[:32]}"
        alternative = {
            "kind": "ticket_audit_user_override",
            "scoreboard_metric": (
                "user_naked_wheels" if len(set(ticket_faces)) == 1 else "user_structure_overrides"
            ),
            "issue": issue,
            "match_no": match_no,
            "ticket_faces": ticket_faces,
            "prescription_faces": prescription_faces,
            "rule_ids": list(registration.known_rule_ids),
            "audit_findings": finding_rows,
        }
        prepared.append((
            match_no,
            RecordAdjudicationRequest(
                subject_type="ticket_audit_finding",
                subject_id=subject_id,
                decision="override",
                reason=registration.reason,
                evidence_rejected=evidence_rejected,
                alternative=alternative,
                supersedes_adjudication_id=None,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"audit-override:{subject_id}",
                requested_at=requested_at,
            ),
        ))

    action_ids: list[str] = []
    for match_no, request in prepared:
        outcome = workflow_actions.record_adjudication(request)
        if outcome.status is not ActionStatus.COMMITTED:
            raise AuditOverrideError(
                f"场{match_no} override Action {outcome.status.value}: {outcome.error_code}"
            )
        action_ids.append(outcome.action_id)
    return AuditOverrideResult(len(errors), len(action_ids), tuple(action_ids))
