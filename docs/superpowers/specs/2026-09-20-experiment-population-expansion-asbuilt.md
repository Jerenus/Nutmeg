# 实验本体对象扩采样 · 竣工说明（2026-09-20）

> 设计原件：`2026-09-20-experiment-population-expansion-design.md`（**含一处已被实测推翻的前提，见 §4.3**）。
> 本文是**竣工版**：描述实际建成的结构、实施中修正的四处设计错误、以及现在被代码保住的不变量。
> 实施提交范围：`8788954 … c54d401`（11 个提交）。

## 1. 问题陈述

RSI 前瞻实验的采样对象与判读产能不匹配。

2026-09-20 实测：竞彩板面 30 场、传统足彩 26131 共 14 场（全部也在板面上），并集 30。
但只有 R0 是 `scope=match` 吃全板，F1c/F2/F9 都是 `scope=day` 且 instrument 硬绑 `--issue {issue}`，
只吃足彩那 14 场。⇒ **当日为 16 场竞彩独有比赛付出的深研成本，不进入任何前瞻实验样本。**

## 2. 核心概念：冻结面 vs 实现面

本次改造的全部设计张力来自一条区分：

| 面 | 字段 | 可变性 | 依据 |
|---|---|---|---|
| **冻结面** | `population` / `falsifier.stratum` / `window` / `buckets` / `stop_rule` / `claim` / `mechanism` | **窗口内不可变**，改＝另立 exp_id | RSI「原件全冻结」 |
| **实现面** | `duties[].scope` / `deadline_rule` / `instrument` / `artifact_glob` | 可修，属工程补齐 | 非判据 |

⇒ **扩采样是否合法，取决于注册表原件怎么写的，而不是取决于我们想怎么采。** 由此得到三类：

- **A 类（扩实现）**：F9、F5 —— 注册表**本来就写** `population: both` / `stratum: pooled`，
  只是 duty 的 instrument 写死了 `--issue`。这是实现缺陷不是判据，可扩。
  F9 窗口 `date_from=2026-09-20` 且 n=0，扩得正当其时。
- **B 类（禁止触碰）**：F2（已 n=11）、F1c、F3、F8 —— 冻结为 `zucai` 且窗口已开。
  要竞彩样本须 **fork 新 exp_id**，样本不得并进原实验的 n。
- **C 类（参照实现）**：R0 —— 已是 `scope=match`，行为须逐字节不变。

## 3. 建成结构

### 3.1 采样域解析器 `nutmeg/decision/rsi_population.py`

单一入口 `matches_for_population(population, *, day, issue, data_dir) -> list[dict]`。

**返回行的统一契约**（六键恒存在，缺失填 `None`，不得缺键）：
```
{match_id, code, match_no, canonical_id, source ∈ {jczq,zucai,both}, unmapped: bool}
```
契约的必要性：下游 `schedule` 要用统一字段构造 duty 实例；字段不齐会在合并后的行上 KeyError。
**duty id 一律用 `match_id`**，不得用 `code`/`match_no`（两者在跨来源行上可能为 `None`）。

**三个 population 的语义**：
- `jczq` → 读 `daily/<day>/jczq-legs-base.json` 的 `legs`
- `zucai` → 读 `<issue>-store-ids.json`；`issue is None` 时返回 `[]`
- `both` → 跨泳道**按身份映射**取真并集；`issue is None` 时**静默降级为 jczq**

### 3.2 跨泳道并集键：`canonical_id` + `channel-map`

⛔**不能用 `match_id` 做并集键**：同一场比赛在两条泳道各有一个 match_id
（竞彩来自体彩板面入库、足彩来自期次入库），直接按 match_id 合并会退化成**相加**。
实测证据：修正前 `both` 返回 **44 行 / 零行 `both`**，修正后 **30 行 / 14 行 `both` + 16 行 `jczq`**。

建成做法：读 `<issue>-channel-map.json`（既有的人工显式映射，`decision-audit-legs --channel-map` 同源），
辅以 `canonical_id`（形如 `M-2026-09-19-埃弗顿-伊普斯`）。**无法映射的行保留原 `source` 并标 `unmapped: true`**
——不静默合并，也不静默丢弃。

此约束并非本次新发明，而是 RUNBOOK B2 的既有纪律：
「按 `zucai-canonical` 键查，**禁用 fair 值反查**」——出生事故 26122 场2/6/7 因同队也在竞彩板上被反查抢错身份。

### 3.3 回放隔离：装在唯一入口

RUNBOOK A7（`25ad896` 写入）：「historical replay 永不增加 prospective R0/F5/F9 样本」。

