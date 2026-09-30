# 判断唯一事实 P0–P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 内核 `forecast_revisions` 装下一条 Read 的全部内容（表态/旗/档/备注），`nutmeg judgment project` 能从内核投影出与 `reads.json` 同形的列表并逐条比对；主循环改判立刻变成一条 `kind=override` 的新 revision。

**Architecture:** 迁移 v47 给 `forecast_revisions` 加 `kind / board_key / judgment_json` 三列（PRAGMA 守卫的 ALTER，Table 定义同步）；`decision-read` 把整条 Read 存进 `judgment_json`；`build_jczq_reads` / `build_auto_reads` 在 Read 里显式写 `kind / board_key / code`；新模块 `judgment_projection` 按 `board_key` 取每个序列的最高 revision 投影回列表并与文件比对；`research refresh` 每次刷新后落 `judgment-projection.json`；`research override` 记账后立刻 refresh。spec：`docs/superpowers/specs/2026-10-01-single-judgment-truth-design.md`（§2 表里的 `belief-v2.json` 经勘察无人读写，本计划不碰；plan frontier 实读 legs-base `fair`）。

**Tech Stack:** Python 3.13, SQLAlchemy Core (SQLite), typer, pytest；`uv run` 跑一切。

**Spec 修正（勘察 2026-10-01 01:40）**：内核现无 kind/note/stance 列；jczq Read 以 draft 入库（`ai:jczq-analyst`），足彩以 committed 入库（`judge:owner`）；`belief-v2.json` 无代码读写。P2–P4 在 P0 比对跑满一周（≥ 2026-10-08）后再出计划。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `nutmeg/ontology/repository/schema_decision.py` | `forecast_revisions` Table 加三列 |
| `nutmeg/ontology/repository/migrations.py` | v47 `forecast_judgment_payload`（守卫 ALTER + 索引） |
| `nutmeg/ontology/repository/decision.py` | `ForecastRevisionRow` 三个默认字段；`insert_revision/_to_revision` 读写；`iter_board_revisions(board_key)` |
| `nutmeg/ontology/actions/forecast_actions.py` | 请求类三个默认字段；draft 记 `supersedes`=序列最新 revision；`_revision_row` 透传 |
| `nutmeg/decision/ontology_adapter.py` | `run_decision_read_v2` 透传 `kind/board_key/judgment=payload` |
| `nutmeg/decision/jczq_reads.py` | Read 加 `kind/board_key/code`；有改判账 → `kind=override` |
| `nutmeg/decision/zucai_auto_judgment.py` | 足彩 Read 加 `kind/board_key/code` |
| `nutmeg/decision/judgment_projection.py` (新) | `project_board / compare / write_report` |
| `nutmeg/interfaces/cli/judgment.py` (新) + `nutmeg/interfaces/cli/__init__.py` | `nutmeg judgment project` |
| `nutmeg/decision/pool.py` | `refresh_day` 末尾写投影比对 |
| `nutmeg/interfaces/cli/research.py` | override 后 `_refresh`；refresh 打印投影行 |
| tests | `tests/ontology/test_forecast_judgment_payload.py`(新)、`tests/decision/test_judgment_projection.py`(新)、既有 `test_migrations.py / test_read_adapter.py / test_jczq_reads.py / test_zucai_auto_judgment.py / test_pool.py` 增改 |

---

### Task 1: 迁移 v47 + Row/Repository 三列

