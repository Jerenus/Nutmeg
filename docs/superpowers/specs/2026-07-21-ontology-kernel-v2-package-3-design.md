# Ontology Kernel v2 Package 3 Design: Decision & Finance Loop

## 信念层与资金层——五动词的正式写路径

> 起草：2026-07-21。上游：`2026-07-20-ontology-kernel-v2-design.md`（umbrella）·
> Package 1（内核）、2A（identity+market）、2B（evidence+context）均已交付合并。
>
> 状态：**设计草案，待用户审阅确认 scope，再写实施计划。**
>
> 本 spec 覆盖 umbrella §13.2 的 **Package 3（Decision & Finance Loop）**：EvidenceBundle、
> Forecast、FactorApplication、Ticket/Ledger、Outcome/TicketSettlement 与五动词 facade。它建在
> 2A/2B 已验证接口之上（Match/Team/Person 身份、MarketSnapshot 去水 fair、Observation/Claim
> 证据），把"我们相信什么、正式做了什么、结果如何"变成可审计的 typed Action。

---

## 0. 站位：Package 3 要回答的问题

Package 1–2 建好了"世界发生了什么"（identity + market + evidence）。Package 3 建"决策控制塔"：

1. **在 cutoff 之前，我们冻结了哪些证据？**（EvidenceBundle：prior snapshot + verified observations
   + caveats，禁未来泄漏）
2. **prior 如何变成 belief？每个 factor 精确贡献哪段概率偏移？**（ForecastRevision + FactorApplication
   delta 分解，和为 belief−prior）
3. **这是首次判断、修订、撤回，还是明确跟市场？**（ForecastSeries 单一 current committed revision；
   belief=prior 表示跟市场）
4. **Ticket 是否忠实引用已提交 Forecast？资金是否真实入账？**（BetLeg→committed Forecast；
   Ticket/BetLeg/CashTransaction 原子同提）
5. **结果如何？**（MatchOutcome + BetLeg/Ticket Settlement，缺失不产 pending）

Package 3 **不**做评分/因子生死判决/RegimeVector（Package 4，可重算 Evaluation 投影）、不做历史迁移与
cutover（Package 5）。

### 0.1 建在 2A/2B 已验证接口上

| 已交付 | Package 3 如何用 |
|---|---|
| `OntologyUnitOfWork.actions/.artifacts/.identity/.market/.context/.evidence` | 新增 `.decision`、`.finance` 仓储挂同一事务 |
| `ActionService.execute`（幂等/权限/回滚/乐观并发已备） | 所有信念/资金写入是 Action handler；**乐观并发在此首次激活**（Forecast/Ticket 修订） |
| `MarketSnapshot`（去水 fair + as_of + snapshot_kind） | prior 锚 = read_time snapshot 的 fair；closing = closing snapshot |
| `Observation`/`Claim`（verification_method、evidence span） | EvidenceBundle 只焊 verified Observation；provisional Claim 仅作 caveat |
| `MatchOutcome`? | 2A 无 Outcome；Package 3 建 MatchOutcome（reconcile 落赛果） |
| migration 1–6 | 决策/资金表由 migration 7+ 增量创建 |

---

## 1. Scope 与内部分期（3A 信念 / 3B 资金）

umbrella 的 Package 3 同时含"信念层"（Forecast/Factor/EvidenceBundle）与"资金层"（Ticket/Ledger/
Outcome/Settlement）。二者可独立 TDD/verify，故拆两份实施计划（包边界不变、下游 4/5 编号不变）：

### Package 3A — Belief Layer（先做）

让 prior→belief 成为可审计、禁未来泄漏、因子可分解的正式判断。这是 3B 出票的唯一硬依赖。

- **对象**：DecisionSession、EvidenceBundle、EvidenceBundleItem、ForecastSeries、ForecastRevision、
  FactorFamily、FactorDefinition、FactorApplication、Scenario。
- **Actions**：`OpenDecisionSession`、`FreezeEvidenceBundle`、`DraftForecast`、`CommitForecast`、
  `ReviseForecast`、`WithdrawForecast`、`ProposeFactorStatus`、`ApplyFactorStatus`。
- **五动词映射**：sense（2A/2B 已建）→ **read**（本包：session→bundle→draft→commit）。
- **端到端**：对一场真实 Match，冻结 EvidenceBundle（prior=read_time snapshot fair），落一条 committed
  ForecastRevision（belief=prior 跟市场，或带 FactorApplication 偏移），验证 delta 分解守恒 + cutoff 纪律。

### Package 3B — Finance Layer（3A verify 通过后）

让 committed Forecast 变成受 policy 约束的资金动作，并结算真实结果。

- **对象**：BudgetPolicy、TicketProposal、Ticket、BetLeg、CashAccount、CashTransaction、MatchOutcome、
  BetLegSettlement、TicketSettlement。
