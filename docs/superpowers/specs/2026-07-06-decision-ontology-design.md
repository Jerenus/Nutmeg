# Nutmeg 决策本体系统 — 第一性原理重设计（最终设计）

> 2026-07-06 定稿。替代全部旧功能层方法（tiered/bold/rules/themes/conflict 引擎）。
> 设计过程：brainstorming 五问定骨架 → 外部对标校验（Palantir Ontology / Halawi NeurIPS
> 2024 / Starlizard CLV / Metaculus 记分）→ 本体重构。实现计划另出（writing-plans）。

---

## §0 第一性原理与五个已确认决策

**不可回避的事实**：竞彩抽水 ≈−13%、传统足彩 ≈−30%；本仓 45 场对照实测判读 58% vs
盲跟市场 64%，分歧场 2:7 落后——原生方向没有 alpha，价值只出现在三个窄点：市场盲区
（071 签位激励）、表达工程（087 对冲）、避损否决（7/03 B 票）。

据此与用户确认的五个根决策：

| # | 问题 | 决策 |
|---|------|------|
| 1 | 目标函数 | **预测手艺最大化**——系统是校准的预测引擎，Brier/校准度是核心指标，投注是副产品 |
| 2 | 信念形成 | **市场锚定 + 理由微调**——去水 fair 是先验，只有命名因子才许偏移，账本判偏移生死 |
| 3 | 范围 | **竞彩 + 传统足彩统一**——一个逐场信念层，两个表达通道 |
| 4 | 可复制 vs 智慧 | **记录推理痕迹，不追位级一致**——输入快照+因子+证据+评分全落盘可重审；判断永不烤进代码 |
| 5 | 新旧接缝 | **保留数据基元作种子演进**——27 个纯数据基元 + judge_ledger；33 个旧信号打分符号（heat/drift/dispersion/conflict/chaos/theme）随旧机器死 |

## §1 外部对标结论（证据，非装饰）

- **Halawi et al. (NeurIPS 2024)**：最强公开 LLM 预测系统整体 Brier 0.179 **输给**人群
  0.149，但**选择性参与**（只在有把握时出手）时跑赢——印证"默认跟市场、有命名理由才偏移、
  空仓合法"是 SOTA 姿态，不是保守妥协。
- **Starlizard/职业玩家**：技能的行业度量是 **CLV（收盘线价值）**，不是输赢——收盘线是
  市场吸收全部信息后的最优估计，持续朝收盘方向偏移 = 含真实信息。**方差远小于赛果**，
  治本仓最大短板（样本效率：41 场攒两周）。
- **Metaculus**：成熟计分架构 = 相对记分（Baseline/Peer score）+ 逐人校准曲线。照抄。
- **Palantir Ontology**：系统该建模**决策**而非数据（Data+Logic+Action+writeback 闭环）；
  LLM agent 只能通过**带 schema 的类型化 Action** 写入本体。我们独立推导出了同构模式
  （"Claude 自由推理、落盘强制 schema"），采纳其**本体中心**架构观；**不采纳**其平台级
  数据集成/流式/微服务（单人仓自杀行为）。

## §2 决策本体（七对象，唯一持久层）

一切持久状态 = 七类对象 + 血缘链接，存 `.nutmeg-data/decision/` 下按类型分文件的
append-only JSONL（幂等 upsert-by-id，同 judge_ledger 的 append_day 纪律）。规模到
1 万+ 对象再议 SQLite——当前每季数百行，JSONL diff 友好、零依赖。

```
Match           一场比赛（跨通道身份）
  {match_id, kickoff_at, home, away, competition,
   channel_refs: {jczq_match_no?, zucai: {issue, index}?}}

MarketSnapshot  某时刻的去水盘口（先验的来源，也是 CLV 的两端）
  {snapshot_id, match_id, taken_at, kind: read_time|closing,
   source: sporttery|fcom500|apifootball|okooo_sp,
   fair: {market: {outcome: prob}}, raw_odds, lines: {hhad_line, ou_line}}

Read            一次判读决策（系统的原子）——见 §3 详细 schema
Factor          命名理由（词典项，有出生证和死亡机制）
  {factor_id, name_zh, definition, born_at, born_from(复盘/洞见引用),
   status: probation|active|retired, retire_reason?}

Ticket          一次下注行动（表达）
  {ticket_id, channel: jczq|shengfucai|renjiu, made_at,
   legs: [{match_id, read_id, market, pick, line?, odds}],
   structure: single|parlay|fushi(复式 selections),
   stake_yuan, computed_hit_prob(代码算,禁嘴算), tag, budget_bucket}

Settlement      结算（对 Read 和 Ticket 各一条）
  {settlement_id, ref_type: read|ticket, ref_id, settled_at,
   outcome_90, score, closing_snapshot_id,
   brier?, clv_pp?, hit?, pnl_yuan?}

FactorVerdict   因子判决（calibrate 的输出，因子的生死簿）
  {factor_id, as_of, n_reads, brier_delta_vs_prior, clv_hit_rate,
   direction_hit_rate, recommendation: keep|watch|retire, next_review_at}
```

