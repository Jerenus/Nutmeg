# RSI 改造工程 · 架构与方案设计档案

**范围**：`e4e1205`（2026-09-18 16:59）→ `c749c03`（2026-09-19 13:13），**75 条提交**
**规模**：44 个新模块、30 个新测试文件 / 167 个用例、8 条注册实验、内核迁移 v29+v30、3 个新 CLI 子组
**用途**：给未来的会话与代理一份可对齐的全景。**读这份之前先读 `docs/sop/CONSTITUTION.md`**——
本工程的每一条设计都是宪法的机器化，不是新立法。

---

## 0. 一句话

把「判断 → 下注 → 复盘 → 改规则」这个原本只活在聊天窗口里的循环，
变成**一组只追加的内核对象 + 一条可从页面按完的流水线 + 一个只读的全景观察台**；
并且在这个过程中，第一次量出了这套系统真正的状态。

---

## 1. 为什么做（出生事故清单）

每一块设计都对应一次真实事故。**没有事故的设计不在本工程里。**

| 事故 | 日期 | 后果 | 落成了什么 |
|---|---|---|---|
| 页面提问无人应答 | 26129 | `user_message` 落盘、`agent_reply` 无进程监听，我在终端手写回复 | 阶段二·追问应答器 |
| SFC-B→C→D→E 四轮只活在聊天 | 26129 | 仓里只剩终版，第二天在 app 里什么都看不到 | 阶段三·候选树 + 回放 |
| F1c 两次断采 | 09-14 / 09-18 | 「该谁在何时做」只在 prereg 散文里；前瞻样本不可回补 | RSI 层·duty 对象 |
| 五份 prereg 五种字段 | — | 程序读不了；RULEBOOK 34 条 probation 无战绩挂载 | RSI 层·登记原件 + 状态投影 |
| 26127「严格空间零解」是假的 | 09-17 | 用户的票落在**声明空间**的缝里，合法空间有 33,745 个解 | 专项·枚举器（声明空间消失） |
| 26114 改买面违反自己刚立的 C8 | 08-14 | `faces` 是人手写字符串，无人校验它与判读一致 | 专项·`face_status` + faces 派生 |
| 「为什么是 768+256+40+100」无对象 | 26129 | 资金分配只在聊天与裁决单散文里 | 专项·`zucai_capital_plan` |
| 竞彩判读只以散文存在 | 长期 | corpus v2 里竞彩 532 行只有价格没有标签 | 深研桥 |
| 首跑后板上 26 场只有 1 场有 Read | 09-19 | 25 场被预算挡掉的比赛**一条判断都没有** | R2·每场都出 Read |

---

## 2. 五层架构

```
┌─ 观察层（只读）  /observe · /observe/exp/<id> · /observe/day/<date>      ECharts 5.5.1
├─ 专项层（结构）  plan tiers → frontier → choose → commit                 zucai_capital_plan
├─ 判读层（判断）  zucai-build-reads / research run → face_status → Read   人 approve
├─ RSI 层（治理）  Experiment / Duty / Observation / Grade / Verdict / Deployment
└─ 内核（权威）    Ontology Kernel v2 · typed Actions · action_permissions
```

**层间铁律**：
- 专项层**只读**判读层，永不重判；判读层永不写结构。
- RSI 层**只治理**，不产生判断也不产生票面。
- 观察层**零写操作**（测试断言无 `<form>`、无 POST）。
- 每层之间只经 typed Action 或只读 repository，无旁路。

### 2.1 各层交付物

| 层 | 模块 | CLI | 内核表 |
|---|---|---|---|
| RSI | `ontology/rsi/models.py`、`repository/rsi.py`、`actions/rsi_actions.py`、`decision/rsi_{prereg,grading,wiring}.py` | `nutmeg rsi` 10 条 | `rsi_experiments` 等 8 张（v29） |
| 专项 | `decision/{face_status,structure_tiers,structure_space,plan_flow,capital_rules}.py`、`actions/capital_actions.py` | `nutmeg plan` 5 条 | `zucai_capital_plans`（v30） |
| 深研桥 | `decision/{jczq_board,research_prompt,research_runner,jczq_reads}.py` | `nutmeg research` 3 条 + `jczq-build-reads` | 复用 ForecastRevision |
| 观察台 | `decision/observe_views.py` + `web/…/observe/*` | — | 只读 |
| 工作台 | `decision/{sop_tasks,workbench_responder,workbench_export}.py`、`interfaces/decision_web_kernel.py` | `workbench-respond`、`workbench-export` | 事件流 `workbench.jsonl` |

