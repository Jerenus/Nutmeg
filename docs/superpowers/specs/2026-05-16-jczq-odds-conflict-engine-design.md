# JCZQ 锐书赔率冲突引擎 — 设计文档

- **日期**：2026-05-16
- **状态**：设计待评审（用户 + Codex review 后进入实现计划）
- **修订**：v3 — 发现 `nutmeg/data/european_odds.py` 已实现冲突检测引擎；数据源由 The Odds API 改为 500.com 抓取
- **关联**：`docs/jczq-decision-framework.md`、`AGENTS.md`、`nutmeg/data/european_odds.py`

---

## 1. 背景与动机

16 天复盘 + 审判级回测（174 场）证明：当前 Poisson-from-odds 系统结构上产不出 alpha（模型从体彩赔率自身反推，无法战胜该市场）。唯一有理论支撑的方向：**edge = 独立信息与所投市场定价的分歧**。

引入真正独立于体彩的第二信息源——国际锐书/欧洲赔率共识——检测体彩定价与之的"明显冲突点"，作为主投注候选。

**关键发现（v3）**：`nutmeg/data/european_odds.py` **已实现冲突检测引擎**：
- `cross_check_signals()` —— 逐 (场×玩法×选项) 算 `欧赔隐含概率 − 体彩隐含概率`，按 `delta_threshold` 过滤，并计算各家书价格的 **dispersion**（离散度）。
- `EuropeanOddsReferenceProvider` 协议、`EuropeanOddsQuote`、`CrossCheckSignal` 数据结构齐全。
- 但**整个模块零引用、未接线**，且只有 `NoOpEuropeanOddsProvider` 空实现。**项目有大脑，没有眼睛。**

所以本项目不是"造冲突引擎"，而是：**① 造眼睛（一个真去 500.com 取欧赔的 provider）② 把已有的 `cross_check_signals` 接进 brief 与 debate 流程 ③ 加注金阶梯。**

## 2. 核心论点（thesis）

- 体彩是慢/软的庄家：定价更新慢、vig ≈ 12–13%。
- 欧洲主流书（尤其 Pinnacle/低 margin 书）共识被博彩界当作"真实概率"的最佳公开代理，vig ≈ 2–5%。
- 体彩对某结果的赔率比欧赔共识去 vig 后的真实概率所对应公允赔率**更慷慨** → +EV 价值点。
- 不保证体彩够软到可利用；它是唯一既有理论支撑、又可严格自我验证的方向。

## 3. 目标 / 非目标

**目标**
- 每日抓 500.com 欧赔，用已有 `cross_check_signals` 检测体彩 vs 欧赔共识的冲突点。
- 冲突点作为**主投注候选**喂进现有 debate 工作流。
- 注金随累积实绩 scale（小注起步）。
- 接入"每日方案 → 次日 review"回测回路，持续自我验证。

**非目标（v1 不做）**
- `hhad`（让球）冲突。体彩让球胜平负 3 路定线 vs 欧洲亚盘 2 路（含半/四分之一球），线型对齐难 → v2。
- `crs` / `hafu` 冲突。无对标盘 + 回测证明 crs 是噪声 → 永不纳入。
- 自动下单；取代 generator（generator 留作 fallback）。
- 把回测当上线门禁（回测是连续反馈回路，§6.7）。

## 4. 覆盖范围（v1）

- **`had`**（胜平负）：体彩胜平负 ↔ 500.com 欧赔（ouzhi）多家欧洲 book 的 1X2。干净 1:1。**v1 确定纳入。**
- **`ttg`**（总进球）：体彩总进球分桶（0/1/.../7+球）↔ 500.com 大小球欧赔。需差分还原分桶概率（§6.3b）。**阶段 1 首步核实 500.com 大小球页存在且多书** → 存在则 v1 纳入，否则快速跟进 v1.1。
- 联赛覆盖：500.com 对几乎所有 JCZQ 场次都有欧赔页（它本就是竞彩分析站）；小联赛书少 → dispersion 高 → `cross_check_signals` 自动降权。覆盖面预计比商业 API 更广。

## 5. 架构总览

```
体彩赔率(已有 brief context) ──> sporttery_implied dict ─┐
                                                          ├─> cross_check_signals() ─> CrossCheckSignal[]
Five00EuropeanOddsProvider ──> EuropeanOddsQuote[] ────────┘   (★已存在于 european_odds.py)      │
(500.com 抓取)                                                                                  │
                                                                          brief"锐书冲突点"节 ──┤
                                                                                                v
                                                            debate 工作流(主候选) ─> final-plan
                                                                                                │
                                conflict-signals.json store <── jczq-daily-review grade <───────┘
                                                │
                                        注金阶梯(读滚动 ROI)
```

