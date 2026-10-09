# RULEBOOK — 判读规则注册表

> 本表只放**现行**规则：「〇」实证表、仍为满级的规则、「八」审票否决、「九」判断 rubric、「十」人群假说。
> 2026-09-27 前的判读条文（表达阶梯 / 证据与偏移 / 旗系统 / 砍腿与双选 / 构票与预算 / 跨渠道）与 **audit 代码化映射（C0–C19 + INFO 参考表）**
> 原文在 `RULEBOOK-archive.md`（2026-10-08 归档，只作检索；偏离登记的条名仍用那里的 ID）。
> 战绩数字的唯一事实源是 `.nutmeg-data/scoreboard.json`；本表引用不复制。

## 〇、规则实证表（2026-09-27 规则瘦身，Jun 定：只保留有正向实证的规则）

**原则**：一条判断类规则只有在前瞻样本上证明「它标记的面比市场给的概率更常/更少开出」，才能影响票面。
没有实证的规则只记账（INFO），不提示、不拦截；判断统一由 belief 承载，票面结构由帽内按判断概率最大化 P 决定。
复核命令：`uv run nutmeg rsi weights propose --all`（T13，严格=可证前瞻样本）。代码：`legs_audit.EVIDENCE_POLICY`。

| 规则 / 码 | 实测（2026-09-27） | 处理 |
|---|---|---|
| C1 方向旗裸单、C2 旗面未盖、C10 | directional_flag_nonmodal n=61，p=0.68，与置换基线分不开 | ERROR→**INFO** |
| C4 conf 裸单 | conf_level n=61，p=0.20 | **INFO** |
| C5/C13 锚方完整度 | anchor_integrity 严格 n=47（<60），全样本 −11pp | **INFO**（未证实） |
| C6 无方向旗未全包 | nondirectional_flag_third_face n=61，p=0.44 | **INFO** |
| C7 活先例 | c7_live_precedent n=142，p=0.95 | **INFO** |
| C8 伪精确锚定 | belief_offset_anchor n=21 | **INFO**（未证实） |
| C9 开季刀 | crash_marker_modal n=61 | **INFO** |
| C11 虚假方向带 / C12 平局低估带 | 各 n=121，p=0.59 / 0.95 | **INFO** |
| C14 昂贵排除（死亡三证） | death_proof_count n=182，p=0.26 | **INFO** |
| C17 读判-票面一致性 | 「第三面更易开」n=130 已证伪 | **INFO** |
| m-四问③b、处方偏离未命名 | 从未量化 | **INFO** |
| **C19 研究点名保险却裸单** | 研究点名的保险面实开 33.3% vs 市场 26.9%（n=33，+6.4±15.1pp）——唯一方向偏正 | ERROR→**WARN**（未证实，照样记账） |
| C3 弃模态面、全包分配、C15/C15b 多票共享死点、C18 跨渠道矛盾 | 结构算术 / 自洽，不是预测主张 | **保留原级别** |
| 注金帽/刹车、没入账=没打、数据纪律 | 宪法 §4-§5 | 不变 |

**截至 2026-09-27 没有任何判断类规则拦截出票**；`decision-audit-legs` 的 ERROR 通道保留，供将来有实证的规则接回（需 T13 严格 n≥60 且显著）。

**事前登记待检验（不影响票面）**：F10 热门低估（历史 60–80% 模态面 n=378 实开 74.9% vs 市场 68.1%，单次扫描，需前瞻复现）；F11 研究的保险点名能否识别热门翻车；**F16 赛程负荷**（2026-10-09：两队 14 天场数差 ≥2 时更密一方被高估？登记前回放 n=598 −0.8pp CI[−4.6,+2.9]＝零效应，预期证伪；台账只展示，见 `team_load.py`）。

