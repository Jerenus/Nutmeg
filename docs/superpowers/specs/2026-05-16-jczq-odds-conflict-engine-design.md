# JCZQ 锐书赔率冲突引擎 — 设计文档

- **日期**：2026-05-16
- **状态**：设计待评审（用户 + Codex review 后进入实现计划）
- **作者**：Claude（brainstorming 流程产出）
- **关联**：`docs/jczq-decision-framework.md`、`AGENTS.md`、[[jczq_5_16_review_landed_rules]]

---

## 1. 背景与动机

16 天每日复盘 + 一次审判级回测（174 场带赔率数据，5/03–5/15）得出两个硬结论：

1. **当前 Poisson-from-odds 系统结构上产不出 alpha。** Poisson 模型是从体彩 HAD 赔率反推 λ 建立的——一个从市场赔率自身推导的模型，原理上无法系统性战胜那个市场，它算出的 "edge" 本质是模型参数化噪声。R26/R28 已实证：模型标 "+30% edge" 的腿回测 12.5% 命中、-47% 实亏。
2. **审判级回测：没有可激进利用的 edge。** 所有 +EV 标记都是小样本噪声或 ~1 个标准误内的不显著值。高赔率 exotic（大球 ROI 0.6、打穿 0.77、冷门 0.91）是市场偏差的亏钱侧。

唯一有理论支撑的方向：**edge 的唯一来源 = 独立信息与所投市场定价的分歧。** 本设计引入一个真正独立于体彩的第二信息源——国际锐书（Pinnacle）赔率——检测体彩定价与锐书共识的"明显冲突点"，作为主投注候选。

## 2. 核心论点（thesis）

- 体彩（中国体育彩票）是慢/软的庄家：定价更新慢、margin 高（vig ≈ 12–13%）。
- Pinnacle 是公认最锐的庄家：margin ≈ 2–3%，吸专业资金、几乎不限红，被博彩界当作"真实概率"的最佳公开代理。
- 当体彩对某结果的赔率，比 Pinnacle 去 vig 后的真实概率所对应的公允赔率**更慷慨** → 那是一个 +EV 价值点。
- "押软书相对锐书共识的偏差" 是博彩文献中有实证支持的边缘类型。这不保证体彩一定够软到可利用，但它是**唯一既有理论支撑、又可被严格自我验证**的方向。

## 3. 目标 / 非目标

**目标**
- 每日检测体彩 `had`（胜平负）赔率 vs Pinnacle `had` 共识的冲突点。
- 把冲突点作为**主投注候选**喂进现有 debate 工作流（`jczq-debate-init/compare/finalize`）。
- 注金随累积实绩 scale —— 小注起步，凭证据放大或砍掉。
- 接入现有"每日方案 → 次日 review"回测回路，**持续自我验证**。

**非目标（v1 明确不做）**
- `hhad` / `ttg` / `crs` / `hafu` 的冲突检测。理由见 §4。v2+ 再扩。
- 自动下单（仍是人工裁决后手动下注）。
- 取代现有 generator —— generator 继续作为 fallback 与对照基线。
- 把回测当"上线门禁"。回测是连续反馈回路（§6.7），不是一次性的准生关卡。

## 4. 覆盖现实（honest scope）

- 引擎只在"**体彩 ∩ 锐书都覆盖**"的联赛产信号 —— 五大联赛、欧冠/欧联、MLS 等。
- 日韩 / 北欧 / 沙特 / 亚冠乙等 obscure 联赛 —— 锐书覆盖薄或无 —— 引擎**诚实地不产信号**。这是结构性的，不是缺陷。
- **v1 仅 `had` 池。** 体彩 `胜平负` ↔ The Odds API `h2h`（主/平/客）是干净的 1:1 映射。`hhad`（让球线对齐）、`ttg`（体彩"总进球分桶" vs 锐书"大小球 X.5 线"无法 1:1 对齐）都有 mapping 难题，留 v2/v3；`crs`/`hafu` 锐书无对标盘且回测证明是噪声，永不纳入。
- v1 had-only 仍可支撑 2–3 串：一天若有多场覆盖联赛比赛，可产出多条 had 冲突腿组成 2串1/3串1。

## 5. 架构总览

```
体彩赔率(已有 brief context) ─┐
                              ├─> compute_had_conflict ──> ConflictSignal[] ──> brief"锐书冲突点"节
OddsReferenceProvider ─> 队名映射 ┘                              │                      │
(The Odds API: Pinnacle h2h)                                     │                  debate 工作流(主候选)
                                                                 v                      │
                                          conflict-signals.json store <── jczq-daily-review grade
                                                                 │
                                                         注金阶梯(读滚动 ROI)
```

## 6. 组件详述

