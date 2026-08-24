# Nutmeg Intelligence OS - Product and Architecture Design

Date: 2026-08-24  
Status: Approved in brainstorming; implementation is split into M1-M6  
Scope: Local, private, single-operator football intelligence and decision system

## 1. Product definition

Nutmeg Intelligence OS is an AI-native football decision operating system. It is not
a recommendation feed and not a web wrapper around the current CLI. It places facts,
evidence, analysis, judgments, actions, financial records, outcomes, and learning in
one temporal and auditable system.

The complete operator lifecycle is:

```text
data operations
  -> daily board
  -> fixture triage
  -> match investigation
  -> forecast adjudication
  -> ticket construction
  -> deterministic audit
  -> per-ticket human confirmation
  -> settlement
  -> review and calibration
  -> governed knowledge writeback
```

The first product serves Jun as a private decision cockpit. It runs locally and binds
to `127.0.0.1` by default. Multi-user collaboration, subscriptions, billing, public
content distribution, cloud synchronization, and an autonomous betting agent are not
part of v1.

The internal implementation is incremental, but v1 is not declared complete until
M1-M6 and all release gates pass together.

## 2. Product principles

### 2.1 Guarded AI, not software with an AI feature

Nutmeg is best described as guarded AI:

- Software owns identity, provenance, deterministic arithmetic, validation, state
  transitions, audit, ledger, settlement, and reproducibility.
- AI owns investigation, comparison, scenario construction, draft judgments, and
  proposed actions. Its quality is measured; it is not treated as deterministic.
- The human operator owns factual adjudication, forecast approval, overrides, rule
  lifecycle decisions, and every real-money confirmation.
- Calibration owns the long-term survival of factors, flags, rules, and predictions.
  Narrative confidence cannot substitute for measured performance.

AI may create provisional Claims, AgentProposals, and draft Forecasts. AI may not
verify its own Claims, commit a Forecast, approve a Ticket, change a rule's lifecycle,
or invoke a funds action.

### 2.2 Ontology writeback

Every consequential decision is a typed, attributable Action. A UI click is not a
special write path. CLI, web, AI, and scheduled workflows must all use the same
validators and Action handlers.

The governing invariant is:

> If it did not pass through an Action and enter the ontology, it did not happen.

Chat transcripts and UI events may remain workflow logs, but any content that changes
a fact, Forecast, Ticket, adjudication, rule, or score must be distilled into a formal
object through a typed Action.

### 2.3 Stability means software invariants

Nutmeg cannot promise that an external provider is always available or always correct.
It promises that external failure is visible and that the software never silently
turns absence into certainty.

The following are hard software invariants:

- Equal versioned inputs at the same cutoff produce equal deterministic outputs.
- Devig, DC, coverage, audit, budget, payout, and settlement each have one server-side
  implementation. The UI contains no duplicate probability or money logic.
- Every mutation is atomic, permission-checked, idempotent, version-aware, and audited.
- Missing, stale, conflicting, or unresolved information is explicit.
- Historical `as_of` views cannot read evidence or outcomes recorded after the cutoff.
- Match identity cannot silently fall back to a plausible duplicate. Unresolved and
  merge/split states are first-class states.
- Ticket, leg, cash transaction, and settlement totals obey ledger conservation.
- Real-money actions require a fresh, explicit, per-ticket human confirmation.

The following remain uncertain and must be measured and cited:

- Tactical narratives and team-structure judgments;
- probability adjustments and scenario weights;
- factor and precedent relevance;
- ticket prescriptions and natural-language summaries;
- source statements not yet verified as Observations.

## 3. Current baseline and M0 status

M0 selected and completed the ontology-first approach rather than building a formal UI
on the legacy file store.

At design approval time:

- `main` contains commit `a19d60f`, the Package 5 cutover work;
- the production ontology is on schema version 9, passes SQLite integrity checks, and
  has no pending migrations;
- the fresh migration reconciled 465 Brier rows with zero mismatches;
- JCZQ and Zucai shadow ingestion completed on the v2 adapter;
- production has substantial Match, Snapshot, Quote, Forecast, and Action data;
- imported historical Forecasts do not have EvidenceBundles and must not be presented
  as fully sourced history;
- the close and settle launchd services were not restored when this design was
  approved. Their restoration and subsequent soak evidence remain M6 release inputs.

