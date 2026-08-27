# rx 对象化 + 记分牌影子对账 实施计划（脊柱工程）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日期：2026-08-27 ｜ 上位设计：`docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md` §6/§9、`docs/superpowers/plans/2026-08-23-memory-ontology-sop-redesign.md` §3

**Goal:** 让 rx 里的 Prediction/Adjudication 散文进入本体内核成为 typed 对象，并让记分牌进入 M5 影子对账期——消灭"falsifier 手工执行、scoreboard.json 手改"这最后一类未对象化执行知识。

**Architecture:** 第一性原理诊断：M1-M6 已交付全部机器（五张 workflow 表、WorkflowActions、scoreboard observe/shadow/cutover 治理命令），但生产库五张表 0 行——缺的是**操作闭环接线**，不是新机器。本计划三段：①迁移 15 把 Prediction 从 match 强绑定放宽为 subject 化（rx 的 P1/P4/P5 是期级预测，M1 的 match_id NOT NULL 外键与真实用法不符）+ 新增 grade_prediction 动作（判定判断留主循环，记账走 typed Action）；②纯函数 rx→请求映射 + `nutmeg workflow` CLI 薄壳；③RUNBOOK 挂接 + 26111 生产回填 + 首次 shadow review。权威切换（M5 步骤 4-6）是用户行权门，**明确排除**。

**Tech Stack:** SQLAlchemy Core + SQLite（`nutmeg/ontology/repository/`，迁移仿 v9 guarded_alter/v10 风格）/ typer CLI（仿 `interfaces/cli/scoreboard.py`）/ pytest（`uv run pytest`，夹具仿 `tests/ontology/test_workflow_actions.py` 的 `_setup`）。

---

## §0 映射契约（先于代码锁定）

**Prediction（rx `predictions[]` → `register_prediction`）**
- 一律 `subject_type='issue'`, `subject_id=<期号>`, `match_id=None`（P2/P3 虽点名单场，但其 falsifier 兑现对象是期级记分牌线；match 级预测留给未来泳道身份统一后使用）。
- `claim`/`falsifier` 原文入库；`idempotency_key=f"rx:{issue}:{P-id}"`。
- 判定：`grade_prediction`，outcome ∈ {hit, miss, na}；判断（falsifier 是否触发）由主循环做，动作只记账；仅 judge_operator 可执行（spec：AI 不得自评）。

**Adjudication（rx `pending_adjudications[]` → `record_adjudication`）**
- 只录**已决**条目：status 含「已裁」「行权」「已复核」「终版」「已定」之一；「需你裁」「待18:30」「已交用户」属未决，跳过并逐条报告。
- `decision`：status 含「行权」→ `override`，否则 → `approve`；`subject_type='issue'`, `subject_id=<期号>`；`reason = q + "｜" + (reason or evidence_rejected)`；`evidence_rejected` 字段存在则转 `[{"type":"note","id":...}]` 形式；`alternative = {"options": options}`（存在时）。
- `idempotency_key=f"rx:{issue}:{ADJ-id}"`。

**双轨纪律（影子期）**：切换批准前 `scoreboard.json` 仍是唯一权威（宪法不变）；每次手改后必须镜像一条 `nutmeg scoreboard observe`（带 `--acknowledge-manual-source`），`nutmeg scoreboard shadow` 逐期对账攒证据。无声双权威被 M5 明令禁止——RUNBOOK 挂接把这条写死。

---

### Task 1: 迁移 15 `prediction_subjects` —— Prediction subject 化 + grade 权限

