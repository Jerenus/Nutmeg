# RSI 过程持久化 Implementation Plan · Part 2（Task 4–7：Actions 与登记原件）

> 续 `2026-09-18-rsi-experiment-persistence.md`（Task 1–3）。同一份 header/纪律适用。

---

### Task 4: RsiActions —— register_experiment / amend_experiment

**Files:**
- Create: `nutmeg/ontology/actions/rsi_actions.py`
- Modify: `nutmeg/ontology/wiring.py`（`reliability_actions = ReliabilityActions(action_service)` 后加一行；`OntologyKernel(...)` 调用加 `rsi_actions=rsi_actions`）
- Modify: `nutmeg/ontology/kernel.py`（`__init__` 加参数 `rsi_actions: RsiActions` 与 `self.rsi_actions = rsi_actions`）
- Test: `tests/ontology/test_rsi_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ontology/test_rsi_actions.py
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    AmendExperimentRequest,
    RegisterExperimentRequest,
    RsiActions,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T0 = datetime(2026, 9, 18, 12, tzinfo=UTC)
HUMAN = dict(actor_id="op:jun", actor_role=ActorRole.JUDGE_OPERATOR)
SYSTEM = dict(actor_id="sys:rsi", actor_role=ActorRole.DETERMINISTIC_SYSTEM)

F2_DOC = {
    "exp_id": "F2", "claim": "让球线向主移动 → 主胜残差为正", "mechanism": "改线是承诺",
    "tier": "observation", "layer": "judgment", "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "累计 n≥140 结账，期间不得调阈值", "quota_slot": False,
    "buckets": ["向客 ≤-0.25", "不动 0", "向主 +0.25", "向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record", "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json",
                "description": "F2 让球线观察单"}],
}


def _rig(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    return RsiActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_register_freezes_the_doc_and_generates_duties(tmp_path):
    actions, engine = _rig(tmp_path)
    out = actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    assert out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        e = uow.rsi.experiment("F2")
        assert e.registered_at == "2026-09-14" and len(e.frozen_hash) == 64
        assert [d.duty_id for d in uow.rsi.duties("F2")] == ["F2:f2-observation"]


def test_register_twice_is_refused_and_system_cannot_register(tmp_path):
    actions, _ = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    with pytest.raises(ValueError, match="已登记"):
        actions.register_experiment(RegisterExperimentRequest(
            doc=F2_DOC, idempotency_key="reg:F2:again", requested_at=T0, **HUMAN))
    denied = actions.register_experiment(RegisterExperimentRequest(
        doc={**F2_DOC, "exp_id": "F9"}, idempotency_key="reg:F9", requested_at=T0, **SYSTEM))
    assert denied.status is ActionStatus.REJECTED


def test_judgment_layer_deploy_eligible_is_refused_at_register(tmp_path):
    actions, _ = _rig(tmp_path)
    with pytest.raises(ValueError, match="judgment"):
        actions.register_experiment(RegisterExperimentRequest(
            doc={**F2_DOC, "tier": "deploy_eligible"}, idempotency_key="reg:bad",
            requested_at=T0, **HUMAN))


def test_amend_appends_but_refuses_to_touch_frozen_fields(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    ok = actions.amend_experiment(AmendExperimentRequest(
        exp_id="F2", what="F1c 窗改 26129 起", why="采集仪从未接上", rule_check="不改阈值",
        mechanism_note="改线=承诺，改赔率=微调", touches={}, idempotency_key="am:1",
        requested_at=T0, **HUMAN))
    assert ok.status is ActionStatus.COMMITTED
    with pytest.raises(ValueError, match="冻结"):
        actions.amend_experiment(AmendExperimentRequest(
            exp_id="F2", what="放宽阈值", why="差一点", rule_check="—", mechanism_note=None,
            touches={"falsifier": {"threshold_pp": 1.0}}, idempotency_key="am:2",
            requested_at=T0, **HUMAN))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.experiment("F2").falsifier["threshold_pp"] == 2.0   # 原件不变
        assert len(uow.rsi.amendments("F2")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.ontology.actions.rsi_actions'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/ontology/actions/rsi_actions.py
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
```

（`schedule_duties` / `fulfill_duty` / `grade_experiment` / `record_verdict` / `approve_deployment` 的方法体在 Task 5、6 里追加到同一个类；Task 4 只到这里。）

