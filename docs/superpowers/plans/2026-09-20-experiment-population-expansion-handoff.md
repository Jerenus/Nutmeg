# 交接提示词 · 实验本体对象扩采样（给 GPT）

> 用法：把「提示词开始」到「提示词结束」之间整段贴给 GPT。本文件也在仓里，GPT 可直接 `cat`。

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词开始 ━━━━━━━━━━━━━━━━━━━━━━━━

你是在 Nutmeg 仓库（`/Users/jz71/Projects/Nutmeg`，中国体彩竞彩足球＋传统足彩的判断/复盘系统，
Python 3.13，`uv` 管依赖，pytest + ruff，有 pre-commit）里执行一项**已批准设计**的工程师。
你不做设计决定。设计写在 spec 里，遇到 spec 与代码冲突以 spec 为准并在报告中指出。

## 0. 先读（顺序不能变）

1. `CLAUDE.md` → 它指向的 `docs/sop/CONSTITUTION.md`（§2 判断字典序、§3 两条元原则）
2. **`docs/superpowers/specs/2026-09-20-experiment-population-expansion-design.md`** ← 本次要实施的设计，§2 的三类划分不可推翻
3. `docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`（RSI 层设计，**已实施**，在它之上工作，不要重做）
4. 现状参考代码，照它们的模式写，不要发明新模式：
   - `experiments/registry/R0.json` ← **唯一的 `scope=match` 参照实现**，你要照它的形状给 F9/F5 写 duty
   - `nutmeg/decision/rsi_wiring.py`（`after_am` / `after_prep` / `after_settle` 三个挂载点）
   - `nutmeg/decision/rsi_prereg.py`（`_DUTY_REQUIRED` / `_SCOPES` 校验）
   - `nutmeg/decision/balance_ledger.py`（`balance_row` / `balance_ledger`，F9 的算法，**不许改算法**）
   - `nutmeg/interfaces/cli/rsi.py:227` 的 `balance`（已支持 `--day`，不是新功能）

## 1. 任务（按序，每个任务独立提交）

**T1 · 并集计算器**
新增 `nutmeg/decision/rsi_population.py`，导出 `matches_for_population(population, *, day, issue, data_dir) -> list[dict]`：
- `"jczq"` → 读 `.nutmeg-data/jczq/daily/<day>/jczq-legs-base.json` 的 `legs`，返回每场 `{match_id, code, source:"jczq"}`
- `"zucai"` → 读 `.nutmeg-data/zucai/<issue>-store-ids.json`，返回 `{match_id, match_no, source:"zucai"}`
- `"both"` → **按 match_id 取并集**（不是假设 zucai ⊆ jczq）。同一 match_id 两边都有时保留一条并标 `source:"both"`。
⛔必须真取并集：26130 有 2 场、26131 有 6 场足彩比赛在体彩板面上未对齐，包含关系不恒成立。
测试：`tests/decision/test_rsi_population.py`，用 26130（2 场未对齐）与 26131（6 场未对齐）的真实文件做夹具，
断言 `both` 的场数 = |jczq ∪ zucai| 且不等于 |jczq|。

**T2 · schedule 按 population 展开 match 级 duty**
改 `rsi schedule`：对任何 `scope=match` 的 duty，用 T1 的函数决定对象集合（现状只有 R0 硬编码走竞彩板面）。
R0 的行为必须**逐字节不变**（回归测试）。

**T3 · F9 duty 由 day 改 match**
改 `experiments/registry/F9.json` 的 `duties[0]`：`scope: "day"` → `"match"`，
`deadline_rule: "earliest_kickoff"` → `"match_kickoff"`，instrument 去掉 `--issue {issue}` 改 `--day {day}`。
⛔**只改 duties，不得碰 `population`/`falsifier`/`window`/`stop_rule`/`claim`/`mechanism`**——
F9 的 `population` 本来就是 `both`、`stratum` 本来就是 `pooled`，这是实现补齐不是改判据。
`rsi balance --day` 逐场记 belief/prior：竞彩场 belief 取 `daily/<day>/reads.json`，足彩场取 `<issue>-reads.json`，
两边都调 `balance_ledger.balance_row()`。

