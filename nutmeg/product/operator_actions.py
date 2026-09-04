from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.decision.legs_audit import DEVIATION_RULE_IDS
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, canonical_json
from nutmeg.ontology.operator.decision_actions import (
    BaselineEnvelopeOfferConstraint,
    BaselineEnvelopeStructureTemplate,
    CommitOperatorMatchJudgmentRequest,
    FaceBundleInput,
    FaceOffsetInput,
    FaceProbabilityInput,
    FactorAdjustmentInput,
    FreezeJudgmentPrescriptionRequest,
    RecordBaselineEnvelopeRequest,
)
from nutmeg.ontology.operator.evidence_actions import RequestEvidenceFreezeRequest
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.contracts import ProductActionRequest, ProductActionResponse
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_contracts import (
    GradePredictionCommand,
    OperatorCommandReceipt,
    RecordDeploymentCommand,
    RequestTelegramConfirmationCommand,
    ResolveIssueAdjudicationCommand,
    SelectTicketVersionCommand,
    TelegramConfirmationDispatch,
)
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)


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


def scoreboard_projection_snapshot(
    source_high_watermark: int,
) -> OperatorSnapshotTokenPayloadV1:
    if source_high_watermark < 0:
        raise ValueError("source high-watermark cannot be negative")
    dependency = f"action_high_watermark:{source_high_watermark}"
    snapshot_hash = hashlib.sha256(
        canonical_json(
            {
                "command_kind": OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION.value,
                "dependency_revision_ids": [dependency],
            }
        ).encode("utf-8")
    ).hexdigest()
    return OperatorSnapshotTokenPayloadV1(
        task_snapshot_hash=snapshot_hash,
        work_item_id="system:scoreboard_projection",
        command_kind=OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION,
        dependency_revision_ids=[dependency],
    )


