# 交接提示词 · 给 GPT 5.6 sol 从零执行全部计划

> 用法：把下面「— 提示词开始 —」到「— 提示词结束 —」之间的内容整段贴给 GPT。它假设 GPT 在 `/Users/jz71/Projects/Nutmeg` 仓库里有 shell 与文件读写能力。

— 提示词开始 —

你是在 Nutmeg 仓库（中国体彩竞彩足球 + 传统足彩的判断/复盘系统，Python 3.13，`uv` 管理，pytest + ruff）里执行既定实施计划的工程师。你的任务是**按计划逐任务实施，直到全部任务完成并通过验收**。你不做设计决定；设计已由用户批准，写在 spec 里。遇到 spec 与代码冲突，以 spec 为准并在报告里指出；遇到 spec 没说的，选最小改动并记录。

## 0. 先读什么（顺序不能变）

1. `CLAUDE.md`（或 `AGENTS.md`，同一份）——项目宪法指针。
2. `docs/sop/CONSTITUTION.md` §2（判断字典序）、§4（注金与刹车）。
3. `docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`——RSI 层设计（**已实施**，提交 `c0f4578..5c1e936`）。你要在它之上工作，不要重做。
4. `docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md`——本次要实施的专项设计。
5. 实施计划（按顺序执行）：
   - `docs/superpowers/plans/2026-09-19-zucai-structure-lane.md`（Task 1–5）
   - `docs/superpowers/plans/2026-09-19-zucai-structure-lane-part2.md`（Task 6–10）
6. 现状参考代码（照它们的模式写，不要发明新模式）：
   - Action 模式：`nutmeg/ontology/actions/rsi_actions.py`、`factor_actions.py`
   - 表与迁移：`nutmeg/ontology/repository/schema_rsi.py`、`migrations.py`（最后一条是 `version=29`，你加 30）
   - 仓库与 UoW：`nutmeg/ontology/repository/rsi.py`、`unit_of_work.py`
   - CLI 子组：`nutmeg/interfaces/cli/rsi.py`（`typer` 子组 + `_cli.app.add_typer`）
   - 候选树事件：`nutmeg/decision/workbench.py::append_candidate`（已有 `parent_version`）
   - 枚举算法原型：`experiments/exp-strict-space.py::enumerate_space`
   - 三证形状：`.nutmeg-data/zucai/26129-research-m8.json` 的 `death_three_proofs`；判读形状：`.nutmeg-data/zucai/26129-legs-base.json`

## 1. 不可违反的仓库纪律

- **`git add` 只用显式路径**。绝不 `-A`、`-u`、`.`。工作区里有别人的脏文件（`docs/sop/RULEBOOK.md`、`nutmeg/decision/research_intake.py`、`scripts/zucai_loop.py`、`experiments/attempts.log` 等），一个都不许带进你的提交。
- **提交不接管道**：`git commit -q -m "..." -- <显式路径>; echo "EXIT=$?"`，然后 `git log --oneline -1` 复验你的 sha 真在 HEAD。曾有子代理报告过一条从未创建的 sha。
- **pre-commit 很慢且有并发陷阱**：碰 `nutmeg/ontology/**` 跑内核测试子集（分钟级）；碰 `nutmeg/interfaces/web/**` 或 `nutmeg/product/**` 跑整套产品测试（3–4 分钟）。提交期间**不要编辑任何文件**，否则钩子把你的编辑当成「钩子改了文件」而拒绝。提交前先 `memory_pressure`（macOS）看内存；钩子若被系统杀掉，pre-commit stash 出去的未暂存改动**不会自动还回**，去 `~/.cache/pre-commit/patch*` 找最新补丁 `git apply` 还回，并按文件数核对。
- **不要跑会碰真数据的命令**：`zucai-prep`（抓网页、重写备料文件）、观察仪 `record`、`decision-settle --no-dry-run`。测试全部用 `tmp_path`。唯一允许对真库跑的是计划里明写的迁移/回填步骤（Task 9），跑前备份 `.nutmeg-data/ontology/`。
- **判断永不入脚本**：你写的所有代码只做算术、校验、落库；任何「该买哪个面」「该不该空仓」的逻辑不许出现。矩阵阈值是 RULEBOOK 常量，不开成参数。
- **每个任务严格 TDD**：先写计划里的失败测试 → 跑 → 确认失败原因与计划写的一致 → 最小实现 → 跑绿 → `uv run ruff check <你碰的文件>` → 提交。不许跳步，不许把两个任务合成一次提交。
- 提交信息末尾两行（原样）：
  `Co-Authored-By: GPT 5.6 sol <noreply@openai.com>`
  `Claude-Session: https://claude.ai/code/session_013HNtSYbfyhHqNMN4f6fJxG`

## 2. 执行协议

对每个任务：
1. 读该任务全文与它引用的现有代码。
2. 写失败测试，运行，把失败信息与计划「Expected」对照；不一致就停下来查原因（通常是计划与真实代码有出入），修计划里的代码而不是改测试意图。
3. 实现，运行该任务测试 + 计划指定的回归集。
4. ruff。
5. 提交，复验 HEAD。
6. 写一段 ≤10 行的任务报告：文件 / 测试数 / ruff / sha / 偏离计划之处及原因。

**偏离计划的原则**：只在计划与真实代码不兼容时偏离（签名、字段名、导入路径）；修到最小；报告里逐条列出。计划里若引用了不存在的函数或字段，先 `grep` 找真名，不要猜。

**卡住的原则**：同一个错误尝试两次仍失败 → 停下，写清你试了什么、看到什么，等用户。不要绕过测试、不要 `--no-verify`、不要改 falsifier/阈值来让测试通过。

## 3. 验收（全部任务做完后逐条跑，把输出原样贴进最终报告）

```
uv run pytest tests/decision/test_face_status.py tests/decision/test_structure_tiers.py \
  tests/decision/test_structure_space.py tests/decision/test_capital_plan_rules.py \
  tests/ontology/test_capital_plan_actions.py tests/test_cli_plan.py \
  tests/decision/test_rsi_grading.py -q
uv run nutmeg plan tiers --issue 26129 --data-dir .nutmeg-data          # 出 tiers + 风向
uv run nutmeg plan frontier --issue 26129 --channel renjiu --cap 1200   # 出前沿 + 两个 max P
uv run nutmeg plan status --issue 26129                                 # 显示回填的 26129 方案与 4 张票入账状态
uv run nutmeg rsi status                                                # F4 应显示 n=1/12
git log --oneline c0f4578..HEAD                                         # 本次全部提交
```
spec §9 的出口条件是最终标准：`plan tiers → frontier → choose → commit` 全程无需聊天窗口；`rsi status` 里 F4 n=1/12；`/replay?date=2026-09-19` 能看到 tiers 根 → 前沿层 → 人的分叉。

## 4. 最终报告格式

- 每任务一行：`Task N | sha | 测试 x passed | 偏离：无/…`
- 验收命令输出原样粘贴
- 未完成项（若有）：哪个任务、卡在哪、你试过什么
- 你在实施中发现的 spec/计划缺陷（不要自己改 spec，列出来）

— 提示词结束 —
