from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from nutmeg.decision.legs_audit import Leg, audit_legs, audit_prescription_deviations
from nutmeg.decision.zucai_deployment import (
    RENJIU_HISTORY_WINDOW,
    DeploymentGateState,
    evaluate_deployment_gate,
)
from nutmeg.decision.zucai_official import OfficialRenjiuHistory
from nutmeg.decision.zucai_optimizer import optimize
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_artifacts import (
    OperatorArtifactError,
    ZucaiArtifactBundle,
    ZucaiArtifactRepository,
    ZucaiCandidateDocument,
)
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    AwaitResultStep,
    BlockedStep,
    BusinessEvidenceSummary,
    CompleteStep,
    ConfirmationStep,
    ConstructTicketStep,
    EvidenceFieldSummary,
    JudgeMatchesStep,
    LedgerStep,
    OperatorEvidenceResponse,
    OperatorLane,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrescriptionDifferenceSummary,
    ReviewItemSummary,
    ReviewStep,
    StepView,
    TaskProgressSummary,
    TicketVersionSummary,
)
from nutmeg.product.operator_state import (
    NEXT_ACTION_LABELS,
    OperatorTaskFacts,
    priority_key,
    resolve_state,
)
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository

_ACTIONABLE_STATES = {
    OperatorTaskState.PREPARE,
    OperatorTaskState.JUDGE_MATCHES,
    OperatorTaskState.CONSTRUCT_TICKET,
    OperatorTaskState.AUDIT_DEPLOYMENT,
    OperatorTaskState.AWAIT_CONFIRMATION,
    OperatorTaskState.AWAIT_LEDGER,
    OperatorTaskState.REVIEW,
}
_FACE_ORDER = "310"


