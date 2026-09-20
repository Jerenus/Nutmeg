# 交接提示词 · 实验测量层改造（给 GPT）

> 用法：把「提示词开始」到「提示词结束」之间整段贴给 GPT。本文件也在仓里，GPT 可直接 `cat`。
> 前序交接：`2026-09-20-experiment-population-expansion-handoff.md`（采样域扩并集，已竣工）。

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词开始 ━━━━━━━━━━━━━━━━━━━━━━━━

你是在 Nutmeg 仓库（`/Users/jz71/Projects/Nutmeg`，中国体彩竞彩足球＋传统足彩的判断/复盘系统，
Python 3.13，`uv` 管依赖，pytest + ruff，有 pre-commit）里执行一项**已批准设计**的工程师。
你不做设计决定。设计写在 spec 里；遇到 spec 与代码冲突，**以 spec 为准并在报告中指出**。

本次改造的一句话目标：**把「事实」变成「可统计量」**。
不改任何判读逻辑、不改任何票面规则、不改任何 falsifier 阈值。

## 0. 先读（顺序不能变）

1. `CLAUDE.md` → 它指向的 `docs/sop/CONSTITUTION.md`（§2 判断字典序、§3 两条元原则）
2. **`docs/superpowers/specs/2026-09-20-experiment-measurement-layer-design.md`** ← 本次要实施的设计
3. `docs/superpowers/specs/2026-09-20-experiment-population-expansion-asbuilt.md`
   ← 前序**已竣工**，在它之上工作；特别读它的 §4.4（验收条件被「让数字好看」满足的事故）与 §5（七条不变量）
4. `docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`（RSI 层设计，已实施，不要重做）
5. 现状参考代码，照它们的模式写，不要发明新模式：
   - `experiments/corpus_build.py` ← `_research_labels()` 是本次要扩的地方（`10847ba` 刚加的）
   - `nutmeg/decision/research_prompt.py:14` ← `hole_location` 的 schema 就写在这一行
   - `nutmeg/decision/research_intake.py` ← 校验模式，照它加 WARN
   - `nutmeg/decision/rsi_prereg.py:16-48` ← `_DUTY_REQUIRED` / `_SCOPES` / instrument 占位校验
   - `nutmeg/interfaces/cli/rsi.py` ← `register` / `schedule` / `due` / `status` 的现状签名
   - `experiments/registry/R0.json` ← `scope=match` 的参照实现
   - `scripts/jczq_result_backfill.py` ← T4 要加定时器的那个脚本
   - `~/Library/LaunchAgents/com.nutmeg.zucai.prep.plist` ← 照它的形状写新 plist

## 1. 任务（按序，每个任务独立提交）

每个任务结束后 `git commit`，提交信息写清「改了什么 / 为什么 / 实测数字」。

---

**T1 · `hole_location` 受控词典**（spec §3.1）

`research_prompt.py:14` 现在写的是字面量 `"hole_location": {...}` —— **没有 schema**。
实测 55 份产物出现 11 种以上不同 key 组合，最常见的 `{anchor,detail,opponent}` 只占 28/55。
画像①（对手**进攻端**缺席才支撑锚方「能赢」，防守端洞只支撑「能进球」）判的就是这一格，
所以它现在**无法被检验**。

1. `research_prompt.py`：把 schema 改成
   `{"unit": "attack|creation|spine|defense|goalkeeper|both|none", "side": "home|away|both|none", "priced_in": bool, "detail": str}`
   并把 spec §3.1 的七条语义绑定写进 prompt 正文
2. `research_intake.py`：`unit` / `side` 落在值域外 → **WARN**，码名 `hole_location_uncontrolled`。
   ⛔**不得报 ERROR**——`research_runner._validate` 遇 ERROR 会整份丢弃重试，那会把预算烧掉
3. `corpus_build._research_labels()`：加三个**扁平**字段
   `hole_location_unit` / `hole_location_side` / `hole_location_priced_in`
4. ⛔**不回填历史 55 份产物**。历史行 `hole_location_unit=None`，不许替历史产物猜值域

---

**T2 · 逐场判后落档**（spec §3.2）

这是逐场闭环缺的那段回程。现在「这一场判对没判对、错在哪一层」只活在期级复盘散文里。

