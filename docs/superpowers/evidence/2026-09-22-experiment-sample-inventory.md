# 实验素材盘点：现有样本 × 执行链 × 可迭代的规则

日期：2026-09-22（只读盘点，未改任何数据）
目的：把仓里已有的、带赛果的样本按"能进哪条 loop、能测哪条规则、缺什么"整理成一张可照着跑的表。

## 0. 三条前提（决定了下面所有"能/不能"）

1. **历史样本只能进回放链，永远进不了判决。** `rsi verdict` 只读 `mode=prospective` 的 grade；`after_settle(historical_replay=True)` 直接返回 `replay_excluded`；研究桥对已开球的比赛一律 `skipped_past_kickoff`。历史样本的合法去处只有：`scripts/zucai_loop.py`、`experiments/exp-*.py`、`noise_floor.py`、`rsi dream`、`decision-postmortem`。
2. **回放链的主职能是证伪，不是选拔。** 确认 +0.3% 效应要约 2.5 年样本，排除 ≥2.9% 效应只要 154 场。用现有样本设计假设时，优先选"能被杀死"的。
3. **泄漏纪律。** A 类（赛前自写 reads/legs/judgment）零泄漏可全量回填；B 类（赔率多点快照）零泄漏；**C 类（赛后可查的伤停/首发/战意）禁用**。新特征样本外 BSS > +5% 先按泄漏处理。`provably_prospective` 只有 40/1055 行为 true，其余为 null，T12 禁止事后补标。

## 1. 样本清单（按可用性排序）

| # | 样本 | 规模 | 带什么 | 路径 | 能进的 loop | 能测/能杀的规则 |
|---|---|---|---|---|---|---|
| S1 | 语料 v2 足彩 legs-base 子集 | 126 行 / 10 期（26121–26131 缺 26125） | fair、赛果、`anchor_integrity`、方向/非方向旗、牌照问号、崩盘标记、先例、conf | `experiments/corpus-v2.json`（`fair_source=legs-base`） | `zucai_loop excl/hyp/search/eval`、`exp-label-residuals.py`、`exp-strict-space.py`、`noise_floor.py --include-unproven` | C7 活先例、C13 锚方完整度、C14 >20% 买方差、C12 平 fair 带、C9 开季窗、方向旗→所指面；F4 门代价 |
| S2 | 语料 v2 足彩 reads.prior 子集 | 336 行 / 26 期（26092–26120） | prior、belief、confidence、note（旗名词表解析准确 96%） | 同上（`fair_source=reads.prior`） | `zucai_loop corpus/eval/fit/tourney/regime/notes/hyp` | 判读 vs 市场（BSS）、note 旗规则、F9（belief_moved 仅 28 行，n_min 60 不够） |
| S3 | 语料 v2 竞彩价格行 | 593 行 / 2026-05-19→09-20 | 去水 fair、`books` 593、`opening_odds` 282、赛果+比分+半场 | 同上（`src=jczq`） | `exp-price-bands.py --src jczq`、`exp-f1-book-dispersion.py`、`rsi dream`（F5 变体） | C11/C12 价格带、F1c 分散度、F5 开盘→临场位移 |
| S4 | 竞彩深研标签行 | 28 行（09-19、09-20） | `death_three_proofs`、`hole_location_*`、赛果 | 同上（`fair_source` 研究派生） | `noise_floor.py --factor death_proof_count` | F8 死亡三证；每天 +30 行在长 |
| S5 | 竞彩全板价格×赛果 | 106 天 / 约 1,228 场 | `bold_odds.json` × `jc-results.json` | `.nutmeg-data/jczq/daily/<日>/`、`.nutmeg-data/jczq/jc-results.json` | 重跑 `corpus_build.py` 可扩到 S3 的两倍 | 价格层基线（已证伪无 edge，只作对照） |
| S6 | 内核 forecast × outcome | 1,393 条 forecast（1,335 committed）× 897 场赛果 | prior/belief 分布、falsifier、证据覆盖率 | `.nutmeg-data/ontology/ontology.db` `forecast_revisions`/`match_outcomes` | **尚未接进 corpus_build**，需新增一条 lane | 判读 Brier/BSS 的最大 A 类来源，比 S2 大 4 倍 |
| S7 | 内核多源赔率 | 12,753 条 md-had，4 家源 | import/intl/sporttery/zucai 四源价格 | `market_quotes` | F1c 分散度、B 类位移 | F1c（26125–26128 永久缺口除外） |
| S8 | F2 前瞻台账 | 11 行已 grade | 逐行 bucket、fair、captured/graded 时间戳 | `experiments/prereg-26126-F2-ledger.json` | `rsi grade --exp F2`（唯一有适配器且合法的前瞻样本） | F2 |
| S9 | 票面级结果 | 25 张 betslips + 11 份 final-tickets + 记分牌 25 条有数字的链 | 腿、fair、注金、命中概率；记分牌是中文散文计数 | `.nutmeg-data/betslips.jsonl`、`zucai/*-final-tickets.json`、`scoreboard.json` | `exp-strict-space.py`；记分牌需先写解析器 | F4 门代价、"同价反事实"复盘 |
| S10 | 早期足彩只有赛果 | 约 72 期（26024–26091） | 只有 official-results | `zucai/official-results.json` | **不要扩**：26099 前无 reads，价格层已证伪 | 无 |

