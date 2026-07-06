# CLAUDE.md — Nutmeg 项目指令（Claude Code 读这份；GPT/Codex 读 AGENTS.md）

> 本文件与 `AGENTS.md` 的「JCZQ Daily Decision SOP」是**同一份行为指令的两个 harness
> 副本**。改一处必须同步另一处。背景见 `docs/jczq-decision-chain-critique.md` + spec §32。

## JCZQ Daily Decision SOP — 单一入口 `jczq-today`（2026-06-04）

历史根因：每个 agent（GPT/Claude）即兴在多套命令/引擎/Poisson 间挑选 → 同一任务决策
路径不一致（"每次跳出系统、隔离决策"）。现在**只有一条路径**。

⚠️ 仓里的 `jczq-daily-brief` / `jczq-daily-advisor` / `jczq-mixed-report` 与
`docs/jczq-decision-framework.md` 里整套 Rules A-J / R1-R28 / F1-F4 描述的是**已退役的
Poisson generator**。live 引擎是 `jczq-tiered`（规则见 spec §25-§31）。做每日决策一律
忽略退役路径，只跑下面这条 SOP。

### 触发短语（任一 → 执行下方唯一 SOP）

- "今天的 jczq 方案" / "今天的方案" / "今天竞彩怎么打" / "出今天的票" / "做今天的投资建议"
- "today's jczq plan" / "today's bets"

### 唯一执行步骤

1. **只跑这一条命令，别的都不要跑：**
   ```bash
   uv run nutmeg jczq-today \
     --write .nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/today-packet.md
   ```
   网络不可用时用 `--replay YYYY-MM-DD` 从已存快照回放；省略 `--write` 打到 stdout。
2. **用 Read 工具读 `today-packet.md`。** 这份决策包是今天**唯一**的决策来源——它已
   确定性地跑完 live 引擎（tiered A/B/D/E）+ 盘面底座（热度 + raw Poisson +EV）+ 裁量问题。
3. **§A 引擎票面 = 已定，勿改腿。** 照单呈现给用户，或建议整张不买。**不要**在退役
   generator / 旧 brief（`jczq-daily-brief`）/ debate 流程 / 各 spec 间即兴重新选腿。
4. **只在 §C「裁量问题」上动判断**，按包里 schema 逐条作答（q_id / 决定 /
   confidence 1-5 / 一行理由）。§C 之外的一切都已被引擎定死。
5. **跨 agent 一致性约定**：你与别的 agent（GPT↔Claude）在某 q_id 答案不同 = 该场
   高不确定 → 建议减注或剔除，**不是**二选一赌运气。
6. **（世界杯窗口 2026-06-11 ~ 07-19）答完 §C 后必须收尾**：
   a. 把作答写入 `.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/judgment-answers.json`，
      schema：`{date, answers: [{q_id, decision, confidence(1-5), reason}],
      agents, final_note, answered_at}`；多 agent 分歧场次标 `divergent: true`。
   b. 以评判员身份写 `.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/predictions.json`
      （schema 见 judge spec §1）：当日**每场**世界杯比赛给明确判定+比分+看球
      逻辑理由+信心 1-5；**要敢偏离市场，理由写球不写概率**；当日信心最高
      （≥4）的在售场次出评判员票（单关 ¥15，与引擎注金永不合账）；冠军 pick
      明确到一支队，换 pick 要写理由。
   c. 跑 `uv run nutmeg jczq-report --date today --dispatch-telegram --no-dry-run`
      推送当日 PDF 世界杯日报。**这是「完成决策」的收尾动作，不可省。**
   窗口外此条自动失效（jczq-report 会提示无世界杯赛事）。

