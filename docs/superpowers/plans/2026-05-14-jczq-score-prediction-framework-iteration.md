# JCZQ 比分/进球预测框架迭代 (F1-F4)

> **缘起**：2026-05-14 用户在 V3 方案后追问"为什么经常选 0:0"。
> 诊断：Poisson 模型系统性高估低分概率（10 天聚合 crs 0:0 alpha 实测命中率
> 1/16 = 6.25% vs 模型 implied 8-15%）。R22/R23/R24 已部分修但只是阈值过滤，
> 没有改模型本身。需要从框架层迭代。
>
> 本文档是 5/15 会话启动的实施 plan。用户已确认要落 F1+F2+F3+F4 全部。

## 诊断证据

| 维度 | 数据 |
|---|---|
| Poisson crs 0:0 alpha 命中率（10 天聚合）| **1/16 = 6.25%** |
| Poisson crs 低进球三花（0:0/0:1/1:0）alpha | **1/24 = 4.2%** |
| 模型 implied 概率 | 8-15% |
| 实际命中率与模型偏差 | **3-6x 低估** |
| 5/14 ≥+15% alpha 4 条全是低进球 | 模型偏差红旗 |
| `strategy_memory.poisson_residuals` 现有样本 | 130 条 |

## 4 个框架迭代方向（已用户授权全落）

### F1：Dixon-Coles 低分校正（学术经典）

**思路**：在 Poisson 基础上加 tau 参数修正 0:0/1:0/0:1/1:1 的联合分布。
论文 Dixon & Coles 1997 是足球分析黄金标准。

**实现**：
- 重写 `nutmeg/services/jczq_poisson.py:_score_grid` 函数
- 引入 tau 校正项：
  ```
  tau(x, y) = 1 - λ_h * λ_a * rho   if x=0, y=0
            = 1 + λ_h * rho         if x=0, y=1
            = 1 + λ_a * rho         if x=1, y=0
            = 1 - rho               if x=1, y=1
            = 1                     otherwise
  ```
- `rho` 是经验校正系数，先固定 -0.05 ~ -0.1（Dixon-Coles 论文建议）
- 后续可从 `strategy_memory.poisson_residuals` 反推每联赛 rho

**测试**：
- `test_f1_dixon_coles_lowers_zero_zero_probability` — 同 lambda 下 D-C 后 0:0 fair_odds 升高
- `test_f1_dixon_coles_keeps_high_score_unchanged` — 3:0 / 2:1 等不受 tau 影响

**复杂度**：中（数学需正确实现 + 全套 Poisson 测试要重跑）
**预期效果**：0:0 fair odds 从 9.97 升到 ~12-13，alpha 从 +36% 自然降到 +20% 左右

### F2：经验残差自校准（Bayes 更新）

**思路**：用现有 130 条 `poisson_residuals` 自动校准每个 (联赛, pool, pick) 桶
的实测命中率 vs 模型 implied，应用 sharp ratio 衰减。

**实现**：
- `nutmeg/services/jczq_strategy_memory.py` 新增：
  ```python
  def compute_empirical_alpha_decay(
      memory, *, league, pool, pick, min_samples=5
  ) -> float:
      """返回 0-1 之间的衰减因子。1.0 = 不衰减；0.5 = alpha 减半"""
  ```
- `compute_poisson_edges` 接收 decay map：alpha edge × decay
- 例：crs 0:0 实测 6.25% vs 模型 9% → decay = 0.69，alpha +36% × 0.69 = +25%

**测试**：
- `test_f2_empirical_decay_zero_zero_below_market` — crs 0:0 命中率低于 implied → decay < 1
- `test_f2_empirical_decay_above_threshold_unchanged` — 样本不足时 decay = 1

**复杂度**：低（用现有数据 + 简单查表）
**预期效果**：crs 0:0 alpha 自动降权（同 F1 类似但走经验路径）

### F3：日级 alpha 集中度警告（元规则）

**思路**：当 brief Section 4 出现 ≥3 条同方向 alpha（如全低进球）时，触发"今日
模型偏差日"标记，所有该方向 alpha edge -10%（动态）。

**实现**：
- `scripts/jczq_daily_brief.py` 新增 Section 4 后的"alpha 方向多样性检查"：
  ```python
  def check_alpha_direction_concentration(rows: list[PoissonEdgeEntry]) -> dict:
      """{direction: count}; direction ∈ {low_goals, high_goals, draw, ...}"""
  ```
- 当 low_goals 方向 count ≥ 3 → 在 brief 顶部加警告 + alpha 列表 edge 后缀 "(-10% 日偏差衰减)"
- generator `compute_poisson_edges` 接收 day_concentration_decay

