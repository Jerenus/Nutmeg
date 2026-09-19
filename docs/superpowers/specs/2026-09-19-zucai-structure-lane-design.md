# 传统足彩专项（结构层）· 设计

日期：2026-09-19 ｜ 状态：设计已获用户逐段批准（含第二段修订），待用户审阅本文 ｜ 后续：writing-plans
依赖：`docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`（RSI 层，已落地 `c0f4578..5c1e936`）

## 0. 一句话

把 RUNBOOK 泳道 B 的 B5–B9（构票 → 审计 → 定案 → 入账）从「聊天窗口里的叙事砍腿」变成一条对象流：
**第一序落成 `face_status`，第二序由机器在 B5c 决策矩阵允许的范围内枚举前沿，人在前沿上挑，
资金方案是内核对象，每一版票面都在候选树上**。专项永不重判——它读判读，不产生判读。

## 1. 出生事故

- **26127**：用户的 3单3双3包落在我**声明**空间的缝里，而合法空间有 33,745 个解——第二序被叙事做掉了。
- **26129**：SFC-B→C→D→E 四轮迭代只活在聊天里，仓里只剩终版；「为什么是 768+256+40+100」没有任何对象记着。
- **26126 / 26128**：宪法第一序照字面（活→盖住或丢）算出「真零解」与 6.9%，与实践脱节；操作规则其实一直是 B5c 矩阵，但它是散文，枚举器读不到。
- **26114**：我改买面违反自己刚立的 C8——`faces` 是人手写的字符串，没有任何东西校验它与判读一致。

## 2. 用户裁定

| # | 裁定 | 来源 |
|---|---|---|
| Z1 | 专项对象 = **当日足彩资金方案**（SFC + 任九）；日帽 ¥2,000 与竞彩额度作外部约束传入；竞彩票面归其独立专项 | 问 1 → A |
| Z2 | 第二序由**机器枚举**，人在 Pareto 前沿上按第三序与刹车挑；行权走 B6b 裁决单 | 问 2 → A |
| Z3 | 第一序落成一等字段 `face_status ∈ {alive, dead, never}`，dead 必挂三证；`faces` 变派生 | 问 3 → A |
| Z4 | 方案一：三态 → 枚举器 → 前沿 → 资金方案；候选树留在事件流（不进内核，避免双权威） | 方案选择 |
| Z5 | **任九帽 ≤¥1,200**（常设行权，登记为 Adjudication）；「两票合计 ≤¥1,600」暂不动 | 第一段反馈 |
| Z6 | **不能太多全包**：收窄由判断质量定级（B5c 矩阵），枚举器只在级内取盖法；枚举前先出「今日风向」；strict 只作 F4 参考地板 | 第二段修订 |
| Z7 | `plan grade` 改名 `plan tiers`；竞彩票先登记、足彩后定案（日帽校验读 betslips） | 第三段反馈 |

## 3. 范围

本 spec：`face_status`（B4 扩展）、定级与风向、枚举器、候选树自动生长、`zucai_capital_plan` 内核对象、`nutmeg plan` 命令面、F4 接线、`rsi dream` CLI、26129 回填。
不在本 spec：竞彩深研桥（独立）、观察界面②（独立）、宪法 §2 措辞是否与 B5c 矩阵对齐（用户的事）。

## 4. 对象与字段

### 4.1 `face_status`（写在 legs-base 每场；B4 `zucai-build-reads` 产出）

```
face_status: { home|draw|away: { state, proofs, precedent, source } }
state     ∈ {alive, dead, never}
proofs    = {a_no_scoring_mechanism, b_precedent_carrier_gone, c_anchor_pass}   ← 研究 JSON death_three_proofs
precedent ∈ {alive, dead, none}                                                  ← C14 词典；none ≠ dead
source    = "<issue>-research-m<N>.json#death_three_proofs.<face>"
```
规则（在 B4，不在枚举器）：
- `dead` ⇔ 研究 `verdict == "dead"` **且** 三证 3/3（intake 已把「宣告死亡但三证不齐」做成 ERROR）。
- `never` **只许 judgment-v1 显式声明**（字段 `never_faces: ["away"]`），不从任何字段推导；尤其不从 `precedent == none` 推（C14：查无先例是举证缺席）。
- 其余一律 `alive`；字段缺失 = alive（举证责任在死的一方）。
- `faces` 派生 = alive 面按 3/1/0 顺序拼接；人写的 `faces` 与派生值不一致 → **ERROR**。
- 枚举器眼里 dead 与 never 同义（不盖）；区别只为复盘。

### 4.2 定级 `tier`（`plan tiers` 产出 `<issue>-tiers.json`；B5c 矩阵的机器读法）

