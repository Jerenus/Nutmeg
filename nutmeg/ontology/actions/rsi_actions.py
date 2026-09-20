"""RSI 实验对象的 typed Actions。

八个 action_type，权限在迁移 v29 的 action_permissions 里：
- rsi_register_experiment / rsi_amend_experiment / rsi_approve_deployment：只许 judge_operator
- rsi_record_verdict：只许 deterministic_system（人不能替 falsifier 说话）
- 其余两者皆可。

所有写入只追加；状态是 nutmeg.ontology.rsi.models.project_status 的投影。
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.rsi import (
    AmendmentRow,
    DeploymentRow,
    DutyInstanceRow,
    DutyRow,
    ExperimentRow,
    GradeRow,
    ObservationRow,
    VerdictRow,
)
from nutmeg.ontology.rsi.models import (
    FROZEN_FIELDS,
    DeploymentDecision,
    Falsifier,
    GradeMode,
    Layer,
    Population,
    Tier,
    Verdict,
    frozen_hash,
    validate_tier_for_layer,
    window_contains,
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
    population_match_kickoffs: dict = field(default_factory=dict)
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

    # ── schedule ──────────────────────────────────────────────────
    def schedule_duties(self, request: ScheduleDutiesRequest) -> ActionOutcome:
        requested_at = request.requested_at or datetime.now().astimezone()
        command = ActionCommand.create(
            action_type="rsi_schedule_duties", actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key or f"rsi-sched:{request.day}",
            payload={"day": request.day, "earliest_kickoff": request.earliest_kickoff,
                     "issue": request.issue},
            requested_at=requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            refs: list[ObjectRef] = []
            for duty in uow.rsi.all_duties():
                experiment = uow.rsi.experiment(duty.exp_id)
                if experiment.layer == "structural" and not window_contains(
                    experiment.window, issue=request.issue, day=request.day
                ):
                    continue
                if duty.scope == "day":
                    targets = [("", request.earliest_kickoff)]
                else:
                    match_kickoffs = request.population_match_kickoffs.get(
                        experiment.population, request.match_kickoffs
                    )
                    targets = list(match_kickoffs.items())
                for match_id, due_at in targets:
                    if uow.rsi.duty_instance(duty.duty_id, request.day, match_id) is not None:
                        continue                       # 已排过：幂等
                    uow.rsi.insert_duty_instance(DutyInstanceRow(
                        duty_id=duty.duty_id, day=request.day, match_id=match_id,
                        issue=request.issue, due_at=due_at, fulfilled_at=None,
                        artifact_path=None, artifact_hash=None))
                    refs.append(ObjectRef("rsi_duty_instance", f"{duty.duty_id}@{request.day}"))
            return tuple(refs)

        return self._svc.execute(command, handler)

    # ── fulfill + observation ─────────────────────────────────────
    def fulfill_duty(self, request: FulfillDutyRequest) -> ActionOutcome:
        requested_at = request.requested_at or datetime.now().astimezone()
        duty_id = f"{request.exp_id}:{request.duty_name}"
        artifact_hash = hashlib.sha256(request.artifact_bytes).hexdigest()
        captured = _iso(request.captured_at)
        # prospective：采样时刻早于当天最早开球（U8-④ 前缀纪律的采样端）
        prospective = request.captured_at < datetime.fromisoformat(request.earliest_kickoff)
        command = ActionCommand.create(
            action_type="rsi_fulfill_duty", actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key or f"rsi-ful:{duty_id}:{request.day}",
            payload={"duty_id": duty_id, "day": request.day, "artifact_hash": artifact_hash,
                     "prospective": prospective},
            requested_at=requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            inst = uow.rsi.duty_instance(duty_id, request.day, request.match_id)
            if inst is None:
                raise ValueError(f"{duty_id} 在 {request.day} 没有排过（先 rsi schedule）")
            # 只有前瞻产物才算履行义务；赛后补的产物留观察记录但这一天仍是 gap
            if prospective and inst.fulfilled_at is None:
                uow.rsi.mark_duty_fulfilled(duty_id, request.day, request.match_id,
                                            fulfilled_at=captured,
                                            artifact_path=request.artifact_path,
                                            artifact_hash=artifact_hash)
            obs_base = f"{request.exp_id}:{request.day}" + (
                f":{request.match_id}" if request.match_id else "")
            existing = uow.rsi.observation(obs_base)
            obs_id = (
                obs_base
                if existing is None or existing.artifact_hash == artifact_hash
                else f"{obs_base}:{artifact_hash[:16]}"
            )
            if uow.rsi.observation(obs_id) is None:  # 同日同内容不重复；内容变化留版本
                uow.rsi.insert_observation(ObservationRow(
                    observation_id=obs_id, exp_id=request.exp_id, day=request.day,
                    population_stratum=request.population_stratum, n_rows=request.n_rows,
                    captured_at=captured, prospective=prospective,
                    judgment_tier_hist=dict(request.judgment_tier_hist),
                    artifact_hash=artifact_hash))
            return (ObjectRef("rsi_observation", obs_id),)

        return self._svc.execute(command, handler)

    # ── grade ─────────────────────────────────────────────────────
    def grade_experiment(self, request: GradeExperimentRequest) -> ActionOutcome:
        GradeMode(request.mode)
        command = ActionCommand.create(
            action_type="rsi_grade_experiment", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"exp_id": request.exp_id, "mode": request.mode, "stratum": request.stratum,
                     "n_cum": request.n_cum, "inputs_hash": request.inputs_hash},
            requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            exp = uow.rsi.experiment(request.exp_id)
            if exp is None:
                raise ValueError(f"{request.exp_id} 未登记")
            f = Falsifier.from_dict(exp.falsifier)
            gid = _new_id("rsig")
            uow.rsi.insert_grade(GradeRow(
                grade_id=gid, exp_id=request.exp_id, mode=request.mode, stratum=request.stratum,
                n_cum=request.n_cum, metric=f.metric, metric_value_pp=request.metric_value_pp,
                ci_low_pp=request.ci_low_pp, ci_high_pp=request.ci_high_pp,
                distance_to_falsifier_pp=f.distance_pp(ci_low=request.ci_low_pp,
                                                       ci_high=request.ci_high_pp),
                cost_axis_pp=request.cost_axis_pp,      # 独立轴，从不与 metric 合成
                as_of_policy=request.as_of_policy, computed_by=request.computed_by,
                inputs_hash=request.inputs_hash, graded_at=_iso(request.requested_at)))
            return (ObjectRef("rsi_grade", gid),)

        return self._svc.execute(command, handler)

    # ── verdict（只许系统；只读 prospective；只读 CI 边界）────────
    def record_verdict(self, request: RecordVerdictRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="rsi_record_verdict", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"exp_id": request.exp_id}, requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            exp = uow.rsi.experiment(request.exp_id)
            if exp is None:
                raise ValueError(f"{request.exp_id} 未登记")
            f = Falsifier.from_dict(exp.falsifier)
            primary = uow.rsi.latest_grade(request.exp_id, mode="prospective", stratum=f.stratum)
            if primary is None:
                raise ValueError("没有 prospective 档的 grade——重放结果进不了判决")
            if primary.n_cum < f.n_min:
                raise ValueError(
                    f"未到期：n_cum={primary.n_cum}，距 n_min 还差 {f.n_min - primary.n_cum}")
            verdict = f.evaluate(n_cum=primary.n_cum, ci_low=primary.ci_low_pp,
                                 ci_high=primary.ci_high_pp)
            # 分层优先：population=both 时两层符号相反且 CI 不重叠 → 合并层 inconclusive
            if exp.population == Population.BOTH.value and verdict is Verdict.SURVIVED:
                z = uow.rsi.latest_grade(request.exp_id, mode="prospective", stratum="zucai")
                j = uow.rsi.latest_grade(request.exp_id, mode="prospective", stratum="jczq")
                if z is not None and j is not None:
                    opposite = (z.metric_value_pp > 0) != (j.metric_value_pp > 0)
                    disjoint = z.ci_low_pp > j.ci_high_pp or j.ci_low_pp > z.ci_high_pp
                    if opposite and disjoint:
                        verdict = Verdict.INCONCLUSIVE
            vid = _new_id("rsiv")
            uow.rsi.insert_verdict(VerdictRow(
                verdict_id=vid, exp_id=request.exp_id, verdict=verdict.value,
                grade_id=primary.grade_id, criterion_snapshot=dict(exp.falsifier),
                decided_at=_iso(request.requested_at)))
            return (ObjectRef("rsi_verdict", vid),)

        return self._svc.execute(command, handler)

    # ── deployment（只许人）──────────────────────────────────────
    def approve_deployment(self, request: ApproveDeploymentRequest) -> ActionOutcome:
        decision = DeploymentDecision(request.decision)
        command = ActionCommand.create(
            action_type="rsi_approve_deployment", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"exp_id": request.exp_id, "decision": decision.value,
                     "rule_id": request.rule_id}, requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            exp = uow.rsi.experiment(request.exp_id)
            if exp is None:
                raise ValueError(f"{request.exp_id} 未登记")
            if not request.reason.strip():
                raise ValueError("deployment 必须带 reason")
            if decision is DeploymentDecision.DEPLOY:
                if exp.layer != Layer.STRUCTURAL.value or exp.tier != Tier.DEPLOY_ELIGIBLE.value:
                    raise ValueError("只有 structural 层且 deploy_eligible 的实验可上线")
                v = uow.rsi.latest_verdict(request.exp_id)
                if v is None or v.verdict != Verdict.SURVIVED.value:
                    raise ValueError("只有 verdict=survived 的实验可上线")
                if not request.rule_id:
                    raise ValueError("deploy 必须指明目标 rule_id")
            if decision is DeploymentDecision.EXTEND and not request.extend_to_exp_id:
                raise ValueError("extend 必须给新 exp_id（不许原地延窗）")
            did = _new_id("rsid")
            uow.rsi.insert_deployment(DeploymentRow(
                deployment_id=did, exp_id=request.exp_id, decision=decision.value,
                rule_id=request.rule_id, reason=request.reason,
                adjudication_ref=request.adjudication_ref,
                extend_to_exp_id=request.extend_to_exp_id, actor_id=request.actor_id,
                decided_at=_iso(request.requested_at)))
            return (ObjectRef("rsi_deployment", did),)

        return self._svc.execute(command, handler)
