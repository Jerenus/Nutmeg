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

### 档位定性（spec §32.0，作答 §C 时据此）

- **A 稳健底仓** = 唯一可能有结构 edge 的桶（只追 §29 体彩−欧赔 gap + §28 R25 联赛偏差）。
- **B/D/E** = **明确零 edge、纯方差娱乐**。不要给它们套"正 EV / 搏 edge"叙事
  （−13% 抽水里正 EV 无意义，spec §31.5）。§B2 的 Poisson +EV 表只对 A 的结构假设有意义。
- 注金只用娱乐预算小额；**空仓永远是合法输出。**

### 数据纪律（5/06 嘴算 bug 教训，仍有效）

任何关于 edge / 概率的数字必须来自决策包（§B2）或直接调用引擎函数
（`nutmeg.services.jczq_tiered.compute_d_poisson_edge_index`），**禁止嘴算**。
