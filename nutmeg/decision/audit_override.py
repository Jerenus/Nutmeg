"""Human-only conversion of disclosed audit ERRORs into typed Adjudications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.legs_audit import (
    Finding,
    deviation_registrations,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.operator.decision_actions import (
    RecordTicketAuditOverrideRequest,
    TicketAuditOverrideInput,
)


class AuditOverrideError(RuntimeError):
    """The explicit operator override is incomplete or could not be recorded."""


@dataclass(frozen=True)
class AuditOverrideResult:
    error_count: int
    adjudication_count: int
    action_ids: tuple[str, ...]


def record_user_overrides(
    payload: dict,
    findings: list[Finding],
    *,
    decision_actions,
    ticket_batch_token: str,
    requested_at: datetime,
) -> AuditOverrideResult:
    """Record the exact current ERROR set through the human-only outer Action."""
    errors = [finding for finding in findings if finding.level == "ERROR"]
    if not errors:
        return AuditOverrideResult(0, 0, ())
    context = decision_actions.ticket_audit_override_context(ticket_batch_token)
    local_signatures = sorted(
        (finding.code, None if finding.match_no is None else str(finding.match_no))
        for finding in errors
    )
    current_signatures = sorted(
        (
            finding.finding_code,
            (
                None
                if finding.official_match_no is None
                else str(int(finding.official_match_no))
            ),
        )
        for finding in context.findings
    )
    if local_signatures != current_signatures:
        raise AuditOverrideError(
            "legs file ERROR set differs from the signed current ticket batch"
        )
    registry = deviation_registrations(payload)
    prepared: list[TicketAuditOverrideInput] = []
    for finding in context.findings:
        if finding.official_match_no is None:
            raise AuditOverrideError("票级 ERROR 没有可引用的人工偏离登记")
        match_no = int(finding.official_match_no)
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
        prepared.append(
            TicketAuditOverrideInput(
                finding_token=finding.finding_token,
                reason=registration.reason,
                rule_ids=registration.known_rule_ids,
            )
        )
    outcome = decision_actions.record_ticket_audit_override(
        RecordTicketAuditOverrideRequest(
            ticket_batch_token=ticket_batch_token,
            expected_snapshot_token=context.expected_snapshot_token,
            overrides=tuple(prepared),
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=(
                f"audit-override:{context.ticket_batch_revision_id}"
            ),
            requested_at=requested_at,
        )
    )
    if outcome.status is not ActionStatus.COMMITTED:
        raise AuditOverrideError(
            f"override Action {outcome.status.value}: {outcome.error_code}"
        )
    adjudication_count = sum(
        ref.object_type == "adjudication" for ref in outcome.result_refs
    )
    return AuditOverrideResult(
        len(errors),
        adjudication_count,
        (outcome.action_id,),
    )
