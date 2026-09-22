# Daily Surface P3 · 定时器与播报证据（2026-09-22）

计划：`docs/superpowers/plans/2026-09-22-daily-surface-p3-timers-and-broadcast.md`（Task 1–5 落地）。
提交：7cb9456（赛果桥）→ d2b29c7（播报）→ 964fe82（runner/CLI）→ 17bd022（四个 plist）→ 本文。

## 真跑（只读，未装载、未发送）

```
$ uv run nutmeg day run --job broadcast --dry-run
（空：三条 02:00 开球的 Read 距截止 161 分，不在 T-30/T-10 窗；两条已过期；因子提案无截止）
$ uv run nutmeg day run --job broadcast --dry-run --date 2026-09-22 --now 2026-09-23T01:35:00+08:00
⏰ 剩 25 分（截止 02:00）
周二004 维冈-布莱克浦（ai:jczq-analyst 草稿）
未定则默认：草稿不入库＝跟市场
（Nutmeg 只播报时间，不代下单；回复或打开 /day 处理）
---   （周二002、周二003 同形）
$ plutil -lint ops/launchd/com.nutmeg.day.*.plist ops/launchd/com.nutmeg.jczq.research.plist
… : OK ×4
```

`broadcasts.jsonl` 未产生，`timeline.json` mtime 未变——dry-run 零副作用。

## 测试

`test_day_results`（3）、`test_day_broadcast`（3）、`test_day_runner`（+2）、`test_cli_day`（+1）、`test_launchd_plists`（2，覆盖全部 14 个 plist）通过；ruff 干净。

## 待改进（不阻塞）

同一截止的多条决定会发多条播报（今天三条 02:00 的 Read 各一条）；下一版按截止分组合并成一条。

## 装载（Jun 的门，本文不执行）

```bash
for p in day.settle jczq.research day.brief day.broadcast; do
  cp ops/launchd/com.nutmeg.$p.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.nutmeg.$p.plist; done
launchctl list | grep nutmeg
```

前提：`.env` 里 `NUTMEG_TELEGRAM_BOT_TOKEN` 与 `NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS` 已配（播报用它们）；`day.brief` 12:00 那次要不要 `--with-logic` 由 P4 决定。
