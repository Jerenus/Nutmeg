# Kernel 落库-报告对账 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 kernel-backed `decision-am --issue` 用 actions 表独立核验 Zucai prep 场数，杜绝 rejected snapshot 被写成成功 shadow 证据。

**Architecture:** ActionRepository 提供按 action type/status/idempotency prefix 的通用只读计数；ontology adapter 在 Zucai typed ingest 后查询本期 committed snapshot Action，并与 prep 同源 matches 数硬比较。失败仍由既有 `_compose` 转成可见 failed step 和 CLI 非零退出。

**Tech Stack:** Python 3.12、SQLAlchemy Core、typed Actions、pytest、Typer。

---

## 文件结构

- Modify `nutmeg/ontology/repository/actions.py`：增加 Action 审计计数查询。
- Create `tests/ontology/test_action_repository.py`：过滤器组合测试。
- Modify `nutmeg/decision/ontology_adapter.py`：本期 Zucai 三数对账。
- Modify `tests/decision/test_ontology_adapter.py`：正常、幂等、rejected 报警。
- Modify `docs/superpowers/plans/2026-08-28-kernel-report-reconciliation.md`：执行证据。

## Task 1: actions 真相层计数 API

**Files:**
- Create: `tests/ontology/test_action_repository.py`
- Modify: `nutmeg/ontology/repository/actions.py`

- [ ] **Step 1: 写失败测试**

用临时 kernel 的 `ActionRepository` 插入两个 committed `build_market_snapshot`（其中一个
幂等键属于 26111）、一个 rejected 同类型 Action 和一个 committed 其他类型 Action：

```python
def test_count_filters_action_truth_by_type_status_and_prefix(tmp_path):
    kernel = _kernel(tmp_path)
    with OntologyUnitOfWork(kernel.engine) as uow:
        _commit(uow.actions, "build_market_snapshot", "zucai:snapshot:26111:1:x")
        _commit(uow.actions, "build_market_snapshot", "zucai:snapshot:26112:1:x")
        _reject(uow.actions, "build_market_snapshot", "zucai:snapshot:26111:2:x")
        _commit(uow.actions, "record_match", "zucai:match:26111:1")
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.actions.count(
            action_type="build_market_snapshot",
            status=ActionStatus.COMMITTED,
            idempotency_prefix="zucai:snapshot:26111:",
        ) == 1
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `uv run pytest tests/ontology/test_action_repository.py -v`  
Expected: FAIL，`ActionRepository.count` 不存在。

- [ ] **Step 3: 最小实现**

在 `ActionRepository` 增加：

```python
def count(
    self,
    *,
    action_type: str | None = None,
    status: ActionStatus | None = None,
    idempotency_prefix: str | None = None,
) -> int:
    query = select(func.count()).select_from(schema.actions)
    if action_type is not None:
        query = query.where(schema.actions.c.action_type == action_type)
    if status is not None:
        query = query.where(schema.actions.c.status == status.value)
    if idempotency_prefix is not None:
        query = query.where(schema.actions.c.idempotency_key.startswith(idempotency_prefix))
    return self._connection.execute(query).scalar_one()
```

- [ ] **Step 4: 跑仓储测试确认 GREEN**

Run: `uv run pytest tests/ontology/test_action_repository.py -v`  
Expected: all tests pass。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/repository/actions.py tests/ontology/test_action_repository.py
git commit -m "feat(ontology): query scoped action truth counts"
```

## Task 2: 正常、幂等与 rejected Zucai 对账

**Files:**
- Modify: `tests/decision/test_ontology_adapter.py`
- Modify: `nutmeg/decision/ontology_adapter.py`

- [ ] **Step 1: 写正常、幂等和 rejected 失败测试**

扩展现有 `test_am_v2_with_issue_ingests_zucai`：

```python
assert (
    "kernel对账 Snapshot: actions落库 1 / prep报告 1 / service本次 1"
    in str(result)
)
```

