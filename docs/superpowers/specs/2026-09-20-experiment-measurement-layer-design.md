# 实验测量层改造 · 设计（2026-09-20）

> 前序：`2026-09-20-experiment-population-expansion-asbuilt.md`（采样域扩到并集，已竣工）。
> 本 spec 解决的是**扩完采样之后暴露出来的下一层问题：样本进来了，但测不出「度」**。
> 提交 `10847ba` 已完成本 spec 的 §3.0（语料接线），其余 T1-T8 待实施。

## 1. 问题陈述

用户 2026-09-20 裁定，把实验目标从「识别活面 → 去防」升级为：

> 「我们要判断的核心是活面也好、崩塌面也好，在两支队伍基本面上，影响的**"度"**有多少，
> **真信息还是噪音**？**人性面**在哪里？是不是和噪音在一起？」

这个升级暴露了三个结构性缺口，都不是判断问题，是**测量层没建**：

### 1.1 「度」测不了 —— 标签产能不足

2026-09-20 实测：语料 952 行有赛果，**只有 84 行带结构标签（8.8%）**。
C7（活先例）n=67、F5（价格带）n=179 —— 这些小样本不是因为比赛不够，
而是因为 **R0 每天产的 30 份 `research-*.json` 一份都没进语料**（`jczq_rows` 写死 `labels=None`）。

> 📌 已在 `10847ba` 修复：标签行 84 → 116，并首次引入 `death_three_proofs`。
> 同时发现一个更前面的断点：`jc-results.json` 回填**停摆 6 天**（停在 09-14，手动脚本无定时器），
> 赛果不回填则深研产物永远进不了语料。已手工补到 124 天 / 1198 场。

### 1.2 「真信息 vs 噪音」没有判据

现行判据是「CI 含不含 0」。在 n=67 量级上这条线**太松**——真信号和噪音都含 0。
C7 的实测正是这个形状：全体 n=67 R=+2.7pp CI[−7.7,+13.1]，训练窗 +12.0pp → 测试窗 −0.7pp。
「分窗不过」是事后才看出来的，**事前没有任何一条判据能拦住它**。

需要的是**噪音地板**：同一批样本把标签随机重排，看「零效应」能达到多大幅度。
任何因子必须超过这条线才算真信息。

### 1.3 「人性面」有数据、没判据

`prep-afternoon` 里已有两列从未被当作判据使用：

| 列 | 语义 | 今日实例 |
|---|---|---|
| `开盘位移 pp` | 从开盘到现在，钱往哪边走 | 场2 +11.45 / 场12 +10.06 / 场14 +9.59 / 场11 −4.50 |
| `跨家分歧 pp` | 庄家之间意见有多不一致 | 场5 1.44 / 场2 1.07 |

备料文件原话：「开盘位移是**旧源结构性拿不到**的量（API-Football 基础 /odds 无初赔，
drift 在那边恒为 0）。方向与阈值未定，三个对应因子在 probation——**不要拿它当已定判据**。」

`bold_odds.json` 也存 `opening_odds`，近 30 日覆盖 **127/300（42%）**。

**人性面与噪音混在一起是必然的**——所以必须先有 §1.2 的噪音地板，才谈得上分开。

### 1.4 逐场闭环缺回程

| 环节 | 粒度 | 状态 |
|---|---|---|
| 深研分析 | 逐场 | R0 `scope=match`，30/30 ✅ |
| 赛果结算 | 逐场 | `jc-results.json` ✅ |
| **判后落档** | — | ⛔**不存在**。复盘只有期级（`scoreboard.json` / `*_retro.md`） |

语料行有 `fair / actual / labels`，但**没有「这一场判对没判对、错在哪一层」**。
那个结论现在只活在期级复盘的散文里，下一期就查不回来。

### 1.5 「只许人」的动作由 AI 代跑

`rsi register` 的 docstring 写着「摄入登记原件（**人**）」，`deploy` 写着「只许人」，
但 CLI 签名里**没有任何身份字段**：

```python
def register(doc_path, data_dir, fork_from, population, window_from) -> None:
```

实测：F5/F9 的 duty 修改、库里三条 amendment，执行者全是 AI。
**「只许人」如果由 AI 代跑，那条约束就是装饰。**

---

## 2. 设计原则（本次不可推翻的四条）

1. **测量层与判断层分离**。本次不改任何判读逻辑、不改任何 `falsifier` 阈值、不改任何票面规则。
   只建「把事实变成可统计量」的管道。
