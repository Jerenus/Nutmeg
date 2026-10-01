# 历史扩容（假期迭代 #5）· 2026-10-01

**目的**：把 gym 的竞彩样本从 134 个板面日（2026-05-18 起）扩到上一个完整赛季，让结构类规则（max-P / 大热两两）有 300+ 天的账，而不是只看 134 天。

## 数据

- **来源**：titan007 `JcResult.aspx?d=<日>`（已是每日结算回填的源）。页面按 `$` 分三段，第三段是**开奖 SP**：每场 `id^胜平负结果^SP^让球结果(线)^SP^总进球^SP^半全场^SP^比分^SP`——只有开出那个面的赔率，没有三面全价。`scripts/jczq_history_backfill.py` 把赛果 + SP 存到 `.nutmeg-data/jczq/jc-history.json`（与每日结算源 `jc-results.json` 分开）。
- **覆盖**：2025-08-01 → 2026-05-17：**290 天 / 4,516 场**，全部带 SP 段；其中 4,320 场（95.7%）有胜平负 SP，196 场只开让球不开胜平负（大热门常见）——这些场在 SP 板上不进策略视野（当天本就买不到 had）。另抓了本赛季 2026-05-18 → 09-30 的 SP 用于口径校验。
- **终盘**：`titan007_closing_backfill.py --results-file jc-history.json` 按 titan007 id 抓每场终盘（sharp/all，含书商 updated_at）进 `daily/<日>/closing_odds.json`。
- **SP 板语义**（`nutmeg/gym/board.py::load_history_board`）：belief ＝ 终盘 sharp fair；派奖 ＝ 开奖 SP（`settle_sp`，只支持 had 腿）；单关一律视为不开；EV 过滤类策略在 SP 板上无从算（没有三面价）。

## 价格口径校验：17:00 快照价 vs 开奖 SP（本赛季 1,230 场可比）

开出面上 SP 相对 17:00 价：**中位 +0.0%、均值 −0.0%，|Δ| 中位 2.4%，P90 8.0%**；按开出面分：主胜 −0.0%、平 −0.7%、客胜 +0.5%；17:00 价高于 SP 的占 43%。结论：**两种价格没有系统性偏差**——gym 用 17:00 快照价结算（本赛季）与用开奖 SP 结算（上赛季）可以放在一张表里比，单腿误差 ~2–3%，串关累乘后仍在噪声内。

## 整赛季回放结果

（终盘回填完成后补：`nutmeg gym run --history --from 2025-08-01 --to 2026-05-17 --policy flat,jczq_max_p,jczq_fav_pairs`，以及 2025-08-01 → 2026-09-30 全跨度。）