判读字段的机器读法（**RULEBOOK 常量，只能经 `rsi deploy` 改**）：
- 四问分 `license_score = q1_spine + q2_route + (not q3a_opponent_scores) + q4_no_context_flag`（0–4）
- 完整度 `anchor_integrity ∈ {pass, fail, symmetric_damage}`
- 翻车 `crash_markers`（非空 = 有翻车标记）
- 每个 alive 面的三证数 `d3_count = a + b + c`（0–3）与 `fair`

| 级 | 每场最多收窄 | 触发 |
|---|---|---|
| T1 | 2（可裸单） | `license_score == 4 ∧ integrity == pass ∧ crash_markers 为空` |
| T2 | 1（可双选） | `license_score == 3 ∧ integrity ∈ {pass, symmetric_damage}` |
| T3 | 0（必全包） | 其余 |
| T4 | 建议丢（仅任九；T3 的子集，建议非强制） | T3 ∧ 三面全 alive ∧ max fair < 0.45（硬币） |

**单个 alive 面可被收窄** ⇔ `d3_count ≥ 2 ∧ fair ≤ 0.15`（B5c 原文「2/3 且被排面 ≤15% 可排」）。`fair > 0.20 ∧ d3_count < 3` 永不可收窄（原文「必须全包」）。15–20% 灰带不可收窄。
级数上限与面规则同时生效：T1 场也只能收窄满足面规则的面。

### 4.3 「今日风向」（`plan tiers` 同时产出，只读）

`{regime: hot|cold|coin, tiers: {T1:n, T2:n, T3:n, T4:n}, narrowable_faces: n, cap_band: low|mid|full, note}`
- regime：按 fair 分布——top1 ≥ 0.60 的场 ≥ 5 → hot；平局 fair ≥ 0.29 的场 ≥ 5 → cold；top1 < 0.45 的场 ≥ 6 → coin；否则 mixed。
- cap_band：`narrowable_faces ≥ 6 → full`；`3–5 → mid`；`≤ 2 → low`（建议，不决策）。

### 4.4 枚举器（`plan frontier`）

输入：legs-base（含 `face_status`）、`channel ∈ {renjiu, shengfucai}`、`cap_yuan`、`tiers.json`。
每场合法盖法 = alive 面集去掉 ≤ 级数上限个「可收窄面」的所有子集（任九另加「丢」）。
- **矩阵模式**（操作空间）：上述规则。
- **strict 模式**（宪法地板，只算 max P 供 F4）：盖全部 alive 或丢。
算术：P(全对) = ∏ Σ fair(盖面)；注数 = ∏ |盖面|；票价 = 注数 × 2。
Pareto 前沿：帽内每个 (注数, 收窄数) 格保留 P 最大者（沿用 `exp-strict-space.enumerate_space` 的 DP）。
`frontier_hash = sha256(legs-base 字节 + channel + cap + mode + tiers 字节)`；同输入同输出。
第三序 = 前沿默认排序 key：等 P 时全包给 top1 最低的场；全包名额按被排面 fair 降序（26123 规则，F7 测它）。
输出 `<issue>-frontier-<channel>.json`：`{frontier_hash, channel, mode, cap_yuan, max_p, strict_max_p, points:[{k, faces, notes, stake_yuan, p_all, shape, narrowings:[{match_no, excluded_face, fair, d3_count, c14_band}]}]}`；空前沿 `max_p = None`。
每个点自动写候选树节点：`version = "frontier#k@¥cap"`, `parent_version = "tiers@<tiers_hash>"`, `verdict = considered`。

### 4.5 `zucai_capital_plan`（内核 typed Action，只追加）

| 字段 | 含义 |
|---|---|
| `plan_id`, `issue`, `day`, `supersedes` | 一期一条；重定案是新记录 |
| `cap_source ∈ {baseline, override, brake}` | baseline = 宪法 ¥400 复式基准 × 2；override = 用户行权，**必带 `adjudication_ref`**；brake = 连续两期全灭减半/空仓 |
| `caps = {renjiu, shengfucai, total}` | 常设 Z5：`renjiu ≤ 1200`；`total ≤ 1600`；`total ≤ 2000 − 当日竞彩已登记` |
| `frontier_refs = {renjiu: hash, shengfucai: hash}` | 枚举那次运行 |
| `max_p_matrix`, `max_p_strict`, `chosen_p` | 三个数并排（B9「并排打印」成字段） |
| `gate_cost_pp = (max_p_matrix − max_p_strict) × 100` | strict 空解时 `None`，F4 不计该期 |
| `chosen = [{channel, candidate_node, legs_file_hash, notes, stake_yuan, p_all, slip_id?}]` | 所选票；`slip_id` 由 B9c 登记后回填（**没入账=没打**） |
| `verdict_refs` | 空仓 / 减注 / 行权的裁决引用 |
| `actor_id`, `committed_at` | 只许 `judge_operator` |

