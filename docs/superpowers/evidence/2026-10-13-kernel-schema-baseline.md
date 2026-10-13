# 2026-10-13 内核 schema 基线重排（迁移链 47→1，删 130 张空表）

> 裁定：Jun 2026-10-13 「清理删除。」——推翻 2026-10-03 §5「迁移链不压基线」。
> 执行：Claude（本会话）。生产库已原地重排，备份在 `.nutmeg-data/archive/`。

## 1. 起因

10-12 运维体检第 13 项列出「78 张空表 schema」，当时按 10-03 裁定不动。10-13 Jun 问这些表有没有用，实查：

| 项 | 数 |
|---|---|
| `ontology.db` 表 | 185 |
| 其中 0 行 | 141 |
| 0 行且现役代码（schema / migrations 之外）零引用 | 134 |
| `operator_*`（09-04〜09-10「双泳道操作台」，10-01 定位改后写入方全删） | 77 |
| `policy_*` / `discovery_*` / `exploration_*`（Dream 影子库，10-04 退役） | 20 |
| 有数据的表 | 44 |

它们删不掉只因迁移链：每步按 `version:name:fingerprint` 记 SHA-256，旧步骤通过 4 份 `schema_operator_*` 模块建表，改任何一步已装库就校验失败。

## 2. 做了什么

### 2.1 代码

- `nutmeg/ontology/repository/migrations.py` 4,842→811 行：`MIGRATIONS = (baseline_2026_10_13,)`。新建库 = `metadata.create_all` + 种子（governance-v1、145 条权限、4 盘口 34 选项、球队别名种子、记分牌 authority）+ 11 条守卫触发器（SQL 照旧链原文）。
- 旧库重排 `_rebase_legacy_chain`：账本必须恰为 1..47 且第 47 行校验和 = `69084dca…436f`（其他形状一律 `MigrationDriftError`）→ 逐张断言退役表 0 行（有行即拒）→ 删存活表上不在基线集合里的触发器（`actions` 上 7 条引用 operator 表的）→ 删 130 张表 → 补齐新建路径种下而生产库缺的 22 条权限 → 账本删 47 行写 1 行。其余数据行不碰。
- 删 9 份 schema 模块：`schema_context` `schema_discovery` `schema_discovery_generation` `schema_discovery_promotion` `schema_operator_decision` `schema_operator_result` `schema_operator_review` `schema_operator_sale` `schema_reliability` `schema_tickets`（`zucai_fixed_prize_policy_revisions` 移到 `schema_finance`，因 `tickets` 外键指向它）。
- 修两处 Table 定义与生产库不符：`actions.replay_run_id` 补外键 → `historical_replay_runs`；`selection_definitions.deployable` 默认值 `text('1')`。
- `kernel.status()` 去掉「10 / 13 已应用才统计出站与记分牌」的步号门；`ontology guarded-init` 行数守卫允许 0 行表消失。
- 测试：删 11 份按步号写的迁移测试（`test_m3_workflow_migration` `test_m6_reliability_migration` `test_rsi_migration` `test_rsi_stratum_migration` `test_schema_{context,decision,evidence,finance,identity,market}_migration` `test_workflow_migration`）与 4 个步号断言的用例；新 `test_migrations.py`：基线一次落地、指纹漂移拒绝、**旧库重排后与新建库结构逐表相等**（pragma 级列 / 外键 / 索引 / 触发器 + 账本 + 权限）、退役表有行即拒、未知账本形状即拒。旧 golden `fresh_schema.sql` 改名 `legacy_schema_47.sql` 做重排夹具（`actions` / `selection_definitions` 两张换成生产库 ALTER 形状的 DDL）；新 golden 重新生成。

### 2.2 生产库

```
uv run nutmeg ontology guarded-init --data-dir …/.nutmeg-data \
  --backup-file …/.nutmeg-data/archive/ontology-before-baseline-20261013-guarded.db
→ ontology guarded migration complete: schema_version=1
```

| 项 | 前 | 后 |
|---|---|---|
| 表 | 185 | 55 |
| 触发器 | 17 | 11 |
| `schema_migrations` | 47 行 | 1 行（`baseline_2026_10_13` `c45653c7…`） |
| `action_permissions` | 123 | 145（补 replay_adjudicator 20 + historical replay 2） |
| 44 张有数据表的行数 | — | 与迁移前备份逐表相等 |
| `PRAGMA integrity_check` | ok | ok |
| 与新建库结构差 | — | 无 |

备份两份：`ontology-before-baseline-20261013.db`（手工，08:15）与 `…-guarded.db`（guarded-init 自动，08:22）。`ontology status` / `rsi status` / `:8787/observe` 重排后正常。

## 3. 留下的 11 张空表（有意保留）

| 表 | 为何留 |
|---|---|
| `ticket_settlements` `bet_leg_settlements` | `finance.py` 有写入路径（结算实际走文件层，从未触发） |
| `factor_definitions` `flag_instances` `observations` | `decision.py` / `workflow.py` / `scoreboard.py` 读 |
| `source_runs` `historical_replay_runs` | 被 `artifact_retrievals` / `actions` 外键指向，且有读路径 |
| `venues` `evidence_bundles` `zucai_fixed_prize_policy_revisions` `factor_families` | 被 `match_revisions` / `forecast_revisions` / `tickets` / `factor_definitions` 外键指向；去掉要重建有数据的表 |

要再删这 11 张得先删它们的写入代码或重建外键表，另案。

## 4. 旧链账本（留档）

```
 1 governance_kernel                 2 evidence_kernel                3 football_identity
 4 market_definitions                5 football_context               6 football_evidence
 7 decision                          8 finance                        9 finance_entry_odds
10 product_workflow                 11 m3_proposal_citations         12 protected_ticket_workbench
13 scoreboard_authority             14 reliability_governance        15 prediction_subjects
16 ticket_shadows                   17 operator_official_sale        18–28 operator_*（证据入库 / 冻结 / 判断基线 / 候选比较 / 部署裁决 / 确认账 / 赛果结算 / 复盘记分 / 修复 / 游标 / 结构事实）
29 rsi_experiments                  30–34 rsi_* / forecast / capital  35 historical_replay_authority
36–41 jczq / discovery              42–47 discovery_* / rsi_* / forecast_judgment_payload
```

完整 47 行（version / name / checksum）保存在 `tests/ontology/golden/legacy_schema_47.sql` 末尾；第 47 行校验和写死在 `migrations.py::LEGACY_FINAL_CHECKSUM`。

## 5. 验证

- `uv run pytest -q tests/ontology tests/product tests/analytics tests/decision/test_ontology_adapter.py tests/decision/test_results_source.py`：全绿。
- 全量 `uv run pytest -q`：exit 0，无 FAILED / ERROR（提交前跑完）。
- `ruff check nutmeg tests`：无告警。
- `nutmeg/` 代码 47,523→37,904 行。