## 2. 执行链清单

| loop | 入口 | 吃历史样本？ | 目前能闭到哪 |
|---|---|---|---|
| 足彩发现闭环（12 子命令 corpus/eval/tourney/fit/excl/regime/archive/rank/turn/notes/hyp/search） | `scripts/zucai_loop.py --corpus v2 --cut <期> --policy <json>` | 是，回放专用 | 策略候选 + 闸 v2 + archive + attempts.log；不写回任何规则 |
| 测量层脚本 | `experiments/exp-label-residuals.py`、`exp-price-bands.py`、`exp-strict-space.py`、`exp-f1/f1b/f2/f3p/f4/b1`、`noise_floor.py` | 是 | 权重表 / 置换地板 / 门代价，stdout |
| 复盘行派生 | `nutmeg decision-postmortem --day <日> [--issue]` | 是 | 生成 `postmortem-*.json`，目前只有 26130/26131 与 09-19/09-20 跑过 |
| 价格带 | `nutmeg rsi price-band --day` | 机械上是，但只 42% 的日子有开盘价 | 补出的产物不算履行 |
| RSI 前瞻链（register→schedule→sweep→fulfill→grade→verdict→deploy） | `uv run nutmeg rsi …` | **否** | 只有 F2/F4 有结账适配器；F1c/F3/F5/F8/F9/R0 打不出 grade |
| 深研桥 | `nutmeg research …`、`jczq-build-reads` | **否**（已开球一律跳过） | 只能对未来板面产标签 |
| Discovery Harness（D0–D7） | `nutmeg discovery …` | 否（要 operator_v2 真实候选流水，生产 0 行） | 见 `2026-09-22-meta-exploration-d4-d7-review.md` |

## 3. 规则树现在怎么迭代（如实）

回放（zucai_loop turn 变异 `policy-*.json` 权重）→ 候选 → **人手写** `experiments/registry/<id>.json` 并 `rsi register` → 前瞻窗积累 → `rsi grade --mode prospective` → `rsi verdict` → `rsi deploy --rule <C 码>` → **手改** RULEBOOK / `legs_audit.py` 的 `CODE_SHORT` / `scoreboard.json`。
`policy-factors-v*.json` 只被 `zucai_loop.apply_policy` 和 F3 的 replay_spec 读，生产代码不读。T13"从测量回到权重"只有 plan：`experiments/factors.json` 不存在，`nutmeg rsi weights` 不是命令，`noise_floor` 只能测 3 个因子而票面由 19 个审计码驱动。

## 4. 现在就能跑的批次（全部回放，零生产写入）

