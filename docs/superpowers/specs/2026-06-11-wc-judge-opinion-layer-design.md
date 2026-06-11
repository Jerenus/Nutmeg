# 世界杯日报「今日判定」评判员层 — 设计文档

> 日期:2026-06-11(当晚,首份日报反馈驱动)
> 状态:已与用户确认
> 关联:`2026-06-11-jczq-worldcup-2026-design.md`(主 spec,本文是其观点层增补)
> 驱动反馈:首份日报"没有明确观点……纯按概率支撑永远选不出答案",用户要的是
> "明智、了解球、有独立判断能力的评判者"的大胆预测(memory:wc-report-bold-opinion-feedback)

## 0. 核心认知与决策记录

观点与注金是两个产品:投注纪律(空仓合法/零 edge 定性/禁嘴算)为**钱**设计;
预测观点的问责方式是**记分牌**,不是钱包——观点层大胆是零成本的,含糊才是输。

| 决策点 | 用户选择 |
| --- | --- |
| 观点与钱的关系 | 记分牌 + 每日一张评判员票(小额独立记账) |
| 观点来源 | 方案 A:Agent 评判员(人味判断,引擎概率只是证据;schema 留双评判员扩展位) |
| 机器代判 | 不做。评判员缺席日如实标注,不用 argmax 凑数 |

**不动的东西**:tiered 引擎、§A 票面、§C 裁量、空仓纪律、¥100 注金体系全部原样;
评判员票 ¥15 与引擎注金永不合账。

## 1. 落盘约定 `predictions.json`

路径:`.nutmeg-data/jczq/daily/{date}/predictions.json`,agent 在答完 §C、写完
judgment-answers.json 之后写(SOP 第 6 条扩展)。

```json
{
  "date": "2026-06-12",
  "judge": "claude",
  "picks": [
    {"fixture": "墨西哥 vs 南非", "match_id": "M01", "match_no": "周四001",
     "judgment": "home", "score": "2-1",
     "reason": "阿兹特克主场+对手中场出球弱,边路爆点足够撕开",
     "confidence": 4, "upset_flag": false, "baseline_pick": "home"}
  ],
  "champion_pick": {"team": "Argentina", "reason": "一句话看球逻辑"},
  "opinion_ticket": {"match_no": "周四001", "market": "had", "pick": "home",
                     "odds": 1.85, "stake_yuan": 15},
  "written_at": "2026-06-12T14:30:00+08:00"
}
```

字段规则:
- `picks` 覆盖**当日全部世界杯场次**(不限竞彩在售);`judgment` ∈ home/draw/away
  (90 分钟口径);`score` 为 "h-a" 字符串;`confidence` 1-5;`reason` 写看球逻辑
  (阵容/状态/风格相克/大赛经验),不写概率复读。
- `match_id` 能对上 `wc2026_tournament.json` 就填(记分走世界杯赛果);
  `match_no` 仅在售场次有(评判员票引用它)。
- `baseline_pick` = 判定时刻的市场最热门(欧赔 fair 最高方;无欧赔用体彩最低
  had 方),**写入时冻结**,防记分时偷看(lookahead)。
- `opinion_ticket`:当日信心最高(≥4)的在售场次单关,¥15 固定;无在售场次或
  无信心 ≥4 的判定时为 null,空缺也如实记。每天至多一张。
- `judge` 字段为双评判员扩展位:未来 GPT 版写 `"judge": "gpt"` 的同构文件
  `predictions-gpt.json`,首版只实现 claude 单评判员。

模块:`nutmeg/services/worldcup/predictions.py` — dataclass + validate + 容错
load(对齐 jczq_judgment_answers.py 的约定:缺失/损坏 → None + 日志)。

## 2. 记分模块 `worldcup/judge_ledger.py`

### 2.1 对账时机与数据

次日 08:10 任务(已有 com.nutmeg.jczq.wc-review-8am 的 `jczq-report --review-pdf`
路径)顺带执行:读昨日 `predictions.json` + `wc2026/results.json`(90 分钟赛果),
逐 pick 对账。

### 2.2 记分口径

