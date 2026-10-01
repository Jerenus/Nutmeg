# 假期迭代 · 回环验收记录（2026-10-01 起，逐项补）

Jun 2026-10-01：「一二三四都处理完成后开始五六的规划和实现，最后验证回环，完成开发后确认测试和验收都能正确。」本页只记**验证动作与结果**，不记设计；每项标日期时刻。

| # | 验证项 | 命令/位置 | 结果 | 时刻 |
|---|---|---|---|---|
| 1 | 全量测试（product 套件除外） | `uv run pytest -q --ignore=tests/product` | **全绿**，exit 0，3 分 08 秒（含 gym 29 条、judgment projection 6 条、rsi F15/G1、hafu 结算） | 10-01 13:28 |
| 2 | gym 结算复现真票 | `uv run nutmeg gym verify` | 41/41 真票可结算；记分牌覆盖期（≥09-18）gym −4,721 = 记分牌 −4,721，差 0 | 10-01 11:0x |
| 3 | 八策略全量回放耗时 | `uv run nutmeg gym run --policy … --out …` | 6 分 05 秒（134 天 + 42 期） | 10-01 11:5x |
| 4 | 判断投影零分歧（历史批量） | `uv run python scripts/judgment_replay.py` | 755 条历史 Read，能进内核的 432 条投影全部一致，分歧 0 | 10-01 12:30 |
| 5 | P2 刷新降级路径 | `uv run nutmeg research refresh --day 2026-09-30` | 投影为空（schema 47 前的 revision 无 board_key）→「⚠️投影为空，保留文件」，文件未动 | 10-01 13:0x |
| 6 | launchd 任务 | `launchctl list \| grep nutmeg` | 14/14 已装载；`decision.am`/`jczq.research` 今日退出码 1 = 国庆板面空（`Sporttery calculator empty, not a WAF block`），属预期 | 10-01 13:27 |
| 7 | 10:45 loop 新末尾步 | `git log -1 -- experiments/corpus-v2.json` | `3e353a2 chore(experiments): loop outputs 2026-10-01` 自动提交成功，工作树此后干净 | 10-01 10:45 |
| 8 | F15/G1 结账走通 | `uv run nutmeg rsi grade --exp F15/G1 --mode prospective` | 两条 n=0（窗口 10-02 起），`rsi status` 可见 | 10-01 12:1x |
| 9 | 终盘历史回填（#5） | `scripts/jczq_history_backfill.py` + `titan007_closing_backfill.py --results-file jc-history.json` | 赛果+SP：290 天 / 4,516 场全带 SP（1 分 49 秒）；终盘回填进行中（~3 天/分钟） | 10-01 13:28 |

## 待验（需要真实板面或到期才能跑）

- **10-02 08:00–10:45 早间链**：`decision-am` 抓到板 → `research run` → `intake` → `jczq-build-reads`（现在＝建 Read → 交本体 → 投影覆盖 `reads.json`）→ 10:45 loop（F10–F15/G1 结账 + Dream 对照账 + `commit_outputs`）。验收点：`daily/<日>/reads.json` 每条带 `kind/board_key/code`；`judgment-projection.json` 分歧 0；`nutmeg judgment project --day <日>` 投影条数 = 板面场数。
- **10-01 20:30 Dream 夜录**：板面空则 `DayBoardTooSmall` 跳过属预期；有板的第一天看 `~/nutmeg-shadow/reports/<日>.json`。
- **整赛季 SP 回放**：终盘回填完成后 `nutmeg gym run --history --from 2025-08-01 --to 2026-05-17 --policy flat,jczq_max_p,jczq_fav_pairs`。
- **10-02 前置片**：`decision-audit-legs --user-override` 入账只写 `adjudications`；**10-09** operator_* 退役专项（分支）。