| 步 | 命令 | 输入 | 产出 / 判据 |
|---|---|---|---|
| R1 | `uv run python experiments/exp-label-residuals.py` | S1（126 行） | 刷新 09-14 的 42 场权重表：锚方完整度 / conf / 标记 / 先例的残差；仍用"期望=去水 fair 均值、收缩 n/(n+10)、<5pp 归零" |
| R2 | `uv run python experiments/noise_floor.py --factor anchor_integrity --include-unproven`，另两个因子同 | S1+S4 | 置换地板 p 值；`include-unproven` 要在结论里标明非前瞻 |
| R3 | `uv run python scripts/zucai_loop.py hyp --corpus v2 --cut 26131` | S1+S2（462 行） | 批量证伪 note 旗假设；Bonferroni 后不显著即杀 |
| R4 | `uv run python scripts/zucai_loop.py excl --corpus v2` | S1 十期 legs | 被排面 R_excl 复算，加进 26129–26131 三期 |
| R5 | `uv run python experiments/exp-price-bands.py --src all` | S1+S2+S3（1,055 行） | C11/C12 价格带残差 |
| R6 | `uv run python experiments/exp-strict-space.py <期>` 对 26121–26131 | S1+S9 | 严格空间最大 P 与门代价（F4 地板） |
| R7 | `uv run nutmeg decision-postmortem --day <日>` 对 13 个有 reads+赛果的竞彩日、`--issue` 对 10 期 legs | S1、S3 | 把 `postmortem` 字段补到语料，再重跑 `corpus_build.py` |
| R8 | `uv run nutmeg rsi dream --exp F3` / `F5` | S2、S3 | 静态变体排名，只作候选，进不了判决 |

每一步的结论都追加到 `experiments/attempts.log`（多重比较记账），不写 scoreboard，不改 RULEBOOK。

## 4b. 2026-09-22 扩容结果（已落地，`experiments/corpus_build.py` + `scripts/titan007_closing_backfill.py`）

| 指标 | 扩容前 | 扩容后 |
| --- | --- | --- |
| 语料总行数 | 1,055 | 1,578 |
| 足彩行 / 期数 | 462 / 36 | 476 / 37 |
| 带判读标签行 | 154 | 202 |
| 带实际出手 `call` 与 `note` 的足彩行 | 0 | 90 |
| 竞彩行 | 593 | 1,007（其中 415 行以 titan007 终盘作价，`fair_kind=closing`） |
| 内核 forecast 挂到已有行 / 独立行 | 0 / 0 | 627 / 95 |
| `provably_prospective=true` 行 | 40 | 100（文件行仍是 26+14，新增全部来自内核账本 `made_at`） |
| 已结算竞彩场次有终盘价 | 722 | 1,228 / 1,228（中位 163 家书商，首末更新相隔中位 141 小时） |

新增的三条 lane 与一次采集：

- **⑤ 判读文件 lane**：`*-judgment.json` 五种历史形态按已知键名提取 call / conf / note / 标签块；`board` 为散文的期跳过不猜。文件内自报的 `made_at` 只存为 `judged_at_declared`，**不参与** `provably_prospective`（文件可改且多份在开球后被改过）。
- **⑥ 内核 lane**：`forecast_revisions`（committed，每场最新修订）× `match_outcomes`，缺赛果时经外部标识回到 `official-results.json` / `jc-results.json`（只读）；`market_quotes` 多源时序按 provider 摘成 opening/closing/快照数/跨度。内核是只追加账本，所以这条 lane 的 `provably_prospective` 可以合法为 true/false；挂到文件行时只放在 `kernel_provably_prospective`，文件行本身的口径不动。
- **竞彩 lane 改以赛果为主键**：同一竞彩号在前一日目录也找价格；有读时盘用读时盘，没有才用终盘。`fair_kind` 区分两者，价格带检验按需筛。
- **终盘采集**：`scripts/titan007_closing_backfill.py` 对 `jc-results.json` 里每场按 titan match_id 抓各家初赔/终赔与书商自己的 `updated_at`，写 `daily/<日>/closing_odds.json`，幂等、逐日原子写。2026-09-22 首跑 1,228 场全部成功，0 场不可用。

