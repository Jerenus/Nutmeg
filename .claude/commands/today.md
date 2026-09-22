---
description: 从今天已跑完的结论开始对话（daily/<日>/session.md）
---

先读 `.nutmeg-data/daily/$(date +%F)/session.md`（没有就先跑 `uv run nutmeg day run --job brief`），再读同目录 `decisions.json`。

规则：
1. 不重跑时间线上已完成（exit=0）的作业；有失败先报失败，不自行修。
2. 对话从 `decisions.json` 里 status=open 的第一条开始；每一条给我「事实 → 判断 → 为什么」，引用 brief.json 的字段，不新增判断。
3. 每一轮回复末尾一行：`最近截止 HH:MM，剩余 N 分；未定则默认：<default_action>`。最后 30 分钟每轮必报；最后 10 分钟明写「现在不定＝空仓」。
4. 资金组合只在 `plan frontier` 的点上讨论；票面只从 `plan choose → plan commit` 出，聊天里不出票面；实票登记、register/deploy、购买确认都是我做，你只准备命令。
5. 我们的讨论用 `uv run nutmeg day note --text "…" --obj <场次>` 记进 discussion.jsonl，页面 /day 同步显示。
6. C 类赛后资讯不进今天任何一场的判断；研究 `captured_at` 晚于开球的卡片按 not_prospective 对待。
