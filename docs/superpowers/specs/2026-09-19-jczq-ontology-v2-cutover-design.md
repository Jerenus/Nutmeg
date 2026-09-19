# JCZQ Ontology v2 Cutover Design

Date: 2026-09-19
Status: proposed for implementation
Owner: Nutmeg operator workflow

## 1. Purpose

Move the daily JCZQ A2-A7 workflow from legacy file authority to the existing
Intelligence OS ontology. The change closes the gap exposed by the 2026-09-19
board run: research and narrative judgment existed, but formal Forecast,
candidate revision, audit, selection, and experiment lineage did not.

The target chain is:

```text
SourceRun / Artifact
  -> EvidenceBundle
  -> AgentProposal / draft Forecast
  -> operator Adjudication
  -> committed ForecastRevision
  -> Judgment Prescription
  -> Ticket Candidate Set Revision
  -> deterministic candidate audit
  -> Candidate Selection or record_no_ticket
  -> placement / settlement / review
  -> experiment and score projections
```

This design reuses the approved M3/M4 objects and Actions. It does not create a
parallel JCZQ decision system.

## 2. Decisions

### 2.1 Authority

From the first trading day after replay acceptance, ontology v2 is the only
authority for JCZQ A2-A7.

- `reads.json`, `legs.json`, and `nutmeg-handoff.json` become read-only
  compatibility projections.
- Compatibility files may be regenerated from ontology state, but may not
  approve a Forecast, construct or select a candidate, authorize placement, or
  drive settlement.
- The CLI and OpenClaw router call the same product Actions. The router contains
  no separate decision rules.
- Chat starts Actions and renders results. It is not a decision store.
- If no legal ontology terminal state exists, close fails closed. It must not
  fall back to a legacy file.

### 2.2 Cutover method

The cutover uses one isolated replay of 2026-09-19 followed by a hard switch on
the next trading day. There is no one-day dual-authority shadow period.

Replay acceptance is a deployment prerequisite. A failed replay blocks the
cutover.

### 2.3 Candidate set model

The existing ontology requires each generation to create exactly two set kinds:

- `judgment_bound`, which may contain deployable candidates; and
- `conditional_market_counterfactual`, which is comparison-only.

The requested 10x, 20x, 50x, and 100x opportunities are therefore structured
odds bands inside the `judgment_bound` candidate set, not new set kinds. The
counterfactual set retains the same bands for comparison where feasible.

Each band records:

- a stable band code: `10x`, `20x`, `50x`, or `100x`;
- its target decimal-odds interval and observed combined odds;
- the candidate revision or a machine-readable `no_feasible_candidate` result;
- parent revision and delta reason for every iteration;
- shared dead faces and cross-ticket exposure; and
- deterministic audit findings.

This preserves the M4 contract while making four-band opportunity discovery
durable and replayable.

### 2.4 Dream-RSI inheritance

This cutover extends, and does not replace, the approved RSI architecture in
`2026-09-18-rsi-experiment-persistence-design.md` and the consolidated
`2026-09-19-rsi-transformation-archive.md`.

- RSI remains a governance layer. It receives observations through RSI typed
  Actions and does not create Forecasts, candidate sets, or tickets.
- Judgment experiments remain prospective-only observation experiments.
  Historical replay may exercise their adapters but cannot fulfill a duty,
  increment prospective `n`, or support a verdict.
- Structural discovery uses append-only revision trees. The authoritative
  parent and delta belong to the Candidate Set Revision; individual candidate
  rows retain content identity and membership but do not define the tree.
- Prefix visibility is enforced at the source boundary. Evidence captured at or
  after the applicable kickoff remains durable but cannot acquire prospective
  eligibility.
- Experiment duties, observations, grades, verdicts, and deployments continue
  through the existing RSI Actions. Product orchestration may request those
  Actions but may not emulate them with callbacks or direct repository writes.
- The constitution's lexicographic objective remains authoritative. Odds bands
  are requested ticket payout-multiple intervals and never become an EV score or
  a weighted optimization objective.

