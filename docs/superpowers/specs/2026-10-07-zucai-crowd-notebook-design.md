# 传统足彩·人群偏离笔记本（Crowd Notebook）· 设计

日期：2026-10-07 ｜ 状态：路线 A 与第一、二段已获用户批准，第三段随本文交审 ｜ 后续：writing-plans
依赖：`2026-09-18-rsi-experiment-persistence-design.md`（RSI 实验对象，已落地）、
`2026-09-19-zucai-structure-lane-design.md`（face_status / tiers / 枚举器；本文是它的修订与前置）

## 0. 一句话

足彩是奖池均分游戏：edge 不来自「我比真相准」，只能来自「我和人群分开的地方人群是错的」。
本设计给系统一本**老彩民的笔记本**：每条人群偏离假说用人话写、用谓词触发、按 RSI 结账；
机器从「人群比例 vs 赛果」的残差里提名，人签字后才登记；线索（Clue）进初稿为 advisory，
证实（deploy）后才成为枚举约束。**逐场本体继续做底料，但对足彩只交校准 P 与事实层否决。**

## 1. 为什么改（记分牌证据）

| 期 | 逐场处方 | 票面 | 死因层 |
|---|---|---|---|
| 26103 | 14/14 | 8/9 | 结构（第五个更好的理由） |
| 26104 | 13/14 | 全版本同死 | 结构（牌照单选） |
| 26098 | 12/13 | 钱票全灭 | 结构（先砍全包后砍裸单） |
| 26123 | 14/14 | 8/9 | 结构（全包名额换一格即 +29,255） |
| 26133 | — | 两票全灭 | 结构（两票共享两裸单，联合同死≈60%） |

逐场判断力相对市场 ≈ 0：F14 训练行 −1.4pp≈市场；F9 belief≡prior；403 天 gym 无策略族 ROI 为正。
奖金由 top2 覆盖率与板面冷热决定（26121/26120/26123），热板帽内无盈利结构两连证，
P4「硬币密度→高奖金」被自身数据证伪（26112–26123 四期系统性错向）。
**结论：足彩的可证伪空间只剩人群分布层，而仓里目前没有任何逐场人群数据（只有期级销量）。**

## 2. 用户裁定

| # | 裁定 |
|---|---|
| N1 | 「人性的偏离」= **投注人群（奖池对手）**的系统性偏爱；不是场上的人、不是 Jun、不是分析者 |
| N2 | 运行方式 = **老彩民的笔记本**：假说人话可读、每期找实例、赛后自动记账、假说有生死 |
| N3 | 假说来源 = **机器提名，人签字**；机器自主生成/淘汰（Dream 路线）不做 |
| N4 | 实现路线 = **A**：挂在 RSI 实验层，不另起账本，不出现双权威 |
| N5 | `p_cal` 用**校准后的市场 P**，不用研究判断（判断层 ≈ 市场，刻意不用） |
| N6 | falsifier 口径 = 触发实例内 **Brier(crowd) − Brier(p_cal)** 的 CI 下界；零假设「人群和市场一样准」 |

## 3. 范围

本 spec：`CrowdMap` 数据对象与采集器、`Hypothesis`（RSI H 前缀实验）扩展字段与 trigger DSL、
`Clue` 事件流、泳道 B 七个接点、`crowd` 命令面（fetch/scan/settle/nominate）、H0 奖金实验、
种子候选假说、26103–26135 回放回填（若源可回取）。
不在本 spec：竞彩人群（固定赔率游戏，edge 逻辑不同）、热板空仓新规则（由 H0 结果自然导出）、
枚举器本身的实现（09-19 spec）、宪法字典序措辞（用户的事）。

## 4. 对象

### 4.1 `CrowdMap`（`.nutmeg-data/zucai/<issue>-crowd.json`，快照追加不覆盖）

```
{
  "issue": "26136",
  "sales_rj": null | int,                       ← 赛后由 zucai_official 补
  "snapshots": [
    {"taken_at": "2026-10-09T09:05+08:00", "source": "500.usr", "lane": "B0|prep14|shift1830|manual",
     "matches": [
       {"match_no": 1, "crowd": {"3": 61.2, "1": 22.0, "0": 16.8},
        "p_cal":  {"3": 58.0, "1": 23.5, "0": 18.5},
        "gap":    {"3": 3.2,  "1": -1.5, "0": -1.7},
        "p_src": "market:avg_eu@500 data-pjgl|titan007 closing", "cal_rule": "cal-2026-09-26"}
     ]}
  ],
  "ex_post": {                                  ← crowd settle 写
    "results": "3103...", "prize_rj": 1234.0, "winners_rj": 5678,
    "crowd_product_win": 0.0123,                ← ∏ crowd(中奖面) 用最后一张快照
    "predicted_winners": 70000.0,               ← sales_rj × crowd_product_win × κ（κ 为单式等效系数，见 §7 H0）
    "anchor_median_12": 2975.0
  }
}
```

