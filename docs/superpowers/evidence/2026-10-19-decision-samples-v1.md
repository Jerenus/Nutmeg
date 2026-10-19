# decision-samples-v1 —— 决策树样本表（历史数据修复，2026-10-19）

Jun 要求「尽可能还原当时各方面的信息和数据，作为后续决策树的样本」。本表是**从当时落盘的文件拼回来的**，不含任何事后补写的研究。

- 构建器：`experiments/decision_samples_build.py`（只取数、对齐、确定性派生；可重跑）
- 产物：`experiments/decision-samples-v1.jsonl`（一行一场，2,083 行，2026-05-18 → 10-18）+ `experiments/decision-samples-v1.coverage.md`（每列非空数与起止日）
- 去重：内核 `match_id` → titan007 `match_id` → 国际盘对齐的竞彩编号 → 日期+队名前两字；竞彩∪足彩合并 228 行，足彩独有 108 行（不在竞彩板上的场次），21 行只有足彩场号键（26121/26127/26128 早期无身份链）。

## 每一行有什么（按来源分块，每块带 `src` / 采集时刻 / `prospective`）

| 块 | 内容 | 覆盖 | 来源 |
|---|---|---|---|
| 身份 | 日期、竞彩编号、足彩期·场、队名、联赛、开球 | 05-18 起 | legs-base / `sporttery_markets`（09-19 前唯一队名来源）/ issue.json |
| `result` | 90' 比分、3/1/0 | 1,630 | `jc-results` → 足彩官方串 → corpus-v2 |
| `price_closing` | titan007 sharp 开盘/终盘去水、书商数 | 1,547 | `closing_odds`（竞彩）/ 足彩 closing-odds / odds-intl |
| `price_read_time` | 15 家读判时去水 + 开盘 | 1,443 | `bold_odds` |
| `price_sporttery` | 体彩 HAD 去水 | 1,741 | `sporttery_markets.had` |
| `belief` | 系统 belief / 市场 prior / judge / 时刻 | 1,638（≠市场 219，07-23 起） | reads.json → 足彩 legs-base → corpus-v2 内核 lane |
| `research` | 锚方、完整度、洞（v1 旧 schema 165 / v2 324）、强弱天平 verdict、表态面/cover/结构、market_read、牌照四问、死亡三证、旗、crash_markers、rubric r1 逐项、**标签代理** | 489（前瞻 405） | research-<code>.json / 足彩 research-m / legs-base 转录 |
| `reader_b` | 两读 κ | 240 | rubric-<code>.json |
| `intl_drift` | 国际盘开→停售位移 | 227 | 足彩 odds-intl |
| `polymarket` | 成交 / 24h / 名次 / PM 概率 / 与市场差 | 132 | polymarket.json |
| `load` | 休息天数 / 14 天场数 / 旗 | 185 | team-load.json |
| `overrides_n` | 主循环改判次数 | 19 | overrides.jsonl |
| `derived` | 热门面、p_fav、档（A/B/b/C/D）、系统偏离 pp、国际盘位移 pp、洞折算（fav/dog/both/none）、热门/表态面命中 | — | 确定性算术 |

## 硬下限（为什么回不到五大联赛第一轮）

| 字段 | 起始 |
|---|---|
| 价格 / 赛果 / 队名 | 05-18 |
| belief≠市场 | 07-23（corpus-v2 内核 lane）；reads.json 口径 09-26 |
| anchor_integrity | 09-10（足彩 26121） |
| 洞 v1（opponent/anchor 两列） | 09-10；洞 v2（side/unit/priced_in） 09-20 |
| 牌照四问 / 死亡三证 | 09-12 / 09-16 |
| 强弱天平 verdict / 表态面 | 09-26 / 09-23 |
| rubric r1 / 两读 κ | 10-05 |
| Polymarket / 损耗 | 10-09 |
| 翻车面·标签（弱/真实） | 09-26（`strength_balance.underdog_path.strength`，285 行）；09-16..09-27 旧 schema 123 行用牌照 `q2_route` 代理，`upset_label_src` 标明 |

8 月 15 日前后的行只有价格、belief、赛果——那时没有任何结构字段。给历史比赛补做研究会看到赛果，项目纪律（历史回放永不增加前瞻样本、研究原件只读）不允许，本表也没做。

