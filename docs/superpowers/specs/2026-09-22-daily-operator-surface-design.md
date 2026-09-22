# 每日使用方式：先跑完、再对话 · 设计（含对外呈现）

日期：2026-09-22 ｜ 状态：提案，待 Jun 逐段裁定 ｜ 后续：writing-plans
依赖：RSI 层（已落地）、深研桥 `research board/run/intake`（已落地）、足彩结构层 `plan tiers/frontier/choose/commit`（已落地）、
观察台 `/observe`（已落地）、每日闭环 `rsi loop`（已落地，launchd 10:45）。

## 0. 一句话

把「开一个聊天窗口、一步步把当天跑出来」改成「定时器在人之前把当天跑到人的门口，人从结论开始对话」：
每天一个 `daily/<日>/` 对象、一条时间线、一张当日页、一个会话入口；对外只多一层只读导出。

## 1. 出生事故

- 今天的日常表面是四块碎片：`nutmeg ops-status`（终端）、`.nutmeg-data/analytics/rsi-loop/latest.md`（文件）、
  `decision-web` 8787（判读工作台 + `/observe`）、`nutmeg app` 8788（九工作区，`legacy_read_only`，RUNBOOK 不再指向它）。
  没有一处把泳道 A + 泳道 B + 定时器 + RSI 放进一个视图。
- 深研桥、结构层、观察台三份 09-19 的 spec 都已有代码，但**没有定时器**触发 `research run`；每场都出草稿 Read 的 R2 只在有人敲命令时发生。
- 结算半边没有自动化：`decision.close/settle` 两个 plist 在仓里但未装载（close 的死因 09-14 已修）；复盘靠人开会话。
- 26130（2026-09-19）：全部深研跑完、裁决单签完，却在等确认中跨过 21:00 截止，超时空仓。
  没有任何东西替人盯着截止时间。
- `com.nutmeg.jczq.results-backfill` 最近一次退出码 2，没有任何界面把它亮出来。

## 2. Jun 的意图（2026-09-22 原话归纳，作为裁定输入）

| # | 意图 |
| --- | --- |
| D1 | 很多工作在我和你沟通之前就已经完成：某时刻复盘完成、前一天闭环完成、某时刻后续比赛备料完成 |
| D2 | 某时刻有一份当天所有竞彩比赛 + 传统足彩的专项分析报告：基于实际分析结果、强弱、因子迭代对比，**给我分析逻辑** |
| D3 | 我基于已做好的准备，通过应用界面或开 session 指定当天已知结论，做进一步思考与讨论，包括最后的投注资金组合 |
| D4 | 界面参考「判断闭环解释页」：知道什么做了、什么没做、做了的结果是什么；每天在一个当日工作界面维护 |
| D5 | 应用可在既有基础上大改；过于传统或用不到的功能没有存在意义 |
| D6 | 未来加入更多查看成员和方案参考用户：专业呈现分析结果与过程；RSI 设计与迭代逻辑要有可视化空间长期维护，帮助我学习、找判断瑕疵 |

## 3. 可行性判断：能，而且大部分零件已经在

| 需要的能力 | 现状 | 缺口 |
| --- | --- | --- |
| 板面与市场基线 | `decision.am` 08:00 已跑，链到 `research board` + `rsi schedule` | 无 |
| 每场深研 + 每场草稿 Read | `research run/intake`、`jczq-build-reads` 已实现（预算 40 场/日，headless `claude -p`） | **无定时器** |
| 足彩备料三槽 | 11:00 / 14:00 / 18:30 已跑，带 Telegram | `plan tiers/frontier` 不自动跟跑 |
| RSI 闭环 | 10:45 已跑，9 步 | 无 |
| 结算与复盘 | `betslip settle`、`scoreboard settle-issue`、`workflow grade-rx`、`workbench-export`（复盘草稿）都有 | 未定时；close/settle 未装载 |
| 当日报告 | `decision-report`（PDF，竞彩）、prep md（足彩）、`latest.md`（RSI） | **没有跨泳道的一份** |
| 页面 | 8787 三栏工作台 + `/observe` + `/betslips`；零前端工具链 | **没有当日页** |
| 会话入口 | 无 `.claude/commands/`；每次从零 | **缺** |
| 截止播报 | Telegram 通道齐全（prep 已推） | **缺 T-30/T-10 播报** |
| 对外呈现 | 无 | **缺** |

结论：新增的是编排（一个 `nutmeg day` 运行器）、一个日报编译器、一张当日页、一个会话入口、一个播报器、一个只读导出。
不需要新框架，不需要新判断逻辑。

