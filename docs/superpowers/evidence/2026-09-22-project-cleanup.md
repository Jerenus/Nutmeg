# 项目大清理 · 记录（2026-09-22）

前置：tag `v0.4.0`（`e371a40`）冻结了清理前的完整工作树。本文所有「已移除」项都可用
`git show v0.4.0:<path>` 取回，`git checkout v0.4.0 -- <path>` 复活。

原则：只删「主题系统已死」或「零引用」的东西；活代码的设计记录（spec）保留；
`.nutmeg-data/` 与未跟踪文件一律不碰（那是 Jun 的）。

## 1. 已移除（227 个跟踪文件）

| 区域 | 数量 | 内容 | 依据 |
| --- | ---: | --- | --- |
| `scripts/` | 67 | 2026-06/07 世界杯与 2026-07/08 期次专用的 dcfit / render / combos / retro 脚本；`jczq_{calibration,draw_analysis,softchalk_track}.py`（只读旧引擎 `tiered-plan-review.json`）；`render_decision_skeleton.py`；`plan_backfill_26129.py`（回填已执行） | 零引用（plist / RUNBOOK / pyproject / nutmeg / tests 全部 grep）；ruff 早已把 `scripts` 排除为归档 |
| `experiments/` | 13 | `exp-{b1,f1,f1b,f2,f3p,f4}*.py`（继任者是 `registry/F*.json` + `rsi_grading.py`）；7 个无人读的 `policy-*.json` | 零引用；`policy-top60-v1.json` 保留（F3 登记引用） |
| `nutmeg/` | 16 | `agents/prompts/`（6 文件 21 行，空 `__init__`）；`models/{vaep,xg}.py`、`data/statsbomb_open.py`（从未实现的 stub）；`data/european_odds.py`（为已删 generator 写的 no-op）；`core/{identity,quota}.py` + `tests/test_identity.py`（测试孤岛，活的 identity 在 `decision/identity.py`；`core/repositories.py` 保留，六处在用）；`interfaces/web/templates/jczq/`（4 个模板，5 月起无路由挂载） | 零导入者（逐模块 grep 点分路径与相对导入） |
| `docs/` | 122 | 切换前（2026-04/05/06）主题已死的 20 spec + 20 plan；`docs/architecture/`（24，v0 架构）；`docs/adr/`（3，Spec Kit 时代）；`docs/process/`；`superpowers/reliability-gates.md`；`superpowers/drafts/sop-trilogy/`（SOP 三件套的漂移影子，最危险的重复）；`wc-research*/`（3 处各 1 文件）；`evidence/m2–m6/*.png`（44 张截图，24MB = docs 体积 83%） | 死系统 / 零引用 / 重复 |
| `ops/` + `docs/ops/` | 10 | `ops/launchd/archive/`（6 个世界杯/tiered 时代 plist）；`zucai.{afternoon,revision}.plist`（被 `prep/prep-revision` 取代，未装载）；`docs/ops/retired-launchd/`（close/settle 的重复副本）；`docs/ops/*.plist`（副本） | plist 单一来源改为 `ops/launchd/` |
| 根目录 | 3 | `DESIGN.md`（指针）、`Nutmeg-DESIGN-v0.3.md`（2026-04 的 v0 设计）、`feature-list.json`（Spec Kit 清单） | 主题已死；README 已重写 |

保留但改写：`README.md`（原 430 行 v0 叙述 + 指向已删文件的链接 → 当前入口/目录/每日界面）；
三处提到 tiered/bold 引擎的 docstring（`services/jczq_results.py`、`services/jczq_apifootball_odds.py`、`data/fcom500.py`）改为现役措辞。

新增到 `ops/launchd/`（与 `~/Library/LaunchAgents` 已装载副本字节一致）：
`com.nutmeg.jczq.results-backfill.plist`、`com.nutmeg.zucai.f2-observe.plist`、
`com.nutmeg.zucai.prep-morning.plist`；`com.nutmeg.rsi.sweep.plist` 更新为已装载版本（多 `PATH` 环境变量）。
现在 `ops/launchd/` 十个 plist 里八个已装载且一致，`decision.close/settle` 两个未装载（close 的死因 09-14 已修，是否复启是 Jun 的门）。

## 2. 第二轮（Jun 2026-09-22 裁定：没用的文档都可以清，只维护可追踪与有明确功能关系的）

- 补上第一轮被分类器拦下的：7 篇旧引擎叙述文档 + 死系统图 + 原始粘贴；`.specify/`（261 文件）；17 个无人链接的 speckit-* 技能。
- **`docs/superpowers/plans/` 改为只放未完成的实施清单**：删 69 份已并入 main 或已有 evidence 的计划（07 月 15、08 月 22、09 月 32）。
  保留：`2026-08-12-l3-asymmetric-autonomy-roadmap.md`（路线图）、`2026-08-23-memory-ontology-sop-redesign.md`（CLAUDE/AGENTS 指针）、
  `2026-09-13-impact-magnitude-three-term.md`（状态未明）。README 已写明这条约定。
