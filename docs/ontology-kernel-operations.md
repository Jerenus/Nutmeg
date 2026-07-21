# Ontology Kernel v2 — Package 1 Operations Contract

> Status: **Package 1 foundation only — not the v2 cutover.** The kernel here is
> the transactional write boundary (SQLite operational database, content-
> addressed artifact store, typed Actions, permissions, migrations). It creates
> **no** football-domain objects (Match/Team/Person/Forecast/Ticket) — those
> arrive in Packages 2–5. The existing five-verb `decision` commands remain the
> current production interface until the Package 5 cutover; the decision
> schedules are intentionally paused during the approved rebuild and must not be
> re-enabled until the cutover gates pass.

Design: `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md`
· Plan: `docs/superpowers/plans/2026-07-21-ontology-kernel-v2-package-1.md`

## 1. Scope

Package 1 gives you a correct, auditable **write path** and nothing more. If a
command or object is about football facts, forecasts, tickets or scoring, it is
not part of Package 1.

## 2. Filesystem paths and ownership

The kernel owns exactly one tree under the application `data_dir`
(`NUTMEG_DATA_DIR`, default `.nutmeg-data`):

```text
.nutmeg-data/ontology/ontology.db                         # operational SQLite (WAL)
.nutmeg-data/ontology/artifacts/sha256/<first-2>/<digest> # immutable evidence blobs
```

It is deliberately separate from `state/state.db` (notification/client state) and
`analytics/analytics.duckdb`. `ensure_directories` creates only `ontology/` and
`ontology/artifacts/`; it never creates the database file.

## 3. `ontology init` and idempotency

```bash
uv run nutmeg ontology init --format json
```

`init` creates the owned directories and applies pending numbered migrations. It
is idempotent: a second run applies nothing (`applied_versions == []`) and leaves
the schema at its current version. `init` exits `2` on an invalid `--format`.

## 4. `ontology status` — read-only health / exit-code contract

```bash
uv run nutmeg ontology status --format json
```

Contract: **status never initializes or migrates the database.** When the
database file is absent it reports `initialized=false`, `schema_version=0`, and
does not create the file. When present it runs `PRAGMA integrity_check`, reads
the migration high-water mark, and counts Actions/artifacts/retrievals. Exit code
is `1` when the kernel is uninitialized or integrity is not `ok`, otherwise `0`;
an invalid `--format` exits `2`. The same read-only status is surfaced in
`nutmeg doctor` (JSON `ontology` block plus a text line) without initializing it.

## 5. Action roles and deny-by-default permissions

Every formal write is an Action carrying an actor role. Permissions are stored as
versioned policy rows and enforced **deny-by-default**: a role may execute an
action type only when an explicit permission row exists under an *active* policy
version — there is no fallback to another policy or role.

Package 1 seeds `governance-v1` with:

| Action | Allowed roles |
|---|---|
| `ingest_artifact` | `connector`, `judge_operator` |
| `change_policy` | `judge_operator` |

`ai_extractor`/`ai_analyst`/`deterministic_system` are **not** granted
`ingest_artifact`; any future need must arrive through an explicit policy Action,
not a pre-granted role. AI roles cannot write verified facts — Claim state and its
verification arrive in Package 2.

## 6. Artifact CAS immutability and orphan-blob safety

Raw evidence is content-addressed by SHA-256 and written once. Publication is
atomic (fsynced temp file, then `os.link` — never a clobbering `rename`); a
re-fetch of identical bytes adds an `ArtifactRetrieval` row, never a second blob.
A database failure *after* a blob is published may leave an unreferenced hash
blob on disk; this is safe and reusable, and no cleanup is attempted inside the
failed transaction. Blobs are never edited in place.

## 7. Backup sequence

1. stop the writers (decision schedules and any zucai/jczq writer);
2. copy `.nutmeg-data/ontology/ontology.db` and the `artifacts/` tree;
3. hash the copy (`shasum -a 256`) into a manifest;
4. resume writers only when explicitly authorized.

## 8. Prohibited operations

Do not edit `ontology.db` with ad-hoc SQL and do not edit or delete artifact
blobs by hand. All writes go through typed Actions on the repository/unit-of-work
layer so that business rows and the Action audit log commit atomically.

## 9. Later packages and current non-goals

Packages 2–5 add the football world & evidence, the decision & finance loop,
learning & regime analytics, and the evidence migration & cutover. Until then:
no Claim/Observation/Forecast/Ticket, no DuckDB scoring, and no legacy data
migration live behind this kernel.

## 10. Package 2A — Identity & Market Facts

Package 2A turns a Match into a cross-channel object with resolved identities and
typed market snapshots. Design:
`docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-2-design.md`.

