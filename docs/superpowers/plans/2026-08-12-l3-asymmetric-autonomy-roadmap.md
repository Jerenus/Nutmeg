# L3 升级 · 不对称自治路线图（Roadmap 级计划）

> **状态：路线图，待用户裁决优先级。** 每个 Package 被拾起时再写 task-by-task 实现计划
> （沿用 kernel-v2 的 package 计划惯例）。
> **总纲**：按 Data Agent 分级（arXiv 2507.01599 / L0-L5），本项目走**不对称自治**——
> 数据/治理/学习平面升 L3，**判读平面刻意停在 L2-L3**（判断永不入脚本，26102 实证连
> "预生成初稿"都会锚定判断）。任何功能入计划前过两道检验：
> ①它是确定性算术/采集/校验，不是判断；②它会改变某条 Read、某张 Ticket 或某次告警。
> **配套 spec**：`2026-08-12-ontology-tie-flow-rule-layer-proposal.md`（本体三层增补）。

---

## Package A · 学习闭环（价值最高——架构 L3-L4 / 实操 L2 的差距所在）

**Why**：calibrate 的因子生死机制设计完备，但现实是 factor 词典 7 条全在 probation、
CLV 轴历史结算覆盖仅 4%、判决表 k-q 条迭代纯靠人工复盘改 CLAUDE.md。
26103 预登记了四条证伪条件，**核验它们是纯确定性算术**，却没有自动化。
26102 奖金估计错 3.3 倍（估中位区，实际 ¥21,018），一次 API 查询就能避免。

- [x] **A1 falsifier 自动核验**(2026-08-12 落地:rules_registry+`decision-rules --verify-issue`,封闭谓词词典 outcome_eq/outcome_count/margin,26103 五条已登记,7 测试)（= 本体提案 §5 的最小版）：
      `rules.jsonl` 登记 `{rule_id, falsifiers[{condition, issue, outcome:pending}]}`；
      reconcile 结算时扫当期 pending → 按赛果机械判 confirmed/refuted → 更新计数；
      calibrate 面板加 Rule 段。**首个活案例：26103 四条预登记（8/14 开奖）。**
- [ ] **A2 CLV 轴复活 —— 开球感知的收盘捕获**：`capture-closing` 从"固定 19:00"改为
      按每场 kickoff T-60min 捕获（依赖 Package E 的调度，或先提供
      `--kickoff-aware` 手动模式）。目标：新结算 CLV 覆盖从 4% → 100%。
- [x] **A3 官方赛果/奖金自动回填**(2026-08-12 落地:`nutmeg zucai-official`,8 测试,26102 实盘验证)：gameNo=90 接口模块化（已验证 12/12 精确）→
      ①自动产 `{issue}-outcomes.json`（**取官方 90' 赛果串，AET 安全**，见 D3）；
      ②开奖后自动回填 ledger 的 hits/prize_yuan；③奖金 vs 回本门槛自动对账
      （26102 那类估计错误变成机器一行输出）。

**出口判据**：一个期次从开奖到 ledger 闭账零人工；预登记证伪条件的核验不再依赖"我记得去核"。

## Package B · 本体 Tier 1（⚠️时间窗：Kernel v2 Package 5 cutover 之前）

**Why**：见配套 spec §1/§2。Tie 对象让 7/7 分型从口传变先验；身份解析前置消灭
`日尔曼-维拉` vs `巴黎圣曼-维拉` 式 canonical 分裂（约束 j 传导不再靠手写注记）。

- [ ] **B1 身份解析前置**：`resolve_team()` 服务化（别名表 466 条升级为解析器）；
      match_id 改 `M-<UTC开球日>-<home_team_id>-<away_team_id>`；未解析打
      `identity_unresolved` 进 audit 日报；历史分裂对象合并脚本。
- [ ] **B2 Tie 对象**：schema + sense 建链 + reconcile 更新 aggregate/state +
      prep/brief 打印 state 与分型先验 + calibrate 按实证累积 n。
- [ ] B3（顺延自 spec Tier 3，随用随长）：画像 note 加 `as_of/valid_regime/review_after`；
      `TeamIntegrity` 快照 JSONL。

**出口判据**：一场次回合的赛制状态由本体给出而非 agent 考证；同一真实比赛跨渠道只有一个 Match。

## Package C · 数据平面自愈（L2→L3 的教科书跨越）

**Why**：今天上午的实况就是需求清单——alias-audit 报了缺口和修法，但**动手的是人**
（三条南美别名 + 一条缩写，手工五分钟）；解放者杯/欧超杯 League 实体至今靠 audit 天天点名；
8/11 板面 WAF 降级直接让 26103 丢了全部 ttg 形状约束，没有任何重试与告警。