### 6.1 `OddsReferenceProvider` — `nutmeg/services/jczq_odds_reference.py`

- The Odds API（the-odds-api.com）客户端。API key 走环境变量 `NUTMEG_ODDS_API_KEY`。
- 每日按"当日有体彩场次的覆盖联赛"拉 `h2h` 赔率，提取 Pinnacle 报价；若某场无 Pinnacle，则取该 API 内 EU sharp 子集（如 Betfair Exchange / 数家低 margin 书）的共识中位数作为降级参考，并在信号上标 `reference=fallback`。
- **Credit 预算**：免费档 500 credits/月，1 credit ≈ 一联赛一 market 一次调用。只拉当日相关联赛 → 估 5–15 credit/天，月内可控。实现需打印当日 credit 消耗。
- 当日结果缓存到 `.nutmeg-data/jczq/daily/<date>/odds-reference.json`（同日不重复调用）。
- 失败模式：API 不可达 / credit 耗尽 → 返回空集，**不抛异常**，brief 标注"锐书数据不可用"，当日引擎静默、退回 generator。
- 复用/替换 SOP memory 中提到的 `EuropeanOddsReferenceProvider` 接口桩（若存在）。

### 6.2 队名 / 联赛映射 — `nutmeg/data/jczq_team_aliases.json`（位置依仓库静态数据既有约定）

- 体彩中文队名 → The Odds API 英文名（或 canonical id）。例：`拜仁 → Bayern Munich`。
- 联赛映射：`德甲 → soccer_germany_bundesliga` 等。
- 人工维护的 JSON；首版对覆盖联赛种子填充。
- 未映射的场次 → 该场无冲突信号 + 写日志，供后续补表。
- **⚠ 这是最大工程风险点**：中英文队名、转会更名、升降级都会让映射腐化。设计上必须"未匹配 = 静默跳过 + 记录"，绝不猜测匹配。

### 6.3 `compute_had_conflict` — `nutmeg/services/jczq_conflict.py`

- 输入：同一场比赛的体彩 `had` 三项小数赔率 + 锐书 `had` 三项小数赔率。
- **去 vig**（normalize 法）：对每个源，`p_i = (1/o_i) / Σ_j(1/o_j)`，体彩与锐书各算一组。
- 锐书去 vig 后的概率 `p_sharp_i` 取作真实概率估计。
- 对每个结果 i（胜/平/负）：
  `edge_i = p_sharp_i × o_sporttery_i − 1`
- `edge_i ≥ CONFLICT_EDGE_THRESHOLD`（初值 **+0.04**，常量、可调）→ 标记为冲突点。阈值取 +4% 而非 0%，是为吸收去 vig 误差与赔率时滞噪声，要求一个真实裕量。
- 输出 `ConflictSignal`：`{date, match_no, league, pool='had', pick, sporttery_odds, sharp_fair_prob, edge, confidence_tier, reference}`。
- `confidence_tier` v1 按 edge 大小分档：`C = +4~7%`，`B = +7~12%`，`A = >12%`。后续版本叠加引擎累积命中率做调整。
- 边界：锐书赔率拉取时间距开赛过久（如 >12h）→ 信号标 `stale` 并降一档信心。

### 6.4 `ConflictSignal` 持久化 store — `.nutmeg-data/jczq/memory/conflict-signals.json`

- 每条记录：信号本体 + 次日 grade 结果（`hit: bool`, `realized_return: float`）。
- 累积数据驱动 §6.7 注金阶梯与滚动 ROI 计算。
- 注：`.nutmeg-data/` 已 gitignore，属运行期数据。

### 6.5 brief 集成 — `nutmeg/services/jczq_brief.py`

- 新增 `## 锐书冲突点` 节，置于第 4 节（Poisson +EV 表）之后——冲突点是更高优先级的候选。
- 内容：冲突信号表（编号 / 对阵 / pick / 体彩赔率 / 锐书公允概率 / edge% / 信心档 / reference）+ **覆盖说明**（今日哪些场次有锐书数据、哪些因联赛不覆盖或队名未映射而无信号）。
- 覆盖说明是诚实性要求——让人一眼看清引擎"能看见多少"。

### 6.6 review 集成 — `nutmeg/services/jczq_review.py`

- `jczq-daily-review` 扩展：对当日 final-plan 中的 had 腿，若它对应一条 ConflictSignal，则 grade 后写回 `conflict-signals.json`。
- 单独追踪"冲突腿"的滚动 ROI（与 generator 腿分开统计）。

### 6.7 注金阶梯（解决"小注起步、有证据再放大"）

读 `conflict-signals.json` 累积的已 grade 冲突腿数 N 与滚动 ROI：

