# Ontology Kernel v2 — Package 2 Design: Football World & Evidence

## 足球世界身份层与证据/市场事实接入

> 起草：2026-07-21。上游：`2026-07-20-ontology-kernel-v2-design.md`（umbrella，已批准）
> · Package 1 已交付并合并（内核写边界：SQLite 运行库 + CAS + typed Action + 权限 + migration）。
>
> 状态：**设计草案，待用户审阅确认 scope，再写实施计划。**
>
> 本 spec 只覆盖 umbrella §13.2 的 **Package 2（Football World & Evidence）**。它建立在 Package 1
> 已验证的真实接口之上（`nutmeg.ontology` 的 Action envelope / PermissionGuard / UnitOfWork /
> migration runner / ContentAddressedArtifactStore / IngestArtifact），不改内核语义，只在其上加
> 领域 Object、Link、identity resolution 和领域 Action handler。

---

## 0. 站位：Package 2 要回答的问题

Package 1 让"写"变正确（原子、幂等、权限、审计、不可变证据）。Package 2 让"世界"变真实：

1. **这场比赛、两支球队、赛事、场馆在所有来源里分别是谁？**（跨通道 canonical 身份，非字符串拼接）
2. **它真实何时开赛？**（真 `scheduled_at`，不是抓取时间——修 umbrella §1.3C）
3. **当时市场对它的价格与信息状态是什么？**（typed MarketQuote/MarketSnapshot + 去水 fair）
4. **每条事实来自哪一份不可变原文？**（Observation/Quote → ArtifactRetrieval 血缘）

Package 2 **不**做判读/信念/出票/结算/评分（Package 3–4）、不做历史数据迁移与 cutover（Package 5）。
它把 Match 变成一个带解析身份和市场事实的一等对象，正好是 Package 3 决策环的输入底座。

### 0.1 建立在 Package 1 的已验证接口上（不重造）

| Package 1 已交付 | Package 2 如何用 |
|---|---|
| `ActionCommand` / `ActionService.execute` / `ActionHandler` | 所有领域写入都是一个 Action handler，复用同一幂等/审计/回滚 |
| `PermissionGuard`（deny-by-default，版本化 policy） | 新增领域 action_type 的权限行进 `governance-v1`（或新 policy 版本） |
| `OntologyUnitOfWork`（`.actions`；将加 `.identity`/`.market`/`.evidence`） | 领域 repository 挂在同一事务连接，业务行与 action log 原子同提 |
| 编号 migration + 漂移检测 | 领域表由 migration 3+ 增量创建，沿用 FK 顺序与 checksum drift |
| `ContentAddressedArtifactStore` + `IngestArtifact` | 每个来源原文先 `IngestArtifact` 落 CAS，再由确定性解析产 typed facts |
| `SourceArtifact` / `ArtifactRetrieval` | Observation/Quote 的 `source_artifact_retrieval_ids` 直接引用它 |

---

## 1. Scope 与内部分期（关键决策）

umbrella 的 Package 2 是"identity resolver + Match/Team/Person/Competition/Venue + Role/Appearance +
Claim/Observation + Market ingest + 接现有 Fixture/Player/Weather/Information"——**这是 Package 1 的
2–3 倍体量**。一份 24–30 任务的巨型 plan 违背"独立可审、独立可验"精神。

**决策：Package 2 保持一个 package 边界与一份 spec（本文），但拆成两份可独立 TDD/verify 的实施计划：**

### Package 2A — Identity & Market Facts（先做，spine first）

让 Match 成为带解析身份的跨通道对象，并挂上 typed 市场事实。这是 Package 3 决策环唯一的硬依赖。

- **Identity**：Competition/CompetitionEdition、Team、Venue、Match/MatchRevision、
  ExternalIdentifier、EntityAlias、TeamAppearance；identity resolver（provider-ID 优先）。
- **Market**：MarketDefinition/SelectionDefinition、MarketQuote、MarketSnapshot（去水 fair）。
- **Actions**：`UpsertProvisionalEntity`、`LinkExternalIdentifier`、`ProposeIdentityLink`、
  `MergeEntity`、`RecordMatch`、`RecordMarketQuote`、`BuildMarketSnapshot`（确定性）。
- **端到端**：把体彩盘（sporttery）+ 一路国际欧赔（bold_odds/500.com）真实快照，经
  `IngestArtifact → 解析 → 身份解析 → MarketQuote → 去水 MarketSnapshot` 全链落库。