### 4.6 候选树（既有 `candidate` 事件，含 `parent_version`）

根 `tiers@<hash>` → 前沿层 `frontier#k@¥cap` → 人的分叉 `choose --edit` 节点（parent = 所选前沿点）→ 再改一版 parent = 上一版。树自动长，人只挂自己的分叉。

## 5. 命令面与 SOP 映射

| SOP | 命令 | 写到哪 |
|---|---|---|
| B4 | `zucai-build-reads`（扩展写 `face_status`；faces 不一致 ERROR） | legs-base |
| B5c→B5 | `plan tiers --issue` | `<issue>-tiers.json` + 候选树根 |
| B5 | `plan frontier --issue --channel [--cap]` | `<issue>-frontier-<channel>.json` + 候选树前沿层 |
| B5 人挑 | `plan choose --issue --channel --point k [--edit legs.json]` | `<issue>-legs-<channel>.json` + 候选树节点 |
| B6/B6b | 不变 | — |
| B9 | `plan commit --issue --cap-source … [--adjudication …]` | 内核 `zucai_capital_plan` |
| B9c | 不变（`betslip register`）；`plan status` 回填 `slip_id` | — |
| 对账 | `plan status --issue` | 只读 |
| B10 | `after_settle` 已接；F4 适配器读 capital_plan | RSI |

权限：`zucai_commit_capital_plan` 仅 `judge_operator`。`tiers/frontier` 确定性算术，不需要 Action。
硬约束：`plan frontier` 拒绝无 `face_status` 的 legs-base（提示先补 B4），不静默回退。
工作台 SOP 任务栏加三个按钮：定级+风向、前沿、定案（需 legs）。

## 6. 与 RSI 层的接线

| 实验 | 层/档 | 样本 | harness | falsifier |
|---|---|---|---|---|
| F4 门代价（已登记） | structural/observation | 每期 `gate_cost_pp` | `rsi_grading.grade_f4()` 读内核 plan 行 | 原 prereg：`gate_cost_median_pp` ci_upper < 5 证伪，n_min 12 |
| F6 B5c 矩阵 | structural/deploy_eligible | 每处收窄的被排面事后开没开，按级分层 | 重放候选树 | 待登记：T1/T2 级被排面兑现残差 ci_upper < +2pp 证伪 |
| F7 第三序分配 | structural/deploy_eligible | 等 P 点的全包去向 | 重放前沿 | 待登记 |

接线：`plan commit` 落 plan → `rsi fulfill --exp F4`；`after_settle` 已会 grade → 补 F4 适配器；`rsi dream --family <spec.json>` CLI 在此补上（消费者 = 矩阵阈值变体族）。
边界：重放只读历史快照（按期哈希）；矩阵阈值只能经 `rsi deploy` → 改 RULEBOOK 常量 → 下一期生效；专项永不写 Read。

## 7. 迁移

- 26129 回填：把 SFC-B/C/D/E 与 RJ9 终版按 `parent_version` 登记进候选树；写一条 `zucai_capital_plan`（override，引用「选9 ≤¥1,000」补登的 Adjudication）；F4 的 26129 观察由此自动产生。
- 常设行权「任九 ≤¥1,200」登记为 Adjudication，spec Z5 引用其 id。
- 旧 legs-base 不回填三态（判断不能事后补）；26129 可从研究 JSON 派生并标 `source=backfill`。

## 8. 测试（守规则的最重要）

- face_status：dead 无 3/3 → ERROR；`precedent=none` 不得推出 never；faces ≠ 派生 → ERROR；字段缺失 = alive。
- 定级：T1–T4 各一例；边界 fair 0.15 / 0.20 归属写死；灰带不可收窄。
- 枚举：T3 场任何前沿点无收窄；T1 场收窄 ≤2 且每面满足面规则；strict 三活只出全包/丢；同输入 `frontier_hash` 相同；空前沿 `max_p=None`；无 `face_status` → 拒绝。
- 资金方案：override 无裁决 → 拒；renjiu > 1200 → 拒；total > 1600 → 拒；日帽扣竞彩已用；`deterministic_system` 调 commit → REJECTED；重定案 `supersedes`。
- 门代价：`gate_cost_pp` 算式；strict 空解 → None 且 F4 不计。
- 树：`choose --edit` 节点 parent = 所选前沿点；`plan status` 对未入账票报「没入账=没打」。
- F4 适配器：读 plan 行的 gate_cost_pp → bootstrap 中位 CI；`after_settle` 后 F4 从 n=0 变 n=1。

## 9. 出口条件

26130 一期从 B4 到 B9 全程只用 `plan tiers → frontier → choose → commit`，聊天窗口里不出现票面；`rsi status` 里 F4 显示 n=1/12；`/replay?date=` 能看到 tiers 根 → 前沿层 → 人的分叉。
