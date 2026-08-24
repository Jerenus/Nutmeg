# Nutmeg Intelligence OS M6 - Reliability and Release Governance Design

Date: 2026-08-24
Status: Approved by the existing M1-M6 program architecture and continuous operator authorization
Scope: M6 only; M1-M5 remain closed except for regressions exposed by M6 verification

## 1. Outcome

M6 turns release confidence into typed, inspectable evidence. It adds a local
reliability plane that can answer four questions without relying on chat memory:

1. Can the ontology authority be backed up and restored without losing counts, Action
   order, ticket hashes, or ledger balances?
2. Have the declared fault, performance, security, browser, scheduler, and observability
   gates been exercised against the current release candidate?
3. Has real non-dispatch soak covered both JCZQ and Zucai for at least 14 calendar days
   without unexplained identity, audit, or ledger divergence?
4. Has Jun explicitly approved the exact evidence snapshot that answered the first
   three questions?

M6 completes the software needed to collect and evaluate this evidence. It does not
pretend that 14 days have elapsed. Until real evidence satisfies the policy,
`ReleaseApproval` remains blocked by construction.

## 2. Considered approaches

### 2.1 External observability and backup platform

Prometheus, a remote backup service, and a CI release system would provide broad
operations features, but they add network authority, secrets, deployment work, and a
second operational plane to a local single-user v1. This is deferred.

### 2.2 Runbooks and signed Markdown only

This is easy to ship, but prose cannot enforce completeness, freshness, role separation,
or evidence-snapshot identity. It would recreate the chat-memory problem at release
time. This is rejected.

### 2.3 Local evidence ledger plus typed approval

This is selected. Reliability reports become immutable ontology evidence through an
Action. A deterministic evaluator computes gates from those rows. Backup manifests are
canonical and content-addressed. Jun may approve only the exact currently-green
snapshot through a judge-only Action. The UI reads this state but contains no release
arithmetic.

## 3. Locked boundaries

- Verification and rehearsal use explicit temporary or copied data roots.
- Production `.nutmeg-data`, SOP files, launchd services, providers, Telegram, betting,
  and funds are not mutated by feature verification.
- Backup creation requires an explicit destination and acknowledgement that writers are
  stopped. It never guesses a production target.
- DuckDB is rebuildable and never outranks SQLite. CAS artifacts remain immutable.
- Scheduler review is read-only. M6 reports loaded/configured state but never runs
  `launchctl bootstrap`, `bootout`, `enable`, or `disable`.
- A release approval does not dispatch, place a ticket, alter a schedule, or switch
  scoreboard authority. It records the operator's decision about a release candidate.
- Synthetic test fixtures may prove the 14-day policy logic, but they are labeled test
  data and can never be imported as real soak evidence.

## 4. Ontology additions and migration 14

Migration 14 adds two immutable tables.

```text
reliability_evidence
  reliability_evidence_id TEXT PK
  evidence_kind TEXT NOT NULL
  workflow TEXT NULL                    # jczq | zucai | system
  business_date TEXT NULL               # YYYY-MM-DD for soak rows
  observed_from TEXT NOT NULL
  observed_to TEXT NOT NULL
  status TEXT NOT NULL                  # passed | failed
  report_json TEXT NOT NULL
  source_refs_json TEXT NOT NULL
  content_hash TEXT NOT NULL UNIQUE
  recorded_at TEXT NOT NULL
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT

release_approvals
  release_approval_id TEXT PK
  release_version TEXT NOT NULL UNIQUE
  evidence_snapshot_sha256 TEXT NOT NULL
  policy_version TEXT NOT NULL
  reason TEXT NOT NULL
  approved_at TEXT NOT NULL
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT
```

`record_reliability_evidence` is allowed for `deterministic_system` and
`judge_operator`. `approve_release` is allowed only for `judge_operator`. AI roles have
no permission for either Action.

An evidence request has an exact allowlisted `evidence_kind`, aware observation bounds,
canonical report object, source references, and SHA-256 content hash. Soak rows also
require `workflow`, `business_date`, `dispatch=false`, `synthetic=false`, and zero or
explicit divergence counts. Duplicate content replays through idempotency; a reused key
with different content conflicts.

## 5. Release policy

Policy `release-v1` emits six gates matching the program architecture.

| Gate | Required current evidence |
| --- | --- |
| G1 single-track authority | `scheduler_authority` passed; ontology v2, required stages, scoreboard/SOP agreement |
| G2 deterministic integrity | `deterministic_suite` and `migration_replay` passed for the candidate commit |
| G3 fault tolerance | `fault_matrix` passed with every required scenario |
| G4 AI safety | `ai_safety` passed for actor spoofing, citation, injection, and protected Actions |
| G5 product experience | `browser_e2e` and `performance` passed; all four p95 budgets satisfied at volume multiplier >= 10 |
| G6 operations | `backup_restore` and `observability` passed, plus real JCZQ and Zucai soak |

Non-soak evidence must be for the same candidate commit and policy version. The
evaluator reports missing, failed, stale, or mismatched evidence explicitly.

Soak requirements are exact:

- both `jczq` and `zucai` have at least 14 distinct business dates;
- each workflow spans at least 14 inclusive calendar days;
- every row is non-dispatch and non-synthetic;
- identity, audit, and ledger divergence counts are all zero;
- no business date or observation end is in the future at evaluation time.

The evaluator canonicalizes the selected evidence IDs, content hashes, gate results,
candidate commit, and policy version into `evidence_snapshot_sha256`. `ApproveRelease`
requires every gate green, a non-empty reason, and an exact expected snapshot hash. The
Action re-evaluates inside its transaction. A stale browser or newly changed evidence
cannot approve an older snapshot.