`nutmeg/ontology/wiring.py`：

```python
from nutmeg.ontology.actions.rsi_actions import RsiActions
...
    reliability_actions = ReliabilityActions(action_service)
    rsi_actions = RsiActions(action_service)
...
    return OntologyKernel(
        ...,
        reliability_actions=reliability_actions,
        rsi_actions=rsi_actions,
        ...
```

`nutmeg/ontology/kernel.py`：`__init__` 参数表在 `reliability_actions: ReliabilityActions,` 后加 `rsi_actions: RsiActions,`；赋值区加 `self.rsi_actions = rsi_actions`；顶部 import `from nutmeg.ontology.actions.rsi_actions import RsiActions`。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_actions.py tests/ontology/test_cli.py -v`
Expected: 4 passed（+ 既有 kernel 构造测试仍绿）

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/actions/rsi_actions.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py tests/ontology/test_rsi_actions.py
git add nutmeg/ontology/actions/rsi_actions.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py tests/ontology/test_rsi_actions.py
git commit -m "feat(rsi): register/amend Actions——原件全冻结，修正案碰判据即拒"
```

---

### Task 5: RsiActions —— schedule_duties / fulfill_duty（含 prospective 与 gap）

**Files:**
- Modify: `nutmeg/ontology/actions/rsi_actions.py`（`RsiActions` 类内追加两个方法）
- Test: `tests/ontology/test_rsi_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/ontology/test_rsi_actions.py
from nutmeg.ontology.actions.rsi_actions import FulfillDutyRequest, ScheduleDutiesRequest


def _registered(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    return actions, engine


def test_schedule_creates_one_instance_per_day_duty_and_is_idempotent(tmp_path):
    actions, engine = _registered(tmp_path)
    req = ScheduleDutiesRequest(day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00",
                                issue="26129", idempotency_key="sch:2026-09-19", requested_at=T0)
    assert actions.schedule_duties(req).status is ActionStatus.COMMITTED
    assert actions.schedule_duties(req).status is ActionStatus.COMMITTED   # 幂等重放
    with OntologyUnitOfWork(engine) as uow:
        pend = uow.rsi.pending_duty_instances(day="2026-09-19", now="2026-09-18T20:00:00+08:00")
        assert [(p.duty_id, p.issue, p.due_at) for p in pend] == [
            ("F2:f2-observation", "26129", "2026-09-19T00:30:00+08:00")]


def test_fulfill_marks_instance_and_writes_prospective_observation(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:1", requested_at=T0))
    out = actions.fulfill_duty(FulfillDutyRequest(
        exp_id="F2", duty_name="f2-observation", day="2026-09-19",
        artifact_path=".nutmeg-data/zucai/26129-f2-observation.json", artifact_bytes=b"{}",
        n_rows=10, population_stratum="zucai", judgment_tier_hist={"price_only": 10},
        captured_at=datetime(2026, 9, 18, 11, 22, 2, tzinfo=UTC),          # 19:22 北京
        earliest_kickoff="2026-09-19T00:30:00+08:00", idempotency_key="ful:1", requested_at=T0))
    assert out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        inst = uow.rsi.duty_instance("F2:f2-observation", "2026-09-19")
        assert inst.fulfilled_at is not None and len(inst.artifact_hash) == 64
        obs = uow.rsi.observation("F2:2026-09-19")
        assert obs.prospective is True and obs.n_rows == 10
        assert uow.rsi.gaps("F2", now="2026-09-20T00:00:00+08:00") == []


def test_late_artifact_is_recorded_as_not_prospective_and_the_day_stays_a_gap(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:1", requested_at=T0))
    actions.fulfill_duty(FulfillDutyRequest(
        exp_id="F2", duty_name="f2-observation", day="2026-09-19",
        artifact_path="x.json", artifact_bytes=b"{}", n_rows=10, population_stratum="zucai",
        judgment_tier_hist={"price_only": 10},
        captured_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),               # 01:00 北京，开球后
        earliest_kickoff="2026-09-19T00:30:00+08:00", idempotency_key="ful:late", requested_at=T0))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.observation("F2:2026-09-19").prospective is False
        # 前瞻窗过了不算：这一天仍是 gap
        assert uow.rsi.gaps("F2", now="2026-09-20T00:00:00+08:00") == ["2026-09-19"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_actions.py -v -k "schedule or fulfill or late"`