**血缘规则**：Read→它看的 Snapshot+引用的 Factor+证据；Ticket→组合的 Read；
Settlement→Ticket/Read+收盘 Snapshot；FactorVerdict→该因子全部 Settlement。
任何对象可回答"你从哪来"。

### Read 的完整 schema（系统的心脏）

```json
{
  "read_id": "R-2026-07-08-092",
  "match_id": "M-...", "snapshot_id": "S-...",
  "made_at": "2026-07-08T15:00:00+08:00",
  "judge": "claude",
  "market": "had",
  "prior":  {"home": 0.46, "draw": 0.27, "away": 0.27},
  "belief": {"home": 0.40, "draw": 0.33, "away": 0.27},
  "factors": [
    {"factor_id": "seeding_incentive", "direction": "draw",
     "weight_pp": 6,
     "evidence": [{"url": "...", "quote": "...", "at": "..."}]}
  ],
  "scenarios": [{"story": "铁桶拖平", "weight": 0.33}],
  "falsifier": "若 X 首发则撤回本偏移",
  "confidence": 3,
  "shadow": false,
  "note": "一句话人读理由"
}
```

- **shadow read**：无命名因子的场次由**代码自动**生成 `belief=prior` 的影子 Read——
  免费攒市场基线校准样本，同时把"参与"变成显式动作而非默认。
- 校验（代码）：概率归一、weight_pp 合计=belief−prior、因子必须在词典且 status≠retired、
  证据非空（shadow 除外）、conf5 仅限 90' 方向（继承判读层硬约束 a-f）。
- 判断（Claude）：因子选择、幅度、场景、falsifier——**永不烤进代码**。

## §3 五个动词（作用在本体上的无状态过程）

```
sense → read → express → reconcile → calibrate ─┐
  ▲                                              │(verdicts 改变下一轮 read 的词典)
  └──────────────────────────────────────────────┘
```

| 动词 | 做什么 | 谁做 | CLI |
|------|--------|------|-----|
| sense | 拉盘口→去水→存 Match+Snapshot(kind=read_time) | 纯代码 | `nutmeg decision-sense` |
| read | 产 Read；校验入库；补全 shadow | Claude 推理+代码校验 | `nutmeg decision-read` |
| express | Reads→Ticket（组合枚举+算术+预算闸）→PDF→Telegram | 代码算术，Claude 选型 | `nutmeg decision-express` |
| reconcile | 赛果+收盘盘口→Settlement（Brier+CLV+pnl）；pending 补扫 | 纯代码 | `nutmeg decision-reconcile` |
| calibrate | 聚合→FactorVerdict+校准曲线+参与精度→渲染面板 | 纯代码，Claude 读判决 | `nutmeg decision-calibrate` |

## §4 三方接口延续矩阵（全部继续使用，映射到动词）

| 既有接口 | 现有资产（原样复用） | 喂哪个动词 | 角色 |
|---|---|---|---|
| **体彩 sporttery webapi** | `SportteryJczqCalculatorProvider`（WAF 浏览器头）、`fetch_sporttery_value_with_fallback`、快照守卫 | sense | 竞彩在售+五玩法盘口（主源） |
| **500.com (fcom500)** | `Fcom500Client`、`parse_jczq_list`、欧赔 opening/live 采集（bold_odds 路径） | sense | 体彩备源 + 无配额欧赔去水 fair |
| **API-Football** | `ApiFootballClient`、`fetch_fixtures_by_date`、国家队别名表、`ingest_results`（90'/AET/PEN 口径+改名映射+漏结回扫） | sense + reconcile | 国际赔率主源（国家队）；赛果主源之一 |
| **okooo 澳客** | `OkoooJczqResultProvider`（分池赛果+**完场 SP 赔率**） | reconcile | 竞彩逐玩法赛果；**收盘盘口的免费来源**——完场 SP 去水即 closing snapshot，CLV 零新增抓取 |
| **体彩传统足彩 webapi** | 在售期 14 场抓取（curl 浏览器头绕 567 WAF） | sense + reconcile | 胜负彩/任九期次与开奖 |
| **Telegram Bot API** | `TelegramBotClient.send_document`、reportlab+NutmegCJK 112mm 手机 PDF | express + calibrate | 票面与校准面板推送 |
| **API-Football 伤停/阵容** | `_default_injury_counts` 等 | read（证据源） | 因子证据（T-60 两触点可选） |
| WebSearch/WebFetch | jczq-match-analyst agent（反偏置约束已烤进定义） | read（证据源） | 实时情报采集 |