2. **受控词典优先于自由散文**。凡是要进统计的字段，必须有封闭值域；
   值域外的值记 WARN 并原样留在 `detail` 里，**不静默丢弃、也不阻断产出**。
3. **测不了就说测不了**。数据源拿不到的历史值不得用插值、默认值或"合理推断"填充；
   缺口写进报告。（依据：`jczq_2026_06_wc_gap_empty_board` —— WAF 降级响应覆盖完好快照造成假空盘。）
4. **新实验只写原件，不登记**。`register` 是人的动作，实施方产出草稿文件即止。

---

## 3. 任务设计

### 3.0 语料接线（✅ 已完成于 `10847ba`，此处仅存档）

`experiments/corpus_build.py:jczq_rows()` 接 `daily/<date>/research-<code>.json`：
标签块与 `zucai_legs` 同构，另加 `death_three_proofs`（逐面 a/b/c + proof_count + verdict）。
`hole_location` **未接**，原因见 T1。

### 3.1 T1 · `hole_location` 受控词典

**问题**：`research_prompt.py:14` 写的是字面量 `"hole_location": {...}` —— **没有 schema**。
实测 55 份产物出现 **11 种以上不同 key 组合**，最常见的 `{anchor, detail, opponent}` 只占 28/55；
另有 `{away, home, note}`、`{china, iran, verdict}`、`{夏窗背景, 破门手段, ...}` 等。

**它是自由散文，不是变量。** 而画像①（「对手**进攻端**机制缺席才支撑锚方"能赢"；
防守端洞只支撑"能进球"」）判的就是这一格——**画像①目前无法被检验，根因在这里。**

**设计**：

```json
"hole_location": {
  "unit":     "attack|creation|spine|defense|goalkeeper|both|none",
  "side":     "home|away|both|none",
  "priced_in": bool,
  "detail":   str
}
```

- `unit` / `side` 闭合值域；`detail` 保留自由散文
- `research_intake` 校验：值域外 → **WARN**（记 `hole_location_uncontrolled`），不报 ERROR、不阻断
- 语义绑定（写进 prompt，供模型判断时对齐）：
  - `attack` = 破门端（中锋/射手）缺
  - `creation` = 组织端（前腰/组织核）缺
  - `spine` = 后腰屏障格缺
  - `defense` = 中卫对缺
  - `goalkeeper` = 门将缺
  - `both` = 攻防两端同时缺（对称崩塌）
  - `none` = 无结构性洞
- 接进 `corpus_build._research_labels`：`hole_location_unit` / `hole_location_side` / `hole_location_priced_in` 三个扁平字段

**不做**：不回填历史 55 份产物（模型不得替历史产物猜值域）。历史行 `hole_location_unit=None`。

### 3.2 T2 · 逐场判后落档（补上闭环回程）

**新产物**：`.nutmeg-data/jczq/daily/<day>/postmortem-<code>.json`（竞彩）
与 `.nutmeg-data/zucai/<issue>-postmortem.json`（足彩，逐场一行）

**核心设计点**：这份产物要测的**不是「我赢没赢」**，而是：

> **当赛果落在我排掉的面上时，那个面在事前登记的三证 / 先例状态是什么？**

这是对「活面影响几度」的**直接测量**——把"事前对该面的死活判断"与"该面是否真的开出"配对。

**字段**：

```json
{
  "match_id": str, "day": str, "issue": str|null, "code": str|null, "match_no": int|null,
  "actual": "3|1|0",
  "call_kind": "single|exclude|full|none",
  "called_faces": "310|31|3|...",
  "hit": bool,
  "excluded_faces": ["1","0"],
  "actual_was_excluded": bool,
  "actual_face_prior": {
    "fair_pp": float,
    "exclusion_tier": "省钱|灰带|买方差|翻面|null",
    "death_proof_count": "0/3|1/3|2/3|3/3|null",
    "precedent_status": "alive|dead|none|null"
  },
  "anchor_integrity": "pass|fail|symmetric_damage|null",
  "confidence": int|null,
  "directional_flags": [str],
  "nondirectional_flags": [str],
  "hole_location_unit": str|null,
  "drift_pp": {"home": float, "draw": float, "away": float} | null,
  "source": "research|legs-base",
  "computed_at": str
}
```

