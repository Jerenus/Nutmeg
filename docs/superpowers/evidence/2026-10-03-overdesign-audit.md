# 过度设计审计与瘦身（2026-10-03 → 10-05）

> 起因：Jun 2026-10-03 问「是否有过度设计以及多余的实现和功能？有没有必要砍掉一些内容和模块」。
> 结论：有。10-01 定位转向（机器＝风控官 + 账房 + 实验员，人＝下注者）之后代码没有跟着缩：
> 一半以上的代码在服务空表、一个月没人用的命令、已作废的「机器构票」流程，以及每天照跑却没有产出的步骤。
> Jun 批准 0–5 波全做、逐步进行。

## 1. 审计方法

- 生产内核 `ontology.db` 只读查询：185 张表的行数与最近写入时刻。
- 命令用量：2026-08-31 → 10-03 的 Claude Code 会话记录里每条 `nutmeg` 命令的次数与最后使用日。
- 可达性：从 launchd plist、OpenClaw 确定性任务、`day_runner` / `rsi_loop` 的子进程清单、RUNBOOK 手工命令出发，
  做函数级引用图（模块级 import 图不可用：内核接线把全部仓储连在一起，任何命令都传递导入约 11.4 万行）。
- 四个只读审计代理分区：内核与 operator、实验层、决策核心、遗留命令面；结论逐条抽查后才采用。

## 2. 审计时的硬数字

| 项 | 数字 |
|---|---|
| 生产内核空表 | 185 张里 142 张为空；`operator_*` 78 张共 2 行（且那 2 行无代码读写） |
| operator 投入 | 8 月以来 operator 代码 + 测试约 3.8 万行 |
| Dream | 09-29 常设批准后 5 夜只录到 1 个世界（2 夜失败、2 夜跳过），对照账 1 行；30 世界就绪门 10-31 前不可达 |
| RSI 判决 | `rsi_verdicts` 0 行；每日 12 步闭环只有 4 步有产出；hyp 每天重测同一批 11 条假设、198 行重复记录 |
| 审计门 | `decision-audit-legs` 已无任何 ERROR 路径：足彩票面恒退出 0，竞彩扁平腿数组无条件退出 1（在 `--user-override` 之前）；26130–34 共 56 张票 0 ERROR；`betslip preview` 不调用它 |
| 命令面 | 143 条命令；每次调用导入 262 个模块（0.59 秒） |

## 3. 执行（每波：worktree 开发 → 全量测试 → 生产数据沙盒端到端 → 快进合入 main）

| 波 | 提交 | 内容 |
|---|---|---|
| 0 | `0d8a860` | 删 `ontology_v2` 开关（代码默认 False、生产靠 `.env` 一行、测试测的是死掉的 v1 路径）；`rsi status` 的 n 与判决同源；verify skill 按现役链路重写 |
| 1 | `133960f` | 删旧版服务层：v0 足彩/价值/心理层、入站 Telegram 机器人、四个闲置数据客户端、DuckDB 仓储、迁移工具、v1 JSONL 动词路径、OpenClaw 确认插件；30 条命令、215 个孤儿函数；CLI 枢纽 488 → 40 行 |
| 2（部分） | `c0689d6` | 删机器构票工具：`zucai-candidates` / `zucai-optimize` / `zucai-ticket` / `plan *`；修 `judgment brief --issue` 遇方向旗二元组即崩的 bug |
| 3 | `47aa3c6` | 删 operator 工作台与受保护票代码、4 条 `workflow ingest-*`；表与迁移链不动 |
| 4 | `22427f0` | Dream/Discovery 退役，规则 v3 迁入 gym（`gym run --policy jczq_rule_v3 --belief read`）；`day.dream` 定时器卸载；RSI 闭环 12 → 9 步；删 `scripts/zucai_loop.py` |
| 5 | 本提交 | 删 8 份已落地的计划；`ARCHITECTURE.docx` 移出 git（按需生成）；本证据文档 |

