# 判断 rubric 契约 r1 · 落地证据（2026-10-02）

Spec：`docs/superpowers/specs/2026-10-02-rubric-judgment-contract-design.md`；计划：`docs/superpowers/plans/2026-10-02-rubric-judgment-contract.md`。
起因：Jun 问 Jev（TypeSafe 系统一模型）与行业 rubric 实施对本项目的参考价值，批准「进一步构思 rubric 改造设计，完成 spec 后开发，同时改对应环节的模型」。

## 1. 设计要点（与行业证据的对应）

| 行业做法 | 本项目落点 |
|---|---|
| Jev：类型化问题 → 概率 + 置信度，不生成文本，可弃权 | 问题表 r1（15 项：事实 7 / 结构 6 / 价格 2，noul/choice），每项概率 + 来源 + 弃权；读者 B 只回 JSON |
| HealthBench：逐例二值标准、负分项、评分器被评测（GPT-4.1 宏 F1 0.662 vs 医生互评 0.647） | 二值/选项项；负分项 `X_narrative_only / X_post_kickoff / X_risk_named_naked`；两读 kappa（K1）＝评分器被评测 |
| 作弊研究：部分满足复合项 36%、把没说的当成说了 35%、粒度错配 29%；90% 标准是"有没有写到" | 复合项拆原子；答是无来源 → 强制弃权并留痕；负分项 |
| 协议级 rubric：分阶段合取 + 一票作废，加法聚合让"没人要的建议把分买回来" | 事实层无成立项 → 预算 0；均势 → 归零；结构层不补分；总峰值 15pp |
| RaR：显式加权求和脆、隐式更强 | 不采纳隐式（判断藏进裁判查不出哪项挪了 belief）；用"上限只从结账往下调"治脆 |
| Anthropic：代码能判的先用代码；每维度单独裁判；kappa<0.4 删 | 位移/终盘/赛程由代码；读者 B 逐项并行作答；K1 阈值 40pp |

**事实修正**：研究文件 260 份（竞彩 127、足彩 133，均 09-19 起），不是 1,578（那是语料行数）。历史重打分的 n 上限 260，且赛后读＝非前瞻，只用于一致性与可读性。

## 2. 落地（commits `c416a0a`、`8a0abf9`、本文档所在提交）

- `nutmeg/decision/rubric_items.py`（问题表 r1，`question_table()` 生成提示词与 RULEBOOK 表，契约与代码不漂移）；`rubric.py`（`validate_rubric` / `rubric_to_tilt` / `derive_stance` / `rubric_summary`）。
- 契约：`research_prompt.rubric_contract()` 并入系统提示；分析员 md 把"手写 tilt"改为"写 null，由 rubric 派生"；运行器 `_REQUIRED` 加 `rubric`，`_validate` 校验 → 派生 tilt → 原 `validate_stance`；落盘逐项盖 `captured_at`（原值 `captured_at_declared`）。改判标 `rubric_overridden`。
- 读者 B：`rubric_reader.py`（state 不含 stance/rubric/结论；`READER_PROMPT` 为 Jev 形状；`--free` 只答整体概率）、CLI `nutmeg rubric read|report`、模型档 `NUTMEG_MODEL_READER=haiku`（settings/.env.example）。
- Read：`rubric_read_view`（版本、逐项答案、逐项 pp、shift、reader_belief、coerced）进竞彩/足彩 Read；语料 `labels.rubric`（A）、`labels.rubric_b`（B 侧车，仅 at<kickoff）、`rubric_belief`、`rubric_overridden`。
- 结账：`experiments/rubric_rows.py` 11 个逐项因子进 `factors.json`（validate 通过）；`grade_k1_prospective` + `experiments/registry/K1.json`（已 `rsi register --by op:jun`，frozen_hash 5921cec3…）；loop `STEP_ORDER` 加 `rubric_read`（读当天竞彩 + 最新一期足彩 + 报表）；`scripts/rubric_rescore.py`。
- 面板：`judgment brief` 两条泳道加 rubric 列（事实/结构/弃权/预算/κ）。
- SOP：RULEBOOK「九」（表由注册表生成）、RUNBOOK A2/A3/B4、CONSTITUTION §2 一句。
- 测试：`test_rubric`（8）、`test_rubric_reader`（4）、`test_research_runner`（+2，夹具加 rubric）、`test_research_prompt`（+1）、`test_overrides`（+1）、`test_jczq_reads`（+1）、`test_zucai_auto_judgment`（+1）、`test_corpus_build`（+1）、`test_rubric_rows`（3）、`test_rsi_grading_prospective`（+1）、`test_judgment_brief`。