These constraints are release gates, not implementation guidance that may be
relaxed locally.

## 3. A2-A7 Workflow

### 3.1 A2: research and evidence intake

Inputs are the official board snapshot, market snapshot, per-match research
artifacts, true capture times, and source hashes.

Every board match has exactly one **current** explicit research terminal state:

- `researched` when canonical intake accepts the research artifact;
- `price_only` when no accepted research exists before the cutoff; or
- `rejected` when an attempted artifact fails canonical intake.

Accepted artifacts become SourceRun/Artifact and EvidenceBundle lineage.
Canonical intake runs before R0 fulfillment. An intake ERROR cannot create an
R0 fulfillment and cannot enter a Forecast. R0 fulfillment must use the existing
`rsi_fulfill_duty` Action, which atomically records duty fulfillment and an
Observation under the RSI eligibility rules. A product callback or direct RSI
repository write is not a valid fulfillment.

Research states are append-only revisions. A pre-kickoff `price_only` or
`rejected` revision may be superseded by a later accepted artifact, while the
old revision remains queryable. The current revision is selected by family and
revision number; uniqueness of `(business_date, match_id)` applies to the
current projection, not to the immutable revision history.

A2 is complete only when the board count reconciles exactly with its terminal
states and every accepted artifact is traceable to its source and capture time.

### 3.2 A3: judgment and Forecast commitment

Each eligible match first receives an AgentProposal or draft Forecast.
`market-anchor` and `ai:jczq-analyst` identify proposal origin; neither identity
has commit authority.

An authorized operator Adjudication approves, revises, or rejects the proposal.
Approval creates the current committed ForecastRevision. The revision retains:

- market prior and belief probabilities;
- named factors and explicit probability movement;
- a reason when the belief remains anchored to the prior;
- falsifier and evidence references;
- capture, proposal, decision, and kickoff time semantics; and
- supersession lineage.

A3 is complete only when every board match has either a current committed
ForecastRevision or an explicit rejection Adjudication. A compatibility Read is
not evidence of commitment.

### 3.3 A4: prescription and candidate iteration

Committed ForecastRevisions freeze into the existing Judgment Prescription.
The candidate generation request then produces the two canonical candidate set
kinds and materializes the four odds bands inside them.

Any changed leg, market, selection, multiplier, or exposure creates a new
Candidate Set Revision. Revisions are append-only and record their parent,
change delta, rationale, candidate hashes, and dependency fingerprint. The
Candidate Set Revision is the discovery-tree node required by Dream-RSI;
candidate rows do not substitute for set-level lineage.

A4 is complete only when every odds band contains at least one candidate or an
explicit `no_feasible_candidate` outcome. Candidates mentioned only in chat do
not count.

### 3.4 A5: audit and selection

Every candidate completes the existing four ontology audit kinds and the
applicable C0-C17 decision audit. The final candidate group also receives a
cross-ticket exposure audit.

- ERROR findings block selection by default.
- WARN findings require explicit adjudication.
- An ERROR may continue only after Jun explicitly authorizes an override and a
  valid `evidence_rejected` Adjudication is committed.
- Selection references the exact current Candidate Set Revision and candidate
  revision. Stale revisions fail optimistic-concurrency checks.

Audit may lead to a Candidate Selection, another Candidate Set Revision, or the
no-ticket path. It may not lead to an edited legacy legs file.

### 3.5 A6: placement or no-ticket terminal state

Selection creates placement intent. Real placement and Telegram dispatch still
require the existing explicit human confirmation boundary.

If no candidate survives, the workflow calls `record_no_ticket` with the audit
references, rejected candidate lineage, applicable rule identifiers, and an
abstention reason.

Each trading day has exactly one legal terminal decision state:

- selected and, when confirmed, placed; or
- no-ticket.

Close fails when neither state exists or both conflict. Deployment permission
never implies permission to bet, move funds, or dispatch publicly.

### 3.6 A7: settlement, review, and experiments