Existing `decision-web` is a useful interaction prototype but is not the product
backend. It reads the legacy `DecisionStore` and uses `workbench.jsonl` and
`decisions.jsonl`; the formal application must not retain those as runtime facts.

## 4. Palantir-style system mapping

Nutmeg maps to four Palantir-like layers without copying Palantir's surface design:

| Palantir concept | Nutmeg responsibility | Product requirement |
| --- | --- | --- |
| Foundry | collection, reconciliation, prep, lineage | source health, freshness, coverage, and replay |
| Ontology | domain objects, links, properties, typed Actions | a single semantic and writeback contract |
| AIP | AI bound to ontology and policy | cited proposals, permissions, human adjudication |
| Workshop | applications on top of the ontology | operational workspaces, not generic dashboards |

The product's defining behavior is not a knowledge graph visualization. It is the
operator acting on ontology objects while every decision retains source lineage,
time, model/actor identity, and an auditable result.

## 5. System architecture

### 5.1 Layers

```text
Jun / AI Copilot
        |
Application workspaces (M2-M5)
        |
Product contract (M1)
  - Product Query Service
  - Product Action Gateway
  - Durable Event Stream
  - Readiness Policies
        |
Ontology Kernel v2
  - identity
  - evidence
  - decision
  - finance/outcomes
  - actions/policies
        |
Deterministic functions + SQLite + DuckDB + CAS + schedulers/providers
```

Formal UI code may consume only the product contract. It may not import legacy
`DecisionStore`, query raw SQLite/DuckDB tables, read daily JSONL files, or reproduce
domain arithmetic in JavaScript.

### 5.2 Product Query Service

The Query Service assembles immutable product DTOs from the ontology repositories,
analytics projections, and operational health sources. DTOs are versioned independently
of database tables.

All collection endpoints support stable pagination and filters. Historical endpoints
accept an `as_of` timestamp and apply the recorded-at/cutoff rules from the ontology.

The first stable query surface is:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/system/health` | service, source, projection, and readiness health |
| `GET /api/v1/board?date=...` | complete daily board with readiness and next action |
| `GET /api/v1/matches/{match_id}` | match investigation aggregate |
| `GET /api/v1/lineage/{object_type}/{object_id}` | object links and Action history |
| `GET /api/v1/actions` | filterable Action audit stream |
| `GET /api/v1/events` | durable SSE stream with cursor recovery |

M2-M5 extend the API within `/api/v1`; incompatible change requires a new version.

### 5.3 Product Action Gateway

The Action Gateway is a thin command boundary. It performs local-session validation,
origin/CSRF protection, request parsing, actor assignment, and HTTP error mapping, then
delegates to existing or newly approved typed Action services.

It does not contain football judgment, probability arithmetic, ticket composition, or
settlement logic.

Each mutation requires:

- an Action type and policy version;
- an actor ID and role assigned by the server;
- an idempotency key;
- expected object versions where concurrent changes are possible;
- an explicit business payload;
- a human confirmation nonce for protected ticket/funds actions.

The standard error envelope is:

```json
{
  "code": "stable_machine_code",
  "message": "operator-readable explanation",
  "action_id": "optional-action-id",
  "field_errors": {},
  "retryable": false,
  "current_version": null,
  "details": {}
}
```

The gateway maps validation failure to 422, permission denial to 403, optimistic
version conflict or idempotency conflict to 409, absent objects to 404, and unexpected
internal failure to 500 with a correlation ID. A failed or rejected formal Action
remains auditable.

### 5.4 Durable Event Stream

An Action that changes product-visible state writes an outbox event in the same SQLite
transaction as its domain rows and Action audit record. An SSE publisher reads the
outbox using a monotonic cursor.

Required behavior:

- restart and disconnect do not lose committed events;
- reconnect resumes after the last acknowledged cursor;
- clients can deduplicate by event ID;
- delivery is at least once; consumers must be idempotent;
- a lagging or disconnected stream is visible in the UI;
- AI streaming text may use a separate transient channel, but a resulting Proposal is
  not durable until written as a workflow object.

### 5.5 Readiness Policies

Every board and match response reports one of:

- `READY`: all hard prerequisites for the requested next Action are satisfied;
- `DEGRADED`: analysis can continue, but missing/stale/conflicting inputs are listed;
- `BLOCKED`: a hard invariant prevents the requested transition.

Typical hard blocks include unresolved cross-source identity, missing required market
anchor, audit ERROR, stale confirmation nonce, unavailable authoritative result, and
optimistic version conflict. WARN conditions may require a recorded Adjudication;
ERROR conditions cannot be overridden in the UI.

## 6. Ontology and workflow additions

M1 adds only objects that can change a Forecast, Ticket, rule lifecycle, or audit
interpretation.

| Object/link | Purpose | Governance |
| --- | --- | --- |
| `Adjudication` | approve, reject, override, lock, withdraw | records actor, reason, alternative, and rejected evidence |
| `FlagInstance` | one flag triggered for one match at one time | links definition, evidence, direction, strength, and outcome |
| `Prediction` | preregistered claim and falsifier | outcome is graded by reconcile, never self-graded by AI |
| `PrecedentLink` | a typed link from current judgment to prior event | records comparison scope and evidence; does not copy prose |
| `AgentProposal` | an unapproved AI analysis or Action proposal | not a fact or committed Forecast; includes citations and model version |

`AgentProposal` is a durable workflow object, not verified evidence. Approval creates a
separate formal Action and result object; it does not mutate the Proposal into truth.

Claim adjudication remains distinct from decision adjudication:

- Claim status answers whether a source assertion is verified, disputed, or retracted.
- Adjudication records what the operator decided to do with evidence, a Forecast, a
  Ticket, or a lifecycle proposal.

Historical imported Forecasts without an EvidenceBundle are labeled
`legacy_unbundled`. The product must not fabricate historical bundles or display those
Forecasts as fully sourced. They may appear in historical metrics only with explicit
coverage caveats.

## 7. Canonical data flow

The normal evidence-to-learning chain is:

```text
SourceRun / SourceArtifact / Retrieval
  -> identity resolution
  -> provisional Claim or deterministic Observation
  -> human/system Claim adjudication
  -> EvidenceBundle frozen at cutoff
  -> AgentProposal / draft Forecast
  -> human Adjudication
  -> committed ForecastRevision
  -> Ticket proposal and deterministic audit
  -> approved Ticket and optional manual dispatch confirmation
  -> Outcome / correction version
  -> leg and ticket Settlement
  -> Forecast/Prediction/Flag/Adjudication score projections
  -> lifecycle proposal
  -> human lifecycle Action
