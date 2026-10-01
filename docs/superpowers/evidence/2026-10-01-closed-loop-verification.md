# 假期迭代 · 回环验收记录（2026-10-01 起，逐项补）

Jun 2026-10-01：「一二三四都处理完成后开始五六的规划和实现，最后验证回环，完成开发后确认测试和验收都能正确。」本页只记**验证动作与结果**，不记设计；每项标日期时刻。

| # | 验证项 | 命令/位置 | 结果 | 时刻 |
|---|---|---|---|---|
| 1 | 全量测试（product 套件除外） | `uv run pytest -q --ignore=tests/product` | **全绿**，exit 0，3 分 08 秒（含 gym 29 条、judgment projection 6 条、rsi F15/G1、hafu 结算） | 10-01 13:28 |
| 1b | 全量测试复跑（定位转向后：审票/初判包/账房/行权片/Dream v3） | 同上 | **全绿**，exit 0 | 10-01 15:3x |
| 2 | gym 结算复现真票 | `uv run nutmeg gym verify` | 41/41 真票可结算；记分牌覆盖期（≥09-18）gym −4,721 = 记分牌 −4,721，差 0 | 10-01 11:0x |
| 3 | 八策略全量回放耗时 | `uv run nutmeg gym run --policy … --out …` | 6 分 05 秒（134 天 + 42 期） | 10-01 11:5x |
| 4 | 判断投影零分歧（历史批量） | `uv run python scripts/judgment_replay.py` | 755 条历史 Read，能进内核的 432 条投影全部一致，分歧 0 | 10-01 12:30 |
| 5 | P2 刷新降级路径 | `uv run nutmeg research refresh --day 2026-09-30` | 投影为空（schema 47 前的 revision 无 board_key）→「⚠️投影为空，保留文件」，文件未动 | 10-01 13:0x |
| 6 | launchd 任务 | `launchctl list \| grep nutmeg` | 14/14 已装载；`decision.am`/`jczq.research` 今日退出码 1 = 国庆板面空（`Sporttery calculator empty, not a WAF block`），属预期 | 10-01 13:27 |
| 7 | 10:45 loop 新末尾步 | `git log -1 -- experiments/corpus-v2.json` | `3e353a2 chore(experiments): loop outputs 2026-10-01` 自动提交成功，工作树此后干净 | 10-01 10:45 |
| 8 | F15/G1 结账走通 | `uv run nutmeg rsi grade --exp F15/G1 --mode prospective` | 两条 n=0（窗口 10-02 起），`rsi status` 可见 | 10-01 12:1x |
| 9 | 终盘历史回填（#5） | `scripts/jczq_history_backfill.py` + `titan007_closing_backfill.py --results-file jc-history.json` | 赛果+SP：290 天 / 4,516 场全带 SP（1 分 49 秒）；终盘 4,515/4,516 带 sharp fair（38 分 46 秒）；本赛季 SP 也抓齐，17:00 价 vs SP 无系统偏差（\|Δ\| 中位 2.4%） | 10-01 14:01 |
| 10 | 整赛季 SP 回放 | `nutmeg gym run --history --from 2025-08-01 --to 2026-05-17 …` / `--to 2026-09-30` | 267 天 60 秒；403 天 ~2 分钟；max_p −16.4%/−20.0%、fav_pairs −18.8%/−10.4%（evidence/2026-10-01-history-expansion.md） | 10-01 14:1x |
| 11 | 本赛季锦标赛复跑（赛果缺口补齐后） | 同 #3 | 数字不变（max_p −789/−28.0%，未结 11→8） | 10-01 13:4x |
| 12 | 审票 | `betslip preview`（tests/test_cli_betslip_preview.py） | 与已购票共享裸单 → ⛔V2、退出码 1；V1 期望回报率/V3 倍投按 tests/decision/test_review.py 6 例 | 10-01 14:5x |
| 13 | 初判包 | `nutmeg judgment brief --day/--issue` | 竞彩/足彩两表 + CLI 写盘，tests/decision/test_judgment_brief.py 3 例 | 10-01 15:0x |
| 14 | 行权只写 Adjudication | `decision-audit-legs --user-override`（无 token） | 1 ERROR → 1 Adjudication，同日幂等；登记不全则 0 条；tests/decision/test_audit_override.py 4 例 | 10-01 15:1x |
| 15 | 账房月报 | `nutmeg account month --month 2026-09` | 9 月：净 −4,721（竞彩 −530 / 足彩 −4,191）、止损已触发、EXP 0 张、F10 n=17 +19.5pp、F9 n=39 −0.2pp、判决 0/0/15 | 10-01 15:2x |
| 16 | Dream 评估器 v3 | tests/discovery/test_dream_compare.py / test_nightly.py | v3 行入夜录与对照账；13+ 例绿 | 10-01 15:2x |

## 待验（需要真实板面或到期才能跑）

- **10-02 08:00–10:45 早间链**：`decision-am` 抓到板 → `research run` → `intake` → `jczq-build-reads`（现在＝建 Read → 交本体 → 投影覆盖 `reads.json`）→ 10:45 loop（F10–F15/G1 结账 + Dream 对照账 + `commit_outputs`）。验收点：`daily/<日>/reads.json` 每条带 `kind/board_key/code`；`judgment-projection.json` 分歧 0；`nutmeg judgment project --day <日>` 投影条数 = 板面场数。
- **10-01 20:30 Dream 夜录**：板面空则 `DayBoardTooSmall` 跳过属预期；有板的第一天看 `~/nutmeg-shadow/reports/<日>.json`。
- ~~10-02 前置片~~ 已提前完成（#14）；**10-09** operator_* 退役专项（分支）。
- **P4-lite**（signals/verdict/retro 改读投影里的 override）未做：`overrides.jsonl` 仍是改判审计源，读者不变；等 P2 跑几天再动。
