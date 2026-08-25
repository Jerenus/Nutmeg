# CONSTITUTION — Nutmeg 决策宪法（极少变更；变更须用户批准并同步 AGENTS 副本）

> 三件套：本文（原则）→ `RUNBOOK.md`（怎么执行）→ `RULEBOOK.md`（规则注册表）。
> 读序：做事读 RUNBOOK，构票查 RULEBOOK，冲突时本文裁决。

## 1. 唯一路径

**决策本体五动词**：sense → read → express → reconcile → calibrate。
2026-07-07 M2 切换后旧引擎（tiered/bold/Poisson/worldcup）全灭，一律忽略其规则叙事。
触发短语（任一即执行 RUNBOOK 对应泳道）："今天的 jczq 方案 / 今天竞彩怎么打 / 出今天的票 / today's bets"→竞彩泳道；"胜负彩 / 任九 / 26xxx期"→足彩泳道。

## 2. 判断的宪法（字典序，低序永不上溯）

1. **第一序·事实定面**：每个面只问机制"活/死/从未存在"。机制活→盖住或丢整场。价格只作对抗性质询，不作裁决。
2. **第二序·P 定结构**：预算由纪律外生给定，帽内最大化 P(全对)。**EV/每元效率禁入决策层**。
3. **第三序·奖池破平局**：奖池逻辑只在 P 不受影响处起作用（全包给 top1 最低场）。

推论：市场锚定（无命名理由=跟市场）；命名因子偏移是唯一可能的 edge，受 CLV 事前 + Brier 事后检验；**空仓永远合法**；高赔=高方差小额。

## 3. 两条元原则（本项目的全部方法论）

- **判断永不入脚本**：脚本只做取数、采集、确定性算术三件事；判读由主循环实时推理。
- **判据必须入代码**：散文规则挡不住"第五个更好的理由"（四票之死→audit 诞生；两次先例失效→C7 诞生）。凡是没被对象化的知识，都不参与执行。

## 4. 注金与刹车

竞彩日 ≤¥400；足彩每期 ≤¥400 复式基准、两票合计 ≤¥1,600；日总帽 ≤¥2,000。
连续两期全灭 → 次期减半或强制空仓复盘日（用户可显式行权覆盖，覆盖入 Adjudication 账）。
**没入账 = 没打**（ledger writeback 原则）。

## 5. 数据纪律

edge/概率/CLV/Brier 数字必须来自决策 store 或本体函数（devig/dcfit/scoring），**禁嘴算**。
赛果三源制：okooo / API-Football / 官方页；500 live 页红格=半场比分，仅作盘口源。
记分牌单一事实源 = `.nutmeg-data/scoreboard.json`；复盘只改那里。

## 6. 裁决协议（人性工程）

- 用户点名某腿 → 单独重审该腿证据，禁用组合 P 一票否决（r条4）。
- 分歧且无新证据 → 处方优先；用户否决合法但须附一行 evidence_rejected，入 Adjudication 账。
- 深研 agent（jczq-match-analyst）反偏置约束改文件本体，禁止现场口传。

## 7. 知识层指针

- 判读规则全集：`RULEBOOK.md`（条文+状态+战绩+出生事故）
- 实体画像：store League/Team `profile_notes`（`nutmeg decision-profile`），不靠 chat 记忆
- 研究底座：`docs/research/INDEX.md`（权威序与取代规则）
- 深研流程：`docs/jczq-mixed-bet-judge-process.md`（七阶段）