**Files:**
- Modify: `nutmeg/ontology/repository/schema_decision.py:76-105`
- Modify: `nutmeg/ontology/repository/migrations.py`（`MIGRATIONS` 末尾 + 新函数）
- Modify: `nutmeg/ontology/repository/decision.py:47-69, 157-182, 199-215, 414-437`
- Modify: `tests/ontology/test_migrations.py:63`
- Test: `tests/ontology/test_forecast_judgment_payload.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ontology/test_forecast_judgment_payload.py
from pathlib import Path

from sqlalchemy import inspect

from nutmeg.ontology.repository.engine import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.decision import DecisionRepository, ForecastRevisionRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_v47_adds_judgment_payload_columns(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version == 47
    columns = {c["name"] for c in inspect(engine).get_columns("forecast_revisions")}
    assert {"kind", "board_key", "judgment_json"} <= columns


def _row(series_id: str, no: int, **extra) -> ForecastRevisionRow:
    return ForecastRevisionRow(
        forecast_revision_id=f"fr-{no}", forecast_series_id=series_id, decision_session_id=None,
        revision_no=no, status="draft", made_at="2026-10-01T10:00:00+08:00",
        information_cutoff_at=None, prior_snapshot_id=None,
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief_distribution={"home": 0.6, "draw": 0.25, "away": 0.15},
        evidence_bundle_id=None, falsifier=None, actor_id="ai:jczq-analyst", model_name=None,
        model_version=None, policy_version="governance-v1", commitment_tier="lean",
        evidence_coverage=None, evidence_quality=None, forecast_stability=None,
        supersedes_revision_id=None, **extra)


def test_board_revisions_round_trip_payload(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-a", "md-had")
        uow.decision.insert_revision(_row(series, 1, kind="research", board_key="jczq:2026-10-01",
                                          judgment={"read_id": "R-1", "code": "周四001"}))
        uow.decision.insert_revision(_row(series, 2, kind="override", board_key="jczq:2026-10-01",
                                          judgment={"read_id": "R-2", "code": "周四001"}))
        other = uow.decision.ensure_series("match-b", "md-had")
        uow.decision.insert_revision(_row(other, 1, kind="market", board_key="jczq:2026-10-02"))
        uow.commit()
    with OntologyUnitOfWork(engine) as uow:
        rows = list(uow.decision.iter_board_revisions("jczq:2026-10-01"))
    assert [(r.revision_no, r.kind, r.judgment["read_id"]) for r in rows] == [
        (1, "research", "R-1"), (2, "override", "R-2")]
    assert rows[0].board_key == "jczq:2026-10-01"
```

（`OntologyUnitOfWork` 的用法以 `tests/ontology/test_decision_repository.py` 为准，若它不是上下文管理器则照那里的写法改。）

- [ ] **Step 2: 跑测试确认失败**：`uv run pytest tests/ontology/test_forecast_judgment_payload.py -q` → FAIL（版本 46 / 无列）。

- [ ] **Step 3: 实现**

`schema_decision.py` 在 `supersedes_revision_id` 后加：
```python
    Column('kind', Text, nullable=True),            # research|override|market|manual|migration
    Column('board_key', Text, nullable=True, index=True),  # jczq:<day> | zucai:<issue>
    Column('judgment_json', Text, nullable=True),   # 提交时的整条 Read（投影源）
```

`migrations.py` 新函数 + 注册 v47：
```python
def _apply_forecast_judgment_payload(connection: Connection) -> None:
    """判断唯一事实 P0（2026-10-01）：revision 装下整条 Read。

    ``kind`` 记这条判断是研究转录/主循环改判/市场锚定/人工；``board_key`` 记它属于哪块板
    （``jczq:<日>`` / ``zucai:<期>``），投影按它取；``judgment_json`` 是提交时的整条 Read。
    新库由 Table 定义直接带列，这里只补旧库。
    """
    columns = {row[1] for row in connection.exec_driver_sql(
        'PRAGMA table_info(forecast_revisions)').fetchall()}
    for name, ddl in (("kind", "TEXT"), ("board_key", "TEXT"), ("judgment_json", "TEXT")):
        if name not in columns:
            connection.exec_driver_sql(f'ALTER TABLE forecast_revisions ADD COLUMN {name} {ddl}')
    connection.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS ix_forecast_revisions_board_key '
        'ON forecast_revisions (board_key)')
```
```python
    Migration(
        version=47,
        name="forecast_judgment_payload",
        fingerprint="additive_kind+board_key+judgment_json+board_index",
        apply=_apply_forecast_judgment_payload,
    ),
```

`decision.py`：`ForecastRevisionRow` 末尾加 `kind: str | None = None`、`board_key: str | None = None`、`judgment: dict | None = None`；`insert_revision` 加 `kind=row.kind, board_key=row.board_key, judgment_json=canonical_json(row.judgment) if row.judgment is not None else None`；`_to_revision` 加 `kind=row['kind'], board_key=row['board_key'], judgment=json.loads(row['judgment_json']) if row['judgment_json'] else None`；新方法：
```python
    def iter_board_revisions(self, board_key: str) -> Iterator[ForecastRevisionRow]:
        rows = self._connection.execute(
            select(sd.forecast_revisions)
            .where(sd.forecast_revisions.c.board_key == board_key)
            .order_by(sd.forecast_revisions.c.forecast_series_id,
                      sd.forecast_revisions.c.revision_no)
        ).mappings()
        for row in rows:
            yield self._to_revision(row)
```
`tests/ontology/test_migrations.py:63` 的 46 → 47。

