# Nutmeg 结构设计（现役系统 · 2026-10-02）

> 本文是**现役系统的结构总图**：定位、组件、每日数据流、判断层、出票与审票、RSI 实验层、Discovery Harness、数据对象、全量分析过程与工程流程。
> 规则与操作的权威仍是 SOP 三件套（`docs/sop/CONSTITUTION.md` 原则 → `RUNBOOK.md` 执行 → `RULEBOOK.md` 规则）；数字的权威是 `.nutmeg-data/scoreboard.json` 与内核；本文与它们冲突时以它们为准，并回来改本文。
> 维护规则：任何改变组件边界、定时任务、对象或流程的提交，同一提交更新本文对应小节与图。

---

## 0. 一句话与定位

Nutmeg 是中国体彩**竞彩足球（JCZQ）**与**传统足彩（胜负彩 / 任九）**的判断与账务系统。

**2026-10-01 定位（Jun 同意）**：403 天回放证明机器的判断概率≈市场、帽内最大化全对概率的出票形状长期亏损、没有任何策略族在样本外 ROI 为正——**机器不再是最终决策者**。

| 角色 | 谁 | 做什么 |
|---|---|---|
| 风控官 | 机器 | 审票：只否决有实证的坏结构（V1 期望回报 < 0.5、V2 与已购票共享裸单），其余只警告与给数字 |
| 账房 | 机器 | 诚实账本：月净值 vs 空仓、止损线 −¥3,000、偏离初稿按理由结账、判断力指标 |
| 实验员 | 机器 | 预登记实验、逐项结账、证伪；探索预算 ≤¥30/日只给预登记实验 |
| 研究员 | 机器 | 每天对样本池逐场深研，按固定问题表（rubric r1）作答，出初判包；足彩另出**机器初稿** |
| 下注者 | Jun | 出当日方案、改初稿、买票、登记 |

两条元原则（宪法 §3）：**判断永不入脚本**（脚本只做取数、采集、确定性算术）；**判据必须入代码**（没被对象化的知识不参与执行）。

---

## 1. 系统总图

```mermaid
flowchart TB
  subgraph SRC["① 外部数据源"]
    direction LR
    S1["体彩竞彩计算器<br/>500.com 备源"] ~~~ S2["titan007<br/>终盘 · 历史 SP"] ~~~ S3["API-Football<br/>国际欧赔"] ~~~ S4["体彩官方 gameNo=90<br/>足彩赛果 · 奖金"] ~~~ S5["足彩期次源"]
  end
  subgraph ING["② 采集与入库 · 确定性脚本"]
    direction LR
    I1["decision-am<br/>入板 · 赔率快照"] ~~~ I2["zucai-prep<br/>早 / 午 / 复核备料"] ~~~ I3["赛果回填<br/>终盘补采"]
  end
  subgraph CORE["③ 事实层"]
    direction LR
    K[("本体内核<br/>ontology.db")] ~~~ F[("运行文件<br/>jczq · zucai · daily")] ~~~ SB[("记分牌<br/>scoreboard.json")]
  end
  subgraph JUD["④ 判断层"]
    direction LR
    R1["深研分析员 A<br/>研究 JSON + rubric r1"] --> R2["协议级聚合<br/>rubric 派生 tilt"] --> R3["Read<br/>写回内核 revision"]
    OV["改判<br/>落到 rubric 项"] --> R3
    R1 --> RB["系统一读者 B<br/>两读 κ"]
  end
  subgraph OUT["⑤ 面板"]
    direction LR
    P1["当日报告<br/>brief · session · site"] ~~~ P2["判决参考页"] ~~~ P3["初判包"] ~~~ P4["足彩机器初稿"]
  end
  subgraph HUM["⑥ 人与审票"]
    direction LR
    H1["Jun 出方案<br/>或改初稿"] --> T1["betslip preview<br/>V1 / V2 否决 · V3 警告"] --> H2["500 app 买票"] --> T2["betslip register<br/>偏离理由 + 预测"]
  end
  subgraph ACC["⑦ 结算与账务"]
    direction LR
    T3["day settle<br/>结算 · 写入记分牌"] --> T4["account month<br/>净值 vs 空仓"]
  end
  subgraph EXP["⑧ 实验层"]
    direction LR
    E1["RSI 闭环 10:45<br/>结账 · 判决 · 因子提案"] ~~~ E2["Dream 夜录 20:30<br/>影子世界 · 对照账"] ~~~ E3["回放 gym<br/>403 天锦标赛"]
  end
  SRC --> ING --> CORE --> JUD --> OUT --> HUM --> ACC --> EXP
  CORE -.->|"内核 · 运行文件 · 语料"| EXP
```