- 删两份「未采纳」提案 spec（07-07 实体层、08-12 Tie/流量/规则三层）；删两份已完成的一次性 runbook
  （`decision-shadow-run-runbook.md`、`ontology-kernel-v2-cutover-runbook.md`），CLAUDE.md / AGENTS.md 同步去掉指针。
- 根 `memory/` 是 Codex 会话笔记：加入 `.gitignore`，11 个误跟踪文件 `git rm --cached`（磁盘保留）。

## 3. 需要 Jun 裁决的（我没动）

| 项 | 现状 | 建议 |
| --- | --- | --- |
| 未跟踪文件 16 个 | `experiments/exp-{label-residuals,price-bands,strict-space}.py`、3 个 `prereg-*.json`、`scripts/render_zucai_26113/26116*.py`、`docs/sop/PROPOSAL-2026-09-13-intent-ontology.md`、`docs/superpowers/plans/2026-08-28-codex-dev-handoff.md` | `prereg-26126-F2-ledger.json` 是代码默认路径（`cli/rsi.py`、`rsi_migrate_preregs.py`），丢了 F2 工具断——要么提交，要么把默认路径改到 `.nutmeg-data/`；三个 exp 脚本的结论已进 evidence，可删；两个 render 脚本同 §1 一次性；两份文档看是否还要 |
| `experiments/corpus-v2.json`（2.6MB） | 跟踪且每天被闭环重建 | 跟踪的好处是 tag 能复现实验样本；代价是每次提交都 churn。保留现状或改 gitignore，二选一 |
| `.nutmeg-data/archive/`（210MB） | 6 个内核 db 快照 + `20260721-…-v2-freeze/`（97MB，含 zucai html 源的完整重复） | 数据不进 git，删除不可逆：保留最近两个 pre-schema 快照，其余移到仓外 |
| `.nutmeg-data/analytics/analytics.duckdb`（62MB，2026-08-02 后未写） | legacy `settings.analytics_db_path` 通道；活的是 `ontology/analytics.duckdb` | 确认无人读后移出 |
| `nutmeg/interfaces/cli/operations.py` 的 v0 命令 | `today-briefs / match-brief / daily-run / popular-matches / agent-status / tactical-visuals / event-tactical-models / fixture-information / analyze-match / agent-analyze-match / bot-dry-run`：EPL demo 时代的通道，背后是 `services/ agents/ analytics/` ≈ 1.4 万行 | 第二阶段：先做依赖图（`jczq_results`、`fcom500`、`api_football` 等被五动词共用，不能整包删），再拆 |
| `CLAUDE.md` vs `AGENTS.md` | CLAUDE.md 声称两者是同一份指令的两个副本，实际 AGENTS.md 多 40 行 OpenClaw 契约 | 把「必须同步」改为「共享 SOP 指针段必须同步」，或把 OpenClaw 段拆到 `docs/integrations/` |
| 活文档里的死引擎词汇 | `docs/sop/CONSTITUTION.md`、`docs/jczq-mixed-bet-judge-process.md`、`docs/decision-shadow-run-runbook.md`、`specs/2026-07-06-decision-ontology-design.md` 仍有 tiered/Poisson/worldcup 措辞 | 宪法是 Jun 的法条，我不改字；后三篇可做一次措辞清扫 |
| `docs/sop/RUNBOOK.md` 第 3 行 | 「launchd 的 am/close/settle 仍禁用，全部手动」已过时：am 每天 08:00 在跑 | 改一行 |
| `scripts/lineup_collector.py` | 09-14 提交的赛前首发采集器，零引用 | 要么接进 `rsi loop`（真外生特征），要么删 |
| `com.nutmeg.jczq.results-backfill` | 已装载但最近一次退出码 2（`RESULTS_STALE`） | 与清理无关，但每日界面必须把它亮出来 |

## 4. 验证

- `uv run python -m compileall -q nutmeg scripts experiments` 通过。
- `uv run ruff check .` 只剩 3 条，全在 Jun 未跟踪的 `exp-price-bands.py` / `exp-strict-space.py`。
- 全量 `uv run pytest` 结果见提交信息。

## 5. 第三轮（Jun 2026-09-23 裁定：不在未来规划中的都退役；不需要的备份删掉；最终版本进 git）

