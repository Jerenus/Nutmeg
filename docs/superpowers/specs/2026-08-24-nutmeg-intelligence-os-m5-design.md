# Nutmeg Intelligence OS M5 - Settlement, Learning, and Scoreboard Design

Date: 2026-08-24
Status: Approved by the program architecture and the operator's continuous implementation authorization
Scope: M5 only; M1-M4 remain closed unless a regression is found

## 1. Outcome

M5 closes the loop from settled operational truth to measured learning. It adds three
formal product workspaces and one governed authority migration:

1. Settlement and Review Center separates forecast truth, money ledger, and
   intervention quality;
2. Rule and Calibration Center exposes factor estimates and lifecycle proposals while
   preserving human-only lifecycle changes;
3. Ontology Browser provides allowlisted object search, typed detail, lineage, Action
   history, and `as_of` replay without raw SQL;
4. Scoreboard migration turns manual review metrics into attributable ontology objects,
   rebuilds deterministic metrics from operational truth, compares them in shadow, and
   permits a human Action to switch authority only when every difference is classified.

M5 does not fetch results, place tickets, call an AI provider, dispatch Telegram, enable
a connector, or alter production schedules. Verification uses fixture and copied data
roots only. The feature branch proves an isolated authority switch but does not mutate
the production `.nutmeg-data/scoreboard.json`.

## 2. Locked constraints

- Operational truth remains in SQLite; DuckDB remains a disposable projection store.
- Existing Brier, CLV, attribution, settlement, and ledger functions remain the only
  implementations. Product code reads their outputs and performs no replacement math.
- Forecast quality, money result, and intervention quality are never collapsed into one
  score or recommendation rank.
- Missing outcome, closing quote, evidence, or intervention labels reduce coverage; they
  never become zero, loss, success, or implied certainty.
- A counterfactual is eligible only when its alternative was durably recorded before the
  current Outcome. M5 never invents a hindsight alternative.
- Calibrate may propose lifecycle changes but cannot apply them. Only the existing
  judge-only `apply_factor_status` Action changes a FactorDefinition.
- A legacy scoreboard metric cannot enter the new authority as an opaque import. Each
  retained manual metric is a typed, attributable `ScoreboardObservation` with evidence.
- Scoreboard cutover is a human-only Action. It requires the exact latest legacy hash,
  a successful current shadow review, zero unexplained differences, and a current
  projection high-water mark.
- Once ontology authority is active, `scoreboard.json` is generated compatibility output.
  A changed file is detected as drift; it is never ingested back silently.
- Product JavaScript performs no scoring, settlement, ledger, projection, or lifecycle
  arithmetic.

## 3. Considered approaches

### 3.1 Add read-only review pages and leave JSON authoritative

This reuses current analytics with little persistence work, but it leaves review edits
outside Actions and creates a permanent dual authority. It is rejected.

### 3.2 Store the legacy JSON as one ontology artifact

This preserves bytes and lineage but does not make the counters queryable, attributable,
or reproducible. It would relabel an opaque document as an ontology without changing its
semantics. It is rejected.

### 3.3 Govern manual observations and rebuild deterministic projections

This is selected. Manual-only knowledge becomes a versioned source object through an
Action; metrics with operational sources are rebuilt. A shadow review classifies exact
matches, formal manual observations, source corrections, and unexplained differences.
Only a clean review can be approved. The approach adds a small migration and explicit
operator workflow, but it satisfies single-track authority and remains replayable.

## 4. Score planes

### 4.1 Forecast truth

The plane reads existing `forecast_scores` and `forecast_scorecards` projection rows:

- sample and outcome coverage;
- Brier and prior-relative skill;
- closing coverage and closing-skill relationship;
- calibration buckets and legacy-unbundled coverage.

Every metric carries projection name/version, source high-water mark, built time,
cohort version, and metric version.

### 4.2 Money ledger

The plane reads operational Ticket, BetLegSettlement, TicketSettlement, CashTransaction,
and account rows, plus the existing `action_finance` scorecard:

- tickets, settled/open counts, stake, payout, P/L, and ledger balance;
- settlement status/method and exact ticket/leg lineage;
- ledger-conservation and duplicate-settlement state.

P/L never substitutes for Brier or intervention quality.

### 4.3 Intervention quality

The plane reads Adjudication, Prediction, FlagInstance, Forecast revision, and Outcome
objects. It reports counts and coverage before reporting rates. A record is scoreable
only when its subject and outcome can be linked without guessing.

The first version reports:

- Adjudication counts by decision, with rejected-evidence coverage;
- Prediction confirmed/refuted/void/pending counts;
- FlagInstance counts by type/status/direction and linked-outcome coverage;
- preregistered alternative coverage and replay results where a valid probability
  distribution was recorded before the Outcome.