## 6. 组件详述

### 6.1 `Five00EuropeanOddsProvider` — 新模块 `nutmeg/services/jczq_odds_reference.py`

- 实现 `european_odds.py` **已有**的 `EuropeanOddsReferenceProvider` 协议：`quotes_for(matches) -> list[EuropeanOddsQuote]`。
- 数据源：500.com（500彩票网），**免费、无 API key、无 credit 限制**。
- 流程：
  1. 抓 `https://live.500.com/jczq.php` → 解析当日 JCZQ 赛程 → `周六NNN → 500.com 数字 match_id` 映射。
  2. 每场抓 `https://odds.500.com/fenxi/ouzhi-<match_id>.shtml`（欧赔 1X2，多家欧洲 book）；ttg 纳入后另抓大小球欧赔页。
  3. 解析各 bookmaker 行 → `EuropeanOddsQuote(match_no, bookmaker, pool, pick, price)`。
- 缓存当日抓取到 `.nutmeg-data/jczq/daily/<date>/european-odds.json`（同日不重复抓）。
- 失败模式：500.com 不可达 / 页面结构变更 / 解析失败 → 返回空集，brief 标注，退回 generator，**不抛异常**。
- HTTP 走项目已用的 `httpx`，带合理 `User-Agent` + 限速（顺序抓、间隔，避免被封）。

### 6.2 场次映射 — **大幅简化**

- 500.com 是中文站，用与 JCZQ **完全相同的赛程**（周六001 等编号）。映射只是 `周六NNN → 500.com 数字 match_id`，从 `jczq.php` 一页即可解析。
- **不需要中英文队名对齐**——这是原 spec（The Odds API 方案）的最大工程风险点，改用 500.com 后**消除**。
- 未在 500.com 找到的场次 → 无信号 + 日志。

### 6.3 冲突计算 — 复用 `nutmeg/data/european_odds.py`

#### 6.3a had

- 体彩 had 三项赔率（由 brief context 的隐含概率 + vig 反推，或直接取原始赔率）→ `sporttery_implied` dict：`{match_no: {(pool,pick): vig_free_prob}}`。
- `Five00EuropeanOddsProvider` 给 `european_quotes`。
- 直接调**已有的** `cross_check_signals(sporttery_implied, european_quotes, delta_threshold=...)` → `CrossCheckSignal[]`。
- v1 复用其现成逻辑（隐含概率 delta + dispersion）。`delta_threshold` 初值沿用 0.05，可调。
- **可选增强**（v1.1）：在 `CrossCheckSignal` 上追加 EV-edge 字段 `edge = european_implied × sporttery_decimal_odds − 1`，更直观表达"押这边是否 +EV"；并按 dispersion 给信号信心降权（书越分裂越不可信）。

#### 6.3b ttg（若 500.com 大小球页可用）

- 500.com 大小球欧赔 → 各档 over/under（X.5）赔率 → 去 vig → `P(under X.5)`。
- 差分还原欧赔分桶概率：`P(N球) = P(under(N+0.5)) − P(under(N−0.5))`；负值 clamp + 整组重归一化；缺档插值或跳过该桶。
- 体彩 ttg 分桶去 vig → 体彩分桶概率。
- 喂进 `cross_check_signals`（pool='ttg'，pick='N球'）。ttg 信号因差分噪声，`delta_threshold` 取更高（初值 0.07）。

### 6.4 `ConflictSignal` 持久化 store — `.nutmeg-data/jczq/memory/conflict-signals.json`

- 每条：`CrossCheckSignal` 本体 + 次日 grade（`hit`, `realized_return`）。
- 驱动 §6.7 注金阶梯与滚动 ROI。`.nutmeg-data/` 已 gitignore。

### 6.5 brief 集成 — `nutmeg/services/jczq_brief.py`

- 新增 `## 锐书冲突点` 节，置于第 4 节（Poisson +EV 表）之后。
- 内容：冲突信号表（编号/对阵/池/pick/体彩赔率/欧赔隐含概率/delta/dispersion/信心档）+ **覆盖说明**（今日哪些场次有/无 500.com 欧赔数据）。

### 6.6 review 集成 — `nutmeg/services/jczq_review.py`

- `jczq-daily-review` 扩展：对当日 final-plan 中对应某 `CrossCheckSignal` 的腿，grade 后写回 `conflict-signals.json`，单独追踪冲突腿滚动 ROI。

### 6.7 注金阶梯

读 `conflict-signals.json` 累积已 grade 冲突腿数 N 与滚动 ROI：

