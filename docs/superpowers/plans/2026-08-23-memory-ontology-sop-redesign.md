# 记忆系统 × 决策本体 × SOP 三位一体重构设计

日期：2026-08-23 ｜ 状态：P0 已执行 / P1-P3 待用户裁定
背景事故：26109 场10（r3 先例在笔记里、检查未触发）暴露"散文记忆不参与执行"的系统病；记分牌（被排面七连/shield 0/8/牌照净线）靠人肉在复盘里携带。

## 1. 诊断（现状的四个结构病）

1. **四层记忆混写在两个平面**：CLAUDE.md（37KB，宪法+清单+履历+记分混排）与 memory/（80 文件，≈30 个已死引擎时代残留，索引扁平无分层）。检索质量随体积单调下降。
2. **记分牌不是数据**：被排面七连、shield 方向 0/8、牌照净线 2/2、保险兑现率——全部靠复盘散文手工累计，易漂移、不可查询、不进执行路径。
3. **先例/旗/裁决不是对象**：r3 的"同场地同型先例"存在于深研笔记的一句话里，audit 摸不到它 → 26105 西布罗与 26109 场10 同一死法两次。**凡是没被对象化的知识，都不参与执行。**
4. **规则没有生命周期运营**：store 里 rules.jsonl 存在但闲置；判决表 k-s 条在散文里生长，无编号、无战绩、无出生事故回链。

## 2. 目标架构：四层记忆（主流设计的本地映射）

| 层 | 主流对应 | 本项目载体 | 现状→目标 |
|---|---|---|---|
| **程序性**（怎么做） | MemGPT core / system prompt | CONSTITUTION + RUNBOOK + 审计代码 | 37KB 散文 → 三件套（见 §5） |
| **语义性**（什么是真的） | 知识图谱 / semantic memory | 本体 store：League/Team/Factor + **新对象 Flag/Precedent/Adjudication/Scorecard** | 散文断言 → 可查询对象 |
| **情节性**（发生过什么） | episodic / event log | 期档案 dossier（prep→reads→legs→rx→settlement→retro 统一命名) | 已较好（rx 模式），补统一命名 |
| **工作记忆** | context window | 会话 + daily/ | 不变 |

**巩固回路（Generative Agents 的 reflection 本地化）**：`decision-settle` 之后跑 `consolidate`——①记分牌自动累计（机械统计不判断）；②生成记忆写入提案（蒸馏，人审后落 memory/）；③标记被取代条目。记忆只增不减是病，**巩固=压缩+汰换**。

## 3. Palantir 本体拆解：第三次增补（四个新对象）

Palantir 语义：Object（业务实体）+ Property + Link + **Action Type（一切变更走动作、带 writeback）** + Function（确定性算子）。本项目已有九对象+五动词；"没入账=没打"即 writeback 原则。本次把还活在散文里的四类知识对象化：

| 新对象 | Schema 要点 | 兑现的散文知识 |
|---|---|---|
| **Flag**（旗实例） | {flag_id, type, direction?, strength, match_id, evidence[], predicted_face, outcome} | shield 方向 0/8 自动累计；旗强度校正（r5 牙口联判）成为字段不是口诀 |
| **Precedent**（先例） | {pairing_scope, venue, type(同场地同型/德比/H2H机制), sample, at, outcome} | **r3 进 audit**：双选被排面若存在活先例 → WARN（26105/26109 两死的直接修法） |
| **Adjudication**（裁决） | {issue, who(user/claude), action(lock/override/veto), evidence_rejected, alternative, outcome} | 干预记分牌：用户锁定 0/2、场5保留 1/1、我的 K1 偏移 0/2——分类可信度由数据说话 |
| **Prediction**（预注册预测） | rx 条目对象化 {claim, falsifier, outcome} | 预测 a-e 自动记分，rx 不再是自由文本 |

**工程边界**：新对象一律进 Ontology Kernel v2（SQLite typed Actions），不进旧 JSONL——对齐 Package 5 cutover 与 2026-08-12 Tie/流量/Rule 提案（该提案未采纳部分不复活，仅 Rule 生命周期与本设计合并）。

## 4. 人性工程（更符合事实与人性的推理链）

两个已被实证的人因失效模式，对策是**仪表化而非消灭**：

1. **我的"第五个更好的理由"**（自我说服）：判据进代码（audit 已证明有效）→ 本次扩展：Precedent WARN、Flag 对象化。散文规则挡不住我，数据挡得住。
2. **用户的"锁定"**（控制感/损失厌恶）：26109 两锁各费一腿，但场5保留是对的——**干预不是噪音，是未被仪表化的信号**。协议改为"举证后再锁"：锁定动作必须附一行 evidence_rejected（你拒绝的是哪条证据），入 Adjudication 对象。分歧时双方立场+falsifier 双注册，长期由分类记分牌决定"谁在哪类判断上可信"。
3. **默认降级规则**：分歧且无新证据 → 处方优先（处方近5期 13-14/14 的战绩就是这条的牌照）；用户仍可行使最终否决（¥400/帽内是你的钱），但否决被记账。
4. 不变的宪法：**字典序（事实定面→P定结构→奖池破平局）、EV 禁入决策层、空仓永远合法、禁嘴算**。

## 5. SOP 重构：一拆三

CLAUDE.md（37KB）→ 三件套，AGENTS.md 同步：

1. **CONSTITUTION（≈2KB，手写，极少变）**：五动词、字典序、禁嘴算、注金帽、触发短语、三件套指针。
2. **RUNBOOK（≈4KB，手写，按泳道）**：zucai 日常 / jczq 日常两条泳道的执行清单（命令+门+时刻表），零理论。
3. **RULEBOOK（生成物，禁手改）**：每条规则 `{rule_id, 条文, 触发器, 状态(active/probation/retired), 战绩 n/m, 出生事故, 已代码化?}`，从 rules.jsonl 渲染。判决表 k-s 条、8/08 铁律、r 条五款全部入册编号。**规则的生死由战绩驱动（同因子生死机制），不由散文长度驱动。**

## 6. 分阶段执行

| 阶段 | 内容 | 状态 |
|---|---|---|
| **P0（今日）** | 本设计文档；MEMORY.md 分层重组+历史归档（30 死条目→ARCHIVE）；`scoreboard.json` 种子（全部手工记分牌数据化）+ 渲染 md | ✅ 已执行 |
| **P1** | 三件套转正至 `docs/sop/`；CLAUDE.md/AGENTS.md 瘦身为指针层 | ✅ 2026-08-23 用户批准执行 |
| **P2a** | audit C7 `excluded_face_live_precedent`(WARN) 已入码+5测试 | ✅ 2026-08-23 |
| **P2b** | Flag/Adjudication 对象进 v2 schema | 排队(对齐 Package 5) |
| **P3** | `nutmeg decision-consolidate`：settle 后自动记分牌+记忆提案+汰换标记 | 排队 |

## 7. 验收标准（沿用本体检验法）

每项改造只问一个问题：**它会不会改变某次 Read 或 Ticket？** 会——落地；不会——砍掉。
- Precedent WARN：会（26105/26109 两张票会因此改结构）✓
- Flag 对象化：会（shield 0/8 自动化后，旗面保险的权重分配有数据依据）✓
- Adjudication：会（分类可信度改变分歧时的默认方向）✓
- 三件套：不直接改 Read，但降低"规则失传/误引"率（26103 的 o 条误用即此类）——按运维债处理 ✓