Jun 本人 2026-10-04 执行：`rsi deploy --retire` F3（F10 的前身登记）与 F4（观测仪 `plan commit` 已删）。

## 4. 结果

| 指标 | 审计前 | 之后 |
|---|---|---|
| `nutmeg/` 生产代码 | 116,572 行 / 431 模块 | 59,784 行 / 284 模块（−49%） |
| 测试 | 86,090 行 / 3,245 用例 | 35,995 行 / 1,594 用例 |
| 命令 | 143 | 77 |
| CLI 导入 | 0.59 秒 / 262 模块 | 0.23 秒 / 154 模块 |
| launchd | 14 | 13 |
| RSI 闭环 | 12 步 | 9 步 |

规则 v3 在 gym 上回放 2026-09-18 → 10-02 的 13 个板面日用时 3.8 秒（研究判断口径：9 张 ¥2 票全部落空）；
同期 Dream 一共只给出 1 行对照账。

## 5. 与原计划不同之处（有意为之）

- **F15 保留**，未并入 F10：它测终盘 ≥0.70 的大热（终盘口径，与 F10 的市场口径 60–80% 不同），是 403 天回放里唯一样本外复现的信号。
- **`team_strength` 留在闭环**：当日报告读它的产物。
- **语料仍每天提交**：每日的 `corpus-v2.json` 版本是实验结账的防篡改留痕（语料重建让 n 倒退就是靠它查到的），git 增量压缩后成本很小。
- **迁移链不压基线**：新库全链 = 1,112 个结构对象 + 1,807 行种子数据（权限、球队别名），压成基线等于用 6,700 行生成文件换 Python 迁移；operator 表留空即可，删代码不需要删表。
- **两份待批提案保留**：`plans/2026-08-12-l3-asymmetric-autonomy-roadmap.md` 与 `plans/2026-09-13-impact-magnitude-three-term.md` 实质已被 10-01 定位与 rubric r1 取代，是否删除由 Jun 定。

## 6. 未做（待 Jun 处理）

自动模式的安全检查拦下了以下改动，Jun 授权后仍被拦，未执行：

1. **研究入库改为只警告**（`research_intake` 拿只喂 INFO 码的字段整份拒收研究）：被判为「删除安全检查」。
2. **审计门一组**：`decision-audit-legs` / `decision-explain-faces` / `decision-adjudicate` / `zucai-deployment-gate` / `zucai-ledger`、7 条记分牌权威命令、`workflow register-rx` / `grade-rx` / `grade-prediction`，以及 CLAUDE.md / AGENTS.md 的「出票硬门」一行：被判为「篡改日志/审计」。
   这一组不动，`legs_audit.py` 也就不能缩到只剩词典，RULEBOOK「一–七」与审计码映射也保持原样。
3. **F5/F9 观测仪（`rsi balance` / `rsi price-band`）与 `rsi.sweep` 降频**：要先改实验的观测义务，属实验治理，人做。
4. **AGENTS.md** 的 SOP 指针段（「Dream 对照账」「出票硬门」）：main 里有一处他人未提交的 AGENTS.md 修改，本系列没有改它，CLAUDE.md 已改，两份副本暂不同步。

## 7. 删除时踩过的坑（给下一次）

- 「空包」可能装着非 `.py` 资源：`nutmeg/interfaces/web` 的模板与静态文件被误删，测试红后恢复。
- 函数级可达图不把模块顶层引用算作可达：`_LazySelection` 与 `capital_rules` 被误删后恢复。每次删定义后必须跑一遍覆盖函数内延迟导入的导入检查。
- worktree 里没有 `.nutmeg-data`：软链到生产数据的沙盒副本（绝不链生产），测试与本地命令都只碰沙盒；`.gitignore` 的 `.nutmeg-data/` 只匹配目录，软链要排除在 `git add` 之外。