### Package 2B — Evidence & Context（2A verify 通过后）

让"资讯/阵容/状态/环境"成为带血缘和时效的证据，喂 Package 3 的 EvidenceBundle。

- **Context/People**：Person、RoleAssignment、PersonMatchStatus、LineupEntry。
- **Evidence**：Claim、ClaimStatusEvent、ClaimEvidenceSpan、Observation、（EvidenceBundle 留给
  Package 3 read 层冻结时再建，本包只保证 Observation/Claim 可被引用）。
- **Actions**：`ExtractClaim`、`VerifyClaim`、`DisputeClaim`、`RetractClaim`、`RecordObservation`。
- **接现有适配器**：api_football/soccerdata（阵容/伤停/近况→Observation）、open_meteo（天气→
  Observation）、资讯（→ provisional Claim）、transfermarkt（球员能力→Observation/Person）。

> 本 spec 完整设计 2A+2B；**先只为 2A 写 plan 并 TDD/verify**，2A 结论作为 2B plan 的输入
> （沿用 umbrella §19 "前包验收结论成为后包输入"的同一纪律，落到包内两期）。下游 Package 3/4/5
> 编号不变。

### 明确排除（属 Package 3–5）

- Forecast/Factor/Read、Ticket/Ledger/Settlement、双轴评分、RegimeVector；
- EvidenceBundle 冻结与 information_cutoff 语义（Package 3 read 层）；
- 历史 116 Match / 331 Snapshot / 212 Read 的实际迁移与旧写路径关闭（Package 5）；
- 恢复 launchd 调度（Package 5 cutover gate 通过后）。

---

## 2. 核心设计决策

### 2.1 身份解析：provider-ID 优先，禁无日志 fuzzy merge（umbrella §4.1 落地）

解析顺序，逐级降级，**每一步都可审计**：

1. **provider external ID**：来源自带的稳定 ID（api_football fixture/team id、体彩竞彩号+业务日、
   足彩期号+序号）→ 命中 `ExternalIdentifier(provider, external_id)` 直接 resolve 到 survivor 实体。
2. **策展 alias**：命中 `EntityAlias(normalized_alias, provider?)`（复用现有
   `jczq_club_team_aliases.json` / `jczq_national_team_aliases.json` / `jczq_league_aliases.json`
   种子）→ resolve。
3. **受控 fingerprint**：仅在 provider 未给 ID 且 alias 未命中时，用受控指纹（normalized name +
   country + team_kind + competition edition 上下文）**提出** `ProposeIdentityLink` 候选，
   **不自动合并**——落 provisional 实体，进人工/主循环 review 队列。

**硬规则**：
- 未解析 = 建 `resolution_status='provisional'` 的真实实体（**绝不 null**，修 umbrella §1.3B）；
  知识覆盖低 ≠ 不存在。
- 任何 `MergeEntity` 是显式、可撤销 Action：不删历史行，旧引用经 redirect view 解析到 survivor；
  merge 带 `reason + evidence_retrieval_ids + actor + reversible`。
- 无 `MergeEntity`/`ProposeIdentityLink` 记录的 fuzzy 合并**禁止**（umbrella §16 首要风险：身份误合并）。

### 2.2 真实开赛时间（修 §1.3C 的两个 bug）

- **`MatchRevision.scheduled_at` 存真实开赛时刻**，未知则显式 `scheduled_at=NULL + schedule_status=
  'unknown'`，**绝不用抓取时间/`taken_at` 冒充**（现 `sense.py` 的 `kickoff_at=snapshot.taken_at` 废弃）。
- 体彩 `matchTime` 解析必带**世界杯时区陷阱防护**（memory 实证）：竞彩"周X0NN"场的 matchTime
  （01:00/05:00…）是北京【次日】凌晨。解析器按体彩业务日 + matchTime 推真实 UTC/北京开赛时刻，
  并落 `ExternalIdentifier(provider='sporttery', external_id=竞彩号, valid_from=业务日)`。
- canonical `match_id` 是**内部 opaque id（不含队名/日期）**；竞彩号/足彩期号/api_football id 全进
  `ExternalIdentifier`（修 §1.3C：字符串身份随别名/日期口径漂移）。

### 2.3 市场事实：复用确定性去水，包在 typed Action 里（umbrella §4.4/§12.2）

