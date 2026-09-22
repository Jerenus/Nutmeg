# RSI 闭环自动化 · 首跑证据

日期：2026-09-22
设计：`docs/superpowers/specs/2026-09-22-rsi-closed-loop-automation-design.md`
命令：`uv run nutmeg rsi loop`（第二次 `--force`）

## 结果

| 项 | 值 |
| --- | --- |
| 步骤 | 8 步，第一次失败 1（F4 重结账撞幂等键），修后第二次失败 0 |
| 耗时 | 21 秒（终盘补采全部幂等跳过，语料重建 1.1 秒，propose 1.9 秒） |
| 前瞻结账 | F2 n=11 +9.0pp；F3 n=23 +8.6pp；F4 n=0；F5 n=23 +7.5pp；F9 n=0 |
| 判决 | 五个全部 `not_due`（距 n_min 分别 129 / 97 / 12 / 97 / 60） |
| 因子提案 | propose_zero ×3（death_proof_count、C11、C12），hold ×6，record_only ×2；无 propose_change |
| 假设批次 | 11 条重跑，结论落 attempts.log |
| 人类清单 | 3 条确认零提案；无登记候选；无部署候选 |
| 报告 | `.nutmeg-data/analytics/rsi-loop/2026-09-22.{json,md}`，`latest.md` |

## 修掉的一个真 bug

`rsi grade` 的幂等键只含 `inputs_hash`，同一份输入第二天重结账时 `requested_at` 不同即撞
`IdempotencyConflictError`。每日闭环必然重跑，所以改为：撞键 = 输入未变，沿用已有 grade，
打印说明，退出码 0。不引入按日期的新键，避免每天写一行相同的 grade。

## 新增的三个前瞻适配器首算

| 实验 | 窗 | n | 残差 | CI | 距 n_min |
| --- | --- | --- | --- | --- | --- |
| F3 | 26125–26136，top1≥60% | 23 | +8.63pp | [−6.67, +21.55] | 97 |
| F5a | ≥2026-09-19，gap12∈[10,20) | 23 | +7.46pp | [−14.04, +28.78] | 97 |
| F9 | ≥2026-09-20，belief≠prior | 0 | — | — | 60 |

F9 为 0 是事实：窗内没有一次判读拨动天平。这正是 F9 要测的东西。

## 未接的适配器与原因

- F8：判据要真实票面上的「两证 + 被排面 fair ≤ X」决策，语料里没有这个决策对象。
- R0：覆盖率要板面总数，观测行只有已研究数。
- F1c：要每期书目分布快照；26125–26128 永久缺口。

## 验证

- `tests/decision/test_rsi_grading_prospective.py` 4 个用例、`tests/decision/test_rsi_loop.py` 3 个用例通过。
- 运行器发出的命令里没有 `rsi deploy` / `rsi register`；`factors.json` 字节未变；RULEBOOK / 码表 / scoreboard 未变。
- `ops/launchd/com.nutmeg.rsi.loop.plist` 已写，未装载（Jun 的行权门）。装载命令：

```
cp ops/launchd/com.nutmeg.rsi.loop.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.nutmeg.rsi.loop.plist
launchctl list | grep rsi.loop
```