Expected: FAIL with `ImportError: cannot import name 'ScheduleDutiesRequest'`（dataclass 已在 Task 4 定义则为 `AttributeError: 'RsiActions' object has no attribute 'schedule_duties'`）

- [ ] **Step 3: Write minimal implementation**

追加到 `RsiActions` 类：

```python
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
                if duty.scope == "day":
                    targets = [("", request.earliest_kickoff)]
                else:
                    targets = list(request.match_kickoffs.items())
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
        captured = request.captured_at.isoformat(timespec="seconds")
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
            obs_id = f"{request.exp_id}:{request.day}" + (f":{request.match_id}" if request.match_id else "")
            if uow.rsi.observation(obs_id) is None:      # 同日二次 fulfill 不重复计数
                uow.rsi.insert_observation(ObservationRow(
                    observation_id=obs_id, exp_id=request.exp_id, day=request.day,
                    population_stratum=request.population_stratum, n_rows=request.n_rows,
                    captured_at=captured, prospective=prospective,
                    judgment_tier_hist=dict(request.judgment_tier_hist),
                    artifact_hash=artifact_hash))
            return (ObjectRef("rsi_observation", obs_id),)

        return self._svc.execute(command, handler)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_actions.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/actions/rsi_actions.py tests/ontology/test_rsi_actions.py
git add nutmeg/ontology/actions/rsi_actions.py tests/ontology/test_rsi_actions.py
git commit -m "feat(rsi): schedule/fulfill——义务按日实例化，赛后补的产物不算履行"
```

---

### Task 6: RsiActions —— grade_experiment / record_verdict / approve_deployment