| 层 | 主要代码 | 权威产物 |
|---|---|---|
| 采集 | `nutmeg/decision/fetch.py` `market_data.py` `zucai_prep.py` `scripts/titan007_closing_backfill.py` `scripts/jczq_result_backfill.py` | `jczq/daily/<日>/sporttery_markets.json` `jczq/jc-results.json` `zucai/<期>-issue.json` `zucai/official-*.json` |
| 内核 | `nutmeg/ontology/`（repository / actions / migrations，schema 47） | `.nutmeg-data/ontology/ontology.db` |
| 判断 | `research_runner.py` `research_prompt.py` `rubric_items.py` `rubric.py` `stance.py` `jczq_reads.py` `zucai_auto_judgment.py` `pool.py` `overrides.py` `rubric_reader.py` `judgment_projection.py` | `research-<code>.json` / `<期>-research-m<N>.json`、`reads.json`、`legs-base`、内核 forecast revision |
| 面板 | `day_brief.py` `day_session.py` `day_publish.py` `verdict_page.py` `judgment_brief.py` `zucai_draft.py` `signals.py` | `daily/<日>/brief.md` `session.md`、`site/`、`verdict.html`、`<期>-draft.md` |
| 审票与账务 | `review.py` `review_runner.py` `betslip.py` `betslip_diagnosis.py` `bankroll.py` `account.py` `retro_encoder.py` | `betslips.jsonl` `scoreboard.json` `analytics/account/<月>.md` |
| 实验 | `rsi_loop.py` `rsi_grading.py` `experiments/*.py` `nutmeg/discovery/` `nutmeg/gym/` | 内核 rsi_* 表、`experiments/corpus-v2.json` `factors.json` `registry/`、`analytics/rsi-loop/` |
| 运行 | `day_runner.py` `day_decisions.py` `day_broadcast.py` `day_ops.py` `day_runs.py` `ops_status.py` | `daily/<日>/timeline.json` `decisions.json` `broadcasts.jsonl` |

---

## 2. 每日时序

### 2.1 定时任务

launchd 14 个（plist 单一来源 `ops/launchd/`，装载副本在 `~/Library/LaunchAgents/`），OpenClaw 3 个仍在用。

```mermaid
gantt
  title 每日定时任务（北京时间）
  dateFormat HH:mm
  axisFormat %H:%M
  section 数据
  早盘入板 decision.am（失败 30 分后重试）   :a1, 08:00, 20m
  OpenClaw 昨日内核结算                      :a2, 08:10, 10m
  赛果回填                                   :a3, 09:30, 10m
  赛果回填 二跑                              :a4, 15:30, 10m
  OpenClaw 临场刷板                          :a5, 17:15, 15m
  section 研究与判断
  深研 jczq.research（并集池 ≤40 场）        :b1, 10:00, 40m
  判决页刷新 主版                            :b2, 12:30, 10m
  判决页刷新 晚版                            :b3, 18:45, 10m
  section 足彩备料
  早备料                                     :c1, 11:00, 10m
  午备料                                     :c2, 14:00, 10m
  截止前复核                                 :c3, 18:30, 10m
  section 面板
  当日报告 v1（带模型解释）                  :d1, 12:00, 15m
  当日报告 v2                                :d2, 14:20, 10m
  当日报告 v3                                :d3, 18:35, 10m
  section 结算与实验
  结算 day.settle                            :e1, 09:45, 10m
  结算 二跑                                  :e2, 15:45, 10m
  RSI 闭环 12 步                             :e3, 10:45, 30m
  OpenClaw D1D2 补结算                       :e4, 12:30, 10m
  Dream 夜录                                 :e5, 20:30, 20m
```

| 定时器 | 时刻 | 命令 | 喂给谁 | 断流后果 |
|---|---|---|---|---|
| `decision.am` | 08:00（失败等 30 分重试） | `nutmeg_scheduler_ops.py run-strict --stage am` → `decision-am` | 内核板面、深研、RSI 义务排程 | 当天没有板面；体彩列表**完全为空**记为合法空盘（2026-10-02） |
| `jczq.results-backfill` | 09:30 / 15:30 | `scripts/jczq_result_backfill.py` | `jc-results.json` → 结算、语料、夜账 | 结算与语料停在旧日期（lag>2 天退出 2） |
| `day.settle` | 09:45 / 15:45 | `day run --job results` + `--job settle` | 实票结算、记分牌复盘编码、处方预测记账 | 昨日票未结、账房缺数 |
| `jczq.research` | 10:00 | `decision-am` → `research run` → `research intake --write` → `jczq-build-reads` | 研究文件、Read、内核 revision、足彩自动 legs-base | 判断层零产出；空盘日两步自动跳过 |
| `rsi.loop` | 10:45 | `rsi loop`（12 步，§5.3） | 实验结账、因子提案、Dream 对照账、语料 | 判决与提案停在前一天 |
| `zucai.prep-morning` / `prep` / `prep-revision` | 11:00 / 14:00 / 18:30 | `zucai-prep --slot … --dispatch-telegram` | 足彩期次、store-ids、位移复核 | 足彩样本池与初稿没有输入 |
| `day.brief` | 12:00 / 14:20 / 18:35 | `day run --job brief`（12:00 带模型解释）+ `day publish` | 当日报告、会话入口、站点、足彩初稿自动重建 | `/today` 会话入口与 `/day` 页读到旧报告 |
| `day.verdict` | 12:30 / 18:45 | `research refresh` + `research verdict` | 判决参考页 | 人工裁决看旧页 |
| `day.dream` | 20:30 | `day run --job dream` → `discovery nightly` | Dream 影子世界（常设批准至 2026-10-31） | 当晚世界缺录；空盘记为跳过 |
| `day.broadcast` | 每 10 分 | `day run --job broadcast` | Jun（Telegram） | 截止无人提醒（26130 复发） |
| `rsi.sweep` | 每小时 :00 | `rsi sweep` | F5 / F9 / R0 / R1 的前瞻观察义务 | 加场日义务过期成缺口，不能回补 |
| `account.month` | 每月 1 日 16:10 | `account month --previous --write` | 账房月报 | 月报缺席（可手跑） |