**它测的不是「我赢没赢」，而是：当赛果落在我排掉的面上时，那个面事前登记的三证/先例状态是什么。**

1. 新增 `nutmeg/decision/postmortem.py`，导出
   `postmortem_rows(*, day, issue, data_dir) -> list[dict]`，字段照 spec §3.2 的 JSON 逐字段实现
2. 新增 CLI `nutmeg decision-postmortem --day <day> [--issue <issue>]`
3. 产物：`.nutmeg-data/jczq/daily/<day>/postmortem-<code>.json`
   与 `.nutmeg-data/zucai/<issue>-postmortem.json`
4. 只在该场**已有赛果**时产出；无赛果计入报告的 `pending` 计数
5. ⛔**纯派生，零判断**。所有字段从既有产物机械抽取
   （research / legs-base / `<issue>-calls.json` / `<issue>-fair.json` / `jc-results.json`）。
   任何一个字段取不到就填 `null`，**不许推断、不许用默认值**
6. 接 `corpus_build` 作为第五路来源

---

**T3 · duty 的 `pending_instrument` 状态**（spec §3.3）

F5 的 instrument 是 `["TODO", "price-band-observation", "--day", "{day}"]`，
每天生成 30 条**永远无法 fulfill** 的实例，持续污染 gap 列表。

> **gap 的语义是「该做没做」，不是「还做不了」。**

1. duty 加可选字段 `"status": "active"|"pending_instrument"`（缺省 `active`）
2. `rsi_prereg.py`：`pending_instrument` 时豁免第 47 行的 `{issue}/{day}` 占位校验，并允许 `instrument[0]=="TODO"`
3. `rsi schedule`：跳过，**不生成实例**
4. `rsi due`：不列入
5. `rsi status`：单列 `pending: F5:price-band-observation（待实现采集器）`，**不计入 gaps**
6. 清理 F5 已生成的未 fulfill 实例。⛔**已 fulfill 的记录一条都不许删**
7. `experiments/registry/F5.json` 只加 `duties[0].status`，**其余字段一个字符都不许动**

---

**T4 · 赛果回填定时器 + 断流告警**（spec §3.4）

`scripts/jczq_result_backfill.py` 是手动脚本，**没有定时器**。实测停摆 6 天无人发现，且静默。

1. 新增 `~/Library/LaunchAgents/com.nutmeg.jczq.results-backfill.plist`，每日 **09:30 BJT**
   （照 `com.nutmeg.zucai.prep.plist` 的形状；日志路径照它的惯例）
2. 脚本加断流自检：`jc-results.json` 最新日期距今 > 2 天时，
   stdout 首行打 `⚠️RESULTS_STALE: latest=<date> lag=<n>d` 并**退出码 2**
3. 写一条运维记录，列明**全部五个**定时器及各自断流的下游后果
   （现有：`decision.am` / `zucai.prep-morning` / `zucai.prep` / `zucai.prep-revision` / `zucai.f2-observe`）
4. ⚠️装完 plist 后跑 `launchctl list | grep nutmeg` 贴输出；**别照记忆假设它在跑**

---

**T5 · `opening_odds` 覆盖诊断**（spec §3.5）—— **诊断任务，不是回补任务**

近 30 日 `bold_odds.json` 覆盖 127/300 = 42%。开盘价是人性轴的唯一原料。

1. 写 `experiments/exp-opening-odds-coverage.py`：按日统计覆盖率 + 按来源拆分缺失原因
2. 报告必须明确回答两问：
   - 缺的 58% 是「当时没抓」还是「源头就不提供」？
   - 历史值在源上是否**仍可取**？
3. ⛔若不可回补，**如实写不可回补**。不许插值、不许用当前赔率替代开盘赔率、不许填默认值
4. ⛔**本任务只诊断不回补**。要回补另开任务

---

**T6 · N0 噪音地板**（spec §3.6）

现行判据是「CI 含不含 0」。n=67 量级上这条线太松，真信号和噪音都含 0。
C7 就是这个形状：全体 R=+2.7pp CI[−7.7,+13.1]，训练窗 +12.0pp → 测试窗 −0.7pp，
**事前没有任何一条判据能拦住它**。

1. 写 `experiments/noise_floor.py`，导出
   `permutation_floor(rows, factor_key, statistic, n_perm=1000, seed=...) -> dict`
   返回 `{n, observed_pp, floor_p2_5, floor_p97_5, p_value, verdict: "above_floor"|"indistinguishable"}`
