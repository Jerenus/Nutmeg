# 运行层整修 · 落地证据（2026-10-02 晚）

起因：Jun 2026-10-02 三次要求——「加一个定时器」（月初账房）、「保持池子 rsi 的工作，保持 discovery harness 层的正确工作」、「播报换内容……F2……让球线观察也可以退役。解决剩余的问题」。
结构总图已同步到 `docs/ARCHITECTURE.md`；定时任务表在 `docs/ops/2026-09-20-scheduled-dataflows.md`。

## 1. 月初账房定时器（commit `fe103b9`）

| 项 | 内容 |
|---|---|
| 定时器 | `com.nutmeg.account.month`，每月 1 日 16:10（15:45 二次结算之后） |
| 命令 | `nutmeg account month --previous --write`，打 `NUTMEG_OK / NUTMEG_FAILED` 标记 |
| 实跑 | 2026-10-02 用同一条命令出 9 月账：净 −4,721（投入 3,774，10 条入账），OK |
| 顺带修 | 「人的偏离」账在真实记分牌上崩溃（26131 等早期条目的 slips 是文字描述）→ 跳过非结构化行 |
| 顺带修 | 状态页与运行记录页把所有排程当每日：月度任务会从 3 号起天天报久未更新、每天 16:10 显示漏跑 → 按排程判（月度 32 天、周度 8 天、其余 2 天），月度/周度只在当天有计划，证据取上月报告文件写入时刻 |

## 2. 池子 RSI 与 Discovery Harness 体检（commit `c1cd735`）

见 `2026-10-02-rubric-judgment-contract.md` §7：空盘日 Dream / 深研链崩溃改为跳过；rubric 逐项因子在因子提案步 KeyError；rubric 永不导致深研拒收；`rsi status` 把 R1 的 37 条观测显示为 0；闭环两读步补读前一天、并发 4。

## 3. 截止播报换内容

**问题**：9 月 23–30 日共发 74 条，全部是「某场 Read 草稿待审批」。判断唯一事实 P2（10-01）后 Read 自动交本体，这一步已不存在；真正该提醒的「足彩停售前没登记」一条都没发过。

**改动**：
- `day_decisions.build_decisions` 不再生成 `approve_read` / `plan_choose_commit`；
- 新增两类、每次播报现算（`live_register_decisions`，不等 12:00/14:20/18:35 的报告）：
  - `register_zucai`：在售期停售前仍无已登记实票（主题带机器初稿注金与审票结论），默认「未登记＝空仓（不买）」；
  - `register_jczq`：当天 `betslip preview` 预审过竞彩方案、却没有登记实票，截止＝预审腿里最早未开球的开球时刻；
- `betslip preview` 每审一张记一行 `daily/<日>/previews.jsonl`（渠道、腿、注金、是否否决）；
- 播报作业与 `--dry-run` 都走 `broadcast_decisions`：去掉过时种类，加上现算的两类。

## 4. F2 与 F1c 退役

| 项 | F2 让球线位移 | F1c 书商分歧度 |
|---|---|---|
| 冻结窗口 | 26126–26137，n_min 140 | 26129–26140，n_min 140 |
| 为什么到不了 | 结账只数主档「向主 ≥+0.5」，9 期累计 11（约 1.2/期），12 期满窗约 15 | 已录 23 行，余 6 期满额 84，合计 107 |
| 另一个问题 | 26131 起观察仪 4 期观察单为空（让球线未抓到） | 采集仪靠 F2 观察单取当期 match_id，观察仪一停每期必失败 |
| 收尾 | 补结 26131–26134（0 行）；终账 n=11 残差 +9.0pp CI[−18.2,+34.3] | — |
| 动作 | `rsi deploy --retire --by op:jun`，理由写进部署记录 | 同左（随 F2 一并退役，是本轮的推论，Jun 可用 `--extend` 另立新实验恢复） |

**机制修复**：退役原先只追加一条部署记录，义务仍是 active，每小时巡检照跑观察仪 → `approve_deployment` 遇 retire 时把该实验全部义务置为 `retired`（`RsiRepository.set_duty_status`）；排程、到期、巡检都只认 active。F2 移出闭环的每日结账名单。

**定时器**：`com.nutmeg.zucai.f2-observe` 已 `bootout` 并从 `~/Library/LaunchAgents` 与 `ops/launchd/` 删除；运行记录页登记表同步删除。脚本 `scripts/zucai_f2_observe.py` 与账本保留作档案。launchd 由 15 个变为 14 个。

