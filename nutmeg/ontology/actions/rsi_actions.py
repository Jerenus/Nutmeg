"""RSI 实验对象的 typed Actions。

八个 action_type，权限在迁移 v29 的 action_permissions 里：
- rsi_register_experiment / rsi_amend_experiment / rsi_approve_deployment：只许 judge_operator
- rsi_record_verdict：只许 deterministic_system（人不能替 falsifier 说话）
- 其余两者皆可。

所有写入只追加；状态是 nutmeg.ontology.rsi.models.project_status 的投影。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.rsi import (
    AmendmentRow,
    DutyRow,
    ExperimentRow,
)
from nutmeg.ontology.rsi.models import (
    FROZEN_FIELDS,
    Falsifier,
    Layer,
    Population,
    Tier,
    frozen_hash,
    validate_tier_for_layer,
)

_REQUIRED_DOC_KEYS = ("exp_id", "claim", "mechanism", "tier", "layer", "population", "min_tier",
                      "window", "falsifier", "stop_rule", "quota_slot", "source_doc",
                      "registered_at")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class RegisterExperimentRequest:
    doc: dict
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class AmendExperimentRequest:
    exp_id: str
    what: str
    why: str
    rule_check: str
    mechanism_note: str | None
    touches: dict            # 想改的字段 → 值；命中 FROZEN_FIELDS 一律拒绝
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduleDutiesRequest:
    day: str                                  # 业务日 YYYY-MM-DD
    earliest_kickoff: str                     # 当天两板最早开球 ISO
    issue: str | None                         # 足彩期号（有则填，供 {issue} 占位）
    match_kickoffs: dict = field(default_factory=dict)   # match_id → kickoff ISO（scope=match 用）
    actor_id: str = "sys:rsi"
    actor_role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM
    idempotency_key: str = ""
    requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FulfillDutyRequest:
    exp_id: str
    duty_name: str
    day: str
    artifact_path: str
    artifact_bytes: bytes
    n_rows: int
    population_stratum: str
    judgment_tier_hist: dict
    captured_at: datetime
    earliest_kickoff: str
    match_id: str = ""
    actor_id: str = "sys:rsi"
    actor_role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM
    idempotency_key: str = ""
    requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GradeExperimentRequest:
    exp_id: str
    mode: str
    stratum: str
    n_cum: int
    metric_value_pp: float
    ci_low_pp: float
    ci_high_pp: float
    cost_axis_pp: float | None
    as_of_policy: str
    computed_by: str
    inputs_hash: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RecordVerdictRequest:
    exp_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ApproveDeploymentRequest:
    exp_id: str
    decision: str
    reason: str
    rule_id: str | None
    adjudication_ref: str | None
    extend_to_exp_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class RsiActions:
    def __init__(self, action_service: ActionService) -> None:
        self._svc = action_service

    # ── register ──────────────────────────────────────────────────
    def register_experiment(self, request: RegisterExperimentRequest) -> ActionOutcome:
        doc = request.doc
        missing = [k for k in _REQUIRED_DOC_KEYS if k not in doc]
        if missing:
            raise ValueError(f"登记原件缺字段: {missing}")
        tier, layer = Tier(doc["tier"]), Layer(doc["layer"])
        validate_tier_for_layer(tier, layer)
        Population(doc["population"])
        Falsifier.from_dict(doc["falsifier"])          # 结构化校验
        fh = frozen_hash(doc)
        command = ActionCommand.create(
            action_type="rsi_register_experiment", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"exp_id": doc["exp_id"], "frozen_hash": fh},
            requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            if uow.rsi.experiment(doc["exp_id"]) is not None:
                raise ValueError(f"{doc['exp_id']} 已登记；要改用 amend，要换判据另立新 exp_id")
            uow.rsi.insert_experiment(ExperimentRow(
                exp_id=doc["exp_id"], claim=doc["claim"], mechanism=doc["mechanism"],
                tier=tier.value, layer=layer.value, population=doc["population"],
                min_tier=doc["min_tier"], window=dict(doc["window"]),
                falsifier=dict(doc["falsifier"]), stop_rule=doc["stop_rule"],
                quota_slot=bool(doc["quota_slot"]), buckets=list(doc.get("buckets") or []),
                rule_ids=list(doc.get("rule_ids") or []), replay_spec=doc.get("replay_spec"),
                dream_ref=doc.get("dream_ref"), variants_tried=doc.get("variants_tried"),
                source_doc=doc["source_doc"], registered_at=doc["registered_at"],
                frozen_hash=fh, created_at=_iso(request.requested_at)))
            refs = [ObjectRef("rsi_experiment", doc["exp_id"])]
            for d in doc.get("duties") or []:
                duty_id = f"{doc['exp_id']}:{d['name']}"
                uow.rsi.insert_duty(DutyRow(
                    duty_id=duty_id, exp_id=doc["exp_id"], recurrence="per_day",
                    scope=d.get("scope", "day"), deadline_rule=d["deadline_rule"],
                    instrument=list(d["instrument"]), artifact_glob=d["artifact_glob"],
                    description=d.get("description", "")))
                refs.append(ObjectRef("rsi_duty", duty_id))
            return tuple(refs)

        return self._svc.execute(command, handler)

    # ── amend ─────────────────────────────────────────────────────
    def amend_experiment(self, request: AmendExperimentRequest) -> ActionOutcome:
        frozen_hit = sorted(k for k in request.touches if k in FROZEN_FIELDS)
        if frozen_hit:
            raise ValueError(f"修正案碰到冻结字段 {frozen_hit}：判据不可修，只能另立新实验")
        command = ActionCommand.create(
            action_type="rsi_amend_experiment", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"exp_id": request.exp_id, "what": request.what},
            requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            if uow.rsi.experiment(request.exp_id) is None:
                raise ValueError(f"{request.exp_id} 未登记")
            aid = _new_id("rsiam")
            uow.rsi.insert_amendment(AmendmentRow(
                amendment_id=aid, exp_id=request.exp_id, what=request.what, why=request.why,
                rule_check=request.rule_check, mechanism_note=request.mechanism_note,
                amended_at=_iso(request.requested_at)))
            return (ObjectRef("rsi_amendment", aid),)

        return self._svc.execute(command, handler)
