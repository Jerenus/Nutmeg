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

- [ ] **Step 1: 写精确业务 fixture 与 RED 前置**

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
        projection_version="scoreboard-v1",
        source_high_watermark=empty.high_watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
```

这一步是运行时 RED：同一状态机在缺 observation 时必须拒绝 formal_manual。

- [ ] **Step 2: 写两个 typed observation 与 GREEN 后置**

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

- [ ] **Step 3: 跑测试确认状态 RED→GREEN 链整体通过**

Run: `uv run pytest tests/scoreboard/test_o_rule_observations.py -v`  
Expected: 1 passed，测试内部先捕获缺 observation 错误，随后成功产生 shadow review。

- [ ] **Step 4: 跑相关回归与 ruff**

Run: `uv run pytest tests/scoreboard/ tests/ontology/test_scoreboard_actions.py tests/analytics/test_scoreboard_projection.py -v`  
Run: `uv run ruff check tests/scoreboard/test_o_rule_observations.py`  
Expected: 0 failed，All checks passed。

- [ ] **Step 5: Commit**

```bash
git add tests/scoreboard/test_o_rule_observations.py
git commit -m "test(scoreboard): formalize o-rule subtype observations"
```

## Task 2: 生产前置核对与临时 CLI 演练

**Files:**
- Runtime temp directory only

- [ ] **Step 1: 只读查询当前 parent 叶节点**

Run a read-only SQLite query for `chains/suspended_tie_sandwich_o`。  
Expected: one current leaf，numerator=3、denominator=6、status=`retired-subpattern`；保存其
`scoreboard_observation_id` 作为 `--supersedes` 与 evidence ID。

- [ ] **Step 2: 在临时 data-dir 初始化 kernel 并调用两次真实 CLI**

对临时 ontology 先写一个 parent，再运行与生产完全相同的 supersede 和 child
`uv run nutmeg scoreboard observe` 命令。  
Expected: 两次 stdout 都是 committed Action；SQLite 查询 parent 当前叶为 revision，child
为独立叶，数值分别 3/6 与 5/5。

## Task 3: 生产 typed observe

**Files:**
- Runtime `.nutmeg-data/ontology/ontology.db` only

- [ ] **Step 1: 修订 parent**

Run `uv run nutmeg scoreboard observe` with：

- group/metric：`chains/suspended_tie_sandwich_o`；
- tally/detail/status：`3/6开平` / 只描述持平开平 retired / `retired`；
- numerator/denominator/value/unit：`3/6/0.5/ratio`；
- evidence：原 parent `scoreboard_observation`；
- `--supersedes`：Task 2 查得的当前 parent ID；
- `--acknowledge-manual-source`。

Expected: committed，result ref object type `scoreboard_observation`。

- [ ] **Step 2: 新增 child**

Run `uv run nutmeg scoreboard observe` with：

- group/metric：`chains/suspended_one_goal_margin_o`；
- tally/detail/status：`5/5分胜负` / 独立保留观察 / `watch`；
- numerator/denominator/value/unit：`5/5/1.0/ratio`；
- evidence：原 parent `scoreboard_observation`；
- `--acknowledge-manual-source`。

Expected: committed，result ref object type `scoreboard_observation`。

- [ ] **Step 3: 生产只读验收**

查询 observation revision 链和两次 Actions：parent 原行被新叶 supersede；child 一条；两条
Action 均 committed；`.nutmeg-data/scoreboard.json` SHA-256 与执行前完全一致。

## Task 4: 完成门

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md`

- [ ] **Step 1: cherry-pick schema 15 共享测试修复**

Run: `git cherry-pick 5c68f09`

- [ ] **Step 2: 全库验证**

Run: `uv run ruff check .`  
Run: `uv run pytest -q`  
Expected: 0 failed。

- [ ] **Step 3: 写入执行证据、勾选计划并提交**

```bash
git add docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md
git commit -m "docs(plan): record o-rule scoreboard verification"
```

## 显式排除

- 不直接编辑/重写 `scoreboard.json`，不运行 export。
- 不运行 cutover、ReleaseApproval、soak 或 launchd。
- 不替其余 17 个 metric 选择 classification。
- 不从脚本推导 o 条结论；3/6 retired 与 5/5 watch 均来自任务书给定裁决。