7. **评判员深研层（默认）—— `docs/jczq-mixed-bet-judge-process.md`**：世界杯窗口内、或用户要
   "深度分析 / 混合投注组合 / 高赔组合 / X 串 Y 方案 / 审核我的方案"时，§6(b) 自动展开成这套
   **七阶段深研流程**（引擎 §A 仍勿改腿；深研只在判读/组合层）：
   ① 盘口底座（`SportteryJczqCalculatorProvider` 取 had/hhad/crs/ttg/hafu + `bold_odds.json` 去水 fair，WAF-aware）
   → ② 逐场派 `jczq-match-analyst` agent（web 深研：实力/战术/**状态/战意**/玩法判断，每场并行）
   → ③ 实力排序 + 五玩法判断（**换玩法逆转**）→ ④ 失败教训过滤（见下）+ 人性/盘口心理
   → ⑤ 组合（脚本算赔率×命中×期望，命中优先、留对冲）→ ⑥ 对抗验证（挖弱腿、诚实纠错不 flip-flop）
   → ⑦ 手机 PDF（reportlab+NutmegCJK 112mm）经 `TelegramBotClient.send_document` 推送。
   **思考驱动（最重要）**：整条链路由**主循环最新 Claude 实时推理**（反复挑战→挖最弱腿取证→诚实纠错→重判），
   **不是跑一遍固定脚本**；脚本/工具/agent 只做"取现有数据 + 采集外部信息 + 确定性算术(禁嘴算)"三件支撑，
   **判断永不烤进脚本**；派出的 `jczq-match-analyst` 也用 opus（judgment-heavy 不降智）。
   **核心原则**：状态≠战意（常方向相反，分开判）；让球平是实证最准高赔玩法、胜平负押冷门是 0/23 死亡陷阱；
   每腿押"模态"不押"隔壁"；空仓永远合法、高赔=高方差小额。
   **失败教训（硬数据）**：大胆/高赔串整票 0/38 全输、腿命中 14%；让球 15%>比分 6%>胜平负冷门 0；
   "3 条冷腿堆 100x+"必死。
   **判读层硬约束（2026-07-06 记分牌复盘落库，细则见 runbook Phase 3/4/6/7）**：
   a. 反偏置六条已烤进 `.claude/agents/jczq-match-analyst.md`——**改约束改文件本体，禁止现场口传**；
   b. **conf5 只许授予"90 分钟方向"**；淘汰赛"悬殊+铁桶"场正路信心硬顶 conf4 + 必配让球双选对冲；
   c. 意见票**默认 had 押模态方向**（实证 had 2/2 vs hhad 3/9）；hhad 单关需 DC 单一净胜模态 ≥35%，
      "恰净胜 N"窄带禁区；hhad 票落盘**必带 `line`**；
   d. 判读层平局单关按 tag `draw_single` 试运行（conf≥4、≤¥20/注、30 注后按 ledger 裁决）——
      "平局收割 0/67"是引擎串票统计，不适用判读层单关；
   e. **A 档否决只许信息面理由**（实名伤停/轮换级），禁 EV 语言（7/04 教训：EV 否决 A，A 2/2 中）；
      每次 A-veto 标 `a_veto: true` 单独累计；
   f. `opinion_ticket` 必须结构化 dict（6/28 字符串票面曾丢整日判定）；收尾三件套不可跳过（7/05 教训）。

### 档位定性（spec §32.0，作答 §C 时据此）

- **A 稳健底仓** = 唯一可能有结构 edge 的桶（只追 §29 体彩−欧赔 gap + §28 R25 联赛偏差）。
  补结后实证（5/25-7/05）：A 2/17 回款 201/385，微弱结构信号；B 0/14、D 0/2、E 0/7。
- **B/D/E** = **明确零 edge、纯方差娱乐**。不要给它们套"正 EV / 搏 edge"叙事
  （−13% 抽水里正 EV 无意义，spec §31.5）。§B2 的 Poisson +EV 表只对 A 的结构假设有意义。
- 注金只用娱乐预算小额；**空仓永远是合法输出。**

### 注金框架（2026-07-06 用户定：每期 ¥400，长期成本追踪）

- **竞彩**：每比赛日总盘 **¥400 硬顶**（上限不是任务；未用完不补、不滚存）。分配骨架见
  runbook Phase 5：引擎档按其自身输出**不加注**；判读层增量拆 主方向单关 ≤¥100 /
  让球双选对冲 ≤¥100 / 平局单关试运行 ≤¥40 / 复选串关创作票 ≤¥60。每张票结构化进
  `predictions.json` → judge ledger 自动对账（`jczq-report` 每次渲染前自动补结最近 3 天 +
  全部 pending；手工全量核账用 `nutmeg jczq-judge-reconcile`）。
- **传统足彩（胜负彩/任九）**：**每期 ¥400 复式预算**，独立于竞彩记账。每期收官把
  `{issue, kind(胜负彩|任九), stake_yuan, tickets, hits, prize_yuan, settled_at}` 追加到
  `.nutmeg-data/zucai/zucai-ledger.jsonl`（agent 维护，同 predictions.json 落盘纪律）。
- 两套 ledger 都是"**没入账 = 没打**"：¥400 框架的意义是成本可核算、长期可复盘。

### 数据纪律（5/06 嘴算 bug 教训，仍有效）

任何关于 edge / 概率的数字必须来自决策包（§B2）或直接调用引擎函数
（`nutmeg.services.jczq_tiered.compute_d_poisson_edge_index`），**禁止嘴算**。