---

## 3. 七条不可协商的设计约束

这七条是**宪法在代码里的形状**，每条都有测试守。改它们要走 `rsi deploy`，不是改代码。

| # | 约束 | 落在哪 | 守护测试 |
|---|---|---|---|
| C1 | **判断永不入脚本** | SOP 任务栏没有 B3 深研 / B5 构票 / B6b ruling | `test_sop_tasks` |
| C2 | **falsifier 由代码判，人不得代判** | `rsi_record_verdict` 权限只有 `deterministic_system` | `test_rsi_actions::…system_only…` |
| C3 | **部署只许人** | `rsi_approve_deployment`、`zucai_commit_capital_plan` 只有 `judge_operator` | 同上 + `test_capital_plan_actions` |
| C4 | **重放结果进不了判决** | `record_verdict` 只读 `mode=prospective` 的 grade | `test_rsi_actions::…ignores_replay…` |
| C5 | **登记原件全冻结** | `frozen_hash` 覆盖 claim/mechanism/falsifier/window/分档；amend 碰即拒 | `test_rsi_actions::…frozen…` |
| C6 | **应答器只解释不判断** | 回复含「建议买/应该排/改成」→ 拒答留痕 | `test_workbench_responder` |
| C7 | **泄漏拒收而非静默丢弃** | grade 的输入行晚于当日最早开球 → `LeakError` 点名期号 | `test_rsi_grading::…refused…` |

**两条元规则**：`inconclusive ≠ survived`（不许原地延窗，只能另立 exp_id）；
**gap 是事实不是罚分**（前瞻窗过了不可回补，赛后补的产物记录但不算履行）。

---

## 4. 借鉴：Dream-RSI（arXiv 2609.14858）

| 论文机制 | 我们的落法 | 差异 |
|---|---|---|
| 发现树（节点=产物+诊断+分数，有父边） | `candidate` 事件加 `parent_version` | — |
| 冻结历史当重放模拟器 | `replay_spec` + `rsi grade --mode replay` | — |
| 前缀可见、不许偷看未来 | 重放与 grade 强制 `as_of = 当日最早开球`，晚于它**拒收** | 我们是拒收不是丢弃 |
| 冻结 agent、只改元策略 | `layer`：judgment 不可重放、最高 observation；structural 可 deploy | — |
| 每轮 M 个候选、重放排序 | `rsi dream --family` + `variants_tried` 进原件 | 多重比较显式化 |
| 必须重新在线部署以免停滞 | **硬门**：verdict 只读 prospective 档 | 论文是建议，我们是铁律（C7 训练窗 +12.0pp → 测试窗 −0.7pp） |
| 加权和目标（质量 − β₁成本 + β₂并行） | **不移植** | 宪法是字典序，EV 禁入决策层；grade 记 metric 与 `cost_axis_pp` 两轴不折算 |

**不可移植的现实**：论文有确定性评估器、可无限重放，50× 省算力；
我们每期只有 14 场、一场只开一次。**我们稀缺的不是算力，是前瞻样本**——
dream 的价值不在快，在于**别把前瞻配额浪费在重放就能否掉的假设上**。

---

## 5. 这次工程量出来的真实状态（最重要的一节）

设计可以再改，**这些数字是系统当前的体检报告**。

### 5.1 天平从不动

```
446 场判读，belief 拨离 prior 的只有 40 场 = 9.0%
26110 之后 22 期、308 场 —— 一次都没拨动过
26129 全部 14 场深研，belief 与 prior 逐场完全相等
```
**后果**：Brier vs 市场恒等于 0——不是没技艺，是**没有表达**；
判读层实验（F1c/F2）测的其实是市场结构，不是我们的判断力。
→ 立 **F9 天平位移账**：每期记拨动几场 / 偏移多少 / 方向对错 / Brier 相对市场。
**`0/14` 是合法值，而且这个零是所有「找信号」实验的基线。**

### 5.2 三证几乎杀不死面

