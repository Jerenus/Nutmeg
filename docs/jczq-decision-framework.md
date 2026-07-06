# JCZQ Daily 决策框架

> ## ⚠️ LEGACY — 退役 Poisson generator 的设计文档（2026-06-04 标记，spec §33）
>
> **本文档描述的是已退役的 Poisson generator 引擎**（R1-R28 / A-J / F1-F4，由
> `jczq-daily-advisor` / `jczq-daily-brief` / `jczq-mixed-report` 产出）。
>
> **live 引擎是 `jczq-tiered`，选腿规则见 `docs/superpowers/specs/2026-05-25-jczq-tiered-plan-design.md` §25-§31。**
> **每日决策唯一入口是 `nutmeg jczq-today`**（spec §32，内含钉死指令）。
>
> 本文档**仅作历史参考**——R1-R28 那套规则 live 引擎一概不用。背景见
> `docs/jczq-decision-chain-critique.md`。请勿据本文档做每日决策或让 agent 套用 Rule A-J。
>
> 🪦 **已排入删除计划**：本文 + 其描述的退役 generator 代码簇（`jczq_daily` /
> `jczq_brief` / `jczq_review` 等）将在世界杯窗口结束（2026-07-19）后整簇归档。
> 时序与安全依据见 **`docs/jczq-refactor-roadmap.md`**（Tier D2/D3）。

## 关于本文档

> Nutmeg 项目内部技术文档。描述了基于 Poisson 模型的中国体彩竞彩足球
> 每日推荐 + 复盘系统。截至 2026-05-14，系统已积累 25 条规则（R1-R25）+
> 4 个框架级修复（F1-F4）+ 670+ 单元测试。
>
> 本文档面向：团队成员、未来 AI 会话冷启动、架构反思、对外分享。

**系统目标**：在 100 元/日的小预算下，用 Poisson 模型 + 经验校准 + 多层
过滤 + 人机双 debate，建立一个抗模型偏差、可持续迭代、可解释的体彩投注
决策流水线。

---

# 第一章 · 设计哲学与起源

## 起源问题

JCZQ 是高变量、高 vig（12-13% 抽水）、低样本（每日 5-15 场）的赌博市场。
开放性研究问题：**用统计模型能否在 100 元小注规模下持续正 EV？**

第一版（5/04）发现 Poisson 模型 + 简单 EV 过滤可识别 alpha，但实战中频繁
出现"模型说 0:0 命中率 10%、实测只有 6%"的系统性偏差。10 天聚合证据：

| 标的类型 | 实测命中率 | 模型 implied | 偏差 |
|---|---:|---:|---|
| crs 0:0 alpha | 1/16 = 6.25% | 8-15% | 模型高估 1.3-2.4x |
| crs 低进球三花（0:0/0:1/1:0）| 1/24 = 4.2% | 25-40% | 模型高估 6-10x |

这是 R22-R25 + F1-F4 的核心动因。

## 五条设计原则

| 原则 | 落地方式 |
|---|---|
| **多层冗余** | 每个决策至少经过 3 层过滤（衰减 → 规则 → 人工裁决）|
| **历史数据驱动** | F2 baseline、R25 league bias、R24 cooling-off 都来自 strategy_memory |
| **可解释** | 每张 ticket 的每条 leg 能反向追溯到规则触发链 |
| **人机双盲 debate** | Claude 和 Codex/GPT 各自独立给方案，再人工裁决 |
| **保守优先** | 信号弱日（无 +15% alpha）默认跳过 C 票 + 留仓 ≥ 20% |

---

# 第二章 · 系统架构（六层流水线）

## 层级总览

| 层 | 名称 | 作用 | 关键模块 |
|---|---|---|---|
| 1 | 数据层 | 收集赔率 + 历史 | Sporttery API、strategy_memory.json |
| 2 | 模型层 | Poisson lambda + score grid | `jczq_poisson.py` |
| 3 | 衰减层 | 三层 bias 校正 | `compute_poisson_edges()` |
| 4 | 过滤层 | R 规则硬过滤 + 软调权 | `select_top_legs()` 等 |
| 5 | Plan 生成层 | 7 类 ticket 自动构建 | `_build_plans()` |
| 6 | 人工裁决层 | Claude vs GPT debate | debate workflow |