def _sha256_if_present(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OperatorActionService:
    def __init__(
        self,
        *,
        queries: OperatorQueryService,
        action_gateway: ProductActionGateway,
        telegram_confirmation=None,
        telegram_owner_chat_id: int | None = None,
        evidence_actions=None,
        decision_actions=None,
        snapshot_tokens: OperatorSnapshotTokenCodec | None = None,
        calibrate=None,
        repository=None,
        scoreboard_path: Path | None = None,
        clock=None,
    ) -> None:
        self._queries = queries
        self._actions = action_gateway
        self._telegram = telegram_confirmation
        self._owner_chat_id = telegram_owner_chat_id
        self._evidence_actions = evidence_actions
        self._decision_actions = decision_actions
        self._snapshot_tokens = snapshot_tokens
        self._calibrate = calibrate
        self._repository = repository
        self._scoreboard_path = scoreboard_path
        self._clock = clock or queries.now

    @property
    def action_gateway(self):
        return self._actions

    @property
    def telegram(self):
        return self._telegram

    @property
    def decision_actions(self):
        return self._decision_actions

    @staticmethod
    def _require_judge(actor_id: str, actor_role: ActorRole) -> None:
        if actor_role is not ActorRole.JUDGE_OPERATOR or not actor_id.strip():
            raise ProductActionBlockedError("operator mutation requires judge_operator")

    def _current_task(self, task_id: str, expected_snapshot_token: str):
        task = self._queries.task(task_id, as_of=self._queries.now())
        if task.mutation_token != expected_snapshot_token:
            raise ProductActionBlockedError("operator task changed after the form was opened")
        return task

    def request_evidence_freeze(
        self,
        command,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self._require_judge(actor_id, actor_role)
        if self._evidence_actions is None or self._snapshot_tokens is None:
            raise ProductActionBlockedError("evidence freeze is not configured")
        requested_at = _parse_aware(self._clock(), "operator clock")
        context = self._queries.evidence_freeze_context(
            command.task_key,
            as_of=requested_at,
        )
        if command.requirement_revision_token != context.requirement_revision_token:
            raise OperatorSnapshotTokenError("task_snapshot_changed")
        self._snapshot_tokens.verify(
            command.expected_snapshot_token,
            expected_command_kind=OperatorCommandKind.FREEZE_EVIDENCE,
            current_task_snapshot_hash=context.task_snapshot_hash,
            current_work_item_id=f"{context.task_key}:evidence",
            current_dependency_revision_ids=(context.dependency_leaves.token_revision_ids()),
        )
        if not context.ready:
            raise ProductActionBlockedError("operator evidence gate is not complete")
        outcome = self._evidence_actions.request_evidence_freeze(
            RequestEvidenceFreezeRequest(
                task_family_id=context.task_key,
                lane=context.lane,
                business_key=context.business_key,
                requirement_revision_token=context.requirement_revision_token,
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=command.idempotency_key,
                requested_at=requested_at,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ProductActionBlockedError("evidence freeze request was not committed")
        return OperatorCommandReceipt(
            command_kind="freeze_evidence",
            status="queued",
            task_key=context.task_key,
        )

    def record_baseline_envelope(
        self,
        command,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self._require_judge(actor_id, actor_role)
        decision_actions, tokens = self._decision_dependencies()
        requested_at = _parse_aware(self._clock(), "operator clock")
        context = self._queries.baseline_envelope_context(
            command.task_key,
            as_of=requested_at,
        )
        tokens.verify(
            command.expected_snapshot_token,
            expected_command_kind=OperatorCommandKind.RECORD_BASELINE_ENVELOPE,
            current_task_snapshot_hash=context.task_snapshot_hash,
            current_work_item_id=context.work_item_id,
            current_dependency_revision_ids=context.dependency_revision_ids,
        )
        outcome = decision_actions.record_baseline_envelope(
            RecordBaselineEnvelopeRequest(
                task_evidence_bundle_revision_id=(context.task_evidence_bundle_revision_id),
                work_item_id=context.work_item_id,
                ticket_kind=command.ticket_kind,
                capital_cap_minor=command.capital_cap_minor,
                currency=command.currency,
                maximum_ticket_count=command.maximum_ticket_count,
                offer_constraints=tuple(
                    BaselineEnvelopeOfferConstraint(
                        official_match_no=item.official_match_no,
                        market_code=item.market_code,
                        allowed_face_bundles=tuple(
                            FaceBundleInput(
                                bundle_code=bundle.bundle_code,
                                face_codes=tuple(bundle.face_codes),
                            )
                            for bundle in item.allowed_face_bundles
                        ),
                        omission_allowed=item.omission_allowed,
                    )
                    for item in command.offer_constraints
                ),
                structure_templates=tuple(
                    BaselineEnvelopeStructureTemplate(
                        kind=item.kind,
                        structure_code=item.structure_code,
                        eligible_official_match_nos=tuple(item.eligible_official_match_nos),
                        pass_size=item.pass_size,
                        required_offer_count=item.required_offer_count,
                        maximum_groups=item.maximum_groups,
                    )
                    for item in command.structure_templates
                ),
                maximum_exhaustive_candidate_count=(command.maximum_exhaustive_candidate_count),
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=command.idempotency_key,
                requested_at=requested_at,
                expected_current_revision_no=(context.expected_current_revision_no),
            )
        )
        self._require_committed(outcome, "baseline envelope")
        return OperatorCommandReceipt(
            command_kind="record_baseline_envelope",
            status="completed",
            task_key=context.task_key,
        )

    def commit_match_judgment(
        self,
        command,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self._require_judge(actor_id, actor_role)
        decision_actions, tokens = self._decision_dependencies()
        requested_at = _parse_aware(self._clock(), "operator clock")
        context = self._queries.match_judgment_context(
            command.task_key,
            command.official_match_no,
            command.market_code,
            as_of=requested_at,
        )
        tokens.verify(
            command.expected_snapshot_token,
            expected_command_kind=OperatorCommandKind.COMMIT_MATCH_JUDGMENT,
            current_task_snapshot_hash=context.task_snapshot_hash,
            current_work_item_id=context.work_item_id,
            current_dependency_revision_ids=context.dependency_revision_ids,
        )
        expected_scope_key = f"match:{command.official_match_no}"
        if any(item.scope_key != expected_scope_key for item in command.factors):
            raise OperatorSnapshotTokenError("invalid_request")
        outcome = decision_actions.commit_operator_match_judgment(
            CommitOperatorMatchJudgmentRequest(
                task_evidence_bundle_revision_id=(context.task_evidence_bundle_revision_id),
                market_prior_baseline_revision_id=(context.market_prior_baseline_revision_id),
                baseline_envelope_revision_id=(context.baseline_envelope_revision_id),
                work_item_id=context.work_item_id,
                match_id=context.match_id,
                official_offer_revision_id=context.official_offer_revision_id,
                market_definition_id=context.market_definition_id,
                prior=tuple(
                    FaceProbabilityInput(
                        face_code=face_code,
                        probability_decimal=probability,
                    )
                    for face_code, probability in context.prior
                ),
                belief=tuple(
                    FaceProbabilityInput(
                        face_code=item.face_code,
                        probability_decimal=item.probability_decimal,
                    )
                    for item in command.belief
                ),
                factors=tuple(
                    FactorAdjustmentInput(
                        factor_definition_id=item.factor_id,
                        scope_key=context.match_id,
                        evidence_ref_tokens=tuple(item.evidence_ref_tokens),
                        offsets=tuple(
                            FaceOffsetInput(
                                face_code=offset.face_code,
                                offset_probability_decimal=(offset.offset_probability_decimal),
                            )
                            for offset in item.offsets
                        ),
                    )
                    for item in command.factors
                ),
                expression_bundles=tuple(
                    FaceBundleInput(
                        bundle_code=item.bundle_code,
                        face_codes=tuple(item.face_codes),
                    )
                    for item in command.expression_bundles
                ),
                rule_ids=tuple(command.rule_ids),
                evidence_ref_tokens=tuple(command.evidence_ref_tokens),
                falsifier=command.falsifier,
                rationale=command.rationale,
                commitment_tier="commit",
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=command.idempotency_key,
                requested_at=requested_at,
                expected_current_revision_no=(context.expected_current_revision_no),
            )
        )
        self._require_committed(outcome, "match judgment")
        return OperatorCommandReceipt(
            command_kind="commit_match_judgment",
            status="completed",
            task_key=context.task_key,
        )

    def freeze_judgment_prescription(
        self,
        command,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self._require_judge(actor_id, actor_role)
        decision_actions, tokens = self._decision_dependencies()
        requested_at = _parse_aware(self._clock(), "operator clock")
        context = self._queries.judgment_prescription_context(
            command.task_key,
            as_of=requested_at,
        )
        tokens.verify(
            command.expected_snapshot_token,
            expected_command_kind=OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION,
            current_task_snapshot_hash=context.task_snapshot_hash,
            current_work_item_id=context.work_item_id,
            current_dependency_revision_ids=context.dependency_revision_ids,
        )
        if tuple(command.judgment_revision_tokens) != tuple(context.judgment_revision_tokens):
            raise OperatorSnapshotTokenError("task_snapshot_changed")
        outcome = decision_actions.freeze_judgment_prescription(
            FreezeJudgmentPrescriptionRequest(
                task_evidence_bundle_revision_id=(context.task_evidence_bundle_revision_id),
                market_prior_baseline_revision_id=(context.market_prior_baseline_revision_id),
                baseline_envelope_revision_id=(context.baseline_envelope_revision_id),
                work_item_id=context.work_item_id,
                judgment_revision_ids=tuple(context.judgment_revision_ids),
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=command.idempotency_key,
                requested_at=requested_at,
                expected_current_revision_no=(context.expected_current_revision_no),
            )
        )
        self._require_committed(outcome, "judgment prescription")
        return OperatorCommandReceipt(
            command_kind="freeze_judgment_prescription",
            status="completed",
            task_key=context.task_key,
        )

    def _decision_dependencies(self):
        if self._decision_actions is None or self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator judgment is not configured")
        return self._decision_actions, self._snapshot_tokens

    @staticmethod
    def _require_committed(outcome, label: str) -> None:
        if outcome.status is not ActionStatus.COMMITTED:
            raise ProductActionBlockedError(f"{label} Action was not committed")

    def rebuild_scoreboard_projection(
        self,
        command,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self._require_judge(actor_id, actor_role)
        if self._snapshot_tokens is None or self._calibrate is None or self._repository is None:
            raise ProductActionBlockedError("scoreboard projection rebuild is not configured")
        source_high_watermark = self._repository.action_high_watermark()
        current = scoreboard_projection_snapshot(source_high_watermark)
        self._snapshot_tokens.verify(
            command.expected_snapshot_token,
            expected_command_kind=OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION,
            current_task_snapshot_hash=current.task_snapshot_hash,
            current_work_item_id=current.work_item_id,
            current_dependency_revision_ids=current.dependency_revision_ids,
        )
        requested_at = _parse_aware(self._clock(), "operator clock")
        scoreboard_checksum = _sha256_if_present(self._scoreboard_path)
        result = self._calibrate.build(
            CalibrateRequest(
                as_of=requested_at.isoformat(),
                built_at=requested_at.isoformat(),
                high_watermark=source_high_watermark,
            )
        )
        if result.status != "succeeded":
            raise ProductActionBlockedError("scoreboard projection rebuild failed")
        if self._repository.action_high_watermark() != source_high_watermark:
            raise ProductActionBlockedError("Action ledger changed during projection rebuild")
        if _sha256_if_present(self._scoreboard_path) != scoreboard_checksum:
            raise ProductActionBlockedError(
                "scoreboard authority changed during projection rebuild"
            )
        return OperatorCommandReceipt(
            command_kind="rebuild_scoreboard_projection",
            status="completed",
            source_high_watermark=source_high_watermark,
            projection_high_watermark=result.high_watermark,
        )

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
            raise ProductActionBlockedError("deployment decision is not allowed by current gate")
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

    def grade_prediction(
        self,
        task_id: str,
        command: GradePredictionCommand,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ProductActionResponse:
        if actor_role is not ActorRole.JUDGE_OPERATOR:
            raise ProductActionBlockedError("prediction grade requires judge_operator")
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "review":
            raise ProductActionBlockedError("task is no longer in review")
        current = task.step.current_item
        if current.item_type != "prediction" or current.item_id != command.prediction_id:
            raise ProductActionBlockedError("prediction is no longer the current review item")
        return self._actions.execute(
            ProductActionRequest(
                action_type="grade_prediction",
                idempotency_key=command.idempotency_key,
                payload={
                    "prediction_id": command.prediction_id,
                    "outcome": command.outcome,
                    "reason": command.reason,
                },
                policy_version="governance-v1",
            ),
            actor_id=actor_id,
            actor_role=actor_role,
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