```
全历史 294 个面，判死 10 个 = 3.4%
26122/26123/26124/26126/26129 五期 = 0，而 26129 那 14 场是全部深研过的
```
→ 立 **F8 死亡三证门槛**实验。⛔不许拍脑袋放宽，重放「两证 + fair≤X%」看会多杀哪些面。

### 5.3 任九的结构性不可能

票级上限 `TICKET_MAX_NARROWINGS = 3`（= C17 铁律）意味着 9 场里最多 3 场能收窄：
```
最省一张票 = 2³ × 3⁶ = 5,832 注 = ¥11,664   ≫ 任何合理帽
```
**→ 任九的可行结构只能来自第一序（把面判死），不能来自第二序（收窄）。**
26129 是活证：14 场三面全 alive、全板只有 1 个可收窄面 → 空前沿，如实。

### 5.4 门的代价可量化

26128 实测：实票 P **31.41%** → 腿级 ERROR 过滤后 **11.32%** → 再加 C17 标记 ≤3 后 **6.94%**。
→ F4 每期自动记 `gate_cost_pp = maxP(矩阵) − maxP(strict)`；strict 空解时记 `None` 不计。
**空仓从此是对着一个数字做的选择，不是从空集里退出来。**

### 5.5 已被证伪的立论（规则动作可留，立论必须改写）

| 立论 | 检验 | 结果 |
|---|---|---|
| 锚方完整度是最强单因子 | n=70 | pass **−6.8pp** / fail **+0.0pp** —— 方向相反 |
| conf 分档预测正路兑现 | n=428（控价格） | 各档 CI 全含 0；conf3 反而 > conf4 |
| C6/C10 标记双选 → 断腿 | n=223 | 原始差 +8.3pp **被价格完全解释**，控后 +1.5pp |
| C7 活先例（r3 双证） | n=67/355 | 训练窗 +12.0pp → **测试窗 −0.7pp** |

---

## 6. 八条在跑的实验

| id | 层/档 | 总体 | falsifier | 现状 |
|---|---|---|---|---|
| F1c 书商分歧度 | judgment/observation | zucai | 上四分位 top1 残差 ci_upper < +2pp | observing 0/140，gaps 4 期（26125–26128 永久缺） |
| F2 让球线位移 | judgment/observation | zucai | 主胜残差 ci_upper < +2pp | observing 10/140 |
| F3 policy-top60 | structural/deploy_eligible | zucai | BSS ci_lower < 0 | registered 0/120 |
| F4 门代价 | structural/observation | zucai | 中位 ci_upper < 5pp | observing 0/12 |
| F5 价格带 | structural/candidate | both | gap12 带残差 | registered 0/120（`variants_tried=20`，多重比较已记） |
| F8 三证门槛 | structural/candidate | zucai | 放宽档兑现率 ci_upper < 现行 +2pp | 新立 |
| F9 天平位移 | judgment/observation | both | 拨动场 Brier 相对市场 ci_upper < 0 | 新立，n=0 |
| R0 深研覆盖率 | judgment/observation | jczq | 覆盖率 ci_lower < 80% | observing 0/200 |

**登记原件**在 `experiments/registry/*.json`（人手写，摄入一次后**内核是唯一权威**）。
`uv run nutmeg rsi status` 一屏答出：状态 / n_cum / CI / 距 falsifier / gaps / 下一期义务。

---

## 7. 一天的完整流水线（26130 起）

```
11:00  zucai-prep --slot morning ──┬─→ rsi schedule + rsi due（义务自动排）
14:00  zucai-prep --slot afternoon ┘   └─→ 按 due 列出的 instrument 自动执行
       decision-am ──→ research board ──→ rsi schedule（竞彩 per-match duty）
       research run --day ──→ research intake --write ──→ jczq-build-reads ──→ decision-read
                              （每场都出 Read：研到的 ai:jczq-analyst / 没研到的 market-anchor）
       zucai-build-reads ──→ face_status（第一序落成字段）
       plan tiers ──→ 今日风向 + T1–T4 定级（B5c 矩阵机器化）
       plan frontier ──→ 帽内 Pareto 前沿 + strict 地板（第二序机器化）
       plan choose ──→ 人在前沿上挑（第三序 + 刹车）
       decision-audit-legs ──→ decision-adjudicate（ERROR 行权走裁决单）
       plan commit ──→ zucai_capital_plan（帽来源三态 / 三个 maxP 并排 / 门代价）
       betslip register ──→ 实票入账（没入账=没打）
18:30  prep-revision ──→ 位移复核
次日   decision-settle ──→ rsi balance（F9）──→ rsi grade ──→ 到期 rsi verdict
随时   /observe 看全景 · /observe/day/<date> 看候选树与资金方案 · /replay 看过程
```

