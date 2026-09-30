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

## 4. 评估指标换轴（2026-10-01 02:00）

**事实**：F9（belief vs 市场 Brier）n=25 才 ±2pp 区间；每天 8–15 场，赛季内分不开。而两天 16/16 的表态面、Dream 对照的「实际 vs 规则最优 vs 空仓」、F10 首结账 +24pp（CI 不含 0）才是有信息量的轴。

**动作**：闭环报告「前瞻结账」分主指标（F14、F10、Dream 对照账）与次指标（F9 等）；简报 RSI 节加「主指标」一行；研究契约改为「结构优先、无锚不拨动」（与 `apply_tilt` 的锚归零一致，避免研究继续写会被归零的拨动）；宪法与 CLAUDE/AGENTS 指针同步「判断力主指标」措辞。样本速率本身受赛程限制，研究预算不是瓶颈，未改预算。

## 2. 判断唯一事实（2026-10-01 03:10，spec 已写，待 Jun 审后出计划）

**事实**：同一场的判断住在 5–6 份文件里（研究原件 / overrides.jsonl / legs-base.stance / reads.json / 内核 forecast_revisions / 足彩 judgment-v1+belief-v2），靠 `research refresh` 互相重建；26133 冰岛 +7 原判被覆盖、09-28 combos 与 reads belief 不一致、F9 每小时报「reads 尚未落盘」都是同一个病。

**动作**：spec `docs/superpowers/specs/2026-10-01-single-judgment-truth-design.md`——内核 ForecastRevision 是唯一可写的判断（intake → `kind=research`，override → `kind=override, supersedes`），其余文件改为 `judgment project` 投影；分片 P0 只读投影（跑一周比对）→ P1 override 入内核 → P2 研究入库直落内核 → P3 足彩并轨 → P4 退役 jsonl/belief-v2/build-reads。**这是大重构，未动任何写路径**；Jun 看过 spec 后再按 writing-plans 出 P0 计划。第 5 条的 `ForecastActions.draft/revise/withdraw` 零调用正是因为这条还没接——瘦身时不许删。

## 5. 内核瘦身（2026-10-01 03:20，清单已出，执行待 Jun 批）

**盘点**（生产库 `.nutmeg-data/ontology/ontology.db`，schema 28）：185 张表，**143 张空**：operator 77/78、policy 15/16、discovery 5/5、ticket 5/6、official 4/4、zucai 4/5、rsi 2/8、factor 2/3、claim/observation/evidence/exploration 各 2/2，另有 20 余张单表空（venues/persons/role/person/lineup/claims/observations/decision/scenarios/budget/flag/precedent/agent/audited/reliability/release/historical/protected/…）。`nutmeg/ontology/actions/` 78 个公开 action 方法，**35 个在 actions 包之外零调用**（按方法名检索，动态派发可能漏计，删前逐条核）：
- `ProtectedTicketActions` 6 个（create/approve ticket batch、operator 变体、bind auditor、remove leg）——机器出票路径 10-01 已退役；
- `DiscoveryGovernanceActions` 4 个 + `DiscoveryWorldActions.record_node/record_failure` + `ReplayActions.finish`——Dream 夜录已跑 3 晚而 discovery 表 5/5 全空 → harness 只写文件，内核这 5 张表从未接线；
- `WorkflowActions` 6 个（agent_proposal/link_precedent/record_adjudication/register_prediction/record_flag_instance）与 `ClaimActions` 3 个——08-23 四新对象的入账路径，实际入账全在 scoreboard.json；
- `ForecastActions.draft/revise/withdraw`——**第 2 条要用，保留**；
- `RsiActions.amend/grade/record_verdict/approve_deployment`、`FactorActions.propose/apply_factor_status`、`BudgetActions.change_budget_policy`、`EntityActions.merge_entity`、`OutcomeActions.correct_outcome`、`TicketActions.record_cash_transaction`——各有一个「应该走内核但实际走文件」的对应物，逐个裁。

**分片提案**（每片一次迁移 + 一次备份，`.nutmeg-data/archive/` 已有三份历史库）：S1 删 operator_* 77 表 + ProtectedTicketActions（两条都已退役，零风险）；S2 discovery_*/policy_* 20 表二选一——要么 Dream harness 改写内核，要么删表（我倾向删：文件即事实、`discovery compare` 已闭环）；S3 Workflow/Claim 路径 vs scoreboard.json 二选一（宪法说记分牌是单一事实源 → 删内核侧）；S4 逐条裁剩余 10 个方法。**没动一行代码**：删表是不可逆迁移，等 Jun 一句「S1 开工」。