- **Actions**：`ChangeBudgetPolicy`、`ProposeTicket`、`ApproveTicket`、`RecordCashTransaction`、
  `CaptureClosing`（2A snapshot 已备，此处标 closing）、`RecordOutcome`、`CorrectOutcome`、`SettleTicket`。
- **五动词映射**：**express**（proposal→approve→ledger）、**reconcile**（outcome→settlement）。
- **端到端**：从 committed Forecast 生成 TicketProposal→ApproveTicket（Ticket+BetLeg+CashTransaction 原子）
  →RecordOutcome→SettleTicket；¥400 框架、空仓合法、缺 outcome 不产 pending。

> 本 spec 完整设计 3A+3B；**先只为 3A 写 plan 并 TDD/verify**，3A 结论作 3B plan 输入。**calibrate 动词
> （评分/因子生死执行/RegimeVector）属 Package 4**——3A 的 ProposeFactorStatus/ApplyFactorStatus 只建
> factor 生命周期状态机骨架，真正的聚合判决在 Package 4。

### 明确排除（Package 4–5）

- ForecastScore/Brier/CLV/校准/FactorEstimate/RegimeVector 的**计算**（Package 4 可重算 Evaluation 投影）；
- DuckDB projections、五张 scorecards；
- 历史 116 Match/212 Read/71 Ticket 迁移、旧写路径关闭、schedule 恢复（Package 5）。

---

## 2. 核心设计决策

### 2.1 EvidenceBundle：焊死 as-of 输入，禁未来泄漏（umbrella §4.3/§5.1）

- Bundle 冻结 `information_cutoff_at`、`prior_snapshot_id`（read_time MarketSnapshot）、
  `verified_observation_ids[]`、`caveat_claim_ids[]`（provisional/disputed 仅风险提示，**不许可偏移**）、
  `identity_resolution_version`、`source_coverage/freshness`、`content_hash`。
- **时态硬规则**：committed ForecastRevision 只能引用 `recorded_at <= cutoff` 且当时有效的 Bundle item。
  `published_at` 更早但 `recorded_at` 晚于 cutoff 的证据**不可用**（历史回放不泄漏未来）。
- Bundle 冻结后不可改；新增资讯 → 新 Bundle + 新 ForecastRevision。
- `content_hash` = 对冻结输入集的确定性哈希（复用 Package 1 `canonical_json` + sha256），可证"同输入同 bundle"。

### 2.2 ForecastRevision：市场锚定 + 因子偏移 + 单一 current（umbrella §4.5）

- `prior_distribution` = Bundle 的 prior snapshot fair（市场共识）；`belief_distribution` = 判断后的概率。
- **`belief=prior` 合法**：表示主循环明确看过后跟市场（不是没判）。未研究比赛不产 fake Forecast，
  analytics 用 prior 作全量基线（Package 4）。
- **FactorApplication delta 分解**（唯一 edge 来源）：每条 `delta_distribution` 对每个 outcome 有符号、
  和为 0；**所有 factor 的 delta 相加精确重建 `belief−prior`**（validator 强制，概率 simplex 校验）。
- **单一 current committed revision** 每 series：commit/revise 用**乐观并发 expected_versions**（Package 1
  已备，此处首次激活）；revise 产新 revision 并 supersede 旧的；withdraw 置 withdrawn。
- `commitment_tier`（follow/lean/commit）供 3B 表达 policy；confidence 拆成 belief/evidence_coverage/
  evidence_quality/forecast_stability（umbrella §9.5，本包落字段，评分在 Package 4）。

### 2.3 分级写回延续（umbrella §6.2）

- **AI Analyst**：产 `draft` ForecastRevision + Factor/Claim review proposal；**不能自行 commit**。
- **Judge/Operator**（单用户系统 = 主循环最新模型在授权内扮演）：CommitForecast/Revise/Withdraw、
  ApplyFactorStatus、ApproveTicket、ChangeBudgetPolicy；actor/model_version/policy_version 必落库。
- **Deterministic System**：Bundle freeze、Policy validation、Outcome ingest、Settlement。

### 2.4 Ticket/Ledger：忠实引用 + 原子同提 + 上限不是任务（umbrella §4.6/§7.3）

- 每条 `BetLeg` 必引用 **committed ForecastRevision** + 准确 `entry_quote_id`（2A MarketQuote）+ line（hhad 必带）。
- `ApproveTicket` 在**一个事务**内写 Ticket + BetLeg[] + CashTransaction(stake)——不出半状态。
- **¥400 硬顶**是成本可核算，不是"填满"任务；空 proposal/空仓是合法结果（umbrella §7.3 修正
  `compose_tickets` 占满 cap 的旧语义）。
- 竞彩/足彩共用信念层与资金语义；`channel` 是表达属性，不是第二台信念引擎。

