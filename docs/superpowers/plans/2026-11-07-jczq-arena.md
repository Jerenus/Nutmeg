# 竞彩虚拟规则赛 Arena Implementation Plan

> 设计：`docs/superpowers/specs/2026-11-07-jczq-arena-design.md`。本计划由同一会话当场执行，所以这里写接口契约和测试用例，代码以提交为准。

**Goal:** 上线一条独立分析线：每天冻结虚拟组合、赛后结算、月度榜单，AI 规则经评审和封存验证后入赛。

**Architecture:** `nutmeg/decision/arena/` 纯函数负责选腿和结算，账本只写 `.nutmeg-data/jczq/arena/`，CLI 是 `nutmeg arena`，定时由两个 launchd 任务驱动。

**Tech Stack:** Python 标准库、typer、pytest、launchd。项目无 numpy 依赖，模拟用纯 Python。

**口径检查结果（Task 0，已完成）：** 147 天 1,210 场，赔率最后变动和国际盘落盘都没有晚于开球。快照只留未开球的场，历史 `matchStatus` 全为 Selling，`selling_rows` 可通用。

## Tasks

- [ ] **Task 1 legs.py**：`build_legs(value, odds, day, *, ref, stances=None) -> list[dict]`。测试：胜平负三面、让1 主不胜、受让1 主不败、其他让球线不出腿、缺国际盘跳过、gap 用 `devig`、stance_match。
- [ ] **Task 2 rules.py**：`validate_rule(rule) -> list[str]`、`pick_legs(legs, rule) -> list[dict] | None`。测试：拒绝赛后字段、档位边界左闭右开、串关不重场、取联合 P 最高、结果确定。
- [ ] **Task 3 settle.py**：`settle_ticket(ticket, outcomes, voids, settled_at) -> dict | None`。测试：全中、一腿错、取消场赔率 1、缺赛果待结、冻结晚于开球被拒。
- [ ] **Task 4 floor.py**：`floor_tickets(day, legs, tier, n=30)`。测试：固定种子可复现、全部落在档内、不重场。
- [ ] **Task 5 baseline.py + ledger.py**：19 条基线、3 条研究；规则与账本读写。测试：赛道数 22、全部过校验、基线去掉两格、追加写入可读回。
- [ ] **Task 6 backtest.py**：`history_days`、`replay`、`check_admission`、`dev_pack`。测试：开发和封存窗口边界、dev pack 不含封存日、入赛门槛。
- [ ] **Task 7 freeze.py**：`freeze_day`。测试：过滤临近开球、同日重跑不重复、当日空记录、地板落盘。
- [ ] **Task 8 board.py**：`track_rows`、`champion_line`、`render_board`。测试：主分算术、无人过线写「本季无有效冠军」。
- [ ] **Task 9 CLI 与定时**：`nutmeg arena init|freeze|settle|board|backtest|dev-pack|admit`，`com.nutmeg.arena.freeze`（18:40）、`com.nutmeg.arena.settle`（09:50、15:50），JobSpec 和 plist 测试。
- [ ] **Task 10 回放验证与文档**：基线回放对照摸底回测；更新 RUNBOOK、ARCHITECTURE、CLAUDE.md、AGENTS.md。
- [ ] **Task 11 首季上线**：`arena init`，6 名 AI 选手投稿，评审，封存验证，装载定时，确认 `account month` 不变。