- **复用** `nutmeg.decision.market_data` 的纯函数（`devig` / `fair_1x2` / `_had_from_pool` /
  `_ttg_from_pool` / `_crs_from_pool` / `snapshots_from_sporttery` / `euro_snapshot_from_bold_odds`）
  作为**确定性 Observation/Snapshot 生成器**，挂 `method_version`；不重写数学，只重接输出到 typed 表。
- `MarketDefinition`（had/hhad/ttg/crs…，带 `settlement_scope` 90'/含加时/点球）+
  `SelectionDefinition`（outcome_key + line）统一玩法口径（修 umbrella §体彩 hhad 3 路 ≠ 亚盘）。
- `RecordMarketQuote`：把单条报价（provider/bookmaker/decimal_odds/captured_at）落 `MarketQuote`，
  引用其 `ArtifactRetrieval`。
- `BuildMarketSnapshot`（**deterministic_system** actor）：对一场一玩法，从 quotes 去水产
  `MarketSnapshot`（fair_distribution + devig_method/method_version + coverage/freshness/disagreement）；
  `snapshot_kind ∈ read_time|closing|intermediate`，带 `as_of`。
- **赔率不是资金流**（umbrella §2.4）：Package 2 只产价格/信息状态，无 MarketFlow（除非来源真给成交量）。

### 2.4 证据分级写回（2B，umbrella §2.1/§6.2）

- **Connector/确定性系统**：官方结构化字段（阵容、赛果结构、天气）→ deterministic `Observation`
  （`verification_method='deterministic'|'official'`）。
- **AI Extractor**：资讯/自然语言 → `provisional Claim`（带 `evidence_spans:[{artifact_retrieval_id,
  quote,locator}]`）；**不能**直接产 verified Observation 或自行验证。
- `Claim` 内容不可变；`status` 是投影，每次转换追加 `ClaimStatusEvent`（可重放裁决轨迹）。
- 冲突 Claim 并存并降 evidence quality，不自动挑一条覆盖另一条（umbrella §14.2）。

---

## 3. Object 模型落位（哪些进 2A / 2B，及新表）

migration 3+（沿 Package 1 runner，FK 序、checksum drift）。表组对齐 umbrella §8.1。

### 2A（migration 3 = identity，migration 4 = market）

```text
identity:
  competitions          {competition_id, name, country, kind}
  competition_editions  {competition_edition_id, competition_id, name, country, format,
                         season_label, stage, valid_from, valid_to}
  teams                 {team_id, team_kind, canonical_name, country, resolution_status, created_at}
  venues                {venue_id, canonical_name, country, latitude, longitude, timezone,
                         resolution_status}
  matches               {match_id, current_revision_id}
  match_revisions       {match_revision_id, match_id, version, competition_edition_id,
                         scheduled_at?, schedule_status, venue_id?, status, round_label?,
                         recorded_at, supersedes_revision_id?}
  team_appearances      {team_appearance_id, match_id, team_id, side}
  external_identifiers  {entity_id, entity_type, provider, external_id, valid_from?, valid_to?}
  entity_aliases        {entity_id, entity_type, normalized_alias, language?, provider?}
  entity_merges         {from_id, into_id, entity_type, reason, evidence_retrieval_ids_json,
                         actor_id, at, reversible}

market:
  market_definitions    {market_definition_id, market_kind, settlement_scope, ordered,
                         line_schema?, outcome_schema_version}
  selection_definitions {selection_id, market_definition_id, outcome_key, line?}
  market_quotes         {quote_id, match_id, market_definition_id, selection_id, provider,
                         bookmaker?, decimal_odds, captured_at, artifact_retrieval_id, quote_status}
  market_snapshots      {market_snapshot_id, match_id, market_definition_id, snapshot_kind, as_of,
                         fair_distribution_json, devig_method, method_version,
                         source_coverage_json, freshness_json, disagreement_json}
  market_snapshot_quotes{market_snapshot_id, quote_id}
```

不变量：标准足球 Match 恰有两个 TeamAppearance（一 designated home、一 designated away，中立场保留票面
主客角色），避免 Match↔TeamAppearance 双向 FK 环（umbrella §4.1）。

### 2B（migration 5 = context，migration 6 = evidence）

