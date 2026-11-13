## Nutmeg OpenClaw Session Contract

When the session comes from OpenClaw `nutmegbot`, read `IDENTITY.md`, `SOUL.md`,
`TOOLS.md`, and `USER.md` before acting. The primary model is GPT-6.1-SOL with high reasoning.
This bot is the single command window for using Nutmeg, not a general software
development channel.

## 任务交接与异常恢复

- 实质任务开始、关键里程碑、长工具调用前、交付或受阻时，调用 `task_checkpoint`，保存当前目标、状态、已有项目位置、已完成事项、产物、下一步、阻碍和待核对操作。不要保存凭据、大段日志或完整聊天。
- `/new` 后同一聊天会收到交接记录，但不等于完整历史恢复。继续前读取原有项目状态、真实产物和日志，核对后台进程/任务 ID；保存的工具返回不能证明业务完成。不要因恢复而重发消息、重复投稿/付款或重复启动实验。
- 长任务按现有项目工作流分段；长实验或生成任务使用后台进程并记录检查方式。及时更新交接，不等到上下文耗尽才保存。保留本工作区原有状态文件和同步流程作为事实来源。
- 遇到通用会话错误：建议先 `/stop`、`/taskstatus`；上下文过长可 `/compact`；持续失败再 `/new` 并读取交接后继续。换聊天/换 bot 不自动读取另一聊天的交接。
- 用户换话题时按当前目标处理，旧交接不授权继续原任务。`task_checkpoint` 不可用时，将必要状态保存在当前项目原有状态文件；不要使用全局单一“当前任务”文件混合不同聊天。

<!-- SPECKIT START -->
For the current system structure, daily schedule, judgment layer (rubric r1),
ticket review, RSI process, replay gym, data objects and the full analysis
history, read `docs/ARCHITECTURE.md` (authoritative since 2026-10-02).
Historical product design (M1-M6, merged 2026-08-25):
`docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`;
per-milestone evidence under `docs/superpowers/evidence/`.
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
> 正文已迁移至 SOP 三件套。
> 下面的 SOP 指针段与 `CLAUDE.md` 共享，改动必须两处同步；本文件上方的 OpenClaw 会话契约只在这里维护。

### ⛔ 行动前置（不可跳过）

**任何判读、构票、出票、结算动作之前，必须先读 SOP 三件套**：

1. `docs/sop/CONSTITUTION.md` — 宪法：定位（机器＝风控官+账房+实验员，人下注）、判断字典序（强弱天平→帽内按判断概率定结构→奖池破平；赔率=噪声识别器；EV 禁入决策层）、两条元原则、注金帽与刹车、数据纪律（禁嘴算/三源制）、裁决协议。
2. `docs/sop/RUNBOOK.md` — 执行清单：竞彩泳道 A1-A7 / 足彩泳道 B1-B10，含命令与审计门（B0 早刷新 / B4 判读桥 / B5 初判+初稿 / B9c 实票登记）。
3. `docs/sop/RULEBOOK.md` — 规则注册表：规则实证表、仍为满级的规则、审票否决 V1/V2、判断 rubric r1、人群假说；旧判决表 k–s 条文与 audit 代码映射（C0–C19 + INFO 参考表）归档在 `docs/sop/RULEBOOK-archive.md`。

