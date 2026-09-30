# 2026-10-01 设计层改造系列 · 证据（逐条追加）

Jun 2026-10-01：「可以，按照你的顺序，逐条进行处理。我觉得都很重要。」
顺序（主循环 2026-09-30 深夜复盘给出）：1 两个判断循环 → 3 真实票路径 → 4 评估指标换轴 → 2 判断唯一事实 → 5 内核瘦身 → 6 身份解析 → 7 月度刹车（Jun 定数）→ 8 Dream 评估口径（10-31）。

## 1. 两个判断循环 → 一个（2026-10-01 00:40）

**事实**：OpenClaw 里仍在跑一条 GPT（codex/gpt-6-sol）判断链：18:20「每日最终决策」写 `legs.json`/`nutmeg-handoff.json` 并向 Telegram 宣布「结论、票面草案和金额」；18:40 受限补跑；18:50 闸门（对 legs.json 跑审计）；19:00 收盘（审计 + `decision-close --dry-run`）；08:20「早间复盘对齐」再推一条 GPT 复盘。74 天里 13 天写出非空 `legs.json`；`decision-close` 从来是 dry-run，真实票走 500 app + 分享卡登记。主循环（Claude）在同一天做判读、改判账、判决参考页，两边互不为输入——Jun 每天可能收到两个相反的「最终决策」。

**动作**：停用 5 个 OpenClaw 任务（`openclaw cron disable`）：`25601f28` 18:20 每日最终决策、`8fb11da3` 18:40 补跑、`eadda096` 18:50 闸门、`d6b2827b` 19:00 收盘、`cb76c387` 08:20 早间复盘对齐。保留：`282ed9c4` 08:10 内核结算（`decision-settle --no-dry-run`，Forecast 评分唯一路径）、`40501fe1` 12:30 D1/D2 补结算、`a562599b` 17:15 临场板面刷新。JunsMediaMini 两条与 Nutmeg 无关，未动。备份：`.nutmeg-data/backups/openclaw-cron-2026-10-01.json`；恢复＝`openclaw cron enable <id>`。

**留待**：若要保留 GPT 作为独立第二意见，正确形态是让它按 `jczq-match-analyst` 同一输出契约写研究文件进入库桥（同一改判账、同一 F14 结账），而不是另一份「最终决策」。

## 3. 真实票路径（2026-10-01 01:30）

**事实**：09-20 以来 26 张真票（¥3,774）全部是 500 app 下单 + 分享卡登记；`decision-close` 的 express 一直 dry-run，Telegram 二段确认从未被消费。审计门、C15/C17、部署门只守着没人走的机器路径。

**动作**：
- `nutmeg/decision/ledger_writeback.py`：`betslip register` 把每张竞彩实票展开成注、用 express 同一条内核路径（`kernel.express.approve_for_match`）写成 Ticket，幂等键 `betslip:<slip_id>:<note>`；没有已提交 Read/选项/真实赔率的注跳过并计数，混合过关如实报 unsupported；内核不可用不挡登记。足彩实票不进内核（内核市场是竞彩口径），账在 betslips/scoreboard。
- 退役：CLI `decision-express`、`decision-close`、`ticket-confirmation`；`verbs.run_decision_close`/`_express_step`、`express.run_express`；OpenClaw 桥脚本；对应测试。保留 `compose_tickets`（内核 composition 仍用）与内核 `ProtectedTicketActions`/表（第 5 条内核审计再定）。
- RUNBOOK A6 改为真实路径，B9 去掉 Telegram 二段确认，头部 close 标退役。