## 层间数据流

**数据层** 提供两类输入：
- 实时赔率（Sporttery 每 30 分钟快照）
- 历史 memory（130+ poisson_residuals + recent_plan_results 等）

**模型层** 把 had 池赔率反推 home_λ / away_λ → 用 Poisson 分布算 7×7 score grid →
聚合出 had / ttg / crs / hafu fair odds。

**衰减层** 把 raw Poisson edge 经三层校正：
1. R25 联赛 ttg/crs 残差 bias（加性 -0.10）
2. F2 (pool, pick) 经验衰减（乘性 ×0.5-1.0）
3. F3 当日集中度衰减（乘性 ×0.9）

**过滤层** 应用 28 条 R 规则硬过滤 + 软调权（如 R10 hi-vol+ttg≤2 hard reject、
R20/R21 had Poisson edge floor、R22 hi-vol crs 低进球 reject）。

**Plan 层** 构建 ticket：A 稳健底仓 / B 主进攻 / D 反大众 / E 极限娱乐 /
cluster 票，加 Rule O 同场禁混 / Rule L 集中度。**C Poisson 单核已被 R28
退役**（5/01-5/15 整票 1/11 天、realized -47.7%）；hafu 池 R27 全面下架。

**裁决层** 跑 debate workflow：Claude 和 Codex/GPT 各写独立 analysis →
auto-compare 出分歧 → 人工裁决 → 多轮修订（V1 → V5）→ final-plan。

## 反馈环

下注 → 比赛结果 → `jczq_review.py` 自动复盘 → 更新 5 个 memory 字段 →
次日 brief 自动用新数据。这是闭环系统的关键：F2 / R25 baseline 不是手工
设置，是历史数据自动累积。

---

# 第三章 · 核心数学：衰减叠加

## 衰减公式

```
final_edge = (raw_edge + R25_league_bias) × F2_decay × F3_decay
```

- **F1 Dixon-Coles tau** 通过修改 score_grid 影响 raw_edge（默认 disabled）
- **R25 league bias** 加性偏移（典型 -0.10）
- **F2 empirical decay** 乘性衰减（[0.5, 1.0]）
- **F3 daily concentration** 乘性衰减（{0.9, 1.0}）

## 5/14 实战示例：004 crs 0:0

| 步骤 | 操作 | edge |
|---|---|---:|
| 0 | raw Poisson edge | **+36.1%** |
| 1 | + R25 西甲 -0.10 | +26.1% |
| 2 | × F2 0.625（实测 6.25% / baseline 10%）| +16.3% |
| 3 | × F3 0.9（当日 3 场低进球 alpha 触发）| **+14.7%** |
| 阈值 | R23 +25% / poisson_solo +15% | 不过 |
| 结果 | C 票自动不出 | — |

5/14 的真实意义：raw alpha 看起来 +36% 很强，但框架综合判断是"今日模型
偏差日"，alpha 不可信。最终 generator 自动不出 C 票，避免了潜在损失。

## 各组件触发条件

| 组件 | 触发 | 衰减形式 |
|---|---|---|
| **F1** | `memory["dixon_coles_rho"] ≠ 0`（默认 0）| 修 score_grid 4 个低分单元 + renormalize |
| **R25** | 联赛 ≥ 5 ttg/crs 残差 + avg > 0 | edge -= 0.10 |
| **F2** | (pool, pick) ≥ 5 样本 + 实测 < baseline × 0.95 | edge ×= max(0.5, actual/baseline) |
| **F3** | ≥ 3 场 ≥+15% raw alpha 同方向 | 该方向 edge ×= 0.9 |

---

# 第四章 · 规则全表

## Rules A-F（5/05 第一批）

基础硬规则，定义系统骨架。

| 规则 | 触发 | 行为 |
|---|---|---|
| A | Poisson edge ≥ +15% | 原出 poisson_solo 票；**R28 已退役该票**，alpha 改进 B/D 腿 |
| B | had ≤ 1.50 | 禁 stable_base / main 强胆 |
| C | 联赛 ttg 中位数 ≥ 2.7 | hi-vol 标记 + 软降权 |
| D | hhad 缺 goal_line | 跳过该腿 |
| E | vig > 12.5% + implied 极差 < 10pp | 三方均盘 had 禁 |
| F | 上次烧场队 | score -0.5 |

