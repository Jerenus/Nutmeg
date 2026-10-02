# 判断 rubric 契约 r1 · 设计（类型化问题 + 协议级聚合 + 逐项结账）

日期：2026-10-02 ｜ 状态：Jun 2026-10-02「可以，开始」，本文为定稿草案，§9 接线以探查结果为准 ｜ 后续：writing-plans → 实施
依赖：研究表态契约（2026-09-23）、strength-v2（2026-09-26）、T13 因子注册表、RSI 闭环、语料 v2、2026-10-01 定位（机器＝风控官+账房+实验员）。
参考：Jev（TypeSafe，2026-09，类型化问题→概率+置信度，不生成文本）；HealthBench（逐例二值标准、负分项、评分器被评测）；Rubrics as Rewards；《Reward Hacking in Rubric-Based RL》（部分满足复合项 36%、把没说的当成说了 35%、粒度错配 29%；90% 标准是"有没有写到"）；协议级 rubric（分阶段、组内合取、一票作废）；Anthropic 评测指南（代码能判的先用代码，每维度单独裁判，kappa<0.4 的标准删）。

## 0. 一句话

研究层不再交一段散文加一个 `stance`，而是对**一张固定的类型化问题表**逐项作答（每项：选项、概率、来源、采集时间、可弃权），belief 由代码按**协议级规则**从答案算出；每一项在 RSI 闭环里**按赛果逐项结账**，没有信号的项被删，权重只许从结账来。

## 1. 为什么改（出生事故与行业证据）

- 26103：处方 14/14 全对而票 8/9 死于"第五个更好的理由"——加法推理让多余的理由补回了唯一要紧的那一格。协议级 rubric 的研究把它叫"用没人要的建议把分买回来"。
- 冰岛 −14、改判账 −9.77：主循环（验证器）接受了层级不够的证据——"把没说的当成说了"。
- 26128 "conf3 裸单开平"、"锚方 PASS vs FAIL 被 n=70 推翻"：序数打分（confidence、完整度 0–4）是最不可信的输出；Jev 的 Score 题在分布漂移下校准误差 0.325，Choice 题 0.079。
- 规则瘦身（09-27）：19 条判断类码无一有正向实证——它们从来没有被逐条结账过，只被当门用。
- F9 n=39 残差 −0.2pp：程度判断≈市场。市场是一个已校准的系统一；一个校准分类器不知道 Varga 腿伤。**契约的价值在把"知道什么事实"和"事实该挪几个 pp"分开**，前者归 LLM，后者归结账。

## 2. 原则（在 09-23 三原则之上）

1. **原子**：一项只问一件事；"主力缺阵且官宣"拆成两项。复合项由校验器拒收。
2. **可弃权**：每项都有 `unknown`/`p=null`；答"是"而无来源或采集时间晚于开球 → 校验器**强制改为弃权**并留痕（反"把没说的当成说了"）。
3. **分阶段合取 + 一票作废**：事实层任何一项未核实，拨动预算归零；无锚（结构层 `anchor_side=none`）拨动归零；其他项再多也不补分。
4. **判断归 LLM，权重归结账**：分析员给的是"这件事成立的概率"，不是 pp；pp = 项目上限 × 概率 × 方向，上限只许从 RSI 结账往下调或退役（T13 规则：propose 从不写权重；部署门只减不加）。
5. **负分项必须有**：至少三条"不该出现"的项（研究点名风险面却裸单、只有叙事没有事实、证据晚于开球）。
6. **两读互评**：同一张表由两个读者各答一次（深研分析员；系统一读者），逐项算 kappa；kappa<0.4 或 n≥100 仍无结果信号 → 删项。
7. **代码能判的不问模型**：赛程密集、开盘位移、终盘方向由代码从数据判，模型只答数据里没有的事实与结构。

## 3. 问题表 r1（`nutmeg/decision/rubric_items.py`，版本号 `RUBRIC_VERSION="r1"`）