建成做法：`matches_for_population` 开头检测 `data_dir/replay-input-manifest-<day>.json`，
存在即**对所有 population 返回空**。
设计取舍：**闸门装在唯一入口而非每个消费点** —— 逐出口判断只要漏一个就穿帮，
入口拦截则新增消费者自动受保护。

### 3.4 日期口径：业务日，非自然日

`day` 一律指**业务日**，以板面文件所在目录名为准，**不得按 kickoff 日期重新分桶**。
依据：26131 的 14 场中有 6 场在 09-21 凌晨开球，但全部属于 `daily/2026-09-20/` 一个板面。
按自然日切分会把跨零点比赛整批分错桶。

### 3.5 调度：duty 定义变更后可重建

`scope=match` 的 duty 由 `rsi schedule` 按 `matches_for_population` 的结果**逐场生成实例**。
幂等键须含 duty 集合内容指纹，否则改 duty 后同日无法重排（实测曾抛
`IdempotencyConflictError: rsi-sched:2026-09-20:26131`）。
重排时**重建实例集合**而非仅同步定义；**已 fulfill 的记录保留不得删除**。

## 4. 实施中修正的四处设计错误

设计原件写于实施前，其中四处前提被实跑推翻。记录于此以免后人重蹈。

### 4.1 返回行字段契约缺失
原件只规定各来源返回什么字段，未规定**合并后是否补齐**。
后果：jczq 行无 `match_no`、zucai 独有行无 `code`，下游按任一字段构造 id 即 KeyError。
修正：六键恒存在契约（§3.1）。

### 4.2 回放隔离条款补入过晚
`25ad896` 把隔离条款写进 RUNBOOK 的时间早于本 spec 补入该条款的时间，
实施方若取用较早版本则看不到。修正：§3.3，并在交接提示词中标为 T2/T3/T4 共同约束。

### 4.3 ⛔`match_id` 被误当作跨泳道共同键
**本次最严重的一处**。原件 §3.1 写「`both` → 按 `match_id` 取并集」，
而项目自身 RUNBOOK B2 早已规定身份映射必须显式给出、身份不许猜（26122 出生事故）。
写 spec 时未核对该既有纪律，最终靠实跑数字不符（44 vs 30）才暴露。
后果若未修：F9 把同一场比赛记两次，n 虚高、Brier 双重计数。
修正：§3.2。

### 4.4 ⛔验收条件可被「让数字好看」满足
原件写「`rsi status` 里 F9 的 n 按竞彩全板场数增长」。该表述有歧义，
被实现为**实例数增长**，一度使 F9 在**当日无任何赛果**的情况下显示 `n=44/60`。
F9 测的是 belief≠prior 场次的 Brier vs 市场——**无赛果则 Brier 不存在**，n 只能在
fulfill 且有观察产物后增长。
修正：验收条件改写为「n 由 fulfill 的真实观察产生，`schedule` 不得使 n 增长」。

> 📌**方法论留痕**：验收条件若能被「让数字好看」满足，它就不是验收条件。
> 本次差一步让一个前瞻实验在零观察的情况下达到结账阈值。

## 5. 现在被代码保住的不变量

1. `population`/`stratum`/`window`/`falsifier`/`stop_rule` 在窗口内不可变——B 类四实验实测逐字节未动
2. 跨泳道并集按显式身份映射，不可映射者标 `unmapped` 而非静默处理
3. 回放日对所有 population 返回空
4. `day` 恒为业务日
5. 返回行六键恒存在，duty id 恒用 `match_id`
6. n 仅由 fulfill 产生，schedule 不计数
7. 姊妹实验登记器拒绝 fork 已结账实验，新件写 `forked_from`

## 6. 竣工验收（2026-09-20 12:50 实测）

```
pytest test_rsi_population/test_rsi_wiring/test_cli_rsi  →  34 passed
ruff check nutmeg/ tests/                                →  All checks passed
git diff --stat experiments/registry/                    →  仅 F5.json、F9.json
matches_for_population('both', 2026-09-20, 26131)        →  30 行 {both:14, jczq:16}
rsi status                                               →  F9 n=0/60（真实）· R0 n=30/200
rsi due --day 2026-09-20（无 --issue）                    →  exit=0，标 <需 --issue> 不抛错
```

## 7. 未完成项

- **F5 的 `pending_instrument` 状态**：F5 的 instrument 是 `["TODO", ...]`（采集器未实现，
  按设计不硬凑）。但它已生成 29 条**永远无法 fulfill** 的实例，将持续污染 gap 列表。
  ⇒ duty 需加 `status: pending_instrument`；`schedule` 跳过、`due`/`status` 单列为
  「待实现采集器」而非 gap。**gap 的语义是「该做没做」，不是「还做不了」。**
- **实例数 29 vs 并集 30**：差一场原因未核（疑为开球时间过滤或某场缺 `kickoff_bj`），不得猜。
