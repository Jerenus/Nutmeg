# JCZQ 锐书赔率冲突引擎 — 设计文档

- **日期**：2026-05-16
- **状态**：设计待评审（用户 + Codex review 后进入实现计划）
- **作者**：Claude（brainstorming 流程产出）
- **修订**：v2 — 应用户意见，v1 范围由 `had` 扩到 `had + ttg`
- **关联**：`docs/jczq-decision-framework.md`、`AGENTS.md`、[[jczq_5_16_review_landed_rules]]

---

## 1. 背景与动机

16 天每日复盘 + 一次审判级回测（174 场带赔率数据，5/03–5/15）得出两个硬结论：

1. **当前 Poisson-from-odds 系统结构上产不出 alpha。** Poisson 模型从体彩 HAD 赔率反推 λ 建立——从市场赔率自身推导的模型原理上无法系统性战胜该市场，其 "edge" 本质是模型参数化噪声。R26/R28 已实证：模型标 "+30% edge" 的腿回测 12.5% 命中、-47% 实亏。
2. **审判级回测：没有可激进利用的 edge。** 所有 +EV 标记都是小样本噪声或 ~1 个标准误内的不显著值。

唯一有理论支撑的方向：**edge 的唯一来源 = 独立信息与所投市场定价的分歧。** 本设计引入真正独立于体彩的第二信息源——国际锐书（Pinnacle）赔率——检测体彩定价与锐书共识的"明显冲突点"，作为主投注候选。

## 2. 核心论点（thesis）

- 体彩（中国体育彩票）是慢/软的庄家：定价更新慢、margin 高（vig ≈ 12–13%）。
- Pinnacle 是公认最锐的庄家：margin ≈ 2–3%，吸专业资金、几乎不限红，被博彩界当作"真实概率"的最佳公开代理。
- 当体彩对某结果的赔率，比 Pinnacle 去 vig 后的真实概率所对应的公允赔率**更慷慨** → 那是一个 +EV 价值点。
- "押软书相对锐书共识的偏差" 是博彩文献中有实证支持的边缘类型。不保证体彩一定够软到可利用，但它是**唯一既有理论支撑、又可被严格自我验证**的方向。

## 3. 目标 / 非目标

**目标**
- 每日检测体彩 `had`（胜平负）与 `ttg`（总进球）赔率 vs Pinnacle 共识的冲突点。
- 把冲突点作为**主投注候选**喂进现有 debate 工作流（`jczq-debate-init/compare/finalize`）。
- 注金随累积实绩 scale —— 小注起步，凭证据放大或砍掉。
- 接入现有"每日方案 → 次日 review"回测回路，**持续自我验证**。

**非目标（v1 明确不做）**
- `hhad`（让球）冲突检测。体彩 hhad 是 3 路定线欧式让球，锐书是 2 路亚盘（含半/四分之一球线），线型对齐比 ttg 更难 → 留 v2。
- `crs` / `hafu` 冲突检测。The Odds API 无精确比分、无半全场 market（已核实），结构上无对标盘；回测亦证明 crs 是噪声 → 永不纳入。
- 自动下单（仍是人工裁决后手动下注）。
- 取代现有 generator —— generator 继续作为 fallback 与对照基线。
- 把回测当"上线门禁"。回测是连续反馈回路（§6.7），不是一次性准生关卡。

## 4. 覆盖现实（honest scope）

- 引擎只在"**体彩 ∩ 锐书都覆盖**"的联赛产信号 —— 五大联赛、欧冠/欧联、MLS 等。
- 日韩 / 北欧 / 沙特 / 亚冠乙等 obscure 联赛 —— 锐书覆盖薄或无 —— 引擎**诚实地不产信号**。这是结构性的，不是缺陷。
- **v1 覆盖 `had` + `ttg` 两池**：
  - `had`：体彩 `胜平负` ↔ The Odds API `h2h_3_way`（主/平/客），干净 1:1 映射。
  - `ttg`：体彩 `总进球` 是**分桶**（0/1/2/.../7+球）；锐书是**大小球 X.5 线**。借 The Odds API 的 `alternate_totals`（多档大小球线，已核实可用）差分还原出锐书的分桶概率，再与体彩分桶对比（机制见 §6.3b）。
