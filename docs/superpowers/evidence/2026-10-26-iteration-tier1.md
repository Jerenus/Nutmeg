# 2026-10-26 迭代设计 Tier 1 落地证据

设计稿：`docs/superpowers/plans/2026-10-26-iteration-design.md`（报告页 https://claude.ai/artifact/VKduMTqCGGW6EmCF7swa8E）。
Jun 当日定案：Tier 1 开工；Tier 2 单位保持「场」、竞彩全板研究保留（#8/#9 撤回）；Tier 3 改「指标两段式」（RULEBOOK「〇」）；Tier 4 越线期 §2 照出票形（#17 撤回）。

## 基线（10-12 → 10-26，runs.jsonl 629 次 33 次 exit≠0）

| 作业 | 次 | 根因 | 处理 |
|---|---|---|---|
| rsi.sweep | 22 | F9 已结账、F16 已退役，但 `--keep-duties` 观察义务仍守前瞻资格；07:00 多数场 reads 未到属合法未登记 | 已结案实验义务「照跑不红」（数据仍供损耗列/位移列），计数 `observer_unregistered` |
| day.settle | 7 | 09:45 `results` 步在赛果封存（15:30 backfill）之前必 exit 1 | exit 0 + `waiting_backfill`，真错仍 exit 1 |
| day.verdict | 3 | enumerate_combos 全枚举 SIGKILL | 10-25 裁腿修复，本日随积压提交 9fdc18ee |
| 会话依赖 | — | 21:00 首发复核 / 18:30 diff 挂在会话 turn | `zucai-lineup-watch` + launchd 每 15 分 |

## 提交

| commit | 内容 |
|---|---|
| 158a0702 | 积压：SOP/§5 两列/N0 登记/两 plist/样本表 |
| 9fdc18ee | 积压：verdict 裁腿、V5、丢光 C 档参考形、④ 名单窗口、预算 40→10000 |
| 737ff903 | sweep/loop 去噪、研究遥测、settle 假红、账房实质余量 |
| 59a4ecd3 | lineup-watch 播报去会话化 + plist |
| 30bd6b5a | 入库只警告、structure_align、builder m 文件对齐 |

## 验证

- `rsi sweep --day 2026-10-26`：`observer_unregistered=0 failed=0` exit 0。
- `rsi loop --skip commit_outputs --force`：9 步 0 失败；日报 83 → 63 行；F14b 行并排「N0 地板 CI[-8.7,+52.2] 不过地板（n=23 同窗）」。
- `day run --job results`：`waiting_backfill … (exit=0)`，rc=0。
- `account month`：第二行「实质余量（含待结票）：待结 3 张 ¥768 → −8,690｜⛔越线 ¥690」。
- 研究遥测真 CLI 冒烟：`model claude-opus-5-5, cache_creation_input_tokens 29757, cost_usd 0.238`——**系统提示每场重建缓存 ~3 万 token，是研究成本大头**（后续优化点，不在本次范围）。
- `zucai-lineup-watch --issue 26150 --dry-run`：`no_match_in_window`，无网络；`--now 2026-10-27T02:30+08:00` 真 API：PSG–Lyon 经同联赛+开球时间回退解析到 fixture 1552800，`no_lineups`（名单未出，下一 tick 重试）。
- 入库桥干跑三份历史被拒原件（26143-m8、10-17 周六006、10-23 周五006）：`blocked False`，`intake_warn` 含 `q4_context_conflict`。`stance.market_read` 枚举外值仍由 `validate_stance` 拒（4 份），未改。
- `structure_align --issue 26150`：最深层 95 格、n≥20 仅 4 格；≥10pp 的 5 格全在粗层（b 档热门开 74% vs 市场 62% n=85＝F10 命题，只展示）。
- builder 重跑 2574 → 2609 行；m 文件 262 份＝直接 105 + 竞彩副本 150 + 7 份窗口外。
- 测试：`tests/decision tests/experiments tests/test_single_source.py tests/test_cli_rsi_sweep.py tests/test_cli_betslip_preview.py` 全过；ruff 全过。

## 有意偏离设计稿的两处

1. F9/F16 registry duty 没置 retired：DB 是事实源，且 team-load.json / balance.json 仍被分析包读；改成「照跑不红」达到同样效果。
2. 入库桥没把 `validate_stance` 的 market_read 拒收一并降级（在 stance.py，另案）。

## 待办

- launchd `com.nutmeg.zucai.lineups` 装载（本日）。
- Tier 3 两段式工具化：`structure_align.py --indicator` 预筛入口、`rsi prereg` n_min 按效应量模板、RULEBOOK「展示中」状态行。
- 研究成本优化：系统提示缓存复用（每场 $0.24 的 cache_creation）。
- Tier 4 #16 选择账 20 期（≈11-10）、#18/#19 待 Jun 签。

## 同日下午 · Tier 2/3/4 落地（commit 207fd00b）

| 项 | 结果 |
|---|---|
| Tier 2 market_read | 枚举外值归一入库（原值留 `market_read_raw`），判死面三证 <3 → alive + `verdict_raw`；intake 加 `market_read_normalized` / `dead_face_downgraded` WARN 码 |
| Tier 2 研究缓存 | 根因：无头 claude 每场新建临时 cwd，CLI 把 cwd 写进上下文 → ~18k token 系统提示段每场重建。固定空目录后对照：A 临时目录 $0.298 / D 固定目录第二次 cache_read 37,064·creation 0·**$0.0075**。brief 与输出 token 不变 |
| Tier 3 预筛 | `structure_align --indicator-json`：残差 CI 按日簇 bootstrap；地板＝同池随机抽同 n 行 200 次（打乱赛果对简单残差无效）。**F19 真实·未价 28 行 −10.9pp CI[−23.8,+4.8] 地板 [−16.1,+11.8] 不过；F10 b 档 85 行 +13.6pp 地板 [−6.0,+14.9] 不过** |
| Tier 3 登记 | `rsi register --prescreen`：不过地板 exit 1；<10pp 写 `role: display_only`；否则 n_min=60 |
| Tier 3 epoch | `rsi epoch --exp --reason`：旧 epoch 结账 + retire 标 epoch_closed，副本 `<id>.v2.json`；只许人跑 |
| Tier 3 K2 | `role: monitor`，loop verdict_due 不再每天 not_due |
| Tier 4 #16 | `account choices --from 26136`：15 期三列同钱账。合计（26150 待）Jun ¥7,652 P 和 2.00 中 2 净 −6,053｜机器默认 7 期出票 ¥4,096 P 和 0.58 中 1 净 −3,247｜退役形 ¥8,034 P 和 1.67 中 3 净 +362。**读法警告**：退役形 26136–26149 全是从 legs-base 赛前 belief 重建（可改文件）、¥6–18 小票按同钱 ×26–106 放大，+362 由 26143/26149 两期撑起；n=15 读合计不读单期，20 期（≈11-10）再读 |
| 待签 | #18 已由账房「开球后才写理由」单列承担；#19 第四次越线动作、epoch 触发规则 由 Jun 写 |
