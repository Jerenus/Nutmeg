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
| T2 | 1（可双选） | `license_score >= 3 ∧ integrity ∈ {pass, symmetric_damage} ∧ crash_markers 为空`（**2026-09-19 两次修正**：①原写 `== 3`，导致 `score=4 + symmetric_damage → T3` 比 `score=3` 更差，四问满分反因完整度降级；②改 `>= 3` 后又必须加 `无 crash`，否则「满分+翻车标记」会从 T3 升到 T2，比原状更糟）|
| T3 | 0（必全包） | 其余 |
| T4 | 建议丢（仅任九；T3 的子集，建议非强制） | T3 ∧ 三面全 alive ∧ max fair < 0.45（硬币） |

**单个 alive 面可被收窄** ⇔ `d3_count ≥ 2 ∧ fair ≤ 0.15`（B5c 原文「2/3 且被排面 ≤15% 可排」）。`fair > 0.20 ∧ d3_count < 3` 永不可收窄（原文「必须全包」）。15–20% 灰带不可收窄。
级数上限与面规则同时生效：T1 场也只能收窄满足面规则的面。
**票级上限（2026-09-19 补）**：全票收窄总数 `TICKET_MAX_NARROWINGS = 3`（与上表同为 RULEBOOK 常量）。它就是 C17 铁律「标记 ≤3」——原型 `exp-strict-space.enumerate_space` 的 `max_marks` 即此。⚠️漏掉它的后果是实测出来的：稠密板前沿点收窄数达 18，这些点在 B6 审计门必触发 C17 ERROR——**前沿提供了必然被拒的票，「人在前沿上挑」这条链就断了**。枚举器必须在 DP 里带票级检查。

#### 4.2.1 票级上限的结构性后果（2026-09-19 实测，非缺陷）

`TICKET_MAX_NARROWINGS = 3` 意味着任九 9 场里最多 3 场能收窄，其余 6 场必须全包。最省的一张票：
`2³ × 3⁶ = 5,832 注 = ¥11,664`——**远超任何合理帽**。所以：

> **任九的可行结构只能来自第一序（把面判死），不能来自第二序（收窄）。**

帽内有解的唯一路径是 `face_status.state == dead`（死面不计入收窄，它是判断不是结构选择）。
26129 就是活证：14 场三面全 alive、全板只有 1 个可收窄面 → 任九空前沿，如实。
**⚠️2026-09-19 更正（原措辞是错的）**：此前这里写「没判死任何面 = 判读层没给出判断」——**错**。
「三面全活」本身就是一个判断，是一句可证伪的话（机制上无面可杀）；宪法 §2 推论更是明文
「市场锚定（无命名理由＝跟市场）」——跟市场是判断，不是判断的缺席。
**判断永远存在，变的是强度；强度决定结构（能不能收窄），不决定要不要判。**

真正的问题在别处，数据说话：全历史 **294 个面只判死 10 个（3.4%）**，26122–26126、26129 五期
**全是 0**，而 26129 那 14 场是**全部深研过**的。三证门槛这么高 → 几乎无死面 → 第一序几乎不产生
结构 → 任九永远空前沿。这不是「诚实信号」，是**三证标准与任九结构不兼容**。

⛔但仍不许拍脑袋放宽三证。放宽走 **F8 实验**（见 §6）：在候选树与历史 legs-base 上重放
「两证 + 被排面 ≤X%」等变体，看历史上会多杀哪些面、那些面实际开出率多少；有前瞻证据再经
`rsi deploy` 改。任九专用票级上限同理。

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
Pareto 前沿：帽内每个 (注数, 收窄数) 格保留 P 最大者（沿用 `exp-strict-space.enumerate_space` 的 DP）；**收窄数 > `TICKET_MAX_NARROWINGS` 的状态直接剪掉**。
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
| **F8 死亡三证门槛**（2026-09-19 新立） | structural/deploy_eligible | 历史 legs-base 的全部被排面与其赛果 | 重放：按「三证齐」「两证 + fair ≤X%」等变体重算判死集合与其实际开出率 | 待登记：放宽档的被排面兑现率 ci_upper < 现行档 + 2pp 即证伪 |
| **F9 天平位移账**（2026-09-19 新立，用户裁定） | judgment/observation | **每场一行**（R2 后全样本） | 每期结算后自动记账 | 待登记：拨动场的 Brier 相对市场 ci_upper < 0 即证伪（说明拨动是负价值） |

