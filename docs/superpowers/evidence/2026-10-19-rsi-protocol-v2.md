# RSI 深度审核 → 判决协议 v2 · 实验组合重整 · rubric r2（2026-10-19）

**触发**：Jun 问「RSI 相关的设计还有什么值得优化和进一步设计的环节」。三路只读审计（代码 / 统计设计 / 运维）+ 主循环复核关键数字。
**裁定（Jun 2026-10-19 原话）**：「1，冻结原文为准。2，可以。3，可以。4，也需要登记，作为正样本。 开始工作」。
**计划**：`docs/superpowers/plans/2026-10-19-rsi-protocol-v2.md`。

## 1 审计发现（已核实）

| # | 发现 | 证据 |
|---|---|---|
| 1 | `Falsifier.evaluate` 不读 `bound`：一律「上界 < t 证伪 / 下界 ≥ t 成立 / 其余跨线」。F10/F11/F14/F15/K1/R0/R1 的原文与结构化字段都是「CI 下界 < t 即证伪」 | `nutmeg/ontology/rsi/models.py`（修前 129–145） |
| 2 | 到期后每天重判＝可选停止：F14 10-12..10-15 四天 inconclusive，10-16 n=132 翻 survived；10-14/10-15 同 n=120 两个 CI（行序依赖） | 内核 `rsi_verdicts` × `rsi_grades` |
| 3 | F14 的 survived 量到的是热门低估：209 成员 151 个表态集合＝市场同尺寸 top-k | 下表 |
| 4 | 判决回不到决策：judgment 层永不能 deploy，闭环仍天天提示「待人决定 rsi deploy」；deploy 全仓只改 CR 线索图标 | `rsi_actions.py`、`rsi_loop.py`、`crowd_clues.py` |
| 5 | T13 治理断：RULEBOOK「九」规定 propose_zero → 上限退役，但注册表强制权重 0、真上限在 `rubric_items.py`，闭环判「不需动作」——rubric 11 项 9 项 propose_zero、F_rotation 反号，上限照旧拨动 | `factor_registry.py:79`、`rsi_loop.py`（修前 `_collect`） |
| 6 | F18 有适配器不在结账清单（10-15 开窗后 n=0）；F19/R0/R1/F8 无适配器 | `rsi_loop.GRADED_EXPERIMENTS` |
| 7 | F 适配器不查 `provably_prospective`（F9 有 7/219 证明不了） | `rsi_grading.py` |
| 8 | F9 竞彩泳道 `belief_moved` 拿 belief 比「当前 fair」：17:15 刷新/终盘替换后没拨动的 Read 也算拨动（16/160） | `experiments/corpus_build.py`（修前 603） |
| 9 | grade 幂等键只含 inputs_hash：适配器改了重放旧 grade；输入 A→B→A 时判决读到 B | `cli/rsi.py`（修前 1130） |
| 10 | 10-06 定的 F14/F10/F15/K1 修正案与 F13 退役 13 天未进内核（`rsi_amendments` 只有 09-19 的 3 行） | 内核 |

**F14 复算**（209 个冻结成员，主循环 2026-10-19 复算，脚本思路：对每场算表态集合与市场同尺寸 top-k 的「命中 − 覆盖」）：

| 口径 | 残差 pp | 95% CI |
|---|---|---|
| F14 原口径（逐场 iid） | +6.95 | [+1.63, +11.83] |
| F14 原口径（按日聚类，14 天） | +6.95 | [+2.58, +11.68] |
| 机械市场 top-k | +5.18 | [−0.22, +10.24] |
| **表态 − top-k 逐场配对** | **+1.77** | **[−2.85, +6.56]**（按日聚类 [−1.59, +6.00]） |
| 其中表态偏离市场的 58 场 | +6.38 | [−11.26, +23.12] |
| 20 种行序下原口径 CI 下界 | 1.34 … 1.69 | （判决可以只由行序翻转） |

## 2 判决协议 v2（代码，裁定 1）