```

No downstream object may silently substitute for a missing upstream object. In
particular, a narrative note is not a Claim, a Claim is not an Observation, a Forecast
is not a Ticket, and ticket profit is not forecast calibration.

## 8. Application workspaces

### 8.1 Command Center

The home screen is an attention and operations surface, not a recommendation ranking.
It shows:

- today's fixtures, kickoff/deadline, workflow state, evidence coverage, market move,
  flags, readiness, and next Action;
- ontology, source, projection, and event-stream health;
- pending identity/Claim/Forecast/Ticket/lifecycle adjudications;
- deadlines, failed tasks, stale evidence, and triggered falsifiers;
- explicit empty-slate behavior when no match is actionable.

No opaque "best bet score" is permitted.

### 8.2 Data Operations Center

This workspace exposes the operational Foundry plane:

- SourceRun status, latency, retries, freshness, and artifact lineage;
- three-source coverage and disagreement;
- alias gaps, unresolved identities, merge/split proposals, and duplicate risk;
- ingestion skips with machine-readable reasons;
- projection high-water marks and outbox lag;
- schedule state and recovery runbooks.

It may initiate safe retries and identity proposals through Actions. It must not offer
direct table editing.

### 8.3 Match Investigation Room

The investigation room binds all content to one canonical Match and one visible
`as_of` time. It contains:

- identity, competition/tie context, kickoff, venue, and source coverage;
- read-time and closing market snapshots, devig anchor, and movement timeline;
- evidence timeline with Claim/Observation type and adjudication state;
- availability, structure, tactical and scenario views;
- FlagInstances, PrecedentLinks, Prediction/falsifier state, and profile references;
- prior-to-belief comparison and Forecast revision history;
- an object-anchored AI investigation thread;
- an AgentProposal and adjudication queue.

AI responses display cited object IDs, source spans, model/version, timestamp,
conflicts, and missing evidence. If a required conflict is unresolved, the AI may save
a Proposal but cannot cause a committed Forecast.

### 8.4 Ticket and Adjudication Workbench

This is the primary decision surface. It provides:

- a face/selection matrix tied to committed Forecast revisions;
- ticket structure and version comparison;
- server-computed combinations, ticket price, budget use, thresholds, and coverage;
- inline C0-C7 audit results using the existing authoritative validator;
- WARN adjudication with `evidence_rejected` where policy permits;
- non-overridable ERROR states;
- explicit empty-slate and remove-leg Actions;
- an immutable audited ticket artifact with content hash.

Real dispatch is a protected two-stage flow:

1. Create and approve the immutable audited Ticket artifact.
2. On a separate confirmation surface, show channel, selections, total amount,
   deadline, audit state, and ticket hash. Jun submits a fresh per-ticket confirmation.

AI roles never receive `ConfirmDispatch`. If no external connector is configured, the
system records a human manual-placement Action and attaches a receipt artifact. The
core workflow remains complete without an external betting channel. Unattended or
rule-triggered automatic betting is permanently excluded.

### 8.5 Settlement and Review Center

Review separates three score planes:

- forecast truth: Brier, prior-relative skill, closing-line relationship, coverage;
- money ledger: stake, payout, net result, settlement method, conservation;
- intervention quality: Adjudication, rejected evidence, Prediction, and versioned
  counterfactuals.

Counterfactual views replay only preregistered alternatives and historical versions.
They must not invent hindsight alternatives after the outcome is known.

### 8.6 Rule and Calibration Center

This workspace shows Factor, Flag, Rule, Prediction, and Adjudication performance with
sample size, cohort, regime, coverage, Brier/CLV measures, and lifecycle state.

Calibrate may mechanically generate lifecycle proposals. Activating, retiring, or
changing a rule/factor requires human approval through a typed Action. A profitable
ticket cannot launder poor probability quality, and good Brier performance cannot
launder a broken money/settlement process.

### 8.7 Ontology Browser

The browser supports object search, typed links, source lineage, Action history,
versions, and `as_of` replay. It is an investigation tool, not a raw SQL editor.

### 8.8 Global Alert Stream

Alerts appear as a global rail rather than a separate silo. They include source and
schedule failure, stale data, unresolved identity, market movement thresholds,
falsifier triggers, deadlines, Action failures, event lag, and settlement corrections.

An alert records acknowledgement and resolution; dismissing it does not mutate the
underlying fact.

## 9. Scoreboard authority cutover

The current SOP declares `.nutmeg-data/scoreboard.json` the single source of truth.
M5 changes this only through a gated authority migration:

1. Build `ScoreboardProjection` from authoritative ForecastScore, Settlement,
   Adjudication, FlagInstance, Prediction, and lifecycle objects.
2. Run the projection in shadow and compare every supported metric to the existing
   JSON scoreboard. Differences must be classified as projection defect, legacy
   manual-only metric, or source correction.
3. Convert any legitimate manual-only metric into a formal source Action/object. Do
   not copy opaque counters into the projection.
4. Obtain explicit operator approval for the authority switch.
5. Update `docs/sop/CONSTITUTION.md`, `docs/sop/RUNBOOK.md`,
   `docs/sop/RULEBOOK.md`, `AGENTS.md`, and `CLAUDE.md` consistently.
6. Make ontology objects the authority and generate `scoreboard.json` as a read-only
   compatibility export. Manual edits become an error.

Until step 5, the existing SOP remains authoritative. There is no unannounced dual
authority period.

## 10. Error handling and degraded operation

### 10.1 General behavior

- Empty data is a designed state, not a blank screen.
- Every failed query or Action shows a stable error code and correlation ID.
- Retriable operations expose a safe retry only when idempotency is guaranteed.
- Version conflict presents the current version and a semantic diff. The system never
  applies last-write-wins to operator decisions.
- A stale browser view cannot approve a Forecast or Ticket without expected-version
  validation.
- Event disconnect changes the visible connectivity state and resumes by cursor.

### 10.2 Provider failure

Provider failure records a SourceRun result and preserves the last known value with its
age. It does not relabel the old value as current. Readiness policy decides whether the
requested next Action is degraded or blocked.

### 10.3 AI failure

If the AI provider is unavailable, deterministic board, identity operations, evidence
review, audit, ticket composition, settlement, and calibration remain usable. Partial
AI text is not persisted as a complete Proposal. A Proposal with missing citations or
invalid object references is rejected.

### 10.4 Outcome correction

Results are versioned; corrections never overwrite history. A corrected Outcome
triggers idempotent resettlement/projection rebuild under an explicit correction
Action, preserving the previous result and method version.

## 11. Security and authority

- The server binds to `127.0.0.1` by default. Non-loopback binding requires an explicit
  option and warning; v1 does not claim multi-user security.
- Mutations require same-origin validation, CSRF protection, a local authenticated
  session, and server-assigned actor roles.
- API payloads cannot choose their own privileged actor role.
- Source text, Claim quotes, and AI output are untrusted content and are escaped in UI.
- Source documents cannot instruct the system to execute Actions. Prompt-injection
  strings remain evidence content.
- Secrets never enter DTOs, event payloads, logs, model prompts, or browser storage.
- Funds-related endpoints accept only the human operator role and require a short-lived
  confirmation nonce bound to ticket hash and amount.
- No external telemetry is enabled by default.

## 12. Visual and interaction direction

The product retains Nutmeg's established ledger/editorial language rather than
imitating a generic enterprise dashboard:

- paper `#F5F7F3`, ink `#1B2620`, pine `#1F5C46`, cinnabar `#B23A2C`, and gold
  `#8A6F2F` are semantic colors;
