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
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_operator_decision as sod
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
    EvidenceFieldSummary,
    JudgeMatchesStep,
    JudgmentFaceBundleView,
    JudgmentFaceView,
    JudgmentFactorView,
    JudgmentRuleView,
    LedgerStep,
    MatchJudgmentEditorView,
    OperatorEvidenceResponse,
    OperatorLane,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrepareStep,
    PrescriptionDifferenceSummary,
    ReviewItemSummary,
    ReviewStep,
    StepView,
    TaskProgressSummary,
    TicketVersionSummary,
)
from nutmeg.product.operator_evidence import OperatorEvidenceService
from nutmeg.product.operator_lanes import (
    JczqLaneAdapter,
    SaleSlateSnapshot,
    ZucaiLaneAdapter,
)
from nutmeg.product.operator_state import (
    NEXT_ACTION_LABELS,
    OperatorTaskFacts,
    priority_key,
    resolve_state,
)
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenPayloadV1,
)
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository

if TYPE_CHECKING:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


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


class _OfficialHistoryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _BuiltTask:
    facts: OperatorTaskFacts
    summary: OperatorTaskSummary
    progress: TaskProgressSummary
    step: StepView
    mutation_token: str


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
    ) -> None:
        self._repository = repository
        self._product_queries = product_queries
        self._legacy_fixture_adapter = legacy_fixture_adapter
        self._official_history = official_history_provider
        self._clock = clock
        self._operator_evidence = operator_evidence
        self._unit_of_work_factory = unit_of_work_factory
        self._snapshot_tokens = snapshot_tokens

    def evidence_freeze_context(self, task_key: str, *, as_of: datetime):
        if self._operator_evidence is None:
            raise ProductNotFoundError("operator evidence service is unavailable")
        return self._operator_evidence.evidence_freeze_context(task_key, as_of=as_of)

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
        if self._unit_of_work_factory is None or self._snapshot_tokens is None:
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
                            step = self._candidate_comparison_step(
                                uow,
                                lineage,
                                prescription,
                                candidate_sets,
                                dependency_ids,
                                selection=(
                                    selection if selection_completed else None
                                ),
                            )
                            progress_label = (
                                "等待部署审计"
                                if selection_completed
                                else "比较候选票"
                            )
        formal_ticket_stage = isinstance(step, ConstructTicketStep)
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
            if slate.lane is OperatorLane.ZUCAI:
                ZucaiLaneAdapter().validate_slate(slate)
                built.append(self._build_zucai(slate.business_key, cutoff, slate))
            else:
                JczqLaneAdapter().validate_slate(slate)
                built.append(self._build_jczq(slate.business_key, cutoff, ticket_rows, slate))
        return built

    def _build_task(self, task_id: str, cutoff: datetime) -> _BuiltTask:
        slate = self._official_slate(task_id, cutoff)
        if slate is None:
            raise ProductNotFoundError(f"operator task {task_id} not found")
        if match := re.fullmatch(r"zucai:(\d{5})", task_id):
            return self._build_zucai(match.group(1), cutoff, slate)
        if match := re.fullmatch(r"jczq:(\d{4}-\d{2}-\d{2})", task_id):
            rows = self._repository.operator_ticket_artifacts(cutoff.isoformat())
            return self._build_jczq(match.group(1), cutoff, rows, slate)
        raise ProductNotFoundError(f"operator task {task_id} not found")

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