- **按登记的 bound 判**：lt → CI[bound] < t 证伪、下界 ≥ t 成立；gt → CI[bound] > t 证伪、上界 ≤ t 成立；其余跨线。
- **单次结账**：「累计 n 场结账」＝在**首次 n ≥ n_min 的那份 grade**（结算 grade）上判一次；已有 v2 判决再调 → 拒绝（「已结账」）。冻结原文写了第二次结账的（CR2「60 期仍跨线则提 retire」）按 `SECOND_LOOK_N` 再判一次。旧协议的每日判决行保留作历史，v2 判决快照带 `protocol=v2-frozen-text`、`settlement_n`、`settlement_graded_at`。
- **CI 只取决于样本集合**：残差先排序再自助，`_rows_hash` 按 key 排序。
- **前瞻门**：依赖判断的实验（F9/F11/F13/F14/F14b/F18/K2）只收 `provably_prospective is True`（K2 另要侧车 `prospective`）；`training_pool` 读历史分层时显式关掉。
- **新登记默认按日聚类**（`_cluster_boot_ci`）；未结账的旧实验不中途换尺子。
- **监测**：结账后只有 `MONITORS`（F9，只能测出「拨动有害」）继续每日 grade；其余已结账/已退役的 `rsi grade` 直接跳过。
- **覆盖守卫**：每个登记原件必须落在 结账 / 不结账（写原因）/ 已关闭 三处之一（`tests/decision/test_rsi_loop.py`）；`rsi status` 对内核里未退役、未结账、又不在两份清单里的实验打 ⚠️。

## 3 v2 重判（结算 grade 是当时内核里的记录，不重算）

| 实验 | 结算 grade | 登记的判据 | v2 判决 | 原文写明的后果 |
|---|---|---|---|---|
| F14 | 2026-10-12 n=77 CI[−3.61, +14.05] | 下界 ≤ 0 证伪 | **falsified** | 表态面不比价格准 → 另立 F14b |
| F11 | 2026-10-17 n=80 CI[−35.14, +0.07] | 下界 < 0 证伪 | **falsified** | **C19 永久退休**；翻车识别目标在现有方法下视为不可达 |
| F9 | 2026-10-10 n=71 CI[−1.77, +0.23] | 上界 < 0 证伪 | inconclusive（不变） | 之后只做有害监测 |
| K1 | 2026-10-08 n=223 CI[+84.32, +92.96] | 下界 < 40 证伪 | survived（不变，合并 κ） | 另立 K2（逐项 κ） |

## 4 实验组合（裁定 3）

| 实验 | 动作 | 为什么 |
|---|---|---|
| F5 | 退役，**义务照跑** | 冻结窗口 26129–26140 已过、两层各 n≥120 未达；`price-band-*.json` 仍被日报漂移列读 |
| F8 | 退役 | 无结账仪 30 天 n=0；被测的三证门 09-26 已退休 |
| F13 | 退役 | 10-06 已定（`crash_markers` 自由文本，严格口径一月 1 行） |
| F15 | 退役 | 与 F10 同一主张（14 行里 12 行也在 F10）；看 F10 的 ≥0.70 分层 |
| F16 | 退役，**义务照跑** | 有效样本 1%（206 行 2 行满足），到期约 2 年；损耗台账仍被初判包读 |
| G1 | 退役 | 主张 ROI>0 但判据是「上界 < −5% 证伪」，主张与判据不一致；约 430 天到期 |
| R0 / R1 | **不退役**，转运维覆盖率指标 | 它们的义务（`research run`）驱动每日深研，退役会停掉研究 |
| F18 | 接进结账清单 | 适配器早已写好 |
| F19 | 不结账（写原因）→ **10-20 接入结账**（§8） | 价内/未价只在分析包 §1 手写，未对象化 |
| F10 / F17 / CR2 | 保留 | |
| **F14b**（新） | 登记 | 表态偏离市场排序的场，与同尺寸 top-k 逐场配对，按日聚类 |
| **K2**（新） | 登记 | 逐项 κ 按项次加权（K1 合并 κ 被词表异质抬高：合并 0.78 vs 逐项加权约 0.43） |

## 5 出口与观察型（裁定 4）

- 登记原件可选字段 `exits`（不进冻结哈希）：`on_survived / on_falsified / on_expired`，动作封闭：`rubric_cap:<项>` / `rule:<码>` / `retire_rule:<码>` / `packet_column:<列>` / `display_only` / `none`。
- **没写出口的照样登记**（`rsi register` 打印「观察型」），作为正样本积累；判决触发出口动作的记录同样计作 RSI 闭环的正样本。