2. ⛔**seed 必须写死并记进产物**。同一份数据两次跑出两个结论 = 这个工具没有价值
3. 统计量至少支持 `face_hit_rate_resid_pp`（该面实开率 − 该面 fair）
4. 在三个既有因子上跑并把输出**原样**贴进报告：
   `c7_live_precedent` / `anchor_integrity` / `death_proof_count`
5. 写原件草稿 `experiments/registry/_draft_N0.json`（`window.date_from` 填 `"TBD"`）
6. ⛔**不得执行 `nutmeg rsi register`**。那是人的动作

---

**T7 · H1 人性轴 + 解掉 F5 的 TODO**（spec §3.7）

1. 实现 F5 那条 duty 缺的采集器：`nutmeg rsi price-band --day <day>`，产出
   `.nutmeg-data/jczq/daily/<day>/price-band-<code>.json`，字段至少
   `{match_id, fair_now, fair_open, drift_pp{home,draw,away}, book_disagreement_pp, books, captured_at}`
2. F5 的 duty 从 `pending_instrument` 改回 `active`，instrument 指向真命令
   （⚠️F5 的**冻结面一个字都不许动**：`population`/`falsifier`/`window`/`buckets`/`stop_rule`/`claim`/`mechanism`）
3. 写原件草稿 `experiments/registry/_draft_H1.json`，判据写成
   「effect 必须 `above_floor`（引用 N0）」，**不许写一个拍脑袋的 pp 阈值**
4. ⛔**不得执行 `nutmeg rsi register`**

---

**T8 · 人的身份约束**（spec §3.8）

`rsi register` 的 docstring 写着「摄入登记原件（**人**）」，`deploy` 写着「只许人」，
但 CLI 签名里没有任何身份字段。实测：F5/F9 的 duty 修改与库里三条 amendment，执行者全是 AI。
**「只许人」如果由 AI 代跑，那条约束就是装饰。**

1. `rsi register` / `rsi amend` / `rsi deploy` 加**必填** `--by TEXT`
2. 三张表各加一列 `acted_by`；迁移给历史行填 `"unattributed"`
3. 拒绝值（大小写不敏感）：`"" / ai / claude / gpt / codex / assistant / system / auto`
   → `ValueError: --by 必须是人的标识；这三条动作按 RSI 设计只许人执行`
4. ⛔**不做真实身份认证**。这条是**留痕**不是**鉴权**——把「AI 代跑」从无声变成有记录

---

## 2. 红线（违反即回滚）

- ⛔**不得修改 `F1c` / `F2` / `F3` / `F8` 的任何字段**。窗口已开（F2 已 n=11），改口径＝样本作废。
  提交前跑 `git diff --stat experiments/registry/`，**只允许 `F5.json` 出现**，
  新实验草稿一律走 `_draft_*.json` 新文件
- ⛔不得改任何 `falsifier` 阈值 / `buckets` / `stop_rule` / `population` / `window` / `claim` / `mechanism`
- ⛔**不得执行 `nutmeg rsi register` / `amend` / `deploy`**。这三条按设计只许人
- ⛔不得改判读逻辑、票面逻辑、audit 码表（`nutmeg/decision/legs_audit.py` 一行都不要动）
- ⛔**不得为了让任何 n 增长而改代码**。本次验收不看 n
  （出生事故见 asbuilt §4.4：「n 按全板增长」被实现成实例数增长，
  一度让 F9 在**当日零赛果**下显示 n=44/60）
- ⛔数据拿不到就写拿不到。**不许插值、不许默认值、不许"合理推断"**
  （依据：WAF 降级响应覆盖完好快照造成假空盘）
- ⛔`git add` 只用显式路径，**绝不用 `-A` / `-u`**
  （2026-09-14 事故：`-A` 把 26 个别人的文件扫进 3 个提交，整条分支无法合并）
- ⚠️仓里有并发写入（`experiments/` 与 `scripts/zucai_loop.py` 的 discovery loop 持续变动），
  动 git 前先 `git status` 确认哪些不是你的改动
- ⚠️pre-commit 会跑数分钟 pytest；期间别人改文件会造成「钩子改了文件」的假拒绝。
  **`git commit | tail` 会吞掉退出码**，必须单独 `echo $?` 或不接管道确认