回归：`tests/experiments/test_corpus_build.py` 12 个用例通过；`noise_floor` 三因子在严格档的 n 与改动前逐字相同（33/110/66）；`exp-price-bands --src jczq` 在 1,007 行上跑通；`zucai_loop eval --corpus v2` 读入 1,578 行。

## 5. 要扩样本就补这几处（都是 A/B 类，零泄漏）

1. ~~`corpus_build.py` 新增 lane：`judgment.json`~~ 已落地（§4b）。
2. ~~`corpus_build.py` 新增 lane：S6 内核 forecast × outcome~~ 已落地（§4b），`made_at < kickoff` 由 `provably_prospective` 表达。
3. ~~重建竞彩 lane 到 1,228 场~~ 已落地（§4b）：少的不是去重，是 506 场没有任何价格，已用 titan007 终盘补齐。
4. 记分牌 25 条中文散文计数写解析器，变结构化命中/未中计数。
5. F3/F5/F8/F9 的结账适配器；没有它们，任何前瞻样本都闭不了环。
6. T13 权重写回通路。

## 7. 准备工作补齐（2026-09-22 下午，Jun 批准五项全做）

| 项 | 落点 | 状态 |
| --- | --- | --- |
| 1 因子注册表（T13 ①②③） | `experiments/factors.json` + `experiments/factor_registry.py validate/propose` | 20 条审计码逐条归属：11 个因子（2 fact / 9 probability）+ 7 组 expression 各带理由；变更规则先冻结（n_min=60、严格档 above_floor、分窗同号）；`propose` 从不写权重，E4/E5 有测试 |
| 2 假设批次 | `scripts/zucai_loop.py hyp --corpus v2 --cut 26131 --log` | 11 条假设（新增 3 条基于实际出手 call 的：排掉面开出 / 单选开出 / 双选开出），结论已落 attempts.log |
| 2b 补采 | `scripts/titan007_closing_backfill.py --zucai` | 4 期 47 场有 titan id 的足彩场次拿到终盘与书商数；36 条带标签行首次有价格细节 |
| 3 测量脚本吃新样本 | `experiments/noise_floor.py` 3→10 个因子，`row_flags` 合并 legs-base / judgment / research 三处标签；`zucai_loop.annotate` 优先用结构化标签再退回 note 解析 | 严格档 n 不够时报 `insufficient` 而不是抛错 |
| 4 记分牌解析器 | `experiments/scoreboard_parse.py` → `experiments/scoreboard-tallies.json` | 40 条链解出 26 条可机读（n / hits / R / CI / MDE80 / 判定），期号对不再误读成分数 |
| 5 记账统一口 | `experiments/attempts.py:log_attempt` | `noise_floor --log`、`factor_registry propose --log`、`zucai_loop hyp --log` 共用一个追加点，格式不变 |

### 7.1 因子提案首跑（严格档=只收可证前瞻行；n_perm=1000）

| 因子 | 层 | 严格 n | 观测 pp | p | 提案 |
| --- | --- | --- | --- | --- | --- |
| c7_live_precedent | fact | 110 | −9.9 | 0.28 | record_only |
| anchor_integrity | probability | 33 | −10.3 | 0.56 | hold（n<60） |
| death_proof_count | probability | 66（面级） | +11.8 | 0.29 | propose_zero |
| directional_flag_nonmodal | probability | 40 | −3.3 | 0.86 | hold |
| nondirectional_flag_third_face | probability | 40 | +22.1 | 0.13 | hold |
| crash_marker_modal | probability | 40 | 无 | 无 | hold（insufficient） |
| conf_level | probability | 40 | −9.4 | 0.47 | hold |
| false_direction_band | probability | 100 | +14.0 | 0.48 | propose_zero |
| draw_underpriced_band | probability | 100 | −4.7 | 0.73 | propose_zero |
| belief_offset_anchor | probability | 2 | 无 | 无 | hold（insufficient） |
| modal_face_dropped | fact | 0 | 未测 | 无 | record_only |

三条 `propose_zero` 的现权重本来就是 0，所以它们是"确认零"而不是改动；C11/C12 的立法样本（n=18 / n=14）在 1,578 行上没有重现。面级因子的 n 高估独立样本数，注册表里已写明这条 caveat。

