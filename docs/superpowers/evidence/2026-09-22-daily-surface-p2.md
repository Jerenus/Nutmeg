# Daily Surface P2 · 当日页证据（2026-09-22）

计划：`docs/superpowers/plans/2026-09-22-daily-surface-p2-day-page.md`（Task 1–4 落地）。
提交：9b7c579（launchd 证据行）→ 96e1dcd（视图合成）→ 73189bc（路由）→ b0aa504（页面渲染）。

## 真实数据读数

`launchd_rows` 对本机 `ops/launchd/` + `launchctl list` + `.nutmeg-data/logs/`：

```
decision.am            08:00               loaded exit=0 2026-09-22T08:00
decision.close         19:00               NOT    exit=- 2026-08-13T19:00  ALARM（未装载 + 久未更新）
decision.settle        08:10               NOT    exit=- 2026-07-21T08:10  ALARM
jczq.results-backfill  09:30               loaded exit=2 2026-09-22T09:30  ALARM（RESULTS_STALE）
rsi.loop               10:45               loaded exit=0 2026-09-22T17:01
rsi.sweep              每小时 00 分         loaded exit=0 2026-09-22T23:00
zucai.f2-observe       每 15 分 08:00-23:45 loaded exit=0 2026-09-22T23:00
zucai.prep / prep-morning / prep-revision   loaded exit=0（当日）
```

`GET /api/day/2026-09-22`（TestClient 对真实 `.nutmeg-data`）：`200`，4 张竞彩卡、8 条待人决定、10 行 launchd、`errors=['缺 retro.md']`（settle 未跑，符合预期）。

## 测试

`tests/decision/test_day_ops.py`（1）、`tests/decision/test_day_view.py`（2）、`tests/test_decision_web_day.py`（6）通过；观察台与工作台既有测试 40 个不受影响；ruff 干净。

## 计划里被子代理纠正的一处真 bug

`decision_web.py` 的工厂里已经有一个局部名 `day_view`（观察台 `/api/observe/day` 的视图函数）。计划原文 `from nutmeg.decision.day_view import day_view` 会静默覆盖它，导致观察台那条路由下次调用签名不匹配。实现改为 `import … as day_page_view`，观察台测试全部照旧通过。

## 未做

`m.logic` 与审计徽章的显示已在 `day.js` 里预留字段，由 P4 填；浏览器截图未存（`nutmeg decision-web` 后打开 `/day` 即见）。