**CLI**：`nutmeg decision-postmortem --day <day> [--issue <issue>]`
- 只在该场**已有赛果**时产出；无赛果则跳过并计入报告的 `pending`
- 幂等：同 `match_id` 重跑覆盖，但 `computed_at` 更新
- **纯派生，不含判断**：所有字段从既有产物（research / legs-base / calls / fair / jc-results）机械抽取

**接 RSI**：不新建实验。该产物作为 `corpus_build` 的第五路来源，
让 `actual_face_prior` 三元组（fair 档 × 三证 × 先例状态）成为可统计维度。

### 3.3 T3 · duty 的 `pending_instrument` 状态

**问题**：F5 的 instrument 是 `["TODO", "price-band-observation", "--day", "{day}"]`
（采集器未实现，按设计不硬凑）。但它每天生成 **30 条永远无法 fulfill 的实例**，持续污染 gap 列表。

> **gap 的语义是「该做没做」，不是「还做不了」。** 两者混在一起，gap 列表就带上长期噪音。

**设计**：
- duty 增加可选字段 `"status": "active" | "pending_instrument"`（缺省 `active`）
- `rsi_prereg`：`status == "pending_instrument"` 时，**豁免** `instrument 必须含 {issue}/{day} 占位` 的校验
  （`rsi_prereg.py:47`），且允许 `instrument[0] == "TODO"`
- `rsi schedule`：跳过 `pending_instrument` 的 duty，**不生成实例**
- `rsi due`：不列入
- `rsi status`：单列一行 `pending: F5:price-band-observation（待实现采集器）`，**不计入 gaps**
- 迁移：清理 F5 已生成的 30 条未 fulfill 实例。**已 fulfill 的记录一律保留不得删除**

### 3.4 T4 · 赛果回填定时器 + 断流告警

**问题**：`scripts/jczq_result_backfill.py` 是手动脚本，**没有 launchd 定时器**
（现有四个：`decision.am` / `zucai.f2-observe` / `zucai.prep-morning` / `zucai.prep-revision` / `zucai.prep`）。
实测停摆 6 天无人发现，且静默——全链下游（语料、F5、C11/C12 复检）跟着停。

**设计**：
- 新增 `com.nutmeg.jczq.results-backfill.plist`，每日 **09:30 BJT**（板面日切之后、备料之前）
- 脚本增加断流自检：若 `jc-results.json` 最新日期距今 **> 2 天**，退出码 2 并在 stdout 首行打
  `⚠️RESULTS_STALE: latest=<date> lag=<n>d`
- 写一条运维记录进 `docs/ops/`（或既有等价位置），列明五个定时器及各自的断流后果

### 3.5 T5 · `opening_odds` 覆盖测量（**测量任务，不是承诺任务**）

近 30 日 `bold_odds.json` 覆盖 **127/300 = 42%**。开盘价是人性轴的唯一原料。

**设计**：
- 写 `experiments/exp-opening-odds-coverage.py`：按日统计覆盖率、按来源拆分缺失原因
- **产出是一份诊断报告，不是一个数字目标**。明确回答：
  1. 缺的那 58% 是「当时没抓」还是「源头就不提供」？
  2. 历史值是否**在源上仍可取**？若不可取，**如实写不可回补**，不得插值
- 若可回补，再单独开任务；本任务**只诊断不回补**

### 3.6 T6 · N0 噪音地板（原件草稿 + 评分器）

**claim**：
> 在给定 n 与给定统计量下，把标签随机重排所得的效应分布，构成该统计量的**噪音地板**；
> 任何因子的实测效应若落在地板分布的 [2.5%, 97.5%] 区间内，即与随机标签不可区分。

**mechanism**：
> 「CI 含 0」在小 n 下几乎必然成立，对真假信号无区分力。
> 置换零分布直接回答「连瞎猜都能做到这个幅度吗」——这是「真信息 vs 噪音」的可操作定义。

**设计**：
- `experiments/noise_floor.py`：`permutation_floor(rows, factor_key, statistic, n_perm=1000, seed=...) -> dict`
  返回 `{n, observed_pp, floor_p2_5, floor_p97_5, p_value, verdict: "above_floor"|"indistinguishable"}`
- **seed 必须写死并记进产物**，否则同一份数据两次跑出两个结论
- 统计量至少支持：`face_hit_rate_resid_pp`（该面实开率 − 该面 fair）
- 首批跑三个既有因子并把结果贴进报告（**只报告，不改任何规则**）：
  `c7_live_precedent` / `anchor_integrity` / `death_proof_count`