- ⚠️`.nutmeg-data/` 在 `.gitignore` 里，别试图提交数据产物

## 3. 验收（逐条跑，把输出原样贴进最终报告）

```
uv run pytest tests/ -q
uv run ruff check nutmeg/ tests/ experiments/ scripts/

git diff --stat experiments/registry/                    # 只允许 F5.json
uv run nutmeg rsi status                                 # F5 不在 gaps
uv run nutmeg rsi due --day 2026-09-20
uv run python -c "import sqlite3;c=sqlite3.connect('.nutmeg-data/ontology/ontology.db');\
print('verdicts',c.execute('select count(*) from rsi_verdicts').fetchone()[0],\
'deployments',c.execute('select count(*) from rsi_deployments').fetchone()[0])"

uv run python experiments/noise_floor.py --factor c7_live_precedent
uv run python experiments/noise_floor.py --factor c7_live_precedent   # 两次必须逐字节一致
uv run python experiments/noise_floor.py --factor anchor_integrity
uv run python experiments/noise_floor.py --factor death_proof_count

uv run nutmeg decision-postmortem --day 2026-09-19
uv run python experiments/exp-opening-odds-coverage.py
launchctl list | grep nutmeg
```

**出口条件（逐条对照 spec §5 的 A1-A8）**：

1. `rsi_verdicts` 与 `rsi_deployments` 仍为 **0 行**
2. `F1c/F2/F3/F8` 的注册表文件**逐字节未变**
3. N0 同 seed 两次输出**逐字节一致**
4. 新 research 产物的 `hole_location.unit` 全部落在闭合值域；
   历史产物 `hole_location_unit=None` 而**不是被猜成某个值**
5. `decision-postmortem` 在一个已结算日产出，且 `actual_was_excluded=true` 的行
   带齐 `{fair_pp, exclusion_tier, death_proof_count, precedent_status}` 三元组
6. T5 报告明确回答「历史可否回补」，**无插值**

**最终报告必须包含**：
- 每个任务的提交 sha
- 上面每条命令的**原样输出**（不要摘要）
- 你在实施中发现的**任何 spec 与现实不符之处**（前序改造有四处设计错误全靠实跑暴露，
  这次大概率还有；发现了就写出来，不要替我圆场）