多源纪律（继承）：主源失败走备源、绝不静默假空盘、WAF 降级不覆盖完好快照、
Czechia 型改名走显式映射、缺收盘快照则 CLV=null 绝不伪造。

## §5 双轴计分与因子生死

**轴一 Brier-对-赛果**（慢，真理）：`brier = Σ(belief−outcome)²`；同时算
`brier_delta_vs_prior = brier(belief) − brier(prior)`——负 = 你的偏移改善了市场先验。
Metaculus Baseline-score 的直译。

**轴二 CLV-对-收盘**（快，信息含量）：`clv_pp = (belief−prior)·(closing_fair−prior)`
的方向命中——你的偏移是否朝收盘移动。开赛即可结，不等赛果方差。

**因子生死（calibrate 的判决规则，数据驱动，继承 spec §30 反 churn）**：
- 出生：只能从复盘/洞见带 `born_from` 引用创建，初始 `probation`。
- 试用：n<30 Read 只积累不判决（"桶 n<30 不改模型"直译）。
- 转正/退休：n≥30 后看双轴——CLV 命中 >55% 且 brier_delta<0 → active；
  双轴皆平庸 → watch 一期；再平庸 → **retired（词典移除，Read 校验即拒绝）**。
- **词典有上限（≤12 个 active）**：新因子转正若超限，必须先退休最弱者——
  结构性防规则堆积（Rules A-J → R1-R28 坟场的免疫机制）。

**其它面板指标**：逐因子/逐信心桶校准曲线；**参与精度**（非 shadow 的 Read 偏移方向
命中率 vs shadow 基线）；通道盈亏（娱乐预算审计，非目标函数）。

**初始因子词典（种子，全部 probation，从实证教训出生）**：
`seeding_incentive`（签位激励，071 实证）、`bunker_profile`（铁桶压缩净胜，087 实证）、
`lineup_news_gap`（实名伤停/轮换时间差，拉赫蒂实证）、`league_bias`（极端联赛画像，
瑞超实证）、`market_line_error`（3 路口径错觉，+28pp 教训）、`fatigue_discount`
（**反向登记**：7/04 证伪方向，试用其否定式）。

## §6 表达层与预算（¥400 框架映射）

引擎档随旧机器退役；¥400/期硬顶不变，桶位改挂 Ticket.budget_bucket（**配置数据
`decision-budget.json`，不是代码规则**——数据>代码版本策略）：

| 通道 | 桶 | 上限 |
|---|---|---|
| jczq | 主方向单关(had_modal，conf≥4) | ≤¥100 |
| jczq | 让球双选对冲(hhad_cover，铁桶悬殊场) | ≤¥100 |
| jczq | 平局单关试运行(draw_single，conf≥4 ≤¥20/注) | ≤¥40 |
| jczq | 复选/串关创作(parlay) | ≤¥60 |
| shengfucai/renjiu | 每期复式(fushi) | ≤¥400/期独立 |

express 的代码职责：复式枚举（任九 C(14,9)、胜负彩复选注数）、组合赔率×命中概率
算术（从 belief 算，**禁嘴算**）、预算闸强制、判读层硬约束闸（had 默认/hhad 需单一
净胜模态≥35%——用按需 DC-from-fair 验证）。空仓永远合法：无合格 Read = 出空票面。

## §7 反积累宪法（系统的免疫系统）

1. **判断永不进代码**：代码只做取数/算术/校验/记账。出现"想把判断写成 if"的冲动 =
   去创建一个 probation 因子。
2. **政策即数据**：任何持久策略（预算/阈值/因子）必须表达为配置或本体对象，代码 PR
   携带新规则一律拒绝。
3. **词典上限 + 强制退休**：见 §5。
4. **每条教训入库时必答**："它替代哪条旧规则？旧的退休了吗？"
5. **shadow 基线永远在跑**：系统随时能回答"如果全跟市场会怎样"——防自嗨的锚。

## §8 目录与实现形态

