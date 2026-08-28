# o 条分型 Scoreboard 观察 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用现有 typed `scoreboard observe` 把 o 条持平开平 3/6 retired 与 1 球差分胜负 5/5 watch 拆成独立 ratio metrics，并证明 legacy parent 可保持 `formal_manual`。

**Architecture:** 不新增平行命令或业务判断模块。测试在临时 kernel 内演示“无 observation 时 formal_manual 被拒绝 → 两次 typed Action 后成功”的完整状态转换；生产只修订既有 parent observation 并新增 child observation，不直接改 legacy JSON。

**Tech Stack:** Python 3.12、typed ScoreboardActions、Typer CLI、SQLite、DuckDB projection、pytest。

---

## 文件结构

- Create `tests/scoreboard/test_o_rule_observations.py`：两分型入库、投影、shadow 验收。
- Modify `docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md`：生产 Action IDs 与验证证据。
- Runtime only `.nutmeg-data/ontology/ontology.db`：两次 `record_scoreboard_observation` typed Action。

## Task 1: 临时 kernel 状态转换验收

**Files:**
- Create: `tests/scoreboard/test_o_rule_observations.py`

- [x] **Step 1: 写精确业务 fixture 与 RED 前置**

测试创建只含 legacy `chains/suspended_tie_sandwich_o` 的临时 scoreboard，先 build 空投影，
再以 `formal_manual` classification 调 `ScoreboardAuthorityService.shadow`：

```python
with pytest.raises(ScoreboardAuthorityError, match="formal manual observation missing"):
    service.shadow(
        legacy_path=legacy,
        classification=[{
            "group_key": "chains",
            "metric_key": "suspended_tie_sandwich_o",
            "classification": "formal_manual",
        }],
        projection_version="sb-v1",
        source_high_watermark=empty.high_watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
```

这一步是运行时 RED：同一状态机在缺 observation 时必须拒绝 formal_manual。

- [x] **Step 2: 写两个 typed observation 与 GREEN 后置**

在同一测试中通过 `kernel.scoreboard_actions.record_observation` 写：

```python
PARENT = {
    "group_key": "chains",
    "metric_key": "suspended_tie_sandwich_o",
    "tally": "3/6开平",
    "status": "retired",
    "numerator": 3.0,
    "denominator": 6.0,
    "value": 0.5,
    "unit": "ratio",
}
CHILD = {
    "group_key": "chains",
    "metric_key": "suspended_one_goal_margin_o",
    "tally": "5/5分胜负",
    "status": "watch",
    "numerator": 5.0,
    "denominator": 5.0,
    "value": 1.0,
    "unit": "ratio",
}
```

重建 projection 后再次 shadow；断言 review manual=1/unexplained=0，并断言 manual plane 两行
的 numerator/denominator/value/status 精确匹配。

- [x] **Step 3: 跑测试确认状态 RED→GREEN 链整体通过**

Run: `uv run pytest tests/scoreboard/test_o_rule_observations.py -v`  
Expected: 1 passed，测试内部先捕获缺 observation 错误，随后成功产生 shadow review。

- [x] **Step 4: 跑相关回归与 ruff**

Run: `uv run pytest tests/scoreboard/ tests/ontology/test_scoreboard_actions.py tests/analytics/test_scoreboard_projection.py -v`  
Run: `uv run ruff check tests/scoreboard/test_o_rule_observations.py`  
Expected: 0 failed，All checks passed。

- [x] **Step 5: Commit**

```bash
git add tests/scoreboard/test_o_rule_observations.py
git commit -m "test(scoreboard): formalize o-rule subtype observations"
```

## Task 2: 生产前置核对与临时 CLI 演练

**Files:**
- Runtime temp directory only

- [x] **Step 1: 只读查询当前 parent 叶节点**

Run a read-only SQLite query for `chains/suspended_tie_sandwich_o`。  
Expected: one current leaf，numerator=3、denominator=6、status=`retired-subpattern`；保存其
`scoreboard_observation_id` 作为 `--supersedes` 与 evidence ID。

- [x] **Step 2: 在临时 data-dir 初始化 kernel 并调用两次真实 CLI**