Settlement consumes only recorded placements. It creates the normal result,
settlement, and review lineage, then updates Forecast scoring and applicable
experiment projections such as Brier, CLV, F9 balance, R0, and F5.

No-ticket has no money settlement, but prospective Forecasts still become
learning samples after outcomes are available. Partial failures create explicit
gaps and are never silently skipped.

Historical replay observations are marked replay-only and never increment
prospective experiment counts.

## 4. Components

### 4.1 Research run ledger

Extend the current research runner so each invocation appends immutable run and
attempt records. The daily research report becomes a projection across those
records. A later small-budget run cannot overwrite the history of a prior run.

The ledger records the board identity, budget, attempt, status, timings,
artifact hash, intake result, and rejection reason for every match considered.

### 4.2 JCZQ board orchestration

Add a product-layer orchestration service that translates board and canonical
research intake results into the existing evidence, proposal, Forecast, and
operator-decision Actions.

The service coordinates Actions but owns no alternative business rules. It
must use current repository and Action APIs for evidence freeze, match judgment,
prescription freeze, candidate generation, selection, and no-ticket recording.

### 4.3 Candidate generation

Extend the existing candidate generator and stored candidate contract with
structured odds-band metadata and iteration lineage. Keep deterministic ranking,
content hashes, exhaustive-space limits, audit partitions, and the two canonical
set kinds unchanged.

The generator must emit a durable no-feasible result for an empty band instead
of inventing a candidate or omitting the band.

### 4.4 Terminal-state and close gate

Add a query for the current trading-day decision terminal state. Close checks
this query and refuses to continue on missing, stale, conflicting, or
audit-incomplete state.

Legacy scheduler and router paths stop reading legs or handoff files as
authority. They may read ontology-generated projections for display only.

### 4.5 Compatibility projections

One projection service generates `reads.json`, `legs.json`, and
`nutmeg-handoff.json` after successful formal Actions. Projection failure is
retryable and cannot change the authoritative state.

The projection includes source revision identifiers so equality between the
compatibility view and ontology state can be verified.

### 4.6 Settlement and experiment coordinator

Reuse current result, settlement, review, and RSI Actions. Add only the missing
JCZQ coordination that connects committed Forecasts and terminal decisions to
their post-result observations.

Experiment eligibility derives from source capture time, the applicable kickoff,
RSI duty state, and replay mode. It is not inferred from a file's presence or
modification time. The coordinator calls RSI Actions and never writes
fulfillments or observations through a product-local adapter.

## 5. Historical Replay

### 5.1 Isolation

Copy the production ontology store and all available 2026-09-19 board,
research, market, Read, and handoff artifacts into an isolated replay root.
Production remains read-only throughout replay.

Preserve original `captured_at`, `made_at`, kickoff, and source hashes. Every
new replay Action carries a replay run identity and `historical_replay` meaning.

Artifacts created after kickoff may validate lineage and rejection behavior,
but may not create a prospective Forecast or prospective experiment sample.

### 5.2 Replay sequence

1. Reconstruct the 30-match board manifest and reconcile every source artifact.
2. Materialize one explicit research terminal state per match.
3. Generate proposals and exercise replay-only approve, revise, and reject
   paths without impersonating a production operator decision.
4. Commit eligible ForecastRevisions and freeze the Judgment Prescription.
5. Generate the two canonical candidate sets, including all four odds bands.
6. Audit every candidate and the combined exposure; append iterations as needed.
7. Record Candidate Selection or `record_no_ticket` through the formal Action.
8. Exercise replay-only outcome, review, and experiment projection paths.

The replay may conclude no-ticket. Such a result is accepted only when it is the
formal terminal state produced after a durable candidate and audit chain.

### 5.3 Replay assertions

- Board input count equals explicit research terminal-state count.
- Every committed ForecastRevision resolves to EvidenceBundle, Artifact, and
  SourceRun lineage.