**Identity.** Teams/venues/competitions/matches carry opaque ids; provider ids
(sporttery matchId, api-football ids) live in `external_identifiers`. Resolution
is **provider-id-first, then curated alias** (seeded from `jczq_*_aliases.json`);
an unresolved entity becomes a `provisional` row — **never null, never guessed
from a team-name string**. `MergeEntity` (judge_operator only) records a
reversible tombstone; `redirect` follows merges to the survivor. A `matchId`
uniquely identifies a sporttery match; `matchNumStr` ("周日104") is the per-day
cross-channel key international odds align to.

**Real schedule.** `MatchRevision.scheduled_at` is the true kickoff (sporttery
`matchDate` + `matchTime`, Beijing), so an early-morning game lands on the next
calendar day — never the ingestion time. Unknown times are explicit
(`schedule_status='unknown'`).

**Market.** `MarketDefinition` carries an explicit `settlement_scope`;
`BuildMarketSnapshot` (deterministic_system) records quotes and de-vigs the fair
distribution by reusing `nutmeg.decision.market_data.devig`.

**Ingest a saved market day** (idempotent):

```bash
uv run nutmeg ontology ingest-market-day --business-date <YYYY-MM-DD> \
  --sporttery <path/to/sporttery_markets.json> [--intl <path/to/bold_odds.json>] --format json
```

It initializes the kernel if needed, upserts teams, records matches with real
schedules, and de-vigs had snapshots; international odds align to the same opaque
match by sporttery match number. `nutmeg ontology status` then reports
`team_count`/`match_count`/`quote_count`/`snapshot_count`.

## 11. Package 2B — Evidence & Context

Package 2B adds the people layer and graded evidence. Design:
`docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-2-design.md`.

**People.** Person resolution reuses 2A's provider-id-first resolver over the
shared external-identifier/alias tables — provisional, never null.
PersonMatchStatus is observation-backed (每个状态回到一条 Observation).

**Graded write-back.** Connectors/deterministic systems record official/
deterministic **Observations**; AI extractors record only **provisional Claims**
with evidence spans and can never record a verified fact or self-verify. Claim
content is immutable; verify/dispute/retract (operator only) append a replayable
`claim_status_events` trail. **Conflicting claims for the same subject coexist —
nothing is auto-overwritten.**

**Ingest a saved evidence day** (idempotent):

```bash
uv run nutmeg ontology ingest-evidence-day --business-date <YYYY-MM-DD> \
  --availability <path> [--weather <path>] [--news <path>] --format json
```

Availability rows become upserted persons + observation-backed match statuses,
weather becomes observations, news becomes provisional claims. Rows that cannot
attach to a known match are **counted as skipped** and printed — standalone the
match map is empty, so Package 3 chains market-day and evidence-day to attach
evidence to real matches. `nutmeg ontology status` then also reports
`person_count`/`observation_count`/`claim_count`. Together with 2A this closes
umbrella Package 2 (Football World & Evidence).

## 12. Package 3A — Belief Layer

Package 3A adds the read verb: turning a market prior into an auditable belief.
Design: `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-3-design.md`.

**EvidenceBundle** freezes an as-of input set at a cutoff — only observations whose
`recorded_at <= cutoff` enter (a later-recorded observation, even if published
earlier, cannot — no future leak). A content hash proves "same inputs, same bundle".

**ForecastRevision** anchors `prior` to the market and records `belief`.
`belief = prior` is a legal follow-market commit. When factors move belief, each
`FactorApplication` carries a signed per-outcome delta summing to zero, and **all
factor deltas must reconstruct `belief − prior` exactly** — enforced before commit.
Each series keeps exactly **one current committed revision**; commit/revise inserts
a new revision that supersedes the prior one (UNIQUE(series, revision_no) is the
concurrency guard); withdraw clears the current.

**Graded write-back.** ai_analyst drafts and proposes; **only judge_operator commits,
revises, withdraws, or applies a factor status**. The factor lifecycle here is a
state machine only — the aggregate skill/CLV verdict that justifies a transition is
a Package 4 projection.

The read flow chains it: `kernel.decision_read.read_match(...)` opens a session,
freezes a bundle, and commits a forecast; `nutmeg ontology status` then reports
`forecast_count`/`bundle_count`. Package 3B (Ticket/Ledger/Outcome/Settlement)
follows on 3A's committed-forecast interface; calibrate/scoring is Package 4.

## 13. Package 3B — Finance & Outcome Layer

Package 3B adds the express and reconcile verbs: turning a committed forecast into a
budget-checked, ledger-atomic ticket, then settling it against a match outcome.