对临时 ontology 先写一个 parent，再运行与生产完全相同的 supersede 和 child
`uv run nutmeg scoreboard observe` 命令。  
Expected: 两次 stdout 都是 committed Action；SQLite 查询 parent 当前叶为 revision，child
为独立叶，数值分别 3/6 与 5/5。

## Task 3: 生产 typed observe

**Files:**
- Runtime `.nutmeg-data/ontology/ontology.db` only

- [x] **Step 1: 修订 parent**

Run `uv run nutmeg scoreboard observe` with：

- group/metric：`chains/suspended_tie_sandwich_o`；
- tally/detail/status：`3/6开平` / 只描述持平开平 retired / `retired`；
- numerator/denominator/value/unit：`3/6/0.5/ratio`；
- evidence：原 parent `scoreboard_observation`；
- `--supersedes`：Task 2 查得的当前 parent ID；
- `--acknowledge-manual-source`。

Expected: committed，result ref object type `scoreboard_observation`。

- [x] **Step 2: 新增 child**

Run `uv run nutmeg scoreboard observe` with：

- group/metric：`chains/suspended_one_goal_margin_o`；
- tally/detail/status：`5/5分胜负` / 独立保留观察 / `watch`；
- numerator/denominator/value/unit：`5/5/1.0/ratio`；
- evidence：原 parent `scoreboard_observation`；
- `--acknowledge-manual-source`。

Expected: committed，result ref object type `scoreboard_observation`。

- [x] **Step 3: 生产只读验收**

查询 observation revision 链和两次 Actions：parent 原行被新叶 supersede；child 一条；两条
Action 均 committed；`.nutmeg-data/scoreboard.json` SHA-256 与执行前完全一致。

## Task 4: 完成门

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md`

- [x] **Step 1: cherry-pick schema 15 共享测试修复**

Run: `git cherry-pick 5c68f09`

- [x] **Step 2: 全库验证**

Run: `uv run ruff check .`  
Run: `uv run pytest -q`  
Expected: 0 failed。

- [x] **Step 3: 写入执行证据、勾选计划并提交**

```bash
git add docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md
git commit -m "docs(plan): record o-rule scoreboard verification"
```

## 执行证据（2026-08-28）

- 定向状态转换：`uv run pytest tests/scoreboard/test_o_rule_observations.py -v`
  → `1 passed`；相关回归 → `19 passed`；`uv run ruff check
  tests/scoreboard/test_o_rule_observations.py` → `All checks passed!`。
- 临时 CLI 演练（`/tmp/nutmeg-t8-observe.qwDR4N`）：parent revision Action
  `ACT-49206bc06ee843f98ef2c5c489624109`、child Action
  `ACT-b698b47c8fd6427fad69507fe215dba2`，均 committed；查询得到 parent 当前叶
  `3/6, 0.5, retired`，child 当前叶 `5/5, 1.0, watch`。
- 生产 parent 原叶：`sbo-618b82c219fc4c3b9e88a2c41193975d`。修订 Action
  `ACT-d41d36bcf8ad4a7bb4a555538de1805d` → observation
  `sbo-4d4e8d4da795404ba4a46ce831e620b7`；child Action
  `ACT-75799238faf143c18c8061d90bcf033b` → observation
  `sbo-8c1a3b5881ca41c187ae930345e47476`。两条 Action 均为
  `judge_operator / committed`。
- `.nutmeg-data/scoreboard.json` 写前写后 SHA-256 均为
  `90a1f16144407bd8f5fcd6f367374bf335605e936bd3205a5778a34361c25dbc`。
- 完成门：`uv run ruff check .` → `All checks passed!`；`uv run pytest -q`
  → 100%，退出码 0；`uv run pytest --collect-only` → `1389 tests collected`。

计划偏离：fixture 使用当前合法 projection version `sb-v1`，而非初稿误写的
`scoreboard-v1`。全库 pytest 的 quiet 输出不打印汇总计数，故证据记录退出码与 100% 进度；
提交前钩子另行保留分域测试证据。

## 显式排除

- 不直接编辑/重写 `scoreboard.json`，不运行 export。
- 不运行 cutover、ReleaseApproval、soak 或 launchd。
- 不替其余 17 个 metric 选择 classification。
- 不从脚本推导 o 条结论；3/6 retired 与 5/5 watch 均来自任务书给定裁决。
