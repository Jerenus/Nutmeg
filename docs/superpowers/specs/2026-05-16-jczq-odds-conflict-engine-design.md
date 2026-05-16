# JCZQ 赔率冲突引擎 — 设计文档

- **日期**：2026-05-16（v4 修订 2026-05-17）
- **状态**：最终版，进入实现
- **修订史**：v1 had-only → v2 +ttg → v3 数据源 500.com + 复用 `european_odds.py` → **v4 数据源改为 API-Football（结构化 API，取代 500.com 抓取）**
- **关联**：`docs/jczq-decision-framework.md`、`nutmeg/data/european_odds.py`、实现计划 `docs/superpowers/plans/2026-05-16-jczq-odds-conflict-engine.md`

---

## 1. 背景与动机

16 天复盘 + 审判级回测（174 场）证明：当前 Poisson-from-odds 系统结构上产不出 alpha（模型从体彩赔率自身反推，无法战胜该市场）。唯一有理论支撑的方向：**edge = 独立信息与所投市场定价的分歧**。

引入真正独立于体彩的第二信息源——**国际书商赔率共识（API-Football）**——检测体彩定价与之的"明显冲突点"，作为主投注候选。

**已有可复用资产**：`nutmeg/data/european_odds.py` **已实现冲突检测引擎**——`cross_check_signals()`（逐 场×玩法×选项 算 `欧赔隐含概率 − 体彩隐含概率`，带各家书 dispersion 离散度）、`EuropeanOddsReferenceProvider` 协议、`EuropeanOddsQuote` / `CrossCheckSignal`。但零引用、未接线，只有 `NoOpEuropeanOddsProvider` 空实现。**本项目 = 造"眼睛"（API-Football provider）+ 接线 + store + 注金阶梯。**

## 2. 核心论点（thesis）

- 体彩是慢/软的庄家：定价更新慢、vig ≈ 12–13%。
- 国际主流书商共识被博彩界当作"真实概率"的最佳公开代理（vig 低、吸专业资金）。
- 体彩对某结果的赔率比书商共识去 vig 后真实概率所对应公允赔率**更慷慨** → +EV 价值点。
- 不保证体彩够软到可利用；它是唯一既有理论支撑、又可严格自我验证的方向。

## 3. 目标 / 非目标

**目标**
- 每日经 API-Football 取国际书商赔率，用已有 `cross_check_signals` 检测体彩 vs 书商共识的冲突点。
- 冲突点作为**主投注候选**喂进现有 debate 工作流。
- 注金随累积实绩 scale（OBSERVE→SMALL→NORMAL→KILL）。
- 接入"每日方案 → 次日 review"回测回路，持续自我验证。

**非目标（v1 不做）**
- `hhad`（让球）冲突：体彩 3 路定线让球 vs 亚盘格式对齐难 → v2。
- `crs` / `hafu` 冲突：回测证明 crs 是噪声 → 永不纳入。
- 自动下单；取代 generator（generator 留作 fallback）。
- 把回测当上线门禁（回测是连续反馈回路，§6.7）。

## 4. 覆盖范围（v1）

- **`had`**（胜平负）：体彩胜平负 ↔ API-Football `Match Winner`（Home/Draw/Away）。干净 1:1。**v1 确定纳入。**
- **`ttg`**（总进球）：体彩总进球分桶（0/1/.../7+球）↔ API-Football `Goals Over/Under`。`Goals Over/Under` 给多档 over/under 线 → 差分还原分桶概率（§6.3b）。**v1 纳入。**
- 联赛覆盖：API-Football 覆盖 1100+ 联赛，预计比商业小型 API 更广，可能覆盖竞彩用的小联赛（北欧/沙特/日韩/MLS）。某场在 API-Football 找不到对应 fixture → 该场无信号（诚实留白）。

## 5. 架构总览

```
体彩赔率(已有 brief context) ──> build_sporttery_implied ──> sporttery_implied dict ─┐
                                                                                    ├─> cross_check_signals()
ApiFootballOddsProvider ──> 场次对齐(联赛+日期+队名) ──> EuropeanOddsQuote[] ─────────┘   (★已存在)
  (API-Football /fixtures + /odds)                                                          │
                                                                       brief"赔率冲突点"节 ──┤
                                                                                            v
                                                          debate 工作流(主候选) ─> final-plan
                                                                                            │
                            conflict-signals.json store <── jczq-daily-review grade <───────┘
                                            │
                                    注金阶梯(读滚动 ROI)
```

## 6. 组件详述

### 6.1 `ApiFootballOddsProvider` — 新模块 `nutmeg/services/jczq_odds_reference.py`