| Phase | 条件 | 冲突腿注金 |
|---|---|---|
| OBSERVE | N < 15 | 纸面记录 或 ≤ 2% 日预算/信号 |
| SMALL | 15 ≤ N < 40 且滚动 ROI > 1.0 | 5–10% 日预算 |
| NORMAL | N ≥ 40 且滚动 ROI > 1.05 | 冲突腿成主仓 |
| KILL/PAUSE | 任意阶段 N ≥ 25 且 ROI < 0.95 | 暂停 + 复审 thesis |

had / ttg 若样本足够，各自单独跑阶梯。数字为初值，可调。**这是"回测作为方向盘而非门禁"的落地。**

## 7. 数据流（每日）

1. （已有）体彩赔率 → brief context → `sporttery_implied`。
2. （新）`Five00EuropeanOddsProvider` 抓 500.com 欧赔 → `EuropeanOddsQuote[]`。
3. （已有）`cross_check_signals` → `CrossCheckSignal[]`。
4. brief 渲染"锐书冲突点"节 + 覆盖说明。
5. 冲突信号作为主候选进 debate 工作流。
6. 人工 + Codex + Claude 裁决 → 最终方案，注金按 §6.7。
7. 次日 `jczq-daily-review` grade → 写回 `conflict-signals.json`。
8. 注金阶梯读新滚动 ROI → 定下一日 phase。

## 8. 错误处理

- 500.com 不可达/结构变更/解析失败 → 空集，brief 标注，退回 generator，不崩。
- 某场在 500.com 找不到 → 该场无信号 + 日志。
- 某 pool 缺数据 → 该 pool 跳过该场。
- ttg 大小球缺档 → 受影响桶不产信号并标记。
- `conflict-signals.json` 不存在/损坏 → 视为空，引擎从 OBSERVE 起。

## 9. 测试策略

- `Five00EuropeanOddsProvider`：用**录制的 500.com HTML fixture** 测解析，测试中不打真实网络。
- `cross_check_signals`：已有逻辑，补单测覆盖（delta 阈值、dispersion、缺体彩侧）。
- ttg 差分还原：多档线 → 分桶、负值 clamp + 重归一化、缺档处理。
- 场次映射：`jczq.php` fixture → `周六NNN → match_id`。
- brief 新节渲染（含"无欧赔数据"覆盖说明分支）。
- 注金阶梯：phase 边界、KILL 触发、按池分档。
- review 集成：冲突腿 grade 写回 store。

## 10. 可选 Phase 0：历史回测（信心头款，非门禁）

- 500.com 保留历史比赛的欧赔页 → 可抓过去 N 天 JCZQ 场次的 `ouzhi-<id>` 页，与现有 13 天体彩历史数据对齐。
- 检验：体彩 vs 欧赔共识的 delta 是否预测赢家、冲突腿 ROI 是否 > 1。
- 输出：设定引擎起始注金 phase（强阳性 → 由 OBSERVE 升 SMALL）。**不做也可直接 OBSERVE 起步。**

## 11. 实现分期（供 writing-plans 拆解）

- **阶段 1 · 抓取地基**：`Five00EuropeanOddsProvider`（jczq.php 赛程→match_id；ouzhi 欧赔解析）+ 缓存 + HTML fixture 测试。首步核实 500.com 大小球页是否可用以定 ttg 去留。
- **阶段 2 · 接线**：`sporttery_implied` 构造 + 调 `cross_check_signals` + brief 新节。
- **阶段 3 · 反馈回路**：review 集成 + `conflict-signals.json` + 注金阶梯。
- **阶段 0（可选、可并行）**：500.com 历史欧赔回测脚本。

## 12. 风险与诚实告知

- **500.com 抓取脆弱性**：HTML 结构会变、可能有反爬/限频。解析需容错，失败优雅退化。这是新的主要工程风险（取代了原 API-credit 风险）。
- 体彩可能没那么软；冲突在去 vig + 抽水后可能不够 +EV → 阈值需保守。
- 500.com 欧赔的 book 构成未知（可能含或不含 Pinnacle）；dispersion 机制部分缓解——书共识紧才可信。
- ttg 分桶概率差分推导带额外噪声 → 更高阈值 + clamp 应对。
- edge 可能很薄（+2–4%），需大样本确认 → 注金阶梯为此而设。
- **本设计不保证盈利。** 是"有理论支撑、可严格自我验证"的最佳尝试。

## 13. 成功标准

- **工程**：引擎每日稳定抓 500.com 欧赔、产 had(+ttg) 冲突信号 + 覆盖报告，500.com 故障时优雅退化。
- **验证**：累积 ≥ 40 条已 grade 冲突腿后滚动 ROI 显著 > 1.0 → 成功，进 NORMAL。
- **诚实失败也是产出**：若 ROI 收敛在 ~0.87（vig 线）→ 结论"体彩不够软、此路不通"，引擎止于 OBSERVE，不在幻觉上持续亏钱。