### 2.5 Outcome/Settlement：结果充分才结算，不制造 pending（umbrella §7.4/§14.2）

- `RecordOutcome` 显式存 90 分钟/加时/点球/终局状态；`CorrectOutcome` 产新 version + 触发重算，不覆盖。
- `BetLeg/Ticket Settlement` 只在结果充分时生成；缺失保持 unavailable，**不产 pending 输票**。
- 让球按 `settlement_scope` + line 3 路口径评分（复用 2A `MarketDefinition.settlement_scope`；禁亚盘口径）。
- Forecast **不产 operational Settlement**；其 Brier/CLV/校准全属 Package 4 可重算 Evaluation。

---

## 3. Object 模型落位（migration 7+）

### 3A（migration 7 = decision）

```text
decision:
  decision_sessions     {decision_session_id, opened_at, operator_id, cutoff_at, scope_json,
                         status, closed_at?}
  evidence_bundles      {evidence_bundle_id, match_id, decision_session_id, frozen_at,
                         information_cutoff_at, market_snapshot_id, prior_distribution_json,
                         identity_resolution_version, source_coverage_json, freshness_json,
                         content_hash}
  evidence_bundle_items {evidence_bundle_id, item_type(observation|caveat_claim),
                         observation_id?, claim_id?, PRIMARY KEY(evidence_bundle_id, item_type,
                         COALESCE(observation_id,claim_id))}
  forecast_series       {forecast_series_id, match_id, market_definition_id,
                         UNIQUE(match_id, market_definition_id)}
  forecast_revisions    {forecast_revision_id, forecast_series_id, decision_session_id, revision_no,
                         status(draft|committed|superseded|withdrawn), made_at,
                         information_cutoff_at, prior_snapshot_id, prior_distribution_json,
                         belief_distribution_json, evidence_bundle_id, falsifier?,
                         actor_id, model_name?, model_version?, policy_version, commitment_tier,
                         evidence_coverage?, evidence_quality?, forecast_stability?,
                         supersedes_revision_id?, UNIQUE(forecast_series_id, revision_no)}
  factor_families       {factor_family_id, name, definition}
  factor_definitions    {factor_definition_id, factor_family_id, version, name, definition, scope,
                         status(probation|active|retired), born_from_refs_json, valid_from,
                         valid_to?, policy_version, UNIQUE(factor_family_id, version)}
  factor_applications   {factor_application_id, forecast_revision_id, factor_definition_id,
                         scope_entity_ids_json, delta_distribution_json,
                         supporting_observation_ids_json, note}
  scenarios             {scenario_id, forecast_revision_id, label, probability, note}
```

不变量：每 series 最多一个 committed current revision（应用层 + 乐观并发强制）；
Σ_factor delta = belief−prior（validator）；committed revision 只引用 cutoff 前 Bundle item。

### 3B（migration 8 = finance/outcome）

```text
finance:
  budget_policies       {budget_policy_id, policy_version, channel, total_cap, bucket_caps_json,
                         status, effective_at, created_at}
  ticket_proposals      {proposal_id, decision_session_id, policy_version, proposed_legs_json,
                         proposed_stake, status, created_at}
  tickets               {ticket_id, channel, proposal_id, approved_at, status, structure,
                         total_stake, currency, account_id}
  bet_legs              {bet_leg_id, ticket_id, forecast_revision_id, match_id,
                         market_definition_id, selection_id, entry_quote_id, line?, stake_share?}
  cash_accounts         {account_id, channel_scope, currency, status}
  cash_transactions     {transaction_id, account_id, ticket_id?, ticket_settlement_id?,
                         kind(stake|payout|adjustment), amount, occurred_at, idempotency_key}
outcome:
  match_outcomes        {outcome_id, match_id, version, score_90, score_aet?, penalties?, status,
                         source_artifact_retrieval_ids_json, recorded_at, supersedes_outcome_id?,
                         UNIQUE(match_id, version)}
  bet_leg_settlements   {bet_leg_settlement_id, bet_leg_id, outcome_id, grade, hit?,
                         settlement_method_version}
  ticket_settlements    {ticket_settlement_id, ticket_id, settled_at, status, stake_amount,
                         payout_amount, pnl_amount, bet_leg_settlement_ids_json,
                         settlement_method_version}
```

不变量：BetLeg→committed ForecastRevision（FK）；ApproveTicket 原子写 Ticket+BetLeg+CashTransaction；
Settlement 只在 Outcome 充分时生成；ledger stake/payout/adjustment 可对平。

---

## 4. 新 Action 与权限（挂 Package 1 内核，migration 7/8 种子）