- 原件草稿 `experiments/registry/_draft_N0.json`，`tier: observation`，`layer: judgment`，
  `population: both`，`window.date_from` 留 `"TBD"`（由人登记时填）

⛔**不得执行 `nutmeg rsi register`。**

### 3.7 T7 · H1 人性轴（原件草稿 + 采集器）

**claim**：
> 开盘位移 `drift_pp`（当前 fair − 开盘 fair）分桶后，模态面实开率相对 fair 的残差，
> 存在超出 N0 噪音地板的系统性偏离。

**mechanism**：
> drift 是**钱的方向**，不是模型的方向——它是盘面上唯一直接编码群体行为的量。
> 若它超不过噪音地板，则「人性面」在本系统的可得数据里**不可分离**，该结论本身即有价值。

**设计**：
- 实现 F5 那条 duty 缺的采集器，命名 `nutmeg rsi price-band --day <day>`，
  产出 `.nutmeg-data/jczq/daily/<day>/price-band-<code>.json`，字段至少：
  `{match_id, fair_now, fair_open, drift_pp{home,draw,away}, book_disagreement_pp, books, captured_at}`
- **同时解掉 T3 的 F5**：采集器落地后，F5 的 duty 从 `pending_instrument` 改回 `active`
  并把 instrument 指向真命令。（⚠️F5 的**冻结面一个字都不许动**——只改 duty 的 instrument/status。）
- 原件草稿 `experiments/registry/_draft_H1.json`，判据写成
  「effect 必须 `above_floor`（引用 N0）」而不是写一个拍脑袋的 pp 阈值

⛔**不得执行 `nutmeg rsi register`。**

### 3.8 T8 · 人的身份约束

**设计**：
- `rsi register` / `rsi amend` / `rsi deploy` 增加**必填** `--by TEXT`
- 值落库（三张表各加一列 `acted_by`），迁移给历史行填 `"unattributed"`
- 拒绝值：`{"", "ai", "claude", "gpt", "codex", "assistant", "system", "auto"}`（大小写不敏感）→
  报错 `ValueError: --by 必须是人的标识；这三条动作按 RSI 设计只许人执行`
- **不做**：不做真实身份认证。这条约束是**留痕**不是**鉴权**——它把「AI 代跑」从无声变成有记录。

---

## 4. 不变量（实施后必须仍然成立）

1. `F1c` / `F2` / `F3` / `F8` 的注册表文件**逐字节未变**（B 类，窗口已开）
2. 任何实验的 `population` / `falsifier` / `window` / `buckets` / `stop_rule` / `claim` 未变
3. `rsi_verdicts` / `rsi_deployments` 仍为 0 行（本次不产生任何判决或上线）
4. 已 fulfill 的 duty 实例一条未删
5. 回放日仍对所有 population 返回空（`matches_for_population` 入口闸门）
6. n 仍只由 fulfill 产生；`schedule` 不使任何实验的 n 增长
7. 判读逻辑、票面逻辑、audit 码表一处未动

## 5. 验收口径

> 📌 承 `asbuilt §4.4` 的教训：**验收条件若能被「让数字好看」满足，它就不是验收条件。**

因此本次验收**不看任何 n 的增长**，只看：

| # | 检验 | 通过标准 |
|---|---|---|
| A1 | `git diff --stat experiments/registry/` | 只允许 `F5.json`（duty status/instrument）出现；**草稿走 `_draft_*.json` 新文件** |
| A2 | `uv run nutmeg rsi status` | `F5` 不再出现在 gaps，单列 pending 行（T7 完成后则为 active 且有实例） |
| A3 | `sqlite3 … "select count(*) from rsi_verdicts"` 与 `rsi_deployments` | 均为 `0` |
| A4 | N0 在三个既有因子上的输出 | 三份 `{n, observed_pp, floor_p2_5, floor_p97_5, verdict}` 原样贴进报告 |
| A5 | 同 seed 跑两次 N0 | 两次输出**逐字节一致** |
| A6 | `hole_location` 词典 | 新产物 `unit` 全部落在闭合值域；历史产物 `unit=None` 而**不是被猜成某个值** |
| A7 | `decision-postmortem` | 在一个已结算日上产出，且 `actual_was_excluded=true` 的行带齐三元组 |
| A8 | T5 诊断报告 | 明确回答「历史可否回补」，若不可回补则如实写明，**无插值** |