<a id="rubric-r2"></a>
## 6 rubric r2（裁定 2）

T13 逐项结账（`uv run nutmeg rsi weights propose --factor rubric_<项>`，2026-10-19 重跑，严格＝可证前瞻样本；observed＝项成立时效应面实开 − 市场价，pp）：

| 项 | r1 上限 | 严格 n | observed pp | 置换 p | 地板判定 | 提案 | r2 |
|---|---|---|---|---|---|---|---|
| F_absence_home | 6 | 160 | +3.8 | 0.59 | indistinguishable | propose_zero | **0** |
| F_absence_away | 6 | 154 | −3.4 | 0.62 | indistinguishable | propose_zero | **0** |
| F_suspension | 4 | 136 | +9.5 | 0.04 | above_floor（两窗不同号） | hold | 4（保留） |
| F_rotation | 3 | 79 | −14.1 | 0.01 | above_floor | propose_change −14.1（与效应方向相反） | **0** |
| F_goalkeeper | 3 | 109 | −1.0 | 0.78 | indistinguishable | propose_zero | **0** |
| F_venue | 2 | 176 | −3.1 | 0.07 | indistinguishable | propose_zero | **0** |
| O_other_event | 2 | 146 | −10.5 | 0.05 | indistinguishable | propose_zero | **0** |
| S_spine_intact | 3 | 148 | +10.2 | 0.24 | indistinguishable | propose_zero | **0** |
| S_underdog_path | 2 | 154 | +0.7 | 0.91 | indistinguishable | propose_zero | **0** |
| S_draw_mode | 2 | 175 | +29.6 | 0.04 | indistinguishable | propose_zero | **0** |
| S_crash_candidate | 2 | 153 | −15.3 | 0.15 | indistinguishable | propose_zero | **0** |

- 治理：RULEBOOK「九」——propose_zero → 该项上限退役；propose_change 只许往下截（F_rotation 的提案方向与效应相反，往下截到 0）。
- 读法：propose_zero 是「n 够了而测不出」，不是「证明为零」；但这些上限本来只有 2–6pp，测不出的效应在钱上也不重要。同期 F9（拨动 vs 市场 Brier）v2 结算 inconclusive、10-19 读数 −0.55pp CI 上界 +0.06；决策树基线（`2026-10-19-decision-samples-v1.md`）22 个研究特征无一降低对数损失——与「拨动≈噪声」一致。
- 两读 κ（审计复算，n 加权逐项 κ ≈ 0.43）：S_dead_face ≈0、S_draw_mode 0.09、S_underdog_path 0.12、M_facts_priced 0.12、O_other_event 0.17、S_crash_candidate 0.32 低于 0.4——四项带效应的已在本版退役上限；M_facts_priced 仍把事实层 pp 减半（只剩 F_suspension），列入 K2 之后的重写清单。
- 实现：`Item.cap_until="r2"`、`cap_at()`、`directional_items(version)`（聚合）与 `EFFECT_ITEMS`（T13 照测）；问题表一字未改，`SUPPORTED_VERSIONS=(r1, r2)` 两版答案一起结账；派生 tilt 的 `derived_from` 记聚合用的版本（改判是 `rubric:r2+override`）。
- 后果：新研究只有 F_suspension 能拨动 belief，其余场次 belief＝市场。

## 7 留给后续批次（10-19 当日已在 `2b4797b5` `3025fa87` `cdf9d787` 做完）

待决收件箱（固定 ID、积压天数、默认动作）、T13 rubric 因子提案改成可执行的「cap→0」、分析包列标「实证/未证」、闭环步骤依赖门控、F1c/F2 死代码、过期告警去重、`as_of` 时区比较、样本账只追加+锁、语料不每日进 git、`decision_samples_build` 走单一来源、ARCHITECTURE §5 / /observe / method 页刷新、账房主次指标（`account.py`，与未提交的止损改动同文件，另提交）。

## 8 2026-10-20 补：F19 对象化与孪生行研究标签

**F19 接入结账**（`rsi_grading.f19_class` / `grade_f19_prospective`，移出 `UNGRADED`）。按 10-16 冻结原文机械化：