- v1 had+ttg 一天可产多条冲突腿，足以支撑 2–3 串。

## 5. 架构总览

```
体彩赔率(已有 brief context) ──────────────┐
                                            ├─> compute_had_conflict ─┐
OddsReferenceProvider ─> 队名/联赛映射 ──────┤                         ├─> ConflictSignal[] ─> brief"锐书冲突点"节
(The Odds API: Pinnacle h2h_3_way            └─> compute_ttg_conflict ─┘          │                    │
 + alternate_totals)                                                              │            debate 工作流(主候选)
                                                                                  v                    │
                                          conflict-signals.json store <── jczq-daily-review grade
                                                                                  │
                                                                          注金阶梯(读滚动 ROI)
```

## 6. 组件详述

### 6.1 `OddsReferenceProvider` — `nutmeg/services/jczq_odds_reference.py`

- The Odds API（the-odds-api.com）客户端。API key 走环境变量 `NUTMEG_ODDS_API_KEY`。
- 每日按"当日有体彩场次的覆盖联赛"拉两个 market：`h2h_3_way`（had）与 `alternate_totals`（ttg），提取 Pinnacle 报价；若某场无 Pinnacle，则取该 API 内 EU sharp 子集（如 Betfair Exchange 等低 margin 书）共识中位数作降级参考，信号标 `reference=fallback`。
- **Credit 预算**：免费档 500 credits/月。had + ttg 两 market ≈ 2 credits/联赛/天；只拉相关联赛 → 估 10–25 credits/天 → 月内可能逼近或略超 500。实现需打印每日 credit 消耗；若超免费档，方案：① 限制覆盖联赛数，② 升最低付费档（约 $30/月）。此为待用户拍板的成本项。
- 当日结果缓存到 `.nutmeg-data/jczq/daily/<date>/odds-reference.json`（同日不重复调用）。
- 失败模式：API 不可达 / credit 耗尽 → 返回空集，**不抛异常**，brief 标注"锐书数据不可用"，当日引擎静默、退回 generator。
- 复用/替换 SOP memory 中提到的 `EuropeanOddsReferenceProvider` 接口桩（若存在）。

### 6.2 队名 / 联赛映射 — `nutmeg/data/jczq_team_aliases.json`（位置依仓库静态数据既有约定）

- 体彩中文队名 → The Odds API 英文名（或 canonical id）。例：`拜仁 → Bayern Munich`。
- 联赛映射：`德甲 → soccer_germany_bundesliga` 等。
- 人工维护的 JSON；首版对覆盖联赛种子填充。
- 未映射的场次 → 该场无冲突信号 + 写日志，供后续补表。
- **⚠ 这是最大工程风险点**：中英文队名、转会更名、升降级会让映射腐化。设计上必须"未匹配 = 静默跳过 + 记录"，绝不猜测匹配。

### 6.3 冲突计算 — `nutmeg/services/jczq_conflict.py`

通用步骤——**去 vig**（normalize 法）：对每个源每个 market，`p_i = (1/o_i) / Σ_j(1/o_j)`。锐书去 vig 后概率取作真实概率估计。

通用 **edge 公式**：`edge_i = p_sharp_i × o_sporttery_i − 1`。`edge_i ≥ 阈值` → 冲突点。

输出 `ConflictSignal`：`{date, match_no, league, pool, pick, sporttery_odds, sharp_fair_prob, edge, confidence_tier, reference, flags}`。

`confidence_tier` v1 按 edge 大小分档：`C = 阈值~+7%`，`B = +7~12%`，`A = >12%`；后续版本叠加引擎累积命中率调整。

#### 6.3a `compute_had_conflict`

- 输入：同场体彩 `had` 三项赔率 + 锐书 `h2h_3_way` 三项赔率。
- 直接套通用步骤。阈值 `CONFLICT_EDGE_THRESHOLD_HAD`，初值 **+0.04**（留裕量吸收去 vig 误差与时滞噪声）。

#### 6.3b `compute_ttg_conflict`

