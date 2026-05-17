# Dixon-Coles 模型校准 — 设计文档

- **日期**：2026-05-17
- **状态**：设计待用户评审
- **目标**：让冲突引擎的 Dixon-Coles 模型产出**可信**的预期进球 —— 能真正区分强弱队、计入主场优势 —— 从而让"模型 vs 市场"成为真实信号，而非系统性 fade 热门。
- **前序**：[[2026-05-17-nutmeg-consolidation-design]] §7。整合改造已让冲突引擎实时通路打通，但模型失准，引擎产出的 edge 不可用。

---

## 1. 问题与证据

冲突引擎 = `ValueBoardService`：模型概率 vs 国际市场公允概率 → edge。整合后首次实跑（2026-05-17，20/34 场对齐），模型在 **14 场冲突表里 13 场都 fade 市场热门** —— 不是 13 个 edge，是同一个模型 bug。

**探针实测**（`expected_goals_from_snapshot`）：

| 比赛 | 窗口 | 主队 xg_for/场 | 客队 xg_for/场 |
|---|---|---|---|
| 热那亚(主) vs AC米兰(客) | 近 5 场 | 1.04 | 1.13 ← 噪声抹平成等强 |
| | 近 20 场 | 1.17 | 1.62 |
| | 整季(36) | 1.27 | **1.71** ← AC米兰明显更强 |
| 里昂(主) vs 朗斯(客) | 近 5 场 | 1.89 | 2.51 |
| | 整季(33) | 1.64 | **2.19** |

## 2. 根因（两个，均已确诊）

**根因 ①：球队实力只用最近 5 场估计。**
`nutmeg/services/value.py` `_evaluate_fixture` 调 `snapshot_service.build_snapshot(fixture_id, recent_matches=5)` —— 写死 5 场。`expected_goals_from_snapshot` 的主分支 `recent-xg-matchup` 读 `matchup.home_trend/away_trend` 的 `xg_for_per_match` 等，这些 trend 就是那 5 场的均值。5 场是纯状态噪声：强队冷一阵看着像弱队、弱队热一阵看着像强队。探针证明：热那亚/AC米兰在 5 场窗口被抹平（1.04≈1.13），拉到整季就正确分开（1.27 vs 1.71）。

**根因 ②：`recent-xg-matchup` 分支无主场优势项。**
公式：`home = (home_attack + away_defense) / 2`、`away = (away_attack + home_defense) / 2`（`nutmeg/models/dixon_coles.py:254-258`）。完全没有 home advantage。主场优势在欧洲主流联赛约值 +0.3~0.4 球/场；缺这一项 → 系统性低估主队。里昂/朗斯即便整季 朗斯 xg(2.19) 仍高于里昂(1.64)，里昂之所以是市场热门很大程度靠主场 —— 模型看不见。

## 3. 方案 —— 分阶段，精简优先

遵循整合设计 §5 的硬原则（精简、不堆约束）。**Stage 1 精简修复**直击两个确诊根因；**Stage 2 强度比模型**仅在 Stage 1 验证不达标时才做（届时另起 spec）。

### Stage 1（本 spec 范围）

**改动 1 — 拉大实力估计窗口。**
`value.py` 新增模块级常量 `_STRENGTH_WINDOW_MATCHES = 38`（覆盖最长的欧洲联赛赛程；快照服务对样本不足优雅截断 —— 探针 n=38 实得 sample=33/36，行为已验证）。`_evaluate_fixture` 把 `recent_matches=5` 改为 `recent_matches=_STRENGTH_WINDOW_MATCHES`。

> 注：`build_board`（非 `_for_fixtures` 路径）若也调 `build_snapshot` 须一并改为同一常量，保持两条路径一致。

**改动 2 — 给 `expected_goals_from_snapshot` 加主场优势项。**
`nutmeg/models/dixon_coles.py` 新增模块级常量 `_HOME_ADVANTAGE = 1.18`（主场进球倍率；对应客场 `1 / 1.18 ≈ 0.847`，使两队总进球期望大致守恒，仅在主客之间再分配）。两个分支都应用：

- `recent-xg-matchup` 分支：
  `home = (home_attack + away_defense) / 2 * _HOME_ADVANTAGE`
  `away = (away_attack + home_defense) / 2 / _HOME_ADVANTAGE`
- `season-xg-per-match` 回退分支：把现有的魔法数 `1.08 / 0.92` 统一替换为 `_HOME_ADVANTAGE / (1/_HOME_ADVANTAGE)`，去掉散落的魔法数、口径一致。