| Action（3A） | 允许 actor |
|---|---|
| `open_decision_session` | judge_operator, deterministic_system |
| `freeze_evidence_bundle` | deterministic_system |
| `draft_forecast` | ai_analyst, judge_operator |
| `commit_forecast` / `revise_forecast` / `withdraw_forecast` | judge_operator |
| `propose_factor_status` | ai_analyst, judge_operator |
| `apply_factor_status` | judge_operator |

| Action（3B） | 允许 actor |
|---|---|
| `change_budget_policy` | judge_operator |
| `propose_ticket` | ai_analyst, judge_operator |
| `approve_ticket` | judge_operator |
| `record_cash_transaction` | deterministic_system, judge_operator |
| `capture_closing` / `record_outcome` / `correct_outcome` / `settle_ticket` | deterministic_system |

每 handler 复用 `ActionService.execute`；commit/revise/approve 用 `expected_versions` 拒绝并发冲突。

---

## 5. 五动词在 Package 3 的落地（umbrella §7）

- **read**（3A）：OpenDecisionSession → FreezeEvidenceBundle（焊 cutoff/prior/verified obs）→ DraftForecast
  （analyst，validator 查概率归一/delta 重建/证据状态/市场口径/权限）→ CommitForecast（judge）。
  明确跟市场 = commit `belief=prior`；未研究比赛不产 fake。
- **express**（3B）：只从 current committed Forecast 生成 TicketProposal → policy validator（玩法/line/相关性/
  预算/单注/总额）→ ApproveTicket（原子写 Ticket+BetLeg+CashTransaction）→ 无合格 proposal 则空仓。
- **reconcile**（3B）：CaptureClosing（标 2A closing snapshot）→ RecordOutcome → BetLeg/Ticket Settlement
  （结果充分才产）→ Outcome/price 更正触发新 version。
- **calibrate**：**Package 4**（可重算投影 + 五 scorecards + factor 聚合判决 + Regime）。3A 只落 factor 状态机
  骨架（propose/apply），不算聚合。

---

## 6. 验收硬门

### 3A 验收（全绿方可开 3B）

1. 真实 Match replay：冻结 EvidenceBundle（prior = 2A read_time snapshot fair）；
   committed ForecastRevision 的 `Σ factor delta == belief − prior`（浮点容差）；`belief=prior` 跟市场路径可落。
2. **时态泄漏测试**：`recorded_at > cutoff` 的 Observation 永不进 Bundle；委员会（committed）revision 只引 cutoff 前 item。
3. **单一 current** 不变量：同 series 第二次 commit 用旧 expected_version → 被拒；revise 产新 revision + supersede。
4. AI analyst 只能 draft，不能 commit（权限测试）。
5. 全仓 ruff + pytest 全绿；决策旧链（tests/decision）不回归。

### 3B 验收

1. 真实 committed Forecast → ProposeTicket → ApproveTicket：Ticket+BetLeg+CashTransaction **一事务原子**；
   BetLeg 100% 引用 committed ForecastRevision + entry quote。
2. ¥400 policy 上限校验；空 proposal = 空仓合法。
3. RecordOutcome → SettleTicket：结果充分才结算；缺 Outcome **不产 pending**；让球按 scope+line 3 路评分。
4. ledger stake/payout/adjustment 对平；CorrectOutcome 产新 version + 重算不覆盖。

---

## 7. 风险与保险栓

| 风险 | 保险栓 |
|---|---|
| 未来泄漏 | Bundle 只焊 recorded_at≤cutoff item；时态测试；committed revision FK 到 Bundle |
| delta 分解不守恒/伪精度 | validator 强制 Σdelta=belief−prior + simplex；小样本不在本包评分（Package 4） |
| 并发双 commit | 乐观 expected_versions（Package 1 已备，本包激活）+ 单 current 不变量测试 |
| 资金半状态 | ApproveTicket 一事务写 Ticket+BetLeg+CashTransaction；缺 Outcome 不产 pending |
| 让球亚盘口径错 | 复用 2A `settlement_scope` + line 3 路评分；禁亚盘 |
| 把 Forecast 短期盈亏当质量 | Forecast 不产 operational Settlement；评分属 Package 4 |
| AI 越权 commit/approve | 权限矩阵（ai_analyst 只 draft/propose；commit/approve 仅 judge_operator） |

---

## 8. 后续顺序

1. 用户审阅本 spec，确认 3A/3B 拆分与 3A 先行；
2. 调用 `writing-plans`，只为 **Package 3A — Belief Layer** 写实施计划（TDD）；
3. 3A TDD + 独立 verify（真实 Match replay）；
4. 3A 验收结论作 **Package 3B** plan 输入；
5. 3B 完成后，Package 3 整体验收，再进 Package 4（Learning & Regime）。

> 关联：umbrella §4.3/§4.5/§4.6/§7/§9/§14 · Package 1（内核）· 2A（identity+market）· 2B（evidence+context）
> 已交付接口。