## 3. 首次实跑（2026-10-02 14:44，`scripts/rubric_rescore.py --lane jczq --limit 3`）

| 项 | 结果 |
|---|---|
| 模型 | haiku（`NUTMEG_MODEL_READER`） |
| 耗时 | ≈55 秒/份（14:44:36 → 14:45:31） |
| 09-19 周六001 | 作答 8 项、弃权 8 项；事实层 7 项**全部弃权**（证据层没有官宣来源）；`S_anchor_side=away`、`S_underdog_path=yes(0.8)`、`M_market_read=overpriced_fav`；belief 33/28/39 |
| 09-19 周六003 | 作答 7 项；**1 项被强制弃权**（答是而无来源→`coerced`，反"把没说的当成说了"的守卫在真实输出上触发）；belief 42/35/23 |
| 失败 1 | `research-run-2026-09-19.json`（运行日志被当研究读）→ 已修：`is_research_file` 排除 `research-run-*` 与 `*.rejected*` |

读法：读者 B 在旧研究上对事实层一律弃权，是对的——旧文件的证据层只有叙述没有来源；它在结构层与价格层给出的答案才是可比的。kappa 要等新研究（带读者 A 的 rubric）落地后才有。历史重打分 260 份按 55 秒/份约 4 小时，分批后台跑，日志 `scratchpad/rescore.log`。

## 4. 待看（不是待办）

- 新研究文件自 10-02 起才带 `rubric`；K1 的 n 要等板面日（每天 8–15 场 × 两读）。
- 历史重打分里读者 A 的答案不存在（旧研究没有 rubric 块），kappa 只能在新文件上算；历史侧车给的是读者 B 的逐项答案 → `rubric_b` 因子行（非前瞻档）只做可读性与方向探查。
- 问题表的项目上限是现行 tier 区间的中点，不是实证；`factor_registry propose` 跑出 `propose_zero` 的项先退役再谈增项。
- `strength_balance.events` 保留为叙述；两套写法并存一段时间后再决定是否删 `events`。

## 5. 其它环节的 rubric 工程（2026-10-02 晚，Jun「按照 1，2，治理，然后再完成后续」）

勘察结论：只在三个环节值得加，判据是"这项能按赛果或两读结账"。入板/价格/初稿/审票是代码，复盘标签已是封闭词典，实验登记已是 rubric，逻辑层解释文不可结账——都不加。

| 项 | 落点 | 结账 |
|---|---|---|
| ① 改判落到项 | `overrides.record_override(items=…, reason=…)`；CLI `--items-json/--reason/--market`；有 rubric 的研究拒收 `--tilt-json`；tilt 从合并 rubric 重新派生（`rubric:r1+override`）；`effective_research` 保留 `research_original_rubric`；语料 `override_reason` | 判决页改判账按理由分层（`_ledger_totals.by_reason`） |
| ② 人的偏离登记 | `BetSlip.deviation/prediction`；`betslip_diagnosis.vs_draft`（加场/丢场/放宽/收窄/换面）；`register/preview --deviation --prediction`；不带只警告 | 账房 `deviation_ledger`：按理由 n/投入/派奖/净/待结 + 预测句 |
| ③ 治理 | `SUPPORTED_VERSIONS / RUBRIC_CHANGELOG / Item.since/until / active_items / items_markdown`；`nutmeg rubric items`；逐项因子与 K1 只认在用版本 | — |
| ④ 来源层级（后续，先采集） | `source_tier` 枚举（club_official/league_official/press/aggregator/social/unknown），校验保留、语料保留、不加权 | K1 过 100 项次后按层级看逐项有效性 |

commit：`cd220fc`（①②）、本节所在提交（③④ + SOP）。

## 6. 历史重打分结果（2026-10-02 晚，终版 260/260）

- 260 份研究文件全部有侧车（竞彩 127、足彩 133）。过程中的 6 次失败都已修成读者端的容错：所有 choice 项加 `unknown`；表外选项、越界概率、不合法的整体 belief 一律改为弃权/丢弃并留痕 `_tolerated`，不再废掉整份作答。
- 侧车进语料 190 行（有赛果、有市场价）。**口径**：读者 B 读的是研究原件里**开球前写下**的证据层（原件只读、captured_at < 开球），只是 B 的读取时刻在赛后，所以标 `prospective=false`、不进严格前瞻档；内容上没有赛后信息泄漏。

