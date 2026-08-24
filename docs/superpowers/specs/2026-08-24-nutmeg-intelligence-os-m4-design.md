# Nutmeg Intelligence OS M4 - Ticket, Audit, and Protected Confirmation Design

Date: 2026-08-24
Status: Approved by the program architecture and the operator's continuous implementation authorization
Scope: M4 only; M1-M3 remain closed unless a regression is found

## 1. Outcome

M4 turns committed Forecast revisions into governed ticket decisions without making
approval synonymous with placement. It delivers one ontology-backed Ticket and
Adjudication Workbench in which the operator can:

1. select faces against the current committed Forecast revision;
2. ask the server to compose the slate with the existing `compose_tickets()` function;
3. inspect the existing C0-C7 audit result from `audit_legs()`;
4. create immutable, versioned ticket-batch revisions;
5. remove a leg through a typed Action and compare revisions;
6. adjudicate every WARN with a reason and `evidence_rejected` references;
7. approve a clean revision and receive one content-addressed artifact per composed
   ticket;
8. open a separate confirmation surface and obtain a short-lived per-ticket nonce;
9. confirm a manual placement with a receipt, after which and only after which the
   formal Ticket, BetLegs, stake CashTransaction, and placement record are committed.

An empty slate is a first-class, legal batch revision. It creates no Ticket, consumes
no confirmation nonce, and writes no CashTransaction.

M4 does not call a betting provider, Telegram, an external model, or a production
scheduler. A connector port is defined and tested with a fake implementation, but no
live connector is configured or shipped.

## 2. Locked constraints

- `compose_tickets()` remains the only budget/allocation/combinations implementation.
- `audit_legs()` remains the only C0-C7 implementation.
- Product JavaScript performs no probability, audit, budget, payout, or settlement
  arithmetic.
- Every leg is tied to the current committed Forecast revision for its match/market.
- Ticket approval does not debit the ledger and does not mean that a bet was placed.
- A formal Ticket and stake debit are written only after protected confirmation.
- Audit ERROR is non-overridable. Audit WARN requires an explicit human Adjudication.
- AI may propose selections but cannot approve a batch, issue or consume a confirmation,
  record placement, or choose a privileged actor role.
- Confirmation is per composed ticket, not per slate.
- A confirmation nonce is single-use, short-lived, stored only as a digest, and bound
  to ticket artifact hash, exact amount, and channel.
- The existing kernel `ExpressService` and `decision-close` compatibility path keep
  their current immediate-booking semantics in M4. M6 may retire that compatibility
  path only after the formal product flow is the approved operational authority.
- `.nutmeg-data/scoreboard.json` remains the Scoreboard authority until M5 completes
  its explicit cutover.

## 3. Considered approaches

### 3.1 Change existing `approve_ticket()` into a two-stage operation

This produces the fewest new classes but is rejected. The current Action is used by
`decision-close`, `ExpressService`, settlement tests, and analytics fixtures. Changing
its meaning would silently stop the CLI from creating the Ticket and stake transaction
that downstream reconcile expects. A feature flag would also create two meanings for
one Action type.

### 3.2 Add confirmation fields directly to the existing `tickets` table

This preserves more of the current schema but is rejected. An approved-yet-unplaced
row would be indistinguishable from legacy approved Tickets, and current settlement
and ledger code assumes an existing Ticket represents a booked stake. Nullable state
columns would spread compatibility branches through finance and analytics.

### 3.3 Add a governed pre-booking model and preserve legacy Express compatibility

This is the selected approach. Immutable TicketBatchRevision and
AuditedTicketArtifact objects represent the decision before money is recorded. A
separate ConfirmTicketPlacement Action validates a durable confirmation challenge and
then uses the same finance persistence invariants to create the existing Ticket,
BetLegs, and CashTransaction atomically. This gives the formal product a correct
two-stage flow without changing the existing CLI contract.

The cost is a small temporary compatibility seam: M4 has both the legacy immediate
Express facade and the new protected product facade. The seam is explicit, tested, and
scheduled for M6 authority review; it is not a second arithmetic or audit path.

## 4. Domain model

### 4.1 TicketBatchRevision

A TicketBatchRevision is an immutable server-computed revision of one workbench slate.
It stores:

- stable `ticket_batch_id` and monotonic `revision_no`;
- `ticket_batch_revision_id` and optional superseded revision;
- business date, channel, account, currency, and deadline;
- canonical input legs, including the operator-authored audit facts;
- the exact result returned by `compose_tickets()`;
- the exact normalized findings returned by `audit_legs()`;
- deterministic content hash and CAS SourceArtifact reference;
- state `draft`, `empty`, `approved`, or `approved_empty`;
- creator Action and timestamp.

The input leg contract separates deterministic identifiers from operator judgment:

```text
match_id, match_no, name, market_definition_id, selection_id, outcome_key,
faces, forecast_revision_id, quote_id, odds, line, bucket,
fair, confidence, directional_flags, nondirectional_flags,
anchor_integrity, precedents
```

The service verifies identifiers, quote price, and current committed Forecast. It does
not invent confidence, flags, precedent status, anchor integrity, or selected faces.
Those values are explicit operator inputs and become part of the artifact hash.

`CreateTicketBatch` writes revision 1. `RemoveTicketLeg` takes an expected current
revision number, removes exactly one addressed input leg, recomputes composition and
audit on the server, and writes a new revision. It never mutates the prior revision.
Removing the final leg creates an `empty` revision. `ApproveTicketBatch` validates the
current draft/empty revision, then writes a new immutable `approved`/`approved_empty`
revision with the same inputs and deterministic result. Artifacts point only to that
approved revision; neither a draft nor an empty revision is updated in place.

### 4.2 AuditFindingIdentity and Adjudication

Each normalized WARN has a stable identity derived from:

```text
ticket_batch_revision_id | level | code | match_no | message
```

The UI records a normal governed Adjudication whose subject is
`ticket_audit_finding` and whose subject ID is that finding identity. The
Adjudication must contain:

- decision `accept_warning` or `reject_ticket`;
- a non-empty human reason;
- `evidence_rejected`, which may be an empty list only when the operator explicitly
  states that no evidence was rejected;
- optional alternative.

Approval requires exactly one latest `accept_warning` Adjudication for every current
WARN. Adjudications for a superseded revision do not carry forward automatically.
ERROR findings always block approval, regardless of Adjudication content.

### 4.3 AuditedTicketArtifact

Approving a non-empty clean batch revision creates one immutable
AuditedTicketArtifact per item in the authoritative composition result. Its canonical
JSON includes:

- schema and policy versions;
- batch and revision identity;
- channel, account, currency, amount, and deadline;
- exact ticket structure and allocated stake;
- exact leg identifiers, Forecast revisions, quote identifiers, booking odds, and
  audit inputs;
- all normalized audit findings and the Adjudication IDs satisfying WARNs;
- creation and approval Action identity.

The SHA-256 of those bytes is the ticket hash shown on the confirmation surface. The
bytes are written to the existing immutable CAS, registered as a SourceArtifact, and
linked from the new ontology row. Approval creates no row in `tickets`, `bet_legs`, or
`cash_transactions`.

Approving an empty revision commits an explicit approved-empty revision and returns
the batch reference. It creates zero ticket artifacts and is successful.

### 4.4 ConfirmationChallenge

`IssueTicketConfirmation` is a judge-only Action. It verifies that the ticket artifact
is approved, unplaced, not past its deadline, and still references current committed
Forecast revisions. It returns a random plaintext nonce once while storing only:

- challenge ID and nonce SHA-256;
- ticket artifact ID, ticket hash, exact amount, currency, and channel;
- issuance and expiry timestamps;
- nullable consumption timestamp and consuming Action ID.

The default lifetime is five minutes. A newer challenge does not make an older fresh
challenge invalid, but successful consumption makes all other challenges for the same
ticket artifact unusable because the artifact can be placed only once.

### 4.5 TicketPlacement

`ConfirmTicketPlacement` is a judge-only Action and requires:

- challenge ID and plaintext nonce;
- ticket artifact ID, displayed ticket hash, channel, and exact amount;
- placement mode `manual` or `connector`;
- for manual placement, a non-empty external/manual reference and non-empty receipt
  bytes with declared content type;
- an idempotency key.

The handler verifies the nonce digest with constant-time comparison, expiry, binding,
single-use state, deadline, current Forecast revisions, budget policy, and absence of
an existing placement. For manual placement it writes the receipt to CAS and registers
the receipt SourceArtifact and retrieval in the same Action transaction. It then
atomically writes:

1. the existing formal Ticket;
2. its BetLegs with the artifact's booking odds;
3. one negative stake CashTransaction;
4. one TicketPlacement linking the artifact, Ticket, receipt, and external reference;
5. challenge consumption.

The Action result returns Ticket, BetLeg, CashTransaction, TicketPlacement, and receipt
references. Thus “没入账 = 没打” remains mechanically true.

Connector mode goes through a `TicketPlacementConnector` port. No default connector is
configured. A request when the port is absent is blocked before consuming the
challenge. Fake-connector tests prove the authority boundary; M4 performs no real
dispatch. Reliable external side-effect recovery remains an M6 release concern and a
connector cannot be enabled by browser payload.

## 5. Persistence and migration 12

Migration 12 adds four typed tables:

