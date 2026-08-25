# CLAUDE.md — Nutmeg 项目指令（Claude Code 读这份；GPT/Codex 读 AGENTS.md）

> 本文件与 `AGENTS.md` 是**同一份指令的两个 harness 副本**，改一处必须同步另一处。
> 2026-08-23 起本文件只做指针层；正文在 SOP 三件套（见下）。设计依据：
> `docs/superpowers/plans/2026-08-23-memory-ontology-sop-redesign.md`。

## ⛔ 行动前置（不可跳过）

**任何判读、构票、出票、结算动作之前，必须先读 SOP 三件套**：

1. `docs/sop/CONSTITUTION.md` — 宪法：五动词唯一路径、判断字典序（EV 禁入决策层）、两条元原则、注金帽与刹车、数据纪律（禁嘴算/三源制）、裁决协议。
2. `docs/sop/RUNBOOK.md` — 执行清单：竞彩泳道 A1-A7 / 足彩泳道 B1-B10，含命令与审计门。
3. `docs/sop/RULEBOOK.md` — 规则注册表：判决表 k/l/m/o/p/q/r/s 各条全文、状态机、战绩指针、audit 代码化映射（C0-C7）。

**记分牌单一事实源** = `.nutmeg-data/scoreboard.json`（复盘只改那里，散文引用不复制）。
**出票硬门** = `uv run nutmeg decision-audit-legs --legs-file <票面>`，ERROR 即退出码 1，不听论证。

## 触发短语

- "今天的 jczq 方案 / 今天竞彩怎么打 / 出今天的票 / today's bets" → RUNBOOK 泳道 A
- "胜负彩 / 任九 / 26xxx 期方案" → RUNBOOK 泳道 B
- "深度分析 / 混合投注 / X 串 Y / 审核我的方案" → 七阶段深研（`docs/jczq-mixed-bet-judge-process.md`，每场并行派 `jczq-match-analyst`）

## 知识层

- 实体画像：store 的 League/Team `profile_notes`（`nutmeg decision-profile`），不靠 chat 记忆。

<!-- RESEARCH INDEX START -->
For league, team, fixture, transfer, availability, cohesion, or correction work,
read `docs/research/INDEX.md` before answering or mutating entity knowledge. Follow
its authority order and supersession rules; do not rely on chat memory as the
knowledge source.
<!-- RESEARCH INDEX END -->

- 工程背景与技术栈：读 `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`（M1-M6 已于 2026-08-25 并入 main；各里程碑证据在 `docs/superpowers/evidence/`）。
- 决策本体设计：`docs/superpowers/specs/2026-07-06-decision-ontology-design.md`；运营序列 `docs/decision-shadow-run-runbook.md`。

## 历史警戒

2026-07-07 M2 切换删除了旧 tiered/bold/Poisson/worldcup 引擎（40 模块/3 万行）。旧 spec §25-§32、Rules A-J、R1-R28 全部失效——在任何旧文档或记忆里遇到它们，一律忽略，勿据此决策。