| id | 阶段 | 类型 | 选项 | 方向/效应 | 上限 pp | 来源 | 现有对应 |
|---|---|---|---|---|---|---|---|
| `F_absence_home` | 事实 | noul | 主队关键球员缺阵已官宣 | down:home | 6 | 必填 | tilt kind absence_official |
| `F_absence_away` | 事实 | noul | 客队关键球员缺阵已官宣 | down:away | 6 | 必填 | 同上 |
| `F_suspension` | 事实 | choice | home/away/both/none/unknown | down:该侧 | 4 | 必填 | suspension |
| `F_rotation` | 事实 | choice | home/away/both/none/unknown（官方/主帅确认轮换） | down:该侧 | 3 | 必填 | rotation_confirmed |
| `F_goalkeeper` | 事实 | choice | home/away/none/unknown（门将更换） | down:该侧 | 3 | 必填 | goalkeeper_change |
| `F_venue` | 事实 | noul | 场地/中立/无观众等异常 | 由 `effect_side` 指定 | 2 | 必填 | venue_anomaly |
| `S_anchor_side` | 结构 | choice | home/away/none | 无锚→预算归零 | — | — | strength_balance.verdict |
| `S_spine_intact` | 结构 | noul | 锚方中轴（门将/中卫/组织核心）完整 | 否→down:锚方 | 3 | 必填 | license q1 / anchor_integrity |
| `S_underdog_path` | 结构 | noul | 弱方取胜路径真实存在 | up:弱方 | 2 | — | underdog_path.strength=real |
| `S_draw_mode` | 结构 | noul | 双方进攻都低效，低比分平局是模态之一 | up:draw | 2 | — | 26103 持平分型 |
| `S_dead_face` | 结构 | choice | 3/1/0/none（三证齐全才可判死） | 只记录，不进 pp | 0 | — | death_three_proofs / 被排面链（已证伪） |
| `S_crash_candidate` | 结构 | noul | 锚方是翻车候选 | down:锚方 | 2 | — | crash_markers / p 条 |
| `M_market_read` | 价格 | choice | agree/overpriced_fav/underpriced_fav/underpriced_draw | 只记录 | 0 | — | market_read |
| `M_facts_priced` | 价格 | noul | 事实层事件已被开盘至今位移吸收 | 是→事实层 pp ×0.5 | — | 代码可判（price-band） | priced_in |
| `X_narrative_only` | 负分 | 派生 | 有拨动而事实层全弃权 | 预算归零 | — | 代码 | 09-30 无锚规则 |
| `X_post_kickoff` | 负分 | 派生 | 任一来源采集时间 ≥ 开球 | 该项弃权 | — | 代码 | T12 |
| `X_risk_named_naked` | 负分 | 票面期 | 研究点名的风险面在票面裸单 | 审票 ⚠️ | — | 代码 | C19 |
| `D_belief` | 结论 | dist | 读者自己的 P(3/1/0) | 只记账（F9 第二通道） | — | — | Jev 式整体概率 |
| `D_structure` | 结论 | choice | single/double/full + face/cover | 票面表态 | — | — | stance.structure |
| `D_falsifier` | 结论 | text | 一句赛后可核验的作废条件 | — | — | — | stance.falsifier |
| `O_other_event` | 事实 | choice+text | home/away/none + 一句 | down:该侧 | 2 | 必填 | 兜底（Optional 档） |

- `noul` 答案 = `{"p": 0–1 或 null}`；`choice` = `{"answer": 选项, "p": 该选项概率}`；每项可带 `source`、`captured_at`、`note`。
- **pp 算术**：`pp_i = cap_i × p_i`（noul）或 `cap_i × p_i`（choice 命中有效应的选项）；`p_i < 0.5` 视为不成立，不计；方向按效应把 pp 从一侧挪到另两面（沿用 `_apply_shift` 的等比分配）。阶段合取：事实层无任何有效"是"→ 结构层与其他事实项的 pp 预算为 0（**无锚归零**，= 现行 ANCHOR_TIERS 规则）；`S_anchor_side=none` → 全部归零；`M_facts_priced` 为真 → 事实层 pp ×0.5。总上限沿用 15/10。
- `D_belief` 不进 belief，只与代码聚合的 belief 并排记账（Jev 式"整体概率"对照"逐项聚合"，哪个 Brier 好以后再说）。

## 4. 两个读者

| 读者 | 模型档 | 输入 | 输出 | 用途 |
|---|---|---|---|---|
| A 深研分析员 | `NUTMEG_MODEL_RESEARCH`（继承/opus） | 检索 + 全文 | 研究 JSON（保留散文字段）+ `rubric` 块 | 主判断 |
| B 系统一读者 | `NUTMEG_MODEL_READER`（默认 haiku，新增） | 研究 JSON 的 summary/strength_balance/evidence 文本（state）+ 问题表 | **只有** `rubric` 块，无散文，一次并行作答全部项 | 两读 kappa、历史重打分、防游戏 |

读者 B 的提示词就是 Jev 的形状：给 state、给 typed questions、要求每题一个概率、不得生成解释、不知道就弃权。它读的是分析员写下的证据，不是网络，所以它答"是"也必须引用分析员列的来源，否则校验器改为弃权。

