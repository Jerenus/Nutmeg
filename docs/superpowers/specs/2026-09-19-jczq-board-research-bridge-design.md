# 竞彩全板深研桥 · 设计

日期：2026-09-19 ｜ 状态：用户裁定 Q1→A；本文为定稿待审 ｜ 后续：writing-plans
依赖：RSI 层（已落地）、专项 spec `2026-09-19-zucai-structure-lane-design.md`（`face_status` 规则复用）

## 0. 一句话

让竞彩当日板的**每一场**在没有聊天窗口的情况下也能得到结构化深研与判读，成为 RSI 层的合法样本（U9/U10）；
研到哪一层如实记 `judgment_tier`；**研不到的场也必须有判断**——「跟市场」是宪法默认的判断，不是判断的缺席（R2）。

## 1. 出生事故

- corpus v2 里竞彩 532 行**只有价格没有标签**——竞彩判读只以散文存在（`decision-report-v2-<day>.md`、`nutmeg-handoff.json`），没有结构化 legs；判读层实验一行也用不上。
- `jczq-match-analyst` 是 Claude Code 子代理（WebSearch/WebFetch，opus），**只能在聊天会话里派**；U10「每场都深研」在「不开聊天窗口」的目标下没有执行体。
- research-intake 只认 `<期>-research-m<场号>.json`；竞彩板没有期号，只有内核 `match_id` 与板面代码（`周五001`）。

## 2. 用户裁定

| # | 裁定 | 来源 |
|---|---|---|
| U9 | 场 × 渠道为总体，竞彩全板都是样本 | RSI spec |
| U10 | 每场都深研；`judgment_tier` 如实记实际深度 | RSI spec |
| R1 | **全板每场 headless 深研**：每场一个 `claude -p` 进程（订阅、开 WebSearch/WebFetch、限并发、按开球排队）；每日研究预算为常量，做不完的场如实记 `price_only` | Q1 → A |

## 3. 对象与文件

- **`face_status.basis ∈ {researched, default}`（R3）**：`researched` = 有研究产物并通过 intake；`default` = 没研究、按「字段缺失 = alive」兜底。
  ⛔两者字段此前完全一样，F6 统计「T3 必全包」时会把「研究过、机制上杀不掉任何面」与「压根没看」混成一类，样本被污染。
  实验按 `basis` 分层，不许合并。
- **板面 legs-base**：`.nutmeg-data/jczq/daily/<day>/jczq-legs-base.json`，键 = 板面代码（`周五001`），每场：`match_id`（内核）、`name`、`competition`、`kickoff_bj`、`fair`（bold_odds 去水）、`hhad_line`、`judgment_tier ∈ {price_only, deep_research}`（本桥不产 `light_read`——研究要么通过 intake 要么没有，不造中间态；但**没研究 ≠ 没判断**，见 R2：price_only 的场出「跟市场」Read）、研究成功后再加 `face_status`（复用专项的 `attach_face_status`）与 intake 回填的标签。
- **研究产物**：`.nutmeg-data/jczq/daily/<day>/research-<code>.json`，schema 与足彩研究 JSON 完全一致（`name / summary / confidence / anchor_integrity / hole_location / license_questions / death_three_proofs / directional_flags / nondirectional_flags / crash_markers / precedents / schedule / market_snapshot`），intake 用同一套校验。
- **每场都出 Read（2026-09-19 用户裁定 R2，最重要的一条）**：`jczq-build-reads --day` 为**板上每一场**产一条 Read，不论研没研到。
  - 研到的场：`judge = "ai:jczq-analyst"`、状态 **draft**、`belief` 来自 `face_status`（活面按 fair 归一）、`judgment_tier = deep_research`；工作台既有 `approve-read / reject-read` 是人的门。
  - 没研到的场（预算/开球/拒收）：`judge = "market-anchor"`、状态 **draft**、`belief = prior`（跟市场）、`confidence = 1`、`judgment_tier = price_only`。
  - ⛔**「跟市场」是判断，不是判断的缺席**——宪法 §2 推论明文：「市场锚定（无命名理由＝跟市场）」。它是一句可被 Brier 评分的可证伪陈述。
  - **出生事故 2026-09-19**：首次真跑后板上 26 场只有 1 场有 Read，25 场被预算挡掉的比赛**一条判断都没有**，对判读层实验永远零贡献——U9 说「场 × 渠道为总体」，实际入样 1/26。
    判断永远存在，变的是**强度**；强度决定结构（能不能收窄），不决定要不要判。实验要的是全样本。
  - 样本行带 `approved` 布尔；实验登记时可声明 `require_approved` 与 `min_tier` 做分层。