## 4. 对象：`daily/<日>/`

日期 = 北京业务日（竞彩板面日）；足彩以期为键，日目录里放指针。目录固定在 `.nutmeg-data/daily/<YYYY-MM-DD>/`：

```
timeline.json     每个作业一行 {job, planned_at, started_at, finished_at, exit, evidence_path}   ← 状态条的唯一数据源
brief.json        日报的结构化事实（§6）；brief.md 是它的渲染
retro.md          昨日复盘草稿（agent 写，标 draft）
decisions.json    待人决定 [{id, kind, deadline, default_action, status}]
session.md        会话入口读的上下文包（由 brief.json 派生，≤ 4k 字）
discussion.jsonl  会话/页面里的人机讨论（追加）
```

规则：全部**只追加**；`timeline.json` 每行必须带时间证据（沿用 `ops-status` 的纪律：拿不到就写「无时间证据」）；
任何作业失败只记一行，不阻断后面的作业（沿用 `rsi loop` 的「只留痕不抛」）。

## 5. 时间线（BJT；现有的不动，新增标 ★）

| 时刻 | 作业 | 产物 | 人？ |
| ---: | --- | --- | --- |
| 07:30 | ★ `nutmeg day settle --date 昨日`：三源赛果 → `betslip settle` / `scoreboard settle-issue` / `workflow grade-rx` / F9 记账 → `workbench-export` 复盘草稿 → `retro.md` | 昨日结算入账、复盘草稿 | 复盘草稿标 `draft`，人读后 approve 进 scoreboard 散文；数字已落记分牌 |
| 08:00 | `decision.am`（现有） | 板面、`research board`、R0 duties | 否 |
| 09:30 | `jczq.results-backfill`（现有；退出码 2 要修） | `jc-results.json` | 否 |
| 10:00 | ★ `research run --day` → `intake --write` → `jczq-build-reads`（定时化 A2/A3 前半） | 每场研究 JSON + 每场草稿 Read | 草稿 Read 仍待 approve |
| 10:45 | `rsi loop`（现有） | `latest.md`、因子提案、判决 | 提案待人 |
| 11:00 | `zucai.prep-morning`（现有） | 早备料 | 否 |
| 12:00 | ★ `nutmeg day brief`：编译 `brief.json/md`（§6） | **当日专项报告 v1** | 否 |
| 14:00 | `zucai.prep`（现有）→ ★ 链 `plan tiers` + `plan frontier`（确定性算术，宪法允许机器做第二序枚举） | 定级、风向、前沿 | `plan choose` 仍是人 |
| 14:20 | ★ `day brief --update` | 报告 v2（足彩前沿进来） | 否 |
| 18:30 | `zucai.prep-revision`（现有）→ ★ `day brief --update` | 报告 v3（位移旗） | 否 |
| 截止前 30/10 分 | ★ `nutmeg day broadcast`：对每个未定的 `decisions.json` 条目推 Telegram，明写默认动作（空仓） | 播报 | **只播报不代决** |
| 任意时刻 | 人开会话 `/today` 或打开 `/day` | 讨论落 `discussion.jsonl` | 是 |

一个运行器 `nutmeg day run --job <name>` 承担全部 ★ 作业（与 `rsi loop` 同一模式：子进程、幂等、`--dry-run`、
写 `timeline.json`）；launchd 每个 ★ 一个 plist，装载是 Jun 的行权门。

## 6. 日报 `brief.json`：事实、判断、逻辑三层分开写

D2 要的是「基于实际分析结果、强弱、因子迭代对比，给我分析逻辑」。写法上必须遵守宪法：
**日报只解释已经产生的判断，不产生新判断**。三层：

### 6.1 事实层（确定性编译，零 LLM）

每场竞彩一张卡：

```
code, name, competition, kickoff_bj, sale_close
market:   fair(开/终/位移 pp), hhad_line, 书商分歧, closing_at
strength: team_strength 指数（两队，市场外残差 + n），联赛翻车残差
research: judgment_tier(price_only|deep_research), face_status(alive/dead/never + basis), anchor_integrity,
          hole_location, license_questions 四问, death_three_proofs, directional/nondirectional flags, crash_markers,
          schedule(rotation_risk, rest_days), precedents(alive/dead 先例)
factors:  factors.json 里每个因子在本场的取值 + 该因子当前的 propose 状态(hold/propose_zero/…) + 噪声地板读数
read:     草稿 Read（judge, belief vs prior, 拨动 pp, confidence, approved?）
audit:    decision-audit-legs 对「跟市场裸单」「模态双选」「全包」三种默认表达的码（C0–C18）
```

