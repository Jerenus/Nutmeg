# Daily Surface P1 · 首跑证据（2026-09-22）

计划：`docs/superpowers/plans/2026-09-22-daily-surface-p1-day-runner.md`（Task 1–6 全部落地，子代理逐任务 + 主会话复核提交）。
提交：99ad562 → a7a6817 → c72b02f → 822f164 → 2807b1e → 081c716 → a749d73（+ 一个 pending 去重修复）。

## 真跑

```
$ uv run nutmeg day run --job brief
day 2026-09-22 brief: brief 4 场 · 待人 7 · 缺席输入 0 (exit=0)
$ ls .nutmeg-data/daily/2026-09-22/
brief.json  brief.md  decisions.json  session.md  timeline.json
```

`session.md` 前几段（原样）：

```
# 会话入口 · 2026-09-22
规则：不重跑已完成作业；先看失败；对话从待人决定开始；每轮末尾报最近截止与剩余分钟。
## 作业
- brief ✓ @22:57
## 待人决定（从这里开始）
- [read:周二004] 周二004 维冈-布莱克浦（ai:jczq-analyst 草稿） · 截止 02:00 · 默认 草稿不入库＝跟市场
- [read:周二002] …  - [read:周二003] …
- [rsi:0] 因子 death_proof_count：propose_zero → 建议 0.0pp … · 默认 不动（hold）
## 竞彩 4 场（深研 4）
- 周二001 韩国亚-沙特亚 · 跟市场 · 0.0pp · 18:00 · 研究 done · Read ai:jczq-analyst/draft
- 周二004 维冈-布莱克浦 · 跟市场 · 0.0pp · 02:00 · 研究 skipped_permanent · Read ai:jczq-analyst/draft
## 足彩 26131 · 截止 20:30
- 风向 {"regime": "mixed", "tiers": {"T1": 1, "T2": 4, "T3": 6, "T4": 3}, …}
```

`decisions.json`：`read:周二001` 与 `plan:26131` 因截止已过标 `expired`，三个 02:00 开球的 Read 与三条因子提案 `open`。

## 测试

`uv run pytest tests/decision/test_day_{timeline,brief,decisions,session,runner}.py tests/test_cli_day.py -q` → 21 passed；ruff 干净。

## 真实数据暴露的三处偏差（都已修）

1. `price-band-<code>.json` 的 `drift_pp` 是逐面 dict，不是标量 → 取 |位移| 最大的带符号值。
2. `<期>-issue.json` 的 `sale_deadline` 是无时区的 `"2026-09-20 20:30"` → 按 +08:00 解析（brief 与 decisions 两处）。首次真跑因此 `TypeError`，时间线如实留了那一行。
3. 同一作业先失败后成功时，待人决定仍列着旧失败 → 只看每个作业最近一次。

## 未做（按计划归属）

broadcast 与 results 桥（P3）、逻辑层与审计列（P4）、页面（P2）。`decision.settle` 未装载，`--job settle` 的 `workbench-export` 已可手跑。