- 总体：研究 `strength_balance.underdog_path` 标「真实」且写了弱方的场（语料新字段 `underdog_side` / `underdog_strength`）；标弱另计不入。
- 翻车面：研究表态里不是热门胜的那一面（face 先、cover 次）；没有＝分析包的「—」，不计。
- 位移：`<期>-odds-intl.json` 的 `micro.drift_*_pp`（语料新字段 `intl_drift_pp`，三面齐才出键，不补 0），弱方面＋平；没有国际盘＝「?」，不计。
- 未价＝研究答 `priced_in=false` ∧ 洞在热门 ∧ 位移 ≤ 0；其余（含位移 ≥ +1pp）价内。
- 判据①「路径依据全部早于开盘」不是数据字段，无法机械判：它只会把场判成价内；与未价三条同时成立的场按未价记（研究自己答了未价）。这是实现对原文的唯一取舍，写在这里。
- 指标：价内组「命中 − 市场 P」均值，市场 P＝legs-base 18:30 重建的 zgzcw 去水（停售前最后一版）；逐行自助（F19 登记早于 v2 的聚类约定）；依赖研究 → `PROOF_GATED`。未价组残差进 `cost_axis_pp` 作对照；样本账只冻结价内组。
- 出口（非冻结字段，10-20 补）：survived → `display_only`；falsified → `rule:F19-label-to-probability`（原文「把标签接回概率层重议」，进收件箱）；expired → `none`。
- 首读（10-20 沙盒，窗 10-17 起）：n=15，−8.3pp CI [−27.7, +13.1]，距 n_min 35。按 10-11 n=90 的形状预期这条会跨线或成立，现在读不出。

**孪生行丢研究标签（既有缺陷，10-20 修）**：足彩场的深研多数走板面通路（channel-map 映射到竞彩编号，研究落在竞彩日目录），而 `dedupe` 遇到孪生只留足彩行、丢掉竞彩行——足彩行自己没有研究文件时，研究标签整个没进语料。10-10 起 65 场如此。修法：`_adopt_twin_research`——孪生可证前瞻、足彩行没有研究标签时并入，legs-base 的旗/完整度优先，记 `research_from`。

影响（同一天的源文件，HEAD 代码 vs 修后，全语料不经样本账）：

| 实验 | HEAD | 修后 | 说明 |
|---|---|---|---|
| F9 / F10 / F17 | 195 / 71 / 13 | 不变 | 不读研究标签 |
| F18 | n=1 | n=2（两组共 27 行入账） | 窗 10-15 起 |
| F19 | n=0 | n=15 | 新适配器 |
| F14（已结账） | n=159 +8.5pp | n=224 +6.9pp [+1.7, +11.9] | v2 已判，不重判 |
| F11（已结账） | n=79 −6.4pp | n=107 −8.2pp [−25.0, +7.2] | v2 已判，不重判 |

F14/F11 是在少了这批行的语料上结账的。v2 只判一次，判决不改；F14 指标本身混着热门低估（§2），复算的 +6.9 不是判断力证据，由 F14b 接替的理由不变。F14b / K2 窗口 10-20 起，从第一天就吃到修后的语料。

结账时点反事实（10-20 源文件，按「判前一天及以前的行、首次 n ≥ n_min 那天」重放）：

| 实验 | 缺 65 场（HEAD 代码） | 补全后 | 判决 |
|---|---|---|---|
| F14 | 10-11 n=64 +8.5 CI [−1.0, +16.7] | 10-11 n=70 +5.7 CI [−4.0, +14.2] | 两种都 falsified |
| F11 | 未够数（n=79 < 80；生产经样本账冻结成员够数） | 10-17 n=85 −12.2 CI [−30.1, +5.5] | 两种都 falsified |

补全数据不改判决。开窗中的实验（F18/F19/F14b/K2）不用人工处理：补回的行入选由机械规则决定、研究写于开球前，次日 `rsi grade` 自动入账；原先以竞彩键入账的成员经 `twin_keys` 认作同一身份，不重复计。冻结行不改成最新状态（漂移只记事件）；本缺陷是「该进的没进」，没有错入的行要撤回。