```
nutmeg/decision/
  ontology.py      # 七对象 dataclass + schema 校验
  store.py         # JSONL 幂等 upsert + 血缘查询
  market_data.py   # 27 个数据基元迁入（去水/解析/快照IO/DC-from-fair 按需）
  sense.py         # §4 接口适配器编排
  express.py       # 组合枚举+算术+预算闸+PDF
  reconcile.py     # 赛果+收盘→Settlement（okooo SP 即 closing）
  calibrate.py     # 双轴聚合+Verdict+曲线渲染
.nutmeg-data/decision/   # {matches,snapshots,reads,factors,tickets,settlements,verdicts}.jsonl
```

judge_ledger 演进为 reconcile+calibrate 的前身（对账纪律/幂等/补扫全部继承）；
现 judge-ledger.jsonl 历史数据一次性迁移为 Read/Settlement 对象（保留 6/12 起全部战绩）。

## §9 迁移路径（与现系统的交接）

- **M0（现在起）**：建 `nutmeg/decision/` 包与五动词，不动现系统。世界杯窗口内
  现 SOP 继续跑。
- **M1（并行，→7/19）**：每日判读同时落新本体（Read/Ticket）；okooo 收盘快照开始积累
  ——CLV 轴从第一天就有数据。
- **M2（7/19 后切换）**：CLAUDE.md/AGENTS.md SOP 重写指向五动词；tiered/bold 残余
  + 33 信号符号 + jczq_market_kernel（被 decision/market_data 取代）删除；launchd
  改挂 decision-* 命令。
- **范围外**：telegram-bot advisor / match-brief / jczq_web 等客户端工具的存废是
  独立产品决策（roadmap Tier D3 悬而未决），本设计不处置。

## §10 测试策略

- market_data：金样快照夹具（现有测试迁移）；store：幂等 upsert/血缘完整性。
- reconcile：hhad 让球线数学（继承 2026-07-06 修复的全部回归测试）、AET/PEN 90'
  口径、CLV 手算夹具对照。
- calibrate：Brier/CLV/校准曲线对手算夹具；Verdict 阈值边界。
- express：预算闸、复式注数枚举（任九 C(14,9)=2002 校验）、组合赔率算术。
- e2e：从快照 replay 一整天 → 确定性产出（sense/express 均可回放）。

## §11 错误处理（继承的教训清单，全部有实证出处）

WAF 降级不覆盖快照（6/11）｜字符串 schema 不丢整日（6/28）｜pending 补扫+absent
救回（7/06）｜未识别标签 pending 不误判输（7/06 review）｜改名映射方向【API→种子】
（7/06 review）｜凌晨场 D+2 补结（7/06）｜缺数据=null 绝不伪造。

## §12 开放问题（实现计划中决断）

1. 收盘快照的兜底：okooo SP 缺失时是否用 API-Football 最后刷新价（倾向：是，标 source）。
2. GPT 第二评委（跨 agent 分歧纪律）在 Read.judge 维度的接入时机（倾向：M1 后）。
3. 历史 judge-ledger 迁移的字段映射细则。

---

## 附录 A · 符号处置清单（权威版，2026-07-06 从 `nutmeg/services/jczq_market_kernel.py` AST 实测生成）

实施 M0 时按此清单执行，**不要重新推导**（本会话已验证过依赖闭包）。

### A.1 迁入 `nutmeg/decision/market_data.py`（29 个，零 KILL 依赖，可直接搬）

```
常量/标签: OUTCOMES, MARKETS, MARKET_LABELS, OUTCOME_LABELS, HARD_LABEL,
          _RE_CRS_KEY, _CRS_OTHER_LABELS, _TTG_LABELS, _HHAD_LABELS
去水数学:  _devig_map, _fair_from_odds, _tc_vig, _clip01, _f, _signed_float
盘口解析:  _had_from_pool, _ttg_from_pool, _crs_from_pool, _ttg_bucket_goals,
          _crs_pick_label, _market_pick_label
类型:     BoldMatch(见 A.2 净化说明), GradedLeg
快照 I/O:  fetch_sporttery_value_with_fallback, persist_sporttery_snapshot,
          persist_bold_odds_snapshot, load_sporttery_snapshot, load_bold_odds_snapshot
结算:     grade_leg
```

### A.2 过渡符号（3 个，带 KILL 依赖，**不迁入**；净化后替代）

| 符号 | 污染点 | 处置 |
|---|---|---|
| `BoldLeg` | 携带 `boldness` 字段（引擎世界观入侵类型） | 不迁；新系统 Ticket.legs 自带 schema；M1 期间留在旧 kernel 供 tiered 用 |
| `bold_leg_for_market` | 用 LEG_ODDS_MIN/MAX 门槛 + market_boldness | 同上，M1 过渡；express 直接构造 Ticket legs |
| `bold_matches_from_sporttery` | 调 `_strong_favorite_tags`（heat tags 进 BoldMatch） | **迁入时做净化版** `matches_from_sporttery`：同解析逻辑，删 tags/信号字段（M0 的唯一手术点，需对照测试） |