- 实现 `european_odds.py` **已有**的 `EuropeanOddsReferenceProvider` 协议：`quotes_for(matches) -> list[EuropeanOddsQuote]`。
- 数据源：API-Football v3。API key 走环境变量 **`API_FOOTBALL_KEY`**。两种接入（构造参数 `mode` 选择，默认 direct）：
  - direct：base `https://v3.football.api-sports.io`，头 `x-apisports-key: <key>`。
  - rapidapi：base `https://api-football-v1.p.rapidapi.com/v3`，头 `x-rapidapi-key` + `x-rapidapi-host: api-football-v1.p.rapidapi.com`。
- 流程：
  1. 对当日比赛涉及的每个联赛，调 `/fixtures?league=<id>&season=<year>&date=<YYYY-MM-DD>` → 拿当日 fixtures（`fixture.id` + 英文队名）。
  2. 把每场 JCZQ 比赛（已知中文联赛+中文队名+日期）对齐到一个 fixture（§6.2）。
  3. 对齐到的 fixture，调 `/odds?fixture=<id>` → `response[].bookmakers[].bets[].values[]`。
  4. 取 `bets[].name == "Match Winner"`（had）与 `"Goals Over/Under"`（ttg）的 values → 转 `EuropeanOddsQuote(match_no, bookmaker, pool, pick, price)`。
- **请求预算**：免费档 100 请求/天。`/odds` 支持 `?league=&season=&date=` 批量形式 → 一联赛一天一次取回该联赛全部 fixtures 的 odds，控制在 ~联赛数×2（fixtures+odds）/天。实现需打印每日请求数；若不够 → 升档或限联赛。
- 缓存当日抓取到 `.nutmeg-data/jczq/daily/<date>/api-football-odds.json`（同日不重复调用）。
- 失败模式：API 不可达 / 配额耗尽 / key 缺失 → 返回空集，brief 标注，退回 generator，**不抛异常**。

### 6.2 场次对齐 — `nutmeg/data/jczq_league_aliases.json` + `nutmeg/data/jczq_team_aliases.json`

- 改用 API-Football（英文）后，**中英文对齐回归**，但有界、可控：
  - 联赛映射 `jczq_league_aliases.json`：体彩中文联赛名 → API-Football `league_id`（小型固定表，覆盖联赛种子填充）。
  - 用 `league_id + date` 查 API-Football fixtures，把候选缩到当天该联赛的几场。
  - 队名映射 `jczq_team_aliases.json`：体彩中文队名 → API-Football 英文队名（或规范 id）；在候选 fixtures 内匹配 home/away。
- 对齐失败（联赛未映射 / 队名未匹配）→ 该场无信号 + 写日志，供补表。绝不猜测匹配。

### 6.3 冲突计算 — 复用 `nutmeg/data/european_odds.py`

通用：`cross_check_signals(sporttery_implied, european_quotes, delta_threshold)` 已实现（隐含概率 delta + dispersion），v1 直接复用。

#### 6.3a had
- 体彩 had 三项赔率 → `build_sporttery_implied` 去 vig → `sporttery_implied`。
- API-Football `Match Winner` values（Home/Draw/Away，多 bookmaker）→ `EuropeanOddsQuote(pool='had', pick∈{胜,平,负})`（Home→胜/Draw→平/Away→负）。
- `delta_threshold` 初值 0.05。

#### 6.3b ttg
- API-Football `Goals Over/Under` 各档（Over/Under 1.5/2.5/3.5…）→ 去 vig 得 `P(under X.5)` → 差分还原分桶概率 `P(N球)`；负值 clamp + 整组重归一化；缺档跳过该桶。
- 体彩 ttg 分桶去 vig → 体彩分桶概率。
- 喂 `cross_check_signals`（pool='ttg'）。`delta_threshold` 取更高初值 0.07（差分噪声）。

### 6.4 `ConflictSignal` 持久化 store — `nutmeg/services/jczq_conflict_store.py` + `.nutmeg-data/jczq/memory/conflict-signals.json`

- 每条：`CrossCheckSignal` 本体 + `sporttery_odds` + 次日 grade（`hit`, `realized_return`）。
- 驱动 §6.7 注金阶梯与滚动 ROI。

### 6.5 brief 集成 — `nutmeg/services/jczq_brief.py`

- 新增 `## 赔率冲突点` 节（第 4 节 Poisson +EV 表之后）：冲突信号表（编号/对阵/池/pick/体彩赔率/书商隐含概率/delta/dispersion/信心档）+ **覆盖说明**（今日哪些场有/无 API-Football 数据）。

### 6.6 review 集成 — `nutmeg/services/jczq_review.py`

- `jczq-daily-review` 扩展：grade 当日 final-plan 中对应某 `CrossCheckSignal` 的腿，写回 `conflict-signals.json`，单独追踪冲突腿滚动 ROI。

### 6.7 注金阶梯

| Phase | 条件 | 冲突腿注金 |
|---|---|---|
| OBSERVE | N < 15 | 纸面 或 ≤2% 日预算/信号 |
| SMALL | 15 ≤ N < 40 且滚动 ROI > 1.0 | 5–10% 日预算 |
| NORMAL | N ≥ 40 且滚动 ROI > 1.05 | 冲突腿成主仓 |
| KILL/PAUSE | 任意阶段 N ≥ 25 且 ROI < 0.95 | 暂停 + 复审 |