**测试**：
- `test_f3_concentration_warning_triggers_when_3_low_goals_alpha` — 5/14 brief 触发
- `test_f3_no_warning_when_diversified` — 5/13 brief 不触发（叙事多样）

**复杂度**：低（brief 渲染层 + 元规则）
**预期效果**：5/14 这种"全天大球多但模型给低进球 alpha"的日子被自动识别

### F4：ttg 替代 crs 作主要 alpha 表达（策略层）

**思路**：crs 9 选项细分过碎，crs 0:0 实际是 ttg=0 球的子集。
策略层把同场 alpha 优先级从 crs → ttg，减少同信号多腿叠加。

**实现**：
- `nutmeg/services/jczq_daily.py:_build_poisson_solo_plan` 加优先级排序：
  ```python
  POOL_PRIORITY_FOR_SAME_MATCH = ["ttg", "had", "hhad", "crs", "hafu"]
  ```
- 当同场有多条 alpha 候选时，按 POOL_PRIORITY 排序选首位
- 例：5/14 004 同时有 crs 0:0 +36.1% 和 ttg 1球 +19.8% → 优先选 ttg 1球（更稳健）
- 但保留：如 crs alpha edge >> ttg alpha edge（差距 ≥ 10pp），仍允许 crs

**测试**：
- `test_f4_ttg_preferred_when_alpha_close` — 同场 ttg +19.8% / crs +20.5% → 选 ttg
- `test_f4_crs_kept_when_dominant` — 同场 ttg +10% / crs +30% → 仍选 crs

**复杂度**：低（策略选 alpha 优先级表）
**预期效果**：减少同信号多腿叠加；ttg 1球 命中率 ~25% 远高于 crs 0:0 ~7%

## 推荐实施顺序

| 阶段 | 顺序 | 理由 |
|---|---|---|
| 第 1 批（高 ROI 低风险）| F2 + F3 | 用现有数据 + brief 渲染层，最快见效 |
| 第 2 批（核心模型）| F1 | Dixon-Coles 是数学正确的根本修复；测试覆盖广 |
| 第 3 批（策略层）| F4 | 在前三个落地后，策略层调优 |

## 与现有 R 规则的关系

| R 规则 | F1-F4 关系 |
|---|---|
| R22 (hi-vol crs 低进球 reject) | F2 经验残差会让 R22 更精确（不再依赖联赛 hi-vol 标记，而是按实测命中率）|
| R23 (crs 0:0 +25% 阈值) | F1 + F2 后可能不再需要硬阈值；动态衰减替代 |
| R24 (poisson_solo 连失冷却) | 与 F1-F4 互补；F1-F4 是模型层，R24 是策略层 |
| R25 (法甲 ttg/crs 残差 bias) | F2 是 R25 的全联赛通用版 |

## 测试覆盖目标

| 类型 | 数量 |
|---|---:|
| F1 Dixon-Coles 测试 | 4-6 条 |
| F2 经验残差测试 | 3-4 条 |
| F3 日级集中度测试 | 2-3 条 |
| F4 策略层优先级测试 | 2-3 条 |
| 历史回归测试修复 | 估 5-10 条（D-C 后 fair_odds 变化）|
| **总新增/修过** | **~25 条** |

落库后总测试数估 648 → ~670+。

## 5/15 会话启动检查清单

- [ ] 确认 5/14 V4 实战结果（A/B/C/D/E/F/G 各票命中情况）
- [ ] 用 5/14 实测更新 `poisson_residuals` 后再启动 F2（多 6-7 条样本）
- [ ] F2 / F3 先 land（低 ROI 高安全）
- [ ] F1 Dixon-Coles 用 plan agent 设计测试
- [ ] F4 最后 land
- [ ] 所有 land 完后用 5/14 brief 重跑回放，对比 V4 vs 假设的 V5
- [ ] 写 5/15 复盘 memory（新规则编号 F1-F4 或继续 R26-R29）

## 用户原话保留

> "我觉得这不应该是对今天一天的策略调整，而是应该迭代目前关于比分这个玩法的
> 策略上，很明显全天大球多，整体击中率就会很低。是否有更合理的预测比分的框架
> 或者大小球的框架来进行策略迭代。"

这是策略层洞察：
1. 不要在票面层 patch，要在模型层 fix
2. "全天大球多" → 5/14 是大球日，但模型给低进球 alpha 是模型偏差
3. "更合理的比分预测框架" → F1 Dixon-Coles + F2 经验校准
4. "大小球的框架" → JCZQ 没有大小球玩法，但 ttg ≤2/≥3 可作类似物（F4 思路）