- `crowd` 三面和必须在 [99, 101]，否则该场 `crowd=null`，不猜不补。
- `p_cal`：市场口径三路概率（去水后）→ 校准修正表 `cal-2026-09-26`（60–80% 热门 +6~8pp，<20% 冷门 −3pp，其余不动；表为 RULEBOOK 常量，改动走 `rsi deploy`）。来源优先级：titan007 终盘 > 500 `data-pjgl`；缺则 `p_cal=null`，`gap=null`。
- 人群比例源：500.com 交易页「本站用户投注比例」（JS 异步填充，接口与历史可取性待工程验证——计划第 1 任务）。它是**500 用户样本**，不是全国奖池；这是已知偏差，H0 正是检验它是否仍有信息。

### 4.2 `Hypothesis` = RSI 实验，`exp_id` 前缀 `H`

在 09-18 登记原件之上新增字段（`label_cn`、`trigger`、`action` 进 `FROZEN_FIELDS`；`psychology`、`examples` 不进）：

```
"exp_id": "H1", "layer": "structural", "population": "zucai", "tier": "candidate|observation|deploy_eligible",
"label_cn": "人群追大牌客场",
"psychology": "大牌崇拜 + 怕漏全中：一场大牌客场若不买客胜，整张票心理上就「废了」",
"trigger": {"all": [
   {"field": "gap.0", "op": ">=", "pp": 15},
   {"field": "away.tier", "op": "in", "v": ["big_name"]},
   {"field": "league", "op": "in", "v": ["英超","西甲","德甲","意甲","法甲"]}
]},
"action": {"role": "fade", "face": "0"},            ← fade | join | cover
"examples": {"pos": ["26120 场11 …"], "neg": ["26121 场3 …"]},
"falsifier": {"metric": "brier_crowd_minus_pcal", "stratum": "triggered", "n_min": 30,
              "bound": "ci_lower", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
"stop_rule": "连续 3 期零触发则 window 顺延；n≥60 仍 inconclusive 则 retire 提案",
"window": {"issue_from": "26136", "n_min": 30}
```

**trigger DSL（封闭集合，不扩展就不许写）**
- 组合：`all` / `any` / `not`，可嵌套一层。
- `field`：`gap.{3|1|0}`、`crowd.{3|1|0}`、`p_cal.{3|1|0}`、`gap_shift.{3|1|0}`（快照③−快照①）、`league`、`home.rank`/`away.rank`（联赛积分榜位次，来自 500 `[n]` 标注）、`home.tier`/`away.tier`（store 画像 `big_name|promoted|other`）、`asian_line`（亚盘盘口，带正负）、`match_no`、`board.hot_count`（p_cal 任一面 ≥65 的场数，板面冷热）。
- `op`：`>=` `<=` `==` `in` `not_in`。
- 实例粒度 = (issue, match_no, face)；一条假说在一场最多触发一次。

**role 语义（对 09-19 枚举器）**
- `fade f`：面 f 不得占全包名额；若 f 是 alive 单面候选则降为「需要盖住」。
- `join f`：允许面 f 做单面（仅当 face_status 其余面为 dead/never 或矩阵级别允许）。
- `cover`：该场优先取全包格。
- 三者在 `tier<deploy_eligible` 或未 `deploy` 时仅为 **advisory**（初稿 ⚑ 显示，不改前沿）。

### 4.3 `Clue`（事件流 `.nutmeg-data/zucai/<issue>-clues.jsonl`，不进内核）

```
{"issue":"26136","match_no":7,"face":"0","exp_id":"H1","snapshot":"prep14","gap":17.3,"crowd":52.1,"p_cal":34.8,
 "role":"fade","advisory":true,
 "acted":null|"followed"|"ignored"|"overridden",      ← B9c 对账时填
 "outcome":null|"hit"|"miss",                          ← crowd settle 填（面 f 是否开出）
 "brier_crowd":null,"brier_pcal":null}
```
同一 (exp_id, match_no, face) 只保留最后一张快照的行作为结算行；早期行留作位移审计。