**退休（沿用 2026-09-26）**：l-归零；死亡三证作排面前提；B5c 矩阵作出票前提；**「弱势方路径 real/strong → 至少双选」**（2026-09-27 退休：弱方路径的强度改为拨 belief，结构交给 P）；**胜负彩大胆单选渠道规则**（2026-09-27 退休：C1/C19 在所有渠道都已不拦截，渠道差异不再需要）。

## 仍为满级的规则（2026-10-08 按代码核对；条文全文在 `RULEBOOK-archive.md`）

| 规则 | 现行动作 | 代码 |
|---|---|---|
| C3 弃模态面（含 top1−top2 <1pp 噪音带）、模态组合错配、全包名额被同价支配、排面与对位机制相反 | WARN，记账 | `legs_audit`：`modal_face_dropped(_flat)` / `modal_stack_mismatch` / `full_cover_allocation_dominated` / `excluded_face_contradicts_read`（不在 `EVIDENCE_POLICY` 里＝不降级） |
| C15 / C15b 多票共享被排面、共享裸单（含联合同死概率） | WARN；与已购票共享裸单在审票侧是 **V2 否决**（「八」） | `shared_exclusion` / `shared_naked_single` / `shared_naked_joint`；`review.py` |
| C18 / C18b 跨渠道立场矛盾、买回足彩已排的面 | WARN；未显式映射身份只报 INFO | `cross_channel_stance_conflict` / `cross_channel_excluded_face` |
| C19 研究点名保险却裸单 | ERROR→**WARN**（未证实，照样记账） | `EVIDENCE_POLICY["research_cover_naked"]` |
| **l-权重表 + 锚归零**：拨动须含官宣或确证结构级证据，否则归零；`form_state` 每条 ≤1pp；shift 峰值 ≤ 证据预算；无官宣 ≤10pp、有官宣 ≤15pp | rubric 派生的 tilt 同样过这道算术 | `stance.TIER_PP` / `ANCHOR_TIERS` / `KIND_PP_CAP` / `apply_tilt` |
| **g-scope 身份脊柱**：一场一个内核 `match_id`；竞彩编号、足彩场号、titan007/500 id 都是别名，只走别名表（`<期>-channel-map(.auto).json`），缺一环显式跳过，不按队名或 fair 值反查 | 校验强制 | `zucai_identity`、C18、`zucai-night-calibrate` |
| 封闭词典（方向 / 无方向旗、`crash_markers`、先例 `alive/dead/none`、标签）：词典外的剥离进 note 并留痕，不阻断 | 入库桥 | `research_intake` + `legs_audit` 词典 |

`decision-audit-legs` 的 ERROR 通道今天是空的（判断类码全被 `EVIDENCE_POLICY` 降级）；出票前真正的否决在 `betslip preview`（「八」）。

## 八、审票否决表（2026-10-01 定位：机器＝风控官，`nutmeg/decision/review.py`）

| 码 | 级别 | 规则 | 实证 |
|---|---|---|---|
| **V1** | 否决 | 期望回报率 E[派奖]/投入 < 0.5（竞彩：每串 P(全中)×模态赔率连乘；足彩：**奖金模型** `zucai/prize-model.json`，E[奖金·1{中}] = e^{a+sd²/2}·Π_i Σ_{A_i} q_i·p_i^{−b}，报「市场口径 × 判断溢价」；无模型文件退回 P(全对)×中位数并标明）；0.5–0.65 警告 | 403 天回放：帽内 max-P 竞彩 −20%、任九 −58%，CI 不含 0；"中了也亏"的双选×双选（jczq-combos 盲区）。奖金模型（`scripts/zucai_prize_model.py`，2026-10-01）：任九 n=41 log(prize)=−5.25+1.007·S，corr 0.95，b 的 CI95 [0.91,1.11]；胜负彩 n=38 b=1.13。中位数口径把热板票高估十倍（max-P 42 期中 11 次，中时奖金中位 ¥215 vs 全局 ¥4,098）；b≈1 ⇒ 市场口径下任何票面形状的期望回报≈返奖率（回测 max-P 模型 0.84 vs 实际 0.43，差在 11 次命中全落热板） |
| **V2** | 否决 | 与同日/同期/跨渠道**已购**票共享裸单 | 26122 四票联死 73.8%、26133 两票联死 ≈60%、09-28 五票同死 004；gym 里真票 vs 机器同日/同期差额全来自此类结构 |
| V3 | 警告 | 倍数 >10，或单票 > 日帽一半 | 26121 ×50 中过一次（+600）、26129 四票 ¥1,164 全灭——方向不一致，只记录 |
| 止损 | 否决（预审） | 月度止损已触发（宪法 §4）：`betslip preview`/`preview-set` 退出码 1，登记不受限（2026-10-06） | 纪律不是预测主张；刹车行权两次均为负样本（记分牌，累计多亏 677）——事后都证明那一刻最不该靠意志力 |