- 锐书侧：从 `alternate_totals` 取多档大小球线（0.5/1.5/2.5/3.5/4.5/5.5 的 over/under）。
- 每档 X.5 去 vig：`P(under X.5) = (1/o_under)/((1/o_over)+(1/o_under))`。
- **差分还原锐书分桶概率**：`P(0球)=P(under0.5)`；`P(N球)=P(under(N+0.5))−P(under(N−0.5))`；`P(7+球)=1−P(under6.5)`。
- **差分噪声处理**：某桶差分出负值或概率曲线非单调 → clamp 到 0 后对整组重新归一化；某 X.5 线缺失 → 相邻线插值，插不出则该桶不产信号并标 `flags=ttg_line_gap`。
- 体彩侧：ttg 分桶赔率去 vig → 体彩分桶概率。
- 逐桶套 edge 公式。阈值 `CONFLICT_EDGE_THRESHOLD_TTG`，初值 **+0.06**——比 had 高，因为锐书分桶概率是差分推导出的、噪声更大，要求更高裕量。
- 投注标的 = 单个体彩 ttg 桶，干净可单投。

### 6.4 `ConflictSignal` 持久化 store — `.nutmeg-data/jczq/memory/conflict-signals.json`

- 每条记录：信号本体 + 次日 grade 结果（`hit: bool`, `realized_return: float`）。
- 累积数据驱动 §6.7 注金阶梯与滚动 ROI 计算。`.nutmeg-data/` 已 gitignore，属运行期数据。

### 6.5 brief 集成 — `nutmeg/services/jczq_brief.py`

- 新增 `## 锐书冲突点` 节，置于第 4 节（Poisson +EV 表）之后——冲突点是更高优先级的候选。
- 内容：冲突信号表（编号 / 对阵 / 池 / pick / 体彩赔率 / 锐书公允概率 / edge% / 信心档 / reference / flags）+ **覆盖说明**（今日哪些场次有锐书数据、哪些因联赛不覆盖或队名未映射而无信号）。
- 覆盖说明是诚实性要求——让人一眼看清引擎"能看见多少"。

### 6.6 review 集成 — `nutmeg/services/jczq_review.py`

- `jczq-daily-review` 扩展：对当日 final-plan 中对应某条 ConflictSignal 的 had/ttg 腿，grade 后写回 `conflict-signals.json`。
- 单独追踪"冲突腿"的滚动 ROI（与 generator 腿分开统计，可按池再细分 had/ttg）。

### 6.7 注金阶梯（解决"小注起步、有证据再放大"）

读 `conflict-signals.json` 累积的已 grade 冲突腿数 N 与滚动 ROI：

| Phase | 条件 | 冲突腿注金 |
|---|---|---|
| OBSERVE | N < 15 | 纸面记录 或 ≤ 2% 日预算/信号 |
| SMALL | 15 ≤ N < 40 且滚动 ROI > 1.0 | 5–10% 日预算 |
| NORMAL | N ≥ 40 且滚动 ROI > 1.05 | 冲突腿成主仓 |
| KILL/PAUSE | 任意阶段 N ≥ 25 且 ROI < 0.95 | 暂停 + 复审 thesis |

- N 与 ROI 默认按全冲突腿统计；had / ttg 两池若样本足够，各自再单独跑一套阶梯（某池失效可单独 KILL 而不拖累另一池）。
- 可选 Phase 0 历史回测（§10）若强阳性 → 起始 phase 由 OBSERVE 升 SMALL。
- 所有数字为初值，落库后按实绩调。
- **这就是"回测作为方向盘而非门禁"的落地**：引擎照常产信号、照常进 brief，但真金注金由累积实绩自动分档。

## 7. 数据流（每日）

1. （已有）体彩赔率拉取 → brief context。
2. （新）`OddsReferenceProvider` 拉当日覆盖联赛的 Pinnacle `h2h_3_way` + `alternate_totals`。
3. （新）队名映射对齐到体彩场次。
4. （新）`compute_had_conflict` + `compute_ttg_conflict` 逐场 → `ConflictSignal[]`。
5. brief 渲染"锐书冲突点"节 + 覆盖说明。
6. 冲突信号作为主候选进 debate 工作流。
7. 人工 + Codex + Claude 裁决 → 最终方案，注金按 §6.7 阶梯。
8. 次日 `jczq-daily-review` grade，冲突腿结果写回 `conflict-signals.json`。
9. 注金阶梯读新滚动 ROI → 设定下一日冲突腿 phase。

## 8. 错误处理