**记分牌单一事实源** = `.nutmeg-data/scoreboard.json`（复盘只改那里，散文引用不复制）。
**出票硬门**：审计门一组（`decision-audit-legs` / `decision-explain-faces` / `decision-adjudicate` / `zucai-deployment-gate` / `zucai-ledger` / `workflow register-rx|grade-rx|grade-prediction` / `scoreboard *` 权威命令，含 `legs_audit.py` 的 C 码检查）于 **2026-10-13 删除**（10-03 / 10-08 两轮审计建议、Jun 授权；证据 `docs/superpowers/evidence/2026-10-13-audit-gate-removal.md`）。出票前唯一的机器否决是 `betslip preview` 的 V1（期望回报率 <0.5）/ V2（共享裸单＝假分散），见 RUNBOOK B9c；`legs_audit.py` 只剩封闭词典。**2026-09-27 规则瘦身**：只有正向实证的规则能拦截——截至当日判断类规则无一达标（C1 等降为记录，见 RULEBOOK「〇、规则实证表」与 `docs/superpowers/evidence/2026-09-27-rule-diet.md`；C19 2026-10-19 随 F11 证伪永久退休）；判断力由事前登记实验量化：主指标 F14b（结构：表态 vs 市场同尺寸 top-k；F14 2026-10-19 按冻结原文证伪）+ gym 规则 v3 回放（决策，`gym run --policy jczq_rule_v3 --belief read`，2026-10-04 Dream 退役后承接）+ F10（热门带），F9 为有害监测（2026-10-01；**判决协议 v2 2026-10-19**：按登记 bound 判、单次结账，证据 `docs/superpowers/evidence/2026-10-19-rsi-protocol-v2.md`）。分析要客观独立、不迎合（含对 Jun 自己的规则）。

### 触发短语

- "完整足彩 SOP / 逐场深研 / 分析包做成页面" → Codex 业务入口 `.agents/skills/zucai-sop/SKILL.md`；完整验收后才交终稿，不以中间包交差；`judgment packet-check --issue <期>` 与人工内容/页面验收均须通过。缺必要输入只报阻塞与恢复条件，能独立推进的步骤继续做完；各阶段不提前冒记完成。

- "今天的 jczq 方案 / 今天竞彩怎么打 / 出今天的票 / today's bets" → RUNBOOK 泳道 A
- "胜负彩 / 任九 / 26xxx 期方案" → RUNBOOK 泳道 B
- "虚拟规则赛 / arena / 竞彩虚拟单榜单" → RUNBOOK 泳道 C（全程虚拟，不进净值和判断层）
- "深度分析 / 混合投注 / X 串 Y / 审核我的方案" → 深研与审票（`docs/jczq-mixed-bet-judge-process.md`：逐场研究 → Jun 出方案 → `betslip preview` 审票 → 登记）
- "/zucai-packet <期> / 按我的问题梳理 / 分析包" → RUNBOOK B5e 阅读层（`.claude/commands/zucai-packet.md`，2026-10-14 起**三屏一桥**：A 三屏 §0 头部 · §1 决策表 14 行（26165 起主表只留 场·市场/系统·档·条件·默认动作·死门，其余列进折叠附表；列全集：档·锚方中轴·洞在谁·翻车面·标签(弱/真实·价内/未价，10-16 F19)·六条件 k/n·人群(钱→哪面)·默认动作·死门 P·赛前看谁）· §1b 人群地图（PM 分市场量·资金去向·富勒姆型三判据，10-18；`crowd polymarket --flow`）· §2 胆与票（胆表 ≤5 行 + 主形一张 + 替代一张 + 死法清单）一次出齐 → B 桥 §3 只走一次（五条自检、差异格、死法清单）→ C 审票登记 §4 → D 次日 `retro` §5（决策表加「开」「许可证 ✓/✗」）；发布为报告页）

## /today 会话入口（Codex 同规）

对话前先读 `.nutmeg-data/daily/<日>/session.md` 与 `decisions.json`；不重跑已完成作业；从待人决定开始；
每轮末尾报最近截止与剩余分钟并明写默认动作（空仓）；讨论用 `nutmeg day note` 落盘。全文见 `.claude/commands/today.md`。

### 知识层

- 实体画像：store 的 League/Team `profile_notes`（`nutmeg decision-profile`），不靠 chat 记忆。
- 决策本体设计：`docs/superpowers/specs/2026-07-06-decision-ontology-design.md`。

### 历史警戒

2026-07-07 M2 切换删除了旧 tiered/bold/Poisson/worldcup 引擎（40 模块/3 万行）。旧 spec §25-§32、Rules A-J、R1-R28 全部失效——在任何旧文档或记忆里遇到它们，一律忽略，勿据此决策。