### 4.4 候选池 `experiments/candidates/H-cand-<n>.json`

`crowd nominate` 产出；字段 = 假说原件的草稿 + `evidence: {n, dir, brier_diff, examples}` + `nominated_at`。
**候选不触发 Clue、不进内核**；签字 = 人把它改名为 `H<k>.json` 放进 `experiments/registry/` 并 `rsi register`。

## 5. 每期流程（泳道 B 七个接点）

| 时点 | 现有步 | 新动作 | 产出 |
|---|---|---|---|
| 早 | B0 早刷新 | `crowd fetch <issue> --lane B0`：快照①，算 p_cal/gap | `<issue>-crowd.json` |
| 14:00 | 备料 | 快照②；`crowd scan <issue>`：active 假说 trigger 跑过板面 → Clue | `<issue>-clues.jsonl` |
| B5 | `judgment draft` | 初稿新增「**人群地图**」节：人群最挤三场（gap 最大）/ 我们分开的位置（Clue + role）/ 分开的代价（覆盖该面多花的注数与 P 损失 pp）；枚举器读 Clue：deploy 后为约束，否则 ⚑ advisory | 初稿 md/json |
| 18:30 | 位移 diff | 快照③；`gap_shift` ≥5pp 的场重跑 scan；Clue 新增/消失进 diff | diff md |
| 出票 | B9c 实票登记 | `betslip register` 对账：每条 Clue 填 `acted`；票面登记不被拦（永不拦登记） | Clue |
| 赛后 | day.settle | `crowd settle <issue>`：ex_post 块；Clue 填 outcome/Brier；RSI grade（H 系列 + H0） | RSI 账 |
| 复盘 | `retro encode` | `crowd nominate <issue>`：残差聚类 → 候选 json + 人话一段；**只提名不登记** | candidates/ |

**三条边界**
1. Clue 在字典序里位于第三序以内：事实层否决（face_status dead）→ 帽内结构 → 分开指数。它不能判死 alive 面，不能越过刹车/止损/日帽。
2. 判决全走 RSI：`verdict` 只读 CI；`deploy` 只许人。证实前「看得见线索，不被牵着走」。
3. 热板空仓不加新规则：H0 证实后，「预测奖金 < 门槛 → 空仓」由 B5 读 ex_ante 预测奖金自然得出；门槛沿用现行部署门的中位口径。

**提名算法（`crowd nominate`）**
- 输入：所有已 settle 的 Clue 行 **以及**未被任何假说触发的 (issue, match_no, face) 残差行（gap 绝对值 ≥10pp）。
- 分桶：`league × face × sign(gap) × rank_band(home/away ∈ {1-4, 5-12, 13+}) × asian_band`；每桶统计 n、`mean(brier_crowd − brier_pcal)`、方向一致率。
- 候选门：n ≥ 8 且 brier 差 > 0 且方向一致率 ≥ 70%；每次最多提名 3 条，按 n×差值排序。
- 人话段由模板生成（`label_cn` 草稿 = 「人群在 <league> 对 <面> 的 <高估/低估>（<rank_band>）」），`psychology` 留空给人写。
- 任何桶与已登记假说 trigger 重叠 ≥50% 实例的，不再提名（避免同义假说刷 n）。

## 6. 种子候选（首批放进 candidates/，不登记；每条零假设 = 人群≈市场）

| 草稿 | 来源 | 预期方向 |
|---|---|---|
| 人群低估平局（gap.1 ≤ −8pp 的场平局频率 vs p_cal） | 冷板 7 平/14（26123、26122）；排平 4/4 对而裸 3 胆 2/6（26112） | 人群平局厌恶 |
| 人群追大牌带洞正路 | 「大牌带洞正路 6/6 全胜标签全失效」（26120）——**注意这是反例：人群可能是对的** | 待数据，可能 join |
| 人群排除面（被排面）开出 | 被排面七连（26109）、26118 第 10 例 | 人群过度排除 |
| 国家队情结（中国/大牌国家队主场 gap.3 ≥ 15pp） | 26135 场1 国足；国家队本体 10-06 | 人群追本国/大名 |
| 升班马主场人群低估 | 「升班马刀三把」（26118）、强锚×升班马=平局 2/2（26122） | 待数据 |

种子只给方向不给结论；全部要等 H0 过门后才可能登记。

