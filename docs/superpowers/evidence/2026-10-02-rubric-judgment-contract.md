# 判断 rubric 契约 r1 · 落地证据（2026-10-02）

Spec：`docs/superpowers/specs/2026-10-02-rubric-judgment-contract-design.md`；计划：`docs/superpowers/plans/2026-10-02-rubric-judgment-contract.md`。
起因：Jun 问 Jev（TypeSafe 系统一模型）与行业 rubric 实施对本项目的参考价值，批准「进一步构思 rubric 改造设计，完成 spec 后开发，同时改对应环节的模型」。

## 1. 设计要点（与行业证据的对应）

| 行业做法 | 本项目落点 |
|---|---|
| Jev：类型化问题 → 概率 + 置信度，不生成文本，可弃权 | 问题表 r1（16 项：事实 7 / 结构 6 / 价格 2，noul/choice），每项概率 + 来源 + 弃权；读者 B 只回 JSON |
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

## 3. 首次实跑

（见 §3 的更新行：读者 B 对 3 份真实研究文件的输出、耗时、κ；历史重打分批次。）

## 4. 待看（不是待办）

- 新研究文件自 10-02 起才带 `rubric`；K1 的 n 要等板面日（每天 8–15 场 × 两读）。
- 历史重打分里读者 A 的答案不存在（旧研究没有 rubric 块），kappa 只能在新文件上算；历史侧车给的是读者 B 的逐项答案 → `rubric_b` 因子行（非前瞻档）只做可读性与方向探查。
- 问题表的项目上限是现行 tier 区间的中点，不是实证；`factor_registry propose` 跑出 `propose_zero` 的项先退役再谈增项。
- `strength_balance.events` 保留为叙述；两套写法并存一段时间后再决定是否删 `events`。