## 用作决策树样本时的三条纪律

1. **只用 `research.prospective=True` 的行学结构特征**（405 行，09-16 起）；None 的行缺采集时刻，不能证明早于开球。
2. **两个 schema 的洞不要混**：v1 的 `side` 是 anchor/underdog/both/none，v2 是 home/away/both/none；`derived.hole_rel` 已统一折算成 fav/dog/both/none，用它。
3. **`belief` 的来源不同**：reads.json（主循环 judgment）、足彩 legs-base（备料时）、corpus-v2（内核 forecast lane）三者的系统偏离幅度不同，`belief.src` 标明；跨来源比较偏离时先按 `src` 分层（10-19 的扫描已看到两条管道对同一窗口的大偏离行数不一致：23 vs 7）。

## 还能做的（都不是新取证）

- 翻车面标签：让 `jczq-match-analyst` 契约把 `underdog_path.{side,strength}` 写成必填字段，从下一场起累计；历史 405 行用 `q2_route` 代理先跑一版树，标明是代理。
- 108 行足彩独有场次与 21 行无身份键的行：补 `store-ids` / 别名表后可并入内核 match_id。
- 每周重跑构建器（`uv run python experiments/decision_samples_build.py`），表随板面增长约 25 行/日。

## 基线结果（2026-10-19，`experiments/decision_tree_baseline.py`）

训练集：前瞻行 n=396（热门实开 59.1% vs 市场均值 53.3%）。目标：市场热门 90' 赢。

**① CART（手写 Gini，5 折分层 ×3）全部输给市场本身**：深度 1/2/3/4 的 CV AUC 0.61/0.64/0.63/0.61，市场 p_fav 连续值 AUC 0.694；Brier 树 0.228–0.249 vs 市场 0.222。全样本拟合树的第一、二层都在 p_fav 上切，结构特征只在叶附近出现，增益 ≤2.3（≈噪声）。

**② 残差检验（市场 logit 重校准 + 单个特征，逻辑回归，5 折 ×5，对数损失）**：市场原值 0.6331 → 只做重校准 0.6262（这一步的改善就是 F10 热门低估）；**22 个特征逐个加入，没有一个让 CV 对数损失低于重校准**（Δ 全部 +0.0003 到 +0.0055）。系数方向稳定（5×5 折同号 =1.00）但无增量的：verdict（+，判 clear 的热门更常赢）、overpriced_fav（−）、drift（+，盘往热门走的更常赢）、confidence（+）、anchor_is_fav（+）、kappa（−）——它们说的东西市场价格里已经有了。

**读法**：n=396 时，研究层的任何一列（锚方、完整度、洞在谁/单位/价内、天平、表态、四问、三证、κ、损耗、PM 成交）都不能在市场价之上改善「热门不翻」的预测；唯一的可学部分是市场整体对热门的低估（重校准），这已在 F10 前瞻中。决策表不加新列；样本表每周重跑，n 翻倍（约 6–8 周）后再跑同一脚本。

## 更正与标签进模型（2026-10-19 10:40）

- 本文与扫描文档早先写「翻车面标签从未编码」是**读错位置**：契约字段是 `strength_balance.underdog_path.{side,strength,routes}`（09-26 起），构建器已改读嵌套位置，原字段 285 行、旧研究代理 123 行。
- **Jun 定必填**：`research_intake._check_underdog_path`——09-26 后的研究缺 `underdog_path` 或 `side∉{home,away}`/`strength∉{none,weak,real,strong}` 报 WARN（不拒收，理由同 rubric：拒收烧预算、留 R0/R1 缺口）；`.claude/agents/jczq-match-analyst.md` 写明必答与三档含义；测试 `tests/decision/test_research_intake.py` 四条。
- 标签进残差检验：`label_real`（real/strong=1）Δ +0.0026、`label_side_is_dog` Δ +0.0049，**与其他 22 个特征一样不改善市场**。分档看：real·b57–64 n=26 热门实开 88.5 vs 市场 59.8（+28.7 ±6.3）是单格最大，但 real·C n=51 +4.9、real·D n=94 0.0，且 26 场的格在 ~60 格里出现一个 4.5σ 的期望不是零——记一笔，不登记。