## Rules R1-R21（5/08 至 5/13 演进）

11 天连续复盘驱动，每条规则都有具体失败案例。

| 规则 | 触发 | 行为 | 来源 |
|---|---|---|---|
| R1 | Poisson λ 校准 | 按联赛 ttg 残差调阈值 | 5/08 |
| R3.1 | 同 (match,pool,pick) ≥ 3 票 | 裁到 ≤ 2 | 5/09 |
| R4 | 半全场早场 ≤08:00 北京 | main/inspiration ≤ 1 late-kickoff | 5/08 |
| R7 | Poisson 覆盖 hhad | 加让球网格 | 5/08 |
| R7.1 | hhad Poisson edge ≤ -10% | select_top_legs 拒 | 5/08 |
| R9 | extreme 多 crs | peak ≥ +25%、其他 ≥ +15% | 5/10 |
| R10 | hi-vol + ttg ≤ 2 球 | main/contrarian hard reject | 5/10 |
| R11 | draw_cluster legs | Poisson edge ≥ -8% | 5/10 |
| R12 | false_signal priced | Poisson edge ≥ -10% | 5/10 |
| R13 | poisson_solo ttg 低 + λ ≥ 2.7 | 拒 | 5/10 |
| R15 | contrarian 不深押强胆 | hhad 让胜 ≤ 3.0 在强胆场拒 | 5/10 |
| R17 | poisson_solo 双 low_goals + λ ≥ 2.3 | 截 1 腿 | 5/11 |
| R18 | extreme + ≥ 2 crs low_goals | 留最强 | 5/11 |
| R19 | contrarian/main hhad 让平 | Poisson edge ≥ -5% | 5/11 |
| R20 | stable_base had + edge ≤ -10% | 拒 | 5/11 |
| R21 | main had + edge ≤ -10% | 拒 | 5/12 |

## Rules R22-R25（5/14 落库）

5/13 复盘 + 用户洞察驱动，针对 0:0 / 低进球 alpha 系统性偏差。

| 规则 | 触发 | 行为 | 备注 |
|---|---|---|---|
| **R22** | hi-vol 联赛 crs 0:0/0:1/1:0 | poisson_solo 拒 + hi-vol+coinflip 双标 select_top_legs 全 intent 拒 | 双层拦截 |
| **R23** | crs 0:0 进 poisson_solo | 阈值 +15% → **+25%** | 全局收紧 |
| **R24** | 最近 3 天 poisson_solo 全 miss | 下次 poisson_solo 硬限 1 腿 | cooling-off |
| **R25** | 联赛 ≥ 5 ttg/crs 残差 > 0 | edge -= 0.10 | 联赛级校准 |

## Rules R26-R28（5/15 至 5/16 落库）

退役级规则——回测证明整池/整票结构性 -EV，停止补丁、直接下架。

| 规则 | 触发 | 行为 | 来源 |
|---|---|---|---|
| **R26** | crs 池 alpha | crs 退出 poisson_solo（仅 inspiration/extreme 可用）| 5/15 复盘：crs 5/01-5/14 leg-hit 1/30 (3.3%) |
| **R27** | hafu 池任何腿 | hafu 全面下架，含 extreme（升级 Rule H）| 5/15 复盘：hafu 0/18 leg-hit |
| **R28** | poisson_solo 整票 | **Poisson 单核 C 票退役**——generator 不再产出 | 5/16 复盘：5/01-5/15 整票 1/11 天、leg-hit 2/16 (12.5%)、realized -47.7% |

**R28 根因**：poisson_solo = "取模型最高 edge 单腿成票"。但"最高 edge"在
Poisson 比分网格上必然是质量最集中的最窄低进球桶（`ttg 1球` / `crs 0:0`），
等于对自家模型校准最差的输出做逆向选择。R17/R18/R22/R23/R24/R26 六轮补丁
治标无效，结构仍 -EV——遂整票退役。`_build_poisson_solo_plan` 函数保留
（cooling-off + edge index 预热、单元测试覆盖），仅从输出列表剔除；
`RULE_R28_RETIRE_POISSON_SOLO` flag 可在 ≥30 天重审后翻回。