## 6. 身份解析（2026-10-01 03:40 ✅）

**事实**：夜账校准 `zucai-night-calibrate` 走 API-Football + `<issue>-af-map.json`，af-map 是每期手工 curl 拼的第二套身份表——26134 没有，当晚三次校准全报「无映射」；而同一场的 90' 赛果早就在 `jczq/jc-results.json`（09:30/15:30 回填），身份也早就在 `<issue>-channel-map.json`（match_id → 足彩场号）与 `jczq-legs-base.json`（竞彩编号 → match_id）里。

**动作**：`nutmeg/decision/zucai_night.py` 改为 足彩场号 →channel-map→ 内核 match_id →当日 legs-base→ 竞彩编号 → jc-results 终场；`--date` 语义改为竞彩板面日；快照改名 `<issue>-night-<日>-jc.json`；`load_af_map/fetch_af_day` 与 `zucai_identity.build_af_map` 删除，API-Football 不再被这条链调用。实跑 26134 @ 2026-09-28：场1/3/4/5/6/7 六场解析且与官方赛果一致，其余 8 场显式「channel-map 无映射（不在竞彩板）」——这是设计：不在竞彩板的场次只等 09:45 官方结算，**不按队名猜**。RULEBOOK g-scope 加「身份脊柱」：canonical 键＝内核 match_id，竞彩编号/足彩场号/titan007 id 都是别名，只走别名表；RUNBOOK B9/B9b 同步。

## 7. 月度刹车（2026-10-01 04:00 ✅ 机制；**数字待 Jun 拍板**）

**事实**：宪法 §4 只有期级刹车（两期全灭→减半/空仓），两次行权都是负样本（累计多亏 ¥677）；账户级没有任何线。记分牌 `tickets` 从 26129 起有净值：**9 月净 −¥4,721**（26129 −1,164 / 26130 0 / 26131 −310 / 26132 −1,362 / 26133 −816 / 26134 −539 / 竞彩 09-26 −180 / 09-28 −350 / 09-29 0）。

**动作**：`nutmeg/decision/bankroll.py`（`MONTHLY_STOP_LOSS_YUAN = 3000`；`ticket_month` 按 `jczq-YYYYMMDD` 或 `<issue>-issue.json` 的 sale_deadline 归月，归不了月的条目单列不猜；`brake_state/status_line`），`betslip preview/register` 与 `plan frontier` 每次打印一行「本月净 / 止损线 / 空间」，**只报不拦**（登记是事实；空仓由主循环按宪法执行）。宪法 §4 加月度止损条，RUNBOOK B9 加指针。

**回测（只算记分牌覆盖的 9 月）**：−¥3,000 会在 26133 结算日（09-27，累计 −3,652）触发 → 26134 与竞彩 09-28 空仓，**少亏 ¥889**；−¥2,000 会在 26132（09-25，−2,836）触发 → 再多免掉 26133，少亏 ¥1,705；−¥4,000 要到 26134 才触发，9 月内一分不省。n=1 个月，这只是量纲校准不是证据；**Jun 选 2,000 / 3,000 / 4,000 或别的数**，改 `bankroll.py` 一处常数 + 宪法一行即可。10 月从 0 起算，空间 ¥3,000。

## 8. Dream 评估口径（2026-10-01 04:05，只记 10-31 决定清单，不写码）

夜录自 09-28 起按常设批准每晚 20:30 跑，闭环报告已有「Dream 对照账」行。10-31 常设批准到期时一起裁：
1. **评估器 v3**：从「帽内 max P + 结构分级」换成决策规则口径——候选票按 belief 算期望回报（奖池中位/竞彩赔率），只有 EV>1 的候选才算「规则最优」，与实际票、空仓三列对照；否则 Dream 永远推荐买（max P 从不为零）。
2. **录制时刻**：20:30 是为了把当天最终票面作为第四份冻结输入；若 `betslip register` 能在 18:50 前完成，可提前到 18:50 与判决页对齐，避免夜场开球后才录（开球过滤已在，只是样本少一截）。
3. **单关缺口**：竞彩单关（`had` 单腿）不在候选枚举里，而 09-28 实票五张全是串关共享同一死点——Dream 对照账目前对「该不该拆单关」无话可说；v3 时一并把单关加进模板。
4. **样本门槛**：10-31 预计 n≈30 晚；Dream 对照账三列（实际/规则最优/空仓）差值 CI 含 0 就继续录到 11-30，不含 0 才谈把评估器接进出票流程。
