# 2026-10-13 审计门一组删除

> 来源：`2026-10-03-overdesign-audit.md` §6 第 2 项、`2026-10-08-slim-round-2.md` §7 第 2 项——两轮都建议删除，均被自动模式判为「篡改日志/审计」拦下。10-13 Jun「剩下的问题全部解决」授权后执行。前提事实：`decision-audit-legs` 的 ERROR 通道自 09-27 规则瘦身起为空；`*-rx.json` 最后一份 26133（09-28），10-01 定位改为机器不出票后无人再做 B7；`nutmeg scoreboard *` 影子期双轨没有任何 plist / OpenClaw / 代码调用。

## 删了什么

| 类别 | 项 | 行 |
|---|---|---|
| CLI 命令 | `decision-audit-legs` `decision-explain-faces` `decision-adjudicate` `zucai-deployment-gate` `zucai-ledger`（`cli/decision.py` 936→572 行）；`zucai-official --settle-ledger` 选项 | −364 |
| CLI 子应用 | `cli/workflow.py`（`register-rx` / `grade-prediction` / `grade-rx`）；`cli/scoreboard.py`（`status` `observe` `rebuild-projection` `shadow` `cutover` `export` `verify-export` `settle-issue` `cutover-readiness`，审计写的「7 条」在 10-03 之后已是 9 条，整组删） | −181 / −526 |
| 决策层模块 | `adjudication_sheet.py`（407）`audit_override.py`（102）`zucai_deployment.py`（291）`zucai_ticket.py`（73）`rx_ingest.py`（74）；`zucai_official.settle_ledger` + `ticket_hits`（57）；`day_runner` 的 grade-rx 步与 `day_brief.latest_closed_issue`（当晚刚加、随之无用） | −1,004 |
| `legs_audit.py` | 1,490→104 行：只剩封闭词典（`PRECEDENT_STATUSES` / 无方向旗 / 方向旗 / `crash_markers` / 追踪标签 / 球队标签），`research_intake` 与 `read_builder` 仍引用；`Leg` / `audit_legs` / C 码 / `EVIDENCE_POLICY` / 面集展开全部删除 | −1,386 |
| 记分牌权威 | `nutmeg/scoreboard/`（`authority.py` 560 行 + `__init__`）；内核 `scoreboard_actions.record_shadow_review` / `approve_cutover` 及两个请求类（死代码周报「只有测试在用」）；`repository/workflow.count_adjudications`（无引用） | −573 / −165 / −4 |
| 测试 | `test_legs_audit*.py`（1,208）`test_adjudication_sheet` `test_audit_override` `test_rx_ingest` `test_zucai_deployment` `test_zucai_ticket` `test_scoreboard_settle_issue` `tests/product/test_scoreboard_projection_cli.py` `tests/scoreboard/`（authority、o-rule observations 经 authority 服务）；`test_zucai_official` 去掉 ledger 三例；`test_day_runner` 的失败段改由 `crowd settle` 触发；`test_read_builder` 改为直接断言 legs-base 结构；`test_scoreboard_actions` 留 `record_export` 系统身份一例 | — |

`find nutmeg -name '*.py' | xargs wc -l`：**51,728 → 47,484**（−4,244）。

## 留下的与原因

- 内核 `scoreboard_actions.record_observation` / `record_export`、`workflow_actions`、`schema_workflow` / `schema_scoreboard` 表、`analytics/calibrate_flow` + `scoreboard_projection` + `intervention_projection`：仍由 `kernel.py` / `wiring.py` / `ontology_adapter`（`decision-settle`）接线，死代码周报不报；表按 10-03 §5 口径留空不删。
- `zucai_gate.py`：是备料的分歧闸（`zucai_prep` / `zucai_insale` 在用），不属审计门。
- `legs_audit` 词典与 `read_builder` 的再导出：入库桥仍用。
- `decision-read`：10-08 §7.3 另案（手工足彩通路）。

## 文档

- CLAUDE.md / AGENTS.md 共享段「出票硬门」改写（两份逐字一致）：审计门一组已删，唯一机器否决是 `betslip preview` V1/V2（RUNBOOK B9c）。
- RUNBOOK：A5 / B4c / B6 / B6b / B7 标 ~~删除~~ 并指向替代（`betslip preview --with` / `preview-set`、`/zucai-packet` §6、`betslip register --prediction`）；B10 去掉 ledger settle / grade-rx / `scoreboard settle-issue|shadow`；收尾清单的 rx outcome 行改为实票 `--prediction` 在 retro 标记。
- RULEBOOK 「〇」「一」「八」五处、CONSTITUTION §6 两处、`docs/jczq-mixed-bet-judge-process.md` 一处：改口径、保留历史。
- ARCHITECTURE 变更日志加 10-13 行。
- `read_builder` / `zucai_draft` / `legs_audit` 模块 docstring 改指向。

## 验证

- `uv run ruff check nutmeg tests scripts experiments`：本次触及文件全部通过（仅 `scripts/renjiu_shape_backtest.py` 12 条 E501 是既有问题，未动）。
- `uv run nutmeg --help` 不再列出任何被删命令；`uv run nutmeg betslip preview --help` 正常。
- `uv run python scripts/deadcode_report.py`：删除后新出现的 3 个死定义（`record_shadow_review` / `approve_cutover` / `count_adjudications`）已随手删；其余 7 条候选是既有的，与本次无关。
- `uv run pytest -q tests`：除两例外全部通过。那两例都由同晚并行新增的 `ops/launchd/com.nutmeg.decision.web.plist` 触发（`test_launchd_plists` 要求每份 plist 有 `StartCalendarInterval`/`StartInterval`，常驻 KeepAlive 没有；`test_decision_web_runs` 要求每份 plist 在 `day_runs.JOBS` 登记证据来源），不在本工作流范围，交由 plist 的作者处理。