读者 B 逐项（`experiments/rubric_b_explore.py`，命中 − 市场价，pp；正 = 项目所押的方向比市场准）：

| 项 | n(答) | 成立 | 成立时 pp | 不成立时 pp |
|---|---|---|---|---|
| F_absence_home | 145 | 95 | −8.7 | +1.4 |
| F_absence_away | 141 | 106 | +1.1 | +2.6 |
| F_suspension | 64 | 32 | −5.7 | 0.0 |
| F_rotation | 88 | 27 | +2.4 | 0.0 |
| F_goalkeeper | 108 | 35 | −8.5 | 0.0 |
| F_venue | 177 | 5 | +3.0 | 0.0 |
| O_other_event | 144 | 36 | −1.9 | 0.0 |
| S_spine_intact（否→锚方减） | 142 | 76 | −10.6 | +2.0 |
| S_underdog_path | 162 | 100 | +2.3 | −2.4 |
| S_draw_mode | 178 | 58 | −2.2 | −2.7 |
| S_crash_candidate | 166 | 22 | −3.6 | −4.4 |

**读法（n 小、非前瞻、单读者，只定方向不定权重）**：
1. 公开的缺阵/门将/中轴受损在这批样本里**已被市场定价甚至过度定价**：项成立时所押方向比市场少中 6–11pp。这与 09-22「带弱点标签方反而超价 +11.6pp」、26128「锚方 PASS vs FAIL 被推翻」同向。r1 给这些项的上限（6/3/3pp）**大概率要往下调**，但要等前瞻样本（K1 与逐项因子 n≥60 严格档）再动。
2. 唯一方向为正的是弱方路径（+2.3，n=100）与轮换（+2.4，n=27）——与 strength-v2「弱势方取胜路径」的立论一致，但 CI 未算，不据此加权。
3. 读者 B 在历史证据层上对事实项弃权 24–67%：旧研究的证据没有结构化来源，B 不猜——守卫按设计工作。
4. 这张表只回答"问题表可读、方向与既有复盘一致"；它不是权重。权重只从前瞻结账来。

## 7. 运行层体检（2026-10-02 晚，Jun「保持池子 rsi 的工作，保持 discovery harness 层的正确工作」）

| 发现 | 影响 | 处理 |
|---|---|---|
| Dream 夜录 10-01、10-02 两晚 `FileNotFoundError` 退出 1（空盘日没有 `jczq-legs-base.json`） | 发现层在假期每晚记失败 | `day_inputs` 缺板面文件 → `DayBoardTooSmall`（与"场次不足"同类跳过，exit 0）；实测 10-02 dry-run 返回 `board_too_small … (empty board)` |
| 深研定时链 10-01、10-02 在 `research intake` / `jczq-build-reads` 崩溃（同一原因） | 定时器显示失败；足彩并集池刷新被跳过 | 两步在空盘日打印"空盘：跳过"并退出 0；`jczq-build-reads` 仍刷新并集池 |
| 今天新加的 11 个 rubric 逐项因子会让 10:45 闭环 `rsi weights propose --all` 抛 `KeyError`（`noise_floor.analyze` 只认自己的因子表） | 明早因子提案步失败 | `analyze` 先查本表再查 `experiments.rubric_rows`；实跑 propose 全部通过（rubric 因子严格前瞻 n=0 → hold） |
| `rubric` 设为深研必填：漏写/写错会整份拒收 | 烧 40 场/日预算、R0/R1 覆盖留缺口 | 改为永不拒收：缺失＝全部弃权（`rubric_missing`），不合法改弃权（`rubric_notes`）；两读报表数漏答 |
| `rsi status` 把 R1（并集池覆盖）显示为 n=0，内核里其实有 37 条前瞻观测 | 池子看起来没在工作 | 覆盖率类实验按前瞻观测行数显示 → 现在 `R1 n=37/200` |
| 闭环两读步只读当天 | 10:45 之后落的研究永远没人读 | `rubric_read` 加读前一天；读者并发 4 |

池子本身在正常工作：09-26→09-30 每天去重后 9–25 场，完成率高（09-28 22 场完成 21）；R1 缺口来自拒收、重试上限、开球前没排到，是真实缺口。早盘入板在假期退出 1（体彩"0 在售 / 0 未开售"），日志自己写着"空盘（合法）"——属于误报，未改：把空列表当成功会掩盖真实的供数故障。