**Files:**
- Modify: `nutmeg/ontology/repository/schema_workflow.py:43-60`（predictions 表）
- Modify: `nutmeg/ontology/workflow/models.py`（PredictionRow）
- Modify: `nutmeg/ontology/repository/workflow.py`（insert/get prediction）
- Modify: `nutmeg/ontology/repository/migrations.py`（新 apply 函数 + MIGRATIONS v15）
- Modify: `tests/ontology/test_workflow_actions.py`（既有 RegisterPredictionRequest 用法同步）
- Test: `tests/ontology/test_prediction_subjects.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.workflow.models import PredictionRow, PredictionStatus

AT = "2026-08-27T10:00:00+00:00"


def _engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_issue_scoped_prediction_row_roundtrip(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.workflow.insert_prediction(PredictionRow(
            prediction_id="pred-1", match_id=None,
            subject_type="issue", subject_id="26111",
            claim="悬置持平4场至少2平", falsifier="≤1场平→o条降级",
            status=PredictionStatus.REGISTERED, outcome=None,
            registered_at=AT, settled_at=None,
        ))
        row = uow.workflow.get_prediction("pred-1")
    assert row.subject_type == "issue" and row.subject_id == "26111"
    assert row.match_id is None


def test_migration_15_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run_migrations(engine)          # 二跑无 drift、无异常
    with engine.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(predictions)")}
    assert {"subject_type", "subject_id", "match_id"} <= cols


def test_grade_permission_granted_to_judge_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT actor_role FROM action_permissions WHERE action_type='grade_prediction'"
        ).fetchall()
    assert {r[0] for r in rows} == {"judge_operator"}
```