An approval remains an immutable historical decision. The status endpoint labels it
`current` only while its snapshot equals the current evaluation; later evidence changes
make it `superseded`, never silently mutate it.

## 6. Backup and restore drill

The backup service owns only an explicit destination. It requires
`acknowledge_writers_stopped=true`, rejects a destination that already contains data,
and builds in a sibling staging directory before atomic publication.

The canonical manifest contains:

- schema and tool versions, created time, and source data root;
- SQLite backup SHA-256 and optional DuckDB SHA-256;
- every CAS relative path, byte count, and SHA-256;
- schema version, SQLite integrity result, Action high-water mark, outbox cursor;
- allowlisted object/table counts;
- sorted audited ticket hashes;
- sorted account ledger balances.

SQLite uses its online backup API after writers are stopped; the source file is never
copied byte-for-byte while WAL state is unresolved. DuckDB and CAS are copied only after
the SQLite snapshot and are verified against the manifest.

`restore-drill` restores into a new explicit directory, verifies every hash, opens the
kernel without pending migrations, compares all manifest facts, rebuilds DuckDB
projections from restored SQLite, and reports the restored projection watermark. A
failed copy, hash mismatch, integrity failure, count mismatch, ticket mismatch, ledger
mismatch, or projection failure leaves the published backup untouched and fails the
drill. Only a successful drill may be recorded as `backup_restore` evidence.

## 7. Fault and performance contracts

The required fault matrix is fixed for `fault-v1`:

```text
provider_timeout
partial_provider_response
invalid_provider_schema
sqlite_lock
process_interruption
duplicate_action
sse_disconnect
projection_interruption
```

Each scenario records the observed result and must end in exactly one acceptable mode:
`retryable`, `degraded`, or `blocked`, with `state_corruption=false`. The validator
rejects missing, duplicate, unknown, or merely claimed scenarios. M6 verification maps
each row to an executable existing or new fault-injection test.

Performance evidence is valid only when `volume_multiplier >= 10`, sample counts are
positive, and p95 values are finite numbers under these fixed budgets:

```text
board_query_ms <= 500
match_query_ms <= 800
action_ack_ms <= 1000
event_reconnect_ms <= 2000
```

The product never turns a failed budget into a warning. G5 remains blocked.

## 8. Scheduler and authority review

The scheduler inspector parses launchd plist files with `plistlib`, validates the exact
AM/close/settle labels, working directory, `run-strict` stage commands, calendar
intervals, and log paths. A separate explicit runtime report supplies loaded state and
the effective `NUTMEG_ONTOLOGY_V2` value; configuration files alone are not treated as
runtime truth.

The review also reads the current scoreboard authority row and runs the existing
five-document SOP checker. It passes only when all required stages are configured and
reported loaded, ontology v2 is effective, scoreboard authority is `ontology`, and the
SOP documents agree. The inspector performs no scheduler mutation and never reads or
emits secret values from `.env`.

## 9. Local observability

The app maintains a process-local, bounded latency registry by route template. It
records request count, error count, and p95 duration without IDs, query strings,
payloads, source text, or credentials. `/api/v1/reliability/metrics` exposes this
registry together with Action status counts, Action/outbox high-water marks and lag,
projection health, authority state, evidence freshness, and last successful restore
drill.

The registry is operational telemetry, not release evidence by itself. A reviewed
observability report must still enter the evidence ledger before G6 can pass.

## 10. Product and CLI experience

M6 adds:

```text
GET  /api/v1/release
GET  /api/v1/reliability/metrics
GET  /release
POST /api/v1/actions  action_type=approve_release
```

The Release workspace is a dense, read-only-first gate board. It shows the six gates,
blocking codes, chosen evidence, soak calendars for both workflows, backup/restore
facts, scheduler/authority state, performance budgets, and current/superseded approval.
The approval form is absent or disabled while blocked. It never calculates eligibility
in JavaScript.

CLI commands use explicit paths and canonical JSON:

```text
nutmeg reliability status
nutmeg reliability record
nutmeg reliability backup-create
nutmeg reliability restore-drill
nutmeg reliability scheduler-review
nutmeg reliability approve-release
```

Every mutating command prints resolved targets. Evidence recording requires an explicit
acknowledgement; backup and restore require separate source/destination paths. No command
defaults to production for mutation in tests.

## 11. Verification

M6 is code-complete only after:

- migration, repository, permission, idempotency, and release-policy tests pass;
- backup/restore succeeds on an isolated M5 lifecycle store and injected interruption
  preserves the prior complete backup;
- all fault matrix rows map to executable passing tests;
- performance budgets are exercised at a declared 10x reference volume;
- desktop/mobile browser E2E traverses operations, match, ticket, review, and release,
  including blocked, offline, restored, and keyboard-focus states;
- full pytest, Ruff, compileall, pre-commit, and repository diff checks pass;
- production/SOP before-after hashes are identical;
- a real current-store `reliability status` truthfully reports the soak/release block.

M6 verification may prove that a fully seeded test fixture can reach approval. It must
also prove that the real evidence ledger cannot. No `ReleaseApproval` is created in
production as part of implementation.

## 12. Explicit non-goals

M6 does not add cloud telemetry, remote backup, multi-user permissions, autonomous
release, scheduler mutation, provider dispatch, Telegram dispatch, betting, funds
actions, or an exception that waives elapsed soak time. Those boundaries remain in
force after v1 release.