OpenClaw 在用（2026-10-01 起只保留确定性任务，GPT 平行判断链全部停用）：08:10 `decision-settle` 昨日内核结算、12:30 D1/D2 补结算（预演）+ `build-context`、17:15 `run-strict --stage am` 临场刷板。

**已退役**：`zucai.f2-observe`（2026-10-02，随 F2 退役，§5.4）；OpenClaw 收盘 / 每日最终决策 / 早间复盘对齐 / 最终决策补跑 / 收盘前闸门（2026-10-01 停用；真票路径改为 preview → 500 app → register）。

### 2.2 高频任务的设计

| 任务 | 出身 | 设计 | 现状判断 |
|---|---|---|---|
| 截止播报 | 26130 等裁决等到停售，全天工作变空仓 | 每 10 分钟扫一遍「待人决定」，截止前 30 / 10 分钟各发一条，同截止合并；已发不重发 | 2026-10-02 换内容：去掉已不存在的「Read 草稿审批」，只提醒「足彩停售前仍无登记实票」与「竞彩预审过方案却未登记」，每次播报现算 |
| RSI 义务巡检 | RSI 实验进内核后，每场观察义务必须在开球前完成；17:15 加场的比赛覆盖不到 | 每小时跑到期义务的观察仪，过期不回补 | 必须；空跑成本几秒 |
| 让球线观察 | F2 预注册：每期最早开球前一个窗口内录让球线 | 每 15 分钟判一次窗口 | 已退役：冻结窗口内主档样本到不了 n_min，26131 起观察单为空 |

### 2.3 人在哪里介入

```mermaid
sequenceDiagram
  autonumber
  participant M as 机器
  participant J as Jun
  participant A as 500 app
  M->>J: 12:00 当日报告 / 12:30 判决页主版（初判包、足彩初稿、账房行）
  J->>M: 出方案或改初稿
  M->>J: betslip preview 审票（V1/V2 否决 · V3 警告 · 对照初稿 · 刹车行）
  Note over M,J: 有 ⛔ 改票后再审；坚持原票可以登记（登记是事实）
  M-->>J: 若截止前 30 / 10 分仍未登记 → Telegram 提醒
  J->>A: 下单
  J->>M: betslip register（偏离初稿带理由 + 可证伪预测）
  M->>M: 次日 09:45 结算 · 复盘编码 · 记分牌
  M->>J: 每月 1 日 账房月报
```

---

## 3. 判断层

### 3.1 判断的宪法（strength-v2 + rubric r1）

- **第一序·强弱天平**：判断目标是两队本场的最终强度对比（阵容、本场状态、风格对位、战术剧本、弱势方取胜路径、事件分级）。
- **赔率是噪声识别器**：与价格不一致时必须回答「市场看到了什么我没看到」。
- **第二序·P 定结构**：预算外生，帽内按判断概率定结构；EV 不入决策层（审票的 V1 是风控否决，不是选票目标）。
- **判断契约（rubric r1，2026-10-02）**：程度不再手写 pp。研究层对 16 项类型化问题逐项给「成立概率 + 来源 + 采集时间」，pp＝项目上限×概率由代码派生，上限只许从逐项结账往下调或退役。

### 3.2 研究到 Read 的数据流