（PredictionRow 字段顺序以 `workflow/models.py` 现文件为准，新增 `subject_type: str`、`subject_id: str`，`match_id` 放宽为 `str | None`；PredictionStatus 枚举值沿用现文件，不新增。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/ontology/test_prediction_subjects.py -v`
Expected: FAIL（TypeError: unexpected keyword 'subject_type' 或列不存在）

- [ ] **Step 3: 实现**

`schema_workflow.py` predictions 表改为：

```python
predictions = Table(
    "predictions",
    metadata,
    Column("prediction_id", Text, primary_key=True),
    Column(
        "match_id",
        Text,
        ForeignKey("matches.match_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    ),
    Column("subject_type", Text, nullable=False, index=True),
    Column("subject_id", Text, nullable=False, index=True),
    Column("claim", Text, nullable=False),
    Column("falsifier", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("outcome", Text, nullable=True),
    Column("registered_at", Text, nullable=False),
    Column("settled_at", Text, nullable=True),
)
```

`migrations.py` 追加（位置仿 `_apply_reliability_governance` 之后）：

```python
_PREDICTION_GRADE_PERMISSIONS = (
    ('grade_prediction', 'judge_operator'),
)


def _apply_prediction_subjects(connection: Connection) -> None:
    cols = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(predictions)')}
    if 'subject_type' not in cols:
        # SQLite 放宽 NOT NULL 需重建表（12-step 简化版；v14 前生产表为空或极小）
        connection.exec_driver_sql('ALTER TABLE predictions RENAME TO predictions_v14')
        schema_workflow.predictions.create(connection)
        connection.exec_driver_sql(
            'INSERT INTO predictions (prediction_id, match_id, subject_type, subject_id,'
            ' claim, falsifier, status, outcome, registered_at, settled_at)'
            " SELECT prediction_id, match_id, 'match', match_id,"
            ' claim, falsifier, status, outcome, registered_at, settled_at'
            ' FROM predictions_v14'
        )
        connection.exec_driver_sql('DROP TABLE predictions_v14')
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _PREDICTION_GRADE_PERMISSIONS
        ],
    )
```

MIGRATIONS 元组追加：

```python
    Migration(
        version=15,
        name='prediction_subjects',
        fingerprint='predictions+subject_type+subject_id+match_nullable+grade_permission',
        apply=_apply_prediction_subjects,
    ),
```

注意两点（执行者必查）：① 迁移在 v10 已建新版表的全新库上也会跑——PRAGMA 守卫使重建段跳过、只插权限；权限插入需与守卫同侧防重复：把 `insert(action_permissions)` 也放进 `if` 内会漏掉全新库，正确做法是权限插入前查 `SELECT COUNT(*) FROM action_permissions WHERE action_type='grade_prediction'` 为 0 才插。② 重建段执行时若 SQLite 外键约束报错，参考仓内 v9 `_apply_finance_entry_odds` 的守卫写法处理。

`workflow/models.py` PredictionRow 加 `subject_type: str`、`subject_id: str`，`match_id: str | None`；`repository/workflow.py` 的 `insert_prediction` values 与 `get_prediction` 构造同步加两字段（照 adjudication 方法的既有风格）。`tests/ontology/test_workflow_actions.py` 中既有 `RegisterPredictionRequest(...)` 调用点先不动——Task 2 才改请求类；本 task 若因 Row 构造报错，同步补 `subject_type='match', subject_id=<match_id>`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/ontology/test_prediction_subjects.py tests/ontology/test_workflow_actions.py tests/migration/ -v`
Expected: 全部 passed（既有测试不回归）

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/repository/schema_workflow.py nutmeg/ontology/repository/migrations.py \
  nutmeg/ontology/workflow/models.py nutmeg/ontology/repository/workflow.py \
  tests/ontology/test_prediction_subjects.py tests/ontology/test_workflow_actions.py
git commit -m "feat(ontology): 迁移15 prediction subject化 + grade权限"
```

### Task 2: RegisterPredictionRequest subject 化 + grade_prediction 动作

**Files:**
- Modify: `nutmeg/ontology/actions/workflow_actions.py`
- Modify: `nutmeg/ontology/repository/workflow.py`（新增 `update_prediction_outcome`）
- Modify: `tests/ontology/test_workflow_actions.py`（既有 register 用法补 subject 字段）
- Test: `tests/ontology/test_prediction_subjects.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 test_prediction_subjects.py）**

```python
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RegisterPredictionRequest,
    WorkflowActions,
)

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


def _actions(tmp_path: Path):
    engine = _engine(tmp_path)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    return WorkflowActions(service), engine


def test_register_issue_prediction_and_grade(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    reg = actions.register_prediction(RegisterPredictionRequest(
        match_id=None, subject_type="issue", subject_id="26111",
        claim="悬置持平4场至少2平", falsifier="≤1场平→o条降级",
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="rx:26111:P1", requested_at=NOW,
    ))
    assert reg.status is ActionStatus.COMMITTED
    pred_id = reg.result_refs[0].object_id
    graded = actions.grade_prediction(GradePredictionRequest(
        prediction_id=pred_id, outcome="miss",
        reason="夜二仅1平(3胜/4负/5平/6胜),falsifier触发",
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="rx:26111:P1:grade", requested_at=NOW,
    ))
    assert graded.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_prediction(pred_id)
    assert row.outcome == "miss" and row.settled_at is not None


def test_ai_cannot_grade(tmp_path: Path) -> None:
    actions, _ = _actions(tmp_path)
    reg = actions.register_prediction(RegisterPredictionRequest(
        match_id=None, subject_type="issue", subject_id="26111",
        claim="c", falsifier="f",
        actor_id="ai:claude", actor_role=ActorRole.AI_ANALYST,
        idempotency_key="rx:26111:Px", requested_at=NOW,
    ))
    out = actions.grade_prediction(GradePredictionRequest(
        prediction_id=reg.result_refs[0].object_id, outcome="hit", reason="r",
        actor_id="ai:claude", actor_role=ActorRole.AI_ANALYST,
        idempotency_key="rx:26111:Px:grade", requested_at=NOW,
    ))
    assert out.status is not ActionStatus.COMMITTED   # 权限拒绝


def test_grade_twice_is_rejected(tmp_path: Path) -> None:
    actions, _ = _actions(tmp_path)
    reg = actions.register_prediction(RegisterPredictionRequest(
        match_id=None, subject_type="issue", subject_id="26111",
        claim="c", falsifier="f",
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="rx:26111:Py", requested_at=NOW,
    ))
    pid = reg.result_refs[0].object_id
    first = actions.grade_prediction(GradePredictionRequest(
        prediction_id=pid, outcome="hit", reason="r",
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=f"grade:{pid}:1", requested_at=NOW,
    ))
    assert first.status is ActionStatus.COMMITTED
    second = actions.grade_prediction(GradePredictionRequest(
        prediction_id=pid, outcome="miss", reason="改判",
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=f"grade:{pid}:2", requested_at=NOW,
    ))
    assert second.status is not ActionStatus.COMMITTED  # 已判定不可重判
```

（ActionStatus/错误路径的具体枚举值以 `actions/models.py` 现文件为准；若权限拒绝走异常而非 status，断言按既有 `test_ai_cannot_record_operator_adjudication` 的写法改。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/ontology/test_prediction_subjects.py -v -k "grade or issue_prediction"`
Expected: FAIL（ImportError: GradePredictionRequest）

- [ ] **Step 3: 实现**

`RegisterPredictionRequest` 增加字段与校验：

```python
@dataclass(frozen=True, slots=True)
class RegisterPredictionRequest:
    match_id: str | None
    subject_type: str
    subject_id: str
    claim: str
    falsifier: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)
        if self.subject_type not in ('match', 'issue'):
            raise ValueError('subject_type must be match or issue')
        if self.subject_type == 'match' and self.match_id != self.subject_id:
            raise ValueError('match-scoped prediction requires subject_id == match_id')
        if self.subject_type == 'issue' and self.match_id is not None:
            raise ValueError('issue-scoped prediction must not carry match_id')