### A.3 M2 处死清单（48 个，随 tiered 引擎一起删，Read 层结构性禁止 import）

```
信号打分: MARKET_SIGNALS, conflict_score, contrarian_score, drift_score,
  dispersion_score, heat_score, internal_conflict, external_conflict_ttg,
  _crs_internal_conflict, _market_signal_scores, _generic_contrarian,
  _market_outcomes, _match_uncertainty, _is_draw_lean, _strong_favorite_tags,
  MatchSignals, PoolSignals, compute_pool_signals
权重/常量: WEIGHT_CONFLICT, WEIGHT_CONTRARIAN, WEIGHT_DRIFT, WEIGHT_DISPERSION,
  WEIGHT_HEAT, _SIGNAL_WEIGHTS, DRIFT_GAIN, DISPERSION_GAIN, HEAT_VIG_GAIN,
  HEAT_TAG, HEAT_TAGS, CHAOS_SCALE, ANCHOR_GAP_THRESHOLD, LEG_ODDS_MIN, LEG_ODDS_MAX
boldness: boldness, market_boldness
chaos:    day_chaos, chaos_band
主题:     THEME_DRAW, THEME_SCORE, THEME_HANDICAP, THEME_GOALS, THEME_MIXED,
  _MARKET_THEME, _THEME_SCRIPTS, ticket_theme, MIN_THEME_LEGS_FOR_RETIREMENT,
  RetiredTheme, retired_themes_with_stats
```

## 附录 B · 实施交接上下文（新 session 从这里开始，无需本会话记忆）

### B.1 仓库现状（截至 commit `177f012`，分支 `research/tunisia-japan-2026-06-20`）

- **种子位置**：`nutmeg/services/jczq_market_kernel.py`（29+3+48 混装，按附录 A 拆）；
  `nutmeg/services/worldcup/judge_ledger.py`（对账/幂等/pending 补扫/hhad 按线评分，全部
  2026-07-06 修好并有回归测试，演进为 reconcile+calibrate）。
- **已删除**（不要试图引用）：`jczq_bold_combos` / `jczq_bold_review` / `jczq_second_leg`
  及其测试与 CLI 命令；3 个退役 launchd（daily-bold / bold-review-8am / daily-review-8am，
  plist 备份在 `.nutmeg-data/launchd-backups/`）。
- **仍在跑的 launchd（M1 期间不得打断）**：daily-tiered、daily-today、tiered-review-8am、
  wc-refresh-18、wc-report-20、wc-review-8am。世界杯窗口至 2026-07-19。
- **测试基线**：1051 passed / ruff 全绿 / pre-commit 已装（ruff + wc/jczq 子集）。
- **本会话关键 commit**：`9683e0e`(对账修复) `2f8f612`(¥400框架) `2f1489a`(路线图)
  `fc12621`(R1内核抽取) `57cba59`(bold删除) `0479d07`(D3证伪) `177f012`(本设计)。

### B.2 必读文件（按序）

1. 本 spec（全部设计决策在此，含依据）。
2. `docs/jczq-refactor-roadmap.md` — 旧系统处置边界（尤其 Tier D3 证伪：jczq_daily/
   conflict/intelligence/debate/web 是**活客户端底座**，未经用户产品决策不得删）。
3. `CLAUDE.md`「判读层硬约束 a-f」+「注金框架」节 — Read 校验与预算闸直接继承。
4. `docs/jczq-mixed-bet-judge-process.md` — 判读七阶段（Read 动词的操作程序前身）。
5. memory `jczq-7-06-system-retro` — 记分牌证据与全部教训出处。

### B.3 实施顺序约定

M0 起手式 = 调用 **writing-plans** skill 基于本 spec 出实现计划；实现遵循
test-driven-development skill；每步跑 `uv run pytest -q` + 收尾用项目 verify skill
（`.claude/skills/verify`，含 replay/reconcile 端到端配方）。**M1 并行期间现 SOP 照跑，
新系统只增不改；M2（7/19 后）才动 CLAUDE.md/AGENTS.md 与 launchd。**

> 关联：`docs/jczq-refactor-roadmap.md`（旧系统处置）· memory `jczq-7-06-system-retro`
> （记分牌证据）· 对标来源见 2026-07-06 会话（Palantir/Halawi/Starlizard/Metaculus）。