- [ ] **Step 4: 跑测试**：`uv run pytest tests/ontology -q` → 全绿。
- [ ] **Step 5: Commit**：`git add nutmeg/ontology/repository/schema_decision.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/repository/decision.py tests/ontology/test_migrations.py tests/ontology/test_forecast_judgment_payload.py && git commit -m "feat(kernel): forecast_revisions carries kind/board_key/judgment_json (schema 47)"`

### Task 2: Actions 透传 + draft 记 supersedes

**Files:**
- Modify: `nutmeg/ontology/actions/forecast_actions.py:36-73, 99-139, 269-300`
- Test: `tests/ontology/test_draft_forecast.py`（增一条）

- [ ] **Step 1: 测试**：连发两条 `DraftForecastRequest(kind="research", board_key="jczq:2026-10-01", judgment={"read_id": "R-a"})` 与 `(kind="override", …{"read_id":"R-b"})`，断言第二条 row 的 `supersedes_revision_id` == 第一条的 id，且 `iter_board_revisions` 读回 `kind`/`judgment`。先跑 → FAIL（TypeError: unexpected kwarg）。
- [ ] **Step 2: 实现**：两个 Request 末尾加 `kind: str | None = None`、`board_key: str | None = None`、`judgment: dict | None = None`；payload 字典加 `'kind': request.kind, 'board_key': request.board_key`（judgment 不进 payload——它是投影源不是决策输入，进 payload 会让幂等哈希随备注抖动）；`draft_forecast` 里 `supersedes = latest revision id of series`（新增 repo 方法 `latest_revision(series_id)`：按 revision_no desc limit 1，任意状态）；`_revision_row` 透传三字段。
- [ ] **Step 3: 跑** `uv run pytest tests/ontology -q` 绿。
- [ ] **Step 4: Commit** `git add nutmeg/ontology/actions/forecast_actions.py nutmeg/ontology/repository/decision.py tests/ontology/test_draft_forecast.py && git commit -m "feat(kernel): forecast requests carry kind/board_key/judgment; drafts supersede the series' latest revision"`

### Task 3: Read 显式带 kind/board_key/code；decision-read 存整条

**Files:**
- Modify: `nutmeg/decision/jczq_reads.py:113-233`
- Modify: `nutmeg/decision/zucai_auto_judgment.py:116-150`
- Modify: `nutmeg/decision/ontology_adapter.py:359-464`
- Test: `tests/decision/test_jczq_reads.py`、`tests/decision/test_zucai_auto_judgment.py`、`tests/decision/test_read_adapter.py`

- [ ] **Step 1: 测试**
  - `test_jczq_reads`: 深研腿 Read 有 `kind == "research"`、`board_key == "jczq:<day>"`、`code == 周X00N`；市场腿 `kind == "market"`；写一条 overrides.jsonl（`record_override`）后重建 → 该腿 `kind == "override"` 且 `override == {"at","note","judge"}`。
  - `test_zucai_auto_judgment`: 转录 Read 有 `kind in {"research","market","manual"}`、`board_key == "zucai:<issue>"`、`code == "<no>"`。
  - `test_read_adapter`: 提交后 `iter_board_revisions("jczq:<day>")` 读回 `judgment == payload`、`kind == payload["kind"]`。
- [ ] **Step 2: 实现**
  - `build_jczq_reads`: 开头 `overrides = {r["research"]: r for r in load_overrides(day_dir)}`；每条 Read 加 `"code": code, "board_key": f"jczq:{day}", "kind": "override" if researched and f"research-{code}.json" in overrides else ("research" if researched else "market"), "override": {k: overrides[...][k] for k in ("at","note","judge")} if override else None`。
  - `build_auto_reads`: 新 Read 加 `"code": no, "board_key": f"zucai:{issue}", "kind": {"main_loop":"manual","research":"research","market_anchor":"market"}.get(source, source)`。
  - `run_decision_read_v2`: 请求加 `kind=payload.get("kind"), board_key=payload.get("board_key"), judgment=payload`。