```

```python
@dataclass(frozen=True, slots=True)
class GradePredictionRequest:
    prediction_id: str
    outcome: str
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)
        if self.outcome not in ('hit', 'miss', 'na'):
            raise ValueError('outcome must be hit, miss, or na')
        if not self.reason.strip():
            raise ValueError('grade reason is required')
```

（`result_refs[0].object_id` 的属性名以 `actions/models.py` 的 ObjectRef 现定义为准，拼法不同则按现文件改断言。）

`WorkflowActions.grade_prediction` 仿 `record_adjudication` 的既有骨架：action_type `'grade_prediction'`，handler 内 `uow.workflow.get_prediction` → 校验 `outcome is None`（否则 raise 域错误，按该文件既有错误上抛方式）→ `uow.workflow.update_prediction_outcome(prediction_id, outcome, reason, settled_at=request.requested_at.isoformat())`。`register_prediction` handler 的 PredictionRow 构造补 subject 两字段。`repository/workflow.py` 新增：

```python
    def update_prediction_outcome(
        self, prediction_id: str, outcome: str, reason: str, settled_at: str
    ) -> None:
        sw = schema_workflow
        self._connection.execute(
            update(sw.predictions)
            .where(sw.predictions.c.prediction_id == prediction_id)
            .values(status='settled', outcome=outcome, settled_at=settled_at)
        )
```

（`update` 从 sqlalchemy 导入；status 值 'settled' 若 PredictionStatus 枚举拼法不同，以枚举为准。reason 落在 Action 审计记录里而非行上——typed Action 本身带 payload。既有 `test_workflow_actions.py` 中 register 用法补 `subject_type='match', subject_id=<同 match_id>`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/ontology/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/workflow_actions.py nutmeg/ontology/repository/workflow.py \
  tests/ontology/test_prediction_subjects.py tests/ontology/test_workflow_actions.py
git commit -m "feat(ontology): register_prediction subject化 + grade_prediction 动作"
```

### Task 3: rx→请求 纯函数映射

