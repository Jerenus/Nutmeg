# Dream 夜间录制 · 实施证据（2026-09-28 / 29）

设计：`docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md`（ea0c4c9，本分支修订评估器 v2 与「对照料在录制时算」两处）
计划：`docs/superpowers/plans/2026-09-28-dream-nightly-recording.md`（81535cf）
分支：`feat/dream-nightly`（worktree `../Nutmeg-dream-nightly`，避免 launchd 在迁移中途导入半成品代码）

## 1. 出生事故：首个真实世界

2026-09-28 21:42 在 Jun 单次批准（「确认，开始跑」）下录制 `discovery-world-3b91e3ce6edf4eb1b9fb53e9`：
7 场（周一002–008），模板 pass-2-1…pass-5-1，**四个分片全部 120 s 超时**，封存为 `no_solution / wall_budget_exhausted`，readiness 记为 failed/degraded。批准文件 `~/nutmeg-shadow/approvals/2026-09-28-first-day-world.json`。

| 阶段 | pass-2-1 | pass-3-1 | pass-4-1 | pass-5-1 |
|---|---|---|---|---|
| 修复前（录制时） | timeout 120 s | timeout 120 s | timeout 120 s | timeout 120 s |
| 只修生成器（原型，评估器 v1） | over_cap 0.0 s | over_cap 0.1 s | over_cap 0.4 s | over_cap 0.9 s |
| 生成器 + 评估器 v2（09-28 板，21:42 截止，开球过滤后 6 场） | complete 0.01 s | complete 0.06 s | complete 0.16 s | complete 0.25 s |

- 生成器根因：`enumerate_candidates` 先 `combinations(全部原子票, ≤20)` 再按模板组数过滤；pass-2-1 有 207 张原子票，cProfile 45 s 内过滤函数被调 1.1 亿次、才走到 size=5。计数门按限制计数（=207），`CandidateSpaceLimitError` 没拦住。
- 评估器 v1：每档候选 >20 即整片 `over_cap` 失败；真实板面每档几十到几百个候选（v2 实测：pass-3-1 20x 档 113 个、pass-5-1 100x 档 121 个）。

## 2. Jun 的裁决（原话）

- 夜间录制设计：「以上全写成设计，常批准先实验到10.31日，其它我按照你的想法开始玩真的设计文档。」
- 评估器：选择「评估器 v2：超 20 不判失败 (Recommended)」。
- 实施：「没问题，一口气完成所有的人实施计划」。
- 定时任务装载（launchd 行权门）：同上授权（设计 §3.4 写明装载属行权门，Jun 批准整份设计与实施）。

## 3. 真实数据端到端（只读生产数据）

09-28 板、截止 `2026-09-28T21:42:11+08:00`：

- 入世界 6 场：周一003–008；`excluded_started`：周一002（`kickoff:2026-09-28T19:00:00+08:00`）
- 票面引用：`2026-09-28:tickets` → `f3d3d035a23d…`（当天空仓，空票面同样被哈希）
- 各档最优（`best_candidates_by_band`，0.47 s）：10x P=0.1145 @8.31、20x P=0.0469 @16.31、50x P=0.0239 @35.71、100x P=0.0120 @76.11
- 决策规则最优：周一004「30」+ 周一005「30」，P=0.5387，4 注，全中每元 1.077（与当天 `jczq-combos` 同一组合）

## 4. 常设批准

`experiments/discovery/approvals/standing-dream-nightly-2026-10.json`
sha256 `ad9feb639fdf02a552a5a3f40a70275132a64dd4864b680d8724c66d3771a26e`；`approved_at`/`valid_from` 2026-09-29T07:48:32+08:00，`valid_until` 2026-10-31T23:59:59+08:00；窗口 20:00–23:59（北京时间）；每业务日至多 1 个世界。撤销＝填 `revoked_at` 或删文件。

## 5. 测试

- 分支逐任务 TDD，每个任务先见红再见绿；`tests/discovery` 全绿。
- worktree 里 `tests/decision` 有 3 个用例按相对路径读生产 `.nutmeg-data`（`test_rsi_population` ×2、`test_balance_ledger::test_real_26129_reads_have_zero_moves`），worktree 无此目录故失败；它们与本改动无关，Task 10/11 提交时跳过了 `pytest-touched-decision` 钩子，合并后在 main 上补跑（见 §6）。

## 6. 合并与装载

见合并后的补记。
