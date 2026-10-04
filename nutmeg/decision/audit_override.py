"""Human-only conversion of disclosed audit ERRORs into typed Adjudications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.legs_audit import (
    DeviationRegistration,
    Finding,
    deviation_registrations,
    ticket_deviation_registrations,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole


class AuditOverrideError(RuntimeError):
    """The explicit operator override is incomplete or could not be recorded."""


@dataclass(frozen=True)
class AuditOverrideResult:
    error_count: int
    adjudication_count: int
    action_ids: tuple[str, ...]


def record_user_override_adjudications(
    payload: dict,
    findings: list[Finding],
    *,
    workflow,
    requested_at: datetime,
) -> AuditOverrideResult:
    """2026-10-01（operator_* 退役前置片）：行权只写 Adjudication，不再碰 operator 票批/收据。

    先把每条 ERROR 的偏离登记全部核完（缺一条整批不写），再逐条 `record_adjudication`：
    subject = 期:场号（票级 ERROR 用 期:ticket），decision = evidence_rejected，
    evidence_rejected = 被驳回的审计码与原文，alternative = 登记的 rule_ids 与所选面。
    """
    from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest

    errors = [finding for finding in findings if finding.level == "ERROR"]
    if not errors:
        return AuditOverrideResult(0, 0, ())
    issue = str(payload.get("issue") or "")
    registry = deviation_registrations(payload)
    ticket_registry = ticket_deviation_registrations(payload)
    legs = payload.get("legs") or {}
    prepared: list[tuple[Finding, DeviationRegistration]] = []
    for finding in errors:
        if finding.match_no is None:
            candidates = [
                item for item in ticket_registry
                if item.user_override and item.reason and item.known_rule_ids
                and (not item.audit_code or item.audit_code == finding.code)
            ]
            if not candidates:
                raise AuditOverrideError(
                    f"票级 ERROR（{finding.code}）缺完整 override 登记"
                    "（需 scope='ticket'、user_override=true、reason、已登记 rule_ids）"
                )
        else:
            candidates = [
                item for item in registry.get(int(finding.match_no), ())
                if item.user_override and item.reason and item.known_rule_ids
            ]
            if not candidates:
                raise AuditOverrideError(
                    f"场{finding.match_no} ERROR 缺完整 override 登记"
                    "（需 user_override=true、reason、已登记 rule_ids）"
                )
        prepared.append((finding, candidates[0]))
    action_ids: list[str] = []
    adjudications = 0
    for finding, registration in prepared:
        subject = (f"{issue}:{finding.match_no}" if finding.match_no is not None
                   else f"{issue}:ticket")
        leg = legs.get(str(finding.match_no)) if finding.match_no is not None else None
        outcome = workflow.record_adjudication(RecordAdjudicationRequest(
            subject_type="zucai_match" if finding.match_no is not None else "zucai_ticket",
            subject_id=subject,
            decision="evidence_rejected",
            reason=registration.reason,
            evidence_rejected=[{"code": finding.code, "message": finding.message,
                                "since": finding.since}],
            alternative={"rule_ids": list(registration.known_rule_ids),
                         "faces": (leg or {}).get("faces", "") if isinstance(leg, dict) else ""},
            supersedes_adjudication_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=(f"audit-override:{issue}:{finding.code}:{finding.match_no}:"
                             f"{requested_at.date().isoformat()}"),
            requested_at=requested_at,
        ))
        if outcome.status is not ActionStatus.COMMITTED:
            raise AuditOverrideError(
                f"override Action {outcome.status.value}: {outcome.error_code}"
            )
        action_ids.append(outcome.action_id)
        adjudications += sum(ref.object_type == "adjudication" for ref in outcome.result_refs)
    return AuditOverrideResult(len(errors), adjudications, tuple(action_ids))