**BudgetPolicy** is versioned data, not scattered `if`s — a ¥400 total cap plus
per-bucket caps (main/hedge/draw/parlay). The cap is a **ceiling, not a fill
target**: an empty proposal is a legal no-op, and `kernel.express.approve_for_match`
with no legs writes nothing. Only judge_operator changes a policy.

**Express is atomic.** Every `BetLeg` references the *current committed*
`ForecastRevision` for its match+market — a leg pointing at a non-committed forecast
is rejected. `approve_ticket` (judge_operator) writes the `Ticket`, its `BetLeg`s,
and the single stake `CashTransaction` in one handler after `validate_within_budget`;
either all land or none do. `propose_ticket` (ai_analyst or judge_operator) records
the intent first. Cash amounts are **signed** (stake negative, payout positive), so
`ledger_balance` is a plain SUM.

**Outcomes are versioned truth.** `record_outcome` (deterministic_system) writes
version 1; `correct_outcome` writes a superseding version and **keeps the prior row**
— corrections never overwrite. `current_outcome` returns the highest version.

**Settlement never fabricates a pending loss.** `settle_ticket` reads
`current_outcome(match_id)`; if there is no outcome it writes nothing and returns
`settled=False`. When an outcome exists, each had leg is graded by `grade_had`
(90-minute home/draw/away), one `BetLegSettlement` and one `TicketSettlement` are
written, and a winning ticket books a payout `CashTransaction`. P&L uses a flat win
multiplier placeholder here — **odds-faithful payout and CLV are Package 4**; hhad/
ttg/crs grading beyond the had representative is a documented 3B follow-on.

`kernel.reconcile.settle_match(...)` records the outcome then settles every ticket
with a leg on the match; `nutmeg ontology status` then reports
`ticket_count`/`settlement_count`. Together with 3A this closes umbrella Package 3
(Decision & Finance Loop). Package 4 (Learning & Regime) consumes committed
forecasts, closing snapshots, outcomes and settlements to build the DuckDB
scoring/regime projections.

**Known 3B limitations (owned by Package 4/follow-on).** `score_90` is the string
convention `"home-away"` (e.g. `"2-1"`); the historical importer normalizes to it.
Settlement is idempotent per idempotency key, but re-settling a ticket under a *new*
key after a `correct_outcome` writes a second `TicketSettlement` and payout rather
than superseding the first — net-P&L reconciliation and supersede-on-resettle are
Package 4 concerns, not silently handled here.

## 14. Package 4A — Analytical Substrate & Forecast Scoring

Package 4A is the first half of the **calibrate** verb: rebuild re-computable
analytical projections from SQLite and produce forecast scorecards. It never writes
operational truth.

**DuckDB is re-computable, never business truth.** A second database
`analytics.duckdb` (`OntologyPaths.analytics`, opened via the POSIX-locked
`connect_analytics_db`) holds only projections. Every row carries six provenance
columns (`projection_name`, `projection_version`, `source_high_watermark`,
`built_at`, `cohort_definition_version`, `metric_version`). A build freezes the
SQLite high-watermark (`max(rowid)` of the append-only `actions` log), runs each
projector **in memory**, then writes all rows in one DuckDB transaction that first
deletes the prior rows for that `projection_version`. No metric reads the clock, so a
rebuild at the same watermark reproduces byte-identical rows. **Keep-last-good:** a
projector that raises records a `failed` run in `projection_runs` and touches no
projection rows — analytics never half-updates.

**Scoring primitives** (`nutmeg/analytics/scoring.py`, `metric_version=scoring-v1`)
are pure: Brier, Brier skill (vs the same-match prior; **`None` when the prior
denominator is 0** — never a divide-by-zero or default), log score, RPS,
closing-skill delta, directional alignment, and ticket CLV log. A missing outcome or
closing is **excluded from that metric's denominator**, never counted as 0.

**Five scorecards, no single total.** 4A ships three — Forecast Truth (Brier skill),
Market Information (closing skill), Calibration & Selectivity (follow-market vs
divergent) — cohorted by market (`cohort-v1`). Earning money never launders a bad
probability; that is why there is no one number. Integrity/Action scorecards, factor
learning and RegimeVector are Package 4B.

`kernel.calibrate.build(CalibrateRequest{as_of, built_at, high_watermark?})` rebuilds
`forecast_scores` + `forecast_scorecards`; `nutmeg ontology status` then reports
`projection_run_count`/`scorecard_count` (read-only — it never creates the DuckDB).
had 3-way is the outcome mapping shipped here; ordered-market RPS (ttg) and other
mappings are a documented 4B follow-on — a non-had revision is scored only where a
mapping exists.