```text
ticket_batch_revisions
  ticket_batch_revision_id TEXT PK
  ticket_batch_id TEXT NOT NULL INDEX
  revision_no INTEGER NOT NULL
  supersedes_revision_id TEXT NULL FK self RESTRICT
  run_date TEXT NOT NULL
  channel TEXT NOT NULL
  account_id TEXT NOT NULL FK cash_accounts RESTRICT
  currency TEXT NOT NULL
  deadline_at TEXT NOT NULL
  input_legs_json TEXT NOT NULL
  composition_json TEXT NOT NULL
  audit_findings_json TEXT NOT NULL
  state TEXT NOT NULL
  content_hash TEXT NOT NULL
  source_artifact_id TEXT NOT NULL FK source_artifacts RESTRICT
  created_at TEXT NOT NULL
  created_by_action_id TEXT NOT NULL FK actions RESTRICT
  UNIQUE(ticket_batch_id, revision_no)

audited_ticket_artifacts
  ticket_artifact_id TEXT PK
  ticket_batch_revision_id TEXT NOT NULL FK ticket_batch_revisions RESTRICT
  ticket_index INTEGER NOT NULL
  ticket_hash TEXT NOT NULL UNIQUE
  source_artifact_id TEXT NOT NULL FK source_artifacts RESTRICT
  amount REAL NOT NULL
  currency TEXT NOT NULL
  channel TEXT NOT NULL
  deadline_at TEXT NOT NULL
  payload_json TEXT NOT NULL
  approved_at TEXT NOT NULL
  approved_by_action_id TEXT NOT NULL FK actions RESTRICT
  UNIQUE(ticket_batch_revision_id, ticket_index)

ticket_confirmation_challenges
  confirmation_id TEXT PK
  ticket_artifact_id TEXT NOT NULL FK audited_ticket_artifacts RESTRICT
  nonce_hash TEXT NOT NULL UNIQUE
  ticket_hash TEXT NOT NULL
  amount REAL NOT NULL
  currency TEXT NOT NULL
  channel TEXT NOT NULL
  issued_at TEXT NOT NULL
  expires_at TEXT NOT NULL
  consumed_at TEXT NULL
  consumed_by_action_id TEXT NULL FK actions RESTRICT

ticket_placements
  ticket_placement_id TEXT PK
  ticket_artifact_id TEXT NOT NULL UNIQUE FK audited_ticket_artifacts RESTRICT
  ticket_id TEXT NOT NULL UNIQUE FK tickets RESTRICT
  placement_mode TEXT NOT NULL
  external_reference TEXT NOT NULL
  receipt_artifact_id TEXT NULL FK source_artifacts RESTRICT
  receipt_retrieval_id TEXT NULL FK artifact_retrievals RESTRICT
  placed_at TEXT NOT NULL
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT
```

Migration 12 grants these permissions only to `judge_operator`:

- `create_ticket_batch`
- `remove_ticket_leg`
- `approve_ticket_batch`
- `issue_ticket_confirmation`
- `confirm_ticket_placement`

AI retains its existing `propose_ticket` permission for the legacy proposal object but
receives none of the new protected permissions. Product APIs do not expose the legacy
immediate `approve_ticket` Action.

## 6. Service boundaries

### 6.1 TicketCompositionService

This pure orchestration unit maps validated workbench legs to the exact legacy shapes,
calls `compose_tickets()` and `audit_legs()`, normalizes the results, and emits canonical
bytes. It owns no arithmetic and writes no data. Direct tests compare its output to the
authoritative functions to catch drift.

### 6.2 ProtectedTicketActions

This ontology service owns Create, Remove, Approve, IssueConfirmation, and
ConfirmPlacement Actions. All persistence happens through the existing Unit of Work and
ActionService. Finance row creation is factored into a private shared booking helper so
legacy `TicketActions.approve_ticket()` and protected confirmation enforce identical
forecast, budget, Ticket, BetLeg, and CashTransaction invariants without changing the
legacy public behavior.

### 6.3 Product contract

The Query Service adds:

- `GET /api/v1/ticket-workbench?date=...&as_of=...`
- `GET /api/v1/ticket-batches/{ticket_batch_id}`
- `GET /api/v1/ticket-artifacts/{ticket_artifact_id}`

The first response supplies only server-derived match identity, committed Forecast,
selection definitions, current quotes, prior batch revision, audit and confirmation
state. It never returns a client-calculated stake or audit result.

Mutations use typed dedicated request/response DTOs while retaining the existing local
session, same-origin, CSRF, server-assigned actor, idempotency, and error envelope:

- `POST /api/v1/ticket-batches`
- `POST /api/v1/ticket-batches/{id}/remove-leg`
- `POST /api/v1/ticket-batches/{id}/approve`
- `POST /api/v1/ticket-artifacts/{id}/confirmations`
- `POST /api/v1/ticket-artifacts/{id}/confirm`

