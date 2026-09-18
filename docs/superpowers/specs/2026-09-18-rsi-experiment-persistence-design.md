# RSI 过程持久化 · 设计（Experiment 作为一等内核对象）

日期：2026-09-18 ｜ 状态：设计已获用户逐段批准，待用户审阅本文 ｜ 后续：writing-plans

## 0. 一句话

把「假设 → 预注册 → 按期采样 → 结账 → 判决 → 上线」这条今天散落在五种格式里的回路，
做成 Ontology Kernel v2 里一组**只追加**的 typed Action；状态全是投影；**判据入代码、部署留给人**。

## 1. 出生事故（为什么现在做）

- **F1c 两次断采**：2026-09-14 一次性批处理后停在 26124；2026-09-18 修正案写「26129 起每期必须落分歧度观察单」，
  当天 19:20 才发现采集仪根本看不见 26129（`t7-backfill.json` 停在 26124）。前瞻窗的样本不可回补——漏一期是永久损失。
  根因：**「这件事该谁在何时做」只存在于 prereg 的散文里，没有任何对象记着它。**
- **五份 prereg 五种字段结构**（`experiments/prereg-*.json`），无法被程序统一读；规则状态词（probation 34 / live 7 /
  promoted 3 / candidate 3 / retired 1）只在 RULEBOOK 散文里。
- 08-23 重构设计写明「RULEBOOK 是生成物、禁手改、从 rules.jsonl 渲染」，至今内核里没有 Rule / Experiment 对象，该设计无数据源。
- **「没证伪就当成立」的形状反复出现**：C7 活先例训练窗 +12.0pp → 测试窗 −0.7pp；「被排面链」同形。

## 2. 用户裁定（本设计的约束，逐条有出处）

| # | 裁定 | 来源 |
|---|---|---|
| U1 | 第一个兑现场景：F1–F5 每条假设的状态 / 累计样本 / falsifier 距离 / 下一步该谁做，不翻记忆直接查得出 | 2026-09-18 问 1 → A |
| U2 | 按期到期的义务（duty）是一等公民，备料链可按它自动执行 | 问 2 → A |
| U3 | falsifier / stop_rule 由代码判，人不得再议；`survived → 上线` 只许人扳 | 问 3 → A |
| U4 | 住内核（typed Actions），登记走 B4 判读桥同一模式：人写原件 → 摄入一次 → 内核唯一权威 | 方案一 |
| U5 | 登记原件**全冻结**（含 mechanism）；理解深化以 amendment 追加，不改原件 | 第一段反馈 1 |
| U6 | 采样缺口是事实记录不是罚分：单场赛果无权翻转判决；过程失职（观察单未落）记 `gap`，实验照跑、多等一期 | 第一段反馈 2 |
| U7 | `inconclusive ≠ survived`；到窗末仍 inconclusive 只许人 `extend`（另立新实验）或 `retire`，不许原地延窗 | 第二段 |
| U8 | Dream-RSI 六条并入（见 §7） | 2026-09-18 论文讨论 |
| U9 | **实验总体的原子单位是「场 × 渠道」**，当天传统足彩 + 竞彩全板都是样本；SFC/任九/串关是吃逐场判读的下游「专项」 | 用户提案 |
| U10 | **每场都深研**（`judgment_tier = deep_research` 为目标）；字段如实记录实际达到的深度 | 问 A/B/C → C |

## 3. 范围与切分

本 spec 只做 **RSI 持久化本身**，在足彩板上可立即实施与测试。以下各自独立成 spec，依赖关系如图：

```
[本 spec] RSI 持久化（Experiment/Duty/Observation/Grade/Verdict/Deployment）
     ▲ 读                    ▲ 喂样本
     │                       │
[② 观察界面]        [A 泳道全板深研桥]（前提：竞彩每场结构化判读 + research-intake 扩到 jczq）
                             ▲
                     [专项层]（SFC/任九/串关：吃当日逐场判读 + 候选树，出票面与资金组合）
```