足彩期：`prep` 三槽摘要、`tiers.json`（每场 T1–T4 + 今日风向）、`frontier` 前 k 个点（P / 注数 / 收窄处）、
日帽与任九帽、`capital_plan`（若已定案）。

RSI：`latest.md` 的表 + 每条实验距判决 n + 今日新增样本数。

### 6.2 判断层（来自已有对象，原样引用，不改写）

每场的「判断」= 草稿 Read + 判决表阶梯位置（跟市场 / 偏移 / 降格 / 翻面）+ 牌照结论（单关 / 至多双选 / 全包 / 丢）。
这些全部来自 `jczq-build-reads` 与审计门的输出；日报**不许**在这里加一句自己的看法。

### 6.3 逻辑层（agent 撰写，标注作者，禁产新判断）

每场 3–6 句：「为什么落在这一格」——按字典序复述：事实层哪一条定了面（机制三态）→ P 层哪一条约束了结构 →
表达阶梯落点 → 与市场分歧的是哪个因子、该因子在注册表里现在是什么状态（hold / 确认零 / 待 n）。
实现：`claude -p`（headless，`--allowedTools ""`，cwd 空目录，stdin = 该场 6.1 + 6.2 的 JSON，系统提示 = 宪法字典序 + 「只解释不判断」硬约束），
输出严格 JSON `{code, logic, cites:[字段路径]}`；`cites` 里出现 6.1/6.2 没有的字段即拒收，该场逻辑层写「未生成」。
成本：每场一次无联网 opus 调用，30 场 ≈ 3–5 分钟。

这样 Jun 看到的每一场都是「事实 → 判断 → 为什么」，而「为什么」的每一句都能点回一个字段。

## 7. 当日页 `/day/<date>`（8787 上新建，默认今天）

参考今天做的「判断闭环解释页」：一页、分块、每块独立降级、深浅色跟系统。Jinja + 原生 JS，不加工具链。

| 块 | 内容 | 数据 |
| --- | --- | --- |
| 状态条 | 时间线：每个作业 计划时刻 / 实际 / 退出码 / 证据路径；失败红、未到灰、跳过黄；`results-backfill` 退出 2 在这里必亮 | `timeline.json` + `launchctl list` |
| 昨日 | 结算数字（记分牌）+ 复盘草稿 + 预测兑现 rx | `retro.md`、scoreboard |
| 竞彩板 | 每场一卡（§6 三层），按开球排序，卡头显示牌照结论与截止倒计时；卡内可展开 Read、审计码、因子取值 | `brief.json` |
| 足彩期 | 风向 + 定级矩阵 + 前沿散点（P vs 注数）+ 方案卡；`plan choose/commit` 按钮保留在此 | tiers / frontier / capital_plan |
| RSI | `latest.md` 表 + 三个「待人决定」提案 + 每条实验的进度环（复用 `/observe` 组件） | rsi-loop、`/api/observe` |
| 待人决定 | `decisions.json` 列表：approve Read / choose / commit / register / deploy / 实票登记，每条带截止与默认动作 | `decisions.json` |
| 会话 | 一键复制 `uv run nutmeg day session --date …` 输出的上下文包路径；页面内的讨论框写 `discussion.jsonl` | `session.md` |

写操作只保留已有的五个：approve/reject Read、note/candidate、register-betslip、`plan choose/commit`、`run-task`。
8787 现在的三栏首页改为指向 `/day`；`/observe`、`/betslips`、`/replay` 保留。
8788（`nutmeg app`）不重建：它的九工作区没有一个是日常路径上的；等 `/day` 跑满两周后再决定是否退役（D5）。

## 8. 会话入口 `/today`

`.claude/commands/today.md`（Claude Code）与 `AGENTS.md` 新增一段（Codex）同一内容：

1. 读 `.nutmeg-data/daily/<今天>/session.md`（brief 的浓缩：每场一行判断 + 逻辑一句 + 待人决定 + 截止表）。
2. 不重跑时间线上已 `done` 的作业；有 `failed` 先报。
3. 对话从 `decisions.json` 第一条开始；每一轮结束带一行「最近截止：xx:xx，剩 N 分」。
4. 讨论落 `discussion.jsonl`（`nutmeg day note --text …`），页面同步显示。
5. 资金组合讨论只在 `plan frontier` 的点上进行；票面只从 `plan choose → commit` 出（09-19 裁定 Z2/Z7）。

## 9. 与宪法的边界（不变的部分）

