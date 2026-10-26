# 2026-10-26 迭代设计 Tier 1 落地证据

设计稿：`docs/superpowers/plans/2026-10-26-iteration-design.md`（报告页 https://claude.ai/artifact/VKduMTqCGGW6EmCF7swa8E）。
Jun 当日定案：Tier 1 开工；Tier 2 单位保持「场」、竞彩全板研究保留（#8/#9 撤回）；Tier 3 改「指标两段式」（RULEBOOK「〇」）；Tier 4 越线期 §2 照出票形（#17 撤回）。

## 基线（10-12 → 10-26，runs.jsonl 629 次 33 次 exit≠0）

| 作业 | 次 | 根因 | 处理 |
|---|---|---|---|
| rsi.sweep | 22 | F9 已结账、F16 已退役，但 `--keep-duties` 观察义务仍守前瞻资格；07:00 多数场 reads 未到属合法未登记 | 已结案实验义务「照跑不红」（数据仍供损耗列/位移列），计数 `observer_unregistered` |
| day.settle | 7 | 09:45 `results` 步在赛果封存（15:30 backfill）之前必 exit 1 | exit 0 + `waiting_backfill`，真错仍 exit 1 |
| day.verdict | 3 | enumerate_combos 全枚举 SIGKILL | 10-25 裁腿修复，本日随积压提交 9fdc18ee |
| 会话依赖 | — | 21:00 首发复核 / 18:30 diff 挂在会话 turn | `zucai-lineup-watch` + launchd 每 15 分 |

## 提交

| commit | 内容 |
|---|---|
| 158a0702 | 积压：SOP/§5 两列/N0 登记/两 plist/样本表 |
| 9fdc18ee | 积压：verdict 裁腿、V5、丢光 C 档参考形、④ 名单窗口、预算 40→10000 |
| 737ff903 | sweep/loop 去噪、研究遥测、settle 假红、账房实质余量 |
| 59a4ecd3 | lineup-watch 播报去会话化 + plist |
| 30bd6b5a | 入库只警告、structure_align、builder m 文件对齐 |

## 验证

- `rsi sweep --day 2026-10-26`：`observer_unregistered=0 failed=0` exit 0。
- `rsi loop --skip commit_outputs --force`：9 步 0 失败；日报 83 → 63 行；F14b 行并排「N0 地板 CI[-8.7,+52.2] 不过地板（n=23 同窗）」。
- `day run --job results`：`waiting_backfill … (exit=0)`，rc=0。
- `account month`：第二行「实质余量（含待结票）：待结 3 张 ¥768 → −8,690｜⛔越线 ¥690」。
- 研究遥测真 CLI 冒烟：`model claude-opus-5-5, cache_creation_input_tokens 29757, cost_usd 0.238`——**系统提示每场重建缓存 ~3 万 token，是研究成本大头**（后续优化点，不在本次范围）。
- `zucai-lineup-watch --issue 26150 --dry-run`：`no_match_in_window`，无网络；`--now 2026-10-27T02:30+08:00` 真 API：PSG–Lyon 经同联赛+开球时间回退解析到 fixture 1552800，`no_lineups`（名单未出，下一 tick 重试）。
- 入库桥干跑三份历史被拒原件（26143-m8、10-17 周六006、10-23 周五006）：`blocked False`，`intake_warn` 含 `q4_context_conflict`。`stance.market_read` 枚举外值仍由 `validate_stance` 拒（4 份），未改。
- `structure_align --issue 26150`：最深层 95 格、n≥20 仅 4 格；≥10pp 的 5 格全在粗层（b 档热门开 74% vs 市场 62% n=85＝F10 命题，只展示）。
- builder 重跑 2574 → 2609 行；m 文件 262 份＝直接 105 + 竞彩副本 150 + 7 份窗口外。
- 测试：`tests/decision tests/experiments tests/test_single_source.py tests/test_cli_rsi_sweep.py tests/test_cli_betslip_preview.py` 全过；ruff 全过。

## 有意偏离设计稿的两处

1. F9/F16 registry duty 没置 retired：DB 是事实源，且 team-load.json / balance.json 仍被分析包读；改成「照跑不红」达到同样效果。
2. 入库桥没把 `validate_stance` 的 market_read 拒收一并降级（在 stance.py，另案）。

## 待办

- launchd `com.nutmeg.zucai.lineups` 装载（本日）。
- Tier 3 两段式工具化：`structure_align.py --indicator` 预筛入口、`rsi prereg` n_min 按效应量模板、RULEBOOK「展示中」状态行。
- 研究成本优化：系统提示缓存复用（每场 $0.24 的 cache_creation）。
- Tier 4 #16 选择账 20 期（≈11-10）、#18/#19 待 Jun 签。
