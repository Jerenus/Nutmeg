# Nutmeg 定时数据流与断流后果（2026-09-20）

> 运行权威是 `~/Library/LaunchAgents/com.nutmeg.*.plist` 与 `launchctl list`。
> 本页记录八条已装载 + 四条待装载的定时数据流（2026-09-22 补 rsi.loop / rsi.sweep / day.* / jczq.research）；plist 单一来源 `ops/launchd/`。

| Label | 时刻（BJT） | 产物/职责 | 断流后果 |
|---|---:|---|---|
| `com.nutmeg.decision.am` | 08:00 | 竞彩早盘抓取、日板和深研调度底座 | 当日板面、R0 深研义务与后续判断链无输入 |
| `com.nutmeg.jczq.results-backfill` | 09:30 | 回填 `jc-results.json` | 语料、postmortem、F5 与 C11/C12 复检停在旧日期；脚本 lag > 2 天退出 2 |
| `com.nutmeg.zucai.prep-morning` | 11:00 | 足彩早备料 | 当期赛程、早盘与后续午后修订缺前置快照 |
| `com.nutmeg.zucai.prep` | 14:00 | 足彩午后备料 | B1-B4 主输入缺失，候选与审计无法按时运行 |
| `com.nutmeg.zucai.prep-revision` | 18:30 | 足彩临场修订 | 晚盘变化、阵容与赛前证据未进入最终判断 |
| `com.nutmeg.zucai.f2-observe` | 08:00-23:45 每 15 分钟 | F2 让球线前瞻观察 | 前瞻窗永久缺样，过开球后不能回补 |
| `com.nutmeg.rsi.loop` | 10:45 | 每日闭环：终盘补采 → 语料重建 → 前瞻结账 → 判决到期 → 因子提案 → 假设批次 → 因子搜索 → 实力指数 → 记分牌解析 → `analytics/rsi-loop/latest.md` | 判决与提案停在前一天；`--force` 可当天重跑 |
| `com.nutmeg.rsi.sweep` | 每小时 :00 | 兑现到期的 RSI 义务仪器 | 义务过期成 gap，事后不能回补 |
| `com.nutmeg.day.settle` | 09:45（须在 09:30 赛果回填之后） | `day run --job results` + `--job settle`：昨日赛果桥 → 实票结算 / rx 判定 / 复盘草稿 `daily/<日>/retro.md` | 昨日复盘草稿与实票结算缺；`/day` 昨日块空 |
| `com.nutmeg.jczq.research` | 10:00 | `research run` → `intake --write` → `jczq-build-reads`：全板每场深研与草稿 Read | 板上只剩 market-anchor 草稿；判读层实验零贡献 |
| `com.nutmeg.day.brief` | 12:00 / 14:20 / 18:35 | `day run --job brief`：日报 v1/v2/v3、待人决定、会话包 | `/day` 与 `/today` 读到旧报告 |
| `com.nutmeg.day.broadcast` | 每 10 分钟 | 截止前 30/10 分钟 Telegram 播报，明写默认空仓 | 截止无人提醒（26130 复发） |

排障先查 `launchctl list | grep nutmeg`，再查 `.nutmeg-data/logs/*.out.log` 与
`*.err.log`。赛果回填 stdout 首行出现 `⚠️RESULTS_STALE` 时，按退出码 2 处理，
不得把旧 `jc-results.json` 当成完整结算源。