```mermaid
flowchart TD
  A["样本池<br/>足彩在售期优先 ∪ 竞彩全板<br/>pool.py · 预算 40 场/日"] --> B["深研分析员 A<br/>claude -p · NUTMEG_MODEL_RESEARCH"]
  B --> C["研究 JSON<br/>强弱天平 · 表态 stance · rubric r1"]
  C --> D{"校验 research_runner._validate"}
  D -->|"rubric 缺失或写错：软化为弃权<br/>（永不拒收，保护 R0/R1）"| E["validate_rubric<br/>答是无来源 / 晚于开球 → 强制弃权"]
  D -->|"结构性错误：拒收重试"| X["*.rejected.json"]
  E --> F["rubric_to_tilt 协议级聚合<br/>事实层无成立 → 归零<br/>均势 → 归零 · 已定价 → 事实 pp 减半 · 峰值 ≤15pp"]
  F --> G["stance.tilt（派生）<br/>原手写 tilt 留在 tilt_declared"]
  G --> H["apply_tilt<br/>锚层证据 · 开球后证据作废"]
  H --> I["Read（belief / stance / rubric 视图）<br/>jczq_reads · zucai_auto_judgment"]
  I --> J[("内核 forecast revision<br/>kind / board_key / judgment_json")]
  J --> K["judgment project<br/>投影覆盖 reads.json（判断唯一事实 P2）"]
  C --> L["系统一读者 B<br/>haiku · 只读证据层"]
  L --> M["侧车 rubric-&lt;code&gt;.json<br/>两读 κ"]
  N["research override<br/>--items-json + --reason"] --> J
```

要点：

1. **样本池**（并集池，Jun 2026-09-27）：足彩在售期的场次优先，加上竞彩全板；未开球场次的 Read 自动交本体。
2. **研究契约**：`research_prompt.RESEARCH_JSON_CONTRACT` + `rubric_contract()`（问题表由 `rubric_items.question_table()` 生成，契约与代码不会漂移）+ 分析员定义 `.claude/agents/jczq-match-analyst.md`。
3. **rubric r1 问题表**：事实层 7 项（主/客缺阵官宣、停赛、轮换、门将、场地、其他）、结构层 6 项（锚方、中轴完整、弱方路径、平局模态、翻车候选、死面）、价格层 2 项（市场读法、事实已定价）。全文与上限见 RULEBOOK「九」或 `nutmeg rubric items`。
4. **永不因 rubric 拒收**：漏写＝全部弃权（`rubric_missing`），不合法选项改弃权（`rubric_notes`）。
5. **改判**：有 rubric 的研究，改判必须落到项并给封闭理由（新官宣信息 / 证据层级不够 / 已被价格吸收 / 研究自相矛盾 / 回市场），tilt 从合并后的 rubric 重新派生；改判账在判决页按理由分层。
6. **判断唯一事实**：Read 自报 `kind / board_key / code`，内核每个序列取最高 revision 投影回 `reads.json`；手工 `decision-read` 已退役。
7. **两读**：读者 B 只读分析员写下的证据层，逐项作答；κ<0.4 的项要重写或删；B 的整体概率只记账（F9 已证 LLM 整体概率≈市场）。

### 3.3 足彩泳道的 legs-base 与机器初稿

```mermaid
flowchart LR
  P["zucai-prep 备料<br/>期次 · store-ids（含 fair）"] --> Q["并集池刷新 pool.refresh_day"]
  R["研究 &lt;期&gt;-research-mN.json<br/>或映射到的竞彩研究"] --> Q
  J1["主循环 judgment-v1（可选，永远优先）"] --> Q
  Q --> S["&lt;期&gt;-reads.json → 内核"]
  Q --> T["&lt;期&gt;-legs-base.json<br/>自动版（不覆盖手工版）"]
  T --> U["zucai_draft 处方忠实初稿<br/>只丢场不降档 · 刹车档 · max-P 对照"]
  U --> V["审票：奖金模型 V1 = 市场口径 × 判断溢价<br/>V2 与已购票共享裸单"]
  V --> W["&lt;期&gt;-draft.md · 当日报告 · 判决页"]
```

- **自动 legs-base（2026-10-02）**：并集池刷新时为截止当天的期次自动建 legs-base（判断来源与 Read 相同，研究的结构字段与 rubric 经 `research_intake` 转录）；没有 `auto` 标记的手工版一律不动。
- **初稿规则**：处方面集合装进帽，任九 14 选 9 只丢场不降档；装不下才降档，每步砍票内判断概率最低的面并写出。
- **奖金模型**（`scripts/zucai_prize_model.py`）：log(奖金)=a+b·S（S＝按市场概率的全板意外度）；任九 n=41、b=1.007、相关 0.95。b≈1 意味着**市场口径下任何形状的期望回报都≈返奖率**，差别只在判断溢价。

---

## 4. 出票、审票、登记与账务