否决＝改票后再审；人坚持原票可登记（登记是事实），审票行随票入账。新增否决项必须先有回放或复盘实证（≥2 次独立样本），与「〇、规则实证表」同纪律。

## 九、判断 rubric r1（2026-10-02，`nutmeg/decision/rubric_items.py` / `rubric.py`）

研究层对固定问题表逐项作答（每项：答案、成立概率、来源、采集时间、可弃权）；`stance.tilt` **由答案派生**，不再手写。参考 Jev（类型化问题→概率，不生成解释）、HealthBench（逐例二值标准 + 负分项 + 评分器被评测）、协议级 rubric（分阶段合取、一票作废）。

| id | 阶段 | 类型 | 选项 | 效应 | 上限 pp | 来源 | 派生 tier | 版本 |
|---|---|---|---|---|---|---|---|---|
| `F_absence_home` | fact | noul | p∈[0,1]/null | down:home | 6 | 必填 | official | r1 |
| `F_absence_away` | fact | noul | p∈[0,1]/null | down:away | 6 | 必填 | official | r1 |
| `F_suspension` | fact | choice | home/away/both/none/unknown | down:side | 4 | 必填 | official | r1 |
| `F_rotation` | fact | choice | home/away/both/none/unknown | down:side | 3 | 必填 | official | r1 |
| `F_goalkeeper` | fact | choice | home/away/none/unknown | down:side | 3 | 必填 | official | r1 |
| `F_venue` | fact | choice | home/away/none/unknown | down:side | 2 | 必填 | official | r1 |
| `O_other_event` | fact | choice | home/away/none/unknown | down:side | 2 | 必填 | inferred | r1 |
| `S_anchor_side` | structure | choice | home/away/none/unknown | 只记录 | — | — | — | r1 |
| `S_spine_intact` | structure | noul | p∈[0,1]/null | down:anchor:no | 3 | 必填 | confirmed_structural | r1 |
| `S_underdog_path` | structure | noul | p∈[0,1]/null | up:underdog | 2 | — | state | r1 |
| `S_draw_mode` | structure | noul | p∈[0,1]/null | up:draw | 2 | — | state | r1 |
| `S_crash_candidate` | structure | noul | p∈[0,1]/null | down:anchor | 2 | — | state | r1 |
| `S_dead_face` | structure | choice | 3/1/0/none/unknown | 只记录 | — | — | — | r1 |
| `M_market_read` | price | choice | agree/overpriced_fav/underpriced_fav/underpriced_draw/unknown | 只记录 | — | — | — | r1 |
| `M_facts_priced` | price | noul | p∈[0,1]/null | 只记录 | — | — | — | r1 |