- 自动化到人的门口为止：草稿 Read 待 approve；`plan choose/commit`、`rsi register/deploy`、实票登记、购买确认全部人做。
- `day brief` 的逻辑层不产生 belief、不改 Read、不写权重、不动 RULEBOOK；引用字段必须存在。
- C 类赛后资讯：`day settle` 只用于昨日；当日卡片的研究 JSON `captured_at` 必须早于开球，否则卡片标 `not_prospective`。
- 播报只报时间与默认动作，不代下单（deadline_broadcast_discipline）。

## 10. 对外呈现（D6）

两个读者层，一套数据：

| 层 | 读者 | 内容 | 形态 |
| --- | --- | --- | --- |
| 内部 | Jun | `/day` 全部 + 写操作 | 8787 |
| 对外 | 查看成员 / 方案参考用户 | ① 当日报告（事实 + 判断 + 逻辑，去掉审计码细节与内部路径）② 昨日结果与**诚实战绩**（命中率、按结构分的盈亏、Brier 相对市场、连败段不隐藏）③ 方法页（宪法摘要、判决表阶梯、RSI 闭环图、每条实验当前状态）④ 判断瑕疵榜（`scoreboard-tallies.json` 的复盘链：死点是哪条门事前点名、事后归因）| `nutmeg day publish` 生成静态 `site/`：每日一页 + 首页；先发 claude.ai artifact 给小圈子，稳定后再挂静态托管 |

RSI 长期可视化（帮助学习与找瑕疵）在 `/observe` 上加三页，全部只读、每日由 `rsi loop` 末尾重生成，导出进 `site/`：

- `/observe/rules`：RULEBOOK 与 `factors.json` 的变更时间线（`git log -p` 派生），每条变更挂它引用的实验与判决。
- `/observe/factors`：因子注册表 + `attempts.log` 里每次 propose 的历史（hold / propose_zero / propose_change 的轨迹）+ 噪声地板。
- `/observe/trace/<date>`：「昨天哪条实验本可以改变哪场的决定」——把每场的死点与当时 `not_due` 的实验对上。

对外守则：显示亏损与空仓；不出现购买指令式措辞；不放 C 类资讯；不放内部路径与 chat 记录。

## 11. 实施包（建议顺序）

| 包 | 内容 | 出口条件 |
| --- | --- | --- |
| P1 | `nutmeg day` 运行器（settle/brief/broadcast/session 四作业）+ `daily/<日>/` 对象 + `brief.json` 事实层与判断层 | 某天 08:00–12:00 无人操作，`daily/<日>/brief.json` 含板上每场卡且每场有草稿 Read；`timeline.json` 每行有时间证据 |
| P2 | `/day` 页（状态条、竞彩板、足彩期、RSI、待人决定）| 页面在无 tiers / 无 research / 内核不可用时各块独立降级；无 POST 之外的写口 |
| P3 | 定时器：`research run` 10:00、`day settle` 07:30、`day brief` 12:00/14:20/18:30 链、`day broadcast`；修 `results-backfill` 退出 2 | `launchctl list` 八加五；连续三天 `timeline.json` 无 failed |
| P4 | 逻辑层（`claude -p` 撰稿 + 引用校验）+ `/today` 会话入口 + `discussion.jsonl` | 每场逻辑层 `cites` 全部可解析；`/today` 开场不重跑任何 done 作业 |
| P5 | `nutmeg day publish` + 方法页 + 战绩页 + `/observe/{rules,factors,trace}` | 小圈子能从一个链接看懂昨天为什么输、今天为什么这样判、系统现在在验证什么 |

每个包按 `writing-plans` 出计划，TDD，证据文档落 `docs/superpowers/evidence/`。

## 12. 需要 Jun 裁定的

| # | 问题 | 我的建议 |
| --- | --- | --- |
| Q1 | 时刻表（§5）是否符合你的作息；日报 v1 定在 12:00 还是更早 | 12:00：等 10:00 深研与 10:45 闭环 |
| Q2 | 07:30 自动结算是否复启（`decision.settle` 死因已修；三源赛果缺一源时如何处理） | 复启，缺源则只出草稿不入账 |
| Q3 | 逻辑层用 `claude -p` 撰稿（每天约 30 次无联网调用）还是先只出事实层 + 判断层 | 先出三层，成本可控；撰稿失败该场写「未生成」 |
| Q4 | 8788 `nutmeg app` 的去留 | 冻结两周后退役 |
| Q5 | 对外先用 artifact 还是直接静态托管 | 先 artifact |
| Q6 | 播报默认动作是否一律「空仓」 | 是（宪法：空仓是对着数字做的选择） |