`_HOME_ADVANTAGE = 1.18` 的依据：欧洲主流联赛主队约占全场进球的 ~55%，客队 ~45%，比值约 1.22；取 1.18 略保守。该值设为具名常量，便于 Stage 2 或回测后调参。

**不改的部分（精简）**：`(攻 + 对手防)/2` 这个平均式结构本身不重写 —— 在去噪输入 + 主场项之后它对 Stage 1 够用。`DixonColesLiteModel` 的定价（score grid / rho / 让球 / 总进球）不动。冲突桥、串关构造器、注金阶梯不动。

### Stage 2（本 spec 范围外，条件触发）

若 Stage 1 验证（§5）仍显示模型系统性 fade 热门，则把 `expected_goals_from_snapshot` 重写为联赛归一的强度比模型（`home_xg = 联赛主场均值 × 主队攻击强度 × 客队防守弱度`，强度 = 队均率 / 联赛均值）。届时另起 spec，需引入联赛均值基准数据源。**本期不做。**

## 4. 受影响文件

- `nutmeg/models/dixon_coles.py` —— 加 `_HOME_ADVANTAGE` 常量；`expected_goals_from_snapshot` 两个分支应用主场项。
- `nutmeg/services/value.py` —— 加 `_STRENGTH_WINDOW_MATCHES` 常量；`_evaluate_fixture`（及 `build_board` 路径若有）把 `recent_matches=5` 改为常量。
- `tests/test_dixon_coles*.py` —— 新增/扩充 `expected_goals_from_snapshot` 的单元测试（见 §6）。
- `tests/test_value_service.py` —— 若断言了 `recent_matches=5` 的调用值，同步更新。

## 5. 验证 —— 本期的验收标准（最关键）

模型"可信"必须可度量。验收 = 用 **2026-05-17 当天数据**重跑冲突引擎并断言：

1. **不再系统性 fade 热门**：对当天每场已对齐比赛，取模型的 `match_winner` 最高概率方向，与市场最高隐含概率方向比较。校准前 ~1/14 一致（~7%）；**校准后要求 ≥ 60% 一致**。
2. **概率与市场正相关**：当天各场模型 P(主胜) 与市场隐含 P(主胜) 的 Pearson 相关系数 **> 0.5**（校准前应接近 0 或为负）。
3. **edge 收敛**：冲突引擎产出的 strong 级 edge 数量显著下降 —— 从"几乎每场都有"变成少数零星场次。

实现计划须包含一个轻量校准检查脚本/测试，对 §5.1、§5.2 给出数值。达不到 → 触发 Stage 2，不强行宣布完成。

> 诚实声明：通过 §5 验证只代表模型**不再明显失准**、可进入 OBSERVE 实绩验证；不代表模型有真实预测力。真实预测力仍由注金阶梯按累积 ROI 实测裁定（自我验证设计）。

## 6. 测试策略（TDD）

- `expected_goals_from_snapshot`：构造受控 snapshot —— (a) 强攻击主队 vs 弱防守客队 → 主队预期进球明显更高；(b) 同一对阵交换主客 → 主场项使主队侧更高；(c) 主场优势项被实际应用（断言含 `_HOME_ADVANTAGE` 的预期值）；(d) `season-xg-per-match` 回退分支同样应用主场项。
- `value.py`：断言 `_evaluate_fixture` 用 `_STRENGTH_WINDOW_MATCHES` 调 `build_snapshot`（fake snapshot_service 记录入参）。
- 全量 `uv run pytest tests/` 保持绿。
- 校准检查（§5）：可作为一个带真实/录制数据的脚本或显式测试；不连真网跑 CI。

## 7. 风险与原则

- **精简**：Stage 1 只加 2 个具名常量 + 改公式两处，不重写模型、不动定价与下游。
- **保持绿**：每步 `pytest` 全绿。
- **不超前**：Stage 2 强度比模型仅在验证不达标时做，另起 spec。
- **可证伪**：§5 给硬性数值门槛；达不到就如实说没校准好，不宣布虚假完成。
- 窗口拉大使 soccerdata 抓取量上升，但 soccerdata 本地缓存，可接受。

## 8. 成功标准

- `expected_goals_from_snapshot` 对强弱悬殊对阵产出明显分化的预期进球，且计入主场优势。
- 2026-05-17 重跑：§5.1 ≥ 60%、§5.2 > 0.5、§5.3 edge 明显收敛。
- 全量测试绿。
- 达标 → 冲突引擎可进入 OBSERVE 阶段（小注/纸面起步，注金阶梯按实绩放量）；不达标 → 触发 Stage 2。
