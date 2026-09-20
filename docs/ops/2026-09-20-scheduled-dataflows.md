# Nutmeg 定时数据流与断流后果（2026-09-20）

> 运行权威是 `~/Library/LaunchAgents/com.nutmeg.*.plist` 与 `launchctl list`。
> 本页记录六条当前定时数据流；原设计所称「全部五个」是新增赛果回填前的数量。

| Label | 时刻（BJT） | 产物/职责 | 断流后果 |
|---|---:|---|---|
| `com.nutmeg.decision.am` | 08:00 | 竞彩早盘抓取、日板和深研调度底座 | 当日板面、R0 深研义务与后续判断链无输入 |
| `com.nutmeg.jczq.results-backfill` | 09:30 | 回填 `jc-results.json` | 语料、postmortem、F5 与 C11/C12 复检停在旧日期；脚本 lag > 2 天退出 2 |
| `com.nutmeg.zucai.prep-morning` | 11:00 | 足彩早备料 | 当期赛程、早盘与后续午后修订缺前置快照 |
| `com.nutmeg.zucai.prep` | 14:00 | 足彩午后备料 | B1-B4 主输入缺失，候选与审计无法按时运行 |
| `com.nutmeg.zucai.prep-revision` | 18:30 | 足彩临场修订 | 晚盘变化、阵容与赛前证据未进入最终判断 |
| `com.nutmeg.zucai.f2-observe` | 08:00-23:45 每 15 分钟 | F2 让球线前瞻观察 | 前瞻窗永久缺样，过开球后不能回补 |

排障先查 `launchctl list | grep nutmeg`，再查 `.nutmeg-data/logs/*.out.log` 与
`*.err.log`。赛果回填 stdout 首行出现 `⚠️RESULTS_STALE` 时，按退出码 2 处理，
不得把旧 `jc-results.json` 当成完整结算源。
