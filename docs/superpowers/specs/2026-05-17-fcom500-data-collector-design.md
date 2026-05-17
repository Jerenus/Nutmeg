# 500.com 数据采集器 — 设计文档

- **日期**：2026-05-17
- **状态**：设计待用户评审
- **目标**：用基于 500.com 的采集器替换 API-Football，作为冲突引擎的市场数据源 —— **无日配额**、**~100% JCZQ 覆盖**（按竞彩编号直接对齐）、4 个玩法全覆盖。
- **前序**：[[2026-05-17-nutmeg-consolidation-design]] §7、[[2026-05-17-dixon-coles-model-calibration-design]]。冲突引擎实时通路已打通，但 API-Football 有日配额限制、且跨系统别名对齐只覆盖 5 大联赛（~60%）。

---

## 1. 背景与动机

冲突引擎 = `ValueBoardService`：Dixon-Coles 模型概率 vs 市场公允概率 → edge。当前"市场"侧数据来自 API-Football，暴露两个结构性问题：

- **日配额**：2026-05-17 当天反复跑 brief 即耗尽 API-Football 当日配额，§5 校准验收门因此跑不了。
- **覆盖率（Gap B）**：JCZQ→API-Football 要靠 `jczq_league_aliases.json` / `jczq_team_aliases.json` 跨系统别名匹配，只收录 5 大联赛 → 每天 34 场只能对齐 ~20 场。

## 2. 现状勘察结论（2026-05-17 实地 WebFetch）

- `odds.500.com` 直接展示**当天 JCZQ 全部 34 场**，比赛编号 **001-034 与体彩完全一致**。
- 玩法齐全：**胜平负 / 让球胜平负 / 比分 / 总进球数 / 半全场**；同时展示**官方竞彩赔率**与**国际博彩公司欧赔**（Bet365 等）。
- 数据是**静态 HTML 表格**（无需无头浏览器）。
- 每场有分析子页：欧赔 `odds.500.com/fenxi/ouzhi-[matchID].shtml`、比分 `.../比分-[matchID].shtml`、总进球 `.../总进球-[matchID].shtml`。

**关键收益**：500.com 把"竞彩比赛 + 国际赔率"按竞彩编号**同页同号**呈现 —— 采集后按竞彩编号直接对齐，**不再需要跨系统别名匹配**，Gap B 自然消失，覆盖率 → ~100%。

## 3. 目标架构

```
JCZQ 每日 brief（竞彩编号 001-034）
        │
        ▼
Fcom500OddsProvider —— 抓 odds.500.com + 各 fenxi 子页，按竞彩编号解析
        │   产出：每场 = 合成 Fixture(队名/联赛/日期) + OddsSnapshot(4 玩法市场赔率)
        ▼
ValueBoardService.build_board_for_fixtures —— 冲突引擎核心逻辑不变
        │   模型侧：soccerdata（已缓存、无配额）按队名取球队实力
        ▼
冲突点 + 串关候选 → brief
```

- **新增** `nutmeg/data/fcom500.py`：`Fcom500OddsProvider`。抓 500.com，按竞彩编号产出每场的市场赔率。接入已有 `nutmeg/data/european_odds.py` 的协议脚手架（`EuropeanOddsReferenceProvider` 目前是 `NoOpEuropeanOddsProvider`，正是接入点）。
- **产出形态**：每场产出一个合成 `Fixture`（队名/联赛/日期来自 500.com，id 用 `fcom500:周日NNN`）+ 一个 `OddsSnapshot`（`MarketOddsSnapshot`/`OutcomeOddsSnapshot`，含 `fair_probability`）。`ValueBoardService` 按既有 `OddsService` 协议消费 —— 冲突引擎核心、串关构造器、注金阶梯**全部不变**。
- **对齐**：按竞彩编号 `周日NNN`。JCZQ brief 的比赛编号 ↔ 500.com 的 001-034 直接对应，不用别名表。`MatchAligner` + 别名表在 500.com 路径下不再使用（保留给 API-Football fallback，见 §6）。

## 4. 4 个玩法的市场赔率来源

冲突引擎要的"市场公允概率"应来自**独立于体彩**的市场（否则拿体彩赔率比体彩 = 循环）。各玩法取数:

| 冲突引擎玩法 | 500.com 来源 | 独立性 |
|---|---|---|
| `match_winner`（胜平负） | 欧赔页 `ouzhi-*`（Bet365 等国际 1X2） | ✅ 国际市场 |
| `handicap`（让球） | 亚盘（Asian handicap，国际） | ✅ 国际市场 |
| `total_goals`（总进球） | 大小球盘（国际 over/under）→ 换算；500.com 总进球分析页 | ⚠️ 国际 O/U 是分界线赔率，需换算成竞彩的精确进球数分布；实现期确认 |
| `correct_score`（比分） | 500.com 比分分析页 `比分-*` | ⚠️ 实现期确认该页是国际比分赔率还是竞彩比分赔率；若仅竞彩则该玩法降级为"模型 vs 体彩"弱信号并明确标注 |