**Files:**
- Create: `nutmeg/decision/rx_ingest.py`
- Test: `tests/decision/test_rx_ingest.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions

RX = {
    "issue": "26111",
    "predictions": [
        {"id": "P1", "claim": "悬置持平4场至少2平", "falsifier": "≤1场平→o条降级"},
        {"id": "P2", "claim": "皇马不至于输球", "falsifier": "皇社客胜→0/9追加"},
    ],
    "pending_adjudications": [
        {"id": "ADJ-2", "status": "我已裁", "q": "场9借场不挂旗", "reason": "单向削弱"},
        {"id": "ADJ-8", "status": "用户行权(大胆SFC≤600)", "q": "SFC486九胆",
         "evidence_rejected": "五条裸胆违审计"},
        {"id": "ADJ-1", "status": "需你裁", "q": "场3裸单 vs o条"},
    ],
}


def test_map_predictions_are_issue_scoped():
    reqs = map_rx_predictions(RX, "26111")
    assert len(reqs) == 2
    assert reqs[0]["subject_type"] == "issue" and reqs[0]["subject_id"] == "26111"
    assert reqs[0]["match_id"] is None
    assert reqs[0]["idempotency_key"] == "rx:26111:P1"
    assert reqs[0]["claim"] == "悬置持平4场至少2平"


def test_map_adjudications_resolved_only():
    reqs, skipped = map_rx_adjudications(RX, "26111")
    assert [r["idempotency_key"] for r in reqs] == ["rx:26111:ADJ-2", "rx:26111:ADJ-8"]
    assert reqs[0]["decision"] == "approve"
    assert reqs[1]["decision"] == "override"
    assert reqs[1]["evidence_rejected"] == [{"type": "note", "id": "五条裸胆违审计"}]
    assert skipped == ["ADJ-1: 未决(需你裁)"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_rx_ingest.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
"""rx JSON → workflow 请求的确定性映射。判断不入脚本:只做字段搬运与已决/未决分拣。"""
from __future__ import annotations

_RESOLVED_MARKS = ("已裁", "行权", "已复核", "终版", "已定")


def map_rx_predictions(rx: dict, issue: str) -> list[dict]:
    out = []
    for p in rx.get("predictions") or []:
        out.append({
            "match_id": None,
            "subject_type": "issue",
            "subject_id": issue,
            "claim": p["claim"],
            "falsifier": p["falsifier"],
            "idempotency_key": f"rx:{issue}:{p['id']}",
        })
    return out


def map_rx_adjudications(rx: dict, issue: str) -> tuple[list[dict], list[str]]:
    out, skipped = [], []
    for a in rx.get("pending_adjudications") or []:
        status = a.get("status", "")
        if not any(m in status for m in _RESOLVED_MARKS):
            skipped.append(f"{a['id']}: 未决({status})")
            continue
        reason = "｜".join(x for x in (a.get("q"), a.get("reason")) if x)
        rejected = a.get("evidence_rejected")
        out.append({
            "subject_type": "issue",
            "subject_id": issue,
            "decision": "override" if "行权" in status else "approve",
            "reason": reason,
            "evidence_rejected": [{"type": "note", "id": rejected}] if rejected else [],
            "alternative": {"options": a["options"]} if a.get("options") else {},
            "idempotency_key": f"rx:{issue}:{a['id']}",
        })
    return out, skipped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_rx_ingest.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/rx_ingest.py tests/decision/test_rx_ingest.py
git commit -m "feat(decision): rx→workflow 请求纯函数映射"
```

### Task 4: `nutmeg workflow` CLI（register-rx / grade-prediction）

**Files:**
- Create: `nutmeg/interfaces/cli/workflow.py`（仿 `cli/scoreboard.py` 的 `_kernel`/`_emit`/`_fail` 骨架）
- Modify: `nutmeg/interfaces/cli/__init__.py`（尾部 import 行，仿 `scoreboard` 在 926 行的注册方式）

- [ ] **Step 1: 实现命令**

```python
"""Workflow object ingestion: rx 散文 → typed Actions."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
)

workflow_app = _cli.typer.Typer(help="rx 对象化与预测判定")
_cli.app.add_typer(workflow_app, name="workflow")

_DATA_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data/ontology").parent, "--data-dir")


def _kernel(data_dir: Path):
    resolved = Path(data_dir).expanduser().resolve()
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=resolved))
    return kernel


def _now() -> datetime:
    return datetime.now(UTC)


@workflow_app.command("register-rx")
def register_rx(
    rx_file: Path = _cli.typer.Option(..., "--rx-file"),
    issue: str = _cli.typer.Option(..., "--issue"),
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """把 rx 的 predictions/已决 adjudications 批量注册进本体(幂等,未决跳过)。"""
    kernel = _kernel(data_dir)
    rx = json.loads(rx_file.read_text("utf-8"))
    now = _now()
    for req in map_rx_predictions(rx, issue):
        outcome = kernel.workflow.register_prediction(RegisterPredictionRequest(
            **req, actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR, requested_at=now,
        ))
        _cli.typer.echo(f"{req['idempotency_key']}: {outcome.status.value}")
    adjs, skipped = map_rx_adjudications(rx, issue)
    for req in adjs:
        outcome = kernel.workflow.record_adjudication(RecordAdjudicationRequest(
            **req, supersedes_adjudication_id=None, actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR, requested_at=now,
        ))
        _cli.typer.echo(f"{req['idempotency_key']}: {outcome.status.value}")
    for line in skipped:
        _cli.typer.echo(f"跳过 {line}")


@workflow_app.command("grade-prediction")
def grade_prediction(
    prediction_id: str = _cli.typer.Option(..., "--prediction-id"),
    outcome: str = _cli.typer.Option(..., "--outcome", help="hit|miss|na"),
    reason: str = _cli.typer.Option(..., "--reason"),
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """判定一条预注册预测(判断在主循环,此处只记账)。"""
    kernel = _kernel(data_dir)
    result = kernel.workflow.grade_prediction(GradePredictionRequest(
        prediction_id=prediction_id, outcome=outcome, reason=reason,
        actor_id="operator:jun", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=f"grade:{prediction_id}",
        requested_at=_now(),
    ))
    _cli.typer.echo(f"{prediction_id}: {result.status.value}")
```