**F9 的出生事故**：`belief` 与 `prior` 的偏移量从未被记账。实测 **446 场判读里只拨动过 40 场（9.0%），
且 26110 之后 22 期、308 场一次都没拨动过**——14 场深研、三证、牌照四问、旗与先例，最后落到
`belief` 上全是原样抄 `prior`。后果：Brier vs 市场恒等于 0（不是没技艺，是**没有表达**），
判读层实验（F1c/F2）测的其实是市场结构而非我们的判断力。

**F9 记什么**（每期结算后自动，不需要人）：
```
{issue, day, n_matches, n_moved, moved_pct, mean_abs_shift_pp, max_shift_pp,
 brier_vs_market_moved, brier_vs_market_all, direction_right_n, direction_wrong_n}
```
- 「拨动」判据：`max(|belief[f] − prior[f]|) > 0.05pp`（冻结常量 `BALANCE_MOVE_EPS_PP = 0.05`）。
- `direction_right` = 拨动的那一面实际开出；两项 Brier 都相对市场 prior 计算。
- ⛔**F9 只记账不判断**：它不建议该不该拨，只回答「这一期我们有没有说出一句市场没说的话、说对没有」。
- 与 F1c–F8 的关系：那些实验在**找**值得拨动天平的信号；F9 记录我们**实际**拨了没有、拨对没有。两边合起来才闭环。
- 本期读数为 `0/14` 是合法值，而且**这个零是系统里最重要的数字**——它是所有「找信号」实验的基线。

**F8 的出生事故**：294 个面判死 10 个（3.4%），五期为 0——门槛高到第一序几乎不产生结构，任九因此恒空前沿。⛔它是**实验**不是修补：不得在没有前瞻证据前直接改三证定义。

接线：`plan commit` 落 plan → `rsi fulfill --exp F4`；`after_settle` 已会 grade → 补 F4 适配器；`rsi dream --family <spec.json>` CLI 在此补上（消费者 = 矩阵阈值变体族）。
边界：重放只读历史快照（按期哈希）；矩阵阈值只能经 `rsi deploy` → 改 RULEBOOK 常量 → 下一期生效；专项永不写 Read。

## 7. 迁移

- 26129 回填：把 SFC-B/C/D/E 与 RJ9 终版按 `parent_version` 登记进候选树；写一条 `zucai_capital_plan`（override，引用「选9 ≤¥1,000」补登的 Adjudication）；F4 的 26129 观察由此自动产生。
- 常设行权「任九 ≤¥1,200」登记为 Adjudication，spec Z5 引用其 id。
- 旧 legs-base 不回填三态（判断不能事后补）；26129 可从研究 JSON 派生并标 `source=backfill`。

## 8. 测试（守规则的最重要）

- face_status：dead 无 3/3 → ERROR；`precedent=none` 不得推出 never；faces ≠ 派生 → ERROR；字段缺失 = alive。
- 定级：T1–T4 各一例；边界 fair 0.15 / 0.20 归属写死；灰带不可收窄。
- 定级单调：`score=4 + symmetric_damage` → T2（不得因完整度把满分降到 T3）；`score=4 + pass + 无 crash` → T1；`score=4 + crash` → T3。
- 票级上限：稠密板（每场 2 个可收窄面、全 T1）前沿里 `max(len(p['narrowings'])) <= 3`。
- 枚举：T3 场任何前沿点无收窄；T1 场收窄 ≤2 且每面满足面规则；strict 三活只出全包/丢；同输入 `frontier_hash` 相同；空前沿 `max_p=None`；无 `face_status` → 拒绝。
- 资金方案：override 无裁决 → 拒；renjiu > 1200 → 拒；total > 1600 → 拒；日帽扣竞彩已用；`deterministic_system` 调 commit → REJECTED；重定案 `supersedes`。
- 门代价：`gate_cost_pp` 算式；strict 空解 → None 且 F4 不计。
- 树：`choose --edit` 节点 parent = 所选前沿点；`plan status` 对未入账票报「没入账=没打」。
- F4 适配器：读 plan 行的 gate_cost_pp → bootstrap 中位 CI；`after_settle` 后 F4 从 n=0 变 n=1。

## 9. 出口条件

26130 一期从 B4 到 B9 全程只用 `plan tiers → frontier → choose → commit`，聊天窗口里不出现票面；`rsi status` 里 F4 显示 n=1/12；`/replay?date=` 能看到 tiers 根 → 前沿层 → 人的分叉。