## Framework F1-F4（5/14 落库）

模型 / 元规则 / 策略层修复，超越单条 R 规则的范畴。

| 框架 | 类型 | 行为 | 5/14 状态 |
|---|---|---|---|
| **F1** | 模型层 | Dixon-Coles tau 修 0:0/1:1/0:1/1:0 | disabled（默认 dc_rho=0）|
| **F2** | 模型层 | (pool, pick) 实测 < baseline → edge × decay | 实测 crs 0:0 ×0.625 |
| **F3** | 元规则层 | ≥3 场 ≥+15% alpha 同方向 → ×0.9 + 警告 | 5/14 首次触发 |
| **F4** | 策略层 | 同场 alpha 优先 ttg（除非 crs >> ttg）| 5/14 active |

## 元规则（reuse_guard）

| 规则 | 来源 | 行为 |
|---|---|---|
| **Rule O** | 国家体彩《自由过关》 | 单票同场不同 pool 禁混合过关 |
| **Rule L** | 5/08 | 同 (match,pool,pick) 跨票 ≥ 3 张 → 裁到 ≤ 2 |
| **Rule L (R3)** | 5/08 | 单 match 最多出现在 3 张票 |
| **Rule H** | 5/06 | hafu legs 仅 extreme 票（4 天 0/9 命中证据）|
| **Rule I-1** | 5/06 | inspiration had ≥ 5.0 必须 Poisson edge ≥ +5% |
| **Rule I-2** | 5/06 | contrarian 不选 Poisson edge ≤ -15% |
| **Rule J** | 5/06 | extreme crs Poisson edge ≥ -10% |

---

# 第五章 · 每日工作流

## 6 步流程

**第 1 步**：触发。用户说"今天的方案" / `/jczq` / launchd 自动。

**第 2 步**：跑 brief 脚本。

```bash
uv run nutmeg jczq-daily-brief \
    --write .nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/brief.md
```

内部双 pass：
1. 算 raw alpha（不应用 bias）
2. 用 raw alpha 算 F3 daily concentration bias
3. 再算一次 with R25 + F2 + F3 + F1 全部 bias

**第 3 步**：brief.md 输出 8 节。

| 节 | 内容 |
|---|---|
| §1 | 盘面热度扫描（强胆 / 舒服盘 / coinflip / hi-vol 标记）|
| §2 | HAD implied prob + 联赛先验 gap |
| §3 | 桶分布计数（cluster 是否触发）|
| §4 | Poisson +EV 列表（含 F3 警告）|
| §5 | generator 自动票（A-F + cluster）|
| §5b | 规则误伤候选（参考用）|
| §7a-c | 叙事多样性 / 跨票集中度 / Kelly 建议 |
| §6 | 投递给 Claude 的指令模板 |

**第 4 步**：debate workflow（人工触发）。

```bash
uv run nutmeg jczq-debate-init --date today
# → 创建 debate 目录的 5 个 stub 文件

# Claude 写 claude-analysis.md
# Codex/GPT 写 gpt-analysis.md

uv run nutmeg jczq-debate-compare
# → 自动语义对齐 disagreements.md

# 人工校正 → disagreement-analysis.md
# 人工裁决 → human-notes.md
# Codex 二次校正
# 修订到 V5/Vn → final-plan.md + final-plan.json
```

**第 5 步**：Sporttery 现场核赔率 → 下注。

**第 6 步**：次日 08:00 launchd 自动跑复盘。

```bash
uv run python -m nutmeg.interfaces.cli jczq-daily-review \
    --date yesterday --output-dir .nutmeg-data/jczq
```

更新 5 个 memory 字段：
- `poisson_residuals`（F2 baseline 数据增长）
- `recent_plan_results`（R24 cooling-off 状态）
- `pattern_buckets`（memory bias 学习）
- `oracle_learnings`（真实命中复盘）
- `decision_policy`（规则自动调权）

