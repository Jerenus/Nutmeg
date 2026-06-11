# JCZQ 世界杯 2026 专题改造 — 设计文档

> 日期:2026-06-11(世界杯开幕日)
> 状态:已与用户逐节确认
> 关联:spec §32(jczq-today 单一入口)、§30(校准元规则)、§25-§35(tiered 引擎)
> 前置事实:6/09 已接入 API-Football 国际欧赔主源 + 86 国家队别名表

## 0. 背景与目标

2026 世界杯(6/11-7/19,美加墨,48 队 12 组 104 场)期间,体彩竞彩盘面以世界杯
赛事为主。现有 `jczq-today` 管线不改即可对世界杯场次出投注决策,但用户要的是
**世界杯预测专题工具**:在投注决策之上叠加赛事级预测(出线/晋级/夺冠概率),
并在**每次完成决策后**产出一份美观可理解的 PDF 每日分析报告。

### 已确认的需求决策

| 决策点 | 用户选择 |
| --- | --- |
| 核心定位 | 专题层叠加:投注决策为核,新增赛事级预测,合成世界杯日报 |
| 报告载体 | PDF(复用 ReportLab CJK 管线)推 Telegram |
| 预测深度 | 全赛事蒙特卡洛:48 队评级 + 整届模拟 + 每日概率变动 |
| 架构 | **方案 B:改造现有管线**(单一入口 jczq-today 内扩展,不另起入口) |
| §3 调整 | 模型加深(攻/防两维 Elo + 东道主加成 + 伤病信号)+ 每日校准闭环 |
| §5 调整 | 视觉升级(matplotlib 图表 + 杂志级排版)+「今日主线」叙事段 |
| §6 调整 | SOP 驱动为主 + 20:00 兜底推送 + 复盘 PDF + 出包时间适配世界杯 |

### 硬约束(沿用既有纪律,一条不破)

- tiered 引擎 A/B/D/E 选腿规则、R 规则、§24 汰留、档位定性**零改动**。
- 决策包确定性:同输入同输出。蒙特卡洛随机种子 = f(run_date),replay 可复现。
- 禁嘴算:报告里一切概率/edge 数字来自引擎落盘文件,不允许 agent 现场估算。
- 空仓合法、B/D/E 纯方差娱乐定性在报告中保留呈现。
- CLAUDE.md 与 AGENTS.md 的 SOP 改动必须同步双写。

## 1. 总体架构与数据流

`jczq-today` 仍是唯一决策入口,管线内扩展两步,新增一个渲染命令:

```
nutmeg jczq-today(launchd 12:00)
  1. Sporttery 快照                       [现状]
  2. API-Football 欧赔(主)+ 500.com(备) [现状]
  3. tiered 引擎 A/B/D/E                  [现状,零改动]
  4. 世界杯层:赛果摄取 → Elo 更新 → 校准日志 → 确定性蒙特卡洛   [新]
  5. today-packet.md 新增 §E 赛事预测                            [新]
        ↓
agent 读包、答 §C → 写 judgment-answers.json                     [新约定]
        ↓
nutmeg jczq-report --date today --dispatch-telegram --no-dry-run  [新命令]
  → 合成 PDF 世界杯日报 → 推 Telegram
```

代码组织:新逻辑全部放 `nutmeg/services/worldcup/` 子包,`jczq_today.py` 只加
一段世界杯层调用(门控见 §9)。「改造现有管线」指接入点在管线内、保持单一入口,
不指把模拟器代码写进核心文件。

```
nutmeg/services/worldcup/
├── __init__.py        # is_wc_active(run_date) 门控 + 对外门面
├── tournament.py      # 赛制静态数据加载、出线规则、对阵映射
├── results.py         # 从 fixtures 快照摄取世界杯赛果
├── ratings.py         # 攻/防两维 Elo + 欧赔锚定 + 伤病调整
├── calibration.py     # 每日模型 vs 赛果校准日志
├── sim.py             # 确定性蒙特卡洛(纯函数)
├── packet_section.py  # §E 渲染(markdown)
├── report_data.py     # 日报数据模型合成(读各落盘文件)
├── charts.py          # matplotlib 图表生成(PNG bytes)
└── report_pdf.py      # ReportLab 排版(复用 jczq_final_plan_pdf 字体基建)
```

落盘目录:

```
.nutmeg-data/jczq/wc2026/
├── results.json           # 已完赛场次(append-only)
├── ratings.json           # 当前攻/防 Elo 状态(含历史版本数组)
├── calibration-log.jsonl  # 每日校准记录
└── sim-{date}.json        # 当日模拟产出(供次日算变动)
.nutmeg-data/jczq/daily/{date}/
├── judgment-answers.json  # agent 裁量作答(新约定)
└── wc-daily-report.pdf    # 当日 PDF 日报
```

