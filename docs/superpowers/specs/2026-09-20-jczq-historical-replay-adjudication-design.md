# JCZQ Historical Replay Adjudication Correction Design

Date: 2026-09-20
Status: approved direction; written correction pending final operator review
Owner: Nutmeg operator workflow
Corrects: `2026-09-19-jczq-ontology-v2-cutover-design.md` sections 5.1-5.4

## 1. Purpose

Complete the isolated 2026-09-19 JCZQ A3-A7 replay without turning draft
compatibility data into a production judgment, impersonating Jun, fabricating a
missing timestamp, or allowing replay output to count as prospective Dream-RSI
evidence.

The current runner proves A2 isolation but then only checks whether A3-A6 rows
already exist. The real source day contains 30 draft Reads and no committed
Forecast. The runner must instead execute the approved ontology workflow inside
the isolated store and prove that the same gates can carry a replay-only
decision chain.

This correction is deliberately narrow. It does not change production A2-A7
authority, candidate semantics, odds bands, audit rules, settlement arithmetic,
RSI verdict eligibility, or the real-money confirmation boundary.

## 2. Approaches Considered

### 2.1 Chosen: context-bound replay through existing Actions

Create a durable replay run, bind an isolated Action service to that run, and
execute the existing proposal, adjudication, Forecast, prescription, candidate,
audit, no-ticket, result, review, and RSI adapters with replay provenance.

This is the only approach that tests the production contracts without granting
the replay production authority. It also makes replay contamination queryable
instead of relying on actor-name conventions.

### 2.2 Rejected: parallel replay tables and replay-only business Actions

A second set of Forecast, candidate, and terminal objects would avoid touching
the current contracts, but it would test a parallel decision engine. Passing
that replay would not prove that the production A3-A7 path works.

### 2.3 Rejected: direct insertion into a cloned database

Direct repository or SQL writes would be isolated, but they would bypass
permissions, idempotency, optimistic concurrency, audit, and Action lineage.
They cannot satisfy the ontology-writeback invariant.

## 3. Authority and Identity

### 3.1 Replay authority domain

Every replay has one immutable `HistoricalReplayRun` with:

- `replay_run_id`, target business date, source-root fingerprint, and source
  artifact manifest hash;
- isolated database identity and schema version;
- start and finish timestamps;
- status: `running`, `accepted`, or `failed`;
- production fingerprints and protected-count snapshots before and after; and
- final report hash and structured failure codes.

The run exists only in the isolated ontology. Starting a run against the
production database path or an already bound production kernel is rejected.
Reusing a replay run id with a different day, source manifest, or database
identity is an idempotency conflict.

### 3.2 Replay action provenance

All A2-A7 Actions created after the run starts carry two explicit envelope
fields:

```text
historical_replay = true
replay_run_id = <HistoricalReplayRun id>
```

The pair is atomic: `historical_replay=true` requires a run id, and a run id
requires `historical_replay=true`. Both fields participate in canonical request
hashing and are persisted in the Action audit row and outbox payload.

The Action service, not each caller, stamps the bound context. This prevents a
nested Action from silently losing replay provenance. A production Action
service rejects replay context; a replay-bound service rejects an absent,
finished, wrong-day, or wrong-database run.

### 3.3 Replay adjudicator

Add the actor role `replay_adjudicator`. It may call only the existing
judgment/prescription/candidate/audit/terminal Actions while all of these are
true:

1. the Action service is bound to an active `HistoricalReplayRun`;
2. the ontology path is the run's isolated database;
3. `historical_replay=true` and `replay_run_id` are present; and
4. no protected placement, funds, dispatch, deployment, or prospective RSI
   Action is requested.

The actor id is deterministic (`replay:<run-id>:adjudicator`) and never equals a
human operator id. Production services reject this role even if a caller
constructs the request directly. Replay Adjudications therefore prove the
state transition but do not claim that Jun made the historical decision.

## 4. Source Semantics

### 4.1 Frozen inputs

The replay input manifest contains the exact hashes of the 2026-09-19 board,
official market snapshot, 30 draft Reads, research artifacts, and any later
authoritative result artifacts. Files are copied before the replay run starts;
the manifest is then immutable.