**Files:**
- Modify: `nutmeg/ontology/actions/rsi_actions.py`
- Test: `tests/ontology/test_rsi_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/ontology/test_rsi_actions.py
from nutmeg.ontology.actions.rsi_actions import (
    ApproveDeploymentRequest,
    GradeExperimentRequest,
    RecordVerdictRequest,
)


def _grade(exp_id, key, *, mode, n, lo, hi, stratum="zucai", role=ActorRole.DETERMINISTIC_SYSTEM):
    return GradeExperimentRequest(
        exp_id=exp_id, mode=mode, stratum=stratum, n_cum=n, metric_value_pp=(lo + hi) / 2,
        ci_low_pp=lo, ci_high_pp=hi, cost_axis_pp=None, as_of_policy="earliest_kickoff",
        computed_by="tests@deadbeef", inputs_hash="i" * 64, actor_id="sys:rsi", actor_role=role,
        idempotency_key=key, requested_at=T0)


def test_verdict_refuses_before_n_min_and_ignores_replay_grades(tmp_path):
    actions, _ = _registered(tmp_path)
    actions.grade_experiment(_grade("F2", "g:replay", mode="replay", n=300, lo=5.0, hi=9.0))
    with pytest.raises(ValueError, match="prospective"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F2", idempotency_key="v:1", requested_at=T0, **SYSTEM))
    actions.grade_experiment(_grade("F2", "g:p1", mode="prospective", n=120, lo=1.0, hi=4.0))
    with pytest.raises(ValueError, match="差 20"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F2", idempotency_key="v:2", requested_at=T0, **SYSTEM))


def test_verdict_is_system_only_and_reads_the_ci_bound(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.grade_experiment(_grade("F2", "g:p", mode="prospective", n=140, lo=-3.0, hi=1.9))
    denied = actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:h", requested_at=T0, **HUMAN))
    assert denied.status is ActionStatus.REJECTED                     # 人不能替 falsifier 说话
    ok = actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:s", requested_at=T0, **SYSTEM))
    assert ok.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        v = uow.rsi.latest_verdict("F2")
        assert v.verdict == "falsified" and v.criterion_snapshot["threshold_pp"] == 2.0


def test_both_population_disagreeing_strata_make_pooled_inconclusive(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "F6", "population": "both",
           "falsifier": {**F2_DOC["falsifier"], "stratum": "pooled"}}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:F6", requested_at=T0, **HUMAN))
    actions.grade_experiment(_grade("F6", "g:z", mode="prospective", n=140, lo=3.0, hi=8.0, stratum="zucai"))
    actions.grade_experiment(_grade("F6", "g:j", mode="prospective", n=140, lo=-9.0, hi=-4.0, stratum="jczq"))
    actions.grade_experiment(_grade("F6", "g:p", mode="prospective", n=280, lo=2.5, hi=6.0, stratum="pooled"))
    actions.record_verdict(RecordVerdictRequest(exp_id="F6", idempotency_key="v:6", requested_at=T0, **SYSTEM))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.latest_verdict("F6").verdict == "inconclusive"   # 合并层看似 survived，被分层否决


def test_deploy_is_human_only_and_gated_by_layer_tier_and_verdict(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "S1", "layer": "structural", "tier": "deploy_eligible"}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:S1", requested_at=T0, **HUMAN))
    dep = lambda key, role, decision="deploy": ApproveDeploymentRequest(  # noqa: E731
        exp_id="S1", decision=decision, reason="C11 带定位已由前瞻窗证实", rule_id="C11",
        adjudication_ref=None, extend_to_exp_id=None, idempotency_key=key, requested_at=T0,
        actor_id="sys:rsi" if role is ActorRole.DETERMINISTIC_SYSTEM else "op:jun", actor_role=role)
    with pytest.raises(ValueError, match="survived"):                    # 没判决不能上线
        actions.approve_deployment(dep("d:0", ActorRole.JUDGE_OPERATOR))
    actions.grade_experiment(_grade("S1", "g:s", mode="prospective", n=140, lo=2.5, hi=9.0))
    actions.record_verdict(RecordVerdictRequest(exp_id="S1", idempotency_key="v:s1", requested_at=T0, **SYSTEM))
    assert actions.approve_deployment(dep("d:sys", ActorRole.DETERMINISTIC_SYSTEM)).status is ActionStatus.REJECTED
    assert actions.approve_deployment(dep("d:h", ActorRole.JUDGE_OPERATOR)).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.latest_deployment("S1").decision == "deploy"


def test_judgment_layer_survived_still_cannot_deploy(tmp_path):
    actions, _ = _registered(tmp_path)                       # F2 是 judgment 层 / observation 档
    actions.grade_experiment(_grade("F2", "g:f2", mode="prospective", n=140, lo=2.5, hi=9.0))
    actions.record_verdict(RecordVerdictRequest(exp_id="F2", idempotency_key="v:f2", requested_at=T0, **SYSTEM))
    with pytest.raises(ValueError, match="structural"):
        actions.approve_deployment(ApproveDeploymentRequest(
            exp_id="F2", decision="deploy", reason="想上", rule_id="C11", adjudication_ref=None,
            extend_to_exp_id=None, idempotency_key="d:f2", requested_at=T0, **HUMAN))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_actions.py -v -k "verdict or pooled or deploy"`
Expected: FAIL with `AttributeError: 'RsiActions' object has no attribute 'grade_experiment'`

- [ ] **Step 3: Write minimal implementation**

追加到 `RsiActions` 类：

```python
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
                raise ValueError(f"未到期：n_cum={primary.n_cum}，距 n_min 还差 {f.n_min - primary.n_cum}")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_actions.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/actions/rsi_actions.py tests/ontology/test_rsi_actions.py
git add nutmeg/ontology/actions/rsi_actions.py tests/ontology/test_rsi_actions.py
git commit -m "feat(rsi): grade/verdict/deploy——verdict 只读 prospective 与 CI 边界，deploy 只许人"
```

---

### Task 7: 登记原件加载与校验（`rsi_prereg.py`）