- [x] **C1 别名自愈提案器**(2026-08-12 落地:`decision-alias-propose`,对手推断法·确定性零LLM,5 测试;双缺场如实报出不猜)：audit 未命中 → 自动 `/teams?search` 核对官方拼写 →
      产出候选补丁（含证据）→ 人一键确认写入。安全机制不变（双边匹配才生效，误映射不串场）。
- [x] **C2 League onboarding**(2026-08-12 手动闭账:解放者杯+欧超杯 League 实体入 seed+sync,audit 全绿;自动脚手架留待后续)：板面出现未解析 leagueAbbName → 自动生成 seed
      条目脚手架（name_zh 精确等于板面缩写）→ sync → audit 复验。
      **现成测试用例：解放者杯、欧超杯。**
- [ ] **C3 WAF 感知重试**：板面拿到 vtoolsConfig-only 假空盘 → 不覆盖既有快照（已有）
      **+ 定时重试 + "板面缺失"心跳**（8/11 的静默代价不再重演）。
- [ ] **C4 心跳统一**：`zucai_gate` 的三态有声模式（干活/无事/失败**都说话**）推广到
      am/close/settle——7/21 静默死亡三周的制度化解药。

**出口判据**：数据缺口从"audit 点名 + 人修"变为"agent 提案 + 人确认"；任何采集失败在当天可见。

## Package D · 确定性算术工具收敛（判读支持，零判断）

**Why**：26103 构票期间盖率/P/门槛前沿被临时脚本重算了十几次；ledger 靠内联 python
手写了五次；AET 口径是这周亲手踩过的坑（博德 90'=2-2 / goals=3-2）。

- [x] **D1 `nutmeg zucai-ticket`**(2026-08-12 落地:与 legs_audit 同 JSON,26103 实票逐位对账 432注/9.03%/¥9,563,自动过结构校验)：读 prep + 判读面集合 → 注数/P/回本门槛/前沿表 +
      需中奖注数换算（销量×0.64÷门槛）→ 自动过 `decision-audit-legs`。
      （把 `scripts/zucai_ticket_optimizer.py` 草稿收编为正式命令。）
- [x] **D2 ledger CLI**(2026-08-12 落地:`zucai-ledger --add/list`,净额汇总;结算由 zucai-official 填)：`nutmeg zucai-ledger add/settle`——替代内联 python，
      schema 校验 + 与 A3 自动回填对接。
- [x] **D3 AET 口径守卫**(2026-08-12 落地:官方 90' 串唯一权威 + 源码级守卫测试)：赛果提取一律以官方 90' 串为源；API-Football 路径强制取
      `score.fulltime` 禁 `goals`；以 2026-08-11 博德（90' 2-2 / ET 3-2）为回归 fixture。

**出口判据**：构票算术与账本操作零内联代码；杯赛加时不可能污染结算。

## Package E · 定时链分级复启（拱顶石——用户已叫停，须分级验证后逐段通电）

**Why**：当前运转自主性低于架构自主性（每天手跑 decision-am）。这是刻意的
（26102 后先想清楚再自动化），复启必须分级、每级先手动验证若干天。

- [x] **E1 prep 链**(2026-08-12 通电:enable+bootstrap+双冒烟;修 publish API bug;心跳实测报出 26104 截止 8/14 22:00)（已建成：gate→prep→heartbeat，纯只读零资金）：enable + bootstrap，
      观察 ≥3 个销售日。
- [ ] **E2 decision-am**（数据入库+基线，零判断）：接 C3/C4 后复启。
- [ ] **E3 close/settle**：默认空 legs（判读缺席=空票合法）+ A2 开球感知捕获 + 心跳。
      **判读永不进调度**——出票前的 legs 只能来自主循环判读 + `decision-audit-legs` 过闸。

**出口判据**：无人日 = 数据齐、基线在、心跳响、空票安全；有人日 = 人只做判读与裁决。

---

## 依赖与排序

```
D3 ──┬── A3 ──── A1(首案例 8/14: 26103 预登记核验)
     │
B1 ── B2（⚠️卡 Package 5 cutover 前）
C3/C4 ── E2 ── E3 ──── A2(开球感知捕获挂调度)
E1（独立，随时可启）      D1/D2（独立，随时可做）
```

**建议启动顺序**：D3+A3（小、且 8/14 结算即用）→ E1（已建成只差通电）→ B1/B2（赶 cutover 窗口）
→ A1 → C1-C4 → E2/E3 → A2 → D1/D2。

## 非目标（与升级同等重要）

- **判读平面不升自主性**：不自动出 legs、不预生成判读初稿、agent 自命名旗不获阻断权。
- 不建 Player/Appearance 对象；Team 画像不加厚。
- L4/L5 不是目标：42 Read 实证模型方向判断不优于市场，edge 在"具名信息 + 人的裁决"，
  自动化它等于复活 M2 埋葬的旧引擎。
