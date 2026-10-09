# 球队损耗台账 + F16 赛程负荷实验 · 设计（2026-10-09）

> Jun 2026-10-09：「是否考虑以前 2 周和后 1 周为周期，给每支队伍制定疲劳值参数，作为损耗度的参考？包括球员受伤等」→「直接按照上述思路完成设计和实验登记稿，然后直接开始相关的代码开发」。
> 定位：**测量仪，不是判断参数**。台账只展示、只记账；任何数字进 belief 之前必须先过 F16 前瞻实证（RULEBOOK「〇」同纪律）。

## 1. 现状（2026-10-09 核对）

损耗今天是**逐场、由深研分析员判断**的，没有按球队累计的量：

| 层 | 内容 | 进不进 belief |
|---|---|---|
| 研究 JSON `schedule` | 上一场/下一场/国脚负荷，散文 | 不进 |
| rubric 事实项 | `F_absence_*`（官宣关键缺阵 ≤6pp）、`F_suspension`（4）、`F_rotation`（官宣轮换 3）、`F_goalkeeper`（3） | 进，须官宣来源 |
| rubric 其他 | `O_other_event`（含疲劳/旅途，inferred ≤2pp）、`S_crash_candidate`（带洞/密集/动机两条 ≤2pp） | 很小；`form_state` 单条 ≤1pp |
| store 画像 | `availability_*` / `squad_spine` / `schedule_congestion_*` | 08-20 静态快照 |

「疲劳牌」是 07-04 复盘点名的四种判读偏置之一，故意压低权重。

## 2. 事前证据（2026-10-09 会话内粗测，jc-history 2025-08-15→2026-05-31 × titan007 终盘 sharp fair）

| 量 | n | 主胜残差（实开 − 终盘 fair） | 95% CI |
|---|---|---|---|
| 休息天数差 主−客 ≤−3 | 556 | −0.6pp | [−4.6, +3.1] |
| 相差 ≤2 天 | 2,219 | +1.0pp | [−1.0, +2.9] |
| ≥+3 | 572 | −0.8pp | [−4.4, +2.8] |
| 主 14 天 ≥4 场、客 ≤2 | 58 | −6.4pp | [−18.1, +5.1] |
| 客 14 天 ≥4 场、主 ≤2 | 55 | +0.3pp | [−11.0, +12.1] |
| 国家队窗口后首个周末 · 热门 ≥60% | 72 | +4.4pp（其余日子 +5.3） | [−5.7, +13.9] |

读法：**休息天数差被市场完全定价**（不立假说，只展示）；只有「单边赛程密集」方向像样但 n 太小、且已被看过——所以 F16 的判据在本文冻结，回放只作登记依据，不进判决。

**登记前回放（判据冻结之后跑，同日）**：主判据 n=598 −0.8pp CI[−4.6,+2.9]——零效应；单边密集 n=136 −6.0pp CI[−14.0,+1.7]。不改判据。全文 `docs/superpowers/evidence/2026-10-09-team-load-replay.md`。

## 3. 台账（`nutmeg/decision/team_load.py`）

### 3.1 出场索引
- 来源（全部已在库，零新数据源）：`jczq/jc-history.json`（业务日 + titan 队名）、`jczq/daily/*/sporttery_markets.json`（`matchDate` + 体彩简称/全称，含未来 1–2 天）、`zucai/*-issue.json`（`kickoff_bj` + 500 简称，含未来一周）。
- 身份：队名一律经种子别名表 `resolve_team` → `team_id`；解析不了的用 `name:<norm_team(名)>`（同源仍可对上，跨源对不上＝如实缺失，不猜）。
- 日期：按日（北京）。各源对深夜场的归日不一（业务日 vs 开球日），误差 ±1 天；同一队相邻 ≤1 天的出场视为同一场去重。
- 覆盖缺口（写进每份台账 `coverage`）：只含竞彩/足彩开售场次——没上板的国内杯赛、部分联赛缺失，休息天数会偏长；国家队出场分钟数没有。首次生产运行实测德乙/法乙/北欧多队休 34–56 天（应约 20），展示里赛季中 >30 天标「?」（`GAP_SUSPECT_DAYS`）。

### 3.2 每队特征（对一场开球日 D）
| 字段 | 定义 |
|---|---|
| `rest_days` | D − 最近一次出场（≤ D−2）；无记录 → null |
| `matches_14d` | 出场日 ∈ [D−14, D−2] 的场数 |
| `next_days` | 下一次出场（≥ D+2，≤ D+10）距 D 的天数；无 → null（「后一周」主要用于轮换风险） |
| `long_break` | `rest_days` ≥ 12（长歇后首战，含国家队窗口） |