```mermaid
flowchart TB
  A["方案<br/>竞彩腿文件 / 足彩票面"] --> B["betslip preview（买之前）"]
  subgraph PRE["审票输出"]
    direction LR
    B1["诊断<br/>共享裸单 · 联死概率<br/>对照处方 · 对照初稿"] ~~~ B2["审票<br/>V1 期望回报 &lt; 0.5 否决<br/>V2 与已购票共享裸单 否决<br/>V3 倍投 / 重注 警告"] ~~~ B3["刹车行<br/>本月净 vs −3,000"] ~~~ B4["预审留痕<br/>previews.jsonl → 截止播报"]
  end
  B --> PRE
  PRE -->|"有否决"| RE["改票后重新 preview<br/>（人坚持原票也可以登记，登记是事实）"]
  PRE -->|"可出（人定）"| C["500 app 下单"]
  subgraph POST["买之后"]
    direction LR
    D["betslip register<br/>偏离理由 + 可证伪预测"] --> E[("betslips.jsonl<br/>竞彩实票同时写内核")] --> F["day settle<br/>09:45 / 15:45"] --> G[("scoreboard.json<br/>tickets · balance_ledger")] --> H["account month<br/>净值 vs 空仓 · 偏离按理由"]
  end
  C --> POST
```

| 规则 | 内容 | 出处 |
|---|---|---|
| 审票否决 | 只有 V1、V2 两条；人坚持原票可登记 | RULEBOOK「八」，`review.py` |
| 月度止损 | 本月净值 ≤ −¥3,000 → 空仓到月底（只报不拦，登记是事实） | 宪法 §4，`bankroll.py` |
| 探索预算 | ≤¥30/日、只给预登记实验，票面 `--note "EXP:<号>"` | 宪法 §4，`account.py` |
| 偏离登记 | 票面与机器初稿有差异时带理由（自判事实 / 价格直觉 / 资金分配 / 结构偏好 / 其他）+ 一句可证伪预测 | RULEBOOK「九」，`betslip_diagnosis.vs_draft` |
| 结算三源 | 90 分钟口径；竞彩 `jc-results.json`，足彩官方 gameNo=90 | RUNBOOK A7 / B10 |

---

## 5. RSI 实验层

### 5.1 实验生命周期

```mermaid
stateDiagram-v2
  [*] --> registered: rsi register（人，冻结哈希）
  registered --> observing: 义务被兑现（rsi fulfill，前瞻＝产物时刻早于开球）
  observing --> graded: rsi grade（适配器，n_cum ≥ n_min）
  graded --> falsified: rsi verdict（系统，冻结判据）
  graded --> survived: rsi verdict
  graded --> inconclusive: rsi verdict
  survived --> deployed: rsi deploy（人，只许 structural 且 deploy_eligible）
  falsified --> retired: rsi deploy --retire（人）
  observing --> retired: rsi deploy --retire（人，义务同时停用）
  registered --> retired: rsi deploy --retire（人）
  observing --> held: rsi deploy --hold（人）
  survived --> extended: rsi deploy --extend 新实验（人）
```

- 登记原件 `experiments/registry/<ID>.json`（claim / mechanism / window / falsifier / stop_rule / duties），登记后冻结；改冻结字段只能另立新实验。
- **判决只许系统，部署只许人**。退役（2026-10-02 起）同时把该实验的义务置为 retired，排程、到期、巡检都不再列它。
- 「前瞻」的唯一证明：产物时刻早于开球（研究文件 `captured_at`、观察仪产物 mtime）。

### 5.2 实验清单（2026-10-02）

| 实验 | 层 | 问的是什么 | 状态 / n |
|---|---|---|---|
| R0 | 覆盖 | 竞彩全板每场有前瞻深研 | observing 101/200 |
| R1 | 覆盖 | 并集样本池每场有前瞻深研 | observing 37/200 |
| F9 | 判断 | 拨动天平的场次 Brier 优于市场 | observing；残差 −0.2pp CI[−0.9,+0.6] |
| F14 | 判断（主） | 表态面集合命中率高于其市场覆盖率 | registered 0/60 |
| F10 | 判断（主） | 0.60–0.80 热门带命中高于价格 | registered 17/150；+19.5pp CI[+1.8,+32.5] |
| F15 | 判断（主） | 终盘 ≥0.70 大热被低估 | registered 0/100 |
| G1 | 结构（主） | gym 规则 `jczq_fav_pairs` 平注 ROI>0 | registered 0/100 |
| K1 | 判断 | rubric 两读合并 κ ≥ 0.40 | registered 0/100 |
| F3 / F5 / F11 / F13 / F4 / F8 | 结构 / 判断 | 冷热板模态、价格带、保险点名、崩塌叙事、门成本、其他 | 见 `nutmeg rsi status` |
| F2 / F1c | 价格因子 | 让球线位移 / 书商分歧度 | **retired 2026-10-02**（窗口内到不了 n_min） |

`nutmeg rsi status` 是唯一事实源；本表只是快照。

### 5.3 每日闭环（10:45 `rsi loop`）