- cinnabar is reserved for judgment, conflict, and pending adjudication;
- serif typography denotes authored judgment, sans-serif denotes interface structure,
  and tabular monospace denotes machine data;
- dense desktop layouts are primary, with responsive review/approval paths;
- motion is limited to meaningful state transitions, streaming evidence, and alert
  arrival;
- every color state also has text/icon semantics and supports keyboard navigation.

The backend is FastAPI. The final client choice is made after interaction prototypes:
SSR/HTMX is suitable for read-heavy surfaces, while isolated typed client components
may be used for the selection matrix, temporal exploration, graph views, and streaming
interaction. Regardless of client technology, deterministic logic remains in Python.

## 13. Milestones

### M1 - Product contract and ontology readiness

Deliver:

- versioned product DTOs and error envelope;
- Query Service, Action Gateway, durable outbox/SSE, and readiness policies;
- Adjudication, FlagInstance, Prediction, PrecedentLink, and AgentProposal semantics;
- `legacy_unbundled` handling;
- headless board, match, lineage, Action, event, and health APIs;
- one golden-day replay through Forecast approval.

Acceptance:

- product service imports no legacy DecisionStore/workbench files;
- every formal mutation has a committed/rejected/failed Action;
- idempotency, permission, optimistic concurrency, and `as_of` tests pass;
- outbox commit and restart recovery are proven;
- missing identity/evidence/readiness states are explicit.