## 5. 结账（RSI 闭环）

- **逐项因子**：每个带效应的项注册为 T13 因子（`experiments/factors.json`，layer=probability，`row_builder=experiments.rubric_rows:<id>`），行 = {factor: 项是否成立, face_hit: 效应面是否开出, fair, provably_prospective}；复用 `propose`（n_min 60、严格前瞻档、置换地板、分窗同号）。`propose_zero` → 项上限改 0（退役）；`propose_change` 只许把上限往下截。
- **两读一致性**：新实验 `K1`：逐项 Cohen's kappa（A vs B）；kappa<0.4 的项列入"重写/删除"清单；n_min 100 项次。
- **整体概率对照**：`D_belief`（读者 B）进 F9 的第二通道（judge=`reader-b`），Brier vs 市场、vs 代码聚合 belief。
- **防游戏**：`G2`：每天抽 20% 场次让读者 B 不看问题表只答 `D_belief` 与 `D_structure`（rubric-free），与看表版本的分歧率；分歧率的月度趋势上升＝分析员在写给表看。
- **历史重打分**：`scripts/rubric_rescore.py` 对已有研究文件（竞彩 141 份、足彩 133 份，共 274 份；剔除拒收与非前瞻）跑读者 B，产出 `rubric` 块并入语料 v2 行 → 逐项因子首次结账。**n 的真实量级是 274，不是 1,578**（1,578 是语料行数，大多数行没有研究文本）。

## 6. 聚合为什么是显式的（与 RaR 的"隐式更强"相反）

RaR 的隐式聚合把判断藏进裁判模型，事后查不出哪一项挪了 belief；我们有赛果可以逐项校验，不需要让裁判替我们加总。显式聚合的"脆"用两件事治：上限只从结账来，阶段合取 + 一票作废替代加法。

## 7. 不做什么

- 不用 rubric 做 RL 训练研究代理（作弊研究：代理分涨、真实质量跌）。
- 不让读者 B 的 `D_belief` 直接当 belief（它会≈市场，F9 已证）。
- 不保留 B5c "4/4 → 裸单"一类加分定档；`S_dead_face` 只记录（被排面链已证伪）。
- 不动审票 V1/V2（它们是代码里的精确规则）。
- `stance` 块本期**保留为派生物**：由 `rubric` 的 `D_structure/D_falsifier/D_belief` 生成，老消费者（F14、C19、判读包）不改接口。

## 8. 出口条件

1. 新研究文件带 `rubric` 块；漏写/写错不拒收（全部或该项弃权并留痕，保护 R0/R1 覆盖，2026-10-02 晚修订），漏答率在两读报表里数。
2. `jczq-build-reads` / `zucai-build-reads` 的 belief 由 `apply_rubric` 算出，Read 带 `rubric` 与逐项 pp 账。
3. 读者 B 对当天每份研究各答一次，`analytics/rubric/<日>.json` 有逐项 kappa。
4. 因子注册表多出 r1 的项目，`factor_registry.py propose --all` 能跑出逐项 n 与提案。
5. 历史重打分 274 份完成，证据文档列出逐项 n、残差、kappa。
6. 日报/判决页每场多一行"事实层 x 项成立 / 结构 … / 预算 … pp / 两读 kappa"。

## 9. 接线清单（探查结果，2026-10-02）

**事实修正**：研究文件共 260 份（竞彩 127 份 09-19→09-30，足彩 133 份 26125→26134），语料 1,665 行里 190 行带研究标签、76 行带 stance。历史重打分的 n 上限是 260，不是 1,578。kappa 没有现成的第二读者——读者 B 就是为此新建的。