---

## 8. 工程纪律（血泪换来的）

| 教训 | 处置 |
|---|---|
| `git add -A` 把 26 个别人的文件扫进 3 个 commit | **只用显式路径**，永不 `-A`/`-u`/`.`；新文件先 `git add` 再 commit |
| `git commit \| tail` 吞掉退出码，「以为提交了」 | 提交**不接管道**；`echo "EXIT=$?"` 后 `git log --oneline -1` 复验 |
| 主循环提交与子代理改文件重叠 → 钩子误判「files were modified」 | **提交与派活不重叠**；提交期间不编辑任何文件 |
| pre-commit 被系统 OOM 杀掉，stash 不还回 | 去 `~/.cache/pre-commit/patch*` 找最新补丁 `git apply` 捞回，按文件数核对 |
| 子代理报了一条**从未创建**的 commit sha | 每条交付**自己 `git log` 复核**，不信报告 |
| 转贴链路断了，意见送不到，同一任务重做三次 | 审查意见**写进仓里的 md**，只让对方 `cat <路径>` |
| 我用 `git checkout` 回退别人的文件，覆盖了他的工作区 | 并发时**不用 checkout 回退**别人的文件 |

---

## 9. 未完成与已知边界

**未完成**
- 第二轮四条（R2/R3/F8/F9）实施中（GPT 5.6 sol 在做，见 `plans/2026-09-19-REVIEW-round2-every-match-judged.md`）
- `rsi grade` 只接 F2、F4 两个适配器；F3/F5/F8/F9 的 harness 待各自观察产物成形
- F6（B5c 矩阵）、F7（第三序分配）只在 spec 里，样本要等 26130 起的候选树
- 26129 的 4 个方案号待补；26129 结算未做

**已知边界**
- `kickoff_bj` 真格式是 `"2026-09-19 00:30"`（空格无秒），字符串比较前必须归一
- `population=both` 的分层是硬规则：两层符号相反且 CI 不重叠 → 合并层 `inconclusive`
- 深研成本：每场一次带联网 opus 调用，实测 140–147 秒/场；28 场 ≈ 35 分钟订阅额度
- 观察台 `/observe` 的「风向」依赖 `<issue>-tiers.json`，没跑 `plan tiers` 时降级显示「今日未定级」

**下一步的自然顺序**
1. 四条落地 → 明天起每天 26 条样本入账
2. 26130 跑一期完整流水线（出口条件：聊天窗口里不出现票面）
3. F4/F9 攒到 n → 第一批真判决
4. F6/F7 登记 → 结构层实验开始吃候选树

---

## 10. 索引

**设计**：`specs/2026-09-18-rsi-experiment-persistence-design.md`（RSI 层）、
`specs/2026-09-19-zucai-structure-lane-design.md`（专项）、
`specs/2026-09-19-jczq-board-research-bridge-design.md`（深研桥）、
`specs/2026-09-19-rsi-observatory-design.md`（观察台）

**计划**：`plans/2026-09-18-app-phase{1,2,3}-*.md`、`plans/2026-09-18-rsi-experiment-persistence{,-part2,-part3}.md`、
`plans/2026-09-19-zucai-structure-lane{,-part2}.md`、`plans/2026-09-19-jczq-board-research-bridge.md`、
`plans/2026-09-19-rsi-observatory.md`

**审查**：`plans/2026-09-19-REVIEW-corrections-for-gpt.md`（四条）、
`plans/2026-09-19-REVIEW-round2-every-match-judged.md`（R2/R3/F8/F9）

**交接**：`plans/2026-09-19-gpt-handoff-prompt.md`（三阶段 20 任务的完整执行协议）

**运行**：`docs/sop/RUNBOOK.md`（泳道 A/B + 非决策附录）、`docs/sop/CONSTITUTION.md`、`docs/sop/RULEBOOK.md`
