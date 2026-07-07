<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md`
<!-- SPECKIT END -->

## OpenClaw / Nutmeg Project Codex Mode

When this repository is reached through OpenClaw `nutmegbot`, treat the bot as a
project-level Codex entrypoint opened at `/Users/jz71/Projects/Nutmeg`.

- `nutmegbot` is no longer limited to the legacy Telegram safe router.
- It may read and edit project files, run tests/builds, call `uv run nutmeg ...`,
  use `scripts/openclaw/nutmeg_command_router.py`, and inspect project state.
- For implementation, debugging, review, refactor, verification, or multi-step
  analysis, it should behave like Codex in this repo root and can delegate to
  the fixed local Codex CLI when invoked from OpenClaw.
- The OpenClaw `coding-agent` skill is enabled for background worker delegation;
  default project execution still uses the fixed NVM Codex CLI.
- The router remains a deterministic helper for Telegram-friendly football
  command output; it is not the boundary for project work.
- Do not leak secrets. Ask once before public dispatch, real betting/funds
  actions, large destructive deletes, or irreversible system-level operations.

## JCZQ 每日决策 SOP — 决策本体五动词（2026-07-07 M2 切换后）

> 本文件与 `CLAUDE.md` 的「JCZQ 每日决策 SOP」是**同一份行为指令的两个 harness 副本**
> （Claude Code 读 CLAUDE.md；GPT/Codex 读本文件）。改一处必须同步另一处。

历史根因：agent 即兴在多套命令/引擎/Poisson 间挑选 → 决策路径不一致。**旧 tiered/bold/
today-packet 引擎 + Poisson generator + jczq-daily/debate/web + worldcup 报告链已于
2026-07-07 全部下葬**（M2 切换，删 40 模块 / 16 旧命令 / 3 万行；含整套 Rules A-J / R1-R28 /
F1-F4 / debate 流程 / brief generator）。现在**只有决策本体一条路径**：
sense→read→express→reconcile→calibrate，市场锚定 + 命名因子偏移 + 双轴检验（Brier 慢真相 /
CLV 快信息）。设计见 `docs/superpowers/specs/2026-07-06-decision-ontology-design.md`；运营序列见
`docs/decision-shadow-run-runbook.md`。**旧 spec §25-§32 / Rules A-J 描述的引擎已删，一律忽略。**

### 触发短语（任一 → 执行下方 SOP）

- "今天的 jczq 方案" / "今天的方案" / "今天竞彩怎么打" / "出今天的票" / "做今天的投资建议"
- "today's jczq plan" / "today's bets"

### 执行步骤（决策本体五动词）

1. **数据入库 + 市场基线（`decision-am`）：**
   ```bash
   uv run nutmeg decision-am --run-date $(date +%Y-%m-%d) --output-dir .nutmeg-data/jczq
   ```
   自取体彩盘口 + 国际欧赔 → sense 去水存 Match/Snapshot（canonical 跨通道身份）→ backfill
   给未判场补 belief=prior 的市场基线 shadow。**这不出判断，只备数据底座。**（launchd 已挂
   08:00 自动；手动补跑用上面命令。网络不可用则用已存快照，sense 会回放。）

2. **判读每场（主循环最新模型实时推理 → `decision-read` 落 Read）：** 读决策 store 的当日
   Match + 欧赔 fair 锚，对每场判**走向**（胜平负 + 比分）。默认**跟市场**（欧赔=市场共识，
   无命名理由不偏移，belief=prior）；只有**实名信息面理由**（伤停/复出/轮换/战意/联赛偏差）
   才落一条**偏移 Read**（belief 背离 prior + 命名 factor + 证据 URL + falsifier）。Read schema：
   `{read_id, match_id, snapshot_id, made_at, judge, market, prior, belief,
   factors:[{factor_id, scope_key?, direction, weight_pp, evidence:[{url,quote,at}]}], confidence, shadow, note}`。
   深度分析/混合投注/世界杯窗口走**七阶段深研**（见下）。判断永不入脚本。

3. **出票（`decision-close`，¥400 框架）：** 把最优玩法结构化成 legs（`{match_id, market,
   selection, odds, bucket, line?}`，bucket ∈ main/hedge/draw/parlay）写
   `daily/<date>/legs.json`，然后：
   ```bash
   uv run nutmeg decision-close --run-date $(date +%Y-%m-%d) \
     --output-dir .nutmeg-data/jczq --dispatch-telegram --no-dry-run
   ```
   capture-closing 抓收盘欧赔（CLV 参照）→ express 按 ¥400 骨架确定性出票 → report PDF →
   Telegram 推送。**空 legs = 空票（空仓永远合法）。**

4. **次日结算 + 学习（`decision-settle`）：**
   ```bash
   uv run nutmeg decision-settle --run-date <昨天日期> \
     --output-dir .nutmeg-data/jczq --dispatch-telegram --no-dry-run
   ```
   reconcile 抓 okooo 赛果算 Brier + CLV（canonical 映射，未终局跳过不产 pending）→ calibrate
   聚合因子判决**并执行**（probation→active 转正 / 平庸→retired 退休 / 词典上限）→ report 复盘。
   （launchd 挂次晨 08:10 自动。）

5. **判读只判走向、赔率只读情绪**：判读层**不算 EV / 盈亏平衡**（那只属已删引擎档，−13% 抽水里
   正 EV 无意义）；赔率读市场情绪 + 侦测信息驱动异动（急动先查因：临场情报→改，纯噪音→守）。
   **价值只来自"市场没定价的状态/战意/伤停"**，被 CLV 事前检验、Brier 事后检验。

### 判读深研层（默认）—— `docs/jczq-mixed-bet-judge-process.md` 七阶段

世界杯窗口内、或用户要"深度分析 / 混合投注组合 / 高赔组合 / X 串 Y 方案 / 审核我的方案"时，
步骤 2 的判读自动展开成七阶段（只在判读/组合层）：
① 盘口底座（decision-am 已存 sporttery had/hhad/crs/ttg + `bold_odds.json` 去水 fair，WAF-aware）
→ ② 逐场派 `jczq-match-analyst` agent（web 深研：实力/战术/**状态/战意**/玩法判断，每场并行）
→ ③ 实力排序 + 五玩法判断（**换玩法逆转**）→ ④ 失败教训过滤（见下）+ 人性/盘口心理
→ ⑤ 判读落 `decision-read`（偏移带命名因子）+ 最优玩法写 legs（脚本算赔率×命中×期望，命中优先、留对冲）
→ ⑥ 对抗验证（挖弱腿、诚实纠错不 flip-flop）→ ⑦ `decision-close` 出 PDF 经 Telegram 推送。
**思考驱动（最重要）**：整条链路由**主循环最新模型实时推理**（反复挑战→挖最弱腿取证→诚实纠错→重判），
**不是跑一遍固定脚本**；脚本/工具/agent 只做"取现有数据 + 采集外部信息 + 确定性算术(禁嘴算)"三件支撑，
**判断永不烤进脚本**；派出的 `jczq-match-analyst` 也用 opus（judgment-heavy 不降智）。
**核心原则**：状态≠战意（常方向相反，分开判）；让球平是实证最准高赔玩法、胜平负押冷门是 0/23 死亡陷阱；
每腿押"模态"不押"隔壁"；空仓永远合法、高赔=高方差小额。
**失败教训（硬数据）**：大胆/高赔串整票 0/38 全输、腿命中 14%；让球 15%>比分 6%>胜平负冷门 0；
"3 条冷腿堆 100x+"必死。
**判读硬约束（2026-07-06 记分牌复盘落库，细则见 runbook Phase 3/4/6/7）**：
a. 反偏置六条已烤进 `.claude/agents/jczq-match-analyst.md`——**改约束改文件本体，禁止现场口传**；
b. **conf5 只许授予"90 分钟方向"**；淘汰赛"悬殊+铁桶"场正路信心硬顶 conf4 + 必配让球双选对冲；
c. 偏移票**默认 had 押模态方向**（实证 had 2/2 vs hhad 3/9）；hhad 单关需 DC 单一净胜模态 ≥35%，
   "恰净胜 N"窄带禁区；hhad leg 落盘**必带 `line`**；
d. 判读层平局单关按 bucket `draw`（conf≥4、≤¥40/注）——"平局收割 0/67"是引擎串票统计，不适用判读层单关；
e. **跟市场的否决只许信息面理由**（实名伤停/轮换级），禁 EV 语言（7/04 教训：EV 否决胜方，实证 2/2 中）；
f. Read 必须结构化 JSON（6/28 字符串票面曾丢整日判定）；decision-close/settle 收尾不可跳过（7/05 教训）；
g. league/team 级因子引用**必带 `scope_key`**（如 league_bias → "swe-allsvenskan"，校验强制）；
   联赛/球队画像读 store 的 League/Team `profile_notes`（decision-sense 已幂等落种子），不再只靠 memory
   （2026-07-07 实体层落库，见 `docs/superpowers/specs/2026-07-07-ontology-entity-layer-proposal.md`）。

### 决策本体核心立场（取代已删的 A/B/D/E 档位叙事）

- **市场锚定**：欧赔去水 fair 是先验（Opta 级超算校准）。**无命名理由 = 跟市场**（belief=prior，
  记 shadow 或判读-跟市场），不硬猜方向。
- **命名因子偏移**：只有实名信息面 gap（伤停/复出/战意/联赛偏差/签位激励/铁桶等词典因子）才 licence
  背离——belief 朝理由方向移，带 factor + 证据。**这是唯一可能有 edge 的地方**，被 CLV 事前 + Brier 事后检验。
- **因子生死**：词典上限 12，probation→active→retired 由 calibrate 自动执行；n<30 只攒不改模型（反积累免疫）。
- **空仓永远合法**；高赔=高方差小额。

### 注金框架（2026-07-06 用户定：每期 ¥400，长期成本追踪）

- **竞彩**：每比赛日总盘 **¥400 硬顶**（上限不是任务；未用完不补、不滚存）。express 按 legs 的
  bucket 骨架确定性分配：主方向单关 ≤¥100 / 让球双选对冲 ≤¥100 / 平局单关 ≤¥40 / 复选串关 ≤¥60。
  每张票 = 一个 Ticket 对象入 store → decision-settle 自动 Brier/CLV 对账。
- **传统足彩（胜负彩/任九）**：**每期 ¥400 复式预算**，独立于竞彩记账。逐场信念层与竞彩共用
  （decision-sense-zucai + 同一 Read/CLV/Brier/因子，canonical 去重）；每期收官把
  `{issue, kind(胜负彩|任九), stake_yuan, tickets, hits, prize_yuan, settled_at}` 追加到
  `.nutmeg-data/zucai/zucai-ledger.jsonl`。
- 两套 ledger 都是"**没入账 = 没打**"：¥400 框架的意义是成本可核算、长期可复盘。

### 数据纪律（5/06 嘴算 bug 教训，仍有效）

任何关于 edge / 概率 / CLV / Brier 的数字必须来自决策 store 或直接调用决策本体函数
（`nutmeg.decision.market_data` 去水 / `nutmeg.decision.scoring` 双轴），**禁止嘴算**。

> **2026-07-07 M2 切换**：本文件原「DEPRECATED · 退役 generator 历史参考」整段（Step 1-4 /
> Rules A-J / debate 流程 / jczq-daily-brief 用法，约 390 行）已随对应代码模块一并删除。历史
> 见 git 历史与 `docs/jczq-decision-chain-critique.md`。