**契约层**
- `nutmeg/decision/rubric_items.py`：问题表 r1（id/阶段/类型/选项/效应/上限/来源要求/对应 tier）。
- `nutmeg/decision/rubric.py`：`validate_rubric(rubric, *, kickoff) → (norm, issues)`（枚举、概率域、复合项拒收、无来源/晚于开球强制弃权并记 `coerced`）；`rubric_to_tilt(norm, prior) → stance.tilt | None`（阶段合取 → 逐项 pp=cap×p → 多面 `shift` + 逐项 `evidence[{tier, kind, pp, source, captured_at, item}]`，tier 按项目映射：事实项 official、中轴 confirmed_structural、结构其余 state、兜底 inferred）；`derive_stance(stance, norm, prior)`：**`stance.tilt` 由 rubric 派生**，分析员写的 tilt 存 `tilt_declared`；`why_not_market` 随之改标。派生 tilt 走现有 `validate_stance`/`apply_tilt`，下游（C19/C8/F14/signals/面板）接口不变。
- `nutmeg/decision/research_prompt.py` `RESEARCH_JSON_CONTRACT` + `.claude/agents/jczq-match-analyst.md`：新增「★判断 rubric（必答）」；`stance.tilt` 改为"不用写，由 rubric 派生"；`strength_balance.events` 保留为叙述，不再要求 pp。
- `nutmeg/decision/research_runner.py`：`_REQUIRED` 加 `rubric`；`_validate` 跑 `validate_rubric` 并派生 tilt；落盘时逐项 `captured_at` 由系统盖（原值存 `captured_at_declared`），与现有证据盖章一致。
- `nutmeg/decision/overrides.py`：改判 `--tilt-json` 仍直接替换 `stance.tilt`，加标 `rubric_overridden=true`（改判账照旧）。

**读者 B（系统一读者）**
- `nutmeg/config/settings.py` `model_reader`（`NUTMEG_MODEL_READER`，默认 `haiku`）；`claude_models.reader_model()`。
- `nutmeg/decision/rubric_reader.py`：`state_text(research)`（summary / strength_balance / anchor 行 / events / sources，不含 stance 与 rubric）、`READER_PROMPT`（Jev 形状：state + 问题表 → 只回 JSON rubric，不解释，不知道就弃权，答"是"必须引用 state 里的来源）、`read_rubric(research, *, claude)`、`--free` 模式（只答 `belief`，不看表）、`kappa(a, b)` 逐项与合并。
- 侧车（研究原件只读）：竞彩 `jczq/daily/<日>/rubric-<code>.json`、足彩 `zucai/<期>-rubric-m<N>.json` = `{a, b, b_free, kappa, model, at, prospective}`；日报表 `analytics/rubric/<日>.json|md`。
- CLI `nutmeg rubric read --day|--issue [--limit] [--free]`、`nutmeg rubric report --day`。
- RSI 闭环新步 `rubric_read`（排在 `corpus_build` 前）：当天两条泳道各跑一次。

**Read 与语料**
- `jczq_reads.build_jczq_reads` / `zucai_auto_judgment._from_research`：Read 带 `rubric`（norm + 派生 tilt 的逐项 pp 账 + `reader_belief`）。
- `experiments/corpus_build._research_labels`：加 `rubric`（A 的逐项 answer/p）、`rubric_b`（侧车 B，仅 `at < kickoff` 时）、`rubric_version`。

**结账**
- `experiments/rubric_rows.py`：每个带效应的项一个行构造器（factor=项成立且 p≥0.5；face_hit=效应面是否开出；fair=该面市场价；provably_prospective），模块级 `_FACTORS` 供 `factor_registry.validate`；`experiments/factors.json` 登记 r1 的 10 个方向项（layer=probability，weight_band 默认，`current_weight_pp=0`）。
- `nutmeg/decision/rsi_grading.grade_k1_prospective`：合并 Cohen's kappa×100（A vs B，弃权不计）；`inputs_hash` 含标签；`experiments/registry/K1.json`（falsifier: `rubric_kappa_pp`, n_min 100, ci_lower < 40 → falsified）；`GRADED_EXPERIMENTS` 加 K1；由 Jun 授权的 `rsi register --by op:jun` 登记。
- `scripts/rubric_rescore.py`：对 260 份研究文件跑读者 B 写侧车（可续跑、`--limit`），之后 `corpus_build` + `factor_registry.py propose --all --log`。

**面板**
- `judgment_brief`（竞彩/足彩行）加「rubric」列：事实 x 项成立 / 结构 y / 预算 pp / 两读 kappa。

**SOP 与证据**
- RULEBOOK 新「九、判断 rubric r1」（问题表 + 聚合规则 + 退役规则）；RUNBOOK A3/B4 加 `rubric read`；CONSTITUTION §2 一句（判断契约＝类型化问题表，权重只从结账来）；证据 `docs/superpowers/evidence/2026-10-02-rubric-judgment-contract.md`。

**测试**：`test_rubric.py`、`test_rubric_reader.py`、`test_research_runner.py`（夹具加 rubric）、`test_jczq_reads.py`、`test_zucai_auto_judgment.py`、`test_corpus_build.py`、`test_rsi_grading_prospective.py`（适配器键集）、`tests/experiments/test_rubric_rows.py`、`test_judgment_brief.py`。