**聚合（协议级，`rubric_to_tilt`）**：pp_i = 上限_i × p_i（p<0.5 不成立）；效应把 pp 从一侧挪到另两面按市场比例分配；**事实层（7 项）无一成立 → 预算 0（无锚归零）**；`S_anchor_side=none` → 全部归零；`M_facts_priced` 成立 → 事实层 pp ×0.5；shift 峰值 ≤15pp；派生 tilt 的 evidence 逐项带 `item/tier/kind/pp/source/captured_at`，走原 `validate_stance/apply_tilt`。
**强制弃权（反"把没说的当成说了"）**：标"必填"的项答是/有效选项而无 source、或 captured_at 非法/晚于开球 → 改为弃权并记 `coerced`，不拒收整份研究。**rubric 永不导致拒收（2026-10-02 晚，保护池子）**：分析员漏写 rubric＝全部弃权跟市场（记 `rubric_missing`），表外选项/越界概率/不合法整体分布改为弃权或丢弃（记 `rubric_notes`）——拒收会烧 40 场/日预算并在 R0/R1 覆盖上留缺口；漏答率在两读报表里数。
**负分项**：`X_narrative_only`（有拨动而事实层全弃权＝归零）、`X_post_kickoff`（T12）、`X_risk_named_naked`（C19，审票期）由代码派生。
**两读**：读者 B（`NUTMEG_MODEL_READER`，默认 haiku）只读分析员写下的证据层（不含 stance/rubric），对同一张表作答 → 侧车 `rubric-<code>.json` / `<期>-rubric-m<N>.json`；逐项一致率在 `analytics/rubric/<日>.md`，合并 kappa 进 K1（n_min 100 项次，CI 下界 <40 证伪）。
**结账与退役**：每个带效应的项是 T13 因子 `rubric_<id>`（`experiments/rubric_rows.py`）；`propose_zero` → 该项上限退役；`propose_change` 只许把上限往下截；kappa<0.4 的项列入重写/删除清单。改判 `research override --tilt-json` 仍直接替换 tilt，研究标 `rubric_overridden`。
**读者 B 的 `belief`**（整体概率）只记账，不进 belief——F9 已证 LLM 整体概率≈市场。
**改判（2026-10-02 起）**：有 rubric 的研究，`research override` 必须落到项（`--items-json` + `--reason`）或 `--market`，不得直接写 tilt；tilt 从合并后的 rubric 重新派生（`derived_from: rubric:r1+override`）。理由封闭枚举：`new_official_info / evidence_tier_too_low / priced_in / research_contradiction / market_only`（无 rubric 的旧研究自动记 `legacy_tilt`）。改判账在判决页按理由分层（Brier 得失），净负的理由类停用。
**人的偏离（2026-10-02 起）**：`betslip register/preview` 对照机器初稿（`<期>-draft.json` 的「初稿」）报加场/丢场/放宽/收窄/换面；有差异时带 `--deviation`（`fact_self_judged / price_instinct / stake_allocation / structure_preference / other`）+ `--prediction`（一句赛后可核验）。不带只警告不阻断（登记是事实），但不进「人的偏离」账；账房 `account month` 按理由列净值与预测。**理由先于结果（2026-10-06）**：登记簿记 `deviation_at`（理由写下的时刻；同 slip_id 补登记沿用，换理由才记新时刻）与 `first_kickoff`（票内最早开球）；`deviation_at ≥ first_kickoff` 的理由单列「开球后才写理由」，不进按理由的净值——看过结果再写的理由是回看，拿它给理由类记功过会把运气记成判断。
**来源层级（只采集）**：事实项可带 `source_tier`（`club_official / league_official / press / aggregator / social / unknown`），r1 不按层级加权；K1 过 100 项次后按层级看逐项有效性，再决定 r2 是否按层级定上限。
**治理**：增删项 ①先写证据文档（结账数据或两读 kappa）→ ②`RUBRIC_CHANGELOG` 加一条 → ③`RUBRIC_VERSION` 升号，`SUPPORTED_VERSIONS` 决定评分器混不混旧版 → ④退役项写 `until`、新项写 `since` → ⑤K1 与逐项因子按 `rubric_version` 过滤。`nutmeg rubric items [--version]` 打印当前表与变更记录。没有证据文档不许改表。

## 十、人群偏离假说（CR，2026-10-07，`nutmeg/decision/crowd_*.py`）

