# Nutmeg Research Knowledge Index

更新时间：2026-08-21（Asia/Shanghai）

## Usage Contract

处理联赛、球队、单场比赛、转会、伤停、磨合、首发连续性或信息纠错时，GPT/Codex 与 Claude 必须先读本索引，再定位相关档案；不得把 chat memory 当成知识来源，也不得只凭文件名猜测哪份档案仍然有效。

本索引是发现与解释层，不是与决策本体竞争的实体数据库。Team/League 的结构化事实仍应通过现有 decision store、`decision-profile` 和 seed 读取与更新。

发生冲突时按以下权威顺序裁决：

1. live decision store 与当前 canonical Match/Snapshot；
2. 当前比赛窗口内更新的官方或一手证据；
3. `nutmeg/data/decision_entities_seed.json` 的策展实体；
4. 本索引中状态为 `active` 的研究档案；
5. 状态为 `superseded` 或 `historical` 的研究档案；
6. chat memory。

即使档案状态为 `active`，具体比赛的转会、伤停、停赛、正式首发和市场 Snapshot 仍须在当前窗口重新采集。研究档案不能绕过“无命名信息面理由则跟市场”的决策纪律。

## Status Vocabulary

| 状态 | 含义 | 允许用途 |
|---|---|---|
| `active` | 可复用的当前联赛/球队本体基线 | 查询、横向比较、生成当前窗口核验清单 |
| `time-bounded` | 只对标注赛程窗口有效 | 当前窗口内准备；过期后只能作为历史证据 |
| `historical` | 比赛或窗口已结束 | 审计、复盘、方法纠错；不得代表当前状态 |
| `superseded` | 已有更新档案替代 | 仅保留证据链；必须转读替代档案 |

## League And Team Ontology Archives

| 日期 | 覆盖范围 | 状态 | 档案 | 主要用途 | 刷新触发器 |
|---|---|---|---|---|---|
| 2026-08-20 | 西甲、法乙、荷乙 League + Team 本体 | `active` | [西甲 / 法乙 / 荷乙本体备料](2026-08-20-la-liga-ligue-2-eerste-divisie-ontology-intelligence.md) | 统一维度比较、实体 ID、名单连续率、近期比赛入口 | 转会窗关闭、正式首发、新的实名伤停或已核实纠错 |
| 2026-08-20 | 意甲、德甲、德乙 League + 56 支 Team 本体 | `active` | [意甲 / 德甲 / 德乙本体备料](2026-08-20-serie-a-bundesliga-bundesliga2-ontology-intelligence.md) | 联赛基线、11 维球队画像、磨合和近期准备队列 | 转会窗关闭、意甲/德甲首轮首发、德乙滚动首发、新的实名伤停或已核实纠错 |

这些档案负责解释结构和证据边界；结构化画像真身仍在 live decision store 与 `nutmeg/data/decision_entities_seed.json`。

## Preparation Queues

| 日期 / 窗口 | 覆盖范围 | 状态 | 档案 | 主要用途 | 失效与复用条件 |
|---|---|---|---|---|---|
| 2026-08-21 至首轮结束 | 英超开幕轮 | `time-bounded` | [英超 MW1 动态情报](2026-08-20-premier-league-mw1-intelligence.md) | 官方赛程边界、覆盖成熟度、首轮待核问题 | 首轮后转为历史；复用前重抓伤停、首发与市场 |
| 2026-08-20 至 2026-08-27 | 西甲、法乙、荷乙未来七日 | `time-bounded` | [三联赛七日准备队列](2026-08-20-la-liga-ligue-2-eerste-divisie-seven-day-prep-queue.md) | A/B/C 分层、临时市场底座、正式首发更新 | 8 月 27 日后转为历史；任何比赛判断须重新进入 canonical Snapshot |

## Fixture Deep Research

| 比赛 / 窗口 | 状态 | 档案 | 主要用途 | 限制 |
|---|---|---|---|---|
| 巴列卡诺 vs 阿拉维斯，2026-08-21 | `historical` | [巴列卡诺 vs 阿拉维斯跨渠道深研](2026-08-20-rayo-alaves-cross-channel-deep-read.md) | 跨渠道继承、赛地异常与无方向性旗的证据样本 | 比赛窗口已结束；当前事实以 settlement/store 为准 |
| 贝蒂斯 vs 皇家社会、敦刻尔克 vs 蒙彼利埃、登博思 vs 埃因FC，2026-08-22 | `time-bounded` | [三场优先比赛深研](2026-08-20-three-priority-fixtures-deep-read.md) | 三场统一状态比较、五玩法初判、证据触发器 | 开赛前必须刷新伤停、正式首发和市场；赛后转为 `historical` |

## Historical Research

| 日期 | 覆盖范围 | 状态 | 档案 | 允许用途 | 限制 |
|---|---|---|---|---|---|
| 2026-06-20 | 突尼斯 vs 日本世界杯小组赛 | `historical` | [Tunisia vs Japan research](2026-06-20-tunisia-vs-japan.md) | 历史伤停、首发、市场研究格式参考 | 不得代表任何当前球队或比赛状态 |

## Correction And Supersession Protocol

- 小型事实修正：在原档案增加带日期的纠错说明、新证据与影响范围；同步更新本索引的刷新说明。
- 实质性替代：新建日期化档案，把旧条目标记为 `superseded`，并在新旧条目中相互链接；不得静默覆盖旧结论。
- 过期准备队列或单场深研：状态改为 `historical`，保留审计价值，但不得继续代表当前伤停、首发或市场。
- Team/League 结构化纠错：先通过 `decision-profile --add-note` 更新 live store，再运行 `decision-entities-sync --write-seed` 回灌 seed；不能只改 Markdown。
- 比赛级判断纠错：落在当前 canonical Read / reconcile / calibrate 链路，不把判断写成永久 Team 事实。

## Registration Checklist

每次新增 `docs/research/*.md` 时必须同时完成：

1. 在正确分类中登记日期、范围、状态、用途、限制和刷新触发器；
2. 使用相对链接，确保档案移动或仓库路径变化后仍可发现；
3. 替代旧档案时执行 supersession 双向链接，不删除审计链；
4. 涉及实体事实时确认 live store 与 seed 是否需要同步；
5. 运行 `uv run pytest tests/decision/test_research_index.py -q`，确认所有研究档案已登记且链接有效。

日常新增档案只修改本索引，不需要反复编辑 `AGENTS.md` 或 `CLAUDE.md`。