- **A 泳道全板深研桥**是 U9/U10 成立的硬前提：今天竞彩判读只以散文存在（`nutmeg-handoff.json`），没有结构化 legs。
  没有它，竞彩样本只有价格没有标签，判读层实验一行也用不上。它是**下一份 spec**，不在本文实现范围。
- 本 spec 的对象模型从第一天就按 U9 设计（场级总体、按日时钟、渠道分层），足彩板先跑，竞彩板接上即用，不需要改模型。

## 4. 对象模型

七类**只追加**的记录。没有任何一张表有可改写的 `status` 列；状态是投影。

| 记录 | 一条 = | 关键字段 | 谁写 |
|---|---|---|---|
| `experiment` | 一条假设的**登记原件** | `exp_id`（F1c/F2/…）、`claim`、`mechanism`、`tier`、`layer`、`population`、`min_tier`、`window`、`falsifier`（结构化）、`stop_rule`、`quota_slot`、`rule_ids`、`replay_spec`、`dream_ref`、`variants_tried`、`source_doc`、`registered_at`（**原登记日**）、`frozen_hash` | 人（`rsi register`） |
| `experiment_duty` | 一条按日义务的定义 | `recurrence = per_day`、`deadline_rule`（`earliest_kickoff` / `match_kickoff`）、`scope`（`day` / `match`）、`instrument`（argv）、`artifact_glob` | 登记时生成 |
| `duty_instance` | 义务在某一天（或某一场）的实例 | `(duty_id, day[, match_id])`、`due_at`、`fulfilled_at`、`artifact_path`、`artifact_hash` | 系统 |
| `experiment_observation` | 某天为某实验采到的一份样本 | `day`、`population_stratum`（zucai / jczq）、`n_rows`、`captured_at`、`prospective`（早于当天最早开球）、`judgment_tier_hist`（各档行数）、产物哈希 | 系统 |
| `experiment_grade` | 一次结账算数 | `mode`（`replay` / `prospective`）、`stratum`（zucai / jczq / pooled）、`n_cum`、`metric`、`ci_low` / `ci_high`、`distance_to_falsifier`、`cost_axis_pp`（P 帽代价，独立轴）、`as_of_policy`、`computed_by`（脚本 + git sha）、`inputs_hash` | 系统 |
| `experiment_verdict` | falsifier 判定 | `verdict`（falsified / survived / inconclusive）、`grade_ref`（**必须是 prospective 档**）、`criterion_snapshot`（当时冻结的判据全文） | **仅 deterministic_system** |
| `experiment_deployment` | 上线 / 搁置 / 废止 / 延续 | `decision`（deploy / hold / retire / extend）、`rule_id`、`reason`、`adjudication_ref`、`extend_to_exp_id` | **仅 human** |
| `experiment_amendment` | 修正案 | `what`、`why`、`rule_check`、`mechanism_note`、`touches_frozen`（真 → 拒绝） | 人 |

### 4.1 字段定义

- `tier ∈ {candidate, observation, deploy_eligible}`：candidate = 只入档不采；observation = 采样但永不进票面；deploy_eligible = survived 后可申请上线。
- `layer ∈ {judgment, structural}`（U8-⑤）：judgment = 关于判读质量的实验，总体是场级行，**不可重放**（判读是人）；structural = 关于规则 / 门 / 面集表达的实验，总体是候选树上的票面节点，**可重放、可 deploy_eligible**。judgment 层实验 `tier` 最高只能是 observation。
- `population ∈ {zucai, jczq, both}`（U9）：声明样本来自哪板。`both` 的 grade 必须分层 + 合并三份。
- `min_tier ∈ {price_only, light_read, deep_research}`：该实验只吃 `judgment_tier ≥ min_tier` 的行。价格类实验 `price_only`；判读类实验至少 `light_read`；U10 下目标是全部 deep，但字段记实际。
- `window = {population, date_from, date_to?, n_min}`：**新实验用日期 + n_min 表达**；在跑的五条保留原「期号」窗（§9）。
- `falsifier = {metric, stratum, n_min, bound: "ci_upper"|"ci_lower", threshold_pp, direction}`：结构化，代码可判。示例 F2：`{metric:"home_resid_pp", stratum:"zucai", n_min:140, bound:"ci_upper", threshold_pp:2.0, direction:"lt_means_falsified"}`。
- `frozen_hash = sha256(canonical_json(claim, mechanism, tier, layer, population, min_tier, window, falsifier, stop_rule, quota_slot, buckets))`（U5：全冻结）。
- `replay_spec = {harness: "experiments/exp-xxx.py::fn", corpus: "experiments/corpus-v2.json", variants: [...]}`（U8-②）。
- `dream_ref` / `variants_tried`：若由 `rsi dream` 产生，记录来源与该轮比较过的变体数（U8-⑥，多重比较显式化）。