### M2 - Read-only command and operations workspaces

Deliver Command Center, Data Operations Center, board filtering, health/readiness,
identity queues, lineage views, alerts, and responsive shell.

Acceptance: an operator can inspect one full day, understand every degraded/blocked
state, resolve supported identity Actions, and navigate to source lineage without using
the terminal.

### M3 - Match investigation and AI copilot

Deliver temporal evidence view, source conflicts, match context, market timeline,
structure/scenario blocks, anchored threads, cited AgentProposals, EvidenceBundle
freeze, and Forecast adjudication/revision.

Acceptance: a real match can move from sourced evidence to a committed Forecast with
no uncited AI write and no future-data leak.

### M4 - Ticket, audit, and protected confirmation

Deliver selection matrix, server-side composition, version comparison, inline C0-C7,
Adjudication capture, audited artifact, per-ticket confirmation, and manual receipt
recording. An external connector is optional and isolated behind the same protected
Action contract.

Acceptance: ticket generation, audit rejection, WARN adjudication, duplicate confirm,
stale confirm, empty slate, manual placement, and recovery paths pass end-to-end.

### M5 - Settlement, review, learning, and scoreboard authority

Deliver settlement/review center, forecast/money/intervention score planes,
counterfactual replay, rule/calibration center, lifecycle proposals, ontology browser,
and the gated Scoreboard authority migration.

Acceptance: a complete Ticket lifecycle settles odds-faithfully, ledger conservation
passes, projections rebuild from operational truth, and no lifecycle state changes
without human approval.

### M6 - Reliability, experience, and release

Deliver fault handling, observability, backup/restore, performance hardening, full E2E,
visual/accessibility verification, shadow/soak evidence, runbooks, and an explicit
ReleaseApproval Action.

Acceptance: all release gates in the next section are green.

## 14. Release gates

### G1 - Single-track authority

- Formal product has zero runtime dependency on legacy DecisionStore or decision JSONL.
- Scoreboard and SOP authority agree.
- Close/settle schedules and all product workflows use the approved v2 path.