---

# 第六章 · 7 类 Plan Kind

## 票面分类速查

| Kind | 中文 | 命中率 | 注金区间 | 角色 |
|---|---|---:|---|---|
| **stable_base** | 稳健底仓 A | ~20% | 25-35 | 每日基本盘 |
| **main** | 主进攻 B | ~14-16% | 20-30 | 主收益期望来源 |
| ~~poisson_solo~~ | ~~Poisson 单核 C~~ | 12.5% leg | — | **R28 退役**（realized -47.7%）|
| inspiration | 高赔率灵感 | ~5-10% | 10-20 | 中等赔率有逻辑标的 |
| **contrarian** | 反大众 D | ~5-8% | 10-15 | 反舒服盘 / coinflip |
| **extreme** | 极限娱乐 E | < 1% | 5-10 | 高杠杆娱乐 |
| false_signal | 假信号审问 | ~10-15% | 5-10 | 反外部噪音 |
| draw/upset_cluster | 聚类 | — | — | ≥ 3 场触发 |

## 各 plan 关键规则

**stable_base（A）**：Rule D 让球线 / Rule B had ≥ 1.50 / R20 had Poisson floor

**main（B）**：R10 hi-vol+ttg≤2 reject / R21 had Poisson floor / R4 late-kickoff

**poisson_solo（C）**：~~R5 / R13 / R17 / R22 / R23 / R24 / R26 / F4~~ — **R28 整票退役**

**contrarian（D）**：Rule I-2 / R10 / R15 / R19 / R12

**extreme（E）**：R27 禁 hafu / Rule J / R9 / R18

**inspiration**：Rule I-1（high-odd had + edge floor）/ R7.1 hhad

**false_signal**：R12 priced edge floor

---

# 第七章 · 修订模式（V1-V5 案例）

## 5/14 一天 5 版本演进

5/14 经历 5 个版本，反映三重驱动力：赔率漂移 + 框架落库 + 用户洞察。

| 版本 | 触发时刻 | 关键变化 | 实下注 | 0:0 暴露 | EV |
|---|---|---|---:|---:|---:|
| V1 | Claude 初版 | 信号稀薄日 4 实票（C 跳过）| 69 | 0 | +1.5 |
| V2 | Codex 校正 | E 删 003 胜/平 -37.6% 强反对腿 | 69 | 0 | +1.6 |
| V3 | 14:40 赔率漂移 | 双 alpha 涌现 → C/F 出战 + G 大胆 4 串 | 81 | 21 | +5.5 |
| V4 | 用户察觉 0:0 集中 | E 删 005 0:0、F/G 减半 | 79 | 12 | +5.6 |
| V5 | F1-F4 框架对齐 | C 减半 10→5 + F 砍 2→0 + 留仓 +7 | 72 | 5 | +2.6 |

## 修订模式启示

**不要追求"完美初版"**：V1 通常是基线，由对照（Codex）+ 数据漂移 + 框架升级
触发演进。每个版本独立 commit + decision-log 事件，可单独验证。

**EV 不是唯一指标**：V5 EV 比 V4 低 -3，但承担"框架可能过严"的成本以避免
"框架可能对"的潜在 -10~-15 损失。这是显式 trade-off。

**0:0 暴露持续下降**：V3 21 元 → V4 12 元 → V5 5 元，**累计 -76%**。
这是用户问"为什么经常选 0:0"的根因修复。

---

# 第八章 · 人机协作裁决

## debate workflow 4 个 artifacts

| 文件 | 角色 |
|---|---|
| `shared-brief.md` | 同源数据（Claude + GPT 都读这个）|
| `claude-analysis.md` | Claude 5-6 票方案 + 与 generator 不同意见 |
| `gpt-analysis.md` | GPT 独立 5-6 票方案 |
| `disagreements.md` | jczq-debate-compare 自动语义对齐 |
| `disagreement-analysis.md` | 人工校正版（修复 auto extractor 噪音）|
| `human-notes.md` | 人工裁决最终票面（含 Codex second-pass 章节）|
| `final-plan.md/json` | 最终票面 + decision-log.json 事件流 |

## 5 种典型冲突的默认裁决