### 4.2 状态投影（不落表，查询时算）

`registered → observing → graded → falsified | survived | inconclusive → deployed | held | retired | extended`

- `observing`：存在 ≥1 条 observation。
- `graded`：存在 ≥1 条 `mode=prospective` 的 grade 且 `n_cum ≥ falsifier.n_min`。
- `falsified / survived / inconclusive`：最新 verdict。
- `deployed / held / retired / extended`：最新 deployment.decision。
- `integrity.gaps = [day…]`：所有过了 `due_at` 且无 `fulfilled_at` 的 duty_instance 的日期（U6：事实，非罚分）。
- `next_due = {day, due_at, instrument}`：下一个未完成的 duty_instance（U1「下一步该谁做」）。

## 5. 状态机与判定规则（写死，测试守）

| 规则 | 含义 |
|---|---|
| grade 每天可跑，verdict 只在到期跑 | 中途看得见数字看不见判决；`rsi verdict` 未到 `n_min` → 拒绝并报差额 |
| verdict 只认 prospective | `grade_ref` 指向 `mode=replay` 的 grade → 拒绝（U8-③ 硬门） |
| verdict 只认 CI 边界 | `falsified` ⇔ 冻结判据成立；`survived` ⇔ 反向成立；其余 `inconclusive`（U7） |
| 分层优先 | `population=both` 时先分层判；两层符号相反且 CI 不重叠 → 合并层 `inconclusive`（U9-①） |
| 单场无权翻转 | grade 每行等权，CI 由 bootstrap 出；红牌那一场在 n=140 里就是 1/140（U6） |
| gap 不改判据 | 缺几天就多等几天到 n_min；**不许**用别期或语料回补 |
| inconclusive 有出口 | 到 `window.date_to` 仍 inconclusive → 人 `extend`（另立 exp_id，`extend_to_exp_id` 回链）或 `retire`；**不许**改 window |
| deploy 只此一门 | survived 且 `tier=deploy_eligible` 且 `layer=structural` → 人 `approve_deployment(deploy, rule_id, reason)` 并落 Adjudication；judgment 层永不 deploy |
| 两轴不折算 | grade 记 `metric`（命中残差 pp + CI）与 `cost_axis_pp`（P 帽代价）两个字段，不产生加权标量（宪法字典序，U8-反） |
| 泄漏拒收 | replay 与 grade 的输入行，任一 provenance 时间戳晚于该日最早开球 → **拒收并报告**，不是静默丢弃（U8-④） |

### 5.1 权限（落 `action_permissions` 表，不靠自律）

| action_type | human | deterministic_system | 说明 |
|---|---|---|---|
| `register_experiment` | ✅ | ❌ | 登记是判断 |
| `schedule_duties` | ✅ | ✅ | 备料链调 |
| `fulfill_duty` / `capture_observation` | ✅ | ✅ | 观察仪调 |
| `grade_experiment` | ✅ | ✅ | 算数 |
| `record_verdict` | **❌** | ✅ | 人不能替 falsifier 说话（U3） |
| `approve_deployment` | ✅ | **❌** | 代码不能把东西推进票面（U3） |
| `amend_experiment` | ✅ | ❌ | `touches_frozen` 为真时 Action 内部拒绝 |