Filesystem modification time is never evidence time. Existing `captured_at`,
`made_at`, market update time, kickoff, and result publication time are
preserved exactly.

### 4.2 Draft Reads

The 30 `reads.json` rows are imported only as replay AgentProposal payloads.
Their `status=draft` is preserved. Import does not create an Adjudication,
committed Forecast, Selection, no-ticket decision, or production observation.

Each proposal resolves its prior and offered prices from the frozen official
market snapshot. A Read cannot supply a missing market identity or silently
replace an EvidenceBundle. AI-origin Reads remain AI proposals;
`market-anchor` Reads remain deterministic price-only proposals.

### 4.3 Missing research capture time

The rejected artifact for `周六002` has no trustworthy `captured_at`. Replay
must not infer one from file metadata or neighboring files.

That artifact is stored as a quarantined attempted input with
`temporal_status=unknown` and the canonical rejection reason. It cannot enter
an EvidenceBundle, Forecast citation, prospective sample, or replay grade.
Because its only legal effect is an explicit rejected A2 revision, the missing
time is a reported `historical_input_gap`, not a release-blocking lineage
failure after quarantine is proven.

`周六002` may still receive a separate market-anchor proposal supported only by
the official pre-kickoff market snapshot. The rejected research artifact is not
laundered into that proposal.

Any missing or unknown time on an artifact used by an accepted EvidenceBundle,
Forecast, result, or experiment row remains a blocking failure.

## 5. Corrected Replay Sequence

### 5.1 A2: research terminals

Reconstruct all 30 board identities and write exactly one current replay-owned
research terminal per match. Expected real-day counts remain 25 `researched`,
1 `rejected`, and 4 `price_only`. Replay intake never fulfills R0.

### 5.2 A3: proposals and Forecasts

For each draft Read:

1. resolve canonical match and market identity;
2. freeze a replay EvidenceBundle from eligible research and/or the official
   pre-kickoff market snapshot;
3. create an AgentProposal retaining the original draft status and origin;
4. record a replay-only approve, revise, or reject Adjudication; and
5. use the existing Forecast commit Action for the accepted/revised proposal.

The run must exercise all three adjudication branches. A rejected proposal may
be superseded by a separate market-anchor proposal; rejection cannot be
silently converted into approval. Every committed Forecast resolves through
EvidenceBundle -> Artifact -> SourceRun and carries replay provenance.

No replay Forecast is prospective, regardless of the historical source time.
Historical source time is still validated to detect leakage and to decide
whether the source was legally visible at the simulated cutoff.

### 5.3 A4: prescription and candidate revisions

Freeze the Judgment Prescription from the current committed replay Forecasts,
then call the existing four-band candidate generator. Exactly the two canonical
set kinds are produced. `10x`, `20x`, `50x`, and `100x` each contain candidates
or a durable `no_feasible_candidate` outcome.

Every non-root Candidate Set Revision records its set-level parent, change
delta, rationale, dependency fingerprint, and candidate hashes. The replay may
append an audit-driven revision, but it may not edit a candidate row to mimic a
tree node.

### 5.4 A5: audit

Run all candidate audit kinds and the final cross-ticket exposure audit through
the existing deterministic code. WARN and ERROR behavior is unchanged.

The replay adjudicator may record the reject branch for a blocked candidate.
It may not use a replay override to make an ERROR candidate deployable. The
specific production-only Jun override path remains outside replay acceptance.

### 5.5 A6: replay terminal

The replay concludes with a formal replay-only `record_no_ticket` after the
candidate and audit chain. This terminal proves the no-ticket Action and close
gate without claiming that Jun historically selected, placed, or abstained on
2026-09-19.

Selection and placement are not reconstructed from `legs.json` or
`nutmeg-handoff.json`. Those files remain comparison inputs only. Any placement,
funds, receipt, or dispatch row is a replay failure.

### 5.6 A7: result, review, and experiments

Use only authoritative, timestamped result artifacts. Apply the normal result
and Forecast-scoring Actions to replay Forecasts. No-ticket produces no money
settlement.

RSI adapters run with `historical_replay=true`. They may produce replay-mode
grades or explicit gaps, but may not fulfill a duty, create a prospective
Observation, increment prospective `n`, support a verdict, or create a
deployment. A missing authoritative result remains blocking; it is not replaced
with a score copied from narrative text.