提交信息末尾加：
```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词结束 ━━━━━━━━━━━━━━━━━━━━━━━━

---

## 我（Claude）的监管清单

GPT 交回后我逐条核这些，不听论证只看输出：

| # | 核什么 | 怎么核 | 为什么是这条 |
|---|---|---|---|
| 1 | 冻结面未动 | `git diff experiments/registry/F1c.json F2.json F3.json F8.json` 必须为空 | B 类实验窗口已开 |
| 2 | 无判决无上线 | 查 `rsi_verdicts` / `rsi_deployments` = 0 | 本次不该产生任何判决 |
| 3 | n 没被做上去 | 对比改造前后 `rsi status` 的 n | asbuilt §4.4 的原样重演 |
| 4 | N0 可复现 | 同 seed 跑两次 diff | 不可复现的零分布 = 没有零分布 |
| 5 | 值域真闭合 | 抽查新 research 产物的 `unit` | 只加 WARN 不加校验＝白改 |
| 6 | 历史没被猜 | 查历史行 `hole_location_unit` 必须全 None | 替历史产物猜值域＝污染语料 |
| 7 | postmortem 零判断 | 逐字段追到源产物 | 派生里混进判断＝实验测自己 |
| 8 | 已 fulfill 未删 | 清理前后 `select count(*) ... where fulfilled_at is not null` | 删已 fulfill＝销毁样本 |
| 9 | 无插值 | 搜 T5 产物里的默认值/填充值 | 假数据比没数据坏 |
| 10 | 定时器真在跑 | `launchctl list \| grep nutmeg` 自己跑一遍 | 别照子代理报的结果信 |

---

# 追加交接 · T9（2026-09-21）

> T1-T8 已全部竣工验收通过（含 GPT 自查修复的 T1/T2/T4/T5 四处）。
> 本节是竣工后新发现的一个 bug，走同一条交接链。

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词开始 ━━━━━━━━━━━━━━━━━━━━━━━━

接着上一轮的测量层改造做 T9，设计写在
`docs/superpowers/specs/2026-09-20-experiment-measurement-layer-design.md` 的
**§9「追加 · T9：观测 stratum 由注册表决定」**，先读那一节。

T1-T8 已验收通过，不要回头改它们。

## 事故

你的 T7 采集器工作正常，但 F5 的 n 永远不会涨：

```
盘上 price-band 产物 : 30 份
F5 观测行            : 30 条，n_rows 合计 30
已 fulfill 实例      : 24 / 30
rsi status           : F5  n = 0 / 120        ⛔
```

根因 `nutmeg/interfaces/cli/rsi.py:44`：

```python
_STRATUM = typer.Option("zucai", "--stratum")
```

`rsi fulfill` 把调用方传入的 stratum 直接写进 `population_stratum`（rsi.py:397），
而 `rsi status` 算 n 时按注册表 `falsifier.stratum` 匹配。
F5 的 `falsifier.stratum = "pooled"`，30 条观测全写成 `"jczq"` —— 一条都对不上。

三个调用方各写各的，前两个是**恰好**对上不是**保证**对上：

| 调用方 | 传什么 | falsifier.stratum | 结果 |
|---|---|---|---|
| research_runner.py:229 | `--stratum jczq` | R0 = jczq | 恰好对上 |
| rsi.py:576（F9 balance） | 硬编码 "pooled" | F9 = pooled | 恰好对上 |
| F5 的 fulfill | jczq | F5 = pooled | ⛔ 永远 n=0 |

映射规则其实已经在代码里（rsi.py:238：`"pooled" if population == "both" else population`），
只是用在 fork 路径，没用在 fulfill 路径。

## 这是同一个病的第三次

1. F9 首日：stratum 对但 n_rows=0、按实例数增长 → 零赛果下显示 n=44/60
2. as-built §4.4：验收条件可被"让数字好看"满足
3. **本次：n_rows 对但 stratum 错 → 采一年样本 n 仍为 0**

共同形状：**观测写进去了、却不计数、而且没有任何地方报警。**
前两次修的是"别让它虚高"，这次要修的是"别让它虚低" —— 两个方向都必须有声音。

## 要做的四件事

**① stratum 不再由调用方决定**
`fulfill_duty` 从已登记实验反查 `falsifier.stratum`，作为 `population_stratum` 的唯一来源。
`--stratum` 保留但降级为断言：传了且与注册表不一致 → 报错
`ValueError: --stratum {传入} 与 {exp} 注册的 falsifier.stratum={注册值} 不一致`。
⛔不得静默采用任一方。

**② 孤儿观测必须发声**（本条是这次真正的价值）
`rsi status` 增加一行，列出存在但不计入 n 的观测：

```
orphan: F5 30 条观测 stratum=jczq，而 falsifier.stratum=pooled（不计入 n）
```

判据：`observation.population_stratum != experiment.falsifier.stratum`。
前两次事故都是靠人盯出来的，第三次要靠系统自己喊。

**③ 修复既有的 30 条**
迁移只改 `population_stratum` 一个字段，且只改与注册表不符的行。
迁移说明里写清「这是标签订正，不是观测重写」，并记录改动条数。
⛔不得删除任何观测行；⛔不得改 n_rows / captured_at / prospective / artifact_hash。

**④ 不做的事**
不改任何 falsifier 阈值、不改 F5 的冻结面、不补跑任何采集器、
不把那 6 条 `prospective=0` 的行改成前瞻 —— 它们的 due_at 是 13:00/16:00×2/18:00/18:30×2，
全部早于采集时刻，是开球后才采的，系统判得对。真实前瞻覆盖就是 24/30。

## 红线（沿用上一轮，逐条仍然有效）

- ⛔不得修改 F1c / F2 / F3 / F8 的任何字段
- ⛔不得执行 `nutmeg rsi register` / `amend` / `deploy`（现在 --by 必填，只许人）
- ⛔不得改判读逻辑、票面逻辑、audit 码表
- ⛔不得为了让任何 n 增长而改代码 —— 本次 F5 的 n 应该变成 **24**，不是 30；
  若你做出了 30，说明把那 6 条回溯行也算进去了，那是错的
- ⛔`git add` 只用显式路径，绝不用 -A / -u
- ⚠️仓里有并发写入；动 git 前先 git status
- ⚠️`git commit | tail` 会吞退出码，必须单独 echo $?

## 验收（逐条跑，原样贴进报告）

```
uv run pytest tests/ -q
uv run ruff check nutmeg/ tests/ experiments/ scripts/
uv run nutmeg rsi status                      # F5 n=24/120；orphan 行消失
git diff --stat experiments/registry/         # 必须为空
uv run python -c "import sqlite3;c=sqlite3.connect('.nutmeg-data/ontology/ontology.db');\
print('obs',c.execute('select count(*) from rsi_observations').fetchone()[0],\
'verdicts',c.execute('select count(*) from rsi_verdicts').fetchone()[0],\
'deployments',c.execute('select count(*) from rsi_deployments').fetchone()[0])"
```

出口条件（对照 spec §9.4 的 B1-B6）：
1. F5 n = **24**/120（不是 0，也不是 30）
2. orphan 行消失；人为造一条错 stratum 观测则它出现
3. `--stratum` 传不一致的值 → 报错退出且不写库
4. R0 仍 30/200、F2 仍 11/140，逐字未变
5. `rsi_observations` 总行数修复前后相等
6. 那 6 条仍是 prospective=0
7. verdicts / deployments 仍为 0

报告里请写明你发现的任何 spec 与现实不符之处。上一轮四处设计错误全靠实跑暴露，
这次大概率还有。

提交信息末尾加：
```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词结束 ━━━━━━━━━━━━━━━━━━━━━━━━

