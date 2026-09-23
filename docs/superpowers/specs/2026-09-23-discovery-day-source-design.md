# Discovery 试点输入改接决策泳道（day source）· 设计

日期：2026-09-23 ｜ 状态：Jun 裁定方案 A（退役 8788 应用，Discovery 输入改接决策泳道对象）｜ 后续：writing-plans
依赖：Discovery Harness D0–D7（已落地）、深研桥 + 表态块（`jczq-legs-base.json` / `reads.json` 每日产出）、`sporttery_markets.json`（`decision.am` 08:00 产出）。

## 0. 一句话

Discovery 的「一个世界」不再从 operator_v2 内核表读（那条写入链只存在于已退役的 8788 网页端，生产表 0 行），改从**当天决策泳道的三份文件**冻结：板面 + 表态、草稿/已批 Read、体彩终盘。生成器、审计器、回放、锦标赛、封存、判决全部不动。

## 1. 出生事故

- 试点契约 `structural-candidate-v1` 的世界输入 = 生成请求 → 处方 → 判断 → 候选集（`operator_candidate_*` 表）。调查（2026-09-23）：这些行只由 `POST /api/v2/operator` 与其 worker 写入；仓里没有 CLI 生产者；在售清单 manifest 无生产者；生产库 0 行。第一个真实世界从 D0 起就到不了。
- 与此同时，决策泳道每天都在产出同一批事实：`jczq-legs-base.json`（每场 fair / 表态面集合 / 标签）、`reads.json`（belief / prior / 作废条件）、`sporttery_markets.json`（体彩 had 赔率）。这正是 `CandidateGenerationInput` 需要的全部：offers（面、概率、报价）+ templates（pass-N-1）。

## 2. 映射

| `CandidateGenerationInput` / 快照字段 | 来源 | 规则 |
| --- | --- | --- |
| `lane` / `ticket_kind` | 常量 | `jczq` / `jczq_pass` |
| `capital_cap_minor` / `unit_stake_minor` | 常量 | ¥2,000 日帽 → 200000 分；单注 ¥2 → 200 分（RULEBOOK 日帽） |
| `maximum_ticket_count` / `maximum_exhaustive_candidate_count` | 试点契约 | 20 / `budgets.max_candidate_generation_count` |
| `offers[]` | legs-base ∩ reads | 只收有 Read 的场；`official_match_no`=板面代码；`official_offer_revision_id`=`{day}:{code}:had`；`market_definition_id`=`md-had`（与 `_SUPPORTED_SETTLEMENT_MARKETS` 同一口径，否则审计把每条腿标为不支持）；`probabilities`=Read.belief；`allowed_face_bundles`=表态面集合本身 + 其中每个单面；`omission_allowed`=True；`quote_ids_by_face`=`sporttery:{day}:{code}:had:{face}`；`booked_decimal_odds_by_face`=体彩 `had.h/d/a` |
| `templates[]` | 板面大小 | `pass-N-1`，N = 2 … min(板面场数, 1 + `max_templates`)，`max_templates` 默认 4（试点 `max_concurrency`） |
| `audit_offers[]` | legs-base 标签 + reads | `_CandidateAuditOffer(belief, prior, prescribed_face_bundles={表态面集合}, rule_ids=(), anchor_integrity, face_precedents)` |
| `references[]` | 三份文件 | `forecast` 每条 Read（id=read_id，source_revision=`{status}:{sha256}`，captured_at=made_at）；`prescription`（id=`{day}:legs-base`，sha256，captured_at=文件 mtime BJT）；`quote` 每个报价（captured_at=`had.updateDate+updateTime` BJT） |
| `business_date` / `slate_revision_id` / `task_snapshot_hash` | day / markets / legs-base+reads | `slate_revision_id`=`day:{day}:{sha256(markets)[:16]}`；`task_snapshot_hash`=sha256(legs-base ∥ reads) |
| `audit_policy_revision` | 常量 | 与 worker 同一 `operator-candidate-audit-v1` |
| 概率量化 | Read.belief | 三面各 6 位小数，余数补到最大面，和恰为 1（`OfferCandidateInput` 硬约束） |
| `source_identity` | 目录 | `day:{绝对路径 jczq_dir/daily/day}` |

面码用生成器的口径（`3/1/0`），实现时以 `operator_candidates` 内部的面码常量为准。

## 3. 录制器的 day 源

`record_shadow_world(..., source_kind="database"|"day")`：
- `database`（保留到 operator_v2 内核退役为止）：现行逻辑不变。
- `day`：`source_database` 参数改传**当天目录**；指纹 = 三份文件 sha256 的并集；独立复核 = 用同一 `cutoff_at` 重新 `read_structural_input_from_day` 并比对 `manifest_hash`；`generation_request_id` 用 `day:{day}` 占位进 approval scope（scope 键不变，减少改动面）。
- 其它守则不变：shadow 库不得在生产目录、批准文件 ≤24h、cutoff 前瞻、baseline 由批准人登记、`max_nodes` 预算、`shadow_only`。

## 4. CLI

`nutmeg discovery shadow-run` 加互斥输入：`--source-day <YYYY-MM-DD> [--jczq-dir .nutmeg-data/jczq]` 与既有 `--source-db + --generation-request-id`。approval scope 里 `source_db` = 当天目录绝对路径，`generation_request_id` = `day:<date>`。

## 5. 后续（不在本 spec）

- 第一个真实世界录完、`nutmeg discovery status` 出现 `sealed_worlds ≥ 1` 后，退役 operator_v2 内核残余：`product/jczq_*`、`operator_{contracts,lanes,artifacts,legacy_import}`、`workflow jczq-*` 命令；把 `operator_candidates.enumerate_band_candidates` 与 `operator_workers._audit_candidate/_CandidateAuditOffer` 搬进 `nutmeg/discovery/`。
- 契约 `authoritative_workflow.generator` 指向搬家后的路径要重冻结 hash（走 D7 契约修订，不静默改）。

## 6. 出口条件

前提：当天至少两场同时有 Read 与体彩 **had** 报价（只开让球盘的场不进 had 世界，2026-09-23 的日本 U21 就是例子）。

某天 12:00 后：`uv run nutmeg discovery shadow-run --source-day <今天> --shadow-db <仓外> --cutoff-at <现在> --approval-file <批准>` 成功，`discovery status` 显示 1 个 sealed world，输入 manifest 含当天全部 Read 与报价引用；生产目录三份文件字节未变。