- 锐书 API 不可达 / credit 耗尽 → 空集，brief 标注，退回 generator，不崩。
- 队名未映射 → 该场无信号 + 日志。
- 锐书某场缺 had 或 totals market → 该池跳过该场。
- `alternate_totals` 线档不全 → 受影响 ttg 桶标 `ttg_line_gap` 不产信号，其余桶照常。
- 锐书赔率过期（拉取时间距开赛过久，如 >12h）→ 信号标 `stale` 并降一档信心。
- `conflict-signals.json` 不存在/损坏 → 视为空，引擎从 OBSERVE 起。

## 9. 测试策略

- `compute_had_conflict` 单测：去 vig 正确性、edge 公式、阈值边界。
- `compute_ttg_conflict` 单测：多档线差分还原分桶、差分负值 clamp + 重归一化、缺线插值/标记、edge 计算。
- 队名映射单测：已知映射命中、未知名静默跳过。
- `OddsReferenceProvider` 用录制的 API 响应 fixture 测试，**测试中不打真实 API**。
- brief 新节渲染测试（含"无锐书数据"覆盖说明分支、had/ttg 混合信号）。
- 注金阶梯单测：各 phase 边界与转换、KILL 触发、按池分别分档。
- review 集成测试：had/ttg 冲突腿 grade 写回 store。

## 10. 可选 Phase 0：football-data.co.uk 历史回测

- 下载覆盖联赛的 football-data.co.uk CSV（含 Pinnacle `PSH/PSD/PSA` 胜平负 + `P>2.5/P<2.5` 大小球历史赔率，回溯多年、免费）。
- **测试 A（总原则）**：在 football-data 多庄家历史数据上，检验"押某软书相对 Pinnacle 共识有正偏差的那一侧"是否 ROI > 1，数千场样本，结论可信；had 与 over/under 各测一遍。
- **测试 B（体彩专属）**：用现有 13 天 ~76 场大联赛数据，检验体彩 vs Pinnacle 偏差是否预测赢家。样本小（76 场），仅作"暗示"。
- 输出：设定引擎起始注金 phase。**非门禁**——不做也可直接 OBSERVE 起步。
- 注：football-data 大小球只有 2.5 一档，故测试 A 的 ttg 部分只能验"over/under 2.5"层级，不能验全分桶；全分桶 edge 仍靠上线后 live 回路积累。

## 11. 实现分期（供 writing-plans 拆解）

- **阶段 1 · 数据地基**：`OddsReferenceProvider`（h2h_3_way + alternate_totals）+ 队名映射 + 缓存。
- **阶段 2 · 冲突核心**：`compute_had_conflict` + `compute_ttg_conflict` + `ConflictSignal` + brief 新节。
- **阶段 3 · 反馈回路**：review 集成 + `conflict-signals.json` store + 注金阶梯。
- **阶段 0（可选、可并行）**：football-data.co.uk 历史回测脚本。

## 12. 风险与诚实告知

- 体彩可能没那么软；冲突在去 vig + 抽水后可能不够 +EV → 阈值需保守。
- 队名映射是持续维护负担。
- 免费 API credit 有限（had+ttg 两 market 后更紧）；联赛覆盖需实测（日韩/沙特可能不在 The Odds API 内）。
- ttg 锐书分桶概率是从多档线差分推导，带额外噪声 → 已用更高阈值（+6%）+ clamp/重归一化应对，但仍是 had 之外的不确定来源。
- 即便一切顺利，edge 可能很薄（+2–4%），需大样本才能确认 → 注金阶梯正是为此而设。
- **本设计不保证盈利。** 它是"有理论支撑、可严格自我验证"的最佳尝试，不是收益承诺。

## 13. 成功标准

- **工程**：引擎每日稳定产 had+ttg 信号 + 覆盖报告，API 故障时优雅退化不崩。
- **验证**：累积 ≥ 40 条已 grade 冲突腿后，滚动 ROI 显著 > 1.0 → 成功，进 NORMAL；had / ttg 可各自判定。
- **诚实失败也是成功的产出**：若 ROI 收敛在 ~0.87（vig 线）→ 结论是"体彩不够软、此路不通"，引擎止于 OBSERVE，不再投入真金。验证机制本身保证了我们不会在幻觉上持续亏钱。
