from __future__ import annotations

import re
from datetime import datetime

from nutmeg.decision.legs_audit import DEVIATION_RULE_IDS
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.contracts import ProductActionRequest, ProductActionResponse
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_contracts import (
    RecordDeploymentCommand,
    RequestTelegramConfirmationCommand,
    ResolveIssueAdjudicationCommand,
    SelectTicketVersionCommand,
    TelegramConfirmationDispatch,
)
from nutmeg.product.operator_queries import OperatorQueryService


def _zucai_issue(task_id: str) -> str:
    match = re.fullmatch(r"zucai:(\d{5})", task_id)
    if match is None:
        raise ProductActionBlockedError("this action requires a Zucai issue task")
    return match.group(1)


def _parse_aware(value: str | datetime, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


class OperatorActionService:
    def __init__(
        self,
        *,
        queries: OperatorQueryService,
        action_gateway: ProductActionGateway,
        telegram_confirmation=None,
        telegram_owner_chat_id: int | None = None,
    ) -> None:
        self._queries = queries
        self._actions = action_gateway
        self._telegram = telegram_confirmation
        self._owner_chat_id = telegram_owner_chat_id

    @property
    def action_gateway(self):
        return self._actions

    @property
    def telegram(self):
        return self._telegram

    @staticmethod
    def _require_judge(actor_id: str, actor_role: ActorRole) -> None:
        if actor_role is not ActorRole.JUDGE_OPERATOR or not actor_id.strip():
            raise ProductActionBlockedError("operator mutation requires judge_operator")

    def _current_task(self, task_id: str, expected_snapshot_token: str):
        task = self._queries.task(task_id, as_of=self._queries.now())
        if task.mutation_token != expected_snapshot_token:
            raise ProductActionBlockedError(
                "operator task changed after the form was opened"
            )
        return task

    def resolve_issue_adjudication(
        self,
        task_id: str,
        command: ResolveIssueAdjudicationCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ProductActionResponse:
        self._require_judge(actor_id, actor_role)
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "judge_matches":
            raise ProductActionBlockedError("task is no longer awaiting adjudication")
        if task.step.item_key != command.adjudication_key:
            raise ProductActionBlockedError("adjudication is no longer current")
        return self._execute_adjudication(
            issue=_zucai_issue(task_id),
            decision=command.decision,
            reason=command.reason,
            evidence_rejected=command.evidence_rejected,
            alternative={
                "rx_adjudication_id": command.adjudication_key,
                "selected_option": command.selected_option,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def select_ticket_version(
        self,
        task_id: str,
        command: SelectTicketVersionCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ProductActionResponse:
        self._require_judge(actor_id, actor_role)
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "construct_ticket":
            raise ProductActionBlockedError("task is no longer constructing a ticket")
        valid = {item.candidate_id for item in task.step.candidates}
        if command.candidate_id not in valid:
            raise ProductActionBlockedError("candidate is no longer available")
        candidate = next(
            item for item in task.step.candidates if item.candidate_id == command.candidate_id
        )
        expected_matches = {item.match_no for item in candidate.prescription_differences}
        submitted_matches = {item.match_no for item in command.deviations}
        if submitted_matches != expected_matches:
            missing = sorted(expected_matches - submitted_matches)
            extra = sorted(submitted_matches - expected_matches)
            missing_text = ", ".join(str(item) for item in missing) or "无"
            raise ProductActionBlockedError(
                f"场 {missing_text} 缺少偏离登记或提交了额外场次 {extra}"
            )
        if any(
            rule_id not in DEVIATION_RULE_IDS
            for item in command.deviations
            for rule_id in item.rule_ids
        ):
            raise ProductActionBlockedError("处方偏离引用了未知规则 ID")
        registry = [
            {
                "match_no": item.match_no,
                "rule_ids": sorted(set(item.rule_ids)),
                "reason": item.reason,
            }
            for item in sorted(command.deviations, key=lambda item: item.match_no)
        ]
        return self._execute_adjudication(
            issue=_zucai_issue(task_id),
            decision="select_ticket",
            reason=command.reason,
            evidence_rejected=[],
            alternative={
                "candidate_id": command.candidate_id,
                "deviation_registry": registry,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def record_deployment(
        self,
        task_id: str,
        command: RecordDeploymentCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ProductActionResponse:
        self._require_judge(actor_id, actor_role)
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "audit_deployment":
            raise ProductActionBlockedError("task is no longer at deployment")
        if command.candidate_id != task.step.candidate.candidate_id:
            raise ProductActionBlockedError("deployment candidate changed")
        if command.decision not in task.step.allowed_decisions:
            raise ProductActionBlockedError(
                "deployment decision is not allowed by current gate"
            )
        return self._execute_adjudication(
            issue=_zucai_issue(task_id),
            decision="deployment",
            reason=command.reason,
            evidence_rejected=[],
            alternative={
                "candidate_id": command.candidate_id,
                "deployment_decision": command.decision,
                "deployment_state": task.step.deployment_state,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def request_telegram_confirmation(
        self,
        task_id: str,
        command: RequestTelegramConfirmationCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> TelegramConfirmationDispatch:
        self._require_judge(actor_id, actor_role)
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "await_confirmation":
            raise ProductActionBlockedError("task is no longer awaiting confirmation")
        if self._telegram is None:
            raise ProductActionBlockedError("Telegram confirmation is not configured")
        if self._owner_chat_id is None:
            raise ProductActionBlockedError("exactly one Telegram owner must be configured")
        prepared = self._telegram.request_confirmation(
            ticket_artifact_id=task.step.ticket_artifact_id,
            chat_id=self._owner_chat_id,
            dry_run=command.dry_run,
            requested_at=self._queries.now(),
        )
        return TelegramConfirmationDispatch(
            ticket_artifact_id=prepared.ticket_artifact_id,
            confirmation_id=prepared.confirmation_id,
            expires_at=_parse_aware(prepared.expires_at, "expires_at"),
            dispatch_state="dry_run" if command.dry_run else "sent",
            message_preview=prepared.text,
        )

    def _execute_adjudication(
        self,
        *,
        issue: str,
        decision: str,
        reason: str,
        evidence_rejected: list[dict[str, str]],
        alternative: dict[str, object],
        idempotency_key: str,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ProductActionResponse:
        return self._actions.execute(
            ProductActionRequest(
                action_type="record_adjudication",
                idempotency_key=idempotency_key,
                payload={
                    "subject_type": "issue",
                    "subject_id": issue,
                    "decision": decision,
                    "reason": reason,
                    "evidence_rejected": evidence_rejected,
                    "alternative": alternative,
                },
                policy_version="governance-v1",
            ),
            actor_id=actor_id,
            actor_role=actor_role,
        )
