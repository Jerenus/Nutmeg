# CLAUDE.md — Nutmeg 项目指令（Claude Code 读这份；GPT/Codex 读 AGENTS.md）

> 本文件与 `AGENTS.md` 共享同一段 SOP 指针（行动前置 / 触发短语 / 知识层 / 历史警戒 / today），改动这段必须两处同步；`AGENTS.md` 另含 OpenClaw 会话契约，只在那边维护。
> 2026-08-23 起本文件只做指针层；正文在 SOP 三件套（见下）。

## ⛔ 行动前置（不可跳过）

**任何判读、构票、出票、结算动作之前，必须先读 SOP 三件套**：

1. `docs/sop/CONSTITUTION.md` — 宪法：定位（机器＝风控官+账房+实验员，人下注）、判断字典序（强弱天平→帽内按判断概率定结构→奖池破平；赔率=噪声识别器；EV 禁入决策层）、两条元原则、注金帽与刹车、数据纪律（禁嘴算/三源制）、裁决协议。
2. `docs/sop/RUNBOOK.md` — 执行清单：竞彩泳道 A1-A7 / 足彩泳道 B1-B10，含命令与审计门（B0 早刷新 / B4 判读桥 / B5 初判+初稿 / B9c 实票登记）。
3. `docs/sop/RULEBOOK.md` — 规则注册表：规则实证表、仍为满级的规则、审票否决 V1/V2、判断 rubric r1、人群假说；旧判决表 k–s 条文与 audit 代码映射（C0–C19 + INFO 参考表）归档在 `docs/sop/RULEBOOK-archive.md`。

**记分牌单一事实源** = `.nutmeg-data/scoreboard.json`（复盘只改那里，散文引用不复制）。
**出票硬门**：审计门一组（`decision-audit-legs` / `decision-explain-faces` / `decision-adjudicate` / `zucai-deployment-gate` / `zucai-ledger` / `workflow register-rx|grade-rx|grade-prediction` / `scoreboard *` 权威命令，含 `legs_audit.py` 的 C 码检查）于 **2026-10-13 删除**（10-03 / 10-08 两轮审计建议、Jun 授权；证据 `docs/superpowers/evidence/2026-10-13-audit-gate-removal.md`）。出票前唯一的机器否决是 `betslip preview` 的 V1（期望回报率 <0.5）/ V2（共享裸单＝假分散），见 RUNBOOK B9c；`legs_audit.py` 只剩封闭词典。**2026-09-27 规则瘦身**：只有正向实证的规则能拦截——截至当日判断类规则无一达标（C1 等降为记录、C19 降为未证实提示，见 RULEBOOK「〇、规则实证表」与 `docs/superpowers/evidence/2026-09-27-rule-diet.md`）；判断力由事前登记实验量化：主指标 F14（结构）+ gym 规则 v3 回放（决策，`gym run --policy jczq_rule_v3 --belief read`，2026-10-04 Dream 退役后承接）+ F10（热门带），F9 为次指标（2026-10-01）。分析要客观独立、不迎合（含对 Jun 自己的规则）。

## 触发短语

- "今天的 jczq 方案 / 今天竞彩怎么打 / 出今天的票 / today's bets" → RUNBOOK 泳道 A
- "胜负彩 / 任九 / 26xxx 期方案" → RUNBOOK 泳道 B
- "深度分析 / 混合投注 / X 串 Y / 审核我的方案" → 深研与审票（`docs/jczq-mixed-bet-judge-process.md`：逐场研究 → Jun 出方案 → `betslip preview` 审票 → 登记）
- "/zucai-packet <期> / 按我的问题梳理 / 分析包" → RUNBOOK B5e 阅读层（`.claude/commands/zucai-packet.md`，2026-10-14 起**三屏一桥**：A 三屏 §0 头部 · §1 决策表 14 行（档·锚方中轴·洞在谁·翻车面·标签(弱/真实·价内/未价，10-16 F19)·六条件 k/n·人群(钱→哪面)·默认动作·死门 P·赛前看谁）· §1b 人群地图（PM 分市场量·资金去向·富勒姆型三判据，10-18；`crowd polymarket --flow`）· §2 胆与票（胆表 ≤5 行 + 主形一张 + 替代一张 + 死法清单）一次出齐 → B 桥 §3 只走一次（五条自检、差异格、死法清单）→ C 审票登记 §4 → D 次日 `retro` §5（决策表加「开」「许可证 ✓/✗」）；发布为报告页）
- "/today / 今天的结论 / 从今天开始" → 读 daily/<日>/session.md（`.claude/commands/today.md`）

## 知识层

- 实体画像：store 的 League/Team `profile_notes`（`nutmeg decision-profile`），不靠 chat 记忆。

<!-- RESEARCH INDEX START -->
For league, team, fixture, transfer, availability, cohesion, or correction work,
read `docs/research/INDEX.md` before answering or mutating entity knowledge. Follow
its authority order and supersession rules; do not rely on chat memory as the
knowledge source.
<!-- RESEARCH INDEX END -->

- 结构总图与工程流程：读 `docs/ARCHITECTURE.md`（现役系统：定位、每日时序、判断层与 rubric、出票审票、RSI、回放 gym、数据对象、全量分析过程、文档地图；2026-10-02 起为权威）。
- 工程背景（历史设计）：`docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`（M1-M6 已于 2026-08-25 并入 main；各里程碑证据在 `docs/superpowers/evidence/`）。
- 决策本体设计：`docs/superpowers/specs/2026-07-06-decision-ontology-design.md`。

## 历史警戒

2026-07-07 M2 切换删除了旧 tiered/bold/Poisson/worldcup 引擎（40 模块/3 万行）。旧 spec §25-§32、Rules A-J、R1-R28 全部失效——在任何旧文档或记忆里遇到它们，一律忽略，勿据此决策。
