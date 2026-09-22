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

## 2. 分类器拒绝、留给 Jun 一行命令的

自动模式分类器把下面几组 `git rm` 判为「不可逆本地破坏」（其实都是跟踪文件，可从 git 取回）。
它们同样满足零引用，命令原样可跑：

```bash
# 旧引擎叙述文档 7 篇 + 一张 563KB 死系统图 + 一份原始粘贴
git rm docs/superpowers/reliability-gates.md docs/wc-research-netherlands-sweden-2026-06-20.md \
  docs/jczq-decision-chain-critique.md docs/jczq-decision-framework.md \
  docs/jczq-decision-skeleton.md docs/jczq-decision-skeleton.png docs/jczq-refactor-roadmap.md \
  docs/integrations/openclaw-botfather-commands.txt
# Spec Kit（2026-04/05，261 文件 1.4MB）与 17 个无人链接的 speckit-* 技能
git rm -r .specify .agents/skills/speckit-*
```

`.claude/skills`、根 `skills/`、`.kiro/skills`、`skills-lock.json` 都只链接 9 个通用开发技能，不含 speckit。

## 3. 需要 Jun 裁决的（我没动）

| 项 | 现状 | 建议 |
| --- | --- | --- |
| 根 `memory/`（22 文件） | 11 个 4–7 月的已跟踪，11 个 9 月的未跟踪，不在 `.gitignore` | 它是 Codex 的会话笔记：加 `memory/` 到 `.gitignore` 并 `git rm --cached memory/*.md`，或全部跟踪；二选一 |
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