| 冲突类型 | Claude 立场 | GPT/Codex 立场 | 默认裁决 |
|---|---|---|---|
| C 票出 vs 跳过 | 跳过（R10+R24）| 出 003 ttg1 单核 | 采 Claude |
| B 票结构 | 2 腿稳健 | 3 腿杠杆 | 采 Claude |
| D 票同联赛 hi-vol | 跨场分散 | 同联赛兑现 alpha | 采 Claude |
| E 票腿数 | 2 腿 | 3 腿 + 强反对腿 | 采 Codex 删腿，结构采 Claude |
| 注金分配 | 加权 A 救场 | 守 SOP default | 取中位 |

## Codex 二次校正的价值

5/14 V1 Claude 自信反驳 GPT 的"E 票胜/平错"判断 → Codex second-pass 指出
Claude 漏读 brief 末尾的"Poisson 强烈反对腿"列表 → 修正 E 票避免 -37.6%
edge 损失。

**教训**：Codex second-pass 已落入 SOP 作必经环节。Claude 与 GPT 出现"我对
你错"的强分歧时，先回 brief 三验证，不要直接定性对方读错。

---

# 第九章 · 反馈环

## 5 个核心 memory 字段

| 字段 | 用途 | 影响规则 |
|---|---|---|
| `poisson_residuals[].goal_residual` | 模型 λ 残差 | R25 / F2 baseline |
| `recent_plan_results[].all_hit` | plan 整票是否命中 | R24 cooling-off |
| `pattern_buckets[league×role×pool].ev_score` | EV-weighted bias | bias_fn in select_top_legs |
| `oracle_learnings[].winning_picks` | 真实命中复盘 | 复盘叙述 + 人工反思 |
| `decision_policy.rules.reuse_guard.burned_teams` | 上次烧场队 | Rule F |

## 反馈节奏

```
下注（操盘人）
    ↓
比赛结果（次日开奖）
    ↓
jczq_review.py 跑复盘
    ↓
update_strategy_memory（5 个字段）
    ↓
次日 brief 自动用新数据
```

这是闭环系统的关键。F2 baseline 不是手工设置（10% / 22% 等只是初始值），
随历史数据累积自动校准；R25 league bias 触发条件随样本增加变更敏感；
R24 cooling-off 状态实时反映最近 3 天命中率。

---

# 第十章 · 关键不变量与守则

## 国家体彩硬规则（不可违反）

- **Rule O**：单票内 same-match 不同 pool **禁止**混合过关（《竞彩自由过关》）
- **预算硬上限 100 元/日**：娱乐预算定位
- **半全场仅 extreme 票**：Rule H 4 天 0/9 命中证据

## 系统层守则

- **brief 强反对腿小列表必读**：generator 在 5 个 plan 下都附"Poisson 强烈
  反对腿 ≤ -20%"列表，裁决前必须扫一遍（5/14 V1 漏读教训）
- **赔率漂移监控**：13:00 → 14:40 一小时可能涌现新 alpha；下注前必须
  Sporttery 现场再核当前价
- **Codex second-pass 必经**：单边裁决日加 0.8x 风险倍数

## 注金分配守则

- A 25-35 / B 20-30 / C 0-20 / D 10-15 / E 5-10 / F 0-3
- 留仓 ≥ 20% 信号稀薄日
- C 票 R24 cooling-off 触发时 default 减半（20 → 10）
- 单点集中度 > 50% 强烈建议拆分叙事

## 裁决心理守则

- **不追求"完美初版"**：V1 必修订，V5 是常态
- **EV 不是唯一指标**：当框架与人工冲突时，承担"框架可能过严"的小成本
- **5/15 复盘验证**：每个版本独立验证 → 哪种判断更准 → 调框架参数

---

# 第十一章 · 术语表

## Pool 类型

| 中文 | 内部名 | 选项 | 备注 |
|---|---|---|---|
| 胜平负 | had | 胜 / 平 / 负 | 90 分钟全场（不含加时）|
| 让球胜平负 | hhad | 让胜 / 让平 / 让负 | 含让球数 goal_line |
| 总进球 | ttg | 0/1/2/3/4/5/6/7+ 球 | 全场总进球数 |
| 比分 | crs | 0:0/1:0/0:1/.../胜其他 | 9 种主要比分 + 胜/平/负其他 |
| 半全场 | hafu | 9 种组合 | 上半时 + 全场结果 |