```text
context:
  persons               {person_id, canonical_name, birth_date?, nationality?, resolution_status,
                         created_at}
  role_assignments      {role_assignment_id, person_id, team_id, role_type, position_group?,
                         valid_from, valid_to?, source_observation_id}
  person_match_statuses {person_match_status_id, match_id, person_id, team_appearance_id,
                         availability, status_kind, valid_from, valid_to?, observation_id}
  lineup_entries        {lineup_entry_id, match_id, person_id, team_appearance_id, lineup_status,
                         role, position?, shirt_number?, captain, observed_at, observation_id}

evidence:
  claims                {claim_id, subject_type, subject_id, predicate, value_json, scope_match_id?,
                         valid_from, valid_to?, status, extractor, extractor_version, created_at,
                         adjudicated_at?}
  claim_status_events   {claim_id, from_status, to_status, action_id, at}
  claim_evidence_spans  {claim_id, artifact_id, artifact_retrieval_id, quote, locator}
  observations          {observation_id, observation_type, subject_type, subject_id, scope_match_id?,
                         value_json, schema_version, valid_from, valid_to?, observed_at, recorded_at,
                         verification_method, quality_json}
  observation_sources   {observation_id, artifact_retrieval_id}
  observation_claims    {observation_id, claim_id}
```

高价值关系用 FK/关联表；概率分布、provider payload、quality 等用带 `schema_version` 的 JSON + 应用层
validator（umbrella §8.1）。

---

## 4. 新 Action 与权限（挂 Package 1 内核）

新 action_type 的权限行进 policy（`governance-v1` 增量，或升 `governance-v2`——由 `change_policy`
Action 落，本身受审计）。角色沿 umbrella §6.2 矩阵：

| Action（2A） | 允许 actor | 说明 |
|---|---|---|
| `UpsertProvisionalEntity` | connector, deterministic_system | 建/取 provisional Team/Venue/Competition/Person |
| `LinkExternalIdentifier` | connector, deterministic_system | provider ID → 实体（幂等） |
| `ProposeIdentityLink` | connector, ai_extractor | fingerprint 候选，进 review，不自动合并 |
| `MergeEntity` / `SplitEntity` | judge_operator | 可撤销，带证据；绕不过 validator |
| `RecordMatch` | connector, deterministic_system | 建 Match/MatchRevision + 两 TeamAppearance |
| `RecordMarketQuote` | connector | 单条报价落库 |
| `BuildMarketSnapshot` | deterministic_system | 去水产 fair snapshot（禁选方向、禁嘴算） |

| Action（2B） | 允许 actor | 说明 |
|---|---|---|
| `RecordObservation` | connector, deterministic_system | 官方/确定性字段 → typed Observation |
| `ExtractClaim` | ai_extractor | 资讯 → provisional Claim（带 evidence span） |
| `VerifyClaim` | deterministic_system（满足官方/交叉验证 policy）, judge_operator | Claim 裁决 |
| `DisputeClaim` / `RetractClaim` | judge_operator | 裁决，不覆盖原主张 |

每个 handler 复用 Package 1 `ActionService.execute`：权限→accepted→handler 业务写→committed 原子同提；
乐观并发 `expected_versions`（Package 1 已备但休眠）在此**首次被激活**——Match/MatchRevision 修订、
Claim 状态转换用 expected version 拒绝冲突写。

---

## 5. 复用地图（现有资产 → 落点）

| 现有资产 | Package 2 落点 |
|---|---|
| `nutmeg/data/*`（api_football, european_odds, fcom500, the_odds_api, open_meteo, soccerdata, transfermarkt） | ingest adapter：`IngestArtifact` 落原文 → 确定性解析产 Quote/Observation/Claim；WAF/降级经验保留 |
| `decision/market_data.py`（devig/fair/pool 解析/snapshots_from_sporttery/euro_snapshot） | 确定性市场数学，挂 `method_version`，重接到 typed MarketQuote/Snapshot |
| `jczq_*_aliases.json` × 4 | `EntityAlias` 种子（migration 幂等落，resolver 第 2 级用） |
| `decision_entities_seed.json` | Team/League `profile_notes` 迁 Observation/画像输入，不再是唯一可建实体集合 |
| `decision/identity.canonical_match_id`（字符串拼接） | **废弃**，由 opaque match_id + ExternalIdentifier 取代 |
| `sense.py` 的 `kickoff_at=taken_at` | **废弃**，由真实 `scheduled_at` 解析取代 |

Package 2 的 sense 相关代码是**新 typed action handler + analytics projector**（umbrella §12.2 "重写
sense/read_ingest/..."），不在旧 `decision/store.py`（JSONL）上补丁。

---

## 6. 血缘与时态纪律（Package 2 段）