再新增幂等重跑：第一次 ingest 后用同一期再跑，断言两次 result 都 succeeded，第二次输出
`actions落库 1 / prep报告 1 / service本次 0`。

同一 RED 中 monkeypatch `MarketActions.build_snapshot` 返回 `ActionStatus.REJECTED`：

```python
def test_am_v2_rejected_snapshot_fails_kernel_count_assertion(tmp_path, monkeypatch):
    from nutmeg.ontology.actions.market_actions import MarketActions
    from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus

    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    zucai_dir = tmp_path / "zucai"
    _write_zucai(zucai_dir)

    def rejected(_self, _request):
        return ActionOutcome(
            action_id="ACT-denied",
            action_type="build_market_snapshot",
            status=ActionStatus.REJECTED,
            error_code="permission_denied",
        )

    monkeypatch.setattr(MarketActions, "build_snapshot", rejected)
    result = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False, issue="26110", zucai_dir=zucai_dir
    )
    assert not result.succeeded
    assert "kernel_snapshot_count_mismatch" in str(result)
    assert "actions=0 prep=1 service=0" in str(result)
```

- [ ] **Step 2: 跑指定测试确认 RED**

Run: `uv run pytest tests/decision/test_ontology_adapter.py -v -k 'zucai or rejected_snapshot'`  
Expected: 正常/幂等测试因无对账输出 FAIL；rejected 测试因 result 仍 succeeded FAIL。

- [ ] **Step 3: 实现对账**

新增：

```python
class KernelCountMismatch(RuntimeError):
    pass


def _committed_zucai_snapshot_actions(kernel, issue: str) -> int:
    with OntologyUnitOfWork(kernel.engine) as uow:
        return uow.actions.count(
            action_type="build_market_snapshot",
            status=ActionStatus.COMMITTED,
            idempotency_prefix=f"zucai:snapshot:{issue}:",
        )
```

`_ingest_zucai_issue` 保存 `rows` tuple，service ingest 后取 `prep_count=len(rows)` 与 Action
计数。两者不等时抛稳定 `kernel_snapshot_count_mismatch`；相等时把三数对账追加到现有
message。service 本次数只诊断，不参与硬判据，以支持 first-anchor 幂等重跑。

- [ ] **Step 4: 跑 adapter 测试确认 GREEN**

Run: `uv run pytest tests/decision/test_ontology_adapter.py -v`  
Expected: all tests pass；rejected step failed 且稳定错误可见。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/ontology_adapter.py tests/decision/test_ontology_adapter.py
git commit -m "feat(decision): reconcile zucai reports with action truth"
```

## Task 3: 完成门与真实源回放

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-kernel-report-reconciliation.md`

- [ ] **Step 1: cherry-pick schema 15 共享测试修复**

Run: `git cherry-pick 5c68f09`  
Expected: 当前分支获得 reliability 动态 schema 期望，避免无关全量失败。

- [ ] **Step 2: 静态检查与全量测试**

Run: `uv run ruff check .`  
Run: `uv run pytest -q`  
Expected: 0 failed。

- [ ] **Step 3: 真实 26111 源复制到临时目录**

把生产 `26111-issue.json`、`26111-odds.json` 只读复制到 `mktemp -d` 的 Zucai 目录，
使用临时 `AppSettings(data_dir=...)` kernel 调 `run_decision_am_v2(..., issue="26111")`。
Expected: 输出 `actions落库 14 / prep报告 14`，临时 actions 表 committed snapshot 计数 14；
不写生产 ontology。

- [ ] **Step 4: 计划勾选、记录证据并提交**

```bash
git add docs/superpowers/plans/2026-08-28-kernel-report-reconciliation.md
git commit -m "docs(plan): record kernel reconciliation verification"
```

## 显式排除

- 不修改生产 ontology，不补写历史 rejected Action。
- 不改权限、重试或修复策略；本包只做查询、计数、断言和退出码。
- 不改变 prep 的判读空白区，不生成票面或概率判断。
- 不对 legacy JSONL 路径伪造 actions 对账。
