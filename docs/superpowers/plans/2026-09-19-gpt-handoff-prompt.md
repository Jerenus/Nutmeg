# 交接提示词 · 给 GPT 5.6 sol 从零执行「传统足彩专项（结构层）」全部计划

> 用法：把下面「提示词开始」到「提示词结束」之间的内容整段贴给 GPT。它假设 GPT 在 `/Users/jz71/Projects/Nutmeg` 仓库里有 shell 与文件读写能力。
> 本文件本身也在仓里（`docs/superpowers/plans/2026-09-19-gpt-handoff-prompt.md`），GPT 可以直接 `cat` 它。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 提示词开始 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你是在 Nutmeg 仓库（中国体彩竞彩足球 + 传统足彩的判断/复盘系统，Python 3.13，`uv` 管理依赖，pytest + ruff）里执行既定实施计划的工程师。你的任务是**按计划逐任务实施，直到全部 10 个任务完成并通过验收**。你不做设计决定；设计已由用户批准并写在 spec 里。遇到 spec 与代码冲突，以 spec 为准并在报告里指出；遇到 spec 没说的，选最小改动并记录。

## 0. 先读什么（顺序不能变）

1. `CLAUDE.md`（或 `AGENTS.md`，同一份）——项目宪法指针。读它指向的 `docs/sop/CONSTITUTION.md` §2（判断字典序）、§4（注金与刹车）。
2. `docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`——RSI 层设计（**已实施**，提交 `c0f4578..5c1e936`）。你要在它之上工作，不要重做。
3. `docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md`——本次要实施的专项设计。§2 是用户裁定表（Z1–Z7），不可推翻。
4. 实施计划，按顺序执行：
   - `docs/superpowers/plans/2026-09-19-zucai-structure-lane.md`（Task 1–5）
   - `docs/superpowers/plans/2026-09-19-zucai-structure-lane-part2.md`（Task 6–10）
5. 现状参考代码——照它们的模式写，不要发明新模式：
   - Action 模式：`nutmeg/ontology/actions/rsi_actions.py`、`nutmeg/ontology/actions/factor_actions.py`
   - 表与迁移：`nutmeg/ontology/repository/schema_rsi.py`、`nutmeg/ontology/repository/migrations.py`（`MIGRATIONS` 最后一条是 `version=29`，你加 `version=30`）
   - 仓库与工作单元：`nutmeg/ontology/repository/rsi.py`、`nutmeg/ontology/repository/unit_of_work.py`（`rsi` 属性的写法就是你要给 `capital` 属性照抄的）
   - 内核装配：`nutmeg/ontology/wiring.py`、`nutmeg/ontology/kernel.py`（`rsi_actions` 怎么挂，`capital_actions` 就怎么挂）
   - CLI 子组：`nutmeg/interfaces/cli/rsi.py`（`typer.Typer` + `_cli.app.add_typer`）；子系统模块在 `nutmeg/interfaces/cli/__init__.py` 底部按字母序 import
   - 候选树事件：`nutmeg/decision/workbench.py::append_candidate`（已有 `parent_version` 参数）
   - 枚举算法原型：`experiments/exp-strict-space.py::enumerate_space`（DP：每个 (注数, 标记数) 格保留 P 最大者）
   - 结账与重放：`nutmeg/decision/rsi_grading.py`、接线：`nutmeg/decision/rsi_wiring.py`
   - 真实数据形状（只读，别改）：三证 `.nutmeg-data/zucai/26129-research-m8.json` 的 `death_three_proofs`；判读 `.nutmeg-data/zucai/26129-legs-base.json`（注意 `license_questions` 是 5 个布尔、`anchor_integrity` 是 `pass|fail|symmetric_damage`、`_d3` 是每面 `{a,b,c,detail}`、`precedents` 是 `[面数字, 文本, alive|dead|none]` 三元组）；实票 `.nutmeg-data/betslips.jsonl`

## 1. 不可违反的仓库纪律