- [ ] **Step 3: 跑** `uv run pytest tests/decision/test_jczq_reads.py tests/decision/test_zucai_auto_judgment.py tests/decision/test_read_adapter.py tests/decision/test_kernel_submit.py tests/decision/test_pool.py -q` 绿。
- [ ] **Step 4: Commit** `git add nutmeg/decision/jczq_reads.py nutmeg/decision/zucai_auto_judgment.py nutmeg/decision/ontology_adapter.py tests/decision/test_jczq_reads.py tests/decision/test_zucai_auto_judgment.py tests/decision/test_read_adapter.py && git commit -m "feat(reads): every Read names its kind/board/code and lands whole in the kernel"`

### Task 4: 投影与比对模块 + CLI

**Files:**
- Create: `nutmeg/decision/judgment_projection.py`
- Create: `nutmeg/interfaces/cli/judgment.py`；register in `nutmeg/interfaces/cli/__init__.py`（照 `betslip_app` 的注册方式）
- Test: `tests/decision/test_judgment_projection.py`

- [ ] **Step 1: 测试**（用 tmp 内核：`build_ontology_engine` + `run_migrations` + `OntologyKernel`——照 `tests/decision/test_read_adapter.py` 的 fixture）
  1. 写 legs-base 两腿 → `build_jczq_reads` → `run_decision_read_v2(kernel=k)` → `project_board(k, "jczq:<day>")` 返回与 `reads.json` **逐条相等**的列表（同序）。
  2. 再 `build_jczq_reads`（made_at 晚一分钟，同内容）→ 不提交；文件 read_id 变了 → `compare` 报 `only_in_file` 2 / `only_in_kernel` 2 但 `same_belief` 2（按 match_id 对齐的 belief 一致）。
  3. 改文件里一条 belief → `belief_mismatch` 1。
  4. `write_report(day_dir, result)` 落 `judgment-projection.json` 与 `reads.projected.json`。
- [ ] **Step 2: 实现**

```python
"""判断唯一事实 P0（2026-10-01）：从内核投影 Read 列表，并与文件比对。

投影规则：`board_key` 下每个 forecast_series 取 revision_no 最高的一条，其 `judgment_json`
就是那条 Read；按 `code` 排序（竞彩编号字典序 / 足彩场号数值序）。比对以 match_id 对齐：
read_id 不同但 prior/belief/stance 相同算「同判断不同版本号」，不算分歧。
"""
from __future__ import annotations

import json
from pathlib import Path

REPORT = "judgment-projection.json"
PROJECTED = "reads.projected.json"
_KEYS = ("prior", "belief", "stance", "judge", "commitment_tier")


def project_board(kernel, board_key: str) -> list[dict]:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    latest: dict[str, tuple[int, dict]] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for row in uow.decision.iter_board_revisions(board_key):
            if row.judgment is None:
                continue
            best = latest.get(row.forecast_series_id)
            if best is None or row.revision_no > best[0]:
                latest[row.forecast_series_id] = (row.revision_no, dict(row.judgment))
    reads = [judgment for _, judgment in latest.values()]
    zucai = board_key.startswith("zucai:")
    return sorted(reads, key=lambda r: (int(r.get("code") or 0) if zucai else str(r.get("code") or "")))


def compare(projected: list[dict], file_reads: list[dict], *, skip_match_ids=()) -> dict:
    by_k = {r["match_id"]: r for r in projected}
    by_f = {r["match_id"]: r for r in file_reads if r.get("match_id") not in set(skip_match_ids)}
    identical, same_belief, mismatch = [], [], []
    for mid in by_k.keys() & by_f.keys():
        k, f = by_k[mid], by_f[mid]
        if k == f:
            identical.append(mid)
        elif all(k.get(x) == f.get(x) for x in _KEYS):
            same_belief.append({"match_id": mid, "kernel": k["read_id"], "file": f["read_id"]})
        else:
            mismatch.append({"match_id": mid, "code": f.get("code") or k.get("code"),
                             "kernel": {x: k.get(x) for x in _KEYS}, "file": {x: f.get(x) for x in _KEYS}})
    return {"projected": len(projected), "file": len(by_f), "identical": len(identical),
            "same_judgment_new_version": same_belief, "mismatch": mismatch,
            "only_in_kernel": sorted(by_k.keys() - by_f.keys()),
            "only_in_file": sorted(by_f.keys() - by_k.keys()),
            "skipped_mapped": sorted(set(skip_match_ids))}


def summary_line(result: dict) -> str:
    return (f"投影 {result['projected']} 条｜文件 {result['file']} 条｜一致 {result['identical']}"
            f"｜同判断新版本 {len(result['same_judgment_new_version'])}"
            f"｜分歧 {len(result['mismatch'])}｜仅内核 {len(result['only_in_kernel'])}"
            f"｜仅文件 {len(result['only_in_file'])}")


def write_report(directory: Path, *, projected: list[dict], result: dict, board_key: str,
                 at: str, prefix: str = "") -> Path:
    directory = Path(directory)
    (directory / f"{prefix}{PROJECTED}").write_text(
        json.dumps(projected, ensure_ascii=False, indent=1), encoding="utf-8")
    path = directory / f"{prefix}{REPORT}"
    path.write_text(json.dumps({"board_key": board_key, "at": at, **result},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path
```

