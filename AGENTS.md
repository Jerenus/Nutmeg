## Nutmeg OpenClaw Session Contract

When the session comes from OpenClaw `nutmegbot`, read `IDENTITY.md`, `SOUL.md`,
`TOOLS.md`, and `USER.md` before acting. The primary model is Claude Fable 5.
This bot is the single command window for using Nutmeg, not a general software
development channel.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current design:
`docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`
(M1-M6 merged to main 2026-08-25; per-milestone evidence under
`docs/superpowers/evidence/`).
<!-- SPECKIT END -->

<!-- RESEARCH INDEX START -->
For league, team, fixture, transfer, availability, cohesion, or correction work,
read `docs/research/INDEX.md` before answering or mutating entity knowledge. Follow
its authority order and supersession rules; do not rely on chat memory as the
knowledge source.
<!-- RESEARCH INDEX END -->

## OpenClaw / Nutmeg Project Command Mode

When this repository is reached through OpenClaw `nutmegbot`, treat the bot as a
project-level operator and command window opened at `/Users/jz71/Projects/Nutmeg`.

- Use the current framework first: existing `uv run nutmeg ...` commands, the
  decision ontology, runbooks and stored data（旧 Telegram 命令路由器已于 2026-09-23 退役）.
  Do not recreate framework behavior in chat or invent a parallel workflow.
- The default role is operational: understand Jun's intent, choose the correct
  existing workflow, execute it, inspect outputs, challenge weak assumptions,
  and present the decision clearly.
- Do not default to feature development, refactoring, architecture changes, or
  writing new scripts. Route unrelated development requests to DevBot.
- Codex yolo capability remains available at this project root for deep
  inspection, verification, or the smallest repair needed when an existing
  Nutmeg workflow is genuinely blocked. After repair and tests, return to the
  user-facing operational task.
- Never use Codex as a second opinion that bypasses the current Nutmeg SOP. It
  must read this file and work through the same framework and data.
- The router is a deterministic Telegram-friendly interface. Use it when it
  covers the request; use the underlying current CLI directly for richer
  supported workflows.
- Do not leak secrets. Ask once before public dispatch, real betting/funds
  actions, large destructive deletes, or irreversible system-level operations.

## JCZQ/足彩 决策 SOP（2026-08-23 起为指针层）

> 本节与 `CLAUDE.md` 是**同一份指令的两个 harness 副本**，改一处必须同步另一处。
> 正文已迁移至 SOP 三件套；设计依据 `docs/superpowers/plans/2026-08-23-memory-ontology-sop-redesign.md`。
> 下面的 SOP 指针段与 `CLAUDE.md` 共享，改动必须两处同步；本文件上方的 OpenClaw 会话契约只在这里维护。

### ⛔ 行动前置（不可跳过）

**任何判读、构票、出票、结算动作之前，必须先读 SOP 三件套**：

1. `docs/sop/CONSTITUTION.md` — 宪法：五动词唯一路径、判断字典序（strength-v2：强弱天平→帽内按判断概率定结构→奖池破平；赔率=噪声识别器；EV 禁入决策层）、两条元原则、注金帽与刹车、数据纪律（禁嘴算/三源制）、裁决协议。
2. `docs/sop/RUNBOOK.md` — 执行清单：竞彩泳道 A1-A7 / 足彩泳道 B1-B10，含命令与审计门（B0 早刷新 / B4 判读桥 / B4b 候选穷举 / B9c 实票登记）。
3. `docs/sop/RULEBOOK.md` — 规则注册表：判决表 k/l/m/o/p/q/r/s 各条全文、状态机、战绩指针、audit 代码化映射（C0-C17 + INFO 参考表）。

**记分牌单一事实源** = `.nutmeg-data/scoreboard.json`（复盘只改那里，散文引用不复制）。
**出票硬门** = `uv run nutmeg decision-audit-legs --legs-file <票面>`，默认/AI/无人值守遇 ERROR 即退出码 1，不听论证；仅 Jun 显式 `--user-override` 且 evidence_rejected Adjudication 入账成功后可继续。**2026-09-27 规则瘦身**：只有正向实证的规则能拦截——截至当日判断类规则无一达标（C1 等降为记录、C19 降为未证实提示，见 RULEBOOK「〇、规则实证表」与 `docs/superpowers/evidence/2026-09-27-rule-diet.md`）；判断力由事前登记实验量化：主指标 F14（结构）+ Dream 对照账（决策）+ F10（热门带），F9 为次指标（2026-10-01）。分析要客观独立、不迎合（含对 Jun 自己的规则）。

### 触发短语

- "今天的 jczq 方案 / 今天竞彩怎么打 / 出今天的票 / today's bets" → RUNBOOK 泳道 A
- "胜负彩 / 任九 / 26xxx 期方案" → RUNBOOK 泳道 B
- "深度分析 / 混合投注 / X 串 Y / 审核我的方案" → 七阶段深研（`docs/jczq-mixed-bet-judge-process.md`，每场并行派深研 agent（Claude 侧为 jczq-match-analyst））

## /today 会话入口（Codex 同规）

对话前先读 `.nutmeg-data/daily/<日>/session.md` 与 `decisions.json`；不重跑已完成作业；从待人决定开始；
每轮末尾报最近截止与剩余分钟并明写默认动作（空仓）；讨论用 `nutmeg day note` 落盘。全文见 `.claude/commands/today.md`。

### 知识层

- 实体画像：store 的 League/Team `profile_notes`（`nutmeg decision-profile`），不靠 chat 记忆。
- 决策本体设计：`docs/superpowers/specs/2026-07-06-decision-ontology-design.md`。

### 历史警戒

2026-07-07 M2 切换删除了旧 tiered/bold/Poisson/worldcup 引擎（40 模块/3 万行）。旧 spec §25-§32、Rules A-J、R1-R28 全部失效——在任何旧文档或记忆里遇到它们，一律忽略，勿据此决策。