## 我的 T9 监管清单

| # | 核什么 | 怎么核 |
|---|---|---|
| 1 | F5 n 是 24 不是 30 | `rsi status`；30 说明把 6 条回溯行算进了前瞻 |
| 2 | 观测没被删 | 修复前后 `count(*) from rsi_observations` 相等 |
| 3 | 只改了 stratum 一列 | 抽一条观测比对 n_rows/captured_at/prospective/artifact_hash |
| 4 | 断言真的会拦 | 自己传一个错 stratum 试，确认报错且不写库 |
| 5 | orphan 行是活的 | 人为造一条错 stratum 观测，确认它出现 |
| 6 | 其余实验 n 未动 | R0 30/200、F2 11/140 |
| 7 | registry 零改动 | `git diff --stat experiments/registry/` 为空 |

---

# 追加交接 · T10（2026-09-21）

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词开始 ━━━━━━━━━━━━━━━━━━━━━━━━

接着做 T10，设计在
`docs/superpowers/specs/2026-09-20-experiment-measurement-layer-design.md` 的 **§10**，先读那节。
T1-T9 已验收通过，不要回头改。

## 事故

2026-09-20 当日六条 duty 里**只有一条有定时器**（F2）。其余全靠人记得跑：

```
R0   30/30   人手动跑深研
F5   24/30   GPT 手动跑了一次（18:42），6 条已过开球
F9    6/30   01:00 才补跑 → 24 场前瞻资格永久丢失
F1c   0/1    无人跑（连续 5 天 gap）
F4    0/1    无人跑
```

根因：`rsi due` 会准确告诉你「几点前、跑哪条命令」，但**系统里没有任何东西去跑它**。
duty 的 `instrument` 本来就是可执行 argv，却只被当作给人看的提示字符串。

而 `scope=match` + `match_kickoff` 的 duty 天然不能靠一次性定时器覆盖 ——
09-20 的开球从 13:00 排到次日 06:30，单次运行只能覆盖「运行时刻之后才开球」的那部分。

## 要做的四件事

**① `nutmeg rsi sweep --day <day> [--issue <issue>]`**
复用 `due` 的同一份计算，逐条渲染 instrument 并执行：
- 跳过 `status == "pending_instrument"`；跳过已 fulfill 的实例
- 已过 deadline 的**不执行**，计入 `expired`，stderr 打
  `⚠️DUTY_EXPIRED: <exp>:<duty> <n> 条已过开球（前瞻资格已失）`
- 报告 `ran / skipped_fulfilled / skipped_pending / expired / failed`
- 幂等：靠既有 `rsi-ful:{exp}:{duty}:{day}:{match}` 幂等键，⛔不得绕过它