The generic `/api/v1/actions` endpoint remains available for WARN Adjudications. Raw
receipt bytes are accepted as base64 only by the manual confirmation DTO, decoded at
the HTTP boundary, and never copied into an Action payload or event.

Stable M4 errors include:

```text
ticket_audit_blocked
ticket_warning_unadjudicated
ticket_revision_conflict
ticket_deadline_passed
confirmation_stale
confirmation_reused
confirmation_binding_mismatch
ticket_already_placed
connector_unavailable
receipt_required
```

## 7. Workbench experience

The new `/tickets` workspace uses the existing Nutmeg ledger/editorial shell. Desktop
shows a dense face matrix beside a sticky deterministic ticket ledger. Narrow screens
turn each match into a full-width card and keep approval controls in document order.

The page shows:

- current committed Forecast revision and belief for each eligible match;
- face controls, quoted odds, bucket, and explicit audit facts;
- server-computed ticket count, amount, structure, and coverage summary;
- ERROR/WARN findings with rule code and origin loss (`since`);
- WARN Adjudication forms including evidence rejected;
- revision timeline and semantic comparison;
- explicit “remove leg” and “record empty slate” paths;
- approved artifact hash, amount, deadline, and placement state;
- a separate confirmation panel with a five-minute expiry indicator, receipt picker,
  manual reference, and final human confirmation button.

The browser may assemble form fields and display the server response. It cannot compute
stake, combined odds, audit results, hashes, expiry validity, or placement readiness.
Controls are keyboard reachable, at least 44 CSS pixels on narrow screens, and include
visible focus and text semantics independent of color.

## 8. Failure, restart, and concurrency behavior

- Reusing an idempotency key with equal content replays the stored outcome.
- Reusing it with different content returns 409 and makes no additional object.
- Removing a leg from a stale batch revision returns a version conflict.
- An ERROR finding prevents approval and creates no ticket artifact.
- A missing WARN Adjudication prevents approval and names each finding identity.
- A stale, malformed, mismatched, or consumed nonce writes no Ticket or CashTransaction.
- Duplicate confirmation with the same idempotency key replays the first Ticket.
- A different key with the consumed nonce is rejected and cannot double debit.
- Process restart between nonce issuance and confirmation is supported because the
  digest and binding are durable.
- Process interruption inside confirmation rolls back challenge consumption, Ticket,
  BetLegs, CashTransaction, placement, and receipt metadata together. An orphaned CAS
  receipt blob is harmless and reusable under the existing CAS contract.
- Forecast revision changes after approval make confirmation blocked; the operator must
  create and approve a new batch revision.
- Empty slate and connector-unavailable states are visible, successful/non-corrupting
  outcomes rather than blank screens or silent fallbacks.

## 9. Test and verification strategy

M4 is implemented in strict RED-GREEN-REFACTOR slices.

Unit and property coverage proves:

- workbench mapping delegates to `compose_tickets()` and `audit_legs()`;
- content hashes are stable under mapping-order changes and change under any material
  ticket, Forecast, audit, amount, or deadline change;
- every new state transition and permission boundary;
- AI denial for every protected Action;
- ERROR block, WARN adjudication, empty slate, stale revision, and stale Forecast;
- nonce entropy shape, digest-only storage, exact binding, expiry, single use, duplicate
  replay, and restart recovery;
- receipt CAS behavior and ledger conservation;
- existing Express, close, settle, and analytics behavior remains unchanged.

Contract and product tests prove strict DTOs, OpenAPI exposure, origin/CSRF enforcement,
receipt redaction from Action/event views, stable errors, and query pagination/order.

Browser verification covers 1440x1000 and 390x844 for draft, ERROR-blocked,
WARN-pending, approved, confirmation, placed, empty, offline, and recovered states. It
checks overflow, 44-pixel controls, keyboard order, focus/error behavior, console errors,
and SSE recovery.

The frozen replay uses a copy of the verified M3 replay store. It performs no provider
fetch and no real dispatch. On an isolated copy it creates one audited batch, resolves
one WARN if present, issues and consumes a manual confirmation with a fixture receipt,
then verifies one Ticket, one stake transaction, matching content hash, Action lineage,
and unchanged source data. Dry close and settle remain callable against their existing
compatibility path.

M4 closes only after focused product/ontology/decision tests, full pytest, Ruff,
compileall, pre-commit, browser evidence, frozen replay, `verify`, and the spec-coverage
completion gate all pass with a clean worktree.

## 10. Explicit non-goals

M4 does not implement settlement/review projections, Scoreboard authority, lifecycle
calibration UI, backup/restore, scheduler restoration, live connector delivery, or a
release approval. Those belong to M5 and M6. It does not modify the SOP trilogy or
claim that the new workbench is production betting authority.
