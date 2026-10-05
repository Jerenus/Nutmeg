# Nutmeg 定时数据流与断流后果（2026-09-20 立，2026-10-02 更新）

> 运行权威是 `~/Library/LaunchAgents/com.nutmeg.*.plist` 与 `launchctl list`；plist 单一来源 `ops/launchd/`。
> 2026-10-05：launchd **13 个**（2026-10-04 退役 `day.dream`，Dream 规则 v3 改由 `gym run --policy jczq_rule_v3 --belief read` 回放；2026-10-02 新增 `account.month`、退役 `zucai.f2-observe`），OpenClaw 仍在用 **3 个**确定性任务。
> 结构总图与每日时序图见 `docs/ARCHITECTURE.md` §2。新增或退役定时器必须同一提交更新本页、`docs/ARCHITECTURE.md` §2 与运行记录页登记表 `nutmeg/decision/day_runs.py:JOBS`。

## launchd

| Label | 时刻（BJT） | 命令 / 产物 | 喂给谁 | 断流后果 |
|---|---:|---|---|---|
| `com.nutmeg.decision.am` | 08:00（失败 30 分后重试一次） | `scripts/openclaw/nutmeg_scheduler_ops.py run-strict --stage am` → `decision-am`：板面、赔率快照入内核；成功后自动 `research board` + `rsi schedule` + 并集池刷新 | 判断层、RSI 义务排程 | 当日没有板面；体彩列表**完全为空**记为合法空盘（`NUTMEG_OK … empty_board`，2026-10-02） |
| `com.nutmeg.jczq.results-backfill` | 09:30 / 15:30 | `scripts/jczq_result_backfill.py` → `jczq/jc-results.json` | 结算、语料、夜账 | 结算与语料停在旧日期；stdout 首行 `⚠️RESULTS_STALE` 时退出 2，不得把旧结果当完整结算源 |
| `com.nutmeg.day.settle` | 09:45 / 15:45 | `day run --job results` + `--job settle`：昨日 90' 赛果桥 → 实票结算 → 记分牌复盘编码 → 处方预测记账 | 记分牌、账房、gym 回放的实际票面 | 昨日票未结；账房缺数 |
| `com.nutmeg.jczq.research` | 10:00 | `decision-am` → `research run`（并集池 ≤40 场，带 rubric r1）→ `research intake --write` → `jczq-build-reads`；并集池刷新同时自动建足彩 legs-base | 研究文件、Read、内核 revision、机器初稿输入、R0/R1 | 判断层零产出；空盘日入库与建 Read 自动跳过 |
| `com.nutmeg.rsi.loop` | 10:45 | `rsi loop` 9 步：终盘补采 → 两读 → 语料 → 前瞻结账 → 到期判决 → 因子提案 → 实力指数 → 记分牌解析 → 自动提交实验文件 → `analytics/rsi-loop/latest.md` | 实验层、当日报告的「待人决定」 | 判决与提案停在前一天；`--force` 可当天重跑 |
| `com.nutmeg.zucai.prep-morning` | 11:00 | `zucai-prep --slot morning --dispatch-telegram`；备料后带期号入本体（产 store-ids） | 足彩样本池、legs-base | 当期赛程与早盘快照缺 |
| `com.nutmeg.zucai.prep` | 14:00 | `zucai-prep --slot afternoon --dispatch-telegram`：重抓、与早间比位移 | 同上 | 午后位移不可见 |
| `com.nutmeg.zucai.prep-revision` | 18:30 | `zucai-prep --slot revision --dispatch-telegram`：截止前最后一次位移复核 | 同上 | 晚盘变化未进入最终判断 |
| `com.nutmeg.day.brief` | 12:00 / 14:20 / 18:35 | `day run --job brief`（12:00 带模型解释）+ `day publish --out site`：当日报告、会话入口、待人决定、足彩初稿自动重建 | `/today`、站点、Jun | 读到旧报告 |
| `com.nutmeg.day.verdict` | 12:30 / 18:45 | `research refresh` + `research verdict`：刷新判断后生成判决参考页 | Jun 的人工裁决 | 看旧页 |
| `com.nutmeg.day.broadcast` | 每 10 分 | `day run --job broadcast`：截止前 30 / 10 分钟 Telegram。**2026-10-02 起只提醒两类**：足彩在售期停售前仍无登记实票；竞彩预审过方案却未登记（截止＝预审腿最早开球）。每次现算 | Jun | 截止无人提醒（26130 复发） |
| `com.nutmeg.rsi.sweep` | 每小时 :00 | `rsi sweep`：兑现到期的观察义务（只认 active 义务） | F5 / F9 / R0 / R1 | 加场日义务过期成缺口，不能回补 |
| `com.nutmeg.account.month` | 每月 1 日 16:10 | `account month --previous --write` → `analytics/account/<上月>.md` | Jun（月报） | 月报缺席（可手跑） |

## OpenClaw（确定性任务，GPT 判断链 2026-10-01 已停用）

| 任务 | 时刻 | 命令 | 备注 |
|---|---|---|---|
| Nutmeg-昨日结算 | 08:10 | `decision-settle --run-date <昨天> --no-dry-run` + `build-context` | 内核 Read 的 Brier / CLV 结算 |
| Nutmeg-D1D2补结算 | 12:30 | D1、D2 `decision-settle --dry-run` + `build-context` | 预演补漏 |
| Nutmeg-临场数据刷新 | 17:15 | `run-strict --stage am` | 17:15 加场；空盘日 2026-10-02 起不再报失败与告警 |

停用：收盘 19:00、每日最终决策 18:20、早间复盘对齐 08:20、最终决策受限补跑 18:40、收盘前闸门 18:50（真票路径改为 `betslip preview` → 500 app → `betslip register`）。

## 已退役

| Label | 退役日 | 原因 |
|---|---|---|
| `com.nutmeg.zucai.f2-observe` | 2026-10-02 | 只服务 F2；F2 冻结窗口内到不了 n_min，26131 起观察单为空；F2 与依赖它的 F1c 一并 `rsi deploy --retire`（证据 `docs/superpowers/evidence/2026-10-02-ops-review.md` §4） |
| `com.nutmeg.decision.close` / `decision.settle`（launchd） | 2026-09 | 由 `day.settle` 与 `betslip register` 取代，从未装载 |

## 排障

1. `uv run nutmeg ops-status`：launchd / OpenClaw / 待办一屏，每条结局带日志时刻（不默认它是今天的）；月度任务按 32 天判久未更新。
2. `.nutmeg-data/logs/<label 去前缀>.out.log` / `.err.log`。
3. `uv run nutmeg decision-web` → `/runs/<日>`：每个定时器当天的计划时刻、实际运行与证据文件。