had / ttg 样本足够时各自单独跑阶梯。数字为初值，可调。

## 7. 数据流（每日）

1. （已有）体彩赔率 → brief context → `build_sporttery_implied` → `sporttery_implied`。
2. （新）`ApiFootballOddsProvider` 查 /fixtures + /odds → 对齐 → `EuropeanOddsQuote[]`。
3. （已有）`cross_check_signals` → `CrossCheckSignal[]`。
4. brief 渲染"赔率冲突点"节 + 覆盖说明。
5. 冲突信号进 debate 工作流（主候选）。
6. 人工 + Codex + Claude 裁决 → 最终方案，注金按 §6.7。
7. 次日 `jczq-daily-review` grade → 写回 `conflict-signals.json`。
8. 注金阶梯读新滚动 ROI → 定下一日 phase。

## 8. 错误处理

- API 不可达/配额耗尽/key 缺失 → 空集，brief 标注，退回 generator，不崩。
- 联赛未映射 / 队名未匹配 → 该场无信号 + 日志。
- 某 pool 缺数据 → 该 pool 跳过该场。
- ttg 大小球缺档 → 受影响桶不产信号并标记。
- `conflict-signals.json` 不存在/损坏 → 视为空，引擎从 OBSERVE 起。

## 9. 测试策略

- `ApiFootballOddsProvider`：用 **mock 的 API-Football JSON fixture**（按 v3 契约构造：`response[].bookmakers[].bets[].values[]`）测解析与对齐，**测试中不打真实网络**（注入式 HTTP fetcher）。
- 场次对齐：联赛/队名映射表 fixture → 命中与未命中。
- `build_sporttery_implied`：去 vig 正确性。
- ttg 差分还原：多档线→分桶、负值 clamp+重归一化、缺档。
- brief 新节渲染（含"无数据"覆盖说明分支）。
- 注金阶梯：phase 边界、KILL 触发、按池分档。
- review 集成：冲突腿 grade 写回 store。
- **实接口冒烟（待 key）**：key 设好后，一次真实 `/fixtures`+`/odds` 调用，确认 mock fixture 与真实 JSON 字段一致；若有微差，调解析。此为唯一需要 key 的步骤。

## 10. 可选 Phase 0：历史回测（信心头款，非门禁）

- API-Football `/odds?league=&season=&date=` 支持历史日期 → 抓过去 N 天书商赔率，与现有 13 天体彩历史对齐。
- 检验：体彩 vs 书商共识 delta 是否预测赢家、冲突腿 ROI 是否 > 1。
- 输出：设定引擎起始注金 phase（强阳性 → OBSERVE 升 SMALL）。不做也可直接 OBSERVE 起步。

## 11. 实现分期

- **阶段 1 · 采集地基**：`ApiFootballOddsProvider`（/fixtures + /odds 调用 + 解析）+ 联赛/队名映射 + 缓存。mock fixture 测试。
- **阶段 2 · 接线**：`build_sporttery_implied` + 调 `cross_check_signals` + brief 新节。
- **阶段 3 · 反馈回路**：`jczq_conflict_store.py`（store + 注金阶梯）+ review 集成。
- **阶段 4 · 实接口冒烟**：key 设好后真实调用核对（唯一需 key）。
- **阶段 0（可选）**：历史回测脚本。

## 12. 风险与诚实告知

- **请求预算**：免费档 100/天；联赛多时需批量查询或升档。
- **队名/联赛对齐**：中英文映射表是持续维护负担（改用 API-Football 的代价；500.com 方案本可免，但 500.com 抓取脆且地域锁，权衡后选 API-Football）。
- **bookmaker 构成未知**：API-Football 含哪些书、是否含 Pinnacle 待实跑确认；`cross_check_signals` 的 dispersion 机制部分缓解（书共识紧才可信）。
- 体彩可能没那么软；冲突在去 vig + 抽水后可能不够 +EV → 阈值需保守。
- ttg 分桶概率差分推导带噪声 → 更高阈值 + clamp。
- edge 可能很薄（+2–4%），需大样本确认 → 注金阶梯为此而设。
- **本设计不保证盈利。** 是"有理论支撑、可严格自我验证"的最佳尝试。

## 13. 成功标准

- **工程**：引擎每日稳定取 API-Football 赔率、产 had+ttg 冲突信号 + 覆盖报告，API 故障时优雅退化。
- **验证**：累积 ≥ 40 条已 grade 冲突腿后滚动 ROI 显著 > 1.0 → 成功，进 NORMAL。
- **诚实失败也是产出**：若 ROI 收敛在 ~0.87（vig 线）→ 结论"体彩不够软、此路不通"，引擎止于 OBSERVE，不在幻觉上持续亏钱。