## 2. 赛制与数据层(`tournament.py` / `results.py`)

### 2.1 静态赛制文件 `nutmeg/data/wc2026_tournament.json`

- 48 队:`team_id`(API-Football 英文名,与 `jczq_national_team_aliases.json` 对齐)、
  中文名、小组、FIFA 排位种子。
- 12 小组 A-L;104 场赛程槽位:`match_id`、阶段(group/r32/r16/qf/sf/third/final)、
  日期(UTC)、对阵(小组赛为实队,淘汰赛为槽位引用如 `1A`/`3ACD`)。
- 32 强对阵映射:每组前 2 的固定槽位 + 8 个最佳第三按 FIFA 官方分配表
  (依据"哪 8 个组出第三"的组合查表)。
- 小组排名细则:积分 → 净胜球 → 进球 → 相互战绩 → 公平竞赛分 → 抽签
  (抽签步骤在模拟中以确定性伪随机替代)。
- 落库方式:实施时从 FIFA 官方赛程整理,**人工校验过的静态 JSON 提交进仓**,
  不依赖运行时抓取。

### 2.2 赛果摄取(`results.py`)

- **复用**每天 `jczq-today` 已经调用的 `fetch_fixtures_by_date` 产出(同一次
  API 配额,不新增调用):从 fixtures 快照中筛出世界杯已完赛场次
  (status=FT/AET/PEN),归一化为 `{match_id, score_90, score_final, outcome,
  penalties}` 追加到 `results.json`(按 match_id 幂等去重)。
- 淘汰赛区分 90 分钟赛果与最终晋级结果:**竞彩盘口 = 90 分钟赛果**,平局是
  有效投注结果;Elo 更新用 90 分钟赛果,晋级判定用最终结果。
- 渲染层在淘汰赛场次自动加一行提示:「淘汰赛盘口=90分钟,平局有效」。

## 3. 实力评级与模拟器(`ratings.py` / `sim.py` / `calibration.py`)

### 3.1 攻/防两维 Elo

- 每队维护 `(atk, def)` 两维评分。初始种子 `nutmeg/data/wc2026_elo_seed.json`:
  从公开国家队 Elo 快照一次性落库(实施时取数,人工校验,提交进仓),按
  「Elo → 平均攻防拆分」初始化(atk = def = elo/2,首轮后自然分化)。
- 期望进球:`λ_home = base_goals × f(atk_home − def_away) × host_boost`,
  f 为指数映射,系数在实施时用近两届世界杯+近年国际赛回测定标,**定标过程
  与结果写进校准日志,不拍脑袋**。
- 东道主加成:美国/加拿大/墨西哥在本国境内比赛时 `host_boost` 生效
  (默认 +0.1 λ 量级,回测定标);中立场地不加成。
- 赛后更新:用 90 分钟赛果按进球差加权的 Elo 增量更新 atk/def,K 系数
  世界杯期间取高值(短赛会、样本少、状态权重大)。

### 3.2 伤病信号(轻接入)

- API-Football `/injuries` 端点按 fixture 拉当日参赛队伤病名单(新增调用,
  仅当日参赛队,配额可控)。
- 只做**降级信号**:当日伤病名单缺席 ≥3 人时对该队 atk、def 各临时折减 5%
  (本场有效,不写回 Elo 状态;阈值与折减幅度随校准日志可调)。不做球员级
  建模——样本太薄,避免过拟合。失败/无数据时静默跳过,记日志。

### 3.3 市场锚定(优先级最高)

- 当天有真实 de-vig 欧赔的场次,模拟**直接用市场概率**(市场 > 模型);
  Elo 模型只负责欧赔覆盖不到的假想对阵(淘汰赛远期分支)。
- 锚定同时反哺评级:市场概率与模型概率差距过大(>15pp)时在校准日志记
  一条 `model_market_gap` 警示,连续触发则提示重定标。

### 3.4 确定性蒙特卡洛(`sim.py`,纯函数)

- 输入:赛制数据 + 已完赛果 + 当前评级 + 当日市场锚定概率 + seed。
- `seed = int(hashlib.sha256(run_date.encode()).hexdigest()[:8], 16)`——同日
  重跑/replay 完全一致。
- 单场:λ 双边 Poisson 采样比分 → 胜平负;淘汰赛 90 分钟平局 → 加时(按
  λ×1/3 再采样)→ 仍平则点球(50/50 基础 + Elo 差微调,上限 60/40)。
- 整届:从「当前真实状态」(已完场次用真实赛果,未完场次模拟)推演到决赛,
  N=20,000 次。numpy 向量化(随 pandas 已有,不新增依赖),目标运行 <10s。
- 产出 `sim-{date}.json`:每队 P(小组出线/32强/16强/8强/4强/决赛/夺冠) +
  metadata(seed、N、评级版本、锚定场次清单),并算对昨日 sim 文件的变动。