## 6. 义务（duty）的一生

1. `rsi register` 时，从原件的 `duties[]` 生成 `experiment_duty`。示例 F2：
   `{recurrence:"per_day", scope:"day", deadline_rule:"earliest_kickoff", instrument:["python","scripts/zucai_f2_observe.py","record","--issue","{issue}"], artifact_glob:".nutmeg-data/zucai/{issue}-f2-observation.json"}`。
   U10 下深研也是 duty：`{scope:"match", deadline_rule:"match_kickoff", instrument:<由「A 泳道全板深研桥」spec 定义的每场深研命令>, artifact_glob:".nutmeg-data/zucai/{issue}-research-m{match_no}.json"}`——
   本 spec 只保证 duty 机制能承载它；该 instrument 在深研桥落地前不注册。
2. 备料链 B0/B1 末尾调 `rsi schedule --day <业务日>`：读当日两板赛程（`<期>-issue.json` + 竞彩日板），
   为每条 observing 实验的 per_day / per_match duty 生成 `duty_instance(due_at)`。
3. `rsi due --day <业务日>` 列出 pending：几点前、跑哪条 instrument；备料链**按它自动执行**（F1c 的洞在此焊死）。
4. 观察仪跑完调 `rsi fulfill --exp F2 --day … --artifact <path>`：登记哈希、行数、`prospective`。
5. 过 `due_at` 仍无产物 → 投影 `gap`；之后补产物**仍是 gap**（前瞻窗过了不算）。

## 7. Dream-RSI 六条（U8，全部是对 §4–6 的加法）

| # | 论文机制 | 我们的落法 |
|---|---|---|
| ① | 发现树：节点 = 产物 + 诊断 + 分数，有父边 | 阶段三 `candidate` 事件加 `parent_version`；每个业务日的候选票面成一棵树。**属阶段三补丁，本 spec 只依赖它存在** |
| ② | 在冻结历史上重放另一策略 | `experiment.replay_spec`；`rsi grade --mode replay` 在 corpus / 候选树上跑变体 |
| ③ | 上线前必须真在线 rollout | **硬门**：verdict 只读 prospective 档 grade；replay 再好看进不了判决。有测试 |
| ④ | 前缀可见、子节点确定性揭示 | 重放器与 grade 对每日强制 `as_of = 当日最早开球`，晚于它的行拒收并报告 |
| ⑤ | 冻结 agent / 评估器，只改元策略 | `layer`：judgment 层不可重放、最高 observation；structural 层可重放、可 deploy |
| ⑥ | 每轮 M 个候选修订，重放排序 | `rsi dream --family <spec>`：在冻结语料上重放一族变体 → 排序表 + `variants_tried`；赢家可 `rsi register --tier candidate --dream-ref …`，`variants_tried` 进原件（多重比较显式） |

不移植：加权和目标（宪法字典序）；「省算力」叙事（我们稀缺的是前瞻样本，dream 的价值是**别把前瞻配额浪费在重放就能否掉的假设上**）。

## 8. 命令面

全部在 `nutmeg rsi …`，每条 = 一个 Action，**没有绕过 Action 写表的路径**。

| 命令 | Action | 执行者 |
|---|---|---|
| `rsi register <prereg.json> [--tier …] [--dream-ref …]` | `register_experiment` | 人 |
| `rsi schedule --day <业务日>` | `schedule_duties` | 系统（备料链） |
| `rsi due --day <业务日>` | 只读 | — |
| `rsi fulfill --exp … --day … [--match …] --artifact <path>` | `fulfill_duty` + `capture_observation` | 系统（观察仪末尾） |
| `rsi grade --exp … --mode prospective\|replay` | `grade_experiment` | 系统 |
| `rsi verdict --exp …` | `record_verdict` | 仅系统 |
| `rsi deploy --exp … --rule … --reason …` / `--hold` / `--retire` / `--extend <new_exp_id>` | `approve_deployment` | 仅人 |
| `rsi amend --exp … --what … --why … [--mechanism-note …]` | `amend_experiment` | 人 |
| `rsi dream --family <spec.json>` | 只读 + 可选 register | 人触发 |
| `rsi status [--exp …] [--day …]` | 只读 | — |