- Post-kickoff evidence cannot acquire prospective semantics.
- Every odds band has candidates or a structured no-feasible result.
- Every candidate iteration has parent and delta lineage.
- Selected candidates have complete individual and cross-ticket audits.
- An unadjudicated ERROR cannot enter Selection.
- Exactly one terminal decision state exists.
- Close fails if Selection and no-ticket are both absent.
- Compatibility projections equal ontology state.
- Status, close, and replay queries work with legacy inputs removed.
- Production object counts, money ledger, dispatch records, and prospective
  experiment counts are unchanged before and after replay.

### 5.4 Replay failures

Missing data, time contamination, dangling references, stale dependencies, and
incomplete audits create structured replay failures. Successful earlier nodes
remain durable. A repair produces a new revision and rerun; it does not overwrite
the failed record.

Any unexplained failure blocks cutover.

## 6. Implementation and Deployment

### 6.1 TDD sequence

1. Add failing tests for immutable research runs, explicit board terminal
   states, temporal eligibility, four odds bands, candidate lineage, individual
   and cross-ticket audits, unique terminal state, legacy non-authority, and
   experiment exclusion.
2. Add the minimum schema migration and repository/Action contracts. Migrations
   append data and never rewrite historical events.
3. Implement A2/A3 orchestration, then A4/A5, then A6/A7.
4. Update SOP A2-A7, CLI help, router behavior, and compatibility projections.
5. Execute isolated replay and produce its lineage, candidate, audit, terminal,
   and experiment-difference reports.

### 6.2 Deployment sequence

Schema migration, code deployment, and authority cutover are separate steps.

1. Apply and verify the additive migration.
2. Deploy code with authority state `legacy_read_only`; no new legacy writes are
   allowed, but v2 cutover is not yet active.
3. Run and accept the isolated replay.
4. Before the next board opens, execute an explicit cutover Action to set
   `ontology_v2_required`.
5. Run discovery and readiness checks before A2 begins.

### 6.3 Rollback and recovery

Before cutover, code may be rolled back while the append-only Action ledger is
preserved. Compatibility projections are rebuildable.

After cutover, legacy write authority is never restored. A v2 failure enters a
fail-closed state: evidence collection may continue, but candidate selection,
placement, dispatch, and close stop until repaired. Recovery resumes from the
latest legal revision.

## 7. Verification Matrix

### 7.1 Unit and contract tests

- time semantics and prospective eligibility;
- state transitions and terminal-state exclusivity;
- idempotency, supersession, and optimistic concurrency;
- odds-band validation and no-feasible outcomes;
- candidate audit completion and override validity; and
- experiment eligibility for selected, no-ticket, and replay paths.

### 7.2 Integration tests

- board to explicit research states;
- evidence to draft and committed Forecast;
- Forecast to prescription and both candidate set kinds;
- four odds bands to iteration, audit, and selection/no-ticket;
- terminal state to compatibility projections; and
- result to settlement, review, and experiment projections.

### 7.3 Failure injection

The following cases must fail closed and remain recoverable:

- missing EvidenceBundle;
- post-kickoff evidence presented as prospective;
- stale Forecast or Candidate Set Revision;
- dangling or incomplete audit references;
- conflicting or duplicate terminal states;
- compatibility projection failure;
- repeated close; and
- partial settlement or experiment projection failure.

### 7.4 Release gate

Cutover requires all of the following:

- ontology, product, decision, CLI, router, and relevant full-suite tests pass;
- isolated 2026-09-19 replay satisfies every assertion;
- no unexplained data or projection difference remains;
- SOP and command help describe v2 as the sole authority;
- tests prove that legacy files cannot drive a write or close path; and
- no real placement, fund movement, or public dispatch occurred during replay.

## 8. Non-goals

- Reconstructing or fabricating missing prospective judgments for matches that
  had already kicked off.
- Replacing existing ontology audit, settlement, or operator authorization
  models.
- Creating a new recommendation score or opaque ranking engine.
- Automatically placing bets or dispatching Telegram messages.
- Maintaining dual write authority after cutover.