### 3.3 每场派生
- `rest_diff` = 主 − 客；`load_diff_14` = 主 `matches_14d` − 客。
- `flags`：`单边密集:<side>`（一方 ≥4、另一方 ≤2）、`负荷差≥2:<更密一方>`（F16 触发）、`下场≤3天:<side>`、`长歇:<home|away|both>`。
- 伤停（来自该场研究 rubric，已有数据，不新采集）：`F_absence_*` 答「是」且 p≥0.5 → 缺阵；`F_suspension`/`F_rotation` 的侧 → 停赛/轮换；`S_spine_intact` 答「否」且 p≥0.5 → 锚方中轴缺。

### 3.4 落盘与冻结
- 竞彩 `jczq/daily/<日>/team-load.json`（行键＝编号，`key`＝`<日>-<编号>`）；足彩 `zucai/<期>-team-load.json`（行键＝场号，`key`＝`<期>-<场号>`）——与语料 v2 行键同形。
- 每行带 `captured_at` 与 `kickoff`；**重写时已开球的行原样保留**（前瞻样本不许事后改）。
- 生成：`nutmeg load ledger --day <日> | --issue <期> [--write]`；`research refresh` 旁支自动写（失败只打印，不挡 Read 与本体提交），因此 12:30 / 18:45 判决页刷新与深研之后都会更新。

### 3.5 展示
- 初判包（竞彩、足彩）加一列「损耗」：`休 主/客 · 14天 主/客` + 旗（⚑密＝单边密集，⇢＝下场≤3天，⏸＝长歇）+ 伤停缩写。**只看不拨动**；读法行写明「休息差历史上已被定价」。

## 4. F16 实验（`experiments/registry/F16.json`，Jun 2026-10-09 批准登记，窗口 2026-10-10 起）

- **主张**：两队 14 天内比赛数相差 ≥2 时，比赛更密的一方取胜的实开率低于市场概率（负荷被市场低估）。
- **指标** `loaded_side_resid_pp` ＝ 1{更密一方胜} − fair[更密一方]（pp，bootstrap 95% CI）。
- **样本**：并集池（足彩∪竞彩）、`min_tier=price_only`；行必须挂着开球前冻结的台账（`captured_at < kickoff`）；`|load_diff_14| ≥ 2`。
- **证伪**：n ≥ 150 时 CI 上界 > 0 ⇒ 证伪（`bound=ci_upper, threshold_pp=0, gt_means_falsified`）；60 期内仍跨线按 stop_rule 提 retire。
- **判据冻结在本文**：回放（2025-26，同一模块）只进证据文档，不进判决；登记后不得改触发阈值、窗口、口径（改＝另立新 exp_id）。
- **义务**：`team-load-ledger`（scope=match，截止＝开球，instrument `nutmeg rsi team-load --day {day}`——写台账并为已排的逐场义务履约，与 F5 price-band 同一模式；已开球的场不调用履约）。
- **结账接线**：语料构建把冻结台账挂到行顶层 `team_load`（不进 `labels`，免得虚增「带判读标签」计数）；`rsi_grading.grade_f16_prospective`（登记前不进 `PROSPECTIVE_ADAPTERS`——注册表只收已登记实验）；登记时把它加进 `PROSPECTIVE_ADAPTERS`、F16 加进 `rsi_loop.GRADED_EXPERIMENTS`。
- **登记只许人**：Jun 2026-10-09 批准，`uv run nutmeg rsi register --by Jun experiments/registry/F16.json`（原件一经登记即冻结）。

## 5. 非目标与治理
- 不改 rubric、不改 belief、不改票面；不新增数据源（国家队分钟数、实时伤停接口留待 F16 有结论后再议）。
- F16 survived 之后要接进判断：①证据文档 ②`RUBRIC_CHANGELOG` ③新项 `since` ④上限只许从结账往下调——与 RULEBOOK「九」治理同一流程。

## 6. 实施清单
1. `team_load.py`：出场索引 / 每队特征 / 每场派生 / 伤停摘要 / 台账合并冻结（TDD）。
2. CLI `nutmeg load ledger`；`pool.refresh_day` 旁支自动写，`research refresh` 打印状态。
3. 初判包「损耗」列。
4. `experiments/team_load_replay.py` → `docs/superpowers/evidence/2026-10-09-team-load-replay.md`。
5. 语料挂载 + `grade_f16_prospective`（TDD）；`_draft_F16.json`。
6. RUNBOOK B1/A4 指针、ARCHITECTURE 文档地图一行。