### 3.5 每日校准闭环(`calibration.py`,§30 元规则的世界杯分册)

- 每日赛果摄取后自动追加 `calibration-log.jsonl`:每场记
  `{date, match_id, model_p, market_p, outcome, brier_model, brier_market,
  lambda_pred, goals_actual}`。
- 滚动指标:模型 Brier vs 市场 Brier、λ 残差均值。**单日只入账不改模型**;
  累计 n≥15 场且模型显著跑偏(λ 残差 |均值|>0.3 或 Brier 落后市场 >0.05)
  时,在 today-packet §E 顶部渲染 🟨 校准警示,提示人工重定标——沿用 §30
  「桶不够不改模型」纪律,防止单日噪声驱动 churn。

## 4. 决策包扩展(§E)与裁量答案落盘

### 4.1 today-packet.md 新增 §E 世界杯赛事预测

- 内容:夺冠概率 top10(含对昨日变动 ↑↓)、今日参赛队的小组出线形势、
  淘汰赛阶段则加「今日晋级焦点」、校准警示(若触发)。
- §A-§D 原样不动;§E 数字全部来自 `sim-{date}.json` 落盘文件。
- §C 裁量问题新增一类世界杯场景:`Q_WC_KNOCKOUT_{match_no}`(淘汰赛在售
  场次,提醒 90 分钟口径并问该场平局保护决定)。派生逻辑仍是确定性枚举。

### 4.2 judgment-answers.json(新约定)

```json
{
  "date": "2026-06-12",
  "answers": [
    {"q_id": "Q_SOFTHOT_周四001", "decision": "keep", "confidence": 4,
     "reason": "欧赔同认,无分歧信号"}
  ],
  "agents": ["claude"],
  "final_note": "一句话总结",
  "answered_at": "2026-06-12T14:30:00+08:00"
}
```

- agent 答完 §C 后用 Write 写入;多 agent 时合并 answers 并在分歧场次标
  `divergent: true`(沿用「分歧=减注」约定)。
- `jczq-report` 读它合成报告;缺失时报告照出,裁量节标注「裁量未作答」。

## 5. PDF 世界杯日报(`jczq-report` 命令)

### 5.1 命令

```bash
uv run nutmeg jczq-report --date today [--dispatch-telegram --no-dry-run]
```

输入:当日 tiered-plan + judgment-answers.json(可缺)+ sim 当日/昨日 +
calibration-log + 昨日 tiered-plan-review.json(可缺)。输出
`wc-daily-report.pdf`,可选推 Telegram(复用现有 bot 管线,发 document)。

变体标志:`--if-missing`(当日已有 PDF 则跳过,供 20:00 兜底)、
`--review-pdf`(只渲染 1-2 页迷你战报:昨日命中/盈亏 + 概率变动,供
08:00 复盘任务)。

### 5.2 视觉与排版

- 新增依赖 `matplotlib>=3.9,<4`(图表生成 PNG bytes 嵌入 PDF);中文字体
  复用 `jczq_final_plan_pdf.py` 已探测的宋体/STHeiti/PingFang 路径,
  matplotlib 与 ReportLab 共用同一字体文件。
- 杂志级排版:封面色带 + 阶段角标、双栏卡片票面、图表占半页;统一配色
  (世界杯主题色 + A/B/D/E 档位各自固定色)。
- 图表四件套(按阶段自动取舍):
  1. 夺冠概率 top10 横向条形图(当日 vs 昨日对比双条)
  2. 夺冠概率趋势线(开赛以来逐日,前 6 名)
  3. 小组积分/出线热力表(小组赛阶段)
  4. 淘汰赛对阵树(淘汰赛阶段,标注每支队晋级概率)

### 5.3 版面七节

1. **报头** — 🏆 日期 · 赛事阶段(小组赛第 X 轮/16 强…)· 赛程进度条
2. **今日主线** — 一段人话叙事:盘面共识 + 看点,「翻面读法」风格(不利
   信号翻面读成今晚盘面共识);由模板 + 当日信号确定性拼装,非 LLM 生成
3. **今日看点** — 当日**全部**世界杯场次(不限竞彩在售)+ 模型/市场胜平负
   概率;竞彩在售场次高亮;淘汰赛标 90 分钟口径
4. **投注决策** — A/B/D/E 票面卡片 + §C 裁量结论 + 注金合计;档位定性文案
   照印(B/D/E 纯方差娱乐、空仓合法)
5. **赛事预测** — 图表四件套 + 概率变动榜(谁暴涨谁出局)
6. **昨日战报** — 票面命中/盈亏 + 模型 vs 市场 Brier 简报(校准闭环可视化)
7. **尾注** — 数据来源、娱乐预算纪律、生成时间与种子(可复现凭据)