## Plan Kind 中英对照

| 内部名 | 中文 | 角色 |
|---|---|---|
| stable_base | 稳健底仓 A | 每日基本盘 |
| main | 最终主方案 B | 主收益 |
| poisson_solo | Poisson 单核 C | alpha 兑现 |
| inspiration | 高赔率灵感 | 中等赔率 |
| contrarian | 反大众盘口 D | 反舒服盘 |
| false_signal | 假信号审问 | 反外部噪音 |
| extreme | 极限小注 E | 高杠杆娱乐 |
| draw_cluster | 平局聚类 | ≥ 3 舒服盘触发 |
| upset_cluster | 爆冷聚类 | ≥ 3 强胆触发 |

## 关键文件位置

| 文件 | 角色 |
|---|---|
| `nutmeg/services/jczq_poisson.py` | Poisson + Dixon-Coles 模型 |
| `nutmeg/services/jczq_intelligence.py` | analytics + Poisson edges + select_top_legs |
| `nutmeg/services/jczq_strategy_memory.py` | 持久化 memory + 校准 helpers |
| `nutmeg/services/jczq_daily.py` | _build_plans 主入口 + 8 类 plan |
| `nutmeg/services/jczq_review.py` | 复盘流水线 |
| `nutmeg/services/jczq_debate.py` | debate workspace |
| `nutmeg/services/jczq_brief.py` | brief 生成（8 节）— CLI: `nutmeg jczq-daily-brief` |

## 关键 memory 字段

| 字段 | 含义 |
|---|---|
| `poisson_residuals` | 历史 leg 残差（F2/R25 数据源）|
| `recent_plan_results` | 滚动 plan 命中（R24 数据源）|
| `pattern_buckets` | league×role×pool EV-weighted（bias_fn 数据源）|
| `oracle_learnings` | 真实命中复盘 |
| `decision_policy` | 自动规则调权 |
| `dixon_coles_rho` | F1 启用开关（默认 0）|

---

# 第十二章 · 当前状态与未来方向

## 截至 2026-05-14 的状态快照

- **测试**：672 GREEN（jczq_* 全套）
- **R 规则**：R1-R25 + F1-F4 全部落库
- **5/14 V5 方案**：A 28 + B 22 + C 5 + D 10 + E 5 + F 0 + G 2 + 留 28 = 100
- **0:0 暴露**：V3 21 元 → V4 12 元 → V5 5 元（累计 -76%）
- **F3 模型偏差日**：5/14 首次触发（3 场 ≥+15% alpha 全低进球）

## 下一阶段迭代方向

| 优先级 | 方向 | 目标 |
|---|---|---|
| 高 | F1 启用 backtest | 5/01-5/14 grid search 找最优 dc_rho |
| 高 | F2 baseline 校准 | 5/14 实测后微调（10% → 9%）|
| 中 | R26 候选 | crs 0:0 hard reject（任何 ticket 都不下）|
| 中 | R10 漏洞修复 | 排查 select_top_legs vs _select_leg 路径差异 |
| 低 | xG 真实数据 | 引入 FBref / Understat 替代 Poisson 反推（F5+）|
| 低 | 多源 closing line | EuropeanOddsReferenceProvider 接入 |

## 引用

- **Dixon & Coles 1997**：Modelling Association Football Scores and
  Inefficiencies in the Football Betting Market（F1 数学基础）
- **国家体育总局《竞彩"自由过关"上线了！》**：
  https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21177108/content.html
  （Rule O 来源）
- **本系统设计文档**：`docs/architecture/jczq-daily-advisor.md`
- **决策 SOP**：`AGENTS.md` § JCZQ Daily Workflow
- **5/14 V5 final plan**：`.nutmeg-data/jczq/daily/2026-05-14/debate/final-plan.md`

---

*Last updated: 2026-05-14 by Claude. Next major iteration: 5/15 review or
F1 启用 backtest.*