| Phase | 条件 | 冲突腿注金 |
|---|---|---|
| OBSERVE | N < 15 | 纸面记录 或 ≤ 2% 日预算/信号 |
| SMALL | 15 ≤ N < 40 且滚动 ROI > 1.0 | 5–10% 日预算 |
| NORMAL | N ≥ 40 且滚动 ROI > 1.05 | 冲突腿成主仓 |
| KILL/PAUSE | 任意阶段 N ≥ 25 且 ROI < 0.95 | 暂停 + 复审 thesis |

- 可选 Phase 0 历史回测（§10）若强阳性 → 起始 phase 由 OBSERVE 升 SMALL。
- 所有数字为初值，落库后按实绩调。
- **这就是"回测作为方向盘而非门禁"的落地**：引擎照常产信号、照常进 brief，但真金注金由累积实绩自动分档。

## 7. 数据流（每日）

1. （已有）体彩赔率拉取 → brief context。
2. （新）`OddsReferenceProvider` 拉当日覆盖联赛的 Pinnacle h2h 赔率。
3. （新）队名映射对齐到体彩场次。
4. （新）`compute_had_conflict` 逐场 → `ConflictSignal[]`。
5. brief 渲染"锐书冲突点"节 + 覆盖说明。
6. 冲突信号作为主候选进 debate 工作流。
7. 人工 + Codex + Claude 裁决 → 最终方案，注金按 §6.7 阶梯。
8. 次日 `jczq-daily-review` grade，冲突腿结果写回 `conflict-signals.json`。
9. 注金阶梯读新滚动 ROI → 设定下一日冲突腿 phase。

## 8. 错误处理

- 锐书 API 不可达 / credit 耗尽 → 空集，brief 标注，退回 generator，不崩。
- 队名未映射 → 该场无信号 + 日志。
- 锐书某场缺 had market → 跳过该场。
- 锐书赔率过期 → 信号标 `stale` 降档。
- `conflict-signals.json` 不存在/损坏 → 视为空，引擎从 OBSERVE 起。

## 9. 测试策略

- `compute_had_conflict` 单测：去 vig 正确性、edge 公式、阈值边界、stale 降档。
- 队名映射单测：已知映射命中、未知名静默跳过。
- `OddsReferenceProvider` 用录制的 API 响应 fixture 测试，**测试中不打真实 API**。
- brief 新节渲染测试（含"无锐书数据"覆盖说明分支）。
- 注金阶梯单测：各 phase 边界与转换、KILL 触发。
- review 集成测试：冲突腿 grade 写回 store。

## 10. 可选 Phase 0：football-data.co.uk 历史回测

- 下载覆盖联赛的 football-data.co.uk CSV（含 Pinnacle `PSH/PSD/PSA` 历史赔率，回溯多年、免费）。
- **测试 A（总原则）**：在 football-data 多庄家历史数据上，检验"押某软书相对 Pinnacle 共识有正偏差的那一侧"是否 ROI > 1，样本数千场，结论可信。
- **测试 B（体彩专属）**：用现有 13 天 ~76 场大联赛数据，检验体彩 vs Pinnacle 偏差是否预测赢家。样本小（76 场），仅作"暗示"。
- 输出：设定引擎起始注金 phase。**非门禁**——不做也可直接 OBSERVE 起步。

## 11. 实现分期（供 writing-plans 拆解）

- **阶段 1 · 数据地基**：`OddsReferenceProvider` + 队名映射 + 缓存。
- **阶段 2 · 冲突核心**：`compute_had_conflict` + `ConflictSignal` + brief 新节。
- **阶段 3 · 反馈回路**：review 集成 + `conflict-signals.json` store + 注金阶梯。
- **阶段 0（可选、可并行）**：football-data.co.uk 历史回测脚本。

## 12. 风险与诚实告知

- 体彩可能没那么软；冲突在去 vig + 抽水后可能不够 +EV → 阈值需保守。
- 队名映射是持续维护负担。
- 免费 API credit 有限；联赛覆盖需实测（日韩/沙特可能不在 The Odds API 内）。
- 即便一切顺利，edge 可能很薄（+2–4%），需大样本才能确认 → 注金阶梯正是为此而设。
- **本设计不保证盈利。** 它是"有理论支撑、可严格自我验证"的最佳尝试，不是收益承诺。

## 13. 成功标准

- **工程**：引擎每日稳定产信号 + 覆盖报告，API 故障时优雅退化不崩。
- **验证**：累积 ≥ 40 条已 grade 冲突腿后，滚动 ROI 显著 > 1.0 → 成功，进 NORMAL。
- **诚实失败也是成功的产出**：若 ROI 收敛在 ~0.87（vig 线）→ 结论是"体彩不够软、此路不通"，引擎止于 OBSERVE，不再投入真金。验证机制本身保证了我们不会在幻觉上持续亏钱。
