from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import combinations
from typing import TYPE_CHECKING, Any

from sqlalchemy import exists, func, or_, select

from nutmeg.decision.legs_audit import (
    DEVIATION_RULE_IDS,
    Leg,
    audit_legs,
    audit_prescription_deviations,
)
from nutmeg.decision.zucai_deployment import (
    RENJIU_HISTORY_WINDOW,
    RENJIU_HISTORY_WINDOW_EFFECTIVE_ISSUE,
    DeploymentGateState,
    evaluate_deployment_gate,
)
from nutmeg.decision.zucai_official import OfficialRenjiuHistory
from nutmeg.decision.zucai_optimizer import optimize
from nutmeg.ontology.actions.models import ObjectRef
from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
from nutmeg.ontology.operator.confirmation import effective_artifact_cutoff
from nutmeg.ontology.operator.review_actions import (
    ShadowReviewTokenCodec,
    ShadowReviewTokenPayload,
)
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_scoreboard as ss
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.product.errors import ProductActionBlockedError, ProductNotFoundError
from nutmeg.product.operator_artifacts import (
    OperatorArtifactError,
    ZucaiArtifactBundle,
    ZucaiCandidateDocument,
    ZucaiReplayBundleAdapter,
)
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    AwaitResultStep,
    BaselineEnvelopeEditorView,
    BaselineEnvelopeOfferView,
    BaselineEnvelopeStructureView,
    BlockedStep,
    BusinessEvidenceSummary,
    CandidateAuditFindingView,
    CandidateComparisonView,
    CandidateCompositionView,
    CandidateSetComparisonView,
    CompleteStep,
    ConfirmationStep,
    ConstructTicketStep,
    DeploymentAuditFindingSummary,
    DeploymentCandidateSummary,
    DeploymentRuleOption,
    EvidenceFieldSummary,
    JudgeMatchesStep,
    JudgmentFaceBundleView,
    JudgmentFaceView,
    JudgmentFactorView,
    JudgmentRuleView,
    LedgerStep,
    MatchJudgmentEditorView,
    NoTicketControl,
    OperatorAuditEnvelopeV1,
    OperatorAuditLineageItemV1,
    OperatorAuditProjectionV1,
    OperatorEvidenceResponse,
    OperatorLane,
    OperatorMaintenanceResponseV1,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrepareStep,
    PrescriptionDifferenceSummary,
    ResultMatchSummary,
    ResultPrizeTierSummary,
    ResultSourceSummary,
    ReviewAdjudicationSummary,
    ReviewCompletionGateSummary,
    ReviewEvidenceOptionSummary,
    ReviewForecastSummary,
    ReviewInterventionSummary,
    ReviewItemSummary,
    ReviewMoneySummary,
    ReviewScoreboardObservationSummary,
    ReviewShadowOptionSummary,
    ReviewStep,
    SettlementCashEntrySummary,
    SettlementLegSummary,
    SettlementNoteSummary,
    SettlementTicketSummary,
    StepView,
    TaskProgressSummary,
    TaskSettlementRunSummary,
    TaskSettlementSkipSummary,
    TicketVersionSummary,
)
from nutmeg.product.operator_evidence import OperatorEvidenceService
from nutmeg.product.operator_lanes import (
    JczqLaneAdapter,
    NoTicketClosure,
    SaleSlateSnapshot,
    ScopeKind,
    ZucaiLaneAdapter,
    derive_sale_wave,
)
from nutmeg.product.operator_state import (
    NEXT_ACTION_LABELS,
    OperatorTaskFacts,
    is_passive_expired_deployment,
    priority_key,
    resolve_state,
)
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)
from nutmeg.product.operator_workbench import (
    OperatorWorkbenchAssembler,
    schedule_recovery_views,
)
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository

if TYPE_CHECKING:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.product.operator_maintenance import OperatorMaintenanceProbe


def _renjiu_history_window(issue: str, *, available_rows: int) -> int:
    if issue.isdigit() and int(issue) >= RENJIU_HISTORY_WINDOW_EFFECTIVE_ISSUE:
        return RENJIU_HISTORY_WINDOW
    return min(20, available_rows)


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
_PROBABILITY_QUANTUM = Decimal("0.000000000001")
_FACE_LABELS = {"3": "主胜", "1": "平", "0": "客胜"}
_OUTCOME_BY_FACE = {"3": "home", "1": "draw", "0": "away"}
_MARKET_LABELS = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "ttg": "总进球",
    "crs": "比分",
}
_REQUIREMENT_LABELS = {
    "E1": "身份对齐",
    "E2": "官方赛程与销售",
    "E3": "官方市场",
    "E4": "国际市场对照",
    "E5": "阵容可用性",
    "E6a": "近期状态",
    "E6b": "结构背景",
    "EC": "冲突清理",
}
_REQUIREMENT_STATE_LABELS = {
    "complete": "已冻结",
    "missing": "缺失",
    "stale": "过期",
    "conflict": "冲突未清",
}
_RESULT_SOURCE_LABELS = {
    "api_football": "API-Football",
    "sporttery_game90": "官方竞彩",
    "okooo_manual": "人工核对",
}
_PRIZE_TIER_LABELS = {
    "sfc_first": "胜负彩一等奖",
    "sfc_second": "胜负彩二等奖",
    "renjiu_first": "任九一等奖",
}
_SETTLEMENT_METHOD_LABELS = {
    "operator-task-settlement-v1": "确定性整单结算 v1",
}
_ROUNDING_POLICY_LABELS = {
    "cn_sporttery_jczq_v1": "竞彩逐注四舍五入 v1",
    None: "足彩固定奖金整数结算",
}


class _OfficialHistoryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _BuiltTask:
    facts: OperatorTaskFacts
    summary: OperatorTaskSummary
    progress: TaskProgressSummary
    step: StepView
    mutation_token: str
    work_item_identity: str | None = None
    scope_kind: ScopeKind | None = None
    projected_state: OperatorTaskState | None = None
    deployment_outcome: str | None = None
    scope_label: str | None = None


