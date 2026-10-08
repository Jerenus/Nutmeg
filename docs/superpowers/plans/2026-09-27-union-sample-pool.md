# 并集样本池：每天「传统足彩（优先）∪ 竞彩」全部进研究→判断→F9→本体 · 实施方案

> **状态（2026-10-08）：已执行（`707e20c`、`9b1a542`）。** 仍留在 `plans/` 只因为它是 R1 的冻结 `source_doc`
> （`experiments/registry/R1.json`），`tests/decision/test_rsi_prereg.py` 要求该路径存在——不要删或改名。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个业务日，把当天在售的传统足彩期次（优先）与竞彩板面的**并集**作为分析样本池：每场都有深研、有 Read、进 F9、并自动提交本体（只交未开球场次）。

**批准：** Jun 2026-09-27 00:50「需要用当天所有传统足彩（优先）和竞彩足球比赛的并集作为分析样本池子进行样本积累，养料培育」；预算保持 40 次/天；Read 自动提交本体、只交未开球场次。

**Architecture:** 不新造判断——判断仍来自深研 agent 的表态（与竞彩泳道同一口径：研究 stance → tilt 算术 → belief）。新增的只是「接线」：①两渠道身份对齐自动落盘；②研究队列取并集且足彩先排；③足彩侧由研究表态自动转录 judgment-v1 → Read（主循环人工 judgment 永远优先）；④Read 自动提交本体（开球后不交、内容没变不交）。R0 冻结不动，另立 R1（population=both）量并集研究覆盖。

**Tech Stack:** Python 3.13 / typer / pytest；数据在 `.nutmeg-data/`。

---

## 现状缺口（2026-09-26 实证）

| 缺口 | 证据 | 后果 |
|---|---|---|
| 渠道对号表只认人工 `{issue}-channel-map.json` | 26132/26133 无此文件；备料自动对齐其实已对上 7 场 | F9 并集 39 场里同一场算两次（7 场） |
| R0 深研 population=jczq | 26133 的 7 场周日比赛不在竞彩板上 | 足彩独有场次从不被自动研究 |
| 足彩 Read 只能由主循环手写 judgment-v1 生成 | `zucai-build-reads --judgment-file` | 没人跑 B 泳道的期次，足彩场次不进 F9 |
| 竞彩/足彩 Read 从不自动进本体 | 09-26 本体里竞彩 Read 全是手工提交 | 语料内核通道只有人工场次；001 永久缺 |

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `nutmeg/decision/zucai_prep.py` | 备料 | 自动对齐结果落 `{issue}-channel-map.auto.json`（jczq match_id → 场号） |
| `nutmeg/decision/rsi_population.py` | 实验池子 | 人工对号表优先，缺则读 `.auto` |
| `nutmeg/decision/pool.py`（新） | 当日并集池 | `day_pool(day, data_dir)`：足彩在售期次 14 场（优先）∪ 竞彩板面，按对号表去重，给出每场研究落点 |
| `nutmeg/decision/research_runner.py` | 深研 | 队列 = 并集池，足彩独有场次写 `zucai/{issue}-research-m{n}.json`；排序：足彩先、未试先、开球先 |
| `nutmeg/decision/zucai_auto_judgment.py`（新） | 足彩表态转录 | 研究 stance → judgment-v1 条目（纯转录+tilt 算术）；已有人工 judgment 的场次不覆盖 |
| `nutmeg/decision/kernel_submit.py`（新） | 自动入本体 | 只交未开球、且 belief/prior 与上次提交不同的 Read；状态记 `.../kernel-submitted.json` |
| `experiments/registry/R1.json`（新） | 并集深研覆盖实验 | population=both，duty 同 R0 |
| `nutmeg/decision/rsi_wiring.py` / `interfaces/cli/research.py` | 接线 | 研究有新产出 → 两渠道重建 Read → 自动提交 |
| SOP 三件套 | 文档 | RUNBOOK A/B 泳道加「并集池」一行；RULEBOOK 记 R1 |

## 任务

### Task 1: 自动对号表
- [ ] 测试：`build_prep` 在 align 成功的场次上写出 `{issue}-channel-map.auto.json`，键=竞彩 match_id，值=足彩场号；人工表存在时不改人工表。
- [ ] 测试：`matches_for_population("both")` 在只有 `.auto` 时去重（source="both"）。
- [ ] 实现、跑测试、提交。

### Task 2: 当日并集池
- [ ] 测试：`day_pool` 返回足彩独有场次在前、带 `research_path`（足彩独有 → `zucai/{issue}-research-m{n}.json`；已对到竞彩 → `jczq/daily/{day}/research-{code}.json`）；同一场只出现一次。
- [ ] 实现、提交。

### Task 3: 研究队列取并集
- [ ] 测试：预算 1 时足彩独有场次先于竞彩场次；足彩独有场次的研究文件写到 zucai 目录并登记 R1 duty。
- [ ] 实现（`run_day` 接受池条目；竞彩行为不变）、提交。

### Task 4: 足彩表态自动转录
- [ ] 测试：研究 stance + fair → judgment-v1 条目（action/prescription=表态面集、belief=tilt 算术结果、flags 等原样转录）；已有 `{issue}-judgment-v1.json` 的场次保留人工条目。
- [ ] 测试：`zucai-auto-reads --issue` 产出 `{issue}-reads.json`，judge=`ai:pool`。
- [ ] 实现、提交。

### Task 5: Read 自动提交本体
- [ ] 测试：开球后不交；与上次提交内容相同不交；新内容交且记状态。
- [ ] 实现 `kernel_submit.submit_pool_reads(day, data_dir)`；接到研究/重建之后；提交。

### Task 6: R1 登记 + 接线 + SOP
- [ ] `experiments/registry/R1.json` 登记（`rsi register --by Jun`，授权见上）。
- [ ] `after_prep` 与 `research run` 有新产出时：两渠道重建 Read → 自动提交；`rsi schedule` 为 R1 排并集 duty。
- [ ] RUNBOOK/RULEBOOK 更新；全量测试；提交。

## 自查
- 覆盖：去重（T1）、足彩优先（T2/T3）、足彩 Read 自动化（T4）、本体（T5）、度量（T6 R1）。
- ⛔判断永不入脚本：T4 只转录 agent 表态，不产生任何判断；主循环人工 judgment 永远覆盖自动条目。
- 前瞻性：T5 开球后不交；T3/T4 沿用 Read 开球后冻结（355f0b9）。