```mermaid
flowchart TB
  subgraph IN["取数与语料"]
    direction LR
    L1["1 closing_backfill<br/>titan007 终盘补采"] --> L2["2 rubric_read<br/>读者 B：昨天 + 今天 + 在售期"] --> L3["3 corpus_build<br/>语料 v2 重建"]
  end
  subgraph JUDGE["结账与判决"]
    direction LR
    L4["4 grade_prospective<br/>F3 F4 F5 F9 F10 F11 F13 F14 F15 G1 K1"] --> L5["5 verdict_due<br/>到期判决（系统）"] --> L6["6 factor_propose<br/>T13 提案 · 含 rubric 逐项"]
  end
  subgraph EXPLORE["探索与对照"]
    direction LR
    L7["7 hyp<br/>假设批次"] --> L8["8 factor_search"] --> L9["9 team_strength"] --> L10["10 scoreboard 解析"] --> L11["11 dream_compare<br/>昨晚世界对照账"]
  end
  L12["12 commit_outputs<br/>自动提交 experiments/ 三个文件"]
  IN --> JUDGE --> EXPLORE --> L12
```

报告在 `.nutmeg-data/analytics/rsi-loop/<日>.json|md` 与 `latest.md`，「待人决定」进当日报告。

### 5.4 因子注册表（T13）与 rubric 逐项结账

- `experiments/factors.json`：因子分 fact（只记录）与 probability（可测可提案）；**propose 从不写权重**，改权重只许人经 `rsi deploy`。
- 规则：n ≥ 60、只收可证明前瞻的行、高于置换地板、训练窗与测试窗同号才 `propose_change`；够 n 而与地板不可分 → `propose_zero`（证伪路径）。
- **rubric 逐项因子**（11 个 `rubric_<id>`，`experiments/rubric_rows.py`）：行＝{项成立, 效应面开出, 效应面市场价, 前瞻}；只结账在用版本（`SUPPORTED_VERSIONS`）。
- 版本治理：增删项必须先有证据文档 → `RUBRIC_CHANGELOG` → 升版本号 → 退役项写 `until`、新项写 `since`。

### 5.5 语料

`experiments/corpus-v2.json`（2026-10-02：1,665 行，竞彩 1,052、足彩 518、内核 95）由 `experiments/corpus_build.py` 每天重建：判读文件、内核 forecast、titan007 终盘三条泳道合并，`provably_prospective` 由 `nutmeg/decision/prospective.py` 判定。研究标签带 rubric 答案（A）与读者 B 侧车（`rubric_b`，赛后读的标非前瞻）。

---

## 6. Discovery Harness 与 Dream

```mermaid
flowchart TD
  S["常设批准 standing-dream-nightly-2026-10<br/>至 2026-10-31 · 可撤销"] --> N["20:30 day run --job dream<br/>→ discovery nightly"]
  N --> D{"day_inputs<br/>板面 · Read · 体彩报价 · 实际票面"}
  D -->|"缺板面文件或未开球场次 &lt; 2"| SK["记为跳过 board_too_small<br/>空盘日不再记失败（2026-10-02）"]
  D -->|"有世界"| AU["authorize_nightly<br/>批准 · 截止时刻 · 开球过滤"]
  AU --> RC["record_shadow_world<br/>写影子库（policy / discovery 表）"]
  RC --> CMP["次日 10:45 dream_compare<br/>实际票 · 规则 v2 · 规则 v3 · 世界各档 · 空仓"]
  CMP --> LED[("analytics/dream-compare/ledger.jsonl")]
  subgraph GYM["回放 gym（离线 · 与 Dream 互为参照）"]
    direction LR
    G1["17:00 快照板 + 上赛季 SP 历史板<br/>官方奖金缓存 · 精确结算"] --> G2["nutmeg gym run<br/>策略族按时间顺序 · 月度刹车"] --> G3[("analytics/gym/&lt;run&gt;/")]
    G4["nutmeg gym verify<br/>复现记分牌"] --> G3
  end
```

- **Dream** 每晚把截止时刻未开球的场次与 Jun 的实际票面冻结成一个影子世界；锦标赛、晋级、部署仍只许人。就绪门 `record_to_baseline` 要 30 个封存世界、20 个独立业务日。
- **评估器 v3**（`dream_compare.decision_rule_v3`）：期望回报 < 0.5 否决，过线里取最高，最高 < 1 则规则最优＝空仓。10-31 裁决是否成为唯一规则行。
- **回放 gym**（`nutmeg/gym/`）：17:00 体彩快照板 + 上赛季 SP 历史板 + 官方奖金缓存，精确结算，按时间顺序带月度刹车；`gym verify` 复现记分牌（9 月 −4,721 精确吻合）。

---

## 7. 数据对象

### 7.1 运行文件（`.nutmeg-data/`，gitignored）