## 5. 足彩 legs-base 自动化（机器初稿不再依赖手跑 B4）

**问题**：初稿依赖 `<期>-legs-base.json`，它只来自泳道 B 的 B4（`zucai-research-intake` + `zucai-build-reads`），没有定时器跑。

**改动**：`zucai_auto_judgment.ensure_auto_legs_base`，挂在并集池刷新（`pool.refresh_day`，10:00 深研后、12:30/18:45 判决页刷新、入板后刷新都会跑）：
- 判断来源与自动 Read 相同（主循环 judgment-v1 永远优先 → 研究表态转录 → 市场锚定），fair 用 store-ids 里同一份；
- 每场把研究的结构字段与 rubric 经 `research_intake.intake` 转录，挂 face_status；
- 写入时带 `auto` 标记；**没有 `auto` 标记的手工 legs-base 一律不动**；
- 只处理截止当天的期次（与足彩研究的样本池一致）。

## 6. 早盘入板与 17:15 临场刷板在空盘日不再报失败

**问题**：国庆每天 08:00 早盘入板退出 1；OpenClaw 17:15「临场数据刷新」跑同一条命令，连败 2 次并向 Telegram 发失败告警。

**改动**：`nutmeg_scheduler_ops._only_empty_board`：当唯一的失败是体彩列表**完全为空**（0 在售、0 未开售、不是 WAF）时记为 `NUTMEG_OK … empty_board`，退出 0；列表里有未开售场次、或有任何其他失败，仍按失败处理。代价分析：若把一次短暂空响应误当空盘，10:00 深研链会再抓一次板面，损失是晚两小时而不是一天。实跑：2026-10-02 `run-strict --stage am` 输出 `NUTMEG_OK stage=am run_date=2026-10-02 empty_board`。

## 7. 验证

- 全量测试退出码 0（每个提交前都跑）；新增测试：`test_day_decisions`（两类现算决定、旧种类剔除）、`test_cli_betslip_preview`（预审留痕）、`test_cli_rsi`（退役停义务）、`test_zucai_auto_judgment`（自动 legs-base、手工版不覆盖、初稿可读）、`test_pool`、`test_nutmeg_scheduler_ops`（空盘与非空盘两种结局）、`test_ops_status` / `test_day_ops` / `test_day_runs`（月度排程）。
- 实跑：空盘日 Dream dry-run 返回 `board_too_small … (empty board)`；研究入库返回「空盘：入库跳过」；因子提案全量跑通；账房定时器命令出 9 月账；早盘入板空盘 OK。
- 内核：F2/F1c 状态 retired，义务 retired。

## 2026-10-06 实地验证：推送与定时任务修复（follow-ups 第 3 条结账）

10-05 夜的三处修复（`eb006f1` 推送降噪、`827be6e` 赛果回填只按有比赛的日子判过期、`aabcb05` 退役义务不排不跑）在 10-05 晚到 10-06 上午的实地结果：

| 时刻 | 任务 | 结果 |
|---|---|---|
| 10-05 17:15 | 临场刷新 | 成功，无 am degraded |
| 10-05 18:30 | 足彩备料复核 | 只因 4 条位移超门槛推送一次，符合新规则 |
| 10-05 23:00 | rsi sweep | F4 `nutmeg plan` 退出 2——发生在 `aabcb05`（23:01:58）提交之前，最后一次 |
| 10-06 08:00 | 早盘入库 | `NUTMEG_OK stage=am empty_board`（周二板 0 在售 / 24 未开售，合法空盘），退出 0；stderr 里的 `Sporttery calculator empty` 是走到空盘判定前的诊断，不触发推送 |
| 10-06 09:30 | 赛果回填 | 退出 0，「本轮 1 天，失败 0」，10-05 七场封存（1,314 → 1,321 场） |
| 10-06 09:45 | 结算 | 退出 0，10-05 两张竞彩 −¥200，七场 Brier 市场 0.4748 / 终判 0.4703 |
| 10-06 全天至 10:00 | sweep ×4、播报 ×N | sweep `ran=0 failed=0`；播报 `sent=0 failed=0` |

launchd 各任务最近退出码全为 0。`day.broadcast.err.log` 里的时区 TypeError 最后写于 09-24，是旧错误。结论：无误报，第 3 条关闭。