足彩是奖池均分：edge 只能来自「和全国人群分开、且人群错」的地方。逐场人群比例拿不到，人群偏离从**官方任九奖金反推**。设计：`docs/superpowers/specs/2026-10-07-zucai-crowd-notebook-design.md`（r2）。

- **模型**：`log 任九奖金 = a + b·S + γ·X`。S = −Σ ln p(实际赛果)（非作废场）；X = 触发面「实开数 − 市场期望数」；p 统一取 zgzcw `europeSp` 去水（全部期次同一源，混源会把源差当成人群偏离）。γ 用 Frisch–Waugh 两步 OLS + 按期 bootstrap 2,000 次。观测单位是**期**（每期一个奖金）。
- **方向**：γ>0 = 全国人群**少买**触发面（`crowd_bias=under`，role `cover`）；γ<0 = **多买**（`over`，role `fade`）。
- **结账**：`rsi grade --exp CR<k> --mode replay|prospective`；metric = 方向符号 × γ × 100（每多开一个触发面奖金变化 %，正数＝假说方向成立）；CI 下界 ≥0 survived，上界 <0 falsified，否则 inconclusive；**判决只认 prospective**，n_min 30 期，60 期仍跨线提 retire。grade 先核登记原件与内核冻结指纹，不符拒绝（改 trigger 走 `rsi amend`）。
- **trigger DSL（封闭）**：粒度 (场, 面)；字段 `face` `p_face` `p_home` `p_draw` `p_away`（%）`fav_face` `is_fav` `league` `league_group`(national/top5/other) `board_hot_count`（最大面 ≥65% 的场数）；**`pm_volume_k`（Polymarket 成交量，千美元）`pm_rank`（本期 14 场按成交量的名次，1＝最受关注）——2026-10-09 加，没上 Polymarket＝空，空值的叶子一律为假**；运算 `>= <= == in not_in`；`all/any/not` 至多 2 层；表外字段登记即拒。回放用 `crowd polymarket-backfill`（终场总成交，与赛前口径不同，所以触发用名次）。**CR2**「高关注大热被全国人群多买」（2026-10-09 Jun 签字，前瞻 26137 起；回放两块不一致：26090–26135 γ −53.3% 显著、26035–26089 −3.8% 为零）见 `docs/superpowers/evidence/2026-10-09-polymarket-attention.md`。
- **advisory → 约束**：只有 `rsi deploy` 过的 CR 的线索成为枚举约束（●）；之前一律 ⚑，只看不用。线索在字典序第三序以内：事实层否决 → 帽内结构 → 人群分开。
- **提名**：48 桶（3 纯面 + 面 × 5 市场档 × 3 联赛组）；门＝CI 不含 0 且窗口内实开 ≥8 次；**按 z = |γ|/标准误排序**（不按 |γ|：首轮 |γ| 前三全是稀有桶，未看过的块上翻号）；与已登记或已选候选触发集合重叠 ≥50% 不提。48 桶在 5% 水平期望约 2.4 个假阳性——候选只是提名。
- **签字**：候选写了 `mechanism`（为什么全国人群会这么偏）才能 `crowd sign`；首轮提名块 26090–26135，回放验证块 26035–26089；之后的提名扫全部已结期，验证只靠前瞻。
- **首轮读数（2026-10-07，zgzcw 口径）**：平局 z=4.42，26090–26135 γ=−24.1% CI[−34.0,−12.6]（n=46，提名块，预检时已看过）；**26035–26089 γ=−21.2% CI[−32.6,−9.5]（n=55，未看过的块）**——全国人群多买平局。另两条候选（五大联赛大热客胜 65%+、其他联赛主胜 35–50%）在未看过的块上翻号，未签。

## 已退休/引擎时代常数（禁区，不再复述理由）

hafu 0/18 下架｜高赔串整票 0/38｜胜平负押冷门 0/23｜"3条冷腿堆100x" 必死｜恰净胜N 窄带禁区｜EV 语言否决判读（e条）