- 每条 `MarketQuote`/`Observation` 必引用 `ArtifactRetrieval`（→ CAS 原文）；无原文不产 typed 事实。
- 四种时间不混用（umbrella §5.1）：`valid_from/to`（世界事实有效期）、`published_at`（来源公开）、
  `retrieved_at/recorded_at`（Nutmeg 何时知道）、`scheduled_at`（真实开赛）。
- `MarketSnapshot.as_of` 与 `snapshot_kind` 精确：read_time/closing 按 as-of + market/line 匹配
  （为 Package 3 CLV 铺路，但 CLV 计算本身属 Package 4）。
- 失败源不静默假空：`SourceRun` 标 complete/partial/stale/unavailable（复用 Package 1 `source_runs`），
  旧 Observation 保留标 stale，不被空响应覆盖（umbrella §14.1 不变量 1）。

---

## 7. 验收硬门（Package 2A → 2B）

### 2A 验收（全绿方可开 2B plan）

1. 一个真实竞彩日 replay（沿 Package 1 verify 同法：拷生产快照到临时目录、本分支代码、只读生产）：
   - 每场 Match 有**真实 `scheduled_at` 或显式 `unknown`**，无 `taken_at` 冒充；
   - 每方都有 resolved 或 provisional Team 节点，**无 silent null identity**；
   - 竞彩号/欧赔 provider id 全进 `ExternalIdentifier`；跨通道（竞彩+足彩）同场经 provider id/alias
     合并为**同一 opaque match_id**；
   - had/hhad/ttg/crs `MarketSnapshot` 带去水 fair、method_version、coverage/freshness；
   - 每条 Quote/Snapshot 可沿血缘回到 `ArtifactRetrieval` → CAS 原文。
2. `MergeEntity`/`SplitEntity` 幂等且可撤销；无日志 fuzzy merge 被测试证明**不发生**。
3. 时态泄漏测试：snapshot 按 as-of/market/line 精确匹配；provider-id 优先解析确定性。
4. 全仓 `ruff check .` + `uv run pytest` 全绿；Package 2 表经 reopened engine 复核 schema。

### 2B 验收

1. 同日 replay 追加：阵容/伤停/天气 → typed Observation（带 verification_method）；资讯 → provisional
   Claim（带 evidence span）；冲突 Claim 并存降质，不自动覆盖。
2. `VerifyClaim`/`DisputeClaim`/`RetractClaim` 落 `ClaimStatusEvent`，可重放裁决轨迹。
3. AI 角色**不能**产 verified Observation / 自行 commit（权限测试证明）。

---

## 8. 风险与保险栓（Package 2 段，承 umbrella §16）

| 风险 | 保险栓 |
|---|---|
| 身份误合并 | provisional 实体 + provider-id 优先 + `ProposeIdentityLink` review 队列 + 可撤销 `MergeEntity` |
| 时区/轮次陷阱（体彩"周X0NN"= 北京次日） | 解析器内建业务日+matchTime→真实开赛推算，带回归测试（memory 实证 fixture） |
| hhad 3 路误按亚盘口径 | `MarketDefinition.settlement_scope` + 双泊松去水 fair 重算 3 路（禁嘴算，复用 market_data） |
| 领域表膨胀 | 对象晋升判据（umbrella §2.2）；罕见字段留 typed Observation payload；2A/2B 各限对象面 |
| AI 把叙事写成事实 | provisional Claim + evidence span + 权限矩阵 + `VerifyClaim` gate（2B） |
| 破坏 Package 1 内核语义 | 只加领域 handler/表，不改内核；每步复用 `ActionService.execute` 并跑 Package 1 回归 |

---

## 9. 后续顺序

1. 用户审阅本 spec，确认 **2A/2B 拆分**与 **2A 先行**的 scope；
2. 调用 `writing-plans`，只为 **Package 2A — Identity & Market Facts** 写实施计划（TDD，逐任务）；
3. 2A 按 TDD 实施 + 独立 verify（真实竞彩日 replay）；
4. 2A 验收结论作为 **Package 2B** plan 输入；
5. 2B 完成后，Package 2 整体验收（umbrella §15.2 相关门），再进 Package 3。

> 关联：`2026-07-20-ontology-kernel-v2-design.md`（umbrella §4/§5/§6/§7/§8/§13/§16）·
> `2026-07-21-ontology-kernel-v2-package-1.md`（已交付内核接口）·
> `docs/ontology-kernel-operations.md`（Package 1 运营契约）。