⛔安全边界：只执行 `argv[0] in {"uv"}`；`argv[0] == "TODO"` 拒绝并计 `skipped_pending`；
其他 argv[0] **报错**不静默跳过。注册表是人写的，但执行器不得成为任意命令入口。

**② 定时器**
`com.nutmeg.rsi.sweep.plist`，**每小时整点**跑 `rsi sweep`。
开球分布 13:00–06:30，逐小时扫把「运行 → 开球」窗口压到 ≤1 小时。
⛔不要做"开球前 N 分钟精确触发"——那要为每场注册一个定时器，脆且难查。
装完跑 `launchctl list | grep nutmeg` 贴输出，别照记忆假设它在跑。

**③ `--day` 缺省取业务日不是自然日**
凌晨 00:00–07:00 仍属前一业务日（26131 有 6 场在 09-21 凌晨开球，但属 `daily/2026-09-20/`）。
⛔按自然日取会让凌晨那几场的 duty 找不到实例。

**④ 不做的事**
- 不改任何 duty 的 `deadline_rule` / `scope`
- ⛔**不给已过期的实例补采** —— 补了也是 `prospective=0`、不涨 n，只制造"已完成"的假象
- 不动 F2 现有的 `zucai.f2-observe`

## 红线（沿用前几轮，逐条仍有效）

- ⛔不得修改 F1c / F2 / F3 / F8 的任何字段；`git diff --stat experiments/registry/` 应为空
- ⛔不得执行 `nutmeg rsi register` / `amend` / `deploy`
- ⛔不得改判读逻辑、票面逻辑、audit 码表
- ⛔**不得为了让任何 n 或"已完成数"变好看而补采过期实例**
- ⛔`git add` 只用显式路径，绝不用 -A / -u
- ⚠️`git commit | tail` 会吞退出码，必须单独 `echo $?`

## 验收（逐条跑，原样贴进报告）

```
uv run pytest tests/ -q
uv run ruff check nutmeg/ tests/ experiments/ scripts/
uv run nutmeg rsi sweep --day 2026-09-19        # 应全部 expired，一条都不执行
uv run nutmeg rsi sweep --day <今天>             # 记下 ran 数
uv run nutmeg rsi sweep --day <今天>             # 第二次应全部 skipped_fulfilled
uv run nutmeg rsi status
launchctl list | grep nutmeg
uv run python -c "import sqlite3;c=sqlite3.connect('.nutmeg-data/ontology/ontology.db');\
print('obs',c.execute('select count(*) from rsi_observations').fetchone()[0],\
'ful',c.execute('select count(*) from rsi_duty_instances where fulfilled_at is not null').fetchone()[0],\
'verdicts',c.execute('select count(*) from rsi_verdicts').fetchone()[0])"
```

出口条件（对照 spec §10.4 的 C1-C7）：
1. 对已完成日 sweep → 全 `expired`，零执行
2. 连跑两次 → 第二次全 `skipped_fulfilled`，观测行数不变
3. `TODO` instrument → `skipped_pending`
4. 非 `uv` 开头 → 报错，不静默跳过
5. 凌晨跑 → `--day` 解析为前一业务日
6. `launchctl list` 出现 `com.nutmeg.rsi.sweep`
7. 观测行只增不减；已 fulfill 一条未删；verdicts 仍为 0

报告里写明你发现的任何 spec 与现实不符之处。

提交信息末尾加：
```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

━━━━━━━━━━━━━━━━━━━━━━━━ 提示词结束 ━━━━━━━━━━━━━━━━━━━━━━━━

## 我的 T10 监管清单

| # | 核什么 | 怎么核 |
|---|---|---|
| 1 | 没有补采过期实例 | 对 09-19 sweep 后，该日 fulfilled 数**不变** |
| 2 | 幂等真的成立 | 连跑两次，`rsi_observations` 行数相等 |
| 3 | 执行器不是任意命令入口 | 造一条 `argv[0]="bash"` 的 duty，确认报错 |
| 4 | 业务日解析 | 凌晨时刻跑，确认取前一业务日 |
| 5 | 定时器真在跑 | 自己跑 `launchctl list`，不信报告 |
| 6 | expired 有声音 | 确认 stderr 真打 `DUTY_EXPIRED`，不是只记在报告里 |
| 7 | registry 零改动 | `git diff --stat experiments/registry/` |
