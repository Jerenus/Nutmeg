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

## 2a. 临场复核（2026-11-16，11-15 竞彩板 11 场复盘落库）
- **先数全板**：按竞彩编号 / `businessDate` 数，次日凌晨开球的场同样算当天的板。11-15 主循环把 11 场说成 7 场，四场深研晚了两小时。
- **体彩价先看更新时间再比价**：`had/hhad.updateDate·updateTime` 早于当日开售、或开售后没动过的，是旧价，不拿来和国际盘算每元回报或价差。11-15 两次出现「旧价对新盘」的假价差（09:30 全板、14:05 周日009）。
- **首发出来之前只写触发条件，不动把握**：按场写「看谁首发 / 若相反怎么改」，名单到了逐场核对，再用 `research override --reason new_official_info` 把事实落到项。11-15 核过首发的 7 场里 5 场的研究实名前提被推翻；停售前看不到首发的场，伤停叙事只当背景。
- **首发来源**（按出名单的早晚）：欧足联赛事 `https://match.uefa.com/v5/matches?fromDate=<日>&toDate=<日>&competitionId=2014` 取 id → `/v5/matches/<id>/lineups`（开球前约 45 分钟，同接口可取上一轮首发做轮换对照）；J 联赛官方页 `/match/<赛事>/<年>/<MMDDnn>/live/`（约 2 小时前）；API-Football（`lineup_watch.default_fetchers()`）最慢，只兜底，且有每日额度，别轮询。
- **盘中刷新盘口不写正式目录**：`nutmeg.decision.fetch.fetch_day(<日>, <临时目录>)` 只抓取落盘；`decision-am` 会用当下在售场次覆盖当日 `sporttery_markets.json`。
- **到 1 的腿只展示**：国际 fair × 体彩赔率 ≥1 的腿 11-15 出现 8 条、全没中；主让 1 让负格回测区间含 0、主受让让胜格显著为负（`jczq_hhad` 回测，2026-11-06），不作下注理由。

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