### G2 - Deterministic integrity

- Full deterministic test suite passes.
- Golden migration/replay has zero unexplained identity, audit, ledger, or scoring
  differences.
- Property/invariant tests cover allocation, payout, settlement, state transitions,
  `as_of`, and projection conservation.

### G3 - Fault tolerance

- Provider timeout, partial response, invalid schema, SQLite lock, process interruption,
  duplicate Action, SSE disconnect, and projection interruption are exercised.
- Every scenario is either safely retryable, visibly degraded, or blocked without
  corrupting state.

### G4 - AI safety

- Uncited or invalid-citation Proposals cannot advance.
- AI roles cannot verify Claims, commit Forecasts, approve Tickets, dispatch funds, or
  apply lifecycle decisions.
- Prompt-injection fixtures cannot change actor role, call an Action, or hide source
  conflicts.
- Model/version and cited input coverage are recorded for every durable Proposal.

### G5 - Product experience

- Desktop and narrow-screen E2E cover the complete operator lifecycle.
- Empty, loading, degraded, blocked, conflict, offline, and restored states are tested.
- Core workspaces have targeted visual snapshots and keyboard-navigation checks.
- On the reference dataset at ten times the M0 object volume: board query p95 is at
  most 500 ms, match aggregate query p95 is at most 800 ms, non-external Action
  acknowledgement p95 is at most 1 second, and local event reconnect resumes within
  2 seconds.

### G6 - Operations and release authority

- At least 14 calendar days of shadow/soak cover both JCZQ and Zucai workflows with
  zero unexplained identity, audit, or ledger divergence.
- Backup/restore reproduces object counts, Action high-water mark, ticket hashes, and
  ledger balances.
- Health, source freshness, Action failures, query latency, projection high-water mark,
  and outbox lag are observable locally.
- Jun executes an explicit ReleaseApproval Action after reviewing the evidence.

## 15. Test strategy

| Layer | Required coverage |
| --- | --- |
| Unit and property | deterministic functions, DTO assembly, state machines, policies, permissions, scoring, projection invariants |
| Contract | OpenAPI/schema snapshots, pagination, error codes, version compatibility, idempotency conflict |
| Integration | SQLite + DuckDB + CAS + outbox, transaction rollback, crash/restart, correction replay |
| Security | CSRF/origin, actor spoofing, prompt injection, HTML escaping, secret redaction, confirmation nonce |
| Browser E2E | operations -> investigation -> Forecast -> Ticket -> audit -> confirmation -> settlement -> review |
| Visual/accessibility | core desktop/narrow layouts, semantic status, keyboard paths, focus/error behavior |
| Shadow/soak | real read-only or non-dispatch daily chains, source failures, schedule behavior, reconciliation |
| Recovery | backup restore, replay from high-water mark, event cursor recovery, projection rebuild |

Each milestone uses TDD and its own focused implementation plan. M1 is implemented and
verified before an M2 plan is executed; the same dependency rule continues through M6.
Program-level approval does not waive milestone verification.

## 16. Observability

The local operations plane records and exposes:

- SourceRun success, latency, retries, skip reason, artifact count, and freshness;
- identity resolution and merge/split queue sizes;
- Action committed/rejected/failed counts and durations;
- Query latency and error rate by endpoint;
- outbox high-water mark, delivery cursor, and lag;
- DuckDB projection high-water marks and rebuild results;
- AI Proposal count, citation coverage, refusal/rejection reason, model/version;
- ticket confirmation, settlement, correction, and ledger-invariant status;
- backup age and last successful restore drill.

Logs are structured and redact secrets and source credentials. Correlation IDs link an
HTTP request, Action, outbox event, and resulting objects.

## 17. Explicit exclusions

V1 does not include:

- multi-user tenancy, team permissions, subscriptions, billing, or public publishing;
- cloud sync or a native mobile application;
- generic no-code ontology editing;
- direct SQL editing through the browser;
- a second probability/settlement implementation in the client;
- hindsight-generated counterfactuals;
- AI verification of its own claims or autonomous lifecycle decisions;
- unattended or rule-triggered automatic betting.

## 18. Implementation decomposition

This document is the program architecture, not one giant implementation task. Work is
split into six independently testable milestone packages. The next artifact after user
review is a detailed M1 implementation plan. M2 planning begins only after M1 passes
its fresh verification gate, and the sequence repeats through M6.

No milestone may expand product authority beyond this design without returning to a
design review.