「今日主线」实现细节:`report_data.py` 内置约 10 个叙事模板(满盘热门日/
冷门夜/淘汰赛生死战/概率大迁移日等),按当日信号(热度分布、概率变动幅度、
阶段)确定性选模板填槽,保证同输入同文案。

## 6. 自动化与 SOP

### 6.1 launchd 节奏(世界杯适配)

世界杯比赛多在北京时间凌晨至上午开球,竞彩当晚停售;且有「早场快照漏晚挂
盘」的历史教训。节奏定为:

| 时间 | 任务 | 说明 |
| --- | --- | --- |
| 12:00 | `jczq-today`(现状任务不动) | 出决策包(世界杯层已含) |
| 18:00 | `jczq-today --refresh-check`(新) | 重抓盘面;若新增场次→重出包+Telegram 提示「盘面有更新」;无变化则静默 |
| 20:00 | `jczq-report --if-missing`(新) | 当日 PDF 还没生成过才跑,标注「裁量未作答」,保证每天必有报告 |
| 08:00 | `jczq-tiered-review` + `jczq-report --review-pdf`(扩) | 复盘照旧出文字版,并加一份迷你 PDF 战报(昨日命中/盈亏+概率变动) |

`--refresh-check`:对比已存 sporttery 快照的场次集合,只在集合变化时重写
包并推送提示,避免覆盖派发文件的旧 bug 重演(沿用 §26 replay 不写盘教训)。

### 6.2 SOP 更新(CLAUDE.md + AGENTS.md 同步双写)

「今天的方案」SOP 在步骤 4(答 §C)之后新增:

> 5. 答完 §C 后,把作答写入
>    `.nutmeg-data/jczq/daily/{date}/judgment-answers.json`(schema 见 spec §4.2),
>    然后跑 `uv run nutmeg jczq-report --date today --dispatch-telegram
>    --no-dry-run` 推送当日 PDF 世界杯日报。这是「完成决策」的收尾动作,不可省。

原步骤 1-4 与档位定性、数据纪律段不动。

## 7. 错误处理

- API-Football 缺赛果/伤病接口失败 → 该队评级暂不更新/不折减,模拟照跑,
  日志记录;连续 2 天摄取不到任何赛果 → §E 顶部渲染 🟥 数据降级警示。
- 别名缺失(世界杯不该发生,86 队表已覆盖)→ 沿用现有「该场缺席、绝不猜测」。
- sim 文件缺失(首日无昨日对比)→ 变动列渲染「—」;昨日 review 缺失 →
  战报节标注「待复盘」。
- matplotlib 字体探测失败 → 图表退化为 ReportLab 原生简表,报告必须能出。
- `--replay` 全程兼容:世界杯层读已存快照,不发任何网络请求。

## 8. 测试计划

- `tournament.py`:出线规则(含最佳第三 8 选官方分配表)、对阵映射、排名
  细则平局分支 —— 用构造小组赛果穷举关键分支。
- `ratings.py`:Elo 更新方向/幅度、东道主加成只在境内生效、伤病折减只影响
  单场、市场锚定优先级。
- `sim.py`:同种子同输出(确定性)、概率和为 1、已完赛场次不被重新模拟、
  淘汰赛点球路径可达。
- `calibration.py`:Brier 计算、n<15 不触发警示、跑偏触发警示。
- `packet_section.py` / `report_data.py`:§E 渲染快照测试、叙事模板选择
  确定性、judgment-answers 缺失容错。
- `report_pdf.py`:PDF smoke test(生成非空 bytes、节标题齐全)、字体缺失
  降级路径。
- CLI:`jczq-report --if-missing` 幂等、`--refresh-check` 集合不变不写盘。
- 预估新增 60-80 个测试;现有 jczq 测试全量回归通过为合并门槛。

## 9. 退役门控

- `is_wc_active(run_date)`:`2026-06-11 ≤ date ≤ 2026-07-19` 且当日赛程/
  在售盘面含世界杯场次。门控外,管线行为与今日完全一致(§E 不渲染、不跑
  模拟、jczq-report 提示「无世界杯赛事」)。
- 7/19 之后零拆除成本;worldcup/ 子包保留,为未来大赛(亚洲杯/欧洲杯)
  复用留底。

## 10. 实施切分(供 writing-plans 参考)

1. 赛制静态数据 + tournament.py + 测试(可独立验收:出线规则正确)
2. results.py + ratings.py + calibration.py + 测试
3. sim.py + 确定性验证 + 性能验证
4. §E packet 接入 + Q_WC_KNOCKOUT + judgment-answers 约定
5. charts.py + report_pdf.py + jczq-report CLI
6. launchd 四任务 + SOP 双写 + 端到端演练(用开幕日真实盘面)
