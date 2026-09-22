# Nutmeg · 过人

中国体彩竞彩足球（JCZQ）与传统足彩（胜负彩/任九）的判断系统：五动词决策本体 +
RSI 实验层（判据自证伪）+ Discovery Harness（结构层回放锦标赛）。

**判断永不入脚本，判据必须入代码。** 出票前的硬门是 `nutmeg decision-audit-legs`。

## 入口

| 读者 | 先读 |
| --- | --- |
| Claude Code | `CLAUDE.md` → `docs/sop/{CONSTITUTION,RUNBOOK,RULEBOOK}.md` |
| Codex / OpenClaw | `AGENTS.md`（同一套 SOP 指针 + OpenClaw 会话契约） |
| 实体知识 | `docs/research/INDEX.md`；画像在 store 的 `profile_notes` |
| 工程背景 | `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md` |
| 内核运维 | `docs/ontology-kernel-operations.md` |
| 定时数据流 | `docs/ops/2026-09-20-scheduled-dataflows.md`；plist 单一来源 `ops/launchd/` |

## 每日界面

```bash
uv run nutmeg ops-status                 # launchd / OpenClaw / 待办，一屏
uv run nutmeg decision-web               # 判读工作台 http://127.0.0.1:8787（含 /observe 观察台、/betslips）
uv run nutmeg rsi status                 # RSI 实验唯一事实源
uv run nutmeg rsi loop                   # 每日闭环（launchd 10:45 已自动跑）→ .nutmeg-data/analytics/rsi-loop/latest.md
```

`uv run nutmeg app`（8788）是九工作区的本体工作台，仍处 `legacy_read_only`，
手册见 `docs/application-operator-manual.md`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `nutmeg/` | 包：`decision/`（五动词、判读、审计门、RSI）、`ontology/`（SQLite 内核 + typed Actions）、`discovery/`（Harness）、`product/`（工作台）、`interfaces/`（CLI / web / bot）、`data/` `services/`（采集） |
| `experiments/` | 语料 v2、因子注册表 `factors.json`、实验登记 `registry/`、Harness 契约 `discovery/`、`attempts.log` |
| `scripts/` | 定时器与采集器（`openclaw/`、结果回填、终盘采集、F2 观察仪、足彩 discovery loop）；ruff 不作质量门 |
| `ops/launchd/` | 全部 plist；装载是 Jun 的行权门 |
| `tests/` | `uv run pytest`（pre-commit 会跑 product 子集） |
| `docs/sop/` | 宪法 / 执行清单 / 规则注册表 |
| `docs/superpowers/` | `specs/`（设计，描述现役系统）、`plans/`（**只放未完成**的实施清单，完成后删除、由 evidence 承接）、`evidence/`（验收证据） |
| `.nutmeg-data/` | 运行数据（gitignored）：`scoreboard.json` 记分牌单一事实源、`jczq/daily/<日>/`、`zucai/`、`ontology/`、`analytics/` |

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