Unsupported historical prose remains `unscored`; it is not parsed into synthetic facts.

## 5. Counterfactual replay

A counterfactual candidate is an Adjudication alternative containing:

```json
{
  "counterfactual": {
    "market_definition_id": "md-had",
    "distribution": {"home": 0.5, "draw": 0.3, "away": 0.2},
    "label": "keep market prior"
  }
}
```

The review projector validates the three-way distribution with the existing probability
contract and accepts it only when `adjudication.created_at <= outcome.recorded_at`. It
uses the existing Brier primitive against the current versioned Outcome and records the
source Adjudication, Outcome, metric version, and eligibility reason. Invalid, late, or
unlinked alternatives are returned with an explicit exclusion code and no score.

Outcome corrections rebuild this projection against the new current Outcome while prior
versions remain inspectable through ontology lineage.

## 6. Scoreboard ontology and migration 13

Migration 13 adds three tables.

```text
scoreboard_observations
  scoreboard_observation_id TEXT PK
  group_key TEXT NOT NULL
  metric_key TEXT NOT NULL
  tally TEXT NOT NULL
  detail TEXT NOT NULL
  status TEXT NOT NULL
  numerator REAL NULL
  denominator REAL NULL
  value REAL NULL
  unit TEXT NULL
  evidence_refs_json TEXT NOT NULL
  effective_at TEXT NOT NULL
  recorded_at TEXT NOT NULL
  supersedes_observation_id TEXT NULL FK self RESTRICT
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT

scoreboard_shadow_reviews
  scoreboard_shadow_review_id TEXT PK
  legacy_source_artifact_id TEXT NOT NULL FK source_artifacts RESTRICT
  legacy_sha256 TEXT NOT NULL
  projection_version TEXT NOT NULL
  source_high_watermark INTEGER NOT NULL
  classification_json TEXT NOT NULL
  matched_count INTEGER NOT NULL
  manual_count INTEGER NOT NULL
  corrected_count INTEGER NOT NULL
  unexplained_count INTEGER NOT NULL
  status TEXT NOT NULL
  reviewed_at TEXT NOT NULL
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT

scoreboard_authority
  authority_id TEXT PK CHECK authority_id = 'primary'
  state TEXT NOT NULL                    # legacy | ontology
  projection_version TEXT NULL
  source_high_watermark INTEGER NULL
  legacy_sha256 TEXT NULL
  shadow_review_id TEXT NULL FK scoreboard_shadow_reviews RESTRICT
  compatibility_export_sha256 TEXT NULL
  approved_at TEXT NULL
  approved_by_action_id TEXT NULL FK actions RESTRICT
  version INTEGER NOT NULL
```

Migration 13 seeds only the singleton authority row in `legacy` state and grants
`record_scoreboard_observation` and `approve_scoreboard_cutover` to `judge_operator`.
It grants `record_scoreboard_shadow_review` and `record_scoreboard_export` only to
`deterministic_system`. AI receives none of these permissions.

## 7. Governed scoreboard workflow

### 7.1 Formalize manual-only metrics

`RecordScoreboardObservation` requires group/metric keys, non-empty tally/detail/status,
an effective time, and at least one valid evidence reference. Optional numerator,
denominator, value, and unit are retained as structured data. Revisions supersede rather
than overwrite. A dedicated CLI may import a legacy file only with an explicit
`--acknowledge-manual-source` flag; it emits one judge Action per metric and preserves
the original file as a CAS SourceArtifact.

### 7.2 Build and compare

`ScoreboardProjection` emits deterministic `scoreboard_metrics` rows for the three score
planes, lifecycle state, and the latest valid manual observations. The shadow service:

1. hashes and stores the exact legacy bytes;
2. compares every legacy group/metric to a current formal observation;
3. classifies each item as `matched`, `formal_manual`, `source_correction`, or
   `unexplained`;
4. records the projection watermark and a canonical comparison;
5. commits `RecordScoreboardShadowReview` through the Action service.

No string heuristic is allowed to silently convert a tally into a numeric metric.

### 7.3 Approve and export

`ApproveScoreboardCutover` requires the expected authority version and shadow review ID.
The handler rechecks that the review is current, succeeded, has zero unexplained items,
and matches the supplied legacy SHA and projection watermark. It then changes only the
singleton authority row to `ontology` and emits an outbox event.

The compatibility exporter is deterministic canonical JSON containing:

- schema/authority/projection metadata;
- the forecast, money, intervention, and lifecycle planes;
- manual observations grouped by their stable legacy group/metric keys;
- content hash and generation Action reference.

The writer uses atomic replacement. Verification compares file bytes with the recorded
export hash. Manual edits produce `scoreboard_export_drift`; they are not imported.

## 8. Product contract

M5 adds these read endpoints under `/api/v1`:

```text
GET /review?as_of=...
GET /calibration?as_of=...
GET /ontology/objects?type=...&q=...&after=...&limit=...
GET /ontology/objects/{object_type}/{object_id}?as_of=...
GET /scoreboard?as_of=...
```

The API paths are:

```text
GET /api/v1/review
GET /api/v1/calibration
GET /api/v1/ontology/objects
GET /api/v1/ontology/objects/{object_type}/{object_id}
GET /api/v1/scoreboard
```

The existing generic Action endpoint handles lifecycle and manual-observation Actions.
Dedicated scoreboard shadow/cutover/export operations remain CLI-only in M5 because they
operate on local files and authority policy; the browser cannot switch authority.

All DTOs are strict and versioned. DuckDB absence or stale projection returns a degraded
plane with a rebuild instruction, while operational settlement and ontology browsing
remain available.

## 9. Workspace experience

### 9.1 Settlement and Review Center

`/review` opens with three parallel score-plane bands, followed by a dense settlement
ledger and a preregistered-counterfactual table. It exposes coverage and provenance next
to every metric. Empty/unsettled states are explicit.

### 9.2 Rule and Calibration Center

`/calibration` shows projection health, factor estimates with interval/sample/cohort,
lifecycle proposals, current states, and regime summaries. Each proposal has a human
apply/reject form. Apply uses the existing `apply_factor_status` Action and requires a
reason-bearing Adjudication link; AI and browser payloads cannot choose actor role.

### 9.3 Ontology Browser

`/ontology` provides allowlisted type filters, stable cursor pagination, object identity,
properties, links, versions, source lineage, and Action history. It never renders raw
table names, accepts SQL, or exposes secret/blob bytes. Historical `as_of` is visible and
enforced server-side.

The existing ledger/editorial visual language remains. Desktop favors scan density;
narrow screens preserve document order, 44-pixel controls, visible focus, and wrapping
for IDs/hashes. No decorative dashboard cards or client-side scoring are introduced.

## 10. Failure and concurrency behavior

- Missing DuckDB returns operational truth with `projection_unavailable`, not a 500.
- A failed projection build keeps the last good version and surfaces the failed run.
- A stale lifecycle proposal is rejected when the Factor status no longer matches.
- An AI lifecycle or scoreboard Action is rejected and audited.
- A late or invalid counterfactual is visible but never scored.
- Duplicate manual observation/import Actions replay by idempotency key.
- A stale authority version or review watermark returns a conflict.
- An unexplained shadow difference blocks cutover.
- Export interruption leaves the prior complete file intact.
- Export drift blocks overwrite until the operator explicitly inspects the difference.
- Outcome correction rebuilds score planes without changing operational ledger history.

## 11. SOP and authority rollout

The production SOP trilogy is currently user-owned and untracked in the main workspace.
M5 must not copy or overwrite those files from this feature worktree. The implementation
therefore ships an operations contract and a deterministic SOP authority checker with
the exact required post-cutover statements:

- ontology objects/projections are the Scoreboard authority;
- `scoreboard.json` is generated read-only compatibility output;
- daily reconcile/calibrate rebuilds and exports it;
- manual review facts enter through `RecordScoreboardObservation`;
- direct JSON edits are an error.

The production cutover command refuses to run until the checker sees those statements in
CONSTITUTION, RUNBOOK, RULEBOOK, AGENTS, and CLAUDE. Tests use fixture copies. This keeps
the code and migration complete without mutating user-owned production documents.

## 12. Verification strategy

M5 follows RED-GREEN-REFACTOR for every behavior. Coverage includes:

- migration 13, permissions, idempotency, rollback, and optimistic authority version;
- exact three-plane values against existing authoritative functions;
- missing/late/corrected outcome and counterfactual eligibility;
- lifecycle proposal cannot mutate state; judge Action can; AI cannot;
- manual observation revision/evidence validation;
- shadow classification, unexplained block, clean isolated cutover, canonical export,
  atomic replacement, and drift detection;
- strict DTO/API/security and no raw SQL/blob exposure;
- review/calibration/ontology desktop and narrow UI states;
- full Ticket placement -> Outcome -> Settlement -> projection -> lifecycle proposal ->
  human lifecycle Action -> compatibility export E2E;
- frozen M4-store migration/rebuild with unchanged source hash;
- full pytest, Ruff, compileall, all hooks, browser evidence, and project `verify` replay.

## 13. Explicit non-goals

M5 does not enable production schedules, perform a production authority switch, invent
historical evidence, import opaque counters without an Action, add live connectors,
implement autonomous lifecycle changes, or issue ReleaseApproval. Backup/restore drills,
14-day soak evidence, performance targets, broad fault injection, schedule authority,
and final release approval belong to M6.