**T4 · F5 首次定义 duty**
`experiments/registry/F5.json` 的 `duties` 现在是空数组。按 spec §3.3 加一条 `scope=match` 的 duty，
population 已是 `both` 不动。duty 名 `price-band-observation`，instrument 由你按 F5 的 claim 决定采什么，
若现有脚本不足以采，**只写 duty 与 artifact_glob，采集器留 TODO 并在报告里说明**，不要为了填满而发明指标。

**T4b · 修 `rsi due` 的 issue 硬绑（已实测复现的 bug，优先级高于 T5）**
`nutmeg rsi due` 只接 `--day`，没有 `--issue`；而 F2/F1c/F9/F4 的 duty instrument 里都有 `{issue}` 占位符。
`rsi_prereg.render_instrument` 在 `issue is None` 时直接 `raise ValueError`，于是**只要注册表里存在任何 issue 绑定义务，整个 due 清单就打不开**。
实测复现：`uv run nutmeg rsi due --day 2026-09-20` → `ValueError: 该 instrument 需要 issue，但当天没有足彩期`。
这条今天 08:30 已在 B0 备料链里无声失败过一次（日志：『⚠️rsi 接线未成功（不影响主任务）』）。
修法：①`rsi due` 增加可选 `--issue`；②未给 issue 时，含 `{issue}` 的义务**照常列出但把命令标成 `<需 --issue>` 并在行尾注明**，不得整条清单抛错；③`after_prep` 调用处把当天 issue 传进去。
测试：`tests/test_cli_rsi.py` 增加「无 issue 时 due 不抛错且仍列出全部义务」用例。

**T5 · 姊妹实验登记器**
`rsi register` 增加 `--fork-from <exp_id> --population <p> --window-from <x>`：
复制原件 claim/mechanism/falsifier 文本，只换 `exp_id`/`population`/`falsifier.stratum`/`window`，
新件写 `forked_from: <原 exp_id>`。**拒绝 fork 已 `settled` 的实验**（报错退出码 1）。
本任务只做登记器，**不要真的 fork F2/F1c/F3/F8**——那是用户的裁决，不是你的。

## 2. 红线（违反即回滚）

- ⛔**不得修改 F2 / F1c / F3 / F8 的任何字段**。它们窗口已开（F2 已 n=11），改口径＝样本作废。
  提交前跑 `git diff --stat experiments/registry/` 确认只有 F9.json 与 F5.json 出现。
- ⛔不得改任何 `falsifier` 阈值、`buckets`、`stop_rule`
- ⛔不得改判读或票面逻辑。本次只碰采样范围。
- ⛔`git add` 只用显式路径，**绝不用 `-A` / `-u`**（2026-09-14 事故：`-A` 把 26 个别人的文件扫进 3 个提交，整条分支无法合并）
- ⚠️仓里有并发写入（`experiments/` 与 `scripts/zucai_loop.py` 的 discovery loop 持续变动），
  动 git 前先 `git status` 确认哪些不是你的改动
- ⚠️pre-commit 会跑数分钟 pytest；期间别人改文件会造成「钩子改了文件」的假拒绝。
  **`git commit | tail` 会吞掉退出码**，必须单独 `echo $?` 或不接管道确认。

## 3. 验收（逐条跑，把输出原样贴进最终报告）

```
uv run pytest tests/decision/test_rsi_population.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py -q
uv run pytest tests/decision/ -q
uv run ruff check nutmeg/ tests/
git diff --stat experiments/registry/          # 必须只有 F9.json 与 F5.json
uv run nutmeg rsi schedule --day 2026-09-20 --issue 26131
uv run nutmeg rsi due --day 2026-09-20
uv run nutmeg rsi status
```

出口条件：`rsi status` 里 **F9 的 n 按竞彩全板场数增长**（不再等于足彩 14），
且 F2/F1c/F3/F8 的 n 与窗口**与实施前完全一致**。

提交信息末尾加：
```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词结束 ━━━━━━━━━━━━━━━━━━━━━━━━