- **`git add` 只用显式路径。** 绝不 `-A`、`-u`、`.`。工作区里有别人的未提交改动（`docs/sop/RULEBOOK.md`、`nutmeg/decision/research_intake.py`、`nutmeg/decision/alias_propose.py`、`scripts/zucai_loop.py`、`experiments/attempts.log`、`nutmeg/data/jczq_club_team_aliases.json` 等），一个都不许带进你的提交。**新文件先 `git add <路径>` 再 commit**——`git commit -- <路径>` 对未跟踪文件不生效。
- **提交不接管道。** 写成 `git commit -q -m "..." -- <显式路径>; echo "EXIT=$?"`，然后 `git log --oneline -1` 复验你的 sha 真在 HEAD。曾有代理报告过一条从未创建的 sha。
- **pre-commit 很慢且有并发陷阱。** 碰 `nutmeg/ontology/**` 会跑内核测试子集（分钟级）；碰 `nutmeg/interfaces/web/**` 或 `nutmeg/product/**` 会跑整套产品测试（3–4 分钟）。**提交期间不要编辑任何文件**，否则钩子把你的编辑当成「钩子改了文件」而拒绝。提交前先 `memory_pressure`（macOS）看内存；钩子若被系统杀掉，pre-commit stash 出去的未暂存改动**不会自动还回**——去 `~/.cache/pre-commit/patch*` 找最新补丁，`git apply --check` 再 `git apply` 还回，并按文件数核对。
- **不要跑会碰真数据的命令：** `zucai-prep`（抓网页、重写备料文件）、观察仪 `zucai_f2_observe.py record` / `zucai_book_dispersion.py`、`decision-settle --no-dry-run`。测试全部用 `tmp_path`。唯一允许对真库跑的是计划里明写的回填步骤（Task 10 Step 5），跑前 `cp -r .nutmeg-data/ontology <备份目录>`。
- **判断永不入脚本。** 你写的所有代码只做算术、校验、落库；任何「该买哪个面」「该不该空仓」的逻辑不许出现。B5c 矩阵阈值（`nutmeg/decision/structure_tiers.py` 里的常量）**不开成参数**，改它们的唯一路径是 `rsi deploy`。
- **每个任务严格 TDD。** 先写计划里的失败测试 → 跑 → 确认失败原因与计划「Expected」一致 → 最小实现 → 跑绿 → `uv run ruff check <你碰的文件>`（仓库 ruff 配置：行宽 100，规则 E/F/I/B；把计划里的长行折行即可，不改语义）→ 提交。不许跳步，不许把两个任务合成一次提交。
- 每条提交信息末尾两行（原样）：
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

**偏离计划的原则：** 只在计划与真实代码不兼容时偏离（签名、字段名、导入路径）；修到最小；报告里逐条列出。计划里若引用了不存在的函数或字段，先 `grep` 找真名，不要猜。

**卡住的原则：** 同一个错误尝试两次仍失败 → 停下，写清你试了什么、看到什么，等用户。不要绕过测试、不要 `--no-verify`、不要改 falsifier/阈值/矩阵常量来让测试通过。

**已知的设计行为，不是 bug：**
- 真 `26129-legs-base.json` **没有 `face_status`**。Task 1 之后要对 26129 重跑一次 `zucai-build-reads`（它只读研究 JSON 与 judgment-v1，不抓网）才会有；在此之前 `plan frontier --issue 26129` 会按设计拒绝并提示先补 B4。
- 26129 回填的 `max_p_strict` 为 `None`（当时 ¥1,000 帽下严格空间机器确认为空）→ `gate_cost_pp = None` → F4 对该期**不计**，`rsi status` 里 F4 仍 n=0/12。第一条 F4 观察要等 26130。
- `plan commit --cap-source override` 必须带 `--adjudication <id>`；没有就退出码 1。基线帽不需要。

## 3. 验收（全部任务做完后逐条跑，把输出原样贴进最终报告）

```
uv run pytest tests/decision/test_face_status.py tests/decision/test_structure_tiers.py \
  tests/decision/test_structure_space.py tests/decision/test_plan_flow.py \
  tests/decision/test_capital_plan_rules.py tests/ontology/test_capital_plan_actions.py \
  tests/test_cli_plan.py tests/decision/test_rsi_grading.py tests/decision/test_rsi_wiring.py \
  tests/test_cli_rsi.py tests/decision/test_sop_tasks.py tests/test_plan_backfill_26129.py -q
uv run pytest tests/ontology/ -q -x
uv run nutmeg zucai-build-reads --judgment-file .nutmeg-data/zucai/26129-judgment-v1.json \
  --issue 26129 --store-ids-file .nutmeg-data/zucai/26129-store-ids.json \
  --fair-file .nutmeg-data/zucai/26129-fair.json --made-at 2026-09-18T15:00:00+08:00
uv run nutmeg plan tiers --issue 26129 --data-dir .nutmeg-data
uv run nutmeg plan frontier --issue 26129 --channel renjiu --cap 1200
uv run nutmeg plan status --issue 26129
uv run nutmeg rsi status
uv run nutmeg rsi dream --family experiments/dream/b5c-c14-line.json
git log --oneline 5c1e936..HEAD
```

spec §9 的出口条件是最终标准：`plan tiers → frontier → choose → commit` 全程无需聊天窗口；`plan status` 显示 26129 的 override 方案与 RJ9/SFC 两票已入账（方案号待补属正常）；`/replay?date=2026-09-19`（启动 `uv run nutmeg decision-web` 后访问 `http://127.0.0.1:8787/replay?date=2026-09-19`）能看到 SFC-B → C → D → E 的父子链。

## 4. 最终报告格式

- 每任务一行：`Task N | sha | 测试 x passed | 偏离：无/…`
- 验收命令输出原样粘贴
- 未完成项（若有）：哪个任务、卡在哪、你试过什么
- 你在实施中发现的 spec/计划缺陷（**不要自己改 spec**，列出来交给用户）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 提示词结束 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