### 7.2 假设批次 1 结果（全语料 1,578 行；标签类只在有标签的行上）

| 假设 | n | 残差 | 95% CI | 判定 |
| --- | --- | --- | --- | --- |
| call:排掉面→开出 | 29 | −12.0pp | [−26.6, +3.2] | 欠功效 |
| call:单选→开出 | 16 | +17.6pp | [−4.0, +38.7] | 欠功效 |
| call:双选→开出 | 13 | +5.2pp | [−14.3, +21.2] | 证伪 |
| 方向旗→非模态 | 76 | −2.8pp | [−13.7, +8.4] | 证伪 |
| 方向旗→开平 | 76 | +0.2pp | [−9.6, +9.9] | 证伪 |
| 无方向旗→非模态 | 65 | −5.1pp | [−17.3, +6.9] | 证伪 |
| C6:无方向旗→第3面 | 65 | −1.8pp | [−11.3, +8.3] | 证伪 |
| 锚方FAIL→正路 | 69 | +1.7pp | [−9.4, +12.9] | 证伪 |
| 锚方PASS→正路 | 61 | −11.6pp | [−23.5, −0.2] | 反向确认（CI 上沿贴 0；置换地板判 indistinguishable，两口径不一致，不据此改规则） |
| C9崩盘标记→正路 | 11 | −0.5pp | [−27.5, +26.7] | 证伪 |
| 基线:全语料→正路 | 1578 | +1.5pp | [−0.9, +3.7] | 证伪 |

"证伪"在这里的含义是"效应小于本样本能检出的最小效应"，不是"效应为零"。call 类假设只有 29/16/13 行，因为 90 条出手里大多数是全包。

### 7.3 续做（2026-09-22 15:00 后）

| 项 | 结果 |
| --- | --- |
| `exp-label-residuals.py --corpus` | anchor / conf 两项改吃语料：完整度 n 70→151，conf n 428→488。conf=4 在 86 行上 R=+10.2pp CI[+1.3,+19.1]，是唯一 CI 不含 0 的档，但置换地板严格档 conf_level 仍 indistinguishable（n=40）。marks / precedent 需要票面腿文件，仍直读 legs |
| R7 复盘行 | `decision-postmortem` 对 12 个有 reads 的竞彩日 + 8 期有 legs 的足彩跑完（20/20 成功）；语料里带 `postmortem` 的行 14→42。26129/26130 的足彩复盘为空，因为这两期没有 `calls.json` |
| R6 严格空间 | 26121–26131 十期：零解 6/10；有解的 4 期最高 P 解赛后 4/4 全断，解集断率 100/99/82/100%。已落 attempts.log；不改 F4 阈值 |
| `nutmeg rsi weights propose` | 已接到 `rsi` 组（`--factor/--all/--corpus/--n-perm/--log`），复用 `experiments/factor_registry.py`，跑完校验注册表字节未变 |

仍在工作树未提交：`scripts/zucai_loop.py`（与 Jun 未提交的 `load_corpus_v2` 同文件）、`experiments/exp-label-residuals.py` 与 `exp-price-bands.py`（Jun 的未跟踪文件，各改了一处）、`experiments/attempts.log`（只追加）。分层拿不准的三处（C1/C2、C5/C13、C14）在 `factors.json` 的 `layer_uncertain_for_jun`。

## 6. 数据缺口（有判读无赛果 / 有赛果无判读）

- 26125/26127/26128 有 legs 无 reads；336 行 reads.prior 无结构标签；`belief_moved` 仅 28 行。
- 内核结算面 `ticket_settlements`、`bet_leg_settlements`、`operator_outcome_revisions`、`operator_match_judgment_*` 全为 0 行；票面级赛果只存在于文件与记分牌散文。
- `decisions.sqlite` 是 0 字节空文件；`state.db` 不含样本。
- `docs/research` 7 份深读只有散文，无结构标签。
- 标签行没有价格细节（126 行 legs 无 books/opening），价格行没有标签（593 行只有 28 行带标签）。