@dataclass(frozen=True, slots=True)
class _SettlementProjection:
    state: str
    command_token: str | None = None
    request_state: str = "not_requested"
    placed_ticket_count: int = 0
    settled_ticket_count: int = 0
    blocking_codes: tuple[str, ...] = ()
    last_run: TaskSettlementRunSummary | None = None
    currency: str | None = None
    total_stake_minor: int = 0
    total_payout_minor: int = 0
    tickets: tuple[SettlementTicketSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorAuditLocator:
    lane: OperatorLane
    business_key: str
    work_item_key: str
    task_snapshot_hash: str


class OperatorAuditTokenResolver:
    """Issue and resolve audit-only locators through the configured HMAC codec."""

    _MARKER = "audit-envelope-v1"
    _COMMAND_KIND = OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION

    def __init__(self, codec: OperatorSnapshotTokenCodec) -> None:
        self._codec = codec

    def issue(
        self,
        *,
        lane: OperatorLane,
        business_key: str,
        work_item_key: str,
        task_snapshot_hash: str,
    ) -> str:
        locator = f"{self._MARKER}|{lane.value}|{business_key}|{work_item_key}"
        return self._codec.encode(
            OperatorSnapshotTokenPayloadV1(
                task_snapshot_hash=task_snapshot_hash,
                work_item_id=locator,
                command_kind=self._COMMAND_KIND,
                dependency_revision_ids=[],
            )
        )

    def resolve(self, token: str) -> OperatorAuditLocator:
        try:
            payload = self._codec.decode(token)
            parts = payload.work_item_id.split("|")
            if (
                payload.command_kind is not self._COMMAND_KIND
                or payload.dependency_revision_ids
                or len(parts) != 4
                or parts[0] != self._MARKER
            ):
                raise ValueError("not an audit locator")
            lane = OperatorLane(parts[1])
            business_key = parts[2]
            work_item_key = parts[3]
            business_pattern = (
                r"\d{5}" if lane is OperatorLane.ZUCAI else r"\d{4}-\d{2}-\d{2}"
            )
            if (
                re.fullmatch(business_pattern, business_key) is None
                or re.fullmatch(r"[a-z][a-z0-9-]{8,100}", work_item_key) is None
            ):
                raise ValueError("invalid audit locator")
        except (OperatorSnapshotTokenError, ValueError) as error:
            raise ProductNotFoundError("operator audit record not found") from error
        return OperatorAuditLocator(
            lane=lane,
            business_key=business_key,
            work_item_key=work_item_key,
            task_snapshot_hash=payload.task_snapshot_hash,
        )


@dataclass(frozen=True, slots=True)
class BaselineEnvelopeCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    expected_current_revision_no: int


@dataclass(frozen=True, slots=True)
class MatchJudgmentCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    match_id: str
    official_offer_revision_id: str
    market_definition_id: str
    prior: tuple[tuple[str, str], ...]
    evidence_refs_by_token: tuple[tuple[str, str], ...]
    expected_current_revision_no: int


@dataclass(frozen=True, slots=True)
class JudgmentPrescriptionCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_revision_tokens: tuple[str, ...]
    judgment_revision_ids: tuple[str, ...]
    expected_current_revision_no: int


@dataclass(frozen=True, slots=True)
class CandidateGenerationCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    fixed_prize_policy_revision_id: str | None
    expected_current_revision_no: int
    market_prior_baseline_token: str
    baseline_envelope_token: str
    judgment_prescription_token: str


@dataclass(frozen=True, slots=True)
class ConfirmationRequestCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    ticket_artifact_id: str
    command_token: str
    ticket_artifact_token: str


@dataclass(frozen=True, slots=True)
class CandidateSelectionCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    expected_current_revision_no: int
    candidate_refs_by_token: tuple[tuple[str, str, str], ...]
    candidate_set_revision_id: str
    candidate_revision_id: str


@dataclass(frozen=True, slots=True)
class SettlementRequestCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    slate_revision_id: str
    result_set_revision_id: str
    prize_table_revision_id: str | None
    command_token: str


@dataclass(frozen=True, slots=True)
class PredictionGradeCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    prediction_refs_by_token: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ScoreboardReviewCommandContext:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    dependency_revision_ids: tuple[str, ...]
    review_id: str
    review_token: str
    disposition_revision_id: str | None
    disposition_token: str | None
    evidence_refs_by_token: tuple[tuple[str, ObjectRef], ...]
    observation_refs_by_token: tuple[tuple[str, str], ...]
    command_kind: OperatorCommandKind


@dataclass(frozen=True, slots=True)
class _DecisionLineage:
    task_key: str
    task_snapshot_hash: str
    work_item_id: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    baseline_envelope_revision_id: str | None
    baseline_envelope_revision_no: int
    required_match_ids: tuple[str, ...]


def _current_leaf_rows(connection, table, id_column, *filters):
    superseding = table.alias(f"{table.name}_superseding")
    rows = connection.execute(
        select(table)
        .where(
            *filters,
            ~exists(select(1).where(superseding.c.supersedes_revision_id == id_column)),
        )
        .order_by(table.c.revision_no, id_column)
    ).mappings()
    return tuple(dict(row) for row in rows)


def _decision_dependencies(lineage: _DecisionLineage) -> tuple[str, ...]:
    values = {
        f"baseline:{lineage.market_prior_baseline_revision_id}",
        f"bundle:{lineage.task_evidence_bundle_revision_id}",
        f"slate:{lineage.slate_revision_id}",
    }
    if lineage.baseline_envelope_revision_id is not None:
        values.add(f"envelope:{lineage.baseline_envelope_revision_id}")
    return tuple(sorted(values))


def _current_forecast_revision(
    uow,
    *,
    match_id: str,
    market_definition_id: str,
) -> tuple[int, str | None]:
    row = uow.connection.execute(
        select(
            sd.forecast_revisions.c.revision_no,
            sd.forecast_revisions.c.forecast_revision_id,
        )
        .select_from(
            sd.forecast_revisions.join(
                sd.forecast_series,
                sd.forecast_revisions.c.forecast_series_id
                == sd.forecast_series.c.forecast_series_id,
            )
        )
        .where(
            sd.forecast_series.c.match_id == match_id,
            sd.forecast_series.c.market_definition_id == market_definition_id,
            sd.forecast_revisions.c.status == "committed",
        )
        .order_by(sd.forecast_revisions.c.revision_no.desc())
        .limit(1)
    ).first()
    if row is None:
        return 0, None
    return int(row.revision_no), str(row.forecast_revision_id)


def _current_judgments(uow, lineage: _DecisionLineage):
    rows = _current_leaf_rows(
        uow.connection,
        sod.operator_match_judgment_revisions,
        sod.operator_match_judgment_revisions.c.operator_match_judgment_revision_id,
        sod.operator_match_judgment_revisions.c.task_family_id == lineage.task_key,
        sod.operator_match_judgment_revisions.c.work_item_id == lineage.work_item_id,
        sod.operator_match_judgment_revisions.c.task_snapshot_hash == lineage.task_snapshot_hash,
        sod.operator_match_judgment_revisions.c.task_evidence_bundle_revision_id
        == lineage.task_evidence_bundle_revision_id,
        sod.operator_match_judgment_revisions.c.market_prior_baseline_revision_id
        == lineage.market_prior_baseline_revision_id,
        sod.operator_match_judgment_revisions.c.baseline_envelope_revision_id
        == lineage.baseline_envelope_revision_id,
    )
    committed: list[dict[str, object]] = []
    for row in rows:
        _revision_no, current_forecast_id = _current_forecast_revision(
            uow,
            match_id=str(row["match_id"]),
            market_definition_id=str(row["market_definition_id"]),
        )
        if current_forecast_id == str(
            row["forecast_revision_id"]
        ) and uow.operator_decision.action_is_committed(
            str(row["action_id"]),
            action_type="commit_operator_match_judgment",
        ):
            committed.append(row)
    return tuple(sorted(committed, key=lambda row: str(row["match_id"])))


def _current_baseline_rows(uow, task_key: str, bundle, as_of: datetime):
    return _current_leaf_rows(
        uow.connection,
        sod.operator_market_prior_baseline_revisions,
        sod.operator_market_prior_baseline_revisions.c.market_prior_baseline_revision_id,
        sod.operator_market_prior_baseline_revisions.c.task_evidence_bundle_revision_id
        == bundle.task_evidence_bundle_revision_id,
        sod.operator_market_prior_baseline_revisions.c.task_family_id == task_key,
        sod.operator_market_prior_baseline_revisions.c.task_snapshot_hash
        == bundle.task_snapshot_hash,
        func.julianday(sod.operator_market_prior_baseline_revisions.c.created_at)
        <= func.julianday(as_of.isoformat()),
    )


def _decimal_text(value: Decimal) -> str:
    normalized = value.quantize(_PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(Decimal(0) if normalized == 0 else normalized, ".12f")


def _history_decimal_text(value: float | None) -> str | None:
    return None if value is None else format(Decimal(str(value)), "f")


def _face_sort_key(face_code: str) -> tuple[int, str]:
    return _FACE_ORDER.find(face_code) if face_code in _FACE_ORDER else 3, face_code


def _face_label(face_code: str, market_code: str) -> str:
    if market_code == "hhad":
        return {"3": "让胜", "1": "让平", "0": "让负"}.get(face_code, face_code)
    if market_code == "ttg" and face_code.startswith("total_"):
        total = face_code.removeprefix("total_")
        return f"{total}{'+' if total == '7' else ''} 球"
    return _FACE_LABELS.get(face_code, face_code)


def _all_face_bundle_views(face_codes: tuple[str, ...]) -> list[JudgmentFaceBundleView]:
    if (1 << len(face_codes)) - 1 > 100:
        raise ProductActionBlockedError(
            "market face combinations exceed the structured editor limit"
        )
    return [
        JudgmentFaceBundleView(
            bundle_code="faces-" + "-".join(selected),
            face_codes=list(selected),
        )
        for size in range(1, len(face_codes) + 1)
        for selected in combinations(face_codes, size)
    ]


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


def _opaque_reference(kind: str, *parts: object) -> str:
    return "opaque." + _token({"kind": kind, "parts": parts})


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
        official_history_provider: Callable[[], list[OfficialRenjiuHistory]],
        clock: Callable[[], datetime],
        legacy_fixture_adapter: ZucaiReplayBundleAdapter | None = None,
        operator_evidence: OperatorEvidenceService | None = None,
        unit_of_work_factory: Callable[[], OntologyUnitOfWork] | None = None,
        snapshot_tokens: OperatorSnapshotTokenCodec | None = None,
        operator_decisions=None,
        operator_candidate_auditor=None,
        maintenance_probe: OperatorMaintenanceProbe | None = None,
        shadow_review_tokens: ShadowReviewTokenCodec | None = None,
    ) -> None:
        self._repository = repository
        self._product_queries = product_queries
        self._legacy_fixture_adapter = legacy_fixture_adapter
        self._official_history = official_history_provider
        self._clock = clock
        self._operator_evidence = operator_evidence
        self._unit_of_work_factory = unit_of_work_factory
        self._snapshot_tokens = snapshot_tokens
        self._audit_tokens = (
            None
            if snapshot_tokens is None
            else OperatorAuditTokenResolver(snapshot_tokens)
        )
        self._operator_decisions = operator_decisions
        self._operator_candidate_auditor = operator_candidate_auditor
        self._maintenance_probe = maintenance_probe
        self._shadow_review_tokens = shadow_review_tokens

    def maintenance(self, *, as_of: datetime) -> OperatorMaintenanceResponseV1:
        cutoff = _aware(as_of, "as_of")
        if self._maintenance_probe is None:
            raise ProductNotFoundError("operator maintenance diagnostic is unavailable")
        return self._maintenance_probe.read(as_of=cutoff)

    def evidence_freeze_context(self, task_key: str, *, as_of: datetime):
        if self._operator_evidence is None:
            raise ProductNotFoundError("operator evidence service is unavailable")
        return self._operator_evidence.evidence_freeze_context(task_key, as_of=as_of)

    def confirmation_request_context(
        self,
        task_key: str,
        ticket_artifact_token: str,
        *,
        as_of: datetime,
    ) -> ConfirmationRequestCommandContext:
        cutoff = _aware(as_of, "as_of")
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError(
                "operator confirmation tokens are not configured"
            )
        artifact_payload = self._snapshot_tokens.decode(ticket_artifact_token)
        if (
            artifact_payload.command_kind
            is not OperatorCommandKind.REQUEST_CONFIRMATION
            or len(artifact_payload.dependency_revision_ids) != 1
        ):
            raise OperatorSnapshotTokenError("invalid_request")
        dependency = artifact_payload.dependency_revision_ids[0]
        marker = "ticket_artifact:"
        if not dependency.startswith(marker) or not dependency.removeprefix(marker):
            raise OperatorSnapshotTokenError("invalid_request")
        artifact_id = dependency.removeprefix(marker)
        with self._decision_uow() as uow:
            link = uow.tickets.artifact_work_item_link(artifact_id)
            if (
                link is None
                or link.task_family_id != task_key
                or _aware(
                    datetime.fromisoformat(link.linked_at),
                    "artifact link time",
                )
                > cutoff
            ):
                raise OperatorSnapshotTokenError("invalid_request")
            stage = self._formal_artifact_stage(
                uow,
                link,
                OperatorLane(link.task_family_id.partition(":")[0]),
                link.task_family_id.partition(":")[2],
                cutoff,
            )
        if (
            not isinstance(stage.step, ConfirmationStep)
            or stage.step.surface_version != "2"
            or stage.step.confirmation_state != "not_issued"
            or stage.step.command_token is None
            or stage.step.ticket_artifact_token != ticket_artifact_token
        ):
            raise ProductActionBlockedError(
                "artifact confirmation command is no longer current",
                code="task_snapshot_changed",
            )
        command_payload = self._snapshot_tokens.decode(stage.step.command_token)
        if (
            command_payload.work_item_id != artifact_payload.work_item_id
            or command_payload.task_snapshot_hash
            != artifact_payload.task_snapshot_hash
        ):
            raise OperatorSnapshotTokenError("task_snapshot_changed")
        return ConfirmationRequestCommandContext(
            task_key=task_key,
            task_snapshot_hash=command_payload.task_snapshot_hash,
            work_item_id=command_payload.work_item_id,
            dependency_revision_ids=tuple(
                command_payload.dependency_revision_ids
            ),
            ticket_artifact_id=artifact_id,
            command_token=stage.step.command_token,
            ticket_artifact_token=ticket_artifact_token,
        )

    def prediction_grade_context(
        self,
        task_key: str,
        expected_snapshot_token: str,
        *,
        as_of: datetime,
    ) -> PredictionGradeCommandContext:
        cutoff = _aware(as_of, "as_of")
        with self._decision_uow() as uow:
            review = self._pending_review_from_snapshot_token(
                uow,
                task_key,
                expected_snapshot_token,
                OperatorCommandKind.GRADE_PREDICTION,
            )
            predictions = self._review_predictions(
                uow,
                review.business_key,
                cutoff,
                pending_only=True,
            )
        if not predictions:
            raise ProductActionBlockedError("review has no pending prediction grade")
        dependencies = tuple(
            sorted(
                {
                    f"review:{review.review_id}",
                    *(f"prediction:{row['prediction_id']}" for row in predictions),
                }
            )
        )
        return PredictionGradeCommandContext(
            task_key=task_key,
            task_snapshot_hash=review.task_snapshot_hash,
            work_item_id=self._review_work_item_id(review),
            dependency_revision_ids=dependencies,
            prediction_refs_by_token=tuple(
                (
                    _opaque_reference(
                        "prediction-review",
                        review.review_id,
                        row["prediction_id"],
                    ),
                    str(row["prediction_id"]),
                )
                for row in predictions
            ),
        )

    def scoreboard_review_context(
        self,
        task_key: str,
        command_kind: OperatorCommandKind,
        expected_snapshot_token: str,
        *,
        as_of: datetime,
    ) -> ScoreboardReviewCommandContext:
        cutoff = _aware(as_of, "as_of")
        if command_kind not in {
            OperatorCommandKind.RECORD_SCOREBOARD_EFFECT_DISPOSITION,
            OperatorCommandKind.RECORD_SCOREBOARD_OBSERVATION,
            OperatorCommandKind.REQUEST_SCOREBOARD_REVIEW_COMPLETION,
        }:
            raise ProductActionBlockedError("unsupported scoreboard review command")
        projection = self._repository.scoreboard_projection(as_of=cutoff.isoformat())
        health = projection.get("health", {})
        if health.get("state") != "available":
            raise ProductActionBlockedError(
                "scoreboard projection must be rebuilt before this review action",
                code=(
                    "projection_stale"
                    if health.get("state") == "stale"
                    else "projection_unavailable"
                ),
            )
        high_watermark = health.get("source_high_watermark")
        if not isinstance(high_watermark, int) or high_watermark < 0:
            raise ProductActionBlockedError(
                "scoreboard projection has no valid source high water",
                code="projection_unavailable",
            )
        with self._decision_uow() as uow:
            review = self._pending_review_from_snapshot_token(
                uow,
                task_key,
                expected_snapshot_token,
                command_kind,
            )
            disposition = uow.operator_review.current_disposition(review.review_id)
            predictions = self._review_predictions(
                uow,
                review.business_key,
                cutoff,
                pending_only=False,
            )
            observation_refs: list[tuple[str, str]] = []
            if disposition is not None:
                for metric_key in disposition.required_metric_keys:
                    observation = uow.scoreboard.current_observation(
                        "review-effect",
                        metric_key,
                    )
                    if observation is not None:
                        observation_refs.append(
                            (
                                _opaque_reference(
                                    "scoreboard-observation",
                                    review.review_id,
                                    observation.scoreboard_observation_id,
                                ),
                                observation.scoreboard_observation_id,
                            )
                        )
        dependencies = tuple(
            sorted(
                {
                    f"review:{review.review_id}",
                    f"scoreboard_projection:{high_watermark}",
                    *(
                        ()
                        if disposition is None
                        else (f"disposition:{disposition.disposition_revision_id}",)
                    ),
                }
            )
        )
        evidence_refs = [
            (
                _opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "operator-review",
                    review.review_id,
                ),
                ObjectRef("operator_review", review.review_id),
            ),
            *[
            (
                _opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "prediction",
                    row["prediction_id"],
                ),
                ObjectRef("prediction", str(row["prediction_id"])),
            )
            for row in predictions
            ],
        ]
        evidence_refs.extend(
            (
                _opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "outcome",
                    outcome_id,
                ),
                ObjectRef("outcome", outcome_id),
            )
            for outcome_id in review.outcome_revision_ids
        )
        return ScoreboardReviewCommandContext(
            task_key=task_key,
            task_snapshot_hash=review.task_snapshot_hash,
            work_item_id=self._review_work_item_id(review),
            dependency_revision_ids=dependencies,
            review_id=review.review_id,
            review_token=_opaque_reference(
                "operator-review",
                review.review_id,
                review.task_snapshot_hash,
            ),
            disposition_revision_id=(
                None if disposition is None else disposition.disposition_revision_id
            ),
            disposition_token=(
                None
                if disposition is None
                else _opaque_reference(
                    "scoreboard-disposition",
                    review.review_id,
                    disposition.disposition_revision_id,
                )
            ),
            evidence_refs_by_token=tuple(evidence_refs),
            observation_refs_by_token=tuple(observation_refs),
            command_kind=command_kind,
        )

    @staticmethod
    def _review_work_item_id(review) -> str:
        return f"{review.task_family_id}:review:{review.review_id}"

    def _pending_review_from_snapshot_token(
        self,
        uow,
        task_key: str,
        expected_snapshot_token: str,
        command_kind: OperatorCommandKind,
    ):
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator snapshot tokens are not configured")
        payload = self._snapshot_tokens.decode(expected_snapshot_token)
        prefix = f"{task_key}:review:"
        if payload.command_kind is not command_kind or not payload.work_item_id.startswith(
            prefix
        ):
            raise OperatorSnapshotTokenError("invalid_request")
        review_id = payload.work_item_id.removeprefix(prefix)
        if not review_id or ":" in review_id:
            raise OperatorSnapshotTokenError("invalid_request")
        review = uow.operator_review.review_item(review_id)
        if (
            review is None
            or review.task_family_id != task_key
            or self._review_work_item_id(review) != payload.work_item_id
        ):
            raise OperatorSnapshotTokenError("invalid_request")
        if (
            review.task_snapshot_hash != payload.task_snapshot_hash
            or uow.operator_review.completion_receipt_for_review(review.review_id)
            is not None
        ):
            raise OperatorSnapshotTokenError("task_snapshot_changed")
        return review

    @staticmethod
    def _review_predictions(
        uow,
        business_key: str,
        cutoff: datetime,
        *,
        pending_only: bool,
    ) -> tuple[dict[str, object], ...]:
        statement = select(sw.predictions).where(
            sw.predictions.c.subject_type == "issue",
            sw.predictions.c.subject_id == business_key,
            func.julianday(sw.predictions.c.registered_at)
            <= func.julianday(cutoff.isoformat()),
        )
        if pending_only:
            statement = statement.where(sw.predictions.c.status == "pending")
        rows = uow.connection.execute(
            statement.order_by(
                sw.predictions.c.registered_at,
                sw.predictions.c.prediction_id,
            )
        ).mappings()
        return tuple(dict(row) for row in rows)

    def settlement_request_context(
        self,
        task_key: str,
        *,
        as_of: datetime,
    ) -> SettlementRequestCommandContext:
        cutoff = _aware(as_of, "as_of")
        lane_value, separator, business_key = task_key.partition(":")
        if separator != ":" or lane_value not in {"jczq", "zucai"} or not business_key:
            raise ProductActionBlockedError("invalid operator settlement task")
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator settlement tokens are not configured")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=True,
            )
            result_set = uow.operator_result.current_result_set(
                lane=lane_value,
                business_key=business_key,
            )
        if result_set is None:
            raise ProductActionBlockedError("authoritative results are not available")
        expected_lineage = (
            result_set.task_family_id == lineage.task_key
            and result_set.work_item_id == lineage.work_item_id
            and result_set.task_snapshot_hash == lineage.task_snapshot_hash
            and result_set.slate_revision_id == lineage.slate_revision_id
        )
        if not expected_lineage:
            raise ProductActionBlockedError("result evidence does not match the current task")
        if result_set.outcome_count != result_set.match_count:
            raise ProductActionBlockedError("authoritative results are not complete")
        prize_table_revision_id = result_set.zucai_prize_table_revision_id
        if lane_value == "zucai" and prize_table_revision_id is None:
            raise ProductActionBlockedError("official prize table is not available")
        if lane_value == "jczq" and prize_table_revision_id is not None:
            raise ProductActionBlockedError("JCZQ result set cannot include a prize table")
        dependencies = tuple(
            sorted(
                (
                    f"result_set_revision:{result_set.result_set_revision_id}",
                    f"slate_revision:{lineage.slate_revision_id}",
                )
            )
        )
        payload = OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            command_kind=OperatorCommandKind.REQUEST_SETTLEMENT,
            dependency_revision_ids=list(dependencies),
        )
        return SettlementRequestCommandContext(
            task_key=task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=dependencies,
            slate_revision_id=lineage.slate_revision_id,
            result_set_revision_id=result_set.result_set_revision_id,
            prize_table_revision_id=prize_table_revision_id,
            command_token=self._snapshot_tokens.encode(payload),
        )

    def baseline_envelope_context(
        self,
        task_key: str,
        *,
        as_of: datetime,
    ) -> BaselineEnvelopeCommandContext:
        cutoff = _aware(as_of, "as_of")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=False,
            )
        return BaselineEnvelopeCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=_decision_dependencies(lineage),
            task_evidence_bundle_revision_id=(lineage.task_evidence_bundle_revision_id),
            market_prior_baseline_revision_id=(lineage.market_prior_baseline_revision_id),
            expected_current_revision_no=lineage.baseline_envelope_revision_no,
        )

    def match_judgment_context(
        self,
        task_key: str,
        official_match_no: str,
        market_code: str,
        *,
        as_of: datetime,
    ) -> MatchJudgmentCommandContext:
        cutoff = _aware(as_of, "as_of")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=True,
            )
            return self._match_judgment_context_for_lineage(
                uow,
                lineage,
                official_match_no,
                market_code,
            )

    def _match_judgment_context_for_lineage(
        self,
        uow,
        lineage: _DecisionLineage,
        official_match_no: str,
        market_code: str,
    ) -> MatchJudgmentCommandContext:
        offer = next(
            (
                item
                for item in uow.operator_sale.offer_revisions_for_slate(lineage.slate_revision_id)
                if item.official_match_no == official_match_no
            ),
            None,
        )
        if offer is None:
            raise ProductActionBlockedError("judgment offer is not in the current task snapshot")
        baseline_rows = uow.operator_decision.market_prior_baseline_probabilities(
            lineage.market_prior_baseline_revision_id
        )
        market_ids = {
            str(row["market_definition_id"])
            for row in baseline_rows
            if str(row["official_offer_revision_id"]) == offer.official_offer_revision_id
            and str(row["match_id"]) == offer.match_id
            and uow.market.market_kind(str(row["market_definition_id"])) == market_code
        }
        if len(market_ids) != 1:
            raise ProductActionBlockedError("judgment market has no exact current baseline")
        market_definition_id = next(iter(market_ids))
        prior = tuple(
            (
                str(row["face_code"]),
                str(row["probability_decimal"]),
            )
            for row in baseline_rows
            if str(row["official_offer_revision_id"]) == offer.official_offer_revision_id
            and str(row["match_id"]) == offer.match_id
            and str(row["market_definition_id"]) == market_definition_id
        )
        if not prior:
            raise ProductActionBlockedError("judgment market has no exact current baseline")
        expected_revision_no, forecast_revision_id = _current_forecast_revision(
            uow,
            match_id=offer.match_id,
            market_definition_id=market_definition_id,
        )
        dependencies = list(_decision_dependencies(lineage))
        dependencies.append(f"offer:{offer.official_offer_revision_id}")
        if forecast_revision_id is not None:
            dependencies.append(f"forecast:{forecast_revision_id}")
        evidence_refs = self._judgment_evidence_refs(
            uow,
            lineage,
            match_id=offer.match_id,
        )
        return MatchJudgmentCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=tuple(sorted(dependencies)),
            task_evidence_bundle_revision_id=(lineage.task_evidence_bundle_revision_id),
            market_prior_baseline_revision_id=(lineage.market_prior_baseline_revision_id),
            baseline_envelope_revision_id=(lineage.baseline_envelope_revision_id or ""),
            match_id=offer.match_id,
            official_offer_revision_id=offer.official_offer_revision_id,
            market_definition_id=market_definition_id,
            prior=prior,
            evidence_refs_by_token=tuple(
                (
                    self._judgment_evidence_token(lineage, evidence_ref),
                    evidence_ref,
                )
                for evidence_ref in evidence_refs
            ),
            expected_current_revision_no=expected_revision_no,
        )

    def judgment_prescription_context(
        self,
        task_key: str,
        *,
        as_of: datetime,
    ) -> JudgmentPrescriptionCommandContext:
        cutoff = _aware(as_of, "as_of")
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator snapshot tokens are not configured")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=True,
            )
            judgments = _current_judgments(uow, lineage)
            if len(judgments) != len(lineage.required_match_ids) or {
                str(row["match_id"]) for row in judgments
            } != set(lineage.required_match_ids):
                raise ProductActionBlockedError(
                    "prescription requires every current committed judgment"
                )
            judgment_ids = tuple(
                str(row["operator_match_judgment_revision_id"]) for row in judgments
            )
            dependencies = tuple(
                sorted(
                    (*_decision_dependencies(lineage),)
                    + tuple(f"judgment:{item}" for item in judgment_ids)
                )
            )
            judgment_tokens = tuple(
                self._snapshot_tokens.encode(
                    OperatorSnapshotTokenPayloadV1(
                        task_snapshot_hash=lineage.task_snapshot_hash,
                        work_item_id=lineage.work_item_id,
                        command_kind=(OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION),
                        dependency_revision_ids=[f"judgment:{revision_id}"],
                    )
                )
                for revision_id in judgment_ids
            )
            prescription_rows = _current_leaf_rows(
                uow.connection,
                sod.operator_judgment_prescription_revisions,
                sod.operator_judgment_prescription_revisions.c.judgment_prescription_revision_id,
                sod.operator_judgment_prescription_revisions.c.task_family_id
                == lineage.task_key,
                sod.operator_judgment_prescription_revisions.c.work_item_id
                == lineage.work_item_id,
                sod.operator_judgment_prescription_revisions.c.task_snapshot_hash
                == lineage.task_snapshot_hash,
                sod.operator_judgment_prescription_revisions.c.task_evidence_bundle_revision_id
                == lineage.task_evidence_bundle_revision_id,
                sod.operator_judgment_prescription_revisions.c.market_prior_baseline_revision_id
                == lineage.market_prior_baseline_revision_id,
                sod.operator_judgment_prescription_revisions.c.baseline_envelope_revision_id
                == lineage.baseline_envelope_revision_id,
            )
            if len(prescription_rows) > 1:
                raise ProductActionBlockedError("task judgment prescription is ambiguous")
            prescription = prescription_rows[0] if prescription_rows else None
            if prescription is not None and not uow.operator_decision.action_is_committed(
                str(prescription["action_id"]),
                action_type="freeze_judgment_prescription",
            ):
                raise ProductActionBlockedError(
                    "task judgment prescription is not committed"
                )
        return JudgmentPrescriptionCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=dependencies,
            task_evidence_bundle_revision_id=(lineage.task_evidence_bundle_revision_id),
            market_prior_baseline_revision_id=(lineage.market_prior_baseline_revision_id),
            baseline_envelope_revision_id=(lineage.baseline_envelope_revision_id or ""),
            judgment_revision_tokens=judgment_tokens,
            judgment_revision_ids=judgment_ids,
            expected_current_revision_no=(
                0 if prescription is None else int(prescription["revision_no"])
            ),
        )

    def candidate_generation_context(
        self,
        task_key: str,
        *,
        as_of: datetime,
    ) -> CandidateGenerationCommandContext:
        cutoff = _aware(as_of, "as_of")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=True,
            )
            prescription = self._current_prescription(uow, lineage)
            if prescription is None:
                raise ProductActionBlockedError(
                    "candidate generation requires a current frozen prescription"
                )
            return self._candidate_generation_context_for_lineage(
                uow,
                lineage,
                prescription,
            )

    def candidate_selection_context(
        self,
        task_key: str,
        candidate_token: str,
        *,
        as_of: datetime,
    ) -> CandidateSelectionCommandContext:
        cutoff = _aware(as_of, "as_of")
        with self._decision_uow() as uow:
            lineage = self._decision_lineage(
                uow,
                task_key,
                cutoff,
                require_envelope=True,
            )
            prescription = self._current_prescription(uow, lineage)
            if prescription is None:
                raise ProductActionBlockedError(
                    "candidate selection requires a current frozen prescription"
                )
            candidate_sets = self._current_candidate_sets(
                uow,
                lineage,
                str(prescription["judgment_prescription_revision_id"]),
            )
            if not candidate_sets:
                raise ProductActionBlockedError(
                    "candidate selection requires current generated candidate sets"
                )
            judgment_set = next(
                item for item in candidate_sets if item.set_kind == "judgment_bound"
            )
            selection = uow.operator_decision.current_candidate_selection(
                task_family_id=lineage.task_key,
                work_item_id=lineage.work_item_id,
            )
            if (
                selection is not None
                and selection.candidate_set_revision_id
                == judgment_set.candidate_set_revision_id
                and uow.operator_decision.action_is_committed(
                    selection.action_id,
                    action_type="select_ticket_candidate",
                )
            ):
                raise ProductActionBlockedError(
                    "ticket candidate is already selected for this candidate set"
                )
            dependencies = self._candidate_selection_dependencies(
                lineage,
                prescription_revision_id=str(
                    prescription["judgment_prescription_revision_id"]
                ),
                candidate_sets=candidate_sets,
                selection=selection,
            )
            refs = self._candidate_selection_refs(
                uow,
                lineage,
                judgment_set,
                dependencies,
            )
            selected = next(
                (item for item in refs if item[0] == candidate_token),
                None,
            )
            if selected is None:
                raise ProductActionBlockedError(
                    "candidate selection token is stale or invalid"
                )
            _, candidate_set_revision_id, candidate_revision_id = selected
            return CandidateSelectionCommandContext(
                task_key=lineage.task_key,
                task_snapshot_hash=lineage.task_snapshot_hash,
                work_item_id=lineage.work_item_id,
                dependency_revision_ids=dependencies,
                expected_current_revision_no=(
                    0 if selection is None else selection.revision_no
                ),
                candidate_refs_by_token=(selected,),
                candidate_set_revision_id=candidate_set_revision_id,
                candidate_revision_id=candidate_revision_id,
            )

    def _candidate_generation_context_for_lineage(
        self,
        uow,
        lineage: _DecisionLineage,
        prescription: dict[str, object],
    ) -> CandidateGenerationCommandContext:
        envelope = uow.operator_decision.baseline_envelope_revision(
            lineage.baseline_envelope_revision_id or ""
        )
        if envelope is None:
            raise ProductActionBlockedError(
                "candidate generation requires a current baseline envelope"
            )
        fixed_policy_id = None
        if envelope.ticket_kind != "jczq_pass":
            policy = uow.operator_result.current_fixed_prize_policy(
                envelope.ticket_kind
            )
            if policy is None:
                raise ProductActionBlockedError(
                    "candidate generation requires a current fixed-prize policy"
                )
            fixed_policy_id = policy.fixed_prize_policy_revision_id
        current_sets = tuple(
            uow.operator_result.current_candidate_set(
                task_family_id=lineage.task_key,
                work_item_id=lineage.work_item_id,
                set_kind=set_kind,
            )
            for set_kind in (
                "judgment_bound",
                "conditional_market_counterfactual",
            )
        )
        dependencies = set(_decision_dependencies(lineage))
        prescription_id = str(
            prescription["judgment_prescription_revision_id"]
        )
        dependencies.add(f"prescription:{prescription_id}")
        if fixed_policy_id is not None:
            dependencies.add(f"fixed-policy:{fixed_policy_id}")
        for set_kind, candidate_set in zip(
            ("judgment_bound", "conditional_market_counterfactual"),
            current_sets,
            strict=True,
        ):
            dependencies.add(
                f"candidate-set:{candidate_set.candidate_set_revision_id}"
                if candidate_set is not None
                else f"candidate-set:{set_kind}:none"
            )
        dependency_ids = tuple(sorted(dependencies))
        judgment_set = current_sets[0]
        command_kind = OperatorCommandKind.REQUEST_CANDIDATE_GENERATION
        return CandidateGenerationCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=dependency_ids,
            task_evidence_bundle_revision_id=(
                lineage.task_evidence_bundle_revision_id
            ),
            market_prior_baseline_revision_id=(
                lineage.market_prior_baseline_revision_id
            ),
            baseline_envelope_revision_id=(
                lineage.baseline_envelope_revision_id or ""
            ),
            judgment_prescription_revision_id=prescription_id,
            fixed_prize_policy_revision_id=fixed_policy_id,
            expected_current_revision_no=(
                0 if judgment_set is None else judgment_set.revision_no
            ),
            market_prior_baseline_token=self._decision_command_token(
                lineage,
                command_kind,
                (f"baseline:{lineage.market_prior_baseline_revision_id}",),
            ),
            baseline_envelope_token=self._decision_command_token(
                lineage,
                command_kind,
                (f"envelope:{lineage.baseline_envelope_revision_id}",),
            ),
            judgment_prescription_token=self._decision_command_token(
                lineage,
                command_kind,
                (f"prescription:{prescription_id}",),
            ),
        )

    @staticmethod
    def _current_prescription(uow, lineage: _DecisionLineage):
        rows = _current_leaf_rows(
            uow.connection,
            sod.operator_judgment_prescription_revisions,
            sod.operator_judgment_prescription_revisions.c.
            judgment_prescription_revision_id,
            sod.operator_judgment_prescription_revisions.c.task_family_id
            == lineage.task_key,
            sod.operator_judgment_prescription_revisions.c.work_item_id
            == lineage.work_item_id,
            sod.operator_judgment_prescription_revisions.c.task_snapshot_hash
            == lineage.task_snapshot_hash,
            sod.operator_judgment_prescription_revisions.c.
            task_evidence_bundle_revision_id
            == lineage.task_evidence_bundle_revision_id,
            sod.operator_judgment_prescription_revisions.c.
            market_prior_baseline_revision_id
            == lineage.market_prior_baseline_revision_id,
            sod.operator_judgment_prescription_revisions.c.
            baseline_envelope_revision_id
            == lineage.baseline_envelope_revision_id,
        )
        if len(rows) > 1:
            raise ProductActionBlockedError(
                "task judgment prescription is ambiguous"
            )
        prescription = rows[0] if rows else None
        if prescription is not None and not uow.operator_decision.action_is_committed(
            str(prescription["action_id"]),
            action_type="freeze_judgment_prescription",
        ):
            raise ProductActionBlockedError(
                "task judgment prescription is not committed"
            )
        return prescription

    @staticmethod
    def _current_candidate_sets(
        uow,
        lineage: _DecisionLineage,
        prescription_revision_id: str,
    ):
        candidate_sets = tuple(
            uow.operator_result.current_candidate_set(
                task_family_id=lineage.task_key,
                work_item_id=lineage.work_item_id,
                set_kind=set_kind,
            )
            for set_kind in (
                "judgment_bound",
                "conditional_market_counterfactual",
            )
        )
        if any(candidate_set is None for candidate_set in candidate_sets):
            return ()
        current_sets = tuple(
            candidate_set
            for candidate_set in candidate_sets
            if candidate_set is not None
        )
        generation_ids = {
            candidate_set.generation_request_id for candidate_set in current_sets
        }
        expected_lineage = (
            lineage.task_key,
            lineage.work_item_id,
            lineage.task_snapshot_hash,
            lineage.slate_revision_id,
            lineage.market_prior_baseline_revision_id,
            lineage.baseline_envelope_revision_id,
            prescription_revision_id,
        )
        if len(generation_ids) != 1 or any(
            (
                candidate_set.task_family_id,
                candidate_set.work_item_id,
                candidate_set.task_snapshot_hash,
                candidate_set.slate_revision_id,
                candidate_set.market_prior_baseline_revision_id,
                candidate_set.baseline_envelope_revision_id,
                candidate_set.judgment_prescription_revision_id,
            )
            != expected_lineage
            or not uow.operator_decision.action_is_committed(
                candidate_set.action_id,
                action_type="generate_ticket_candidate_set",
            )
            for candidate_set in current_sets
        ):
            return ()
        return current_sets

    @staticmethod
    def _candidate_selection_dependencies(
        lineage: _DecisionLineage,
        *,
        prescription_revision_id: str,
        candidate_sets,
        selection,
    ) -> tuple[str, ...]:
        dependencies = set(_decision_dependencies(lineage))
        dependencies.add(f"prescription:{prescription_revision_id}")
        dependencies.update(
            f"candidate-set:{candidate_set.candidate_set_revision_id}"
            for candidate_set in candidate_sets
        )
        dependencies.add(
            "selection:none"
            if selection is None
            else f"selection:{selection.candidate_selection_id}"
        )
        return tuple(sorted(dependencies))

    def _candidate_selection_refs(
        self,
        uow,
        lineage: _DecisionLineage,
        judgment_set,
        dependencies: tuple[str, ...],
    ) -> tuple[tuple[str, str, str], ...]:
        refs = []
        for candidate in uow.operator_result.candidates_for_set(
            judgment_set.candidate_set_revision_id
        ):
            if candidate.partition == "over_cap":
                continue
            token = self._decision_command_token(
                lineage,
                OperatorCommandKind.SELECT_CANDIDATE,
                tuple(sorted((*dependencies, f"candidate:{candidate.candidate_revision_id}"))),
            )
            refs.append(
                (
                    token,
                    judgment_set.candidate_set_revision_id,
                    candidate.candidate_revision_id,
                )
            )
        return tuple(refs)

    def _decision_uow(self):
        if self._unit_of_work_factory is None:
            raise ProductActionBlockedError("operator judgment reads are not configured")
        return self._unit_of_work_factory()

    @staticmethod
    def _decision_lineage(
        uow,
        task_key: str,
        as_of: datetime,
        *,
        require_envelope: bool,
    ) -> _DecisionLineage:
        bundle = uow.operator_decision.current_task_evidence_bundle_revision(
            task_key,
            as_of=as_of.isoformat(),
        )
        if bundle is None:
            raise ProductActionBlockedError("task has no current frozen evidence bundle")
        baseline_rows = _current_baseline_rows(uow, task_key, bundle, as_of)
        if len(baseline_rows) != 1:
            raise ProductActionBlockedError("task market prior baseline is missing or ambiguous")
        baseline = baseline_rows[0]
        if not uow.operator_decision.action_is_committed(
            str(baseline["action_id"]),
            action_type="freeze_market_prior_baseline",
        ):
            raise ProductActionBlockedError("task market prior baseline is not committed")
        envelope_rows = _current_leaf_rows(
            uow.connection,
            sod.operator_baseline_envelope_revisions,
            sod.operator_baseline_envelope_revisions.c.baseline_envelope_revision_id,
            sod.operator_baseline_envelope_revisions.c.task_evidence_bundle_revision_id
            == bundle.task_evidence_bundle_revision_id,
            sod.operator_baseline_envelope_revisions.c.task_family_id == task_key,
            sod.operator_baseline_envelope_revisions.c.work_item_id
            == str(baseline["work_item_id"]),
            sod.operator_baseline_envelope_revisions.c.task_snapshot_hash
            == bundle.task_snapshot_hash,
            func.julianday(sod.operator_baseline_envelope_revisions.c.created_at)
            <= func.julianday(as_of.isoformat()),
        )
        if len(envelope_rows) > 1:
            raise ProductActionBlockedError("task baseline envelope is ambiguous")
        if require_envelope and len(envelope_rows) != 1:
            raise ProductActionBlockedError("task baseline envelope is not committed")
        envelope = envelope_rows[0] if envelope_rows else None
        if envelope is not None and not uow.operator_decision.action_is_committed(
            str(envelope["action_id"]),
            action_type="record_baseline_envelope",
        ):
            raise ProductActionBlockedError("task baseline envelope is not committed")
        items = uow.operator_decision.task_evidence_bundle_items(
            bundle.task_evidence_bundle_revision_id
        )
        return _DecisionLineage(
            task_key=task_key,
            task_snapshot_hash=bundle.task_snapshot_hash,
            work_item_id=str(baseline["work_item_id"]),
            slate_revision_id=bundle.slate_revision_id,
            task_evidence_bundle_revision_id=(bundle.task_evidence_bundle_revision_id),
            market_prior_baseline_revision_id=str(baseline["market_prior_baseline_revision_id"]),
            baseline_envelope_revision_id=(
                None if envelope is None else str(envelope["baseline_envelope_revision_id"])
            ),
            baseline_envelope_revision_no=(
                0 if envelope is None else int(envelope["revision_no"])
            ),
            required_match_ids=tuple(item.match_id for item in items),
        )

    def _formal_judgment_task(
        self,
        task_id: str,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        slate: SaleSlateSnapshot,
        cutoff: datetime,
    ) -> _BuiltTask | None:
        if self._unit_of_work_factory is None:
            return None
        if self._snapshot_tokens is None:
            return None
        candidate_sets = ()
        selection = None
        selection_completed = False
        with self._decision_uow() as uow:
            bundle = uow.operator_decision.current_task_evidence_bundle_revision(
                task_id,
                as_of=cutoff.isoformat(),
            )
            if bundle is None:
                return None
            baseline_rows = _current_baseline_rows(uow, task_id, bundle, cutoff)
            if not baseline_rows:
                return self._prepare_task(
                    task_id,
                    lane,
                    business_key,
                    deadline,
                    slate,
                    cutoff,
                )
            lineage = self._decision_lineage(
                uow,
                task_id,
                cutoff,
                require_envelope=False,
            )
            artifact_links = uow.tickets.artifact_work_item_links_for_work_item(
                lineage.work_item_id
            )
            if artifact_links:
                return self._formal_sale_wave_artifact_stage(
                    uow,
                    lineage,
                    lane,
                    business_key,
                    deadline,
                    cutoff,
                    artifact_links,
                )
            items = uow.operator_decision.task_evidence_bundle_items(
                lineage.task_evidence_bundle_revision_id
            )
            judgments = _current_judgments(uow, lineage)
            completed_match_ids = {str(row["match_id"]) for row in judgments}
            completed = len(completed_match_ids)
            total = len(lineage.required_match_ids)
            if lineage.baseline_envelope_revision_id is None:
                step = self._baseline_envelope_step(
                    uow,
                    lineage,
                    lane,
                    cutoff,
                )
                progress_label = "限定票面范围"
                dependency_ids = _decision_dependencies(lineage)
            else:
                unresolved = next(
                    (item for item in items if item.match_id not in completed_match_ids),
                    None,
                )
                if unresolved is not None:
                    step, dependency_ids = self._match_judgment_step(
                        uow,
                        lineage,
                        unresolved,
                        bundle,
                        cutoff,
                        completed=completed,
                        total=total,
                    )
                    progress_label = "逐场判断"
                else:
                    prescription = self._current_prescription(uow, lineage)
                    if prescription is None:
                        step, dependency_ids = self._prescription_ready_step(
                            lineage,
                            judgments,
                            completed=completed,
                            total=total,
                        )
                        progress_label = "冻结判断处方"
                    else:
                        prescription_id = str(
                            prescription["judgment_prescription_revision_id"]
                        )
                        candidate_sets = self._current_candidate_sets(
                            uow,
                            lineage,
                            prescription_id,
                        )
                        if not candidate_sets:
                            generation = self._candidate_generation_context_for_lineage(
                                uow,
                                lineage,
                                prescription,
                            )
                            step = ConstructTicketStep(
                                task_id=lineage.task_key,
                                mode="candidate_request",
                                request_generation_token=(
                                    self._decision_command_token(
                                        lineage,
                                        OperatorCommandKind.REQUEST_CANDIDATE_GENERATION,
                                        generation.dependency_revision_ids,
                                    )
                                ),
                                market_prior_baseline_token=(
                                    generation.market_prior_baseline_token
                                ),
                                baseline_envelope_token=(
                                    generation.baseline_envelope_token
                                ),
                                judgment_prescription_token=(
                                    generation.judgment_prescription_token
                                ),
                            )
                            dependency_ids = generation.dependency_revision_ids
                            progress_label = "生成完整候选集"
                        else:
                            judgment_set = next(
                                candidate_set
                                for candidate_set in candidate_sets
                                if candidate_set.set_kind == "judgment_bound"
                            )
                            selection = (
                                uow.operator_decision.current_candidate_selection(
                                    task_family_id=lineage.task_key,
                                    work_item_id=lineage.work_item_id,
                                )
                            )
                            selection_completed = bool(
                                selection is not None
                                and selection.candidate_set_revision_id
                                == judgment_set.candidate_set_revision_id
                                and uow.operator_decision.action_is_committed(
                                    selection.action_id,
                                    action_type="select_ticket_candidate",
                                )
                            )
                            dependency_ids = self._candidate_selection_dependencies(
                                lineage,
                                prescription_revision_id=prescription_id,
                                candidate_sets=candidate_sets,
                                selection=selection,
                            )
                            if selection_completed and selection is not None:
                                step, dependency_ids = self._deployment_step(
                                    uow,
                                    lineage,
                                    prescription,
                                    judgment_set,
                                    selection,
                                    dependency_ids,
                                    as_of=cutoff,
                                )
                            else:
                                step = self._candidate_comparison_step(
                                    uow,
                                    lineage,
                                    prescription,
                                    candidate_sets,
                                    dependency_ids,
                                    selection=None,
                                )
                            progress_label = (
                                "等待部署审计"
                                if selection_completed
                                else "比较候选票"
                            )
        formal_ticket_stage = isinstance(step, (ConstructTicketStep, AuditDeploymentStep))
        candidate_count = sum(
            candidate_set.candidate_count for candidate_set in candidate_sets
        )
        facts = OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0 if formal_ticket_stage else 1,
            candidate_count=candidate_count,
            selected_candidate_id=(
                selection.candidate_selection_id
                if selection_completed and selection is not None
                else None
            ),
            audit_recorded=False,
            deployment_decision=None,
            ticket_artifact_id=None,
            confirmation_state=None,
            placement_state=None,
            result_available=False,
            pending_review_items=0,
        )
        return _BuiltTask(
            facts=facts,
            summary=_summary(
                facts,
                title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ") + business_key,
            ),
            progress=TaskProgressSummary(
                completed=completed,
                total=total,
                label=progress_label,
            ),
            step=step,
            mutation_token=_token(
                {
                    "task_id": task_id,
                    "slate": slate,
                    "mode": step.mode,
                    "dependencies": dependency_ids,
                }
            ),
            work_item_identity=lineage.work_item_id,
            scope_kind=ScopeKind.SALE_WAVE,
        )

    def _formal_review_stages(
        self,
        task_id: str,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        cutoff: datetime,
    ) -> tuple[_BuiltTask, ...]:
        if self._unit_of_work_factory is None:
            return ()
        with self._decision_uow() as uow:
            review_ids = tuple(
                review.review_id
                for review in uow.operator_review.review_items_for_task(task_id)
            )
        return tuple(
            self._formal_review_stage(
                task_id,
                lane,
                business_key,
                deadline,
                cutoff,
                review_id=review_id,
            )
            for review_id in review_ids
        )

    def _formal_review_stage(
        self,
        task_id: str,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        cutoff: datetime,
        *,
        review_id: str | None = None,
    ) -> _BuiltTask:
        with self._decision_uow() as uow:
            reviews = uow.operator_review.review_items_for_task(task_id)
            if not reviews:
                raise ProductNotFoundError("operator review does not exist")
            pending = uow.operator_review.pending_review_items_for_task(task_id)
            review = next(
                (
                    item
                    for item in reviews
                    if review_id is None or item.review_id == review_id
                ),
                None,
            )
            if review is None:
                raise ProductNotFoundError("operator review does not exist")
            completion = uow.operator_review.completion_receipt_for_review(
                review.review_id
            )
            if completion is not None:
                facts = self._review_facts(
                    lane,
                    business_key,
                    deadline,
                    pending_count=0,
                )
                return _BuiltTask(
                    facts=facts,
                    summary=_summary(
                        facts,
                        title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                        + business_key,
                    ),
                    progress=TaskProgressSummary(
                        completed=1,
                        total=1,
                        label="复盘",
                    ),
                    step=CompleteStep(
                        task_id=task_id,
                        title="本期复盘已完成",
                        summary="预测、资金与治理处置均已留下可审计记录。",
                    ),
                    mutation_token=_token(
                        {
                            "task_id": task_id,
                            "completed_review": review.review_id,
                        }
                    ),
                    work_item_identity=self._review_work_item_id(review),
                    scope_kind=ScopeKind.REVIEW,
                    projected_state=OperatorTaskState.COMPLETE,
                )
            if review not in pending:
                raise ProductActionBlockedError("operator review state is inconsistent")
            fact = uow.operator_review.eligibility_fact(
                review.review_eligibility_fact_id
            )
            if fact is None:
                raise ProductActionBlockedError("review eligibility fact is unavailable")
            disposition = uow.operator_review.current_disposition(review.review_id)
            links = (
                ()
                if disposition is None
                else uow.operator_review.observation_links_for_disposition(
                    disposition.disposition_revision_id
                )
            )
            completion_requests = uow.operator_review.completion_requests_for_review(
                review.review_id
            )
            predictions = self._review_predictions(
                uow,
                business_key,
                cutoff,
                pending_only=False,
            )
            money = self._review_money_summary(uow, fact)
            shadow_rows = tuple(
                dict(row)
                for row in uow.connection.execute(
                    select(ss.scoreboard_shadow_reviews)
                    .where(
                        func.julianday(ss.scoreboard_shadow_reviews.c.reviewed_at)
                        <= func.julianday(cutoff.isoformat())
                    )
                    .order_by(
                        ss.scoreboard_shadow_reviews.c.reviewed_at.desc(),
                        ss.scoreboard_shadow_reviews.c.scoreboard_shadow_review_id.desc(),
                    )
                ).mappings()
            )
            action_rowids = {
                link.observation_action_id: uow.operator_review.action_rowid(
                    link.observation_action_id
                )
                for link in links
            }
            adjudication_rows = uow.operator_review.adjudication_history(
                business_key=business_key,
                as_of=cutoff.isoformat(),
            )
            observation_rows = (
                ()
                if disposition is None
                else uow.operator_review.scoreboard_observation_history(
                    disposition.disposition_revision_id
                )
            )

        projection = self._repository.scoreboard_projection(as_of=cutoff.isoformat())
        health = projection.get("health", {})
        projection_high_watermark = health.get("source_high_watermark")
        scoreboard_projection_state = {
            "available": "ready",
            "stale": "stale",
        }.get(str(health.get("state")), "unavailable")
        projection_ready = (
            scoreboard_projection_state == "ready"
            and isinstance(projection_high_watermark, int)
            and projection_high_watermark >= 0
        )
        review_work_item_id = self._review_work_item_id(review)
        review_token = _opaque_reference(
            "operator-review",
            review.review_id,
            review.task_snapshot_hash,
        )
        disposition_token = (
            None
            if disposition is None
            else _opaque_reference(
                "scoreboard-disposition",
                review.review_id,
                disposition.disposition_revision_id,
            )
        )
        scoreboard_dependencies = (
            ()
            if not projection_ready
            else tuple(
                sorted(
                    {
                        f"review:{review.review_id}",
                        f"scoreboard_projection:{projection_high_watermark}",
                        *(
                            ()
                            if disposition is None
                            else (
                                f"disposition:{disposition.disposition_revision_id}",
                            )
                        ),
                    }
                )
            )
        )

        def command_token(kind: OperatorCommandKind) -> str | None:
            if not projection_ready or self._snapshot_tokens is None:
                return None
            return self._snapshot_tokens.encode(
                OperatorSnapshotTokenPayloadV1(
                    task_snapshot_hash=review.task_snapshot_hash,
                    work_item_id=review_work_item_id,
                    command_kind=kind,
                    dependency_revision_ids=list(scoreboard_dependencies),
                )
            )

        pending_predictions = [
            row for row in predictions if row.get("status") == "pending"
        ]
        prediction_dependencies = tuple(
            sorted(
                {
                    f"review:{review.review_id}",
                    *(
                        f"prediction:{row['prediction_id']}"
                        for row in pending_predictions
                    ),
                }
            )
        )
        grade_token = (
            None
            if not pending_predictions or self._snapshot_tokens is None
            else self._snapshot_tokens.encode(
                OperatorSnapshotTokenPayloadV1(
                    task_snapshot_hash=review.task_snapshot_hash,
                    work_item_id=review_work_item_id,
                    command_kind=OperatorCommandKind.GRADE_PREDICTION,
                    dependency_revision_ids=list(prediction_dependencies),
                )
            )
        )
        forecast = [
            ReviewForecastSummary(
                title=str(row["claim"]),
                falsifier=str(row["falsifier"]),
                state=(
                    "pending"
                    if row.get("status") == "pending"
                    else str(row.get("outcome") or "na")
                ),
                prediction_review_token=(
                    _opaque_reference(
                        "prediction-review",
                        review.review_id,
                        row["prediction_id"],
                    )
                    if row.get("status") == "pending"
                    else None
                ),
                grade_command_token=(
                    grade_token if row.get("status") == "pending" else None
                ),
            )
            for row in predictions
        ]
        evidence_options = [
            ReviewEvidenceOptionSummary(
                label="本期复盘范围",
                token=_opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "operator-review",
                    review.review_id,
                ),
            ),
            *[
            ReviewEvidenceOptionSummary(
                label=f"预注册预测：{row['claim']}",
                token=_opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "prediction",
                    row["prediction_id"],
                ),
            )
            for row in predictions
            ],
        ]
        evidence_options.extend(
            ReviewEvidenceOptionSummary(
                label=f"正式赛果 {index}",
                token=_opaque_reference(
                    "review-evidence",
                    review.review_id,
                    "outcome",
                    outcome_id,
                ),
            )
            for index, outcome_id in enumerate(review.outcome_revision_ids, start=1)
        )
        shadow_options = self._review_shadow_options(
            review,
            disposition,
            links,
            shadow_rows,
            action_rowids,
        )
        linked_keys = sorted(link.metric_key for link in links)
        gates = self._review_completion_gates(
            disposition,
            links,
            completion_requested=bool(completion_requests),
        )
        intervention = ReviewInterventionSummary(
            disposition=("undecided" if disposition is None else disposition.disposition),
            reason=None if disposition is None else disposition.reason,
            required_metric_keys=(
                [] if disposition is None else list(disposition.required_metric_keys)
            ),
            linked_metric_keys=linked_keys,
            review_token=review_token,
            disposition_token=disposition_token,
            effect_command_token=command_token(
                OperatorCommandKind.RECORD_SCOREBOARD_EFFECT_DISPOSITION
            ),
            observation_command_token=(
                command_token(OperatorCommandKind.RECORD_SCOREBOARD_OBSERVATION)
                if disposition is not None
                and disposition.disposition == "effect_required"
                else None
            ),
            completion_command_token=(
                command_token(
                    OperatorCommandKind.REQUEST_SCOREBOARD_REVIEW_COMPLETION
                )
                if disposition is not None
                and disposition.disposition == "effect_required"
                else None
            ),
            evidence_options=evidence_options,
            shadow_options=shadow_options,
        )
        step = ReviewStep(
            surface_version="2",
            task_id=task_id,
            title="本期复盘",
            review_kind=review.review_kind,
            review_state="pending",
            scoreboard_projection_state=scoreboard_projection_state,
            forecast_truth=forecast,
            money_ledger=money,
            intervention_quality=intervention,
            adjudication_history=[
                ReviewAdjudicationSummary(
                    decision=row.decision,
                    reason=row.reason,
                    rejected_evidence_count=row.rejected_evidence_count,
                    created_at=_aware(
                        datetime.fromisoformat(row.created_at),
                        "adjudication created_at",
                    ),
                )
                for row in adjudication_rows
            ],
            scoreboard_observation_history=[
                ReviewScoreboardObservationSummary(
                    metric_key=row.metric_key,
                    tally=row.tally,
                    detail=row.detail,
                    status=row.status,
                    numerator_decimal=_history_decimal_text(row.numerator),
                    denominator_decimal=_history_decimal_text(row.denominator),
                    value_decimal=_history_decimal_text(row.value),
                    unit=row.unit,
                    effective_at=_aware(
                        datetime.fromisoformat(row.effective_at),
                        "scoreboard observation effective_at",
                    ),
                )
                for row in observation_rows
            ],
            completion_gates=gates,
            maintenance_href="/operator-next/maintenance",
        )
        facts = self._review_facts(
            lane,
            business_key,
            deadline,
            pending_count=1,
        )
        completed_steps = sum(item.state != "pending" for item in forecast)
        completed_steps += sum(gate.state in {"complete", "not_required"} for gate in gates)
        total_steps = len(forecast) + len(gates)
        return _BuiltTask(
            facts=facts,
            summary=_summary(
                facts,
                title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                + business_key,
            ),
            progress=TaskProgressSummary(
                completed=completed_steps,
                total=total_steps,
                label="复盘",
            ),
            step=step,
            mutation_token=_token(
                {
                    "task_id": task_id,
                    "review_id": review.review_id,
                    "review_state": "pending",
                    "review_kind": review.review_kind,
                    "disposition": (
                        None
                        if disposition is None
                        else disposition.disposition_revision_id
                    ),
                    "linked_metrics": linked_keys,
                    "projection_high_watermark": projection_high_watermark,
                }
            ),
            work_item_identity=review_work_item_id,
            scope_kind=ScopeKind.REVIEW,
            projected_state=OperatorTaskState.REVIEW,
        )

    @staticmethod
    def _review_facts(
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        *,
        pending_count: int,
    ) -> OperatorTaskFacts:
        return OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0,
            candidate_count=1,
            selected_candidate_id="review-terminal-scope",
            audit_recorded=True,
            deployment_decision="empty_position",
            ticket_artifact_id=None,
            confirmation_state=None,
            placement_state=None,
            result_available=True,
            pending_review_items=pending_count,
        )

    @staticmethod
    def _review_money_summary(uow, fact) -> ReviewMoneySummary:
        if fact.settlement_run_id is None:
            return ReviewMoneySummary(state="not_applicable")
        run = uow.operator_result.task_settlement_run(fact.settlement_run_id)
        if run is None:
            raise ProductActionBlockedError("review settlement receipt is unavailable")
        current = []
        for revision_id in run.ticket_settlement_revision_ids:
            revision = uow.operator_result.ticket_settlement_revision(revision_id)
            if revision is None:
                raise ProductActionBlockedError("review settlement row is unavailable")
            leaf = uow.operator_result.current_ticket_settlement(revision.ticket_id)
            if leaf is None:
                raise ProductActionBlockedError("review settlement head is unavailable")
            current.append(leaf)
        if not current:
            return ReviewMoneySummary(state="not_applicable")
        currencies = {row.currency for row in current}
        if len(currencies) != 1:
            raise ProductActionBlockedError("review settlement currencies conflict")
        stake_minor = sum(row.stake_minor for row in current)
        payout_minor = sum(row.gross_payout_minor for row in current)
        return ReviewMoneySummary(
            state=(
                "corrected"
                if any(row.settlement_state == "corrected" for row in current)
                else "settled"
            ),
            currency=currencies.pop(),
            stake_minor=stake_minor,
            payout_minor=payout_minor,
            pnl_minor=payout_minor - stake_minor,
            ticket_count=len(current),
        )

    def _review_shadow_options(
        self,
        review,
        disposition,
        links,
        shadow_rows: tuple[dict[str, object], ...],
        action_rowids: dict[str, int | None],
    ) -> list[ReviewShadowOptionSummary]:
        if (
            disposition is None
            or disposition.disposition != "effect_required"
            or self._shadow_review_tokens is None
        ):
            return []
        required = tuple(disposition.required_metric_keys)
        observed_hashes = {link.observed_legacy_sha256 for link in links}
        required_targets = {
            (
                link.metric_key,
                f"scoreboard_observation:{link.scoreboard_observation_id}",
            )
            for link in links
        }
        options = []
        for row in shadow_rows:
            classification = json.loads(str(row["classification_json"]))
            included = {
                (str(item.get("metric_key")), str(item.get("target_ref")))
                for item in classification
                if item.get("classification") != "unexplained"
            }
            unexplained = {
                (str(item.get("metric_key")), str(item.get("target_ref")))
                for item in classification
                if item.get("classification") == "unexplained"
            }
            high_watermark = int(row["source_high_watermark"])
            ready = (
                str(row["status"]) == "succeeded"
                and len(observed_hashes) == 1
                and str(row["legacy_sha256"]) in observed_hashes
                and required_targets <= included
                and required_targets.isdisjoint(unexplained)
                and all(
                    rowid is not None and rowid <= high_watermark
                    for rowid in action_rowids.values()
                )
            )
            reviewed_at = datetime.fromisoformat(str(row["reviewed_at"]))
            options.append(
                ReviewShadowOptionSummary(
                    label=f"{reviewed_at:%Y-%m-%d %H:%M} 影子核对",
                    state="ready" if ready else "not_ready",
                    token=self._shadow_review_tokens.encode(
                        ShadowReviewTokenPayload(
                            shadow_review_id=str(
                                row["scoreboard_shadow_review_id"]
                            ),
                            source_high_watermark=high_watermark,
                            compared_legacy_sha256=str(row["legacy_sha256"]),
                            metric_keys=required,
                        )
                    ),
                )
            )
        return options

    @staticmethod
    def _review_completion_gates(
        disposition,
        links,
        *,
        completion_requested: bool,
    ) -> list[ReviewCompletionGateSummary]:
        if disposition is not None and disposition.disposition == "no_effect":
            state = "not_required"
            detail = "已明确本次复盘不改变治理记分牌。"
            return [
                ReviewCompletionGateSummary(
                    gate=gate,
                    label=label,
                    state=state,
                    detail=detail,
                )
                for gate, label in (
                    ("legacy_update", "旧记分牌更新已观察"),
                    ("observations", "所需观察已提交"),
                    ("shadow_reconciliation", "所选影子核对有效"),
                )
            ]
        required = () if disposition is None else disposition.required_metric_keys
        linked = tuple(link.metric_key for link in links)
        observed_hashes = {link.observed_legacy_sha256 for link in links}
        legacy_complete = bool(
            disposition is not None
            and len(observed_hashes) == 1
            and disposition.pre_update_legacy_sha256 not in observed_hashes
        )
        observations_complete = bool(required and linked == required)
        return [
            ReviewCompletionGateSummary(
                gate="legacy_update",
                label="旧记分牌更新已观察",
                state="complete" if legacy_complete else "pending",
                detail=(
                    "已观察到更新后的权威文件。"
                    if legacy_complete
                    else "请先在外部治理步骤更新权威记分牌。"
                ),
            ),
            ReviewCompletionGateSummary(
                gate="observations",
                label="所需观察已提交",
                state="complete" if observations_complete else "pending",
                detail=(
                    "每项治理指标均已形成 typed Action。"
                    if observations_complete
                    else f"还需提交 {max(0, len(required) - len(linked))} 项治理观察。"
                ),
            ),
            ReviewCompletionGateSummary(
                gate="shadow_reconciliation",
                label="所选影子核对有效",
                state="pending",
                detail=(
                    "完成请求已提交，等待确定性校验回执。"
                    if completion_requested
                    else "等待选择并提交一份有效影子核对。"
                ),
            ),
        ]

    @staticmethod
    def _visible_artifact_terminal(uow, artifact_id: str, cutoff: datetime):
        terminal = uow.tickets.artifact_terminal_receipt(artifact_id)
        if terminal is None:
            return None
        terminal_at = _aware(
            datetime.fromisoformat(terminal.terminal_at),
            "artifact terminal time",
        )
        return terminal if terminal_at <= cutoff else None

    def _formal_sale_wave_artifact_stage(
        self,
        uow,
        lineage: _DecisionLineage,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        cutoff: datetime,
        links,
    ) -> _BuiltTask:
        terminals = tuple(
            self._visible_artifact_terminal(
                uow,
                link.ticket_artifact_id,
                cutoff,
            )
            for link in links
        )
        placed_count = sum(
            terminal is not None and terminal.terminal_kind == "placed"
            for terminal in terminals
        )
        terminal_count = sum(terminal is not None for terminal in terminals)
        if placed_count:
            outcome = "placed" if placed_count == len(links) else "partially_placed"
        elif terminal_count == len(links):
            outcome = (
                "no_ticket"
                if all(
                    terminal is not None
                    and terminal.terminal_reason == "human_no_ticket"
                    for terminal in terminals
                )
                else "expired"
            )
        else:
            outcome = "pending"
        facts = OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0,
            candidate_count=1,
            selected_candidate_id="protected-artifact-scope",
            audit_recorded=True,
            deployment_decision=("empty_position" if outcome == "no_ticket" else "keep"),
            ticket_artifact_id=links[0].ticket_artifact_id,
            confirmation_state=("consumed" if placed_count == len(links) else None),
            placement_state=(
                "placed"
                if placed_count
                else "shadow" if terminal_count == len(links) else "unplaced"
            ),
            result_available=False,
            pending_review_items=0,
        )
        labels = {
            "pending": "受保护票据已拆分，逐票等待本人确认。",
            "placed": "本销售窗口的受保护票据均已确认出票。",
            "partially_placed": "本销售窗口仅有部分票据确认出票。",
            "no_ticket": "本销售窗口的剩余票据均已由本人明确关闭。",
            "expired": "本销售窗口未形成正式出票。",
        }
        summary = _summary(
            facts,
            title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ") + business_key,
        ).model_copy(
            update={
                "state": OperatorTaskState.COMPLETE,
                "is_actionable": False,
                "next_action_label": NEXT_ACTION_LABELS[OperatorTaskState.COMPLETE],
            }
        )
        return _BuiltTask(
            facts=facts,
            summary=summary,
            progress=TaskProgressSummary(
                completed=terminal_count,
                total=len(links),
                label="出票结果",
            ),
            step=CompleteStep(
                task_id=lineage.task_key,
                title="销售窗口出票结果",
                summary=labels[outcome],
            ),
            mutation_token=_token(
                {
                    "task_id": lineage.task_key,
                    "work_item_id": lineage.work_item_id,
                    "artifact_ids": [link.ticket_artifact_id for link in links],
                    "terminal_ids": [
                        None
                        if terminal is None
                        else terminal.artifact_terminal_receipt_id
                        for terminal in terminals
                    ],
                }
            ),
            work_item_identity=lineage.work_item_id,
            scope_kind=ScopeKind.SALE_WAVE,
            projected_state=OperatorTaskState.COMPLETE,
            deployment_outcome=outcome,
        )

    def _formal_artifact_stages(
        self,
        task_id: str,
        lane: OperatorLane,
        business_key: str,
        cutoff: datetime,
    ) -> tuple[_BuiltTask, ...]:
        if self._unit_of_work_factory is None or self._snapshot_tokens is None:
            return ()
        with self._decision_uow() as uow:
            links = uow.tickets.artifact_work_item_links_for_task_family(
                task_id,
                as_of=cutoff.isoformat(),
            )
            return tuple(
                self._formal_artifact_stage(
                    uow,
                    link,
                    lane,
                    business_key,
                    cutoff,
                )
                for link in links
            )

    @staticmethod
    def _artifact_link_lineage(link, *, work_item_id: str) -> _DecisionLineage:
        return _DecisionLineage(
            task_key=link.task_family_id,
            task_snapshot_hash=link.task_snapshot_hash,
            work_item_id=work_item_id,
            slate_revision_id=link.slate_revision_id,
            task_evidence_bundle_revision_id="artifact-projection",
            market_prior_baseline_revision_id="artifact-projection",
            baseline_envelope_revision_id=None,
            baseline_envelope_revision_no=0,
            required_match_ids=(),
        )

    @staticmethod
    def _artifact_current_offers(uow, artifact_id: str) -> tuple[object, ...]:
        current = []
        for link in uow.tickets.protected_artifact_offer_revision_links(artifact_id):
            source = uow.operator_sale.offer_revision(link.official_offer_revision_id)
            if source is None:
                raise ProductActionBlockedError(
                    "protected artifact offer revision is unavailable"
                )
            offer = uow.operator_sale.current_offer_by_family(
                source.official_offer_family_id
            )
            if offer is not None:
                current.append(offer)
        return tuple(current)

    def _formal_artifact_stage(
        self,
        uow,
        link,
        lane: OperatorLane,
        business_key: str,
        cutoff: datetime,
    ) -> _BuiltTask:
        artifact = uow.tickets.ticket_artifact(link.ticket_artifact_id)
        binding = uow.tickets.protected_artifact_binding(link.ticket_artifact_id)
        identity = f"{link.work_item_id}:artifact:{link.ticket_artifact_id}"
        if artifact is None or binding is None:
            facts = OperatorTaskFacts(
                lane=lane,
                business_key=business_key,
                deadline_at=None,
                waiting_until=None,
                source_error_code="protected_artifact_binding_missing",
                has_issue=True,
                has_prep=True,
                unresolved_adjudications=0,
                candidate_count=1,
                selected_candidate_id="protected-artifact",
                audit_recorded=True,
                deployment_decision="keep",
                ticket_artifact_id=link.ticket_artifact_id,
                confirmation_state=None,
                placement_state=None,
                result_available=False,
                pending_review_items=0,
            )
            return _BuiltTask(
                facts=facts,
                summary=_summary(
                    facts,
                    title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                    + business_key,
                    block_reason_code="protected_artifact_binding_missing",
                ),
                progress=TaskProgressSummary(completed=0, total=1, label="票据完整性"),
                step=BlockedStep(
                    task_id=link.task_family_id,
                    title="受保护票据绑定缺失",
                    recovery=OperatorRecoverySummary(
                        code="protected_artifact_binding_missing",
                        missing="受保护票据的正式决策绑定",
                        impact="不能发起本人确认",
                        action_label="运行完整性审计",
                    ),
                ),
                mutation_token=_token({"artifact": link.ticket_artifact_id}),
                work_item_identity=identity,
                scope_kind=ScopeKind.ARTIFACT,
                projected_state=OperatorTaskState.BLOCKED,
                deployment_outcome="pending",
                scope_label="受保护票据",
            )

        terminal = self._visible_artifact_terminal(
            uow,
            link.ticket_artifact_id,
            cutoff,
        )
        if terminal is not None and terminal.terminal_kind == "placed":
            result = self._formal_result_stage(
                uow,
                self._artifact_link_lineage(link, work_item_id=link.work_item_id),
                lane,
                business_key,
                _aware(
                    datetime.fromisoformat(binding.frozen_deadline_at),
                    "artifact deadline",
                ),
                cutoff,
                artifact_link=link,
            )
            if result is None:
                raise ProductActionBlockedError("placed artifact has no result stage")
            placement = uow.tickets.placement_for_artifact(link.ticket_artifact_id)
            if placement is None:
                raise ProductActionBlockedError("placed artifact has no placement")
            return replace(
                result,
                work_item_identity=(
                    f"{link.work_item_id}:ticket:{placement.ticket_id}"
                ),
                scope_kind=ScopeKind.TICKET,
                deployment_outcome=None,
                scope_label=f"已出票票 {binding.ticket_index + 1}",
            )

        current_offers = self._artifact_current_offers(
            uow,
            link.ticket_artifact_id,
        )
        effective_cutoff = effective_artifact_cutoff(binding, current_offers)
        label = (
            f"票 {binding.ticket_index + 1} · "
            f"{binding.currency} {binding.stake_minor / 100:.2f}"
        )
        if terminal is not None:
            outcome = (
                "no_ticket"
                if terminal.terminal_reason == "human_no_ticket"
                else "expired"
            )
            facts = OperatorTaskFacts(
                lane=lane,
                business_key=business_key,
                deadline_at=effective_cutoff,
                waiting_until=None,
                source_error_code=None,
                has_issue=True,
                has_prep=True,
                unresolved_adjudications=0,
                candidate_count=1,
                selected_candidate_id="protected-artifact",
                audit_recorded=True,
                deployment_decision=(
                    "empty_position" if outcome == "no_ticket" else "keep"
                ),
                ticket_artifact_id=link.ticket_artifact_id,
                confirmation_state="expired",
                placement_state="shadow",
                result_available=False,
                pending_review_items=0,
            )
            return _BuiltTask(
                facts=facts,
                summary=_summary(
                    facts,
                    title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                    + business_key,
                ),
                progress=TaskProgressSummary(completed=1, total=1, label="出票结果"),
                step=CompleteStep(
                    task_id=link.task_family_id,
                    title="本票未出票",
                    summary=(
                        "已由你明确关闭本票。"
                        if outcome == "no_ticket"
                        else "截止前未完成本人确认，没有进入账本。"
                    ),
                ),
                mutation_token=_token(
                    {
                        "artifact": link.ticket_artifact_id,
                        "terminal": terminal.artifact_terminal_receipt_id,
                    }
                ),
                work_item_identity=identity,
                scope_kind=ScopeKind.ARTIFACT,
                projected_state=OperatorTaskState.COMPLETE,
                deployment_outcome=outcome,
                scope_label=label,
            )

        head = uow.tickets.confirmation_challenge_head(link.ticket_artifact_id)
        challenge = (
            None
            if head is None
            else uow.tickets.confirmation_challenge_revision(
                head.challenge_revision_id
            )
        )
        if head is not None and challenge is None:
            raise ProductActionBlockedError("confirmation challenge head is invalid")
        if challenge is not None:
            issued_at = _aware(
                datetime.fromisoformat(challenge.issued_at),
                "confirmation issued time",
            )
            if issued_at > cutoff:
                head = None
                challenge = None
            else:
                effective_cutoff = min(
                    effective_cutoff,
                    _aware(
                        datetime.fromisoformat(challenge.effective_cutoff_at),
                        "confirmation cutoff",
                    ),
                )
        confirmation_state = "open" if challenge is not None else "not_issued"
        source_error = (
            "confirmation_expired" if effective_cutoff <= cutoff else None
        )
        facts = OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=effective_cutoff,
            waiting_until=None,
            source_error_code=source_error,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0,
            candidate_count=1,
            selected_candidate_id="protected-artifact",
            audit_recorded=True,
            deployment_decision="keep",
            ticket_artifact_id=link.ticket_artifact_id,
            confirmation_state=(
                "expired" if source_error is not None else confirmation_state
            ),
            placement_state="unplaced",
            result_available=False,
            pending_review_items=0,
        )
        if source_error is not None:
            return _BuiltTask(
                facts=facts,
                summary=_summary(
                    facts,
                    title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                    + business_key,
                    block_reason_code=source_error,
                ),
                progress=TaskProgressSummary(completed=0, total=1, label="等待截止扫描"),
                step=BlockedStep(
                    task_id=link.task_family_id,
                    title="确认已到截止时刻",
                    recovery=OperatorRecoverySummary(
                        code=source_error,
                        missing="artifact shadow 截止回执",
                        impact="本票不能再发起或完成确认",
                        action_label="等待截止扫描完成",
                    ),
                ),
                mutation_token=_token(
                    {
                        "artifact": link.ticket_artifact_id,
                        "cutoff": effective_cutoff,
                    }
                ),
                work_item_identity=identity,
                scope_kind=ScopeKind.ARTIFACT,
                projected_state=OperatorTaskState.BLOCKED,
                deployment_outcome="pending",
                scope_label=label,
            )

        command_dependencies = [f"ticket_artifact:{link.ticket_artifact_id}"]
        if challenge is not None:
            command_dependencies.append(
                f"challenge_revision:{challenge.challenge_revision_id}"
            )
        artifact_lineage = self._artifact_link_lineage(
            link,
            work_item_id=identity,
        )
        command_token = (
            self._decision_command_token(
                artifact_lineage,
                OperatorCommandKind.REQUEST_CONFIRMATION,
                tuple(sorted(command_dependencies)),
            )
            if confirmation_state == "not_issued"
            else None
        )
        artifact_token = (
            self._decision_command_token(
                artifact_lineage,
                OperatorCommandKind.REQUEST_CONFIRMATION,
                (f"ticket_artifact:{link.ticket_artifact_id}",),
            )
            if confirmation_state == "not_issued"
            else None
        )
        return _BuiltTask(
            facts=facts,
            summary=_summary(
                facts,
                title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                + business_key,
            ),
            progress=TaskProgressSummary(
                completed=1 if confirmation_state == "open" else 0,
                total=2,
                label="本人确认",
            ),
            step=ConfirmationStep(
                surface_version="2",
                task_id=link.task_family_id,
                amount_minor=binding.stake_minor,
                currency=binding.currency,
                deadline_at=effective_cutoff,
                confirmation_state=confirmation_state,
                confirmation_expires_at=(
                    effective_cutoff if confirmation_state == "open" else None
                ),
                command_token=command_token,
                ticket_artifact_token=artifact_token,
            ),
            mutation_token=command_token
            or _token(
                {
                    "artifact": link.ticket_artifact_id,
                    "challenge": challenge.challenge_revision_id,
                }
            ),
            work_item_identity=identity,
            scope_kind=ScopeKind.ARTIFACT,
            projected_state=OperatorTaskState.AWAIT_CONFIRMATION,
            deployment_outcome="pending",
            scope_label=label,
        )

    def _formal_result_stage(
        self,
        uow,
        lineage: _DecisionLineage,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        cutoff: datetime,
        *,
        artifact_link=None,
    ) -> _BuiltTask | None:
        links = (
            (artifact_link,)
            if artifact_link is not None
            else uow.tickets.artifact_work_item_links_for_work_item(
                lineage.work_item_id
            )
        )
        if not links:
            return None
        terminals = tuple(
            uow.tickets.artifact_terminal_receipt(link.ticket_artifact_id)
            for link in links
        )
        if any(terminal is None for terminal in terminals):
            return None
        terminal_kinds = {
            terminal.terminal_kind for terminal in terminals if terminal is not None
        }
        all_shadow = terminal_kinds == {"shadow"}
        if all_shadow:
            placed_ticket_ids = ()
        elif artifact_link is not None:
            placement = uow.tickets.placement_for_artifact(
                artifact_link.ticket_artifact_id
            )
            placed_ticket_ids = () if placement is None else (placement.ticket_id,)
        else:
            placed_ticket_ids = uow.operator_result.placed_ticket_ids_for_work_item(
                lineage.work_item_id
            )
        result_set = (
            None
            if all_shadow
            else uow.operator_result.current_result_set(
                lane=lane.value,
                business_key=business_key,
            )
        )
        matches: list[ResultMatchSummary] = []
        result_state = "not_imported"
        prize_state = "not_applicable" if lane is OperatorLane.JCZQ else "missing"
        prize_published_at = None
        prize_tiers: list[ResultPrizeTierSummary] = []
        settlement = _SettlementProjection(
            state="not_applicable" if all_shadow else "result_waiting",
            placed_ticket_count=len(placed_ticket_ids),
            blocking_codes=() if all_shadow else ("result_not_ready",),
        )
        if result_set is not None:
            result_rows = uow.operator_result.result_matches_for_set(
                result_set.result_set_revision_id
            )
            source_rows = uow.operator_result.result_source_receipts_for_set(
                result_set.result_set_revision_id
            )
            outcomes_by_match = {
                outcome.match_id: outcome
                for outcome in uow.operator_result.outcomes_for_result_set(
                    result_set.result_set_revision_id
                )
            }
            sources_by_match: dict[str, list[object]] = {}
            for source in source_rows:
                sources_by_match.setdefault(source.match_result_revision_id, []).append(
                    source
                )
            for row in result_rows:
                match = self._repository.match(row.match_id, cutoff.isoformat())
                match_label = self._match_label(match, row.official_match_no)
                source_views = [
                    ResultSourceSummary(
                        source_label=_RESULT_SOURCE_LABELS[source.source_kind],
                        state=source.receipt_state,
                        result_label=self._result_source_label(source),
                        captured_at=(
                            None
                            if source.captured_at is None
                            else _aware(
                                datetime.fromisoformat(source.captured_at),
                                "result source capture",
                            )
                        ),
                        source_kind=source.source_kind,
                        source_disposition=source.source_disposition,
                        home_90=source.home_90,
                        away_90=source.away_90,
                        invalid_code=source.invalid_code,
                    )
                    for source in sorted(
                        sources_by_match.get(row.match_result_revision_id, []),
                        key=lambda item: item.source_index,
                    )
                ]
                outcome = outcomes_by_match.get(row.match_id)
                matches.append(
                    ResultMatchSummary(
                        official_match_no=row.official_match_no,
                        match_label=match_label,
                        agreement_state=row.agreement_state,
                        result_disposition=row.normalized_disposition,
                        home_90=row.normalized_home_90,
                        away_90=row.normalized_away_90,
                        sources=source_views,
                        outcome_state=(
                            "waiting"
                            if outcome is None
                            else "corrected"
                            if outcome.revision_no > 1
                            else "committed"
                        ),
                    )
                )
            if any(match.agreement_state == "conflict" for match in matches):
                result_state = "conflict"
            elif any(match.agreement_state == "missing" for match in matches):
                result_state = "missing"
            elif any(match.result_disposition == "postponed" for match in matches):
                result_state = "postponed"
            elif len(matches) == result_set.match_count:
                result_state = (
                    "corrected" if getattr(result_set, "revision_no", 1) > 1 else "ready"
                )
            if lane is OperatorLane.ZUCAI:
                prize_id = result_set.zucai_prize_table_revision_id
                prize = (
                    None
                    if prize_id is None
                    else uow.operator_result.prize_table_revision(prize_id)
                )
                if prize is not None:
                    prize_state = "ready"
                    prize_published_at = _aware(
                        datetime.fromisoformat(prize.published_at),
                        "prize publication",
                    )
                    prize_tiers = [
                        ResultPrizeTierSummary(
                            tier_label=_PRIZE_TIER_LABELS[tier.tier_code],
                            tier_code=tier.tier_code,
                            ticket_kind=tier.ticket_kind,
                            required_correct_count=tier.required_correct_count,
                            official_winning_note_count=(tier.official_winning_note_count),
                            payout_minor_per_winning_note=(
                                tier.payout_minor_per_winning_note
                            ),
                        )
                        for tier in uow.operator_result.prize_table_tiers(
                            prize.prize_table_revision_id
                        )
                    ]
            if result_state in {"ready", "corrected"} and prize_state in {
                "not_applicable",
                "ready",
            }:
                context = self._settlement_context_for_result(
                    lineage,
                    result_set,
                    lane=lane,
                )
                settlement = _SettlementProjection(
                    state="not_requested",
                    command_token=context.command_token,
                    placed_ticket_count=len(placed_ticket_ids),
                )
            elif result_state in {"ready", "corrected"} and prize_state == "missing":
                settlement = _SettlementProjection(
                    state="prize_waiting",
                    placed_ticket_count=len(placed_ticket_ids),
                    blocking_codes=("prize_not_ready",),
                )
            else:
                settlement = _SettlementProjection(
                    state="result_waiting",
                    placed_ticket_count=len(placed_ticket_ids),
                    blocking_codes=("result_not_ready",),
                )
            settlement = self._persisted_settlement_projection(
                uow,
                result_set,
                result_rows=result_rows,
                cutoff=cutoff,
                fallback=settlement,
            )
        facts = OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
            has_prep=True,
            unresolved_adjudications=0,
            candidate_count=1,
            selected_candidate_id="terminal-ticket-scope",
            audit_recorded=True,
            deployment_decision="keep",
            ticket_artifact_id=links[0].ticket_artifact_id,
            confirmation_state="consumed",
            placement_state="shadow" if all_shadow else "placed",
            result_available=False,
            pending_review_items=0,
        )
        step = AwaitResultStep(
            surface_version="2",
            task_id=lineage.task_key,
            title="赛果与结算",
            expected_at=deadline,
            result_state=result_state,
            result_matches=matches,
            prize_state=prize_state,
            prize_published_at=prize_published_at,
            prize_tiers=prize_tiers,
            settlement_state=settlement.state,
            settlement_command_token=settlement.command_token,
            result_cutoff_at=(
                None
                if result_set is None
                else _aware(
                    datetime.fromisoformat(result_set.result_cutoff_at),
                    "result cutoff",
                )
            ),
            settlement_ready=settlement.command_token is not None,
            request_state=settlement.request_state,
            placed_ticket_count=settlement.placed_ticket_count,
            settled_ticket_count=settlement.settled_ticket_count,
            blocking_codes=list(settlement.blocking_codes),
            last_run=settlement.last_run,
            currency=settlement.currency,
            total_stake_minor=settlement.total_stake_minor,
            total_payout_minor=settlement.total_payout_minor,
            tickets=list(settlement.tickets),
        )
        completed = sum(match.agreement_state == "agreed" for match in matches)
        total = 0 if result_set is None else result_set.match_count
        return _BuiltTask(
            facts=facts,
            summary=_summary(
                facts,
                title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ")
                + business_key,
            ),
            progress=TaskProgressSummary(
                completed=completed,
                total=total,
                label="赛果与结算",
            ),
            step=step,
            mutation_token=_token(
                {
                    "task_id": lineage.task_key,
                    "work_item_id": lineage.work_item_id,
                    "terminal_kinds": sorted(terminal_kinds),
                    "result_set_revision_id": (
                        None
                        if result_set is None
                        else result_set.result_set_revision_id
                    ),
                }
            ),
            work_item_identity=lineage.work_item_id,
            scope_kind=(ScopeKind.ARTIFACT if all_shadow else ScopeKind.TICKET),
            projected_state=OperatorTaskState.AWAIT_RESULT,
        )

    def _persisted_settlement_projection(
        self,
        uow,
        result_set,
        *,
        result_rows,
        cutoff: datetime,
        fallback: _SettlementProjection,
    ) -> _SettlementProjection:
        request = uow.operator_result.settlement_request_for_result(
            result_set.result_set_revision_id
        )
        if request is None:
            return fallback
        run = uow.operator_result.task_settlement_run_for_request(
            request.settlement_request_id
        )
        if run is None:
            job = uow.operator_decision.worker_job_for_source(
                job_kind="task_settlement",
                source_object_type="operator_settlement_request",
                source_object_id=request.settlement_request_id,
            )
            return _SettlementProjection(
                state=(
                    "integrity_blocked"
                    if job is not None and job.state == "failed"
                    else "queued"
                ),
                request_state=(
                    "rejected"
                    if job is not None and job.state == "failed"
                    else "queued"
                ),
                placed_ticket_count=fallback.placed_ticket_count,
                blocking_codes=(
                    ("placement_integrity_blocked",)
                    if job is not None and job.state == "failed"
                    else ()
                ),
            )
        placed_ticket_ids = uow.operator_result.placed_ticket_ids_for_work_item(
            result_set.work_item_id
        )
        skips = uow.operator_result.task_settlement_skips(run.settlement_run_id)
        ticket_labels = {
            ticket_id: f"第 {index} 票"
            for index, ticket_id in enumerate(placed_ticket_ids, start=1)
        }
        last_run = TaskSettlementRunSummary(
            requested_ticket_count=run.requested_ticket_count,
            eligible_ticket_count=run.eligible_ticket_count,
            settled_ticket_count=run.settled_ticket_count,
            skipped_ticket_count=run.skipped_ticket_count,
            persisted_settlement_count=run.persisted_settlement_count,
            skips=[
                TaskSettlementSkipSummary(
                    ticket_label=ticket_labels.get(skip.ticket_id, "未知票据"),
                    reason_code=skip.reason_code,
                )
                for skip in skips
            ],
        )
        blocking_codes = tuple(sorted({skip.reason_code for skip in skips}))
        if run.settlement_state == "not_applicable":
            return _SettlementProjection(
                state="not_applicable",
                request_state="completed",
                placed_ticket_count=0,
                settled_ticket_count=0,
                blocking_codes=blocking_codes,
                last_run=last_run,
            )

        ticket_views = self._settlement_ticket_views(
            uow,
            run,
            result_rows=result_rows,
            cutoff=cutoff,
        )
        if not ticket_views:
            reasons = set(blocking_codes)
            if "placement_integrity_blocked" in reasons:
                state = "integrity_blocked"
            elif "prize_not_ready" in reasons:
                state = "prize_waiting"
            elif "result_not_ready" in reasons:
                state = "result_waiting"
            else:
                raise ProductActionBlockedError(
                    "completed settlement run has no displayable ticket outcome"
                )
            return _SettlementProjection(
                state=state,
                request_state="completed",
                placed_ticket_count=len(placed_ticket_ids),
                settled_ticket_count=run.settled_ticket_count,
                blocking_codes=blocking_codes,
                last_run=last_run,
            )
        currencies = {ticket.currency for ticket in ticket_views}
        if len(currencies) != 1:
            raise ProductActionBlockedError("settlement ticket currencies conflict")
        return _SettlementProjection(
            state=run.settlement_state,
            request_state="completed",
            placed_ticket_count=len(placed_ticket_ids),
            settled_ticket_count=run.settled_ticket_count,
            blocking_codes=blocking_codes,
            last_run=last_run,
            currency=currencies.pop(),
            total_stake_minor=sum(ticket.stake_minor for ticket in ticket_views),
            total_payout_minor=sum(ticket.payout_minor for ticket in ticket_views),
            tickets=ticket_views,
        )

    def _settlement_ticket_views(
        self,
        uow,
        run,
        *,
        result_rows,
        cutoff: datetime,
    ) -> tuple[SettlementTicketSummary, ...]:
        result_by_match = {row.match_id: row for row in result_rows}
        views = []
        for ticket_number, revision_id in enumerate(
            run.ticket_settlement_revision_ids,
            start=1,
        ):
            revision = uow.operator_result.ticket_settlement_revision(revision_id)
            if revision is None:
                raise ProductActionBlockedError("settlement ticket row is unavailable")
            ticket = uow.finance.ticket(revision.ticket_id)
            if ticket is None or ticket.ticket_kind is None:
                raise ProductActionBlockedError("settlement ticket identity is unavailable")
            notes_by_id = {
                note.ticket_note_id: note
                for note in uow.operator_result.ticket_notes(revision.ticket_id)
            }
            leg_results = {
                row.ticket_note_leg_id: row
                for row in uow.operator_result.ticket_note_leg_settlements(
                    revision.settlement_revision_id
                )
            }
            note_views = []
            for note_result in uow.operator_result.ticket_note_settlements(
                revision.settlement_revision_id
            ):
                note = notes_by_id.get(note_result.ticket_note_id)
                if note is None:
                    raise ProductActionBlockedError("settlement note binding is unavailable")
                leg_views = []
                for leg in uow.operator_result.ticket_note_legs(note.ticket_note_id):
                    grade = leg_results.get(leg.ticket_note_leg_id)
                    result = result_by_match.get(leg.match_id)
                    match = self._repository.match(leg.match_id, cutoff.isoformat())
                    if grade is None or result is None:
                        raise ProductActionBlockedError(
                            "settlement leg binding is unavailable"
                        )
                    market_code = (
                        uow.market.market_kind(leg.market_definition_id)
                        or leg.market_definition_id
                    )
                    leg_views.append(
                        SettlementLegSummary(
                            match_label=self._match_label(
                                match,
                                result.official_match_no,
                            ),
                            market_label=_MARKET_LABELS.get(
                                market_code,
                                market_code,
                            ),
                            selection_label=_face_label(
                                leg.selection_code,
                                market_code,
                            ),
                            result_label=self._settlement_result_label(
                                grade.market_result_code,
                                grade.result_disposition,
                                market_code,
                            ),
                            grade=grade.leg_grade,
                            leg_index=leg.leg_index,
                            official_match_no=result.official_match_no,
                            market_code=market_code,
                            selection_code=leg.selection_code,
                            result_disposition=grade.result_disposition,
                            market_result_code=grade.market_result_code,
                            leg_grade=grade.leg_grade,
                            booked_decimal_odds=leg.booked_decimal_odds,
                            settlement_parameter_decimal=(
                                leg.settlement_parameter_decimal
                            ),
                        )
                    )
                note_views.append(
                    SettlementNoteSummary(
                        note_number=note.note_index + 1,
                        structure_label=self._settlement_structure_label(note),
                        grade=note_result.note_grade,
                        unit_count=note_result.unit_count,
                        correct_leg_count=note_result.correct_leg_count,
                        void_leg_count=note_result.void_leg_count,
                        prize_label=(
                            None
                            if note_result.prize_tier_code is None
                            else _PRIZE_TIER_LABELS[note_result.prize_tier_code]
                        ),
                        payout_minor=note_result.payout_minor,
                        legs=leg_views,
                        note_index=note.note_index,
                        group_label=self._settlement_group_label(
                            note.ticket_kind,
                            note.group_code,
                        ),
                        note_grade=note_result.note_grade,
                        winning_unit_count=note_result.winning_unit_count,
                        void_unit_count=note_result.void_unit_count,
                        stake_minor=note.stake_minor,
                        prize_tier_code=note_result.prize_tier_code,
                    )
                )
            ticket_kind_label = self._settlement_ticket_label(
                ticket.ticket_kind,
                note_views,
            )
            views.append(
                SettlementTicketSummary(
                    ticket_number=ticket_number,
                    ticket_kind_label=ticket_kind_label,
                    settlement_state=revision.settlement_state,
                    currency=revision.currency,
                    stake_minor=revision.stake_minor,
                    paid_note_unit_count=revision.paid_note_unit_count,
                    winning_note_unit_count=revision.winning_note_unit_count,
                    void_note_unit_count=revision.void_note_unit_count,
                    payout_minor=revision.gross_payout_minor,
                    notes=note_views,
                    ticket_label=f"第 {ticket_number} 票 · {ticket_kind_label}",
                    revision_no=revision.revision_no,
                    corrected=revision.settlement_state == "corrected",
                    settlement_method_label=self._settlement_method_label(
                        revision.method_version
                    ),
                    rounding_policy_label=self._rounding_policy_label(
                        revision.rounding_policy_version
                    ),
                    distinct_note_count=revision.distinct_note_count,
                    cash_entries=[
                        SettlementCashEntrySummary(
                            transaction_kind=cash.transaction_kind,
                            amount_minor=cash.amount_minor,
                            currency=cash.currency,
                            replaces_prior_payout=(
                                cash.reverses_transaction_id is not None
                            ),
                        )
                        for cash in uow.operator_result.settlement_cash_links(
                            revision.settlement_revision_id
                        )
                    ],
                )
            )
        return tuple(views)

    @staticmethod
    def _settlement_structure_label(note) -> str:
        if note.ticket_kind == "sfc":
            return "胜负彩 14 场"
        if note.ticket_kind == "renjiu":
            return "任九 9 场"
        value = note.structure_code.replace("x", " 串 ")
        return "单关" if value in {"1", "1 串 1"} else value

    @staticmethod
    def _settlement_ticket_label(
        ticket_kind: str,
        notes: list[SettlementNoteSummary],
    ) -> str:
        if ticket_kind == "sfc":
            return "胜负彩"
        if ticket_kind == "renjiu":
            return "任九"
        structure = notes[0].structure_label if notes else ""
        return f"竞彩 {structure}".strip()

    @staticmethod
    def _settlement_group_label(
        ticket_kind: str,
        group_code: str | None,
    ) -> str | None:
        if ticket_kind != "renjiu" or group_code is None:
            return None
        official_match_nos = group_code.split("-")
        if not all(re.fullmatch(r"\d+", number) for number in official_match_nos):
            raise ProductActionBlockedError("settlement group label is unavailable")
        return "场次 " + "、".join(official_match_nos)

    @staticmethod
    def _settlement_method_label(method_version: str) -> str:
        try:
            return _SETTLEMENT_METHOD_LABELS[method_version]
        except KeyError as error:
            raise ProductActionBlockedError(
                "settlement method version is unavailable"
            ) from error

    @staticmethod
    def _rounding_policy_label(rounding_policy_version: str | None) -> str:
        try:
            return _ROUNDING_POLICY_LABELS[rounding_policy_version]
        except KeyError as error:
            raise ProductActionBlockedError(
                "settlement rounding policy is unavailable"
            ) from error

    @staticmethod
    def _settlement_result_label(
        result_code: str,
        disposition: str,
        market_code: str,
    ) -> str:
        if disposition == "official_void":
            return "官方无效场"
        face = {"home": "3", "draw": "1", "away": "0"}.get(
            result_code,
            result_code,
        )
        return _face_label(face, market_code)

    @staticmethod
    def _result_source_label(source) -> str | None:
        if source.receipt_state != "available":
            return None
        if source.source_disposition == "played_90":
            return f"{source.home_90} - {source.away_90}"
        if source.source_disposition == "postponed":
            return "比赛延期"
        if source.source_disposition == "official_void":
            return "官方无效场"
        raise ProductActionBlockedError("result source disposition is invalid")

    def _settlement_context_for_result(
        self,
        lineage: _DecisionLineage,
        result_set,
        *,
        lane: OperatorLane,
    ) -> SettlementRequestCommandContext:
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator settlement tokens are not configured")
        if (
            result_set.task_family_id != lineage.task_key
            or result_set.work_item_id != lineage.work_item_id
            or result_set.task_snapshot_hash != lineage.task_snapshot_hash
            or result_set.slate_revision_id != lineage.slate_revision_id
            or result_set.lane != lane.value
            or result_set.outcome_count != result_set.match_count
        ):
            raise ProductActionBlockedError("result evidence does not match the current task")
        prize_id = result_set.zucai_prize_table_revision_id
        if (lane is OperatorLane.ZUCAI and prize_id is None) or (
            lane is OperatorLane.JCZQ and prize_id is not None
        ):
            raise ProductActionBlockedError("result prize binding is not ready")
        dependencies = tuple(
            sorted(
                (
                    f"result_set_revision:{result_set.result_set_revision_id}",
                    f"slate_revision:{lineage.slate_revision_id}",
                )
            )
        )
        payload = OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            command_kind=OperatorCommandKind.REQUEST_SETTLEMENT,
            dependency_revision_ids=list(dependencies),
        )
        return SettlementRequestCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=dependencies,
            slate_revision_id=lineage.slate_revision_id,
            result_set_revision_id=result_set.result_set_revision_id,
            prize_table_revision_id=prize_id,
            command_token=self._snapshot_tokens.encode(payload),
        )

    def _deployment_step(
        self,
        uow,
        lineage: _DecisionLineage,
        prescription: dict[str, object],
        candidate_set,
        selection,
        dependencies: tuple[str, ...],
        *,
        as_of: datetime,
    ) -> tuple[AuditDeploymentStep, tuple[str, ...]]:
        candidate = uow.operator_result.candidate(selection.candidate_revision_id)
        if candidate is None:
            raise ProductActionBlockedError("selected ticket candidate is missing")
        metric = uow.operator_result.candidate_metric(candidate.candidate_revision_id)
        if metric is None:
            raise ProductActionBlockedError("selected ticket candidate metric is missing")
        findings = uow.operator_result.candidate_audit_findings(
            candidate.candidate_revision_id
        )
        if self._operator_candidate_auditor is not None:
            if self._operator_decisions is None:
                raise ProductActionBlockedError(
                    "current candidate audit authority is not configured"
                )
            resolved_selection = self._operator_decisions.resolve_current_selection_in_uow(
                uow,
                candidate_selection_id=selection.candidate_selection_id,
            )
            current_audit = self._operator_candidate_auditor(uow, resolved_selection)
            findings = current_audit.findings
        lineage_row = uow.connection.execute(
            select(sod.operator_ticket_decision_lineage_revisions)
            .where(
                sod.operator_ticket_decision_lineage_revisions.c.candidate_selection_id
                == selection.candidate_selection_id
            )
            .order_by(
                sod.operator_ticket_decision_lineage_revisions.c.revision_no.desc()
            )
            .limit(1)
        ).mappings().first()
        batch = None
        artifacts = []
        if lineage_row is not None:
            source_batch = uow.tickets.batch_revision(
                str(lineage_row["ticket_batch_revision_id"])
            )
            if source_batch is None:
                raise ProductActionBlockedError("ticket decision lineage has no batch")
            batch = uow.tickets.current_batch_revision(source_batch.ticket_batch_id)
            if batch is None:
                raise ProductActionBlockedError("ticket decision lineage batch is unavailable")
            artifacts = uow.tickets.ticket_artifacts_for_revision(
                str(lineage_row["ticket_batch_revision_id"])
            )
            if not artifacts:
                artifacts = uow.tickets.ticket_artifacts_for_revision(
                    batch.ticket_batch_revision_id
                )

        stage_dependencies = set(dependencies)
        if batch is not None:
            stage_dependencies.add(f"ticket_batch_revision:{batch.ticket_batch_revision_id}")
        if artifacts:
            stage_dependencies.update(
                f"ticket_artifact:{artifact.ticket_artifact_id}"
                for artifact in artifacts
            )
        resolved_error_ids: set[str] = set()
        if lineage_row is not None and batch is not None:
            batch_revision_id = str(lineage_row["ticket_batch_revision_id"])
            direct_links = (
                uow.operator_result.candidate_generation_override_links_for_batch(
                    batch_revision_id
                )
            )
            generation_is_current = not direct_links or any(
                link.generation_request_id == candidate_set.generation_request_id
                for link in direct_links
            )
            inherited_links = (
                uow.operator_result.candidate_generation_override_links(
                    candidate_set.generation_request_id
                )
                if generation_is_current
                else ()
            )
            if inherited_links:
                receipts = tuple(
                    uow.operator_result.ticket_audit_override_receipt(
                        link.override_receipt_id
                    )
                    for link in inherited_links
                )
                if all(receipt is not None for receipt in receipts):
                    errors = tuple(
                        finding for finding in findings if finding.severity == "ERROR"
                    )
                    try:
                        matching = (
                            ProtectedTicketActions._match_inherited_operator_overrides(
                                uow,
                                errors=errors,
                                receipts=tuple(
                                    receipt
                                    for receipt in receipts
                                    if receipt is not None
                                ),
                                candidate_content_hash=candidate.content_hash,
                                audit_policy_version=(
                                    candidate_set.audit_policy_version
                                ),
                            )
                        )
                    except ValueError:
                        matching = {}
                    resolved_error_ids = set(matching)
            elif generation_is_current:
                matching = {
                    receipt.candidate_audit_finding_id
                    for receipt in (
                        uow.operator_result.ticket_audit_override_receipts_for_batch(
                            batch_revision_id
                        )
                    )
                    if receipt.candidate_revision_id
                    == candidate.candidate_revision_id
                    and receipt.candidate_content_hash == candidate.content_hash
                    and receipt.audit_policy_version
                    == candidate_set.audit_policy_version
                }
                current_error_ids = {
                    finding.candidate_audit_finding_id
                    for finding in findings
                    if finding.severity == "ERROR"
                }
                if matching == current_error_ids:
                    resolved_error_ids = matching
        unresolved_errors = [
            finding
            for finding in findings
            if finding.severity == "ERROR"
            and finding.candidate_audit_finding_id not in resolved_error_ids
        ]
        unresolved_warns = []
        for finding in findings:
            if finding.severity != "WARN":
                continue
            adjudication = uow.workflow.latest_adjudication(
                "ticket_audit_finding",
                finding.candidate_audit_finding_id,
            )
            if adjudication is None or adjudication.decision != "accept_warning":
                unresolved_warns.append(finding)

        no_ticket_context = (
            None
            if self._operator_decisions is None
            else self._operator_decisions.no_ticket_decision_context(
                task_family_id=lineage.task_key,
                lane=lineage.task_key.partition(":")[0],
                business_key=lineage.task_key.partition(":")[2],
                work_item_id=lineage.work_item_id,
                as_of=as_of,
            )
        )
        current_no_ticket = (
            None
            if no_ticket_context is None
            or no_ticket_context.current_no_ticket_revision_id is None
            else uow.operator_result.no_ticket_revision(
                no_ticket_context.current_no_ticket_revision_id
            )
        )
        if (
            no_ticket_context is not None
            and no_ticket_context.current_no_ticket_revision_id is not None
            and current_no_ticket is None
        ):
            raise ProductActionBlockedError("current no-ticket revision is unavailable")
        if (
            current_no_ticket is not None
            and current_no_ticket.deployment_outcome != "reopened"
        ):
            mode = "supersede_no_ticket"
            command_kind = OperatorCommandKind.SUPERSEDE_NO_TICKET
        elif batch is None:
            mode = "create_ticket_batch"
            command_kind = OperatorCommandKind.CREATE_TICKET_BATCH
        elif unresolved_errors:
            mode = "blocked"
            command_kind = None
        elif unresolved_warns:
            mode = "adjudicate_audit_warn"
            command_kind = OperatorCommandKind.ADJUDICATE_AUDIT_WARN
        elif artifacts:
            mode = "request_confirmation"
            command_kind = OperatorCommandKind.REQUEST_CONFIRMATION
        else:
            mode = "approve_ticket_batch"
            command_kind = OperatorCommandKind.APPROVE_TICKET_BATCH

        stage_dependencies_tuple = tuple(sorted(stage_dependencies))
        no_ticket_dependencies = (
            stage_dependencies_tuple
            if no_ticket_context is None
            else tuple(
                sorted(
                    (
                        f"business_key:{no_ticket_context.business_key}",
                        f"lane:{no_ticket_context.lane}",
                        f"scope_fingerprint:{no_ticket_context.scope_fingerprint}",
                        f"slate_revision:{no_ticket_context.slate_revision_id}",
                        f"task_family:{no_ticket_context.task_family_id}",
                    )
                )
            )
        )
        command_token = (
            None
            if command_kind is None
            else self._decision_command_token(
                lineage,
                command_kind,
                (
                    no_ticket_dependencies
                    if command_kind is OperatorCommandKind.SUPERSEDE_NO_TICKET
                    else stage_dependencies_tuple
                ),
            )
        )
        selection_token = (
            self._decision_command_token(
                lineage,
                OperatorCommandKind.CREATE_TICKET_BATCH,
                (f"selection:{selection.candidate_selection_id}",),
            )
            if mode == "create_ticket_batch"
            else None
        )
        batch_token = (
            self._decision_command_token(
                lineage,
                command_kind or OperatorCommandKind.APPROVE_TICKET_BATCH,
                (f"ticket_batch_revision:{batch.ticket_batch_revision_id}",),
            )
            if batch is not None and mode in {
                "adjudicate_audit_warn",
                "approve_ticket_batch",
            }
            else None
        )
        artifact_token = (
            self._decision_command_token(
                lineage,
                OperatorCommandKind.REQUEST_CONFIRMATION,
                (f"ticket_artifact:{artifacts[0].ticket_artifact_id}",),
            )
            if mode == "request_confirmation" and len(artifacts) == 1
            else None
        )
        if mode == "request_confirmation" and len(artifacts) != 1:
            raise ProductActionBlockedError(
                "confirmation currently requires one protected ticket artifact"
            )
        audit_override_ticket_batch_token = (
            self._operator_decisions.issue_ticket_batch_audit_token(
                batch.ticket_batch_revision_id
            )
            if mode == "blocked"
            and unresolved_errors
            and batch is not None
            and self._operator_decisions is not None
            else None
        )
        visible_findings = unresolved_errors or unresolved_warns or list(findings)
        finding_views = [
            DeploymentAuditFindingSummary(
                severity=finding.severity.lower(),
                label=f"{finding.finding_code} · {finding.audit_kind}",
                value=finding.message,
                finding_token=(
                    self._decision_command_token(
                        lineage,
                        OperatorCommandKind.ADJUDICATE_AUDIT_WARN,
                        (f"finding:{finding.candidate_audit_finding_id}",),
                    )
                    if finding in unresolved_warns
                    else None
                ),
            )
            for finding in visible_findings
        ]
        return (
            AuditDeploymentStep(
                surface_version="2",
                task_id=lineage.task_key,
                candidate=DeploymentCandidateSummary(
                    label=candidate.candidate_code,
                    ticket_count=metric.ticket_count,
                    stake_minor=metric.stake_minor,
                    objective_label=(
                        "P(全对)"
                        if metric.probability_kind == "all_required_legs"
                        else "P(至少一票全对)"
                    ),
                    objective_probability_decimal=(
                        metric.objective_probability_decimal
                    ),
                ),
                audit_state=(
                    "error"
                    if unresolved_errors
                    else "warn" if unresolved_warns else "pass"
                ),
                findings=finding_views,
                mode=mode,
                command_token=command_token,
                candidate_selection_token=selection_token,
                ticket_batch_token=batch_token,
                audit_override_ticket_batch_token=(
                    audit_override_ticket_batch_token
                ),
                ticket_artifact_token=artifact_token,
                no_ticket_command_token=self._decision_command_token(
                    lineage,
                    OperatorCommandKind.RECORD_NO_TICKET,
                    no_ticket_dependencies,
                ),
                no_ticket_revision_token=(
                    self._decision_command_token(
                        lineage,
                        OperatorCommandKind.SUPERSEDE_NO_TICKET,
                        (
                            "no_ticket_revision:"
                            f"{no_ticket_context.current_no_ticket_revision_id}",
                        ),
                    )
                    if mode == "supersede_no_ticket" and no_ticket_context is not None
                    else None
                ),
                comparison_candidate_token=self._decision_command_token(
                    lineage,
                    OperatorCommandKind.RECORD_NO_TICKET,
                    (f"candidate:{candidate.candidate_revision_id}",),
                ),
                rule_options=[
                    DeploymentRuleOption(
                        label=rule_id,
                        token=self._decision_command_token(
                            lineage,
                            OperatorCommandKind.RECORD_NO_TICKET,
                            (f"rule:{rule_id}",),
                        ),
                    )
                    for rule_id in sorted(DEVIATION_RULE_IDS)
                ],
            ),
            stage_dependencies_tuple,
        )

    def _candidate_comparison_step(
        self,
        uow,
        lineage: _DecisionLineage,
        prescription: dict[str, object],
        candidate_sets,
        dependencies: tuple[str, ...],
        *,
        selection,
    ) -> ConstructTicketStep:
        judgment_set = next(
            item for item in candidate_sets if item.set_kind == "judgment_bound"
        )
        selection_refs = (
            ()
            if selection is not None
            else self._candidate_selection_refs(
                uow,
                lineage,
                judgment_set,
                dependencies,
            )
        )
        candidate_tokens = {
            candidate_revision_id: token
            for token, _candidate_set_revision_id, candidate_revision_id in selection_refs
        }
        conditional_set = next(
            item
            for item in candidate_sets
            if item.set_kind == "conditional_market_counterfactual"
        )
        market_probability_by_signature = {}
        for candidate in uow.operator_result.candidates_for_set(
            conditional_set.candidate_set_revision_id
        ):
            _composition, signature, _faces = self._candidate_composition(
                uow,
                conditional_set,
                candidate,
            )
            metric = uow.operator_result.candidate_metric(
                candidate.candidate_revision_id
            )
            if metric is None:
                raise ProductActionBlockedError(
                    "candidate comparison metric is missing"
                )
            market_probability_by_signature[signature] = Decimal(
                metric.objective_probability_decimal
            )
        candidate_set_views = []
        for candidate_set in candidate_sets:
            candidates = [
                self._candidate_comparison_view(
                    uow,
                    prescription,
                    candidate_set,
                    candidate,
                    candidate_token=candidate_tokens.get(
                        candidate.candidate_revision_id
                    ),
                    market_probability_by_signature=(
                        market_probability_by_signature
                    ),
                    selection_completed=selection is not None,
                )
                for candidate in uow.operator_result.candidates_for_set(
                    candidate_set.candidate_set_revision_id
                )
            ]
            if not candidates:
                raise ProductActionBlockedError(
                    "candidate comparison set is empty"
                )
            candidate_set_views.append(
                CandidateSetComparisonView(
                    label=(
                        "判断处方候选"
                        if candidate_set.set_kind == "judgment_bound"
                        else "市场条件对照"
                    ),
                    comparison_only=bool(candidate_set.comparison_only),
                    candidates=candidates,
                )
            )
        selected_candidate_code = None
        if selection is not None:
            selected_candidate = uow.operator_result.candidate(
                selection.candidate_revision_id
            )
            if selected_candidate is None:
                raise ProductActionBlockedError(
                    "selected ticket candidate is missing"
                )
            selected_candidate_code = selected_candidate.candidate_code
        return ConstructTicketStep(
            task_id=lineage.task_key,
            mode="candidate_comparison",
            selection_command_token=(
                None
                if selection is not None
                else self._decision_command_token(
                    lineage,
                    OperatorCommandKind.SELECT_CANDIDATE,
                    dependencies,
                )
            ),
            selection_completed=selection is not None,
            selected_candidate_code=selected_candidate_code,
            candidate_sets=candidate_set_views,
        )

    def _candidate_comparison_view(
        self,
        uow,
        prescription: dict[str, object],
        candidate_set,
        candidate,
        *,
        candidate_token: str | None,
        market_probability_by_signature: dict[tuple[object, ...], Decimal],
        selection_completed: bool,
    ) -> CandidateComparisonView:
        metric = uow.operator_result.candidate_metric(
            candidate.candidate_revision_id
        )
        if metric is None:
            raise ProductActionBlockedError("candidate comparison metric is missing")
        composition, signature, candidate_faces = self._candidate_composition(
            uow,
            candidate_set,
            candidate,
        )
        findings = uow.operator_result.candidate_audit_findings(
            candidate.candidate_revision_id
        )
        selectable = bool(
            not selection_completed
            and candidate_set.set_kind == "judgment_bound"
            and candidate.partition != "over_cap"
            and candidate_token is not None
        )
        market_difference = None
        market_probability = market_probability_by_signature.get(signature)
        if candidate_set.set_kind == "judgment_bound" and market_probability is not None:
            delta_pp = (
                Decimal(metric.objective_probability_decimal) - market_probability
            ) * 100
            normalized = delta_pp.quantize(
                _PROBABILITY_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
            if normalized == 0:
                normalized = Decimal(0)
            market_difference = f"相对市场先验 {normalized:+.12f} pp"
        return CandidateComparisonView(
            code=candidate.candidate_code,
            partition=candidate.partition,
            rank=candidate.rank,
            selectable=selectable,
            deployable=bool(candidate.deployable),
            candidate_token=candidate_token if selectable else None,
            composition=composition,
            ticket_count=metric.ticket_count,
            distinct_note_count=metric.distinct_note_count,
            paid_note_unit_count=metric.paid_note_unit_count,
            stake_minor=metric.stake_minor,
            capital_utilization_decimal=metric.capital_utilization_decimal,
            objective_label=(
                "P(全对)"
                if metric.probability_kind == "all_required_legs"
                else "P(至少一票全对)"
            ),
            objective_probability_decimal=(
                metric.objective_probability_decimal
            ),
            expected_broken_legs_decimal=(
                metric.expected_broken_legs_decimal
            ),
            break_even_bonus_minor=metric.break_even_bonus_minor,
            break_even_to_official_median_decimal=(
                metric.break_even_to_official_median_decimal
            ),
            common_dead_faces=[
                f"场 {item.official_match_no} · {item.face_code}"
                for item in uow.operator_result.candidate_dead_faces(
                    candidate.candidate_revision_id
                )
            ],
            prescription_differences=self._candidate_prescription_differences(
                uow,
                prescription,
                findings,
                candidate_faces,
            ),
            audit_findings=[
                CandidateAuditFindingView(
                    audit_kind=item.audit_kind,
                    finding_code=item.finding_code,
                    severity=item.severity,
                    message=item.message,
                    rule_id=item.rule_id,
                )
                for item in findings
            ],
            market_difference=market_difference,
        )

    def _candidate_composition(self, uow, candidate_set, candidate):
        tickets = uow.operator_result.candidate_tickets(
            candidate.candidate_revision_id
        )
        if not tickets:
            raise ProductActionBlockedError(
                "candidate comparison ticket composition is missing"
            )
        offers_by_id = {
            offer.official_offer_revision_id: offer
            for offer in uow.operator_sale.offer_revisions_for_slate(
                candidate_set.slate_revision_id
            )
        }
        envelope_numbers = tuple(
            str(value)
            for value in uow.connection.execute(
                select(
                    sod.operator_baseline_envelope_offer_constraints.c.
                    official_match_no
                )
                .where(
                    sod.operator_baseline_envelope_offer_constraints.c.
                    baseline_envelope_revision_id
                    == candidate_set.baseline_envelope_revision_id
                )
                .order_by(
                    sod.operator_baseline_envelope_offer_constraints.c.
                    constraint_index
                )
            ).scalars()
        )
        singles: list[str] = []
        doubles: list[str] = []
        full_covers: list[str] = []
        pass_groups: list[str] = []
        selected_numbers: set[str] = set()
        candidate_faces: dict[str, set[str]] = {}
        signature_tickets = []
        for ticket in tickets:
            grouped: dict[tuple[str, str], list[str]] = {}
            for leg in uow.operator_result.candidate_ticket_legs(
                ticket.candidate_ticket_id
            ):
                key = (
                    leg.official_offer_revision_id,
                    leg.market_definition_id,
                )
                grouped.setdefault(key, []).append(leg.selection_code)
            signature_legs = []
            group_numbers = []
            for (offer_id, market_id), raw_faces in grouped.items():
                offer = offers_by_id.get(offer_id)
                if offer is None:
                    raise ProductActionBlockedError(
                        "candidate comparison offer is missing"
                    )
                match_no = offer.official_match_no
                faces = tuple(sorted(set(raw_faces), key=_face_sort_key))
                selected_numbers.add(match_no)
                candidate_faces.setdefault(match_no, set()).update(faces)
                group_numbers.append(match_no)
                label = f"场 {match_no} · {''.join(faces)}"
                if len(faces) == 1:
                    singles.append(label)
                elif len(faces) == 2:
                    doubles.append(label)
                else:
                    full_covers.append(label)
                signature_legs.append((offer_id, market_id, faces))
            group_parts = [ticket.structure_code]
            if ticket.group_code:
                group_parts.append(ticket.group_code)
            group_parts.append(" / ".join(f"场 {number}" for number in group_numbers))
            pass_groups.append(" · ".join(group_parts))
            signature_tickets.append(
                (
                    ticket.ticket_kind,
                    ticket.structure_code,
                    ticket.group_code,
                    tuple(signature_legs),
                )
            )
        composition = CandidateCompositionView(
            singles=list(dict.fromkeys(singles)),
            doubles=list(dict.fromkeys(doubles)),
            full_covers=list(dict.fromkeys(full_covers)),
            omissions=[
                f"场 {number}"
                for number in envelope_numbers
                if number not in selected_numbers
            ],
            pass_groups=list(dict.fromkeys(pass_groups)),
        )
        signature = tuple(signature_tickets)
        return composition, signature, candidate_faces

    @staticmethod
    def _candidate_prescription_differences(
        uow,
        prescription: dict[str, object],
        findings,
        candidate_faces: dict[str, set[str]],
    ) -> list[PrescriptionDifferenceSummary]:
        difference_findings = [
            finding
            for finding in findings
            if finding.audit_kind == "prescription_difference"
            and finding.official_match_no is not None
        ]
        if not difference_findings:
            return []
        prescribed_faces: dict[str, set[str]] = {}
        prescription_items = uow.operator_decision.judgment_prescription_items(
            str(prescription["judgment_prescription_revision_id"])
        )
        for item in prescription_items:
            judgment = uow.operator_decision.operator_match_judgment_revision(
                item.operator_match_judgment_revision_id
            )
            if judgment is None:
                continue
            offer = next(
                (
                    current
                    for current in uow.operator_sale.offer_revisions_for_slate(
                        str(prescription["slate_revision_id"])
                    )
                    if current.match_id == judgment.match_id
                ),
                None,
            )
            if offer is None:
                continue
            rows = uow.connection.execute(
                select(sod.operator_match_judgment_bundle_faces.c.face_code)
                .select_from(
                    sod.operator_match_judgment_face_bundles.join(
                        sod.operator_match_judgment_bundle_faces
                    )
                )
                .where(
                    sod.operator_match_judgment_face_bundles.c.
                    operator_match_judgment_revision_id
                    == item.operator_match_judgment_revision_id
                )
                .order_by(
                    sod.operator_match_judgment_face_bundles.c.bundle_index,
                    sod.operator_match_judgment_bundle_faces.c.face_index,
                )
            ).scalars()
            prescribed_faces[offer.official_match_no] = set(map(str, rows))
        result = []
        for match_no in dict.fromkeys(
            str(finding.official_match_no) for finding in difference_findings
        ):
            rules = list(
                dict.fromkeys(
                    str(finding.rule_id)
                    for finding in difference_findings
                    if str(finding.official_match_no) == match_no
                    and finding.rule_id is not None
                )
            )
            result.append(
                PrescriptionDifferenceSummary(
                    match_no=int(match_no),
                    prescribed_faces="".join(
                        sorted(
                            prescribed_faces.get(match_no, set()),
                            key=_face_sort_key,
                        )
                    ),
                    candidate_faces="".join(
                        sorted(
                            candidate_faces.get(match_no, set()),
                            key=_face_sort_key,
                        )
                    ),
                    registered_rule_ids=rules,
                )
            )
        return result

    def _baseline_envelope_step(
        self,
        uow,
        lineage: _DecisionLineage,
        lane: OperatorLane,
        cutoff: datetime,
    ) -> JudgeMatchesStep:
        context = BaselineEnvelopeCommandContext(
            task_key=lineage.task_key,
            task_snapshot_hash=lineage.task_snapshot_hash,
            work_item_id=lineage.work_item_id,
            dependency_revision_ids=_decision_dependencies(lineage),
            task_evidence_bundle_revision_id=(lineage.task_evidence_bundle_revision_id),
            market_prior_baseline_revision_id=(lineage.market_prior_baseline_revision_id),
            expected_current_revision_no=lineage.baseline_envelope_revision_no,
        )
        return JudgeMatchesStep(
            task_id=lineage.task_key,
            item_key="baseline-envelope",
            title="限定本轮票面搜索范围",
            prompt="",
            options=[],
            mode="baseline_envelope",
            comparison_only=True,
            completed_match_count=0,
            required_match_count=len(lineage.required_match_ids),
            envelope=self._baseline_envelope_editor(
                uow,
                lineage,
                lane,
                cutoff,
            ),
            envelope_command_token=self._decision_command_token(
                lineage,
                OperatorCommandKind.RECORD_BASELINE_ENVELOPE,
                context.dependency_revision_ids,
            ),
        )

    def _baseline_envelope_editor(
        self,
        uow,
        lineage: _DecisionLineage,
        lane: OperatorLane,
        cutoff: datetime,
    ) -> BaselineEnvelopeEditorView:
        repository = self._repository.bound_to(uow.connection)
        offers_by_id = {
            offer.official_offer_revision_id: offer
            for offer in uow.operator_sale.offer_revisions_for_slate(lineage.slate_revision_id)
        }
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for row in uow.operator_decision.market_prior_baseline_probabilities(
            lineage.market_prior_baseline_revision_id
        ):
            key = (
                str(row["official_offer_revision_id"]),
                str(row["match_id"]),
                str(row["market_definition_id"]),
            )
            grouped.setdefault(key, []).append(str(row["face_code"]))
        editor_offers = []
        for (offer_id, match_id, market_id), faces in grouped.items():
            offer = offers_by_id.get(offer_id)
            if offer is None:
                raise ProductActionBlockedError(
                    "market baseline references an unavailable official offer"
                )
            market_code = uow.market.market_kind(market_id) or market_id
            match = repository.match(match_id, cutoff.isoformat())
            editor_offers.append(
                BaselineEnvelopeOfferView(
                    official_match_no=offer.official_match_no,
                    match_label=self._match_label(match, offer.official_match_no),
                    market_code=market_code,
                    market_label=_MARKET_LABELS.get(market_code, market_code),
                    face_bundles=_all_face_bundle_views(tuple(sorted(faces, key=_face_sort_key))),
                    omission_available=True,
                )
            )
        official_numbers = list(dict.fromkeys(item.official_match_no for item in editor_offers))
        if lane is OperatorLane.JCZQ:
            structures = [
                BaselineEnvelopeStructureView(
                    kind="jczq_pass",
                    structure_code=f"pass-{size}-1",
                    structure_label="单关" if size == 1 else f"{size} 串 1",
                    eligible_official_match_nos=official_numbers,
                    pass_size=size,
                    required_offer_count=size,
                    maximum_groups=1,
                )
                for size in range(1, min(len(official_numbers), 8) + 1)
            ]
            ticket_kinds = ["jczq_pass"]
        else:
            structures = [
                BaselineEnvelopeStructureView(
                    kind="zucai_group",
                    structure_code="sfc-14",
                    structure_label="胜负彩 14 场",
                    eligible_official_match_nos=official_numbers,
                    pass_size=None,
                    required_offer_count=14,
                    maximum_groups=1,
                ),
                BaselineEnvelopeStructureView(
                    kind="zucai_group",
                    structure_code="renjiu-9",
                    structure_label="任九 9 场",
                    eligible_official_match_nos=official_numbers,
                    pass_size=None,
                    required_offer_count=9,
                    maximum_groups=2,
                ),
            ]
            ticket_kinds = ["sfc", "renjiu"]
        return BaselineEnvelopeEditorView(
            lane=lane,
            ticket_kinds=ticket_kinds,
            currency="CNY",
            capital_cap_minor=20000,
            maximum_ticket_count=2,
            maximum_exhaustive_candidate_count=100,
            offers=editor_offers,
            structures=structures,
        )

    def _match_judgment_step(
        self,
        uow,
        lineage: _DecisionLineage,
        item,
        bundle,
        cutoff: datetime,
        *,
        completed: int,
        total: int,
    ) -> tuple[JudgeMatchesStep, tuple[str, ...]]:
        offer = next(
            (
                value
                for value in uow.operator_sale.offer_revisions_for_slate(lineage.slate_revision_id)
                if value.match_id == item.match_id
            ),
            None,
        )
        if offer is None:
            raise ProductActionBlockedError("judgment match has no current official offer")
        constraint_rows = tuple(
            uow.connection.execute(
                select(sod.operator_baseline_envelope_offer_constraints).where(
                    sod.operator_baseline_envelope_offer_constraints.c.baseline_envelope_revision_id
                    == lineage.baseline_envelope_revision_id,
                    sod.operator_baseline_envelope_offer_constraints.c.official_match_no
                    == offer.official_match_no,
                )
            ).mappings()
        )
        if len(constraint_rows) != 1:
            raise ProductActionBlockedError("judgment match requires one exact envelope market")
        market_code = str(constraint_rows[0]["market_code"])
        context = self._match_judgment_context_for_lineage(
            uow,
            lineage,
            offer.official_match_no,
            market_code,
        )
        editor = self._match_judgment_editor(
            uow,
            context,
            item,
            bundle,
            offer,
            cutoff,
        )
        return (
            JudgeMatchesStep(
                task_id=lineage.task_key,
                item_key=offer.official_match_no,
                title="逐场登记判断",
                prompt="",
                options=[],
                mode="match_judgment",
                comparison_only=True,
                completed_match_count=completed,
                required_match_count=total,
                editor=editor,
                judgment_command_token=self._decision_command_token(
                    lineage,
                    OperatorCommandKind.COMMIT_MATCH_JUDGMENT,
                    context.dependency_revision_ids,
                ),
            ),
            context.dependency_revision_ids,
        )

    def _match_judgment_editor(
        self,
        uow,
        context: MatchJudgmentCommandContext,
        item,
        bundle,
        offer,
        cutoff: datetime,
    ) -> MatchJudgmentEditorView:
        repository = self._repository.bound_to(uow.connection)
        match = repository.match(context.match_id, cutoff.isoformat())
        if match is None or match.get("scheduled_at") is None:
            raise ProductActionBlockedError("current judgment match identity is unavailable")
        frozen = uow.operator_decision.freeze_bundle_for_action(item.freeze_bundle_action_id)
        if frozen is None:
            raise ProductActionBlockedError("frozen judgment evidence is unavailable")
        evidence_token_by_ref = {
            evidence_ref: token
            for token, evidence_ref in context.evidence_refs_by_token
        }
        evidence_refs = set(evidence_token_by_ref)
        evidence = [
            BusinessEvidenceSummary(
                label=f"{requirement_id} · "
                f"{_REQUIREMENT_LABELS.get(requirement_id, requirement_id)}",
                value=_REQUIREMENT_STATE_LABELS.get(state, state),
                source_label="冻结证据包",
                freshness_label=datetime.fromisoformat(bundle.information_cutoff_at).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                severity=("info" if state == "complete" else "warn"),
            )
            for requirement_id, state in item.requirement_states
        ]
        timeline = repository.market_timeline(
            context.match_id,
            context.market_definition_id,
            cutoff.isoformat(),
        )
        current_fair = timeline[-1].get("fair_distribution", {}) if timeline else {}
        market_code = (
            uow.market.market_kind(context.market_definition_id) or context.market_definition_id
        )
        faces = []
        for face_code, prior_text in context.prior:
            outcome_key = _OUTCOME_BY_FACE.get(face_code, face_code)
            latest = current_fair.get(outcome_key, current_fair.get(face_code))
            prior = Decimal(prior_text)
            movement = Decimal(0) if latest is None else (Decimal(str(latest)) - prior) * 100
            faces.append(
                JudgmentFaceView(
                    face_code=face_code,
                    face_label=_face_label(face_code, market_code),
                    prior_probability_decimal=prior_text,
                    movement_pp_decimal=_decimal_text(movement),
                    belief_probability_decimal=prior_text,
                )
            )
        factor_rows = tuple(
            uow.connection.execute(
                select(sd.factor_definitions)
                .where(
                    sd.factor_definitions.c.status == "active",
                    sd.factor_definitions.c.policy_version == bundle.policy_version,
                    func.julianday(sd.factor_definitions.c.valid_from)
                    <= func.julianday(cutoff.isoformat()),
                    or_(
                        sd.factor_definitions.c.valid_to.is_(None),
                        func.julianday(sd.factor_definitions.c.valid_to)
                        > func.julianday(cutoff.isoformat()),
                    ),
                )
                .order_by(sd.factor_definitions.c.factor_definition_id)
            ).mappings()
        )
        factors = []
        for row in factor_rows:
            anchors = [
                evidence_token_by_ref[str(ref)]
                for ref in json.loads(str(row["born_from_refs_json"]))
                if str(ref) in evidence_refs
            ]
            if anchors:
                factors.append(
                    JudgmentFactorView(
                        factor_id=str(row["factor_definition_id"]),
                        label=str(row["name"]),
                        scope_key=f"match:{offer.official_match_no}",
                        evidence_ref_tokens=anchors,
                    )
                )
        allowed_bundles = uow.operator_decision.baseline_envelope_allowed_bundles(
            context.baseline_envelope_revision_id,
            official_match_no=offer.official_match_no,
            market_code=market_code,
        )
        return MatchJudgmentEditorView(
            official_match_no=offer.official_match_no,
            match_label=self._match_label(match, offer.official_match_no),
            competition_label=str(match.get("competition") or "赛事"),
            kickoff_at=datetime.fromisoformat(str(match["scheduled_at"])),
            sale_deadline_at=offer.sale_deadline_at,
            market_code=market_code,
            market_label=_MARKET_LABELS.get(
                market_code,
                context.market_definition_id,
            ),
            evidence=evidence,
            evidence_ref_tokens=list(evidence_token_by_ref.values()),
            faces=faces,
            factors=factors,
            rules=[
                JudgmentRuleView(rule_id=rule_id, label=rule_id)
                for rule_id in sorted(DEVIATION_RULE_IDS)
            ],
            face_bundles=[
                JudgmentFaceBundleView(
                    bundle_code=code,
                    face_codes=list(bundle_faces),
                )
                for code, bundle_faces in allowed_bundles.items()
            ],
        )

    def _prescription_ready_step(
        self,
        lineage: _DecisionLineage,
        judgments,
        *,
        completed: int,
        total: int,
    ) -> tuple[JudgeMatchesStep, tuple[str, ...]]:
        judgment_ids = tuple(str(row["operator_match_judgment_revision_id"]) for row in judgments)
        dependencies = tuple(
            sorted(
                (*_decision_dependencies(lineage),)
                + tuple(f"judgment:{revision_id}" for revision_id in judgment_ids)
            )
        )
        judgment_tokens = [
            self._decision_command_token(
                lineage,
                OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION,
                (f"judgment:{revision_id}",),
            )
            for revision_id in judgment_ids
        ]
        return (
            JudgeMatchesStep(
                task_id=lineage.task_key,
                item_key="judgment-prescription",
                title="冻结本轮判断处方",
                prompt="",
                options=[],
                mode="prescription_ready",
                comparison_only=True,
                completed_match_count=completed,
                required_match_count=total,
                prescription_command_token=self._decision_command_token(
                    lineage,
                    OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION,
                    dependencies,
                ),
                judgment_revision_tokens=judgment_tokens,
            ),
            dependencies,
        )

    def _decision_command_token(
        self,
        lineage: _DecisionLineage,
        command_kind: OperatorCommandKind,
        dependency_revision_ids: tuple[str, ...],
    ) -> str:
        if self._snapshot_tokens is None:
            raise ProductActionBlockedError("operator snapshot tokens are not configured")
        return self._snapshot_tokens.encode(
            OperatorSnapshotTokenPayloadV1(
                task_snapshot_hash=lineage.task_snapshot_hash,
                work_item_id=lineage.work_item_id,
                command_kind=command_kind,
                dependency_revision_ids=list(dependency_revision_ids),
            )
        )

    def _judgment_evidence_token(
        self,
        lineage: _DecisionLineage,
        evidence_ref: str,
    ) -> str:
        digest = hashlib.sha256(evidence_ref.encode("utf-8")).hexdigest()
        return self._decision_command_token(
            lineage,
            OperatorCommandKind.COMMIT_MATCH_JUDGMENT,
            (f"evidence-ref:{digest}",),
        )

    @staticmethod
    def _judgment_evidence_refs(
        uow,
        lineage: _DecisionLineage,
        *,
        match_id: str,
    ) -> tuple[str, ...]:
        item = next(
            (
                candidate
                for candidate in uow.operator_decision.task_evidence_bundle_items(
                    lineage.task_evidence_bundle_revision_id
                )
                if candidate.match_id == match_id
            ),
            None,
        )
        if item is None:
            raise ProductActionBlockedError(
                "judgment match has no current frozen evidence item"
            )
        frozen = uow.operator_decision.freeze_bundle_for_action(
            item.freeze_bundle_action_id
        )
        if frozen is None:
            raise ProductActionBlockedError("frozen judgment evidence is unavailable")
        return tuple(
            sorted(
                {
                    *item.requirement_ref_tokens,
                    *item.market_prior_ref_tokens,
                    *item.conflicts_cleared_ref_tokens,
                    *frozen.evidence_ref_tokens,
                }
            )
        )

    @staticmethod
    def _match_label(match: dict[str, object] | None, official_match_no: str) -> str:
        if match is None:
            return f"场 {official_match_no}"
        home = str(match.get("home_team") or "主队")
        away = str(match.get("away_team") or "客队")
        return f"{home} - {away}"

    def worklist(self, *, as_of: datetime) -> OperatorWorklistResponse:
        cutoff = _aware(as_of, "as_of")
        built = sorted(
            self._build_all(cutoff),
            key=lambda item: (
                is_passive_expired_deployment(item.facts, cutoff),
                priority_key(item.facts, cutoff),
            ),
        )
        tasks = [
            item.summary.model_copy(
                update={
                    "priority_rank": rank,
                    "is_actionable": (
                        item.summary.is_actionable
                        and not is_passive_expired_deployment(item.facts, cutoff)
                    ),
                }
            )
            for rank, item in enumerate(built)
        ]
        selected = next(
            (item for item in tasks if item.state is not OperatorTaskState.COMPLETE),
            None,
        )
        return OperatorWorklistResponse(as_of=cutoff, selected=selected, tasks=tasks)

    def _workbench(self, cutoff: datetime) -> OperatorWorkbenchAssembler:
        return OperatorWorkbenchAssembler(
            slates=self._repository.operator_sale_slates(as_of=cutoff.isoformat()),
            built_tasks=self._build_all(cutoff),
            match_lookup=self._repository.match,
            schedule_recoveries=schedule_recovery_views(
                self._repository.operator_schedule_checks(as_of=cutoff.isoformat())
            ),
        )

    def today(self, *, as_of: datetime):
        cutoff = _aware(as_of, "as_of")
        return self._workbench(cutoff).today(as_of=cutoff)

    def lane(self, lane: OperatorLane, *, as_of: datetime):
        cutoff = _aware(as_of, "as_of")
        return self._workbench(cutoff).lane(lane, as_of=cutoff)

    def task_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        *,
        as_of: datetime,
    ):
        expected = (
            r"\d{5}"
            if lane is OperatorLane.ZUCAI
            else r"\d{4}-\d{2}-\d{2}"
        )
        if re.fullmatch(expected, business_key) is None:
            raise ValueError("business key does not match lane")
        cutoff = _aware(as_of, "as_of")
        detail = self._workbench(cutoff).task(
            lane,
            business_key,
            as_of=cutoff,
        )
        detail = self._with_audit_links(detail)
        return detail.model_copy(
            update={
                "no_ticket": self._task_no_ticket_control(
                    detail.task_id,
                    detail.step,
                    cutoff,
                )
            }
        )

    def work_item_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        work_item_key: str,
        *,
        as_of: datetime,
    ):
        expected = (
            r"\d{5}"
            if lane is OperatorLane.ZUCAI
            else r"\d{4}-\d{2}-\d{2}"
        )
        if re.fullmatch(expected, business_key) is None:
            raise ValueError("business key does not match lane")
        if re.fullmatch(r"[a-z][a-z0-9-]{8,100}", work_item_key) is None:
            raise ValueError("work item key is invalid")
        cutoff = _aware(as_of, "as_of")
        detail = self._workbench(cutoff).task(
            lane,
            business_key,
            as_of=cutoff,
            work_item_key=work_item_key,
        )
        detail = self._with_audit_links(detail)
        return detail.model_copy(
            update={
                "no_ticket": self._task_no_ticket_control(
                    detail.task_id,
                    detail.step,
                    cutoff,
                )
            }
        )

    def audit(self, audit_token: str, *, as_of: datetime) -> OperatorAuditEnvelopeV1:
        cutoff = _aware(as_of, "as_of")
        if self._audit_tokens is None:
            raise ProductNotFoundError("operator audit record not found")
        locator = self._audit_tokens.resolve(audit_token)
        try:
            detail = self.work_item_v2(
                locator.lane,
                locator.business_key,
                locator.work_item_key,
                as_of=cutoff,
            )
        except (ProductNotFoundError, ValueError) as error:
            raise ProductNotFoundError("operator audit record not found") from error
        work_item = detail.active_work_item
        if self._audit_snapshot_hash(work_item.snapshot_token) != locator.task_snapshot_hash:
            raise ProductNotFoundError("operator audit record not found")

        slate = next(
            (
                item
                for item in self._repository.operator_sale_slates(
                    as_of=cutoff.isoformat()
                )
                if item.lane is locator.lane
                and item.business_key == locator.business_key
            ),
            None,
        )
        if slate is None:
            raise ProductNotFoundError("operator audit record not found")

        technical_work_item_id = work_item.work_item_key
        dependency_revision_ids: list[str] = []
        try:
            command_payload = self._snapshot_tokens.decode(work_item.snapshot_token)
        except OperatorSnapshotTokenError:
            command_payload = None
        if command_payload is not None:
            technical_work_item_id = command_payload.work_item_id
            dependency_revision_ids = command_payload.dependency_revision_ids

        lineage = [
            OperatorAuditLineageItemV1(
                relation="identifies",
                object_type="operator_work_item",
                object_id=technical_work_item_id,
                revision_id=None,
                content_hash=locator.task_snapshot_hash,
                created_by_action_id=None,
                source_payload_location=None,
            ),
            OperatorAuditLineageItemV1(
                relation="uses",
                object_type="official_sale_slate_revision",
                object_id=slate.slate_revision_id,
                revision_id=slate.slate_revision_id,
                content_hash=slate.content_hash,
                created_by_action_id=None,
                source_payload_location=None,
            ),
        ]
        lineage.extend(
            OperatorAuditLineageItemV1(
                relation="contains",
                object_type="official_offer_revision",
                object_id=offer.official_offer_revision_id,
                revision_id=offer.official_offer_revision_id,
                content_hash=None,
                created_by_action_id=None,
                source_payload_location=None,
            )
            for offer in sorted(
                slate.offers,
                key=lambda item: (
                    item.official_match_no,
                    item.official_offer_revision_id,
                ),
            )
        )
        lineage.extend(
            self._audit_dependency_item(reference)
            for reference in dependency_revision_ids
        )

        projection = self._audit_projection(cutoff)
        return_href = (
            f"/operator-next/{locator.lane.value}/{locator.business_key}/"
            f"{locator.work_item_key}"
        )
        return OperatorAuditEnvelopeV1(
            as_of=cutoff,
            title=f"{detail.task_label}技术审计",
            task_label=detail.task_label,
            work_item_label=work_item.scope_label,
            return_href=return_href,
            task_id=detail.task_id,
            work_item_id=technical_work_item_id,
            task_snapshot_hash=locator.task_snapshot_hash,
            audit_override_ticket_batch_token=(
                detail.step.audit_override_ticket_batch_token
                if isinstance(detail.step, AuditDeploymentStep)
                else None
            ),
            lineage=lineage,
            projection=projection,
        )

    def _with_audit_links(self, detail):
        if self._audit_tokens is None:
            return detail
        updated_items = [
            item.model_copy(
                update={
                    "audit_href": (
                        "/operator-next/audit/"
                        + self._audit_tokens.issue(
                            lane=detail.lane,
                            business_key=detail.business_key,
                            work_item_key=item.work_item_key,
                            task_snapshot_hash=self._audit_snapshot_hash(
                                item.snapshot_token
                            ),
                        )
                    )
                }
            )
            for item in detail.work_items
        ]
        active = next(
            item
            for item in updated_items
            if item.work_item_key == detail.active_work_item.work_item_key
        )
        return detail.model_copy(
            update={"work_items": updated_items, "active_work_item": active}
        )

    def _audit_snapshot_hash(self, snapshot_token: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", snapshot_token):
            return snapshot_token
        if self._snapshot_tokens is not None:
            try:
                return self._snapshot_tokens.decode(snapshot_token).task_snapshot_hash
            except OperatorSnapshotTokenError:
                pass
        return _token({"audit_snapshot_token": snapshot_token})

    @staticmethod
    def _audit_dependency_item(reference: str) -> OperatorAuditLineageItemV1:
        object_type, separator, object_id = reference.partition(":")
        return OperatorAuditLineageItemV1(
            relation="depends_on",
            object_type=object_type if separator else "dependency_revision",
            object_id=object_id if separator else reference,
            revision_id=object_id if separator else reference,
            content_hash=None,
            created_by_action_id=(object_id if object_type == "action" else None),
            source_payload_location=None,
        )

    def _audit_projection(self, cutoff: datetime) -> OperatorAuditProjectionV1:
        projection = self._repository.scoreboard_projection(as_of=cutoff.isoformat())
        current_high_watermark = self._repository.action_high_watermark()
        health = projection.get("health")
        if not isinstance(health, dict):
            raise ValueError("scoreboard projection health is unavailable")
        state = str(health.get("state"))
        if state == "unavailable":
            return OperatorAuditProjectionV1(
                projection_name="scoreboard",
                state="unavailable",
                projection_version=None,
                source_action_high_watermark=None,
                current_action_high_watermark=current_high_watermark,
                built_at=None,
            )
        if state not in {"available", "stale"}:
            raise ValueError("unknown scoreboard projection state")
        source_high_watermark = int(health["source_high_watermark"])
        built_at_value = health.get("built_at")
        built_at = (
            built_at_value
            if isinstance(built_at_value, datetime)
            else datetime.fromisoformat(str(built_at_value))
        )
        return OperatorAuditProjectionV1(
            projection_name="scoreboard",
            state=(
                "ready"
                if source_high_watermark == current_high_watermark
                else "stale"
            ),
            projection_version=str(health["projection_version"]),
            source_action_high_watermark=source_high_watermark,
            current_action_high_watermark=current_high_watermark,
            built_at=_aware(built_at, "scoreboard projection built_at"),
        )

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
            no_ticket=self._task_no_ticket_control(task_id, built.step, cutoff),
        )

    def _task_no_ticket_control(
        self,
        task_id: str,
        step: StepView,
        as_of: datetime,
    ) -> NoTicketControl | None:
        if self._snapshot_tokens is None or self._operator_decisions is None:
            return None
        if isinstance(step, AuditDeploymentStep) and step.surface_version == "2":
            recorded = step.mode == "supersede_no_ticket"
            command_token = (
                step.command_token if recorded else step.no_ticket_command_token
            )
            if command_token is None:
                return None
            return NoTicketControl(
                state="recorded" if recorded else "available",
                command_token=command_token,
                no_ticket_revision_token=step.no_ticket_revision_token,
                comparison_candidate_token=step.comparison_candidate_token,
                rule_options=step.rule_options,
            )

        lane, separator, business_key = task_id.partition(":")
        if not separator or lane not in {"jczq", "zucai"} or not business_key:
            return None
        slate = self._official_slate(task_id, as_of)
        if slate is None:
            return None
        work_item_id = None
        closures: list[NoTicketClosure] = []
        current_task_closures = ()
        with self._decision_uow() as uow:
            bundle = uow.operator_decision.current_task_evidence_bundle_revision(
                task_id,
                as_of=as_of.isoformat(),
            )
            if bundle is not None and bundle.slate_revision_id == slate.slate_revision_id:
                baseline_rows = _current_baseline_rows(uow, task_id, bundle, as_of)
                if len(baseline_rows) == 1:
                    work_item_id = str(baseline_rows[0]["work_item_id"])
            current_task_closures = (
                uow.operator_result.current_no_ticket_revisions_for_task_family(
                    task_id
                )
            )
            for closure in current_task_closures:
                if closure.deployment_outcome == "reopened":
                    continue
                for scope in uow.operator_result.no_ticket_offer_scopes(
                    closure.no_ticket_revision_id
                ):
                    offer = uow.operator_sale.offer_revision(
                        scope.official_offer_revision_id
                    )
                    if offer is not None:
                        closures.append(
                            NoTicketClosure(
                                official_offer_family_id=(
                                    offer.official_offer_family_id
                                ),
                                official_offer_revision_id=(
                                    offer.official_offer_revision_id
                                ),
                            )
                        )
        if work_item_id is None:
            wave = derive_sale_wave(
                slate,
                as_of,
                no_ticket_closures=tuple(closures),
            )
            if wave is not None:
                work_item_id = wave.work_item_id
            else:
                closed = tuple(
                    closure
                    for closure in current_task_closures
                    if closure.deployment_outcome != "reopened"
                )
                if not closed:
                    return None
                work_item_id = closed[-1].work_item_id
        context = self._operator_decisions.no_ticket_decision_context(
            task_family_id=task_id,
            lane=lane,
            business_key=business_key,
            work_item_id=work_item_id,
            as_of=as_of,
        )
        current = None
        if context.current_no_ticket_revision_id is not None:
            with self._decision_uow() as uow:
                current = uow.operator_result.no_ticket_revision(
                    context.current_no_ticket_revision_id
                )
        recorded = bool(
            current is not None
            and current.deployment_outcome != "reopened"
            and not context.offer_revision_ids
            and not context.artifact_ids
        )
        if not recorded and not context.offer_revision_ids and not context.artifact_ids:
            return None
        command_kind = (
            OperatorCommandKind.SUPERSEDE_NO_TICKET
            if recorded
            else OperatorCommandKind.RECORD_NO_TICKET
        )
        dependencies = tuple(
            sorted(
                (
                    f"business_key:{context.business_key}",
                    f"lane:{context.lane}",
                    f"scope_fingerprint:{context.scope_fingerprint}",
                    f"slate_revision:{context.slate_revision_id}",
                    f"task_family:{context.task_family_id}",
                )
            )
        )
        command_token = self._snapshot_tokens.encode(
            OperatorSnapshotTokenPayloadV1(
                task_snapshot_hash=context.task_snapshot_hash,
                work_item_id=context.work_item_id,
                command_kind=command_kind,
                dependency_revision_ids=list(dependencies),
            )
        )
        revision_token = None
        if recorded and current is not None:
            revision_token = self._snapshot_tokens.encode(
                OperatorSnapshotTokenPayloadV1(
                    task_snapshot_hash=context.task_snapshot_hash,
                    work_item_id=context.work_item_id,
                    command_kind=command_kind,
                    dependency_revision_ids=[
                        f"no_ticket_revision:{current.no_ticket_revision_id}"
                    ],
                )
            )
        return NoTicketControl(
            state="recorded" if recorded else "available",
            command_token=command_token,
            no_ticket_revision_token=revision_token,
            rule_options=[
                DeploymentRuleOption(
                    label=rule_id,
                    token=self._snapshot_tokens.encode(
                        OperatorSnapshotTokenPayloadV1(
                            task_snapshot_hash=context.task_snapshot_hash,
                            work_item_id=context.work_item_id,
                            command_kind=command_kind,
                            dependency_revision_ids=[f"rule:{rule_id}"],
                        )
                    ),
                )
                for rule_id in sorted(DEVIATION_RULE_IDS)
            ],
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
        if self._official_slate(task_id, as_of) is None:
            raise ProductNotFoundError("operator evidence not found")
        try:
            bundle = self._legacy_bundle(issue)
        except OperatorArtifactError as error:
            raise ProductNotFoundError("operator evidence not found") from error
        if bundle is None:
            raise ProductNotFoundError("operator evidence not found")
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
                    EvidenceFieldSummary(label="胜", value=f"{record.fair_had.home:.2%}"),
                    EvidenceFieldSummary(label="平", value=f"{record.fair_had.draw:.2%}"),
                    EvidenceFieldSummary(label="负", value=f"{record.fair_had.away:.2%}"),
                    EvidenceFieldSummary(label="让球", value=record.hhad_line or "未提供"),
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

    def _legacy_bundle(self, issue: str) -> ZucaiArtifactBundle | None:
        if self._legacy_fixture_adapter is None:
            return None
        return self._legacy_fixture_adapter.load_optional(issue)

    def _build_all(self, cutoff: datetime) -> list[_BuiltTask]:
        slates = self._repository.operator_sale_slates(as_of=cutoff.isoformat())
        ticket_rows = self._repository.operator_ticket_artifacts(cutoff.isoformat())
        built: list[_BuiltTask] = []
        for slate in slates:
            deadline = min(
                (offer.sale_deadline_at for offer in slate.offers),
                default=None,
            )
            if slate.lane is OperatorLane.ZUCAI:
                ZucaiLaneAdapter().validate_slate(slate)
                primary = self._build_zucai(slate.business_key, cutoff, slate)
            else:
                JczqLaneAdapter().validate_slate(slate)
                primary = self._build_jczq(
                    slate.business_key,
                    cutoff,
                    ticket_rows,
                    slate,
                )
            built.append(self._archive_expired_sale_wave(primary, cutoff))
            built.extend(
                self._formal_artifact_stages(
                    f"{slate.lane.value}:{slate.business_key}",
                    slate.lane,
                    slate.business_key,
                    cutoff,
                )
            )
            built.extend(
                self._formal_review_stages(
                    f"{slate.lane.value}:{slate.business_key}",
                    slate.lane,
                    slate.business_key,
                    deadline,
                    cutoff,
                )
            )
        return built

    @staticmethod
    def _archive_expired_sale_wave(
        built: _BuiltTask,
        cutoff: datetime,
    ) -> _BuiltTask:
        if not is_passive_expired_deployment(built.facts, cutoff):
            return built
        task_id = f"{built.facts.lane.value}:{built.facts.business_key}"
        return replace(
            built,
            summary=built.summary.model_copy(
                update={
                    "state": OperatorTaskState.COMPLETE,
                    "is_actionable": False,
                    "next_action_label": NEXT_ACTION_LABELS[
                        OperatorTaskState.COMPLETE
                    ],
                }
            ),
            step=CompleteStep(
                task_id=task_id,
                title="本销售窗口已结束",
                summary="截止前未形成正式出票；本工作项仅保留在历史记录中。",
            ),
            scope_kind=ScopeKind.SALE_WAVE,
            projected_state=OperatorTaskState.COMPLETE,
        )

    def _build_task(self, task_id: str, cutoff: datetime) -> _BuiltTask:
        candidates = [
            item
            for item in self._build_all(cutoff)
            if f"{item.facts.lane.value}:{item.facts.business_key}" == task_id
        ]
        if not candidates:
            raise ProductNotFoundError(f"operator task {task_id} not found")
        return min(
            candidates,
            key=lambda item: (
                is_passive_expired_deployment(item.facts, cutoff),
                priority_key(item.facts, cutoff),
            ),
        )

    def _official_slate(self, task_id: str, cutoff: datetime) -> SaleSlateSnapshot | None:
        return next(
            (
                slate
                for slate in self._repository.operator_sale_slates(as_of=cutoff.isoformat())
                if f"{slate.lane.value}:{slate.business_key}" == task_id
            ),
            None,
        )

    def _build_zucai(self, issue: str, cutoff: datetime, slate: SaleSlateSnapshot) -> _BuiltTask:
        task_id = f"zucai:{issue}"
        official_deadline = min(
            (offer.sale_deadline_at for offer in slate.offers),
            default=None,
        )
        formal = self._formal_judgment_task(
            task_id,
            OperatorLane.ZUCAI,
            issue,
            official_deadline,
            slate,
            cutoff,
        )
        if formal is not None:
            return formal
        try:
            bundle = self._legacy_bundle(issue)
        except OperatorArtifactError as error:
            return self._source_block(task_id, issue, error, official_deadline, slate)
        if bundle is None:
            return self._prepare_task(
                task_id,
                OperatorLane.ZUCAI,
                issue,
                official_deadline,
                slate,
                cutoff,
            )
        adjudications = self._repository.adjudications_for_subject(
            "issue", issue, cutoff.isoformat()
        )
        predictions = self._repository.predictions_for_subject("issue", issue, cutoff.isoformat())
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
            deadline_at=official_deadline,
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
            "official_slate": slate,
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

    def _source_block(
        self,
        task_id: str,
        issue: str,
        error: Exception,
        deadline: datetime | None,
        slate: SaleSlateSnapshot,
    ) -> _BuiltTask:
        facts = OperatorTaskFacts(
            lane=OperatorLane.ZUCAI,
            business_key=issue,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code="source_contract_invalid",
            has_issue=True,
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
            _token({"task_id": task_id, "slate": slate, "error": str(error)}),
        )

    def _prepare_task(
        self,
        task_id: str,
        lane: OperatorLane,
        business_key: str,
        deadline: datetime | None,
        slate: SaleSlateSnapshot,
        cutoff: datetime,
    ) -> _BuiltTask:
        facts = OperatorTaskFacts(
            lane=lane,
            business_key=business_key,
            deadline_at=deadline,
            waiting_until=None,
            source_error_code=None,
            has_issue=True,
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
        step = (
            self._operator_evidence.prepare_step(task_id, as_of=cutoff)
            if self._operator_evidence is not None
            else PrepareStep(
                task_id=task_id,
                title="准备本任务数据",
                recovery=OperatorRecoverySummary(
                    code="operator_inputs_missing",
                    missing="本任务的严格证据与结构化输入",
                    impact="官方任务已建立，判断与构票尚不能开始",
                    action_label="采集并导入本任务数据",
                ),
            )
        )
        return _BuiltTask(
            facts=facts,
            summary=_summary(
                facts,
                title=("足彩 " if lane is OperatorLane.ZUCAI else "竞彩 ") + business_key,
            ),
            progress=TaskProgressSummary(
                completed=0,
                total=0,
                label=NEXT_ACTION_LABELS[resolve_state(facts)],
            ),
            step=step,
            mutation_token=_token({"task_id": task_id, "slate": slate}),
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
            for match_no in sorted(set(prescription) | set(candidate.faces()), key=int):
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
            else "warn"
            if any(item.level == "WARN" for item in findings)
            else "pass"
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
                    "history_window": _renjiu_history_window(
                        bundle.issue.issue_id, available_rows=len(history)
                    ),
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
        self,
        run_date: str,
        cutoff: datetime,
        rows: list[dict[str, Any]],
        slate: SaleSlateSnapshot,
    ) -> _BuiltTask:
        task_id = f"jczq:{run_date}"
        formal = self._formal_judgment_task(
            task_id,
            OperatorLane.JCZQ,
            run_date,
            min(
                (offer.sale_deadline_at for offer in slate.offers),
                default=None,
            ),
            slate,
            cutoff,
        )
        if formal is not None:
            return formal
        task_rows = [row for row in rows if str(row["run_date"]) == run_date]
        if not task_rows:
            return self._prepare_task(
                task_id,
                OperatorLane.JCZQ,
                run_date,
                min(
                    (offer.sale_deadline_at for offer in slate.offers),
                    default=None,
                ),
                slate,
                cutoff,
            )
        ticket = next((row for row in task_rows if row.get("ticket_artifact_id")), None)
        deadline_raw = next(
            (
                row.get("deadline_at") or row.get("batch_deadline_at")
                for row in task_rows
                if row.get("deadline_at") or row.get("batch_deadline_at")
            ),
            None,
        )
        deadline = min(
            (offer.sale_deadline_at for offer in slate.offers),
            default=(datetime.fromisoformat(str(deadline_raw)) if deadline_raw else None),
        )
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
            summary = "未确认，按未出票处理；没有入账" if placement == "shadow" else "已按记录完成"
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