每个 pick 产出一条 ledger 记录:
- `judgment_hit`:judgment == outcome_90
- `score_hit`:score 与 90 分钟比分全中(AET/PEN 场次 goals_90 不可知 → 比分
  记 null,只记胜平负;outcome_90 必为 draw)
- `baseline_hit`:baseline_pick == outcome_90(同口径基线)
- `upset_hit`:upset_flag 且 judgment_hit 且 judgment != baseline_pick
  (预警了爆冷且爆了)
- 评判员票:按 odds × stake 结盈亏(命中 +stake×(odds−1),不中 −stake)
- 赛果未出(凌晨未踢完/摄取延迟)→ pick 挂起,后续日对账时补结(幂等:
  ledger 按 (date, fixture) 去重)

### 2.3 ledger 与累计指标

追加 `wc2026/judge-ledger.jsonl`(一行一 pick + 一行 ticket 结果)。累计指标由
读取函数现算(不存中间态):判定命中率 / 比分命中率 / 爆冷查准率(upset_hit /
upset_flag 总数)/ 评判员票累计盈亏,全部与 baseline 命中率并列。评判员缺席日
记一条 `{"date": ..., "absent": true}`,不入分母但公示缺席天数。

## 3. PDF 版面变化(report_pdf.py / report_data.py / charts.py)

- **「今日判定」升为第 2 节**(报头之后):原「今日主线」叙事并入该节导语。
  每场一行:大字判定 + 比分 + 一句理由,信心用 ★×n,爆冷预警行用红色 `[爆冷]`
  角标(NutmegCJK 缺 emoji/特殊字形,一律 ASCII/CJK 安全字符,主 spec 教训)。
- **冠军 pick 框**:与模拟概率并排——"模拟:西班牙 19.3% 居首;本席 pick:
  阿根廷——{reason}"。观点与模型公开对峙,是特性不是 bug。
- **「昨日战报」加记分牌**:昨日判定 X/Y、比分 Z 中、爆冷命中、评判员票盈亏、
  累计命中率折线(matplotlib 小图:评判员 vs 基线两条线)、缺席天数。
- **迷你战报(--review-pdf)**同步加记分牌摘要。
- **20:00 兜底版**:predictions.json 缺失 → 该节渲染"今日评判员缺席(裁量与
  判定均未作答,本报告为自动兜底)"。

`report_data.py` 的 `DailyReport` 增加 `predictions: Predictions | None` 与
`ledger_summary: LedgerSummary | None` 字段;`build_daily_report` 读盘组装。

## 4. SOP 第 6 条扩展(CLAUDE.md + AGENTS.md 双写)

第 6 条 a/b 之间插入新步骤(原 b 顺延为 c):

> b. 以评判员身份写
>    `.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/predictions.json`(schema 见
>    worldcup spec 观点层 §1):当日**每场**世界杯比赛给明确判定+比分+看球逻辑
>    理由+信心;**要敢偏离市场**,理由写球不写概率;当日信心最高(≥4)的在售
>    场次出评判员票(单关 ¥15);冠军 pick 明确到一支队,换 pick 要写理由。

## 5. 错误处理

- predictions.json 缺失/损坏 → 日报该节标缺席,记分牌照常渲染历史累计;
- 对账时 results 缺该场 → 挂起补结,不误判为 miss;
- ledger 损坏行 → 跳过 + 日志,不崩对账;
- 评判员票引用的 match_no 当日票面赔率缺失 → 盈亏记 null 并标注"赔率未存,
  人工补结"。

## 6. 测试计划(预估 25-30 个)

- predictions schema 校验/容错加载/judge 扩展位;
- 记分:judgment/score/baseline/upset 四种命中的真值表、AET 场次比分 null、
  挂起补结幂等、缺席日不入分母;
- 票盈亏:命中/不中/赔率缺失三分支;
- 渲染:判定节快照、缺席降级、记分牌折线 PNG 非空、冠军 pick 框;
- SOP diff 双写一致性(沿用主 spec 验法)。

## 7. 实施切分(供 writing-plans 参考)

1. predictions.py 模型+校验+容错 + 测试
2. judge_ledger.py 对账+累计指标 + 测试
3. report_data/report_pdf/charts 渲染接入 + 测试
4. jczq-report 管线挂记分(--review-pdf 路径触发对账)+ SOP 双写 + 端到端演练