**实现期第一件事**：用真实 matchID 抓样本页，确认 `total_goals` / `correct_score` 的国际赔率可得性，按实情把上表"⚠️"项定死。spec 不假设、不猜测。

**半全场（半全场）排除** —— 与整合设计 R27 一致（0/18 历史，不做）。

## 5. 抓取与健壮性

- **方式**：普通 HTTP 客户端（复用项目已有的 `tls_requests` / `httpx` 栈）+ HTML 解析。静态表格，无需无头浏览器。
- **礼貌**：设 UA、请求间隔 ≥ 1s、每页结果缓存（同一天同页只抓一次，参考 `MatchAligner` 的 fixture 缓存）。
- **优雅降级是契约**：任一页面抓取失败 / 解析失败 / 某玩法缺失 → 该场该玩法无市场数据，brief 照常渲染、记 warning、不崩（与现冲突桥的降级行为一致）。
- **无真网测试**：测试用**录制的 500.com HTML 样本**（存到 `tests/fixtures/fcom500/`）驱动解析器，CI 不连真网。

## 6. 分阶段

### Stage A（本 spec 主体）— 500.com 欧赔采集器
`Fcom500OddsProvider` 落地：抓取 + 4 玩法解析 + 产出合成 `Fixture` + `OddsSnapshot` + 接入冲突引擎。完成后冲突引擎的**市场侧**完全无配额、全覆盖。

### Stage B（本 spec 内，紧随）— 模型 snapshot 去 API-Football 依赖
当前 `FixtureSnapshotService.build_snapshot` 仍会调 API-Football 取球队 context，配额耗尽时**硬崩**（2026-05-17 实测）。模型侧真正需要的是 soccerdata 的球队 trend（已缓存）。Stage B：让 snapshot 在 API-Football 不可用时**优雅降级**到 soccerdata-only —— `expected_goals_from_snapshot` 只用 soccerdata trend，本就够。完成后冲突引擎**整条链路**无 API-Football 依赖。

### 范围外
- 模型校准 §5 验收 / Stage 2（[[2026-05-17-dixon-coles-model-calibration-design]]，独立推进）。
- API-Football 不删除 —— 降为 fallback（500.com 不可用时兜底），别名表一并保留。

## 7. 风险

- **抓取脆弱性**：500.com 页面改版会让解析器失效。缓解：解析器集中在 `fcom500.py` 一处、录制样本测试可快速定位失效、优雅降级保证不崩。
- **反爬 / ToS**：500.com 是商业站。缓解：低频、设 UA、缓存、只取公开赔率页。若被封 → fallback 到 API-Football。
- **500.com 监管历史**：500.com 多年前线上彩票业务被监管叫停，但仍作为赔率/资讯站运营，赔率数据公开可见。本采集器只读公开赔率页、不涉及任何交易。
- **数据口径**：国际 O/U 换算成竞彩精确进球数有模型误差 —— §4 标注，实现期核实。

## 8. 测试策略（TDD）

- 解析器：录制真实 500.com HTML 样本 → 单元测试断言解析出的每场 4 玩法赔率正确（含缺玩法、缺场、页面异常的降级路径）。
- `Fcom500OddsProvider`：注入假 HTTP 客户端（喂录制 HTML），断言产出的 `Fixture` + `OddsSnapshot` 形态正确、按竞彩编号归组。
- 集成：冲突引擎用 500.com provider 跑通 `build_board_for_fixtures`，端到端断言（扩充 `test_daily_pipeline_acceptance.py`）。
- 全量 `uv run pytest tests/` 保持绿；不连真网。

## 9. 验收标准

- `Fcom500OddsProvider` 对当天 JCZQ **全部 34 场**产出市场赔率（4 玩法，缺失项优雅降级），**不调用 API-Football**。
- 冲突引擎用 500.com 数据源端到端跑通每日 brief，覆盖率 ~100%（vs 现在 ~60%）。
- Stage B 后整条链路无 API-Football 依赖 → 模型校准 §5 验收门可随时重跑（不再受配额阻塞）。
- 全量测试绿。

## 10. 成功标准

一个**无配额、全覆盖**的市场数据底座 —— 冲突引擎不再受 API-Football 日配额掣肘、不再因别名表缺失而漏掉 40% 的比赛。这同时解除了模型校准 §5 验收门的配额阻塞，让"完善全链路"得以真正收尾。
