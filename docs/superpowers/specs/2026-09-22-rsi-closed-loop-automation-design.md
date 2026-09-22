# RSI 闭环自动化 v1：人之前的每一步每天自动转

日期：2026-09-22
状态：已实现（`nutmeg/decision/rsi_loop.py`，`nutmeg rsi loop`），定时器待 Jun 装载
上位：`docs/sop/CONSTITUTION.md`（verdict 只系统、deploy 只人）、`2026-09-18-rsi-experiment-persistence-design.md`、`2026-09-20-experiment-measurement-layer-design.md` §13

## 1. 一句话

把 2026-09-22 复核时手动转过的那半圈（采样 → 语料 → 测量 → 提案）和前瞻链断掉的那一段（结账 → 判决）接成一条每天自动跑的链；人只剩下看一份报告、做三种决定（登记、裁分层、部署）。

## 2. 不变量（先于实现冻结）

| # | 不变量 | 落点 |
| --- | --- | --- |
| I1 | 运行器不写权重、不改 RULEBOOK / `CODE_SHORT` / scoreboard、不登记实验、不部署 | `rsi_loop.py` 只发子进程；测试断言命令里没有 `rsi deploy` / `rsi register` |
| I2 | 每一步是子进程，失败只影响该步并进报告；退出码非零仅当有步骤失败 | `_run_step` / `run_loop` |
| I3 | 「未到期」「没有前瞻 grade」是预期状态，记为 `not_due`，不是失败 | `NOT_DUE_MARKERS` |
| I4 | 同一天已有报告则整圈跳过；`--force` 才重跑，定时器重复触发无副作用 | `run_loop` 的日期标记 |
| I5 | 前瞻结账只读登记原件的 `window`，永不回补窗前样本（T12） | `grade_f3/f5/f9_prospective` 的窗过滤 |
| I6 | 结账用系统身份；判决由 `record_verdict` 按冻结判据算；两者都不经人 | `rsi grade` / `rsi verdict` 既有 Action |
| I7 | 每条结论经 `experiments/attempts.py:log_attempt` 进多重比较记账 | propose / hyp 的 `--log` |
| I8 | 报告只列事实与提案，人类动作单独成清单 | `LoopReport.human_actions` |

## 3. 每日链（`nutmeg rsi loop`）

| 步 | 命令 | 写什么 | 失败语义 |
| --- | --- | --- | --- |
| closing_backfill | `titan007_closing_backfill.py`（竞彩板 + `--zucai`） | `daily/<日>/closing_odds.json`、`<期>-closing-odds.json`，幂等 | 网络失败只丢当天增量 |
| corpus_build | `corpus_build.py --out experiments/corpus-v2.json` | 语料 v2 | 失败则后续步骤用旧语料 |
| grade_prospective | `rsi grade --exp F2/F3/F4/F5/F9 --mode prospective` | `rsi_grades` 追加行 | 单个实验失败不影响其余 |
| verdict_due | `rsi verdict --exp …` | 到期才写 `rsi_verdicts` | 未到期 = `not_due` |
| factor_propose | `rsi weights propose --all --log` | 只 stdout + attempts.log | 注册表字节校验不变 |
| hyp | `zucai_loop.py hyp --corpus v2 --cut <最新期> --log` | attempts.log | — |
| team_strength | `team_strength.py build` | `.nutmeg-data/analytics/team_strength.json` | — |
| scoreboard | `scoreboard_parse.py --out experiments/scoreboard-tallies.json` | 结构化计数 | — |
| report | 运行器自身 | `.nutmeg-data/analytics/rsi-loop/<日>.json|.md`、`latest.md` | — |

建议时点 10:45（08:00 decision-am、09:30 赛果回填之后）。plist 在 `ops/launchd/com.nutmeg.rsi.loop.plist`；装载是 Jun 的行权门，运行器不自装。

## 4. 前瞻结账适配器（本次新接 F3 / F5 / F9）

| 实验 | 样本 | 指标 | 层 | 备注 |
| --- | --- | --- | --- | --- |
| F3 policy-top60 | 语料足彩行，issue ∈ [26125, 26136]，top1 ≥ 60% | 模态面残差 pp，zucai | structural / deploy_eligible | 首算 n=23，+8.6pp CI[−6.7,+21.6]；n_min 120 |
| F5a 价格带 | 语料两泳道，date ≥ 2026-09-19，gap12 ∈ [10,20)pp | 模态面残差 pp，pooled（另可按泳道） | structural / candidate | 首算 n=23，+7.5pp；n_min 120 |
| F9 判读增量 | 语料两泳道，date ≥ 2026-09-20，belief ≠ prior | 市场 Brier − 判读 Brier，pp | judgment / observation | 首算 n=0：窗内没有拨动 |
| F2 | 既有 ledger 适配器 | — | — | 不变 |
| F4 | 既有资金方案适配器 | — | — | 不变 |
| F8 / R0 / F1c | 未接 | — | — | F8 的判据要真实票面上的「两证」决策；R0 要板面总数；F1c 要书目分布快照。各自另立任务 |

窗前样本一律不入：这是 T12 的硬线，也是 I5。

## 5. 人还要做什么（唯一三种动作）

1. **裁分层**：`experiments/factors.json` 的 `layer_uncertain_for_jun` 三处。
2. **登记**：报告里 `propose_change` 的因子、`hyp` 里过线的假设，人写 registry 原件后 `rsi register --by <人>`。
3. **部署**：`rsi verdict` 出 survived 且实验是 structural / deploy_eligible 时，`rsi deploy --by <人> --rule <C 码>`，然后手改 RULEBOOK / 码表 / scoreboard。

运行器每天把这三类候选放进 `human_actions`；没有候选时明写"无"。

## 6. 验收

| # | 检验 | 结果（2026-09-22） |
| --- | --- | --- |
| A1 | `rsi loop --dry-run` 打印 8 步全部命令，均以 `uv run` 开头 | 通过（`tests/decision/test_rsi_loop.py`） |
| A2 | 假运行器下：跳过、失败、未到期三种状态各自正确分类，报告 JSON/MD 落盘，人类清单含提案与失败步骤 | 通过 |
| A3 | 同日重复调用不重跑；`--force` 重跑 | 通过 |
| A4 | 运行器发出的命令里没有 `rsi deploy` / `rsi register` | 通过 |
| A5 | 三个适配器：窗过滤、泳道过滤、阈值、空样本、哈希稳定 | 通过（`tests/decision/test_rsi_grading_prospective.py`） |
| A6 | 真跑一圈 | 见同日 evidence 与 `latest.md` |

## 7. 不做的事

- 不自动 `turn`（候选策略变异）：候选生成仍是人发起的 `zucai_loop turn`，因为它改的是影子策略权重，即使不进实盘也应由人触发。
- 不自动通知：报告落盘即止；接 Telegram 是下一步，且只发摘要不发数字建议。
- 不装载 launchd：四行权门之一。
