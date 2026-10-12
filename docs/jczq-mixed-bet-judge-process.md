# 深度分析与方案审核（竞彩 / 足彩，现役流程）

> 触发：「深度分析 / 混合投注 / X 串 Y / 审核我的方案」（CLAUDE.md / AGENTS.md）。
> 2026-10-08 改写：本文原是 2026-06 世界杯窗口的七阶段 runbook，里面的旧出票链与日级 regime 命令早已删除，
> 原文只在 git 历史里。
> 定位（宪法）：机器给判断、审票与账，**Jun 出方案、买票**；机器不构票、不替人定票面。命令细节以 `docs/sop/RUNBOOK.md` 为准。

## 0. 原则
- 思考由主循环实时驱动：挖最弱的那条腿，用新的工具调用取证；改判说清「什么变了、为什么」，别在浅层证据上来回摆。
- 脚本只做取数、采集、确定性算术；概率、P、回报一律来自命令输出，**禁嘴算**。
- 分析员定义（`.claude/agents/jczq-match-analyst.md`）里的反偏置约束、90 分钟口径、3 路让球对主循环同样适用。
- **空仓永远合法。**

## 1. 先看已有的判断（不重跑）
- 判决页 `uv run nutmeg research verdict --day <日>` → `daily/<日>/verdict.html`（12:30 / 18:45 自动）：逐场市场·研究原判·终判与证据，置顶「需要你裁决」。
- `daily/<日>/signals.md`；初判包 `uv run nutmeg judgment brief --day <日>`（足彩 `--issue <期>`，带机器初稿）。

## 2. 逐场研究（缺的、过期的才做）
- **默认**：`uv run nutmeg research run --day <日> --code <场次> [--concurrency N]`——无头 `claude -p`，系统提示＝分析员定义 + 研究 JSON 契约 + rubric r1 问题表；占当日 40 次预算；产 `research-<场次>.json` 并自动校验。之后 `uv run nutmeg research refresh --day <日>`：重建 Read、交本体、重写 signals。
- **补查 / 追问**（Jun 点名某腿、出了新消息）：主循环并行派 `jczq-match-analyst`（每场一个）。约束只在 agent 文件本体里，**不在派发提示里现场口传**；要改就改文件。足彩场次先 `uv run nutmeg zucai-premise-card --issue <期>`，把卡原样贴进提示（RUNBOOK B3a）。
- **结论先落对象再谈票**：`uv run nutmeg research override --day <日> --code <场次> --note … --items-json … --reason …`（或 `--market`）；禁止手改 `research-*.json`（RUNBOOK「信号留存」/ B5a）。只活在聊天里的结论，下一轮按 belief 重算时会被静默推翻。

## 3. Jun 出方案
- 竞彩：腿文件 + 过关方式；`uv run nutmeg jczq-combos --day <日>` 只给「同判断下 P 最高的形状」作参考（只枚举 ≥2 串）。
- 足彩：在机器初稿上改（`uv run nutmeg judgment draft --issue <期>`；处方忠实、只丢场不降档）。
- 每腿押模态、不押隔壁（总进球带别漏掉最可能的球数）；引擎时代的禁区（高赔串、胜平负押冷门、恰净胜 N 窄带）见 RULEBOOK「已退休」。

## 4. 审票
- 单张：`uv run nutmeg betslip preview --channel <jczq|renjiu|shengfucai> --placed-at <日> (--legs-file … --combo … | --faces … --issue <期>)`。
- 一组票一起审：`uv run nutmeg betslip preview-set --plan <计划.json>`——组内互相同死只有一起审才看得见。
- 输出：诊断（共享裸单、联合同死概率、对照处方/初稿）＋审票（⛔V1 期望回报率 <0.5、⛔V2 与已购票共享裸单、⚠️V3 倍投/重注）＋刹车/月度止损行。有 ⛔ 退出码 1：改票后再审；坚持原票也可登记（登记是事实，审票行随票入账）。
- 审计门 `decision-audit-legs` 2026-10-13 已删（判断类码自 09-27 起本就不拦截，RULEBOOK「〇」）；审票只看 `betslip preview` 的 V1/V2。

## 5. 定案与登记
- `uv run nutmeg betslip register --slip-id <号> --channel … --placed-at <日> …`；与初稿有偏离时带 `--deviation <理由类> --prediction "<一句赛后可核验>"`，理由在票内最早开球前写。
- **没入账＝没打**；截止前 30 / 10 分钟仍无登记会被提醒。

## 6. 复盘
- 次日 09:45 / 15:45 自动结算（`uv run nutmeg day run --job settle`）；足彩开奖后 `uv run nutmeg retro encode --issue <期> --prize-per-note <官方单注>`。
- 跟市场的判断只能用信息面理由否决（实名伤停 / 轮换 / 战意变化），不用价格或 EV 语言；复盘时按理由分层看改判得失（判决页「改判账」）。