**Files:**
- Create: `nutmeg/decision/rsi_prereg.py`
- Test: `tests/decision/test_rsi_prereg.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_rsi_prereg.py
import json

import pytest

from nutmeg.decision.rsi_prereg import load_registry_doc, render_instrument

GOOD = {
    "exp_id": "F2", "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["a"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record", "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json"}],
}


def test_load_accepts_a_well_formed_doc(tmp_path):
    p = tmp_path / "F2.json"; p.write_text(json.dumps(GOOD), encoding="utf-8")
    doc = load_registry_doc(p)
    assert doc["exp_id"] == "F2" and doc["duties"][0]["name"] == "f2-observation"


@pytest.mark.parametrize("bad,msg", [
    ({"falsifier": {**GOOD["falsifier"], "bound": "point"}}, "bound"),
    ({"window": {}}, "window"),
    ({"registered_at": "9/14"}, "registered_at"),
    ({"duties": [{"name": "x", "scope": "day", "deadline_rule": "whenever",
                  "instrument": [], "artifact_glob": "y"}]}, "deadline_rule"),
    ({"duties": [{"name": "x", "scope": "day", "deadline_rule": "earliest_kickoff",
                  "instrument": ["python", "x.py"], "artifact_glob": "y"}]}, "instrument"),
])
def test_load_rejects_malformed_docs(tmp_path, bad, msg):
    p = tmp_path / "bad.json"; p.write_text(json.dumps({**GOOD, **bad}), encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        load_registry_doc(p)


def test_render_instrument_fills_placeholders():
    argv = render_instrument(["python", "x.py", "--issue", "{issue}", "--day", "{day}"],
                             issue="26129", day="2026-09-19")
    assert argv == ["python", "x.py", "--issue", "26129", "--day", "2026-09-19"]
    with pytest.raises(ValueError, match="issue"):
        render_instrument(["--issue", "{issue}"], issue=None, day="2026-09-19")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_rsi_prereg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.rsi_prereg'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/rsi_prereg.py
"""登记原件（experiments/registry/<exp_id>.json）的加载与校验。

原件由人手写，`nutmeg rsi register` 摄入一次；之后内核是唯一权威，原件只是登记时的
文本。这里只做结构校验——判据的语义（CI 怎么判）在 nutmeg.ontology.rsi.models。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nutmeg.ontology.rsi.models import Falsifier, JudgmentTier, Layer, Population, Tier

_REQUIRED = ("exp_id", "claim", "mechanism", "tier", "layer", "population", "min_tier",
             "window", "falsifier", "stop_rule", "quota_slot", "source_doc", "registered_at")
_DEADLINE_RULES = ("earliest_kickoff", "match_kickoff")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_registry_doc(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise ValueError(f"登记原件缺字段: {missing}")
    Tier(doc["tier"]); Layer(doc["layer"]); Population(doc["population"]); JudgmentTier(doc["min_tier"])
    Falsifier.from_dict(doc["falsifier"])
    w = doc["window"]
    if not isinstance(w, dict) or not ({"issue_from", "issue_to"} <= set(w)
                                       or {"date_from", "n_min"} <= set(w)):
        raise ValueError("window 必须是 {issue_from, issue_to} 或 {date_from, n_min[, date_to]}")
    if not _DATE.match(str(doc["registered_at"])):
        raise ValueError("registered_at 必须是 YYYY-MM-DD（原登记日，不是摄入日）")
    for d in doc.get("duties") or []:
        for k in ("name", "scope", "deadline_rule", "instrument", "artifact_glob"):
            if k not in d:
                raise ValueError(f"duty 缺字段 {k}")
        if d["deadline_rule"] not in _DEADLINE_RULES:
            raise ValueError(f"deadline_rule 必须是 {_DEADLINE_RULES}")
        if d["scope"] not in ("day", "match"):
            raise ValueError("duty.scope 必须是 day/match")
        if not d["instrument"] or not any("{issue}" in a or "{day}" in a for a in d["instrument"]):
            raise ValueError("instrument 必须含 {issue} 或 {day} 占位，否则每天跑的是同一条命令")
    return doc


def render_instrument(argv: list[str], *, issue: str | None, day: str) -> list[str]:
    out: list[str] = []
    for a in argv:
        if "{issue}" in a:
            if issue is None:
                raise ValueError("该 instrument 需要 issue，但当天没有足彩期")
            a = a.replace("{issue}", issue)
        out.append(a.replace("{day}", day))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_rsi_prereg.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/rsi_prereg.py tests/decision/test_rsi_prereg.py
git add nutmeg/decision/rsi_prereg.py tests/decision/test_rsi_prereg.py
git commit -m "feat(rsi): 登记原件加载与结构校验"
```

（Task 8–12 见 Part 3：F2 结账适配器与泄漏拒收、`rsi dream`、CLI、读侧、五份迁移、接线。）