| 路径 | 内容 |
|---|---|
| `jczq/daily/<日>/` | `sporttery_markets.json` `jczq-legs-base.json` `reads.json` `research-<code>.json` `rubric-<code>.json` `overrides.jsonl` `closing_odds.json` `signals.md` `verdict.html` `judgment-brief.md` |
| `jczq/jc-results.json` `jc-history.json` `void-matches.json` | 竞彩赛果、上赛季 SP 历史、作废场 |
| `zucai/` | `<期>-issue.json` `-store-ids.json` `-legs-base.json` `-reads.json` `-judgment-v1.json` `-research-m<N>.json` `-rubric-m<N>.json` `-draft.json/.md` `-legs-draft-<渠道>.json`；`official-results.json` `official-prizes.json` `prize-model.json` |
| `daily/<日>/` | `brief.json/md` `session.md` `decisions.json` `timeline.json` `broadcasts.jsonl` `previews.jsonl` `retro.md` `results-90.json` |
| `betslips.jsonl` | 登记簿（实票 / 试玩、诊断、偏离理由、预测） |
| `scoreboard.json` | **记分牌单一事实源**（tickets、balance_ledger、adjudications、链） |
| `ontology/ontology.db` | 本体内核 |
| `analytics/` | `rsi-loop/` `rubric/` `account/` `gym/` `dream-compare/` `team_strength.json` |
| `logs/` | 各定时器的 out/err 日志（状态页按日志时刻判断，不默认它是今天的） |

### 7.2 内核（schema 47，185 张表）

| 表族 | 用途 | 备注 |
|---|---|---|
| `match` `market` `official` `source` `entity` | 身份、报价、官方赛果、来源 | 身份只认显式映射（RULEBOOK g-scope） |
| forecast revisions（schema 47 起带 `kind / board_key / judgment_json`） | 判断唯一事实 | `nutmeg judgment project` 投影 |
| `ticket` `scoreboard` `claim` `factor` | 实票、记分牌镜像、主张、因子 | 竞彩实票由 `betslip register` 写入 |
| `rsi_*`（8） | 实验、义务、观察、结账、判决、部署、修正 | `nutmeg rsi status` |
| `policy_*`（16） `discovery_*`（5） | Dream 影子库同一套迁移 | 不能删 |
| `operator_*`（78） | 旧操作台对象 | 退役专项 2026-10-09（分支 `kernel/operator-retirement`） |

运维规则见 `docs/ontology-kernel-operations.md`。

---

## 8. 全量分析过程（证据链）

每一步都是「复盘或回放 → 证据文档 → 规则或结构变更」，证据在 `docs/superpowers/evidence/`。

| 日期 | 发现 | 结论 → 变更 | 证据 |
|---|---|---|---|
| 07-07 | 旧 tiered/bold/Poisson 引擎无法自证 | M2 切换为决策本体五动词（sense → read → express → reconcile → calibrate） | `specs/2026-07-06-decision-ontology-design.md` |
| 08-23 | 规则散在记忆和聊天里 | 记分牌单一事实源 + SOP 三件套 | `plans/2026-08-23-memory-ontology-sop-redesign.md` |
| 09-18 → 09-22 | 判据从没被逐条结账 | RSI 实验进内核、每日闭环、T13 因子注册表、语料 v2 | `specs/2026-09-18-rsi-experiment-persistence-design.md` `evidence/2026-09-22-rsi-closed-loop-first-run.md` `evidence/2026-09-22-experiment-sample-inventory.md` |
| 09-23 | Read 全抄市场，F9 恒 0 | 研究表态契约 stance | `specs/2026-09-23-research-stance-contract-design.md` |
| 09-26 | 规则太严，帽内连续零解 | strength-v2：强弱天平、赔率作噪声识别器 | `plans/2026-09-26-strength-v2-judgment-overhaul.md` |
| 09-27 | 19 条判断类码无一正向实证 | 规则瘦身：只有正向实证的规则能拦截 | `evidence/2026-09-27-rule-diet.md` |
| 09-30 | 两天表态面 16/16 全对而拨动净负 | 拨动必须有官宣/确证结构证据做锚；F13/F14 登记；登记即诊断、复盘编码器 | `evidence/2026-09-30-project-review-follow-ups.md` |
| 10-01 | GPT 平行链与主循环互不为输入；判断住在多份文件 | 设计系列 8 项：GPT 链停用、真票入内核、评估换轴、判断唯一事实 P0–P2、内核瘦身勘察、身份链、月度止损、Dream v3 | `evidence/2026-10-01-design-series.md` |
| 10-01 | **403 天回放**：帽内 max-P −20%（CI 不含 0）、任九 −58%；大热两两上赛季 −18.8%；大热校准样本外 +4.7pp 但体彩价 ROI −10.9%；实力模型前瞻 null | **定位转向**：机器＝风控官 + 账房 + 实验员，人＝下注者 | `evidence/2026-10-01-replay-gym.md` `evidence/2026-10-01-history-expansion.md` `evidence/2026-10-01-price-edge-validation.md` `evidence/2026-10-01-team-strength-prospective.md` |
| 10-01 | 足彩初稿不能省；任九 P 与中奖奖金反相关 | 机器初稿（处方忠实）+ 奖金模型（b≈1） | `evidence/2026-10-01-design-series.md` §11 |
| 10-02 | 判断的「程度」是手写数字，无法逐项检验 | rubric r1 类型化问题表 + 协议级聚合 + 读者 B 两读 + K1 + 逐项因子 | `specs/2026-10-02-rubric-judgment-contract-design.md` |
| 10-02 | **历史重打分**（260 份研究、190 行有赛果）：公开缺阵 / 门将 / 中轴受损成立时所押方向比市场少中 6–11pp；只有弱方路径 +2.3（n=100）与轮换 +2.4（n=27）为正 | 事实项上限大概率偏高，待前瞻 n≥60 再调；非前瞻，不定权重 | `evidence/2026-10-02-rubric-judgment-contract.md` §6 |
| 10-02 | 改判与人的判断都没有按理由结账 | 改判落到 rubric 项 + 封闭理由；人的偏离登记 + 账房按理由结账；rubric 版本治理 | 同上 §5 |
| 10-02 | 运行层体检：空盘日 Dream/深研崩溃、因子提案会 KeyError、R1 显示为 0、播报内容过时、F2 不可能结账 | 空盘跳过、提案解析 rubric 因子、R1 按观测数、播报换内容、F2/F1c 退役、足彩 legs-base 自动化、早盘空盘不再报失败 | 同上 §7，`evidence/2026-10-02-ops-review.md` |