（`--data-dir` 默认值按 `cli/scoreboard.py` 若为必选则同样必选，保持一致；`build_ontology_kernel` 的守卫（initialized/integrity/pending_migrations）照 scoreboard 的 `_kernel` 抄——迁移未跑时应显式失败而非自动迁移，生产迁移在 Task 6 显式执行。）

- [ ] **Step 2: 冒烟**

Run: `uv run nutmeg workflow --help && uv run nutmeg workflow register-rx --help`
Expected: 两级 help 正常渲染

- [ ] **Step 3: Commit**

```bash
git add nutmeg/interfaces/cli/workflow.py nutmeg/interfaces/cli/__init__.py
git commit -m "feat(cli): nutmeg workflow register-rx / grade-prediction"
```

### Task 5: RUNBOOK 双轨挂接

**Files:**
- Modify: `docs/sop/RUNBOOK.md`

- [ ] **Step 1: B7 行尾追加**

`；落盘后 uv run nutmeg workflow register-rx --rx-file <issue>-rx.json --issue <issue>（幂等，可裁决后重跑补录）`

- [ ] **Step 2: B10 行尾追加**

`；预测判定 workflow grade-prediction 逐条记账；scoreboard.json 每处手改镜像一条 nutmeg scoreboard observe（影子期双轨：JSON 仍权威，无镜像=违 M5）；期末 nutmeg scoreboard shadow 对账入证据`

- [ ] **Step 3: Commit**

```bash
git add docs/sop/RUNBOOK.md
git commit -m "docs(sop): RUNBOOK B7/B10 rx对象化与记分牌双轨挂接"
```

### Task 6: 生产迁移 + 26111 回填 + 首次 shadow review（**主循环亲自执行，不派 subagent**）

- [ ] **Step 1: 备份生产库**

Run: `cp .nutmeg-data/ontology/ontology.db .nutmeg-data/archive/ontology-pre-v15-$(date +%Y%m%d).db`

- [ ] **Step 2: 显式迁移生产库到 v15**

Run: `uv run nutmeg scoreboard status --data-dir .nutmeg-data`（内核构建即自动跑迁移，v9→14 先例）
Expected: 输出 targets 正常、无 pending migrations；异常则从 Step 1 备份回滚

- [ ] **Step 3: 回填 26111**

Run: `uv run nutmeg workflow register-rx --rx-file .nutmeg-data/zucai/26111-rx.json --issue 26111`
Expected: P1-P5 五条 committed；ADJ 已决条 committed、未决条逐条跳过报告

- [ ] **Step 4: 判定已决预测**（P1 miss/P2 hit，reason 引 rx night2 块；其余待夜三与开奖）

- [ ] **Step 5: 镜像本周两次 scoreboard 手改**（o条降级、updated_at）为两条 `nutmeg scoreboard observe`，然后 `nutmeg scoreboard shadow` 跑首次对账、`nutmeg scoreboard status` 留档

- [ ] **Step 6: 验证幂等后收尾**（register-rx 重跑应全 idempotent-hit；结果与 shadow 输出摘要写入当期 retro）

## 显式排除

- **权威切换**（`scoreboard cutover`）：用户行权门，M5 步骤 4-6，本计划只把影子期跑起来；
- FlagInstance/PrecedentLink 回填：需 match_id 解析，等两泳道身份统一（26111 待办 6）后补；
- 预测自动判定：falsifier 是否触发是判断，永在主循环；
- Telegram/驾驶舱：Package 2/4 范围。