class _OfficialHistoryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _BuiltTask:
    facts: OperatorTaskFacts
    summary: OperatorTaskSummary
    progress: TaskProgressSummary
    step: StepView
    mutation_token: str


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _token(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _summary(
    facts: OperatorTaskFacts,
    *,
    title: str,
    block_reason_code: str | None = None,
) -> OperatorTaskSummary:
    state = resolve_state(facts)
    return OperatorTaskSummary(
        task_id=f"{facts.lane.value}:{facts.business_key}",
        lane=facts.lane,
        business_key=facts.business_key,
        title=title,
        state=state,
        deadline_at=facts.deadline_at,
        waiting_until=facts.waiting_until,
        is_actionable=state in _ACTIONABLE_STATES,
        next_action_label=NEXT_ACTION_LABELS[state],
        priority_rank=0,
        block_reason_code=block_reason_code,
    )


class OperatorQueryService:
    def __init__(
        self,
        *,
        repository: ProductReadRepository,
        product_queries: ProductQueryService,
        artifacts: ZucaiArtifactRepository,
        official_history_provider: Callable[[], list[OfficialRenjiuHistory]],
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._product_queries = product_queries
        self._artifacts = artifacts
        self._official_history = official_history_provider
        self._clock = clock

    def worklist(self, *, as_of: datetime) -> OperatorWorklistResponse:
        cutoff = _aware(as_of, "as_of")
        built = sorted(
            self._build_all(cutoff),
            key=lambda item: priority_key(item.facts, cutoff),
        )
        tasks = [
            item.summary.model_copy(update={"priority_rank": rank})
            for rank, item in enumerate(built)
        ]
        selected = next(
            (item for item in tasks if item.state is not OperatorTaskState.COMPLETE),
            None,
        )
        return OperatorWorklistResponse(as_of=cutoff, selected=selected, tasks=tasks)

    def task(self, task_id: str, *, as_of: datetime) -> OperatorTaskResponse:
        cutoff = _aware(as_of, "as_of")
        worklist = self.worklist(as_of=cutoff)
        selected = next((item for item in worklist.tasks if item.task_id == task_id), None)
        if selected is None:
            raise ProductNotFoundError(f"operator task {task_id} not found")
        built = self._build_task(task_id, cutoff)
        return OperatorTaskResponse(
            as_of=cutoff,
            mutation_token=built.mutation_token,
            selected=selected,
            alternatives=[item for item in worklist.tasks if item.task_id != task_id],
            progress=built.progress,
            step=built.step,
        )

    def now(self) -> datetime:
        return _aware(self._clock(), "operator clock")

    def evidence(
        self,
        task_id: str,
        evidence_key: str,
        *,
        as_of: datetime,
    ) -> OperatorEvidenceResponse:
        _aware(as_of, "as_of")
        task_match = re.fullmatch(r"zucai:(\d{5})", task_id)
        if task_match is None:
            raise ProductNotFoundError("operator evidence not found")
        issue = task_match.group(1)
        try:
            bundle = self._artifacts.load(issue)
        except OperatorArtifactError as error:
            raise ProductNotFoundError("operator evidence not found") from error
        prep_match = re.fullmatch(r"prep-match-(\d{1,2})", evidence_key)
        if prep_match:
            match_no = int(prep_match.group(1))
            record = bundle.match_record(match_no)
            if record is None:
                raise ProductNotFoundError("operator evidence not found")
            return OperatorEvidenceResponse(
                task_id=task_id,
                evidence_key=evidence_key,
                title=f"场 {match_no} {record.name}",
                source_label=f"足彩 {issue} 下午准备数据",
                observed_at=bundle.prep.captured_at,
                freshness_label=bundle.prep.captured_at.strftime("%Y-%m-%d %H:%M"),
                fields=[
                    EvidenceFieldSummary(label="赛事", value=record.league),
                    EvidenceFieldSummary(label="开球", value=record.kickoff_bj),
                    EvidenceFieldSummary(
                        label="胜", value=f"{record.fair_had.home:.2%}"
                    ),
                    EvidenceFieldSummary(
                        label="平", value=f"{record.fair_had.draw:.2%}"
                    ),
                    EvidenceFieldSummary(
                        label="负", value=f"{record.fair_had.away:.2%}"
                    ),
                    EvidenceFieldSummary(
                        label="让球", value=record.hhad_line or "未提供"
                    ),
                ],
            )
        if evidence_key == "rx-capital":
            return OperatorEvidenceResponse(
                task_id=task_id,
                evidence_key=evidence_key,
                title=f"足彩 {issue} 资金约束",
                source_label="已登记处方",
                observed_at=bundle.rx.registered_at,
                freshness_label=bundle.rx.registered_at.strftime("%Y-%m-%d %H:%M"),
                fields=[
                    EvidenceFieldSummary(label=str(label), value=str(value))
                    for label, value in sorted(bundle.rx.capital_report.items())
                ],
            )
        raise ProductNotFoundError("operator evidence not found")

    def _build_all(self, cutoff: datetime) -> list[_BuiltTask]:
        built = [self._build_zucai(issue, cutoff) for issue in self._artifacts.discover_issues()]
        ticket_rows = self._repository.operator_ticket_artifacts(cutoff.isoformat())
        run_dates = sorted({str(row["run_date"]) for row in ticket_rows})
        built.extend(self._build_jczq(run_date, cutoff, ticket_rows) for run_date in run_dates)
        return built

    def _build_task(self, task_id: str, cutoff: datetime) -> _BuiltTask:
        if match := re.fullmatch(r"zucai:(\d{5})", task_id):
            return self._build_zucai(match.group(1), cutoff)
        if match := re.fullmatch(r"jczq:(\d{4}-\d{2}-\d{2})", task_id):
            rows = self._repository.operator_ticket_artifacts(cutoff.isoformat())
            return self._build_jczq(match.group(1), cutoff, rows)
        raise ProductNotFoundError(f"operator task {task_id} not found")

    def _build_zucai(self, issue: str, cutoff: datetime) -> _BuiltTask:
        task_id = f"zucai:{issue}"
        try:
            bundle = self._artifacts.load(issue)
        except OperatorArtifactError as error:
            return self._source_block(task_id, issue, error)
        adjudications = self._repository.adjudications_for_subject(
            "issue", issue, cutoff.isoformat()
        )
        predictions = self._repository.predictions_for_subject(
            "issue", issue, cutoff.isoformat()
        )
        alternatives = [row.get("alternative") or {} for row in adjudications]
        resolved_rx_ids = {
            str(alternative["rx_adjudication_id"])
            for alternative in alternatives
            if alternative.get("rx_adjudication_id")
        }
        pending = [item for item in bundle.rx.pending_adjudications if item.requires_operator]
        unresolved = [item for item in pending if item.id not in resolved_rx_ids]
        selection = next(
            (
                row
                for row in reversed(adjudications)
                if (row.get("alternative") or {}).get("candidate_id")
            ),
            None,
        )
        selected_id = (
            str(selection["alternative"]["candidate_id"]) if selection is not None else None
        )
        deployment = next(
            (
                row
                for row in reversed(adjudications)
                if (row.get("alternative") or {}).get("deployment_decision")
                and selection is not None
                and str(row["created_at"]) > str(selection["created_at"])
            ),
            None,
        )
        deployment_decision = (
            str(deployment["alternative"]["deployment_decision"])
            if deployment is not None
            else None
        )
        explicit_artifact_id = next(
            (
                str(alternative["ticket_artifact_id"])
                for alternative in reversed(alternatives)
                if alternative.get("ticket_artifact_id")
            ),
            None,
        )
        tickets = self._repository.operator_ticket_artifacts(cutoff.isoformat())
        ticket = next(
            (row for row in tickets if row.get("ticket_artifact_id") == explicit_artifact_id),
            None,
        )
        confirmation_state = self._confirmation_state(ticket, cutoff) if ticket else None
        placement_state = self._placement_state(ticket) if ticket else None
        settlement = self._ticket_settlement(ticket, cutoff)
        result_available = (
            bundle.rx.outcomes is not None
            or settlement is not None
            or any(row.get("settled_at") or row.get("outcome") for row in predictions)
        )
        pending_predictions = [row for row in predictions if row.get("status") == "pending"]
        pending_reviews = len(pending_predictions)
        candidate_ids = {candidate.candidate_id for candidate in bundle.candidates}
        selection_invalid = selected_id is not None and selected_id not in candidate_ids
        facts = OperatorTaskFacts(
            lane=OperatorLane.ZUCAI,
            business_key=issue,
            deadline_at=bundle.fallback_deadline(),
            waiting_until=None,
            source_error_code="selected_candidate_missing" if selection_invalid else None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=len(unresolved),
            candidate_count=len(bundle.candidates),
            selected_candidate_id=selected_id,
            audit_recorded=deployment is not None,
            deployment_decision=deployment_decision,
            ticket_artifact_id=explicit_artifact_id if ticket is not None else None,
            confirmation_state=confirmation_state,
            placement_state=placement_state,
            result_available=result_available,
            pending_review_items=pending_reviews,
        )
        state = resolve_state(facts)
        comparisons = self._candidate_summaries(bundle, selection)
        block_code = None
        if selection_invalid:
            block_code = "selected_candidate_missing"
        if state is OperatorTaskState.BLOCKED and deployment_decision == "keep":
            block_code = "protected_artifact_missing"
        step: StepView
        if state is OperatorTaskState.JUDGE_MATCHES:
            current = unresolved[0]
            step = JudgeMatchesStep(
                task_id=task_id,
                item_key=current.id,
                title=current.q,
                prompt=current.q,
                options=self._adjudication_options(current.options, current.default),
                evidence=[
                    BusinessEvidenceSummary(
                        label="资金",
                        value="；".join(
                            f"{label}: {value}" for label, value in bundle.rx.capital_report.items()
                        ),
                        evidence_href=f"/tasks/{task_id}/evidence/rx-capital",
                    )
                ],
            )
        elif state is OperatorTaskState.CONSTRUCT_TICKET:
            step = ConstructTicketStep(
                task_id=task_id,
                prescription=self._prescription(bundle),
                candidates=comparisons,
            )
        elif state is OperatorTaskState.AUDIT_DEPLOYMENT:
            try:
                step = self._audit_step(
                    bundle,
                    selected_id,
                    selection,
                    comparisons,
                    explicit_empty=any(
                        alternative.get("materially_indistinguishable") is True
                        for alternative in alternatives
                    ),
                )
            except _OfficialHistoryUnavailable as error:
                facts = replace(facts, source_error_code="official_history_unavailable")
                block_code = "official_history_unavailable"
                retry_at = cutoff + timedelta(minutes=15)
                step = BlockedStep(
                    task_id=task_id,
                    title="官方历史暂不可用",
                    recovery=OperatorRecoverySummary(
                        code=block_code,
                        missing="任九官方奖金历史",
                        impact="部署门暂时不能计算",
                        action_label="稍后重试",
                        retry_at=retry_at,
                    ),
                    correlation_id=_token(str(error))[:16],
                )
        elif state is OperatorTaskState.BLOCKED:
            step = BlockedStep(
                task_id=task_id,
                title=(
                    "已选票版已不存在"
                    if block_code == "selected_candidate_missing"
                    else "缺少正式出票制品"
                ),
                recovery=OperatorRecoverySummary(
                    code=block_code or "operator_task_blocked",
                    missing=(
                        "已提交选择对应的结构化候选票"
                        if block_code == "selected_candidate_missing"
                        else "与本期显式绑定的 protected ticket artifact"
                    ),
                    impact="不能可靠推进当前流程",
                    action_label="返回票版流程核对",
                ),
            )
        elif state is OperatorTaskState.COMPLETE:
            step = CompleteStep(
                task_id=task_id,
                title="本期流程已完成",
                summary=(
                    "已明确裁决空仓；没有出票或入账"
                    if deployment_decision == "empty_position"
                    else "流程已按持久化记录完成"
                ),
            )
        elif state is OperatorTaskState.AWAIT_CONFIRMATION and ticket is not None:
            step = ConfirmationStep(
                task_id=task_id,
                ticket_artifact_id=str(ticket["ticket_artifact_id"]),
                amount=float(ticket["amount"]),
                currency=str(ticket["currency"]),
                deadline_at=datetime.fromisoformat(str(ticket["deadline_at"])),
                confirmation_state=confirmation_state or "not_issued",
                confirmation_expires_at=(
                    datetime.fromisoformat(str(ticket["expires_at"]))
                    if ticket.get("expires_at")
                    else None
                ),
            )
        elif state is OperatorTaskState.AWAIT_LEDGER and ticket is not None:
            step = self._ledger_step(task_id, ticket)
        elif state is OperatorTaskState.REVIEW:
            step = self._review_step(
                task_id,
                predictions=predictions,
                pending_predictions=pending_predictions,
                settlement=settlement,
                bundle=bundle,
            )
        else:
            step = AwaitResultStep(
                task_id=task_id,
                title="等待权威赛果",
                expected_at=facts.deadline_at,
            )
        summary = _summary(
            facts,
            title=f"足彩 {issue}",
            block_reason_code=block_code,
        )
        progress = TaskProgressSummary(
            completed=len(pending) - len(unresolved),
            total=len(pending),
            label="逐项裁决" if unresolved else NEXT_ACTION_LABELS[summary.state],
        )
        mutation_payload = {
            "task_id": task_id,
            "bundle": bundle.model_dump(mode="json"),
            "candidate_ids": [candidate.candidate_id for candidate in bundle.candidates],
            "adjudications": [
                {
                    "id": row.get("adjudication_id"),
                    "created_at": row.get("created_at"),
                    "alternative": row.get("alternative"),
                }
                for row in adjudications
            ],
            "predictions": [
                {
                    "id": row.get("prediction_id"),
                    "status": row.get("status"),
                    "settled_at": row.get("settled_at"),
                }
                for row in predictions
            ],
            "ticket": ticket,
        }
        return _BuiltTask(facts, summary, progress, step, _token(mutation_payload))

    def _ticket_settlement(
        self, ticket: dict[str, Any] | None, cutoff: datetime
    ) -> dict[str, Any] | None:
        if ticket is None or not ticket.get("ticket_id"):
            return None
        ticket_id = str(ticket["ticket_id"])
        return next(
            (
                row
                for row in self._repository.settlements(as_of=cutoff.isoformat())
                if str(row.get("ticket_id")) == ticket_id
            ),
            None,
        )

    @staticmethod
    def _review_step(
        task_id: str,
        *,
        predictions: list[dict[str, Any]],
        pending_predictions: list[dict[str, Any]],
        settlement: dict[str, Any] | None,
        bundle: ZucaiArtifactBundle,
    ) -> ReviewStep:
        current = pending_predictions[0]
        hit_count = sum(row.get("outcome") == "hit" for row in predictions)
        calibration_summary = None
        if bundle.night_snapshots:
            latest = bundle.night_snapshots[-1]
            calibration_summary = f"夜间校准已收录 {len(latest.results)} 场赛果"
        elif bundle.rx.outcomes is not None:
            calibration_summary = "赛后结果已登记"
        return ReviewStep(
            task_id=task_id,
            hit_count=hit_count,
            total_count=len(predictions),
            stake_yuan=(float(settlement["stake_amount"]) if settlement else None),
            payout_yuan=(float(settlement["payout_amount"]) if settlement else None),
            pnl_yuan=(float(settlement["pnl_amount"]) if settlement else None),
            calibration_summary=calibration_summary,
            current_item=ReviewItemSummary(
                item_type="prediction",
                item_id=str(current["prediction_id"]),
                title=str(current["claim"]),
                evidence=[
                    BusinessEvidenceSummary(
                        label="证伪条件",
                        value=str(current["falsifier"]),
                        source_label="已登记 prediction",
                    )
                ],
                allowed_outcomes=["hit", "miss", "na"],
            ),
        )

    def _source_block(self, task_id: str, issue: str, error: Exception) -> _BuiltTask:
        facts = OperatorTaskFacts(
            lane=OperatorLane.ZUCAI,
            business_key=issue,
            deadline_at=None,
            waiting_until=None,
            source_error_code="source_contract_invalid",
            has_issue=False,
            has_prep=False,
            unresolved_adjudications=0,
            candidate_count=0,
            selected_candidate_id=None,
            audit_recorded=False,
            deployment_decision=None,
            ticket_artifact_id=None,
            confirmation_state=None,
            placement_state=None,
            result_available=False,
            pending_review_items=0,
        )
        step = BlockedStep(
            task_id=task_id,
            title="源文件结构无效",
            recovery=OperatorRecoverySummary(
                code="source_contract_invalid",
                missing="可验证的本期结构化文件",
                impact="无法可靠展示或推进流程",
                action_label="修复源文件后重试",
            ),
            correlation_id=_token(str(error))[:16],
        )
        return _BuiltTask(
            facts,
            _summary(facts, title=f"足彩 {issue}", block_reason_code="source_contract_invalid"),
            TaskProgressSummary(completed=0, total=0, label="数据校验"),
            step,
            _token({"task_id": task_id, "error": str(error)}),
        )

    def _candidate_summaries(
        self,
        bundle: ZucaiArtifactBundle,
        selection: dict[str, Any] | None,
    ) -> list[TicketVersionSummary]:
        if not bundle.candidates:
            return []
        fair: dict[str, dict[str, float]] = {}
        for candidate in bundle.candidates:
            for match_no, leg in candidate.legs.items():
                fair.setdefault(match_no, leg.fair.model_dump())
        result = optimize(
            {
                "issue": bundle.issue.issue_id,
                "price_per_note": 2,
                "budget_yuan": 400,
                "baseline_id": None,
                "fair": fair,
                "versions": [
                    {"id": candidate.candidate_id, "faces": candidate.faces()}
                    for candidate in bundle.candidates
                ],
                "groups": [],
            }
        )
        stats = {str(row["id"]): row for row in result["versions"]}
        prescription = self._prescription(bundle)
        registered = self._registered_deviations(selection)
        common_dead = self._common_dead_faces(bundle.candidates)
        summaries = []
        for candidate in bundle.candidates:
            row = stats[candidate.candidate_id]
            differences = []
            for match_no in sorted(
                set(prescription) | set(candidate.faces()), key=int
            ):
                prescribed = prescription.get(match_no, "")
                current = candidate.faces().get(match_no, "")
                if set(prescribed) == set(current):
                    continue
                number = int(match_no)
                differences.append(
                    PrescriptionDifferenceSummary(
                        match_no=number,
                        prescribed_faces=prescribed,
                        candidate_faces=current,
                        registered_rule_ids=(
                            registered.get(number, [])
                            if selection
                            and selection.get("alternative", {}).get("candidate_id")
                            == candidate.candidate_id
                            else []
                        ),
                    )
                )
            summaries.append(
                TicketVersionSummary(
                    candidate_id=candidate.candidate_id,
                    label=candidate.version,
                    faces=candidate.faces(),
                    notes=int(row["notes"]),
                    cost_yuan=int(row["cost_yuan"]),
                    p_all=float(row["p_all"]),
                    expected_broken=float(row["expected_broken"]),
                    within_cap=bool(row["within_cap"]),
                    common_dead_faces=common_dead,
                    prescription_differences=differences,
                )
            )
        return summaries

    def _audit_step(
        self,
        bundle: ZucaiArtifactBundle,
        selected_id: str | None,
        selection: dict[str, Any] | None,
        comparisons: list[TicketVersionSummary],
        *,
        explicit_empty: bool,
    ) -> AuditDeploymentStep:
        selected_doc = next(
            candidate for candidate in bundle.candidates if candidate.candidate_id == selected_id
        )
        selected_summary = next(
            candidate for candidate in comparisons if candidate.candidate_id == selected_id
        )
        registry = (selection or {}).get("alternative", {}).get("deviation_registry", [])
        legs = [
            Leg(
                match_no=int(match_no),
                name=leg.name,
                faces=leg.faces,
                fair=leg.fair.model_dump(),
                confidence=leg.confidence,
                directional_flags=tuple(leg.directional_flags),
                nondirectional_flags=tuple(leg.nondirectional_flags),
                anchor_integrity=leg.anchor_integrity,
                precedents=tuple(leg.precedents),
            )
            for match_no, leg in selected_doc.legs.items()
        ]
        findings = audit_legs(legs) + audit_prescription_deviations(
            {
                "prescription": self._prescription(bundle),
                "legs": {key: value.model_dump() for key, value in selected_doc.legs.items()},
                "deviation_registry": registry,
            }
        )
        audit_state = (
            "error"
            if any(item.level == "ERROR" for item in findings)
            else "warn" if any(item.level == "WARN" for item in findings) else "pass"
        )
        try:
            history = self._official_history()
            if not history:
                raise RuntimeError("official history is empty")
            gate = evaluate_deployment_gate(
                {
                    "issue": bundle.issue.issue_id,
                    "history_as_of_issue": bundle.issue.issue_id,
                    "period_cap_yuan": 400,
                    "history_window": RENJIU_HISTORY_WINDOW,
                    "candidates": [
                        {
                            "id": candidate.candidate_id,
                            "stake_yuan": candidate.cost_yuan,
                            "hit_probability": candidate.p_all,
                        }
                        for candidate in comparisons
                    ],
                },
                history,
            )
        except (RuntimeError, ValueError) as error:
            raise _OfficialHistoryUnavailable(str(error)) from error
        allowed = {
            DeploymentGateState.PASS: ["keep", "change_structure"],
            DeploymentGateState.REVIEW: ["keep", "drop_match", "change_structure"],
            DeploymentGateState.REDUCE_OR_EMPTY: [
                "drop_match",
                "change_structure",
                "empty_position",
            ],
        }[gate.state]
        if gate.selected_id != selected_id and "keep" in allowed:
            allowed.remove("keep")
        if explicit_empty and "empty_position" not in allowed:
            allowed.append("empty_position")
        evidence = [
            BusinessEvidenceSummary(
                label=item.code,
                value=item.message,
                severity={"ERROR": "error", "WARN": "warn"}.get(item.level, "info"),
            )
            for item in findings
        ]
        evidence.append(
            BusinessEvidenceSummary(
                label="部署门",
                value=(
                    f"帽内候选 {gate.selected_id}，资金使用率 {gate.capital_utilization:.1%}，"
                    f"回本/中位 {gate.break_even_to_median:.2f}x"
                ),
                severity="warn" if gate.state is not DeploymentGateState.PASS else "info",
            )
        )
        return AuditDeploymentStep(
            task_id=f"zucai:{bundle.issue.issue_id}",
            candidate=selected_summary,
            gate_candidate_id=gate.selected_id,
            gate_candidate_cost_yuan=gate.stake_yuan,
            audit_state=audit_state,
            findings=evidence,
            deployment_state=gate.state.value,
            capital_utilization=gate.capital_utilization,
            median_bonus=gate.median_bonus,
            break_even_to_median=gate.break_even_to_median,
            allowed_decisions=allowed,
        )

    @staticmethod
    def _prescription(bundle: ZucaiArtifactBundle) -> dict[str, str]:
        prescription = bundle.rx.prescription_P14
        flattened = dict(prescription.singles)
        flattened.update(prescription.doubles)
        flattened.update({match_no: "310" for match_no in prescription.fulls})
        return flattened

    @staticmethod
    def _registered_deviations(selection: dict[str, Any] | None) -> dict[int, list[str]]:
        result: dict[int, list[str]] = {}
        for item in (selection or {}).get("alternative", {}).get("deviation_registry", []):
            try:
                result[int(item["match_no"])] = [str(rule) for rule in item["rule_ids"]]
            except (KeyError, TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _common_dead_faces(candidates: list[ZucaiCandidateDocument]) -> list[str]:
        if not candidates:
            return []
        common_matches = set.intersection(*(set(candidate.legs) for candidate in candidates))
        dead = []
        for match_no in sorted(common_matches, key=int):
            covered = set().union(
                *(set(candidate.legs[match_no].faces) for candidate in candidates)
            )
            missing = "".join(face for face in _FACE_ORDER if face not in covered)
            if missing:
                dead.append(f"场{match_no}: {missing}")
        return dead

    @staticmethod
    def _adjudication_options(options: str | None, default: str | None) -> list[str]:
        parsed = [item.strip() for item in (options or "").split("/") if item.strip()]
        if not parsed and default:
            parsed = [default]
        return parsed

    @staticmethod
    def _confirmation_state(ticket: dict[str, Any], cutoff: datetime) -> str:
        if not ticket.get("confirmation_id"):
            return "not_issued"
        if ticket.get("consumed_at"):
            return "consumed"
        expires_at = datetime.fromisoformat(str(ticket["expires_at"]))
        return "expired" if expires_at <= cutoff else "open"

    @staticmethod
    def _placement_state(ticket: dict[str, Any]) -> str:
        if ticket.get("ticket_shadow_id"):
            return "shadow"
        return "placed" if ticket.get("ticket_placement_id") else "unplaced"

    @staticmethod
    def _ledger_step(task_id: str, ticket: dict[str, Any]) -> LedgerStep:
        return LedgerStep(
            task_id=task_id,
            ticket_artifact_id=str(ticket["ticket_artifact_id"]),
            placement_state=OperatorQueryService._placement_state(ticket),
            amount=float(ticket["amount"]),
            currency=str(ticket["currency"]),
            external_reference=ticket.get("external_reference"),
        )

    def _build_jczq(
        self, run_date: str, cutoff: datetime, rows: list[dict[str, Any]]
    ) -> _BuiltTask:
        task_id = f"jczq:{run_date}"
        task_rows = [row for row in rows if str(row["run_date"]) == run_date]
        if not task_rows:
            raise ProductNotFoundError(f"operator task {task_id} not found")
        ticket = next((row for row in task_rows if row.get("ticket_artifact_id")), None)
        deadline_raw = next(
            (
                row.get("deadline_at") or row.get("batch_deadline_at")
                for row in task_rows
                if row.get("deadline_at") or row.get("batch_deadline_at")
            ),
            None,
        )
        deadline = datetime.fromisoformat(str(deadline_raw)) if deadline_raw else None
        confirmation = self._confirmation_state(ticket, cutoff) if ticket else None
        placement = self._placement_state(ticket) if ticket else None
        facts = OperatorTaskFacts(
            lane=OperatorLane.JCZQ,
            business_key=run_date,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0,
            candidate_count=1,
            selected_candidate_id=str(task_rows[0]["ticket_batch_revision_id"]),
            audit_recorded=True,
            deployment_decision="keep",
            ticket_artifact_id=str(ticket["ticket_artifact_id"]) if ticket else None,
            confirmation_state=confirmation,
            placement_state=placement,
            result_available=False,
            pending_review_items=0,
        )
        state = resolve_state(facts)
        block_code = "protected_artifact_missing" if state is OperatorTaskState.BLOCKED else None
        if state is OperatorTaskState.BLOCKED:
            step: StepView = BlockedStep(
                task_id=task_id,
                title="正式出票制品尚未生成",
                recovery=OperatorRecoverySummary(
                    code="protected_artifact_missing",
                    missing="approved protected ticket artifact",
                    impact="不能开启确认",
                    action_label="返回出票工作台",
                    href="/tickets",
                ),
            )
        elif state is OperatorTaskState.AWAIT_CONFIRMATION and ticket is not None:
            step = ConfirmationStep(
                task_id=task_id,
                ticket_artifact_id=str(ticket["ticket_artifact_id"]),
                amount=float(ticket["amount"]),
                currency=str(ticket["currency"]),
                deadline_at=datetime.fromisoformat(str(ticket["deadline_at"])),
                confirmation_state=confirmation or "not_issued",
                confirmation_expires_at=(
                    datetime.fromisoformat(str(ticket["expires_at"]))
                    if ticket.get("expires_at")
                    else None
                ),
            )
        elif state is OperatorTaskState.AWAIT_LEDGER and ticket is not None:
            step = self._ledger_step(task_id, ticket)
        elif state is OperatorTaskState.COMPLETE:
            summary = (
                "未确认，按未出票处理；没有入账"
                if placement == "shadow"
                else "已按记录完成"
            )
            step = CompleteStep(task_id=task_id, title="本日流程已完成", summary=summary)
        else:
            step = AwaitResultStep(task_id=task_id, title="等待赛果", expected_at=deadline)
        return _BuiltTask(
            facts=facts,
            summary=_summary(facts, title=f"竞彩 {run_date}", block_reason_code=block_code),
            progress=TaskProgressSummary(completed=0, total=0, label=NEXT_ACTION_LABELS[state]),
            step=step,
            mutation_token=_token({"task_id": task_id, "rows": task_rows}),
        )