**当前判断力的诚实读数**：F9（程度判断）残差 −0.2pp、CI 含 0——belief≈市场；结构判断（F14）与热门带（F10/F15）在前瞻结账中；rubric 历史探查显示「公开信息已定价」。系统的产出是**少亏多少 + 证伪了几条**。

---

## 9. 工程流程

```mermaid
flowchart TB
  subgraph DESIGN["设计与实现"]
    direction LR
    Q["问题<br/>复盘 · 回放 · Jun 的问题"] --> SP["设计 spec<br/>docs/superpowers/specs"] --> PL["实施计划<br/>docs/superpowers/plans<br/>（只放未完成）"] --> TDD["测试先行实现<br/>tests/ · uv run pytest"]
  end
  subgraph LAND["落地与同步"]
    direction LR
    EV["证据<br/>docs/superpowers/evidence"] --> SOPS["SOP 三件套<br/>CONSTITUTION · RUNBOOK · RULEBOOK"] --> DOC["本文 · README<br/>定时数据流文档"] --> MEM["记忆<br/>~/.claude/projects/…/memory"]
  end
  DESIGN --> LAND
```

- **验证**：`make verify`（ruff + compileall + pytest）；全量约 3 分钟；提交前看真实退出码，不用 `| tail` 吞掉它。
- **提交**：只用显式路径 `git add <path>`，绝不 `-A/-u`；实验输出文件由 10:45 闭环自动提交（`--no-verify`，只提交 `experiments/` 三个文件）。
- **定时器**：plist 单一来源 `ops/launchd/`；新增或退役必须同一提交更新 `day_runs.JOBS`（运行记录页的证据来源）、本文 §2 与 `docs/ops/2026-09-20-scheduled-dataflows.md`。
- **数据**：`.nutmeg-data/` 不进 git；研究原件只读，改判走 `research override`。
- **模型分档**：深研继承默认（opus），逻辑层解释 sonnet，读者 B haiku（`NUTMEG_MODEL_*`）。

---

## 10. 文档地图

| 想知道 | 读 | 状态 |
|---|---|---|
| 现役结构与流程 | 本文 | 权威 |
| 原则、规则、执行 | `docs/sop/CONSTITUTION.md` `RULEBOOK.md` `RUNBOOK.md` | 权威 |
| 定时任务与断流后果 | `docs/ops/2026-09-20-scheduled-dataflows.md` | 权威（2026-10-02 更新） |
| 内核运维 | `docs/ontology-kernel-operations.md` | 权威 |
| 实体知识 | `docs/research/INDEX.md`；画像在 store 的 `profile_notes` | 权威 |
| 某个组件为什么这样设计 | `docs/superpowers/specs/<日>-<主题>-design.md` | 设计时的原件；被后续 spec 或本文取代的部分以后者为准 |
| 某个变更是否落地、数字是多少 | `docs/superpowers/evidence/` | 证据 |
| 工程背景（M1–M6 产品化） | `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md` | 历史设计；工作区与治理的思路仍有效，现役结构以本文为准 |
| OpenClaw 时代的调度契约 | `docs/nutmeg-scheduler-operations.md` | 部分过时（见其头注） |
| 2026-07-07 之前的引擎 | tag `v0.4.0` | 已废止，勿据此决策 |