## 7. H0：人群比例有没有信息（登记原件随计划第 1 任务一并写）

- claim：`log(predicted_winners) − log(actual_winners_rj)` 的绝对误差，显著小于 12 期滚动中位锚换算出的等效误差 `|log(anchor_median_12) − log(prize_rj)|`。
- `predicted_winners = sales_rj × ∏ crowd(中奖面) × κ`，κ 为单式等效系数（人群买复式使有效注数 ≠ 销量/2），在回放窗（26103–26135）上拟合一次后冻结，前瞻期不再动。
- falsifier：`metric = log_err_diff`，`n_min = 12`（回放可立刻给 ~30），`bound = ci_upper`，`threshold = 0`，`direction = gt_means_falsified`。
- **H0 证伪 ⇒ 500 用户比例对奖池无信息 ⇒ H1+ 全部停在候选，本设计止步于数据层**（笔记本仍可记，但不接枚举器）。
- H0 成立 ⇒ ex_ante 预测奖金进入 B5 初稿第一行，替代中位锚。

## 8. 命令面

```
nutmeg crowd fetch   <issue> [--lane B0|prep14|shift1830|manual]   # 采集快照 + p_cal/gap
nutmeg crowd scan    <issue> [--snapshot last]                     # 触发 active 假说 → Clue
nutmeg crowd settle  <issue>                                       # ex_post + Clue 结算 + RSI grade
nutmeg crowd nominate <issue|--all>                                # 残差聚类 → candidates/
nutmeg crowd map     <issue> [--format md|json]                    # 人群地图（初稿「人群地图」节复用）
nutmeg crowd backfill --from 26103 --to 26135                      # 历史回填（源可取时）
```
全部幂等、只追加；`--format json` 的 stdout 只放结构化结果。接入 launchd 现有三条（B0/14:00/18:30）与 day.settle，**不新增 plist**；Telegram 只在「Clue 新增且 deploy 级」时推（只推需要 Jun 动作的事）。

## 9. 失败处理

| 情形 | 处理 |
|---|---|
| 500 页 WAF/空响应/比例列为 `-` | 快照缺失，记 `snapshots[].status="missing"`；不猜不补；初稿「人群地图」节写「本期无人群数据」 |
| 三面和不在 [99,101] | 该场 `crowd=null`；scan 跳过；settle 不计 |
| p_cal 源缺失 | `gap=null`，所有含 gap 的 trigger 不触发 |
| 中途改 trigger | 走 `rsi amend` → 新 frozen_hash → 历史 Clue 保留 `exp_hash`，结算只累计同 hash 的行 |
| 票面登记时 Clue 文件缺失 | 登记照常，`acted` 留 null（永不拦登记） |
| 场次作废（`*`） | 该场 Clue `outcome="void"`，不入 n |
| 延期/改期 | 以体彩业务日与官方赛果串为准（沿用 zucai_official） |

## 10. 测试

- 单元：trigger DSL 评估（含 `not`/嵌套/字段缺失）；gap 与校准表；三面和校验；Brier 两项；H0 对数误差；提名分桶与重叠剔除；Clue 去重（最后快照为结算行）。
- 回放 fixture：26123（冷板 7 平，¥30,407）与 26120（极热板 ¥145）两期人工录入的比例快照 → 期望 ex_post、Clue 与 H0 行。
- 集成（`/verify`）：沙盒副本上跑 `crowd fetch→scan→map→settle→nominate` 全链，确认只追加、幂等、不动内核非 RSI 表；`judgment draft` 含「人群地图」节；`betslip register` 在 Clue 缺失时仍成功。
- 契约：H 系列原件过 `rsi_prereg.load_registry_doc`；`FROZEN_FIELDS` 扩展后旧实验哈希不变（回归测试）。

## 11. 与现有文件的关系

- `docs/sop/RUNBOOK.md` 泳道 B：B0/B4/B5/B9c/settle 各加一行指针；`RULEBOOK.md` 新增「十、人群偏离假说」节：校准表常量、trigger DSL 字段集、role 语义、advisory/约束切换条件。
- `2026-09-19-zucai-structure-lane-design.md`：§4.2 `tier` 增 `crowd_clues` 输入；枚举器 role 约束的读法在那边实现。
- `docs/ARCHITECTURE.md`：判断层与 rubric 之后加「人群层」一节与一张图（mmdc 校验）。
- 记忆：positioning 与 strength-v2 不变；本设计是「足彩专项」的前置数据层。
