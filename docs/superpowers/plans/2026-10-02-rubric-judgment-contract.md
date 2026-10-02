# 判断 rubric 契约 r1 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 研究层改为对固定的类型化问题表逐项作答（概率 + 来源 + 可弃权），belief 由代码按协议级规则从答案派生；新增系统一读者（haiku）做两读 kappa 与历史重打分；逐项进 T13 因子结账；面板与 SOP 同步。

**Architecture:** `rubric_items.py`（问题表 r1）+ `rubric.py`（校验、强制弃权、派生 tilt）挂在现有 `stance.py` 之上：派生出的 `stance.tilt` 走原来的 `validate_stance/apply_tilt`，所以 Read/审计/F14/面板的接口不变。读者 B 是一个只回 JSON 的 `claude -p` 调用（`rubric_reader.py`），产物是研究文件旁的侧车。结账复用 T13 `factor_registry`（逐项行构造器）与 RSI 适配器（K1 kappa）。

**Tech Stack:** Python 3.12, typer, pytest, `claude -p` headless（模型档 `NUTMEG_MODEL_READER`）。

Spec: `docs/superpowers/specs/2026-10-02-rubric-judgment-contract-design.md`

---

### Task 1: 问题表与校验/派生（`rubric_items.py` / `rubric.py`）

**Files:**
- Create: `nutmeg/decision/rubric_items.py`, `nutmeg/decision/rubric.py`
- Test: `tests/decision/test_rubric.py`

- [ ] 写失败测试：合法 rubric → norm；复合项/非法选项 → ERROR；答"是"无来源 → 强制弃权并记 `coerced`；`captured_at ≥ kickoff` → 弃权；无事实项成立 → `rubric_to_tilt` 返回 None（无锚归零）；`S_anchor_side=none` → None；事实项 + 结构项 → shift 各面之和为 0、峰值 ≤ Σpp、evidence 带 item 与 tier；`M_facts_priced` 为真 → 事实层 pp 减半；`derive_stance` 把分析员的 tilt 挪到 `tilt_declared`，派生 tilt 过 `validate_stance`。
- [ ] 实现 `rubric_items.py`：`RUBRIC_VERSION="r1"`，`ITEMS: dict[id, Item(phase, type, options, effect, cap_pp, source_required, tier, kind)]`；`PHASES=("fact","structure","price","conclusion")`。
- [ ] 实现 `rubric.py`：`validate_rubric`、`rubric_to_tilt`、`derive_stance`、`rubric_summary`。
- [ ] `uv run pytest tests/decision/test_rubric.py -q` 通过；commit `feat(rubric): r1 question table, validation, derived tilt`.

### Task 2: 契约与运行器（分析员必答 rubric；tilt 由 rubric 派生）

**Files:**
- Modify: `nutmeg/decision/research_prompt.py`, `.claude/agents/jczq-match-analyst.md`, `nutmeg/decision/research_runner.py`, `nutmeg/decision/overrides.py`
- Test: `tests/decision/test_research_runner.py`, `tests/decision/test_research_prompt.py`, `tests/decision/test_overrides.py`

- [ ] 测试：`_validate` 缺 `rubric` → ValueError；带合法 rubric 的文档返回时 `stance.tilt` 为派生（含 `derived_from="rubric:r1"`），分析员的 tilt 在 `stance.tilt_declared`；落盘后每项 `captured_at` 等于系统时间、原值在 `captured_at_declared`。
- [ ] 契约文本：`RESEARCH_JSON_CONTRACT` 加 `rubric` 块（逐项 id/类型/选项/来源要求），说明 `stance.tilt` 不用写；md 加「★判断 rubric（必答）」段，`strength_balance.events` 的 pp 改为可选叙述。
- [ ] 运行器：`_REQUIRED += ("rubric",)`；`_validate` 调 `validate_rubric` → `derive_stance` → 再 `validate_stance`；写盘时逐项盖 `captured_at`。
- [ ] overrides：`effective_research` 在研究含 rubric 且 override 给 tilt 时标 `rubric_overridden=True`。
- [ ] 跑相关测试；commit `feat(rubric): research contract requires rubric; tilt derived from items`.

### Task 3: 读者 B 与 CLI

**Files:**
- Modify: `nutmeg/config/settings.py`（`model_reader`）, `.env.example`, `nutmeg/decision/claude_models.py`（`reader_model`）
- Create: `nutmeg/decision/rubric_reader.py`, `nutmeg/interfaces/cli/rubric.py`
- Test: `tests/decision/test_rubric_reader.py`

- [ ] 测试（假 claude 返回固定 JSON）：`state_text` 不含 `stance`/`rubric` 字段；`read_rubric` 解析并校验；无来源的"是"被强制弃权；`kappa` 对两份一致答案为 1.0、全不同为 ≤0；`read_day` 写侧车并跳过已有侧车；`report` 生成 json/md。
- [ ] 实现 `rubric_reader.py` 与 CLI `nutmeg rubric read --day|--issue [--limit] [--free] [--force]`、`nutmeg rubric report --day`。
- [ ] commit `feat(rubric): system-one reader (haiku) sidecars, kappa, report`.

### Task 4: Read 载荷与语料标签

**Files:**
- Modify: `nutmeg/decision/jczq_reads.py`, `nutmeg/decision/zucai_auto_judgment.py`, `experiments/corpus_build.py`
- Test: `tests/decision/test_jczq_reads.py`, `tests/decision/test_zucai_auto_judgment.py`, `tests/experiments/test_corpus_build.py`（若无则新建最小测试）

- [ ] 测试：Read 带 `rubric{version, items, tilt_pp, reader_belief}`；语料 `labels.rubric` 与 `labels.rubric_b`（侧车 `at < kickoff` 才带）。
- [ ] 实现；commit `feat(rubric): reads and corpus carry rubric answers`.

### Task 5: 逐项结账（T13 行构造器 + K1）

**Files:**
- Create: `experiments/rubric_rows.py`, `experiments/registry/K1.json`
- Modify: `experiments/factors.json`, `nutmeg/decision/rsi_grading.py`, `nutmeg/decision/rsi_loop.py`
- Test: `tests/experiments/test_rubric_rows.py`, `tests/decision/test_rsi_grading_prospective.py`

- [ ] 测试：行构造器对 `F_absence_home=yes(p .9)` 产出 factor=1、face_hit 取效应面（down:home → 命中=非主胜）；K1 对同答案 kappa=100pp。
- [ ] 实现；`factor_registry.py validate` 通过；`GRADED_EXPERIMENTS` 加 K1；`rsi register experiments/registry/K1.json --by op:jun`。
- [ ] commit `feat(rubric): per-item factor rows and K1 inter-reader kappa`.

### Task 6: 闭环步骤 + 历史重打分

**Files:**
- Modify: `nutmeg/decision/rsi_loop.py`（`rubric_read` 步）
- Create: `scripts/rubric_rescore.py`
- Test: `tests/decision/test_rsi_loop.py`（步骤顺序）

- [ ] 实现并跑 `scripts/rubric_rescore.py`（后台，可续跑）；跑完 `nutmeg rsi loop` 的 corpus_build + `factor_registry.py propose --all --log`；结果进证据。
- [ ] commit `feat(rubric): loop step and historical rescoring`.

### Task 7: 面板 + SOP + 证据 + 记忆

- [ ] `judgment_brief` 行加 rubric 摘要；RULEBOOK「九」；RUNBOOK A3/B4；CONSTITUTION §2；evidence 文档；memory。
- [ ] 全量测试 + ruff；commit `docs(rubric): SOP, evidence, panel column`.