- **覆盖率实验 R0**（observation / judgment 层 / population=jczq / min_tier=price_only）：唯一目的是让「每场深研」成为 **duty**——`scope=match, deadline_rule=match_kickoff, instrument=["uv","run","nutmeg","research","run","--day","{day}","--code","{code}"]`。研不到的场自然成 gap，覆盖率有账。

## 4. headless 深研运行器

`nutmeg research run --day <day> [--code <code>] [--budget N] [--concurrency 2]`
1. 读板面 legs-base；按 `kickoff_bj` 升序排队；跳过已有研究产物的场（幂等）。
2. 每场：`claude -p --system-prompt <agent 正文 + JSON 输出契约> --allowedTools "WebSearch,WebFetch" --max-turns 12 --output-format json`，stdin = 比赛简报（对阵 / 赛事 / 开球 / fair / 让球线 / 市场位移 / 来自内核画像的 `profile_notes`）。cwd 为空临时目录（不灌仓库上下文）。
3. 输出严格 JSON；解析失败或 intake 校验 ERROR → 产物写到 `research-<code>.rejected.json`，该场仍 `price_only`，不重试超过 1 次。
4. **预算常量** `RESEARCH_DAILY_BUDGET = 40`（模块常量，改动走 `rsi deploy`）；超出的场记 `price_only` 并在报告里列出「因预算未研」。
5. 运行报告 `research-run-<day>.json`：每场 `{code, status: done|rejected|skipped_budget|skipped_past_kickoff, seconds, attempts}`；同时对每场调 `rsi fulfill --exp R0 --match <match_id>`。
6. 泄漏纪律：开球时刻之后不再启动该场研究（`skipped_past_kickoff`），已启动的完成后按 `captured_at` 判 prospective。

## 5. 命令面与接线

| 步 | 命令 | 产物 |
|---|---|---|
| A1 备料后 | `research board --day` | `jczq-legs-base.json`（price_only） |
| A3 深研 | `research run --day` | `research-<code>.json` + 运行报告 + R0 观察 |
| A3b 入库 | `research intake --day [--write]` | legs-base 回填标签 + `face_status`（复用 `zucai-research-intake` 的每场校验，键改 code） |
| A4 落 Read | `jczq-build-reads --day` → `decision-read --reads-file` | 内核草稿 Read（ai:jczq-analyst） |
| 工作台 | 既有 approve/reject | `approved` |
| 备料链 | `decision-am` 成功后自动 `research board` + `rsi schedule`（per-match duties） | — |

权限：草稿 Read 的 actor 为 `ai_analyst`；`approve-read` 仍只许 `judge_operator`。运行器本身不需要 Action（它写文件，落库经既有 decision-read）。

## 6. 成本与保险丝

- 每场一次带联网检索的 opus 调用；实测足彩 14 场约 15–25 分钟（并发 2）。28–50 场/天 ≈ 30–60 分钟，走订阅额度。
- 预算常量 + 按开球排队 + 幂等跳过 = 三道保险丝；任何一道触发都**如实记录**，不降级成假判读。
- 研究进程失败永不让备料链失败（与 `rsi_wiring` 同样的「只留痕不抛」）。

## 7. 测试

- 运行器：假 `claude` 可执行（脚本）→ 幂等跳过已研场；预算 N=2 时第 3 场 `skipped_budget`；开球已过 `skipped_past_kickoff`；非法 JSON → `.rejected.json` 且 legs 仍 `price_only`；每场调用 `rsi fulfill` 的 argv 正确。
- intake by code：同一套 ERROR（confidence 缺失、三证不齐宣告死亡）在 code 键上生效；成功后 `face_status` 存在且 `faces` 派生。
- build-reads（R2）：**板上每场都有且只有一条 Read**；研到的 `judge == "ai:jczq-analyst"` 且 `judgment_tier == "deep_research"`；没研到的 `judge == "market-anchor"`、`belief == prior`、`confidence == 1`、`judgment_tier == "price_only"`；两者 `status` 均为 draft。
- basis 分层（R3）：研究通过的 leg `face_status[*].basis == "researched"`；没研究的 leg 若有 face_status 则为 `"default"`；两者不得在同一实验格里合并。
- R0 duty：`rsi schedule --day` 为板上每场生成 `duty_instance(match_id)`；未研的场过开球后成 gap。

## 8. 出口条件

某一天 `decision-am` 之后无人操作，`research run --day` 跑完：板上 ≥ 预算内每场都有 `research-<code>.json` 或明确的跳过原因；`rsi status` 里 R0 显示当天 observation 与 gaps；工作台里**板上每一场**都有一条草稿 Read 等待 approve（研到的 `ai:jczq-analyst`、没研到的 `market-anchor`）；`reads.json` 条数 == 板面场数；corpus v2 重建后竞彩带标签行数从 84 显著上升。