- **进 git**：另一会话未提交的 intake（④只数情境旗、先例查无正则）、别名提案、`zucai_loop` 上下文特征、`attempts.log`、三份 prereg 与 F2 台账（代码默认路径）——`a4e…` 之前的 `chore: land pending session work`。
- **删未跟踪一次性文件 7 个**（3 个 exp 脚本、2 个 render 脚本、intent-ontology 提案、codex 交接稿）。
- **运行数据备份**：`.nutmeg-data` 501MB → 328MB。删 0721 只读冻结（97MB，含 zucai html 源全套重复）、pre-schema14、m2-legacy、pre-ligue1、v28/pre-v15/pre-v16 内核快照、launchd 旧备份、回放 v2–v4、两个 `.bak`、0 字节 `ontology.sqlite`。保留最近两个内核快照（09-19 pre-v34、09-20 pre-f9）与回放 v5。
- **退役 v0 EPL 命令通道**（c8a56ff，≈9,900 行）：`operations.py`/`core.py` 的 17 条命令、只服务它们的 services/domain/storage/process 模块、Spec Kit doctor 桥、旧 OpenClaw 命令路由器与其手册。`make init`/`doctor` 改用 `nutmeg ontology status`。保留：Telegram bot 的 match-brief 路径、`nutmeg odds`、所有活泳道导入的模块。
- **退役 decision.close/settle 定时链**（75bd5d0）：两个 plist、调度脚本的 close/settle 分支与 11 个测试、`reliability` 的阶段枚举；`scripts/lineup_collector.py` 零引用删除。
- **文档清扫**（c4dedd9）：宪法、判读流程、决策本体设计 spec 不再出现旧引擎名；CLAUDE.md 的「两份同步」改为「共享 SOP 指针段同步」。
- **赛果回填误报**（8550c66）：当天未踢完 → `RESULTS_PENDING` 退出 0；昨天及更早未齐才 `RESULTS_STALE` 退出 2。

### 5.1 已裁：方案 A（2026-09-23）

Jun 选 A：8788 应用连同 product 级联退役（1189f48，169 文件 ≈5.97 万行）；Discovery 输入改接决策泳道三份文件（`specs/2026-09-23-discovery-day-source-design.md`，证据 `evidence/2026-09-23-discovery-day-source.md`）。`nutmeg odds` 与 Telegram bot 的 v0 分析栈未裁，保留。

### 5.2 原冲突记录

8788 应用（`nutmeg app` + `nutmeg/product/operator_*` ≈ 27,500 行 + 30,000 行测试）**与 Discovery 试点的 operator_v2 输入是同一条写入链**：
生成请求 / 候选集只由网页端 `POST /api/v2/operator` 与其 worker 写入，仓里没有任何 CLI 生产者；官方在售清单 manifest 也没有生产者；生产库这些表至今 0 行。
「退役 8788」与「Discovery 用 active 输入」不能同时成立，见本轮汇报。

### 5.3 第四轮（2026-09-23，Jun：「1，2，3，4 现在都能开始了」）

- **`rsi fulfill` / `rsi schedule` 同日幂等修复**（3fedd5e）：`rsi_observations.superseded_by`（迁移 45）；同日同场第二次兑现改为「取代」而非撞键；fulfil 键含 artifact hash16，schedule 键含目标指纹——同输入重跑仍是 no-op，输入变了才是新动作。
- **operator_v2 残余批次 1**（5dac531）：`product/jczq_{board_workflow,compatibility,cutover,replay,replay_adjudication,replay_inputs,replay_workflow}`、`operator_artifacts`、`operator_legacy_import` 与 10 个测试文件；`decision-close` 不再有 v2 路径（`run_decision_close_v2` 删除）；`workflow jczq-*` 命令退役；RUNBOOK A1b/A3/A6 改写。
- **`nutmeg odds` 命令组与 v0 bot 分析栈**（82a39b7）：`cli/odds.py`、`agents/{router,workflow}`、`services/{analysis,evals,players}`、`domain/{analysis,evals,players}`、`storage/prediction_repository`、`models/scoring`、`evals/` 与 7 个测试文件；bot `/brief` 回「已退役」。保留 snapshot/odds/value 链（足彩 value bridge 用 `ValueBoardService`）。
- 三批合并树全量 3040 通过；每批按显式路径分别提交。
- 顺带发现两处，留 Jun 裁：
  - `services/jczq_value_wiring.build_jczq_value_bridge` 只剩测试引用（CLI 只用 zucai wiring；`zucai_value_wiring` 还从它导 `season_for_date`）——可把 `season_for_date` 挪到 zucai wiring 后退役整个模块。
  - **CLV 轴的收盘快照入库已死**：内核 `market_snapshots` 最后一条 `closing` 是 2026-08-23（`read_time` 到今天 4,143 条）。唯一入库函数 `ontology_adapter._capture_closing_v2` 找的是 `bold_odds_closing.json`，而每日目录里实际落的是 `closing_odds.json`，且 v2 close 路径已删——函数只被 `tests/decision/test_closing_report_adapter.py` 养着。`analytics/{forecast,factor}_projection` 读 `closing_fair` 算 CLV，因此 08-23 后 CLV 恒空。选项：(a) `day.settle` 09:45 顺手把前一日 `closing_odds.json` 按 `snapshot_kind="closing"` 入库（改文件名即可复活）；(b) 接受 CLV 只在 titan007 终盘语料里算，删掉该函数与测试。