CLI `nutmeg judgment project --day D [--issue I]`：jczq → `board_key=f"jczq:{day}"`, 文件 `daily/<day>/reads.json`，前缀 ""；zucai → `board_key=f"zucai:{issue}"`, 文件 `zucai/<issue>-reads.json`，前缀 `<issue>-`，`skip_match_ids` = channel-map 里的 match_id。内核 = `build_ontology_kernel(get_settings())`（可注入）。打印 `summary_line` + 分歧逐条一行。

- [ ] **Step 3: 跑** 新测试绿；`uv run nutmeg judgment project --day 2026-09-30` 对生产库跑一次看结果（只读 + 写 daily/ 两个文件）。
- [ ] **Step 4: Commit** `git add nutmeg/decision/judgment_projection.py nutmeg/interfaces/cli/judgment.py nutmeg/interfaces/cli/__init__.py tests/decision/test_judgment_projection.py && git commit -m "feat(judgment): project a board's Reads from the kernel and diff them against reads.json (P0)"`

### Task 5: refresh 落投影比对；override 立即 refresh（P1）

**Files:**
- Modify: `nutmeg/decision/pool.py:98-145`
- Modify: `nutmeg/interfaces/cli/research.py:135-148, 228-257`
- Test: `tests/decision/test_pool.py`（refresh 后 `summary["projection"]` 与文件存在）；`tests/test_cli_research.py`（override 后 reads.json 该腿 `kind == "override"`）

- [ ] **Step 1: 测试** 先写、先红。
- [ ] **Step 2: 实现**：`refresh_day` 加参数 `kernel=None`；在 signals 之前：若 legs_path 存在且 kernel 可得 → `projected = project_board(kernel, f"jczq:{day}")`，`result = compare(projected, reads)`，`write_report(day_dir, …)`，`summary["projection"] = summary_line(result)`；异常吞成 `summary["projection_error"]`。`_refresh` 打印 `投影比对：<line>`。`override` 命令末尾：jczq → `_refresh(day, data_dir)`；zucai → `_refresh(<issue sale_deadline 日>, data_dir)`。
- [ ] **Step 3: 跑** `uv run pytest tests/decision/test_pool.py tests/test_cli_research.py -q` 绿。
- [ ] **Step 4: Commit** `git add nutmeg/decision/pool.py nutmeg/interfaces/cli/research.py tests/decision/test_pool.py tests/test_cli_research.py && git commit -m "feat(research): refresh writes the kernel-vs-file projection report; override re-intakes and lands as a kernel revision (P1)"`

### Task 6: SOP/证据/一周比对义务

- [ ] RUNBOOK B4 判读桥行加：`nutmeg judgment project --day <日>`＝内核 vs 文件比对；分歧>0 先查再改判。RULEBOOK 无改。
- [ ] 证据 `docs/superpowers/evidence/2026-10-01-design-series.md` §2 追加「已落地 P0/P1、比对首跑结果、一周门槛」。spec §2 表格删 belief-v2 行、§4 P3 改写为「judgment-v1 由投影生成」。
- [ ] Commit docs。

## Self-Review
- Spec 覆盖：§3 写路径①（intake→kind=research）经 Task 3+5 达成（研究入库仍经 legs-base，但每次 intake 都落 revision）；②（override→revision）Task 5；§3 读路径的「消费者改接」属 P2–P4，明确延后；§6 验收第 1 条由 Task 4 的比对报告承担。
- 类型一致：`iter_board_revisions` / `ForecastRevisionRow.judgment` / `project_board` 名称贯穿 Task 1/2/4。
- 无占位符。