## 6. Report and Acceptance

The replay report is derived from the isolated ontology after the finish Action;
it is not assembled from caller-supplied booleans. In addition to the existing
fields it records:

- replay run status and source-manifest hash;
- counts of replay-stamped Actions by A2-A7 stage;
- proposal approve/revise/reject branch counts;
- committed Forecast and full evidence-lineage counts;
- prescription and both Candidate Set Revision ids;
- four structured odds-band outcomes;
- candidate and cross-ticket audit completeness;
- replay no-ticket revision id;
- result/Forecast-grade coverage and replay-mode RSI outputs;
- quarantined historical gaps; and
- production fingerprints and protected-count deltas.

Acceptance requires all of the following:

1. board and A2 terminal counts are 30/30 with the expected status counts;
2. every A2-A7 Action after run start is stamped with the same replay run id;
3. A3 exercised approve, revise, and reject and every committed Forecast has
   complete eligible lineage;
4. the prescription, two set kinds, four band outcomes, candidate audits, and
   cross-ticket audit are complete;
5. exactly one replay terminal exists and it is the formal replay no-ticket;
6. every committed Forecast has an authoritative result and replay score, or
   the run fails with the exact missing result ids;
7. prospective R0/F5/F9 counts, verdicts, and deployments are unchanged;
8. production object, money, dispatch, and prospective-observation counts are
   unchanged and its tree fingerprint is byte-identical;
9. no unexplained failure remains; and
10. `jczq-cutover --check-only` independently recomputes these conditions and
    the report hash from the isolated store.

The quarantined `周六002` research timestamp gap is accepted only if it remains
excluded from every accepted evidence and learning lineage. Any other unknown
or contaminated source time blocks acceptance.

## 7. Schema and Component Changes

The correction requires one additive migration after schema 34:

- `historical_replay_runs` for durable run identity and finish state;
- `actions.historical_replay` and nullable `actions.replay_run_id` with pair and
  run-reference constraints; and
- the `replay_adjudicator` permission rows limited by the runtime replay guard.

Expected implementation boundaries:

- ontology Action model/repository/service: generic replay provenance and guard;
- replay run repository and typed start/finish Actions;
- product replay input adapter: frozen Reads/market/research/result mapping;
- existing JCZQ board workflow: replay orchestration only, no duplicate rules;
- replay report/query and cutover verifier; and
- focused migration, permission, A3-A7 integration, leakage, and failure tests.

The production Action API remains backward compatible: non-replay commands
default to `historical_replay=false`, `replay_run_id=null`, and retain their
current permission behavior.

## 8. Failure and Recovery

Failures are append-only and stage-coded. Successful nodes remain in the
isolated run. Repair creates a new revision or a new replay run; it never
rewrites a failed Action.

Mandatory failure injection covers:

- replay actor on a production or unbound service;
- nested Action missing or changing replay context;
- manifest mutation after run start;
- draft Read treated as committed authority;
- unknown time entering an accepted EvidenceBundle;
- post-kickoff evidence presented as cutoff-visible;
- incomplete Forecast or candidate lineage;
- stale candidate dependency;
- unadjudicated ERROR selected or overridden by replay;
- duplicate/conflicting terminal state;
- result coverage gap;
- prospective RSI mutation; and
- any production filesystem or protected-count delta.

## 9. Deployment Boundary

An accepted replay permits only `jczq-cutover --check-only` to report readiness.
It does not activate `ontology_v2_required` and does not authorize betting,
funds movement, placement, Telegram dispatch, or public output.

The explicit production cutover remains a separate operator Action at the next
board-open boundary after review of the accepted report. After cutover, failure
remains fail-closed; legacy write authority is never restored.

## 10. Supersession

For historical replay only, this document supersedes the ambiguous parts of
sections 5.1-5.4 of the 2026-09-19 cutover design:

- it defines the replay adjudicator without human impersonation;
- it makes replay provenance an Action-envelope invariant;
- it defines draft Read use as proposal input only;
- it classifies the missing timestamp on an already rejected artifact as a
  quarantined historical gap rather than fabricated evidence; and
- it fixes the accepted terminal to replay-only no-ticket so no historical
  selection is invented.

All other cutover and Dream-RSI requirements remain authoritative.