### 8.1 与现有链条的三处接线（加一行，不改语义）

1. **备料链**：`zucai-prep`（B0/B1）末尾 → `rsi schedule` + `rsi due` 并按 instrument 执行。
2. **观察仪**：`zucai_f2_observe.py record`、`zucai_book_dispersion.py` 产物落盘后 → `rsi fulfill`。采集口径、BUCKETS、泄漏纪律**一字不动**。
3. **结算**：`zucai-settle` 之后 → 对所有 observing 实验 `rsi grade --mode prospective`；到期者自动 `rsi verdict`。

### 8.2 读侧（给②用）

`ProductReadRepository` 新增：`experiments(as_of)`、`experiment_timeline(exp_id, as_of)`、`duties_due(day)`。与判读工作台同一 repository、同一 `as_of` 口径。

## 9. 迁移

- 五份旧 prereg 各写一份新格式原件 `experiments/registry/<exp_id>.json`，字段从旧文件搬，`source_doc` 指回旧文件；旧文件保留。
- `registered_at` 取**原登记日**（F2 = 2026-09-14），不是摄入日。
- **在跑的窗口不重新索引**（U9-②）：F1c/F2 窗仍是「26129–26140 / 26126–26137、population=zucai、min_tier=price_only」；
  用 `window.issue_from/issue_to` 兼容字段表达，代码同时支持日期窗与期号窗。
- 回填观察：F2 ledger 26126/26127/26128 → 三条 `capture_observation`；t7-dispersion 26129 → 一条；**F1c 的 26125–26128 记 gap**（真缺，不造数据）。
- schema 升级一版（`migrations.py` 照 `_apply_governance_kernel` 模式），含权限种子；可重跑、有校验和。
- `scoreboard.json` 本 spec 不动；`experiment_deployment.rule_id` 用 RULEBOOK 现有码（C0–C18 等），供②与未来 RULEBOOK 渲染回链。

## 10. 测试（守规则的最重要）

- **权限**：human 调 `record_verdict` → 拒绝；deterministic_system 调 `approve_deployment` → 拒绝。
- **冻结**：amend 碰任一冻结字段 → 拒绝；`mechanism_note` 追加 → 通过且原件不变。
- **判定**：n<n_min 调 verdict → 拒绝并报差额；n≥n_min 三种 CI 形态 → falsified / survived / inconclusive 各一；到窗末 inconclusive **不**自动变 survived。
- **重放硬门**：verdict 引用 `mode=replay` 的 grade → 拒绝。
- **分层**：`population=both`、两层符号相反 CI 不重叠 → 合并层 inconclusive。
- **泄漏**：输入行 provenance 晚于当日最早开球 → grade 拒收并列出行号。
- **gap**：过 `due_at` 无 artifact → gap；之后补 → 仍 gap；gap 不改 n_min。
- **幂等**：同一 exp_id 二次 register → 拒绝；同一 (exp, day) 二次 fulfill → 不重复计数。
- **两轴**：grade 记录里不存在任何由 metric 与 cost 合成的标量字段。
- **层**：`layer=judgment` 的实验 register 时 `tier=deploy_eligible` → 拒绝。
- **迁移**：五份摄入后 `rsi status` 数字与旧文件一致（F2 n=33 等）；F1c gaps = [26125,26126,26127,26128]。

## 11. 出口条件（这份 spec 做完的标志）

`uv run nutmeg rsi status` 一屏答出 U1 的四个问题（状态 / n_cum / 距 falsifier / next_due）；
备料链在 26130 自动落两张观察单，不靠人记得；`rsi verdict` 对未到期实验拒绝；一个 human 调 `record_verdict` 被权限表拦下。
