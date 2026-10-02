# Nutmeg · 过人

中国体彩竞彩足球（JCZQ）与传统足彩（胜负彩/任九）的判断与账务系统：决策本体内核 +
研究判断层（rubric r1 类型化问题表）+ RSI 实验层（判据自证伪）+ Discovery Harness（Dream 夜录 · 回放 gym）。

**定位（2026-10-01）**：机器＝风控官（审票否决已知坏结构）+ 账房 + 实验员 + 研究员，人＝下注者。
竞彩机器出初判不出票；足彩机器出初稿；Jun 出方案 → `betslip preview` 审票 → 下单 → `betslip register`。
**判断永不入脚本，判据必须入代码。** 结构总图：`docs/ARCHITECTURE.md`。

## 入口

| 读者 | 先读 |
| --- | --- |
| 结构总图（现役） | `docs/ARCHITECTURE.md`：总图、每日时序、判断层、出票审票、RSI、Dream、数据对象、全量分析过程、工程流程、文档地图 |
| Claude Code | `CLAUDE.md` → `docs/sop/{CONSTITUTION,RUNBOOK,RULEBOOK}.md` |
| Codex / OpenClaw | `AGENTS.md`（同一套 SOP 指针 + OpenClaw 会话契约） |
| 实体知识 | `docs/research/INDEX.md`；画像在 store 的 `profile_notes` |
| 工程背景（历史设计） | `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`（M1–M6；现役结构以 `docs/ARCHITECTURE.md` 为准） |
| 内核运维 | `docs/ontology-kernel-operations.md` |
| 定时数据流 | `docs/ops/2026-09-20-scheduled-dataflows.md`（2026-10-02 更新：launchd 14 个 + OpenClaw 3 个）；plist 单一来源 `ops/launchd/` |

## 每日界面

```bash
uv run nutmeg ops-status                              # launchd / OpenClaw / 待办，一屏
uv run nutmeg decision-web                            # 工作台 http://127.0.0.1:8787（/day、/runs/<日>、/verdict/<日>、/betslips、/observe）
uv run nutmeg judgment brief --day <日>               # 竞彩初判包（不出票）
uv run nutmeg judgment brief --issue <期> --write     # 足彩初判包 + 机器初稿（单跑初稿：judgment draft --issue）
uv run nutmeg betslip preview --channel … [--issue …] # 审票：V1/V2 否决、V3 警告、对照初稿、刹车行
uv run nutmeg betslip register … --deviation … --prediction …   # 登记实票（偏离初稿带理由与预测）
uv run nutmeg research override --code … --items-json … --reason …  # 改判落到 rubric 项
uv run nutmeg rsi status                              # RSI 实验唯一事实源
uv run nutmeg rubric report --day <日>                # 两读逐项一致率与 κ
uv run nutmeg account month [--month YYYY-MM]         # 账房：净值 vs 空仓、止损、偏离按理由
```

每日时序（14 个 launchd 定时器 + 3 个 OpenClaw 任务）见 `docs/ARCHITECTURE.md` §2。

## 目录

| 路径 | 内容 |
| --- | --- |
| `nutmeg/` | 包：`decision/`（研究与 rubric、Read、审票、账房、日运行器、RSI 闭环）、`ontology/`（SQLite 内核 schema 47 + typed Actions）、`discovery/`（Dream / Harness）、`gym/`（回放环境）、`product/`（repository + runtime）、`interfaces/`（CLI / web / bot）、`data/` `services/`（采集） |
| `experiments/` | 语料 v2、因子注册表 `factors.json`（含 rubric 逐项因子）、实验登记 `registry/`、Harness 契约 `discovery/`、`attempts.log`（10:45 闭环自动提交） |
| `scripts/` | 定时器与采集器（`openclaw/`、结果回填、终盘采集、奖金模型、rubric 历史重打分、足彩 discovery loop；F2 观察仪 2026-10-02 退役，脚本留档） |
| `ops/launchd/` | 全部 plist（14 个）；装载是 Jun 的行权门 |
| `tests/` | `uv run pytest`（pre-commit 会跑 product 子集） |
| `docs/sop/` | 宪法 / 执行清单 / 规则注册表 |
| `docs/superpowers/` | `specs/`（设计，描述现役系统）、`plans/`（**只放未完成**的实施清单，完成后删除、由 evidence 承接）、`evidence/`（验收证据） |
| `.nutmeg-data/` | 运行数据（gitignored）：`scoreboard.json` 记分牌单一事实源、`betslips.jsonl` 登记簿、`jczq/daily/<日>/`、`zucai/`、`daily/<日>/`、`ontology/`、`analytics/`（详见 `docs/ARCHITECTURE.md` §7） |

## 开发

```bash
make init        # uv sync + doctor
make verify      # ruff + compileall + pytest
```

提交只用显式路径 `git add <path>`，绝不 `-A/-u`。

## 历史

2026-07-07 M2 切换删除了旧 tiered/bold/Poisson/worldcup 引擎；切换前的设计文档、
一次性脚本与 Spec Kit 已于 2026-09-22 清理出工作树（见
`docs/superpowers/evidence/2026-09-22-project-cleanup.md`），完整内容在 tag `v0.4.0`。
