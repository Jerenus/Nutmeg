# Nutmeg Dual-Lane Operator Workbench Rebuild Design

Date: 2026-09-03
Status: Written spec approved by Jun on 2026-09-04
Scope: Make the local Application the primary daily operator surface for both JCZQ and Zucai

## 1. Purpose

Nutmeg's ontology kernel and deterministic decision services are operating, but the
Application is not connected to the current production lifecycle. The existing focused
workbench still derives tasks from a transitional Zucai rx-file contract. Production
artifacts evolved after issue 26112, while the Application contract and its fixtures did
not. A green product test suite therefore certifies an old shape rather than the current
workflow.

This rebuild makes the Application useful for daily operation without moving football
judgment into software. The Application becomes the primary surface for reviewing
evidence, recording the human decision, comparing ticket structures, auditing, requesting
protected confirmation, observing Telegram-confirmed placement/ledger state, requesting
settlement, and reviewing. Existing CLI and Telegram workflows remain responsible for
collection and evidence supplementation.

This design refines and supersedes the transitional artifact boundary in
`docs/superpowers/specs/2026-08-28-phase-aware-operator-workbench-design.md`. The focused
interaction model, ontology authority, typed Action boundary, and safety rules from that
design remain in force.

## 2. Production diagnosis

The 2026-09-03 read-only audit established the following baseline:

- ontology schema 16 passes SQLite integrity checks and contains 6,606 Actions;
- the morning pipeline collected eight official Sporttery fixtures and four international
  market fixtures, producing seven canonical Matches and eleven Snapshots;
- all 616 Team entities remain provisional, and only five of eight current aliases resolve;
- Observation, Claim, and EvidenceBundle counts are all zero;
- the Application opens expired issue 26112, while issues 26113-26116 produce 12, 13, 18,
  and 26 source-contract errors respectively;
- formal ticket batches, audited artifacts, placements, and settlements are all empty;
- the scoreboard and objectified observation flow stopped on 2026-08-31, and its projection
  is stale against later Actions;
- three writable Application instances were running concurrently;
- no active Telegram token owner exposed a working ticket-confirmation callback route or
  heartbeat;
- 309 product tests passed, but their operator fixture represented only issue 26112.

The failure is not that all daily collection stopped. It is that current collection,
formal evidence, Application state, protected ticketing, ledger, and calibration no longer
form one temporal chain.

## 3. Decisions approved in brainstorming

The following choices are binding for this rebuild:

1. JCZQ and Zucai are implemented together against a shared operator contract.
2. Tasks are discovered deterministically from the official sale schedule. A task does
   not require an rx file to exist.
3. The home surface is a unified Today queue with separate JCZQ and Zucai lane views.
4. For JCZQ, the evidence gate covers every official fixture still offered at the task
   snapshot. For Zucai, it covers all fourteen official issue fixtures. JCZQ retains one
   day view but uses each fixture's real sale deadline; closed fixtures never expire later
   fixtures by association.
5. Every match must pass a structured evidence checklist before judgment or ticket
   construction can begin. Missing, stale, or conflicting evidence blocks the whole task.
6. Collection and evidence supplementation remain external CLI/Telegram work. The
   Application displays gaps and refreshes formal state; it does not embed an autonomous
   research agent.
7. Once evidence is complete, the system freezes a market-baseline counterfactual. It is
   visible before human judgment but is never deployable.
8. After every match has a committed human+AI structured judgment, deterministic services
   generate adjusted ticket candidates and compare them with the baseline. Only adjusted
   candidates can proceed to final adjudication.
9. No-ticket is never an automatic fallback or generic recommendation. CONSTITUTION makes
   it legal at every phase, so Jun may choose it as soon as an official task exists. When
   baseline/candidates exist, the decision must preserve them as preregistered
   counterfactuals; an earlier decision preserves the exact missing-data snapshot instead.
10. The Application is the main surface for judgment and ticket operation. Telegram is a
    lightweight reminder/resume channel and the separate human confirmation surface.
11. `ConfirmDispatch` remains unavailable to every AI role. No component automatically
    places a bet.

## 4. Product shape

### 4.1 Primary navigation

The primary navigation contains three stable views:

- **Today**: all current human actions across both lanes, ordered by deadline;
- **Zucai**: active/current-focus issues and the recent issue archive;
- **JCZQ**: active/current-focus Shanghai sale days and the recent day archive.

System maintenance remains one quiet icon/link. Ontology, identity, source health,
projection administration, calibration administration, and release governance remain
available there, but they do not occupy the first viewport.

### 4.2 Today queue

Today answers one question: what needs Jun now?

The queue is not a metric dashboard. It contains a single emphasized next action followed
by later actions, externally blocked work, confirmation/shadow follow-up,
placement-ledger integrity incidents, review items, and lane-level collection recovery.
A task row states the lane, business key, `next_deadline` when one exists, phase, progress,
blocking reason, and next permitted action. A lane-level schedule-recovery row has no fake
business key or task snapshot; it names the Shanghai check date and the external collection
recovery action instead.

The ordering tuple is deterministic:

1. open human actions before a known deadline;
2. overdue confirmation/shadow actions and placement-ledger integrity incidents;
3. evidence-complete tasks awaiting judgment or ticket action;
4. externally blocked evidence work, ordered by the nearest deadline;
5. review work awaiting human disposition, including zero-placement work whose settlement
   state is `not_applicable`;
6. lane-level official-schedule recovery.

Completed work items and passive work items whose deployment window expired are archive-only.
A task appears in Today only through a current child work item with a human action or an
external blocker relevant to a non-terminal deadline; passive waiting for a result does not
keep it in the queue. A later settlement or review work item may return the task to Today
without reopening deployment. Equal ordering keys are resolved by lane, business key,
scope kind, and work-item ID so repeated reads cannot reorder the queue.

Odds direction, confidence, EV, predicted value, or a football narrative may not affect
task ordering.

## 5. Task discovery and lifecycle

### 5.1 Authoritative discovery input

Canonical Match rows alone cannot represent a Zucai issue number, official match order,
sale window, or the markets currently offered for JCZQ. Add the following ontology objects:

```text
OfficialSaleSlateRevision
  slate_revision_id, lane, business_key, revision_no
  source_artifact_retrieval_id, published_at, retrieved_at
  valid_from, supersedes_revision_id, content_hash

OfficialOffer
  official_offer_revision_id, official_offer_family_id, slate_revision_id
  match_id, official_match_no
  market_definition_ids, sale_opens_at, sale_deadline_at, status

OfficialScheduleCheckReceipt
  schedule_check_id, lane, shanghai_check_date, checked_at, source_run_id
  check_state, official_source_artifact_retrieval_id
  imported_business_keys, error_code
```

The importer accepts only `OfficialSaleSlateManifestV1`:

```text
schema_version = "official-sale-slate-v1"
lane, business_key, published_at, retrieved_at
official_source_artifact_retrieval_id, supersedes_slate_revision_id
offers: list[OfficialOfferManifestV1]

OfficialOfferManifestV1
  canonical_match_id, official_match_no, market_definition_ids
  sale_opens_at, sale_deadline_at
  status = scheduled | on_sale | sale_closed | cancelled
```

The referenced retrieval must be an official Sporttery schedule/sale artifact. A 500.com
page, rx/prep narrative, API-Football fixture, or inferred kickoff-minus-offset is not an
official sale slate. Sale times must be timezone-aware source fields; a missing deadline is
not synthesized.

An external official-schedule importer commits both through
`import_official_sale_slate` as a `deterministic_system` Action. Import is atomic,
idempotent, and reconciles returned counts against ontology rows. It rejects duplicate
official match numbers, unresolved Match references, missing deadlines, invalid market
definitions, and a revision that does not supersede the current slate.

The same external collection run records exactly one `OfficialScheduleCheckReceipt` for
each lane and Shanghai calendar date. `check_state` is one of `slate_imported`,
`confirmed_no_sale`, or `failed`. `slate_imported` requires a non-empty exact list of
business keys committed by that run. `confirmed_no_sale` requires an official retrieval
that explicitly shows no published sale and an empty list. `failed` requires a closed error
code and does not claim that no sale exists. A missing receipt means the check has not run.
These receipts are operational collection facts, not football judgments, and the browser
cannot create them.

### 5.2 Task identity and per-offer time

An operator task remains a derived read model, not another source-of-truth table:

```text
task_id      = <lane>:<business_key>
lane         = jczq | zucai
business_key = Shanghai sale date for JCZQ | official issue number for Zucai
```

The task is a stable day/issue container, not a single mutable phase. Its actionable children
are derived work items:

```text
work_item_id = <task_id>:<task_snapshot_hash>:<scope_kind>:<scope_key>
scope_kind   = sale_wave | artifact | ticket | review
```

A `sale_wave` binds one exact set of selectable offers and their slate/task snapshot. Zucai
normally has one wave. JCZQ may have successive waves as early offers close while later offers
remain open. An approved artifact, placed Ticket, or review retains its own work item after
the sale wave that created it is no longer current. At most one sale wave is current for the
same task snapshot; multiple artifact, ticket, and review work items may coexist.

`official_offer_family_id` is the stable server-derived identity of one official offer within
a lane/business key across slate revisions. A revision receives a new
`official_offer_revision_id` but retains the family ID when its official match identity is
unchanged. This is how an explicit
no-ticket scope remains closed across a correction while a genuinely added offer receives a
new family ID and a new sale wave.

Task discovery reads the current `OfficialSaleSlateRevision`; it never scans for
`*-rx.json` names.

- A Zucai task exists when the current official issue revision contains exactly fourteen
  ordered offers.
- A JCZQ task exists when the current official day revision contains at least one offer.
- The server derives one `offer_state(as_of)` with this precedence: an offer cancelled or
  removed by the current revision is `cancelled`; an explicitly closed offer or one with
  `sale_deadline_at <= as_of` is `closed`; a remaining offer with
  `as_of < sale_opens_at` is `upcoming`; otherwise it is `open`. Equality at opening is
  open; equality at deadline is closed. The importer rejects unknown source states,
  `sale_opens_at >= sale_deadline_at`, and a source marked `on_sale` when its own
  `published_at` is outside that interval.
- At any `as_of`, the JCZQ evidence gate covers every open offer in the current sale wave.
  A closed early fixture becomes read-only and cannot be selected, while later fixtures
  remain active in the same day view.
- A JCZQ task has no invented day-wide cutoff. Its queue deadline is the minimum deadline
  among current upcoming/open offers and open confirmation challenges. Thus an upcoming
  offer on which Jun may already exercise no-ticket still has an ordering deadline. An
  artifact deadline is frozen at approval as the minimum real deadline among every offer
  referenced by that artifact; it is never recomputed after one of those offers closes.
- If today's schedule-check receipt is absent or failed, Today shows a lane-level
  `official_schedule_missing` recovery item with the last SourceRun state, even if an older
  non-terminal task is still visible. `slate_imported` or `confirmed_no_sale` suppresses that
  item; the latter does so without inventing a task or issue number.
- A new official slate revision invalidates the derived task snapshot. It never mutates a
  frozen evidence bundle, baseline, judgment, or ticket; affected work must be explicitly
  refreshed against the new revision.
- A protected artifact keeps its originally frozen deadline as history, but confirmation
  uses `effective_cutoff = min(frozen_deadline, every current referenced-offer deadline)`.
  A superseding official revision may shorten this cutoff or cancel/remove an offer, never
  extend it. The import transaction invalidates affected open challenges and records
  `official_deadline_shortened` or `official_offer_cancelled` shadow outcomes when the new
  cutoff is already terminal. The callback rechecks the same current offer revisions in its
  atomic placement transaction, so it cannot win a race after the official correction.
  Tickets placed before the correction remain immutable and use official-void settlement
  when applicable; no stake is silently reversed.

The canonical `task_snapshot_hash` is SHA-256 over canonical JSON containing the lane,
business key, current slate revision ID and content hash; every current offer's family ID,
revision ID, official order, market definitions, source status, opening/deadline timestamps,
and derived offer state; and the current no-ticket-closed family/revision set. The raw
`as_of` timestamp is not hashed, so time passing inside one state interval does not churn
forms. Each signed `expected_snapshot_token` additionally binds that task hash, work-item
ID, command kind, and every current workflow-object/challenge/terminal-receipt revision read
by that form. Crossing an opening or deadline boundary changes the derived state vector and
invalidates every unsubmitted mutation form, even when no importer ran. A slate revision or
state-vector change creates a new sale-wave snapshot from the still-actionable offer
families. Existing no-ticket Actions continue to close only the family IDs in their
immutable scope; an offer family newly added by a revision is never inherited into that
adjudication and appears in a new sale wave.

### 5.3 Public work-item phases

```text
waiting_schedule
  -> prepare_evidence
  -> judge_matches
  -> compare_tickets
  -> audit_deployment
  -> await_confirmation
  -> await_result
  -> review
  -> complete
```

`waiting_schedule` belongs only to the lane-level recovery item; no task/work-item ID exists
until a valid slate supplies a business key. Each task work item uses only the applicable
segment beginning at `prepare_evidence`. The task summary does not invent one phase from
incompatible children: it exposes ordered work items and names the
highest-priority item as `next_action`. Thus an early JCZQ artifact may be `await_result`
outside Today while the current later-offer sale wave remains `judge_matches`, and a prior
review may return to Today alongside it.

A sale-wave or artifact work item is paired with an orthogonal deployment outcome. Legal
values are closed by scope:

| Scope kind | Legal phase segment | Legal deployment outcome |
| --- | --- | --- |
| `sale_wave` | `prepare_evidence` through `complete`, or `blocked` | `pending | placed | partially_placed | no_ticket | expired` |
| `artifact` | `await_confirmation` through `complete`, or `blocked` | `pending | placed | no_ticket | expired` |
| `ticket` | `await_result` through `complete`, or `blocked` | null |
| `review` | `review | complete | blocked` | null |

`expired` means every selectable offer in that work item is sale-terminal, no artifact in its
scope was placed, and no explicit no-ticket adjudication resolved the scope. `closed` and
`cancelled` are both sale-terminal. Closing one JCZQ offer or artifact never expires the day
task or another work item. An expired outcome does not erase result/review obligations or
reopen sale. `blocked` is an exceptional phase when a contract, integrity, policy, audit, or
concurrency error prevents the ordinary resolver from proceeding.

An artifact is atomic and can never be `partially_placed`. For a sale wave, `pending` means
no placement exists and at least one scoped offer/artifact remains actionable; `placed`
means every materialized artifact was placed and no unresolved offer remains;
`partially_placed` means at least one artifact was placed and another scoped offer/artifact
is pending, no-ticket, or expired; `no_ticket` means zero placements and every remaining
family was explicitly closed by no-ticket; and `expired` means zero placements, no pending
family, and at least one family/artifact reached any non-no-ticket sale-terminal state,
including natural close, deadline expiry, or official cancellation. Thus an all-cancelled
scope is `expired`, not an unrepresentable state. This order is exhaustive, and no renderer
may choose an outcome from presentation state.

Incomplete evidence remains `prepare_evidence` with blocked readiness rather than being
mislabelled as a system failure. A malformed imported contract is `blocked` because no
amount of normal operator judgment can repair it.

### 5.4 Deadline and archive behavior

- Each offer expires at its own official deadline. `cancelled` is also sale-terminal. The
  current JCZQ sale wave remains open while another selectable offer or confirmation
  challenge in its scope is open; result waiting is visible in the lane archive rather than
  occupying Today.
- Every approved but unplaced artifact is marked shadow at its effective cutoff. The shadow
  reason distinguishes `confirmation_not_requested` from `deadline_unconfirmed`; a
  confirmation reference is optional for the first case.
- A Telegram callback atomically consumes its challenge, creates the Ticket/placement,
  and writes the stake ledger entry. There is no valid consumed-without-placement state.
- There is no normal phase between confirmation and result waiting. A disagreement among
  challenge, placement, and ledger records is a blocked integrity incident; the browser
  cannot manufacture a placement to repair it.
- Once all offers in a work item are closed/cancelled and all placement outcomes in that scope
  are resolved, that work item leaves Today. The day/issue remains in the lane archive; only
  its current sale wave or a later settlement/review work item returns to Today.
- Completed work items and passive expired-outcome work items never appear at the tail of
  Today and never auto-open; a later explicit review item follows the normal Today priority.
- `not placed` and `no ticket selected` are distinct. The first is an observed artifact
  outcome; the second is an explicit deployment adjudication.

### 5.5 Cross-business-key current resolver

`current` does not mean "latest lexical business key." At the same `as_of`, more than one
business key may be on sale. A task has `task_state = current` exactly when its latest slate
has an upcoming/open offer or open challenge. All other tasks are `archive`; owning an
actionable historical review returns an item to Today but does not relabel that task as
current. Passive result waiting likewise does not make a task current.

Each lane response exposes all current tasks plus one nullable `focus_business_key`. The
resolver chooses the task owning that lane's first task-backed entry under the Today
ordering; a lane-level schedule-recovery entry is ignored because it owns no task. If the
lane has no task-backed Today entry, it chooses the live task with the earliest non-terminal
offer deadline, with business key and task ID as stable ties. If neither exists,
`focus_business_key` is null and the lane root shows a no-current-sale state plus archive
links; it never auto-opens the most recent expired task. A focus selected for an actionable
historical review may therefore name a task in `archive_tasks`, while a recovery-only lane
has null focus. Concurrent issues, tomorrow's presale, and a current day can coexist; an old
review cannot displace an earlier live deadline; and an all-closed lane cannot masquerade as
current. Direct archive/review links remain valid but do not change this resolver.

## 6. Strict evidence gate

### 6.1 Evidence requirement contract

The Application evaluates typed facts against
`operator-evidence-policy-v1`. Each requirement has a stable ID and the following exact
initial rule:

| ID | Requirement | Minimum input | Freshness / validity |
| --- | --- | --- | --- |
| E1 | canonical identity | Match plus both Teams in canonical state; every cross-source alias resolves to them | current entity revisions; no provisional, ambiguous, merged-away, or unresolved state |
| E2 | official schedule and offer | current `OfficialSaleSlateRevision` from an official retrieval | revision validity includes cutoff; fixture, competition, order, markets, kickoff, and deadline present |
| E3 | official market | official Sporttery Snapshot for every offered decision market | observed no more than 6 hours before cutoff |
| E4 | international comparison | deterministic Snapshot from at least one configured international market source with resolved identity | observed no more than 6 hours before cutoff |
| E5 | availability | for both teams, official Observation or Claim corroborated by two credible sources; an explicit sourced `no_known_absence` is valid evidence | observed no more than 24 hours before cutoff and validity includes cutoff |
| E6a | recent form | deterministic recent-form Observation for both teams, backed by versioned authoritative results | generated no more than 72 hours before cutoff |
| E6b | structural context | official Observation or corroborated Claim for both teams covering formation/cohesion/material squad change; an explicitly sourced `no_material_structural_change` Observation is valid | observed no more than 72 hours before cutoff and validity includes cutoff |
| EC | conflict clearance | zero contradictory non-retracted values for every E2-E6 predicate | conflict adjudication/retraction recorded before cutoff |

`allow_explicit_unavailable` is `false` for E1-E6. A provider failure, empty search result,
or old cached payload never satisfies a requirement. `no_known_absence` and
`no_material_structural_change` are not empty results: each is a positive Observation that
the named source set and policy lookback were checked at a recorded time.

Availability and structural Claims carry `valid_from` and `valid_to`. A record whose
interval does not include the task cutoff is stale regardless of insertion time. The
Application never treats absence of a row as evidence that nothing happened.

### 6.2 Whole-task gate

All required matches must be complete:

```text
zucai_ready = complete_matches == 14
jczq_ready  = complete_matches == currently_open_official_offers
```

Any missing, stale, or conflicting item blocks `freeze_evidence_bundle`, market-baseline
creation, Forecast commit, and ticket construction for the task. The page lists each
affected match and requirement. The Application offers refresh/recheck only; collection,
source retrieval, and evidence supplementation are executed through existing CLI or
Telegram workflows.

This strict policy is deliberately stronger than both the current generic product
readiness and RUNBOOK A1's `missing international alias means omit that anchor` behavior.
Approval of this written design authorizes a synchronized RUNBOOK change for the operator
workflow; it does not alter unrelated product APIs. Until the external ingest contract is
implemented and the RUNBOOK change lands in the same verified package, this gate runs only
in shadow and cannot replace the active workflow.

### 6.3 Reachable external evidence ingest

Collection remains outside the Application, but it must have a formal path into the
ontology. Add a strict `EvidenceIntakeManifestV1` with:

```text
EvidenceIntakeManifestV1
  schema_version = "evidence-intake-v1"
  lane, business_key, slate_revision_id, captured_at
  matches: list[MatchEvidenceIntakeV1]

MatchEvidenceIntakeV1
  official_match_no, canonical_match_id
  source_receipts: list[EvidenceSourceReceiptV1]
  observations: list[TypedObservationIntakeV1]
  claims: list[TypedClaimIntakeV1]
  coverage_receipts: list[EvidenceCoverageReceiptV1]

EvidenceSourceReceiptV1
  source_kind, source_run_id, artifact_retrieval_id, captured_at

TypedObservationIntakeV1
  observation_schema, subject_type, canonical_subject_id
  valid_from, valid_to, observed_at, verification_method
  value: RegisteredObservationValueV1
  artifact_retrieval_ids: list[str]

TypedClaimIntakeV1
  claim_schema, subject_type, canonical_subject_id, predicate
  scope_match_id, valid_from, valid_to, extractor, extractor_version
  value: RegisteredClaimValueV1
  spans: list[EvidenceSpanIntakeV1]

EvidenceSpanIntakeV1
  artifact_id, artifact_retrieval_id, quote, locator

EvidenceCoverageReceiptV1
  requirement_id, subject_scope, evidence_ref_tokens: list[str]

RegisteredObservationValueV1 =
  PersonAvailabilityObservationValueV1
  | TeamAvailabilityClearObservationValueV1
  | RecentFormObservationValueV1
  | StructuralContextObservationValueV1

PersonAvailabilityObservationValueV1
  kind = "person_availability_v1"
  team_token, person_token
  availability = expected | available | doubtful | out | suspended | returned
  status_kind = injury | suspension | rotation | selection | coach_status

TeamAvailabilityClearObservationValueV1
  kind = "team_availability_clear_v1"
  team_token, checked_source_kinds: list[str]
  lookback_started_at, lookback_ended_at, finding_count = 0

RecentFormObservationValueV1
  kind = "recent_form_v1"
  team_token, sample_match_tokens: list[str]
  wins, draws, losses, goals_for, goals_against

StructuralContextObservationValueV1
  kind = "structural_context_v1"
  team_token
  context_kind = formation | cohesion | material_squad_change
  state = present | absent, fact_text

RegisteredClaimValueV1 = AvailabilityClaimValueV1 | StructuralContextClaimValueV1

AvailabilityClaimValueV1
  kind = "availability_claim_v1"
  team_token, person_token
  availability, status_kind

StructuralContextClaimValueV1
  kind = "structural_context_claim_v1"
  team_token, context_kind, state, fact_text
```

`RegisteredObservationValueV1` and `RegisteredClaimValueV1` are closed discriminated unions
of checked-in ontology value schemas; the manifest never accepts an arbitrary value mapping.
Unknown schema names, fields, subject types, predicates, verification methods, or requirement
IDs quarantine the complete manifest. A new Claim is always imported as `provisional` by the
authorized extractor path. A manifest may reference an already adjudicated Claim but cannot
declare it verified; verify/dispute/retract remains a separate judge-only Action. Coverage
receipts identify evidence to evaluate and never grant readiness themselves.

The Claim enums reuse the corresponding Observation enums. Counts are non-negative integers;
recent-form totals must equal the distinct authoritative sample references. A
`no_known_absence` fact is represented only by
`TeamAvailabilityClearObservationValueV1`, while `no_material_structural_change` is the
`material_squad_change/absent` structural Observation. No free-form value object or unknown
`kind` reaches ontology storage.

`uv run nutmeg workflow ingest-evidence --manifest <path>` and the matching deterministic
Telegram router action call one service. The service does no research or interpretation.
It validates references, records only typed Actions, reports committed/rejected/skipped
counts, and reconciles those counts against ontology rows. Any skip keeps the named
requirement incomplete. This is the required bridge from external main-loop research to
the strict Application gate.

### 6.4 Evidence freeze

When the final requirement becomes complete, the operator records a judge-only
`request_evidence_freeze` Action. A `deterministic_system` worker validates the request and
executes the existing governed `freeze_evidence_bundle` Action. Each match bundle records its
market prior, eligible Observation/Claim revisions, conflicts cleared, cutoff, freshness,
and policy version. The browser never submits a system role.

New evidence after the freeze does not rewrite the bundle. The task shows
`new_evidence_available`; Jun either keeps the bound version or explicitly creates a new
bundle and reopens affected judgments. A newly stale required market before artifact
approval blocks deployment and requires refresh/review.

## 7. Market baseline and structured judgment

### 7.1 Non-deployable market baseline

After all evidence bundles are frozen, `deterministic_system` Action
`freeze_market_prior_baseline` creates an immutable `MarketPriorBaselineRevision`. It
contains every required match/market probability plus exact Snapshot, EvidenceBundle,
slate, cutoff, policy, arithmetic-version, and content-hash references. It exists before any
human judgment and is the pure market prior for later calibration.

A ticket-shaped comparison additionally requires a judge-owned
`BaselineEnvelopeRevision`:

```text
lane, ticket_kind, capital_cap
per offer: market ids, allowed face bundles, omission allowed/forbidden
exact allowed pass/group templates
maximum ticket count, maximum exhaustive candidate count
```

For Zucai, the official fourteen-match issue supplies the offer set; Jun chooses Renjiu or
SFC, which offers may be omitted for Renjiu, the permissible face bundles, and ticket/group
templates. For JCZQ, Jun supplies participating fixtures, markets, permissible selections,
and pass templates. These are explicit expression constraints: software may not infer which
fixture, market, face, omission, or pass is worth buying.

The server exhaustively enumerates the finite legal space declared by the envelope. It never
uses a heuristic beam, hidden pruning, or model-selected option. If the declared space
exceeds the explicit limit, it rejects the envelope and asks Jun to narrow it rather than
returning a preferred subset. The same deterministic composition functions evaluate each
structure once with the frozen market matrix and once with committed beliefs.

For one ticket, the objective probability is `P(all required legs correct)`. For a
multi-ticket batch it is `P(at least one ticket has all required legs correct)`, computed as
the exact union of ticket events rather than a sum. The resulting market-side ticket shape is
named `ConditionalMarketTicketCounterfactual`: it measures market probabilities under the
same human-supplied envelope, not a pure-market fixture/selection strategy. It must not be
scored or described as evidence that the market itself would have chosen those fixtures.

The prior baseline and conditional counterfactual are preregistered comparison objects, not
Forecasts, prescriptions, approved Tickets, or recommendations. They are visually labelled
`comparison only`; validators reject their object kind at candidate selection, TicketBatch,
approval, and protected confirmation boundaries.

### 7.2 Judgment entry

Application is the primary editing surface. For every match, it presents:

- identity, competition, kickoff, and sale deadline;
- market prior and movement in percentage points;
- the E1-E6b requirement checks, EC conflict-clearance state, source status, and freshness;
- existing Factor, Flag, Precedent, and named Rule references;
- probability distribution for the selected market;
- prior-to-belief deltas and typed evidence anchors;
- the selected expression faces/markets;
- an explicit falsifier and concise rationale.

An AI AgentProposal may be displayed as a draft if an external main-loop workflow already
stored it with citations. The Application does not invoke autonomous research. Jun edits or
approves the draft, and only a `judge_operator` Action commits the ForecastRevision/Read.
AI output never self-promotes to committed judgment.

Every committed judgment obeys these invariants at stored, not display, precision:

- its prior equals the exact row in the bound `MarketPriorBaselineRevision`;
- a zero-delta belief may have zero Factors and is a valid human judgment;
- any non-zero face delta requires at least one named Factor with typed evidence references;
- deterministic factor offsets must reconstruct every belief value from the prior exactly,
  including normalization and zero-sum checks; an empty Factor list plus non-zero delta is
  rejected;
- expression faces and allowed face bundles are explicit judge input, never inferred from
  confidence, entropy, market rank, or a factor label.

Progress is counted from current committed revisions, not browser submissions, service
return values, rx prose, or generated reports. All required matches must have a current
committed judgment bound to the frozen evidence cutoff before a judge-owned
`JudgmentPrescriptionRevision` can freeze their Forecast references, expression choices,
named Rules, and evidence anchors. Ticket comparison unlocks only for that frozen revision.

### 7.3 Persistent decision lineage

The implementation adds the following revisioned objects and Actions. Common revision fields
are stable object ID, family ID, revision number, superseded revision, work-item/task snapshot,
slate revision, content hash, created-at, and created-by Action. Request idempotency and
expected versions are mandatory.

| Object | Required lineage/content | Creating Action and role |
| --- | --- | --- |
| `MarketPriorBaselineRevision` | EvidenceBundle refs, Snapshot refs, cutoff, prior matrix, policy/arithmetic versions | `freeze_market_prior_baseline`, deterministic_system after the governed evidence freeze |
| `BaselineEnvelopeRevision` | scoped offer refs, capital cap, ticket kind, offer/market/face/omission options, exact templates and enumeration limit | `record_baseline_envelope`, judge_operator |
| `JudgmentPrescriptionRevision` | current ForecastRevision refs, expression bundles, Rule IDs, evidence anchors and falsifiers | `freeze_judgment_prescription`, judge_operator |
| `TicketCandidateSetRevision` | baseline, envelope and prescription refs; generator version; every enumerated candidate, metric and audit result | `generate_ticket_candidate_set`, deterministic_system |
| `TicketCandidateSelection` | one judgment-bound candidate ref, candidate-set revision, reason and expected task snapshot | `select_ticket_candidate`, judge_operator |
| `NoTicketAdjudicationRevision` | exact work-item/task snapshot, scoped offer/artifact refs, and phase-dependent counterfactual refs in section 8.4 | `record_no_ticket`, judge_operator |
| `TicketDecisionLineage` | TicketBatchRevision -> work item, task, slate, bundles, baseline, envelope, prescription, candidate set and selection | written atomically by the existing human `create_ticket_batch` Action |

Superseding any input does not rewrite descendants. It makes dependent envelope,
prescription, candidate, selection, audit, and form tokens non-current until explicitly
rebuilt. `TicketDecisionLineage` is required before a batch can be audited. A zero-delta
judgment candidate remains distinct from the market counterfactual because it references the
human Forecast and prescription revisions; equal probabilities or faces never collapse
their object kinds or provenance.

## 8. Ticket construction and deployment

### 8.1 Candidate generation

The browser performs no pricing, probability, combinatorial, or settlement arithmetic.
Lane-specific deterministic services generate a `TicketCandidateSetRevision` from the
frozen prescription and exact envelope. They enumerate all legal combinations of the
operator-declared face bundles, omission permissions, and structure templates; they neither
invent an option nor silently prune the result.

Zucai SFC candidates express all fourteen issue matches; each Renjiu ticket declares its
exact nine-match group and any multi-ticket group supplied by the envelope. JCZQ requires
Jun's finite fixture, market, selection, and pass options from the evidence-complete and
judged slate. The service may combine those options and calculate their coverage, but does
not decide which new fixture or market is worth betting.

Candidate storage already contains the complete deterministic placement/settlement input:
ticket kind, structure/group, currency, integer unit stake and multiplicity, total stake,
canonical composition, and every ordered leg's offer/match/market/selection. JCZQ legs bind
the exact Quote, positive booked Decimal odds, and signed HHAD line when required. Zucai legs
forbid those odds fields and bind one registered fixed-prize policy revision shared by the
candidate. Initial SFC/Renjiu policy revisions therefore exist before candidate generation,
not only when an artifact or settlement is later created.

Before ordering, every generated candidate runs the same current leg audit,
prescription-difference audit, cap check, and lane deployment arithmetic. The candidate set
retains all results in three visible partitions: eligible, audit-blocked, and over-cap. No
candidate is hidden because it scored poorly or failed an audit.

Every candidate row shows:

- singles, doubles, full covers, omitted matches, and pass groups;
- ticket count, price, and funding-cap usage;
- the exact objective probability, labelled `P(all correct)` for one ticket or
  `P(at least one ticket all correct)` for a batch, and expected broken legs;
- shared dead faces across multiple tickets;
- every difference from the committed prescription with named Rule IDs;
- its exact difference from the frozen market baseline.

An eligible candidate is within cap, judgment-bound, and has no unadjudicated audit ERROR.
Every leg references a committed current Forecast. It remains judgment-bound when all
probability deltas are zero; the human did not have to disagree with the market. The prior
baseline and conditional market counterfactual remain non-deployable even when their content
is identical to a judgment-bound candidate.

### 8.2 Policy objective resolution

The checked-in lower documents currently contradict CONSTITUTION: section 2 requires
maximizing `P(all correct)` within an external cap and excludes EV from the decision layer,
while current Zucai RULEBOOK/RUNBOOK text ranks fixed-prize Renjiu sizes by break-even line.
This is an implementation migration precondition, not a runtime operator choice.

CONSTITUTION explicitly governs lower-document conflicts, so this rebuild does not leave
two executable objectives. It applies the constitutional order:

1. exhaustively generate and audit the operator-declared finite space;
2. exclude over-cap and unadjudicated-ERROR rows from the eligible ordering without hiding
   them from the comparison;
3. order eligible rows by the exact objective probability defined above, descending;
4. break equal-P ties by lower stake and then canonical content hash;
5. never label the first row `recommended` or select/approve it automatically.

New probability services use decimal arithmetic with precision 50. Stored input
probabilities and objective results are canonical decimal strings quantized to 12 decimal
places with round-half-even; display rounding never participates in ordering. Equality for
the P tie-break means equality at that stored 12-place scale. Candidate hashes cover the
unrounded canonical inputs, generator version, envelope, and composition.

Break-even and official median-bonus multiples remain visible report-only analytics. They
do not rank, block, reduce, or recommend no-ticket. The package that activates this behavior
must update the contradictory RUNBOOK and RULEBOOK lines in the same commit while leaving
CONSTITUTION unchanged. Until those documents and the CLI share this policy, the new ticket
surface remains in shadow mode.

### 8.3 Audit and explicit adjudication

Only a judgment-bound candidate may be selected. An over-cap candidate cannot be
materialized. A selected audit-blocked candidate may be materialized as a draft solely so
Jun can exercise the existing external adjudication path; the Application keeps approval
blocked. `create_ticket_batch` atomically writes its full `TicketDecisionLineage`, then reruns
the current authoritative leg audit, prescription-difference audit, budget check, and lane
deployment report against current input revisions.

The browser never supplies an artifact deadline. At `approve_ticket_batch`, the server
resolves every offer through the selected candidate and frozen lineage, requires each offer
still to be open in the bound current slate revision, computes the minimum
`sale_deadline_at`, and freezes that value into the protected artifact. A stale token,
superseded slate, closed/cancelled offer, or approval time at/after that minimum rejects the
Action; no client field can extend the window.

- Audit ERROR blocks Application approval. There is no Web override control and the Web
  server never shells out. The existing external `--user-override` flow is refactored onto
  one `record_ticket_audit_override` domain Action available only to `judge_operator`. It
  records `evidence_rejected` for every ERROR against the exact batch revision, candidate
  content hash, finding ID, and audit-policy version. Protected approval may proceed only
  when every current ERROR has such a committed receipt and a fresh audit produces the same
  bindings; the artifact preserves both original findings and override Action IDs.
- WARN requires the existing typed Adjudication where the policy demands one.
- Every prescription deviation requires a named Rule ID.
- A change after audit creates a new revision and invalidates the prior audited artifact.
- If an override changes candidate eligibility, the judge Action appends a candidate-
  generation request referencing the override receipts. The deterministic worker alone
  creates a new `TicketCandidateSetRevision`; neither step edits the old ranking or
  suppresses the original ERROR.

### 8.4 No-ticket adjudication

No-ticket is always available to Jun for the still-unplaced scope of a current sale-wave or
artifact work item after official task discovery, as required by CONSTITUTION. It is visually
secondary and never preselected. It uses the dedicated `record_no_ticket` Action; a generic
Adjudication payload cannot substitute for it. The judge-only command includes an idempotency
key, expected task/work-item snapshot token, reason code, reason text, optional Rule IDs, and
the exact current slate revision. The server derives and stores the immutable scope as every
remaining upcoming/open offer and every approved-but-unplaced artifact in that sale-wave
snapshot; the browser cannot omit a pending artifact or add a closed/foreign one.

The closed initial reason codes are `human_all_dice`, `evidence_incomplete`,
`no_compliant_structure_within_cap`, `discipline_brake`, and `operator_discretion`. Software
does not choose or infer a code or decide which code is Rule-derived. Jun submits the separate
closed `reason_basis = rule_derived | operator_judgment`; `rule_derived` requires at least one
current Rule ID, while `operator_judgment` does not require a fabricated Rule reference.
`operator_discretion` preserves the constitutional right to no-ticket without fabricating a
football rule.

- Before evidence completion, the adjudication preserves all missing/stale/conflicting
  requirement IDs and snapshot hash and records that no valid ticket counterfactual existed.
- After baseline creation, it preserves the exact baseline revision.
- After an envelope exists, it also preserves the envelope and any conditional market
  counterfactual.
- After candidate creation, it preserves the candidate-set revision and the human-designated
  comparison candidate, if any.

Evidence absence, a single WARN, low confidence text, or a failed external collection run
must never automatically create or recommend no-ticket. The UI may report entropy and
conflicts as arithmetic/facts, but the interpretation `all dice` remains human judgment.
An explicit no-ticket adjudication closes only its unplaced scope. In a zero-placement scope,
its deployment outcome is `no_ticket`. If another artifact in the work item was already
placed, the work-item outcome remains `partially_placed`; the adjudication records how the
remaining artifacts were closed and never relabels or reverses the placed Ticket/ledger.
No-ticket against approved but unplaced artifacts atomically invalidates their unconsumed
challenges and records `human_no_ticket` shadow outcomes with no stake. A concurrent consumed
challenge makes the expected snapshot stale and rejects the no-ticket Action.

`record_no_ticket` and `supersede_no_ticket` use the server transaction's receipt time, not
a browser timestamp. Before either Action evaluates its requested transition, the
transaction recomputes every scoped offer state and artifact `effective_cutoff` against the
current slate. A bare offer's effective cutoff is its current `sale_deadline_at`; an
artifact uses the stricter formula in section 5.2. The transaction first commits any
already-due expiry/shadow terminal transitions under the same CAS rules. No-ticket may
close, and supersession may reopen, only an offer/artifact for
which that receipt time is strictly earlier than its effective cutoff and whose offer state
is upcoming/open. Equality or lateness belongs to expiry/shadow even when the periodic
scanner has not run. If this terminalization changes the submitted scope, the command returns
`task_snapshot_changed` plus the existing terminal receipts; it cannot relabel the expired
part as `human_no_ticket` in the same request. A refreshed command may adjudicate only the
remaining non-terminal scope.

The resolved work item moves to result/review so its available baseline counterfactual is
still graded. While at least one scoped offer is upcoming or open, Jun may reopen only through
a new judge-only `supersede_no_ticket` Action with the expected adjudication revision; the new
sale-wave snapshot excludes closed/cancelled offers and never resurrects an invalidated
artifact. A slate/evidence change never reopens it implicitly. The resolver returns an
explicitly reopened work item to Today at the earliest phase its still-current artifacts
satisfy; it never restores a closed offer or a prior confirmation window. An early no-ticket
with no baseline receives only operational and data-availability review. The system never
constructs a hindsight probability or ticket counterfactual after results arrive.

A zero-placement scope has task settlement state `not_applicable`, but that state never
suppresses review. Any zero-placement scope without a baseline creates an operational/data-
availability review item as soon as its deployment scope becomes terminal, whether by early
no-ticket, natural deadline expiry, or official cancellation. A no-ticket or expiry with a
frozen baseline waits for the required Outcomes and then creates the forecast-truth review
item even though money settlement remains `not_applicable`.

Before the review schema is installed, these transitions persist a normalized review-
eligibility fact containing the trigger, task/work-item snapshot, optional baseline, review
kind, and `immediate | outcomes_required` readiness condition. The later deterministic review
worker alone executes `materialize_operator_review_item` as `deterministic_system` to derive
an actionable review item from that fact. Its idempotency key is the eligibility-fact ID plus
the exact satisfied Outcome revision set. Deployment and settlement Actions never write a
future review row directly, and no GET may materialize one.

## 9. Confirmation, ledger, settlement, and review

### 9.1 Protected confirmation

Approval creates immutable audited ticket artifacts bound to ticket hash, amount, channel,
deadline, and source versions. The primary Application action opens the first protected
confirmation stage and sends the compact ticket summary to Telegram.

Only the configured owner may consume the Telegram callback and invoke the protected
placement Action. No AI actor, scheduler, Web session, entropy threshold, or rule trigger
receives that authority.

Each audited artifact has its own challenge and callback. A multi-ticket batch may therefore
be `partially_placed`: confirmed artifacts enter the ledger atomically, while other
artifacts remain open or become shadow independently.

Each challenge is an immutable revision identified by `challenge_revision_id` and grouped by
a stable `challenge_family_id`. It is bound to artifact hash, lineage, effective cutoff, and
nonce hash. A migrated legacy `confirmation_id` is retained only as nullable audit data; new
API and terminal links use `challenge_revision_id`. A per-artifact current-head relation
enforces at most one open challenge while preserving predecessor revisions. Each challenge has one expected revision and exactly one
terminal receipt, enforced by a unique challenge reference. The callback may transition `open -> placed` only when its
server-recorded ingress time is strictly earlier than the effective cutoff. The scanner may
transition `open -> shadow` only when `effective_cutoff <= as_of`; equality belongs to expiry.
Callback, scanner, official-slate correction, and human no-ticket all use the same CAS in
their atomic Action transaction. The winner writes the sole terminal receipt; an idempotent
replay returns it, while a competing different transition reports the existing terminal
state and creates no Ticket, shadow duplicate, or cash row.

Every artifact terminal receipt stores `terminal_kind = placed | shadow` separately from its
closed `terminal_reason`. `actual_placement_confirmed` is valid only for `placed`;
`confirmation_not_requested`, `deadline_unconfirmed`, `human_no_ticket`,
`official_deadline_shortened`, and `official_offer_cancelled` are valid only for `shadow`.
An approved artifact can terminalize without ever having a challenge, so artifact identity is
the required CAS key and `challenge_revision_id` on the receipt is nullable. Migration 22
creates the challenge revision/head tables before the terminal-receipt table, so SQLite can
enforce the nullable restricted foreign key from its first write. Migration 23 migrates legacy
challenges into those tables and activates the confirmation/note workflow without renaming
the receipt key or introducing a competing challenge model.

### 9.2 Telegram ownership and Application infrastructure workers

Telegram updates have exactly one consumer per bot token. Production keeps OpenClaw as
`telegram_update_owner`; `nutmeg app` must not start a native poller for that token. The
repository ships a native OpenClaw plugin for that owner. In full registration mode it calls
`api.registerInteractiveHandler({channel: "telegram", namespace: "ntc", handler})`; changing
only the Python command router is not an integration. The handler captures its process clock
at entry, then requires `accountId == "nutmeg"`, `auth.isAuthorizedSender`, and configured
chat and sender allowlists. It serializes only the closed normalized callback fields to a
fixed local Nutmeg bridge over stdin. It never places data on argv, invokes a shell, returns
`submitText`, or allows an `ntc:` callback to enter the AI path. Success, safe rejection, and
bridge failure all return `{handled: true}` after a bounded user-facing response.

The plugin also uses `api.registerService` to maintain one operational owner-lease row per
configured owner instance while its full runtime is alive. Startup records the immutable
owner/configuration registration through `register_telegram_update_owner` as
`deterministic_system`, idempotent on account, owner instance, transport, and router version.
The first pulse and every 30-second pulse thereafter update only that registration's
server-observed heartbeat sequence/time and 90-second lease expiry. A pulse is not a new
typed Action or business-domain revision, so it cannot advance the Action high-water mark or
stale the scoreboard projection; no per-pulse history is accumulated or pruned. The row
binds `accountId="nutmeg"`, owner instance, transport label, plugin/router version, and the
registration Action and contains no token or nonce. Actual callback attestations and terminal
placement remain typed Actions. Actual channel connectivity is
reported separately from the read-only result of
`openclaw channels status --channel telegram --json`, selecting the `nutmeg` account. The
legacy `telegram-bot.offset` file remains an update cursor and its mtime is never treated as
health evidence. Plugin installation, enablement, and the production OpenClaw restart remain
an explicit Jun activation gate; build and isolated verification do not change OpenClaw
configuration.

`nutmeg app` is the sole owner of every transport-independent queue consumer. In active mode
one `OperatorInfrastructureWorkers` supervisor starts the consumers in this fixed order:

1. evidence-freeze requests (`request_evidence_freeze` -> existing
   `freeze_evidence_bundle` plus `link_operator_task_evidence_freeze`);
2. market-baseline derivation (`freeze_market_prior_baseline`);
3. candidate-generation requests (`generate_ticket_candidate_set`);
4. confirmation-deadline scanning (`mark_ticket_shadow` through the shared artifact CAS);
5. settlement requests (`settle_task`);
6. review-eligibility materialization (`materialize_operator_review_item`);
7. scoreboard-review completion requests (`complete_scoreboard_review`);
8. product outbox/SSE delivery and read-model invalidation.

Every named completion is a `deterministic_system` Action; request Actions remain
`judge_operator`. The only exceptions are the read-model invalidator and delivery cursor,
which are projections of committed outbox data and cannot change business state. Startup
finishes recovery of expired queue leases before accepting HTTP traffic. Shutdown stops new
claims in reverse order, lets the current bounded transaction finish, then releases the
writer and Application leases.

Judge request and objective eligibility rows stay immutable. A separate operational
`operator_worker_jobs` table has one unique row per
`(job_kind, source_object_type, source_object_id)` and uses the closed state machine
`queued -> leased -> completed | failed`, with `lease_owner`, `lease_expires_at`,
`attempt_count`, `available_at`, `last_error_code`, and the resulting Action/receipt
reference. The request/fact Action inserts its job atomically. A process death returns an
expired lease to `queued`; idempotency keys make replay converge on the original result.
Retryable SQLite contention and process interruption use bounded exponential backoff;
invalid input, permission failure, stale dependencies, and invariant failure become visible
terminal `failed` jobs and are never silently retried. Derived baseline/review work uses the
same job contract even when its immutable source is a completed fact rather than a judge
request. Queue lease updates are operational state, not football or business revisions; the
job's successful business result is always the named typed Action.

Production `legacy_read_only` and `shadow` modes start only deadline scanning, outbox delivery,
and read-model invalidation. They do not claim decision/result/review requests; queued work
remains durable until active mode returns. The deadline scanner remains enabled so rollback
cannot abandon an already approved artifact. Isolated active mode starts the full supervisor
against its isolated root and simulated transport. Telegram update consumption and owner
heartbeats remain OpenClaw-owned and are not Application workers.

A native Nutmeg poller is legal only with an explicitly different bot token or after Jun
changes ownership and disables the OpenClaw consumer. The Application never performs that
ownership change itself.

It does not run official match collection, research, judgment, candidate selection,
placement, or betting. If Telegram is not configured or its owner heartbeat is stale, the
Application remains usable but blocks confirmation with the concrete transport state.

### 9.3 Placement and ledger

The owner button means `actual placement confirmed`. Its callback builds a Telegram
attestation receipt and atomically consumes the challenge, creates the formal Ticket and
placement, and writes the stake ledger entry through one extension of the existing protected
Action. If any part fails, none of those records commits and the challenge remains retryable
until expiry.

The protected artifact contains canonical note composition, not only a face summary. The
callback materializes immutable `TicketNote` rows and `TicketNoteLeg` links with note index,
structure/group, selection refs, and integer stake minor units. Their composition hash must
equal the audited artifact hash, and the sum of note stakes must equal both Ticket total and
the stake transaction. JCZQ note legs require the booked Quote and decimal odds. Zucai
SFC/Renjiu note legs bind official match/selection refs and the fixed-prize policy; they must
not fabricate entry odds to fit the JCZQ model.

The approved artifact also has a normalized binding row for the exact
`candidate_ticket_id` (not merely its possibly multi-ticket candidate revision), ticket
index/kind, integer total stake, currency, candidate/composition hash, lineage revision,
frozen deadline, and nullable fixed-prize policy, plus ordered child links to every official
offer revision. The candidate-ticket foreign key and a uniqueness constraint make one
artifact resolve to exactly one candidate ticket. Its signed JSON document may duplicate
those facts as an audit receipt, but normal queries, foreign-key checks, placement, and
settlement never depend on parsing that JSON.

The storage contract is explicit:

```text
TicketNote
  ticket_note_id, ticket_id, protected_artifact_id, note_index
  ticket_kind, structure_code, group_code, currency
  unit_stake_minor, unit_count, stake_minor, composition_hash
  fixed_prize_policy_revision_id

TicketNoteLeg
  ticket_note_leg_id, ticket_note_id, leg_index
  official_offer_revision_id, match_id, market_definition_id, selection_code
  quote_id, booked_decimal_odds, settlement_parameter_decimal
  fixed_prize_policy_revision_id

PlacementCashLink
  ticket_id, transaction_id, stake_minor, currency

ZucaiFixedPrizePolicyRevision
  fixed_prize_policy_revision_id, policy_version, ticket_kind, currency
  standard_unit_stake_minor, allowed_tier_codes, official_void_rule
  effective_at, content_hash, created_by_action_id
```

`note_index` and `leg_index` are unique within their parents. `group_code` is nullable only
when the ticket kind has no group. A JCZQ Ticket, note, and leg require null
`fixed_prize_policy_revision_id`; each leg requires `quote_id` and positive
`booked_decimal_odds`. A market definition such as HHAD that requires a settlement parameter
also requires its signed line in `settlement_parameter_decimal`. A Zucai protected artifact
and resulting Ticket bind exactly one non-null fixed-prize policy revision. Every note and
leg copies that same revision and forbids quote/odds/parameter fields; mixed revisions in one
Ticket are an integrity error. Odds, lines, and later arithmetic inputs are canonical decimal
strings, never binary floats. Currency is fixed across the Ticket, its notes, stake
transaction, and later payout transactions.

`PlacementCashLink.stake_minor` is the integer-money placement authority and reconciles to
the Ticket/artifact/note sum. The linked legacy `CashTransaction.amount` remains a
compatibility projection and is never converted back into minor units for audit or
settlement arithmetic.

`unit_count` is a positive integer and `stake_minor == unit_stake_minor * unit_count`. One
`TicketNote` represents one unique canonical selection composition; repeated identical notes
are combined through `unit_count`, not duplicated rows. The initial Zucai policies are
versioned deterministic records for `sfc` and `renjiu`, both CNY with
`standard_unit_stake_minor = 200`; their allowed tiers and official-void behavior match the
closed rules below. Zucai requires the policy stake as `unit_stake_minor`. JCZQ also records
its official unit stake and multiplier explicitly, so booked-odds payout never infers a
multiplier from aggregate Ticket money.

At artifact creation and placement, the bound Zucai policy's `ticket_kind` must equal the
artifact, Ticket, and every note; its currency must equal the artifact, Ticket, notes, and
stake currency; every note's `unit_stake_minor` must equal `standard_unit_stake_minor`; and
its `allowed_tier_codes` must equal the checked-in closed tier set for that ticket kind.
These sale-time checks do not require a future prize table. At settlement, the prize table
must additionally exist, its issue/currency/ticket-kind/exact tier-code set must match the
Ticket and bound policy, and payout currency must match them. Any mismatch blocks before
writing the corresponding Ticket or settlement.

Checked-in policy content is registered by a versioned
`register_zucai_fixed_prize_policy` `deterministic_system` Action. A content change appends a
revision; it never edits the policy bound to an audited artifact. There is no browser policy
mutation command.

The old Web form and API path that accept nonce, external reference, and receipt to perform
final placement are removed from the active product. The domain service remains callable by
the sole Telegram callback owner and dedicated tests. Browser attempts return 405.

`No ledger = not placed` remains authoritative. An approved artifact that never receives a
challenge and an issued-but-unconfirmed artifact both create shadow records at the artifact
effective cutoff and no stake transaction.

### 9.4 Settlement and review

Authoritative results are imported externally through `import_result_evidence_set` into a
versioned `ResultEvidenceSetRevision`. Each revision binds the task/slate revision, source
retrievals, normalized values, importer version, content hash, and any superseded result set.
`uv run nutmeg workflow ingest-results --manifest <path>` accepts only the following strict
manifest. It does no result research and cannot create a source artifact from an unsourced
score.

```text
ResultEvidenceManifestV1
  schema_version = "result-evidence-v1"
  lane, business_key, task_snapshot_token, slate_revision_token
  result_cutoff_at, supersedes_result_set_token
  matches: list[MatchResultEvidenceManifestV1]
  zucai_prize_table: ZucaiPrizeTableManifestV1 | null

MatchResultEvidenceManifestV1
  official_match_no, canonical_match_id
  sources: list[ResultSourceManifestV1]

ResultSourceManifestV1
  source_kind, receipt_state, artifact_retrieval_id, captured_at
  source_disposition, home_90, away_90, invalid_code

ZucaiPrizeTableManifestV1
  issue, currency, published_at, official_artifact_retrieval_id
  supersedes_prize_table_token
  tiers: list[ZucaiPrizeTierManifestV1]

ZucaiPrizeTierManifestV1
  tier_code, ticket_kind, required_correct_count
  official_winning_note_count, payout_minor_per_winning_note
```

The manifest has exactly one source row for each configured source kind and rejects unknown
or duplicate fields/rows. A `missing` source has null retrieval, capture, disposition, score,
and invalid code. An `invalid` source retains its retrieval/capture refs, requires a closed
`invalid_code`, and has null normalized disposition/scores. An `available` source requires
the retrieval/capture/disposition fields and the score rules below. Only Zucai accepts a
prize table; for Zucai it is required before settlement, while JCZQ requires null.

```text
ResultEvidenceSetRevision
  result_set_revision_id, family_id, revision_no, supersedes_revision_id
  lane, business_key, task_snapshot_hash, slate_revision_id
  result_cutoff_at, importer_version, content_hash, created_by_action_id
  match_results: list[MatchResultEvidenceRevision]
  zucai_prize_table_revision_id

MatchResultEvidenceRevision
  match_result_revision_id, result_set_revision_id, official_offer_revision_id, match_id
  normalized_disposition, normalized_home_90, normalized_away_90, agreement_state
  source_receipts: list[ResultSourceReceipt]

ResultSourceReceipt
  source_kind, source_artifact_retrieval_id, captured_at
  source_disposition, home_90, away_90, receipt_state, invalid_code

OutcomeRevision
  outcome_revision_id, family_id, revision_no, supersedes_revision_id
  match_id, match_result_revision_id, result_set_revision_id
  result_disposition, home_90, away_90
  source_artifact_retrieval_ids, recorded_at, created_by_action_id
```

When present, `normalized_disposition` and `source_disposition` are exactly `played_90`,
`postponed`, or `official_void`. A missing receipt has null retrieval, capture, disposition,
score, and invalid-code fields; missing/conflicting normalization has null normalized
disposition and scores. An invalid receipt retains its available audit references, requires
one of `artifact_unreadable | schema_mismatch | invalid_score | source_identity_mismatch | unsupported_status`,
and has null disposition/scores. Scores are required non-negative
integers only for `played_90` and otherwise must be null. `agreement_state` is
`missing | conflict | agreed`; only an agreed `played_90` or `official_void` creates a new
`OutcomeRevision`. An agreed `postponed` match stays waiting without an Outcome. Each Outcome
binds exactly one normalized match-result revision, so a result-set correction supersedes
rather than rewrites it. Outcome stores facts only; each grader derives its market result
code from the score/disposition, market definition, and persisted settlement parameter. For
Zucai, `zucai_prize_table_revision_id` may be null until official prizes are published but is
a hard settlement requirement; it is always null for JCZQ.

JCZQ CRS uses three distinct official aggregate selection codes: `win_other`, `draw_other`,
and `loss_other`. A grader returns a registered exact-score code when present and otherwise
the aggregate matching the home/draw/away direction. The legacy generic `other` selection is
retained only for historical audit and is non-deployable; candidate audit and settlement
block it rather than guessing a direction.

For each required match it contains:

1. API-Football `score.fulltime` (90-minute result even when status is AET/PEN);
2. official Sporttery/gameNo=90 result and, for Zucai, official prize data;
3. an okooo result captured manually as a source artifact, with no WAF bypass.

The official result is mandatory, and all three normalized 90-minute results must agree.
Missing sources keep the affected matches waiting; disagreement creates
`result_source_conflict` and blocks their Outcomes and dependent settlements. A result-set
correction creates new Outcome revisions and preserves all superseded evidence.

For a normally completed match, agreement means the same integer `home_90/away_90`. A
postponed match remains waiting. A cancelled/abandoned match may become `official_void` only
when the official settlement artifact declares it void and the other two sources corroborate
the non-completion status; no score is invented. Result DTOs distinguish `played_90`,
`postponed`, and `official_void`.

For Zucai the same revision also contains an official
`ZucaiPrizeTableRevision` sourced from gameNo=90:

```text
ZucaiPrizeTableRevision
  prize_table_revision_id, family_id, revision_no, supersedes_revision_id
  issue, currency, published_at, source_artifact_retrieval_id
  content_hash, created_by_action_id
  tiers: list[ZucaiPrizeTier]

ZucaiPrizeTier
  prize_table_revision_id, tier_code, ticket_kind, required_correct_count
  official_winning_note_count, payout_minor_per_winning_note
```

The closed tiers are `sfc_first` (`sfc`, 14), `sfc_second` (`sfc`, 13), and
`renjiu_first` (`renjiu`, 9); the table requires exactly one of each. Tier matching is exact,
not greater-than-or-equal: an SFC note with 14 correct receives only `sfc_first`, one with 13
receives only `sfc_second`, and every other count receives no tier; a Renjiu note with exactly
9 correct receives only `renjiu_first`, and every other count receives no tier. The importer
rejects an issue mismatch, wrong ticket-kind/count pairing, duplicate/missing tier,
non-integer amount, negative winning-note count, negative
`payout_minor_per_winning_note`, or a prize artifact that is not linked to the official
retrieval.
Prize-table values are not inferred from odds, pool estimates, or historical medians.
The `sfc` policy allows exactly `sfc_first/sfc_second`; the `renjiu` policy allows exactly
`renjiu_first`. Their `all_faces_match` official-void rule counts a void leg as correct for
each fixed-prize note rather than converting the whole note to a JCZQ-style refund.

When the required result evidence exists, the Application may record a judge-only
`request_settlement` Action referencing the exact result-set revision and task snapshot. A
`deterministic_system` `TaskSettlementService` consumes it. This is a deliberate generalization,
not a call to the current single-match HAD-only service:

- every Ticket must retain the exact note composition and stake per note from its audited
  artifact; note totals and placement stake must reconcile before settlement;
- each leg is graded against the current Outcome for that leg's own Match and the market
  definition's declared settlement scope;
- JCZQ supports every market exposed for construction (`had`, `hhad`, `ttg`, and `crs`) with
  one versioned grader per market definition. Any lost leg makes the note `lost` with zero
  payout. With no loss and at least one winning leg, the note is `won`; payout uses its booked
  odds, settlement parameters, and stake, with void legs contributing 1.0 under the named
  official rounding policy. If every leg is void, the note is `void` and its payout/refund is
  exactly its persisted `stake_minor`;
- SFC expands each immutable note across its fourteen bound offer legs and grades 14/13
  correct by the mutually exclusive exact-match tier rule above. Renjiu grades only the exact
  nine offer legs bound to that note against `renjiu_first`; the fourteen-match result set is
  its source universe, not fourteen legs in a Renjiu note. A winning note pays
  `unit_count * payout_minor_per_winning_note`;
- an offered market or ticket kind without a registered grader is blocked at candidate audit
  with `unsupported_settlement_market`; it is never silently voided;
- one atomic `settle_task` Action writes a task-run receipt plus zero or more Ticket settlement
  revisions, their leg/note grades, payout totals, and cash-ledger entries. An internal count
  mismatch rolls back the whole run.

The resulting storage objects are likewise closed:

```text
TaskSettlementRunReceipt
  settlement_run_id, request_action_id, settle_action_id
  task_id, work_item_snapshot_hash, result_set_revision_id
  prize_table_revision_id, settlement_method_version
  rounding_policy_version, fixed_prize_policy_revision_ids
  requested_ticket_count, eligible_ticket_count, settled_ticket_count
  skipped_ticket_count, persisted_settlement_count
  persisted_note_grade_count, persisted_leg_grade_count, persisted_cash_count
  ticket_settlement_revision_ids, skips: list[TaskSettlementSkip]
  completed_at

TaskSettlementSkip
  ticket_id, reason_code

TicketSettlementRevision
  settlement_revision_id, family_id, revision_no, supersedes_revision_id
  settlement_run_id, ticket_id, result_set_revision_id, prize_table_revision_id
  fixed_prize_policy_revision_id
  method_version, rounding_policy_version, settlement_state, currency
  distinct_note_count, paid_note_unit_count
  winning_note_unit_count, void_note_unit_count
  gross_payout_minor, created_by_action_id

TicketNoteSettlement
  settlement_revision_id, ticket_note_id, note_grade
  unit_count, winning_unit_count, void_unit_count
  correct_leg_count, void_leg_count
  prize_tier_code, payout_minor

TicketNoteLegSettlement
  settlement_revision_id, ticket_note_leg_id, outcome_revision_id
  result_disposition, market_result_code, leg_grade

SettlementCashLink
  settlement_revision_id, transaction_id, transaction_kind
  reverses_transaction_id, amount_minor, currency
```

`settlement_state` is `settled | corrected`; a blocked or waiting request creates no
settlement revision. `note_grade` is `won | lost | void`; `leg_grade` is
`won | lost | void`. For JCZQ, any lost leg maps to `lost`; otherwise at least one winning
leg maps to `won`; otherwise all legs are void and map to `void`. For Zucai, exact tier match
maps to `won` and every other count maps to `lost`; policy-matched void legs increment
`void_leg_count` but never make the fixed-prize note itself `void`. `paid_note_unit_count` is
the sum of all persisted note `unit_count` values regardless of outcome;
`winning_note_unit_count` sums `unit_count` only for `won` notes; and
`void_note_unit_count` sums it only for JCZQ `void` notes. These counters are disjoint except
that winning and void counts are both subsets of paid count. A note copies those rules into
`winning_unit_count` and `void_unit_count`: respectively `unit_count/0` for won, `0/unit_count`
for JCZQ void, and `0/0` for lost. Zucai always has `void_unit_count = 0`. Run skips use the
closed codes `already_current | result_not_ready | prize_not_ready | placement_integrity_blocked`;
a persisted unsupported market is an integrity failure rather
than a silent skip. The receipt counts the exact scoped placed Tickets, and
`requested = eligible + skipped`, `eligible = settled`, and every persisted child count must
match the rows committed by the same Action.

A correction revision directly supersedes only the current effective settlement. It appends
a `payout_reversal` for that predecessor's still-effective positive payout and, when the new
amount is positive, one replacement `payout`. A unique non-null
`reverses_transaction_id` permits each positive payout to be reversed at most once and is
required only on `payout_reversal`; payout rows require it null. The four transitions are
therefore positive->zero (reversal only), zero->positive (new payout only),
positive->positive (reversal plus new payout), and zero->zero (no cash rows). A second or later
correction reverses only the direct predecessor's replacement payout, never an already
reversed historical payout. Cash amounts retain the existing signed-ledger invariant: stake
and payout reversal are negative, payout is positive, and balance is their sum. Every
reversal amount is exactly the negative of its referenced positive payout.

JCZQ graders parse booked odds and settlement parameters as `Decimal` with context precision
50. `cn_sporttery_jczq_v1` multiplies the note stake by every winning non-void booked odd,
uses `1` for void legs, rounds half-up once at note payout to integer minor units, and then
sums note payouts. `rounding_policy_version` is part of settlement identity. Zucai performs
integer unit-count times official integer per-note payout and does not pass through this odds
rounding policy.

Settlement identity includes ticket ID, result-set revision, prize-table revision,
fixed-prize policy revision, method version, and rounding-policy version. JCZQ requires null
prize/fixed-prize refs and a non-null rounding version; Zucai requires non-null prize/fixed-
prize refs and a null odds-rounding version. For Zucai, the settlement policy reference must
equal the one revision shared by its artifact, Ticket, notes, and legs and must pass the
ticket-kind/currency/unit-stake/allowed-tier invariants above. Exact replay is idempotent.
Corrections follow the direct-predecessor transition rules above; they never delete
transactions, rewrite prior
settlements, or charge stake again. Ledger projections sum signed amounts and verify
conservation.

The review view presents forecast truth, money ledger, and intervention quality separately.
It queues Prediction grades, Adjudications, Factor verdicts, night-calibration reports, and
scoreboard observations for Jun's judgment.

The Application does not write `scoreboard.json`. During shadow operation that JSON remains
the authority. Jun still updates it through the external governed operating step, then the
Application or CLI may record the matching `scoreboard observe`; shadow reconciliation is
external governance rather than a completed Web-only lifecycle.

Jun first records `record_scoreboard_effect_disposition` as `effect_required` with exact
metric keys or `no_effect` with a reason. This judge-only typed Action cannot be inferred by
the resolver. `effect_required` requires a non-empty unique metric-key set; `no_effect`
requires an empty set and a non-empty reason. When a review changes scoreboard truth, it
remains pending until the external
`scoreboard.json` update hash has been observed, the matching scoreboard-observation Action
has committed, and shadow reconciliation passes. The Application displays these three gates
but cannot perform the JSON mutation or scoreboard cutover. A `no_effect` review completes
only from its explicit disposition Action and does not invent an external update requirement.

Completion is not inferred from the latest global shadow run. The review records its lane,
business key, disposition Action, pre-update scoreboard hash, required metric keys, and exact
observation Action references. A deterministic `ScoreboardReviewCompletionReceipt` binds
that review to either its `no_effect` disposition or the post-update `legacy_sha256`, the
observation Action IDs, a shadow-review ID whose `source_high_watermark` includes those
Actions, and zero unexplained differences for the review's metric keys. Only that receipt
permits `review -> complete`.

```text
ScoreboardEffectDispositionRevision
  disposition_revision_id, family_id, revision_no, supersedes_revision_id
  review_id, disposition, reason
  pre_update_legacy_sha256, required_metric_keys, created_by_action_id

ScoreboardReviewObservationLink
  review_id, disposition_revision_id, metric_key, observation_action_id
  observed_legacy_sha256

ScoreboardReviewCompletionReceipt
  completion_receipt_id, review_id, disposition_revision_id
  post_update_legacy_sha256, observation_action_ids
  shadow_review_id, shadow_source_high_watermark, completed_by_action_id
```

Every linked observation is submitted with the signed review token, has exactly one required
metric key, and names the same post-update hash. Completion rejects missing, duplicate,
superseded, wrong-review, wrong-hash, or below-high-water observations. For `no_effect`, the
disposition retains its pre-update hash, while the completion receipt's post-update hash,
observation links, and shadow-review fields are null. This is the only receipt shape that
bypasses external reconciliation.

Each review has exactly one current disposition revision. A new judge submission must name
the expected current revision, supersedes it only before completion, and invalidates all links
to the old revision. Once a completion receipt exists, both review and disposition are
terminal. For `no_effect`, `record_scoreboard_effect_disposition` atomically creates the
receipt and sets `completed_by_action_id` to that same judge Action. For `effect_required`,
Jun explicitly submits `request_scoreboard_review_completion` after the external update,
observation Actions, and shadow review. The command must carry the exact signed opaque
shadow-review token selected by Jun; that token binds the shadow-review ID, source high-water
mark, compared legacy hash, and metric-key set. A worker executes
`complete_scoreboard_review` as a `deterministic_system` Action, validates that exact review
and every other bound gate, and atomically writes the receipt. It never searches for or
chooses the latest qualifying global shadow run. GETs, projection rebuilds, and an unrelated
global shadow run never create it.

## 10. Application architecture

```text
External CLI / Telegram collection
        |
versioned importer -> typed Actions -> Ontology / CAS
        |
+-----------------------+-----------------------+
| Zucai lane adapter    | JCZQ lane adapter     |
| issue + 14 matches    | sale day + all offers |
+-----------------------+-----------------------+
        |
OperatorTaskProjection (derived, versioned, no write authority)
        |
Today / Zucai / JCZQ focused workbench DTOs
        |
browser form -> Product Action Gateway -> typed Action -> outbox refresh
```

### 10.1 Replacement boundary

`ZucaiArtifactRepository` is removed as the live task-discovery authority. Legacy issue,
prep, rx, candidate, and ledger files may enter through explicit versioned importers for
historical continuity. Each importer:

- accepts one declared schema version;
- validates with strict typed contracts;
- emits formal Actions/objects or a quarantined import report;
- records source hash, retrieval, import version, counts, and skips;
- is idempotent and replayable;
- never guesses a schema from arbitrary keys;
- never passes an arbitrary mapping to templates or JavaScript.

Current producer paths must emit a declared contract version. Historical files have no
embedded version, so import requires an explicit `--contract-version`; content inspection
may never select the version. The golden replay contract is:

| Issue | Declared rx contract | Expected result |
| --- | --- | --- |
| 26113 | `zucai-legacy-rx-v2` | accept five Predictions and recognize six Adjudication entries; preserve four string ticket summaries as non-deployable legacy text |
| 26114 | `zucai-legacy-rx-v2` | accept five Predictions and recognize seven Adjudication entries; preserve three string ticket summaries as non-deployable legacy text |
| 26115 | `zucai-legacy-rx-v3` | accept six Predictions and recognize five Adjudication entries; all four candidate rows lack faces and remain non-deployable summaries |
| 26116 | `zucai-legacy-rx-v3` | accept eight Predictions and recognize seven Adjudication entries; import eight face-bearing rows as unaudited drafts and four rows as non-deployable summaries |

For every issue, the issue/prep contract independently imports its recorded historical task
data for replay. It may satisfy official-slate authority only when its provenance references
an official Sporttery retrieval; otherwise its slate is labelled `legacy_replay` and cannot
become the current production discovery input.
Only already-resolved legacy Adjudication entries create formal Adjudications; pending
entries remain visible work. A face-bearing legacy candidate is never approved on import:
it must be linked to current Forecast revisions and rerun the current audit. Any mismatch
from the table fails its golden test. Unknown versions or undeclared fields are quarantined
with a stable reason, but a historical rx failure cannot erase the current task discovered
from `OfficialSaleSlateRevision`.

### 10.2 Lane boundaries

Both adapters implement one public protocol:

```text
discover(as_of) -> list[TaskSeed]
snapshot(task_id, as_of) -> LaneTaskSnapshot
evidence_requirements(snapshot) -> list[RequirementStatus]
baseline_inputs(snapshot) -> BaselineInputs
ticket_inputs(snapshot) -> CandidateInputs
result_status(snapshot) -> ResultStatus
```

The shared resolver understands phases and authority, while lane modules own market
definitions, ticket notation, group composition, result encoding, and lane-specific audit
reports. No large conditional tree mixes both sports-lottery formats in templates.

### 10.3 Product contracts

All normal-workflow responses are strict, versioned discriminated DTOs with unknown fields
rejected. Datetimes are timezone-aware ISO 8601 values, money is integer minor units with an
explicit currency, and probabilities are decimal strings at a declared precision. The
normal surface uses these contracts rather than passing ontology rows or arbitrary mappings.

The sale-slate boundary is:

```text
OfficialSaleSlateViewV1
  kind = "official_sale_slate_v1"
  lane, business_key, revision_no, state
  published_at, retrieved_at, next_deadline_at
  total_offer_count, open_offer_count, offers: list[OfficialOfferViewV1]

OfficialOfferViewV1
  kind = "official_offer_v1"
  official_match_no, match_label, competition_label
  kickoff_at, sale_opens_at, sale_deadline_at, offer_state
  markets: list[OfferMarketViewV1]
  evidence_complete_count, evidence_required_count, next_action

OfferMarketViewV1
  market_code, market_label, settlement_policy_label
```

Slate state is `current | superseded | invalid`; offer state is
`upcoming | open | closed | cancelled`. A cancelled offer remains visible in lineage but is
excluded from readiness and candidate envelopes.

The baseline boundary is:

```text
BaselineEnvelopeViewV1
  kind = "baseline_envelope_v1"
  lane, business_key, ticket_kind
  currency, capital_cap_minor, maximum_ticket_count
  offer_constraints: list[OfferConstraintViewV1]
  allowed_structures: list[StructureTemplateViewV1]
  maximum_exhaustive_candidate_count
  envelope_state, blocked_reasons: list[OperatorBlockViewV1]

OfferConstraintViewV1
  official_match_no, market_code
  allowed_face_bundles: list[FaceBundleViewV1]
  omission_allowed

FaceBundleViewV1
  bundle_code, face_codes: list[str]

StructureTemplateViewV1
  kind = jczq_pass | zucai_group
  structure_code, structure_label, eligible_official_match_nos
  pass_size, required_offer_count, maximum_groups

MarketBaselineViewV1
  kind = "market_baseline_v1"
  lane, business_key, cutoff_at, policy_label, comparison_only = true
  probability_precision = 12
  rows: list[MarketProbabilityRowV1]
  envelope: BaselineEnvelopeViewV1 | null
  deterministic_metrics: CandidateMetricsV1 | null

MarketProbabilityRowV1
  official_match_no, market_code
  faces: list[FaceProbabilityViewV1]

FaceProbabilityViewV1
  face_code, probability_decimal

CandidateMetricsV1
  currency, ticket_count, distinct_note_count, paid_note_unit_count
  stake_minor, capital_utilization_decimal
  probability_kind = all_required_legs | any_ticket_all_required_legs
  objective_probability_decimal, expected_broken_legs_decimal
  common_dead_faces: list[DeadFaceViewV1]
  break_even_bonus_minor, break_even_to_official_median_decimal

DeadFaceViewV1
  official_match_no, face_codes: list[str]
```

The result boundary is:

```text
ResultEvidenceViewV1
  kind = "result_evidence_v1"
  lane, business_key, state, result_cutoff_at
  matches: list[MatchResultEvidenceViewV1]
  zucai_prize_table: ZucaiPrizeTableViewV1 | null
  settlement: TaskSettlementViewV1
  settlement_ready, blocking_codes: list[str]

MatchResultEvidenceViewV1
  official_match_no, match_label
  receipts: list[ResultSourceReceiptViewV1]
  normalized_disposition, normalized_home_90, normalized_away_90
  agreement_state, outcome_state

ResultSourceReceiptViewV1
  source_kind, captured_at, receipt_state, source_disposition
  home_90, away_90, invalid_code

ZucaiPrizeTableViewV1
  issue, currency, published_at
  tiers: list[ZucaiPrizeTierViewV1]

ZucaiPrizeTierViewV1
  tier_code, ticket_kind, required_correct_count
  official_winning_note_count, payout_minor_per_winning_note

TaskSettlementViewV1
  request_state, settlement_state, blocking_codes: list[str]
  currency: str | null, placed_ticket_count, settled_ticket_count
  total_stake_minor, gross_payout_minor
  last_run: TaskSettlementRunViewV1 | null
  tickets: list[TicketSettlementViewV1]

TaskSettlementRunViewV1
  requested_ticket_count, eligible_ticket_count, settled_ticket_count
  skipped_ticket_count, persisted_settlement_count
  skips: list[TaskSettlementSkipViewV1]

TaskSettlementSkipViewV1
  ticket_label, reason_code

TicketSettlementViewV1
  ticket_label, settlement_state, revision_no, corrected
  settlement_method_label, rounding_policy_label
  currency, distinct_note_count, paid_note_unit_count
  winning_note_unit_count, void_note_unit_count
  stake_minor, gross_payout_minor
  notes: list[TicketNoteSettlementViewV1]
  cash_entries: list[SettlementCashEntryViewV1]

TicketNoteSettlementViewV1
  note_index, structure_label, group_label
  note_grade, unit_count, winning_unit_count, void_unit_count
  correct_leg_count, void_leg_count, prize_tier_code
  stake_minor, payout_minor, legs: list[TicketLegSettlementViewV1]

TicketLegSettlementViewV1
  leg_index, official_match_no, match_label, market_code, selection_code
  result_disposition, market_result_code, leg_grade
  booked_decimal_odds, settlement_parameter_decimal

SettlementCashEntryViewV1
  transaction_kind, amount_minor, currency, replaces_prior_payout
```

`source_kind` is exactly `api_football | sporttery_game90 | okooo_manual`;
`receipt_state` is `missing | available | invalid`; `normalized_disposition` and
`source_disposition` are `played_90 | postponed | official_void | null`; `outcome_state` is
`waiting | committed | corrected`; result state is
`waiting_sources | waiting_completion | conflict | ready | corrected`.
`waiting_completion` means the sources agree the match is postponed but no settleable Outcome
exists. Settlement request state is
`not_requested | queued | completed | rejected`; task settlement state is
`not_applicable | not_ready | blocked | settled | corrected`, while a ticket settlement is
`blocked | settled | corrected`. `not_applicable` requires zero placed Tickets, zero money
totals, null currency, and an empty ticket list. `booked_decimal_odds` is required for JCZQ
and null for Zucai; `prize_tier_code` is required only for a winning fixed-prize note.
Result state `ready` means Outcomes are ready independently of prize publication; a Zucai
view with no current prize table has `settlement_ready = false` and `prize_not_ready`.
For official-void Zucai legs the registered fixed-prize policy treats every face as matching;
JCZQ instead grades the leg void with odds multiplier one. These lane rules are versioned and
never inferred by the UI.

The Telegram ownership boundary is:

```text
TelegramOwnerStatusV1
  kind = "telegram_owner_status_v1"
  owner_mode = openclaw | native_distinct_token | unavailable | conflict
  configured, last_heartbeat_at, heartbeat_state
  confirmation_available, blocking_code, recovery_label
```

`OperatorBlockViewV1` contains only `code`, operator-readable `message`, repair owner,
reevaluation time, and a stable recovery link. It never embeds raw provider payloads.

Every browser mutation extends this exact envelope:

```text
OperatorCommandV2
  schema_version = "2"
  kind, expected_snapshot_token, idempotency_key
```

The initial `/api/v2/operator` allowlist is:

| Command kind | Business fields | Delegated human Action |
| --- | --- | --- |
| `freeze_evidence` | task key, current requirement revision token | queues judge-owned `request_evidence_freeze`; worker runs governed freeze |
| `record_baseline_envelope` | ticket kind, cap/currency, offer constraints, structure templates, enumeration limit | `record_baseline_envelope` |
| `commit_match_judgment` | match/market key, belief decimals, typed Factor inputs, face bundles, Rule IDs, evidence refs, falsifier, rationale | existing Forecast/Read commit plus its judgment link |
| `freeze_judgment_prescription` | current judgment revision tokens | `freeze_judgment_prescription` |
| `request_candidate_generation` | baseline, envelope, prescription opaque tokens | queues deterministic `generate_ticket_candidate_set` |
| `select_candidate` | candidate opaque token, reason | `select_ticket_candidate` |
| `record_no_ticket` | work-item token, reason code/text, reason basis, Rule IDs, optional comparison-candidate token; server derives remaining scope | `record_no_ticket` |
| `supersede_no_ticket` | adjudication token, reason | `supersede_no_ticket` |
| `create_ticket_batch` | selection token, account/channel | existing protected draft Action plus decision lineage |
| `adjudicate_audit_warn` | batch/finding tokens, decision, reason, evidence refs | existing judge-only Adjudication |
| `approve_ticket_batch` | current batch token | existing protected approval Action |
| `request_confirmation` | audited artifact token | existing first-stage confirmation Action |
| `request_settlement` | task and result-set tokens | queues deterministic task settlement |
| `grade_prediction` | prediction review-item token, outcome `hit | miss | na`, reason | existing `grade_prediction` Action |
| `record_scoreboard_effect_disposition` | review token, disposition, metric keys, reason | matching judge-only Action |
| `record_scoreboard_observation` | review token, typed observation, external scoreboard hash | existing `scoreboard observe` Action |
| `request_scoreboard_review_completion` | current review/disposition tokens and exact signed shadow-review token | queues deterministic `complete_scoreboard_review` validation |
| `rebuild_scoreboard_projection` | no business fields | invokes the existing build-only projector; writes no Action and never changes `scoreboard.json` |

Judgment Factor input is also closed:

```text
FactorAdjustmentInputV2
  factor_id, scope_key
  evidence_ref_tokens: list[str]
  offsets: list[FaceOffsetInputV2]

FaceOffsetInputV2
  face_code, offset_probability_decimal

FaceProbabilityInputV2
  face_code, probability_decimal

FaceBundleInputV2
  bundle_code, face_codes: list[str]

OfferConstraintInputV2
  official_match_no, market_code
  allowed_face_bundles: list[FaceBundleInputV2]
  omission_allowed

StructureTemplateInputV2
  kind = jczq_pass | zucai_group
  structure_code, eligible_official_match_nos: list[str]
  pass_size, required_offer_count, maximum_groups

ScoreboardObservationInputV2
  group_key, metric_key, tally, detail, status
  numerator_decimal, denominator_decimal, value_decimal, unit
  evidence_ref_tokens: list[str], effective_at, supersedes_observation_token

ScoreboardEffectDispositionInputV2
  disposition = effect_required | no_effect
  metric_keys: list[str], reason
```

The `kind` discriminator selects one strict command class rather than a generic payload.
`record_baseline_envelope` uses `OfferConstraintInputV2` and
`StructureTemplateInputV2`; `commit_match_judgment` uses
`FaceProbabilityInputV2`, `FactorAdjustmentInputV2`, and `FaceBundleInputV2`; and
`record_scoreboard_observation` uses exactly one `ScoreboardObservationInputV2`. Every
optional scalar is declared nullable by its command class. No command accepts `dict`,
`Mapping`, `Any`, an anonymous object list, or unregistered extra fields. Actor ID/role,
policy version, object IDs, and `deterministic_system` role are server-owned. This router has
no audit-ERROR override, final placement, rule lifecycle, scoreboard cutover, release, or
launchd mutation command.

`ScoreboardEffectDispositionInputV2.reason` is always non-empty. `effect_required` requires
one or more unique registered metric keys; `no_effect` requires an empty metric-key list.
There is no generic `grade_review_item`: the initial browser contract grades only a
Prediction through the exact existing Action. Adjudication history, Factor verdicts, and
night-calibration reports remain visible, but any further mutation requires its own future
named command/Action contract rather than a dynamic outcome payload or factor-lifecycle
bypass.

The task/work-item boundary is also explicit:

```text
OperatorTodayResponseV1
  kind = "operator_today_v1", as_of
  next_action: TodayQueueEntryV1 | null
  entries: list[TodayQueueEntryV1]

TodayQueueEntryV1 = TodayWorkItemViewV1 | LaneScheduleRecoveryViewV1

TodayWorkItemViewV1
  kind = "today_work_item_v1"
  lane, business_key, task_label, scope_kind, scope_label
  phase, deployment_outcome, next_deadline_at
  progress: WorkItemProgressViewV1
  blocking_reason: OperatorBlockViewV1 | null
  next_action: WorkItemActionViewV1

LaneScheduleRecoveryViewV1
  kind = "lane_schedule_recovery_v1"
  lane, shanghai_check_date, recovery_key, phase = "waiting_schedule"
  last_check_state: str | null, last_checked_at: datetime | null
  last_source_run_state: str | null
  blocking_reason: OperatorBlockViewV1
  next_action: WorkItemActionViewV1

OperatorLaneResponseV1
  kind = "operator_lane_v1", lane, as_of
  focus_business_key: str | null
  current_tasks: list[OperatorTaskSummaryV1]
  archive_tasks: list[OperatorTaskSummaryV1]

OperatorTaskSummaryV1
  kind = "operator_task_summary_v1"
  lane, business_key, task_label, task_state
  current_slate: OfficialSaleSlateViewV1
  work_items: list[OperatorWorkItemViewV1]

OperatorWorkItemViewV1
  kind = "operator_work_item_v1"
  scope_kind, scope_label, phase, deployment_outcome
  next_deadline_at, is_current, snapshot_token
  progress: WorkItemProgressViewV1
  blocking_reason: OperatorBlockViewV1 | null
  next_action: WorkItemActionViewV1 | null

WorkItemProgressViewV1
  completed_count, required_count, progress_label

WorkItemActionViewV1
  action_code, action_label, enabled, recovery_link
```

`scope_kind` is `sale_wave | artifact | ticket | review`; phase uses section 5.3 plus
`blocked`; phase/outcome combinations must satisfy the matrix in section 5.3. `task_state`
is `current | archive`; it is not a phase and multiple business keys may be current under
section 5.5. A Today work-item row always has an operator/recovery action. A passive or
archived `OperatorWorkItemViewV1` may have null `next_action`; its nullable blocking reason
distinguishes passive waiting from a repairable block. The server orders Today entries by
section 4.2 and derives the top-level `next_action` from its first row, never from odds or an
aggregate guessed phase. A lane's `focus_business_key` is derived only by section 5.5. The opaque
`snapshot_token` is submitted by forms but not rendered as operator text. A schedule-recovery
entry has neither a business key nor a task snapshot token.

The remaining normal contracts are lane-filtered worklists,
`EvidenceRequirementSummary`, `MatchEvidenceChecklist`, `MatchJudgmentEditor`,
`TicketCandidateComparison`, `NoTicketAdjudicationSummary`, phase-specific StepView variants,
and stable recovery models. `RuntimeWorkerStatus` contains `TelegramOwnerStatusV1` rather
than exposing transport configuration.

Technical IDs, content hashes, exact Action high-water marks, and source payload locations
live in a separate audit envelope reached through deliberate drill-down. Normal DTOs contain
formatted business labels and stable links only. Mutating forms carry a signed opaque
snapshot token; templates do not display or decode its internal references.

## 11. Interface behavior

### 11.1 Normal visibility

The default task view shows only operator-relevant information:

- business day/issue, lane, progress, kickoff and sale deadline;
- match teams and competition;
- evidence-category state and concise verified facts;
- market distribution, movement, committed belief, and delta;
- rules/flags that affect the current action;
- selected expression and candidate-ticket impact;
- audit state, stake, cap use, and confirmation/ledger state.

Source links, capture time, version history, Actions, IDs, hashes, and correlation IDs are
progressive disclosure. Raw JSON, generic mapping dumps, tracebacks, schema versions, and
Action counts never appear in a normal workflow page.

### 11.2 Interaction

- One primary command advances each phase.
- Match judgment uses stable numeric inputs, face/market checkboxes, controlled Rule/Factor
  selectors, evidence references, and a concise reason field.
- Saving advances to the next unresolved match and cannot shift layout dimensions.
- Ticket candidates use a comparison table, not serialized cards or nested panels.
- PASS, WARN, ERROR, waiting, stale, expired, and complete use text/icon semantics in
  addition to color.
- Desktop keeps match navigation, judgment, and ticket impact visible without overlap.
- Mobile becomes one reading column in the order evidence -> judgment -> impact -> action.

## 12. Error and recovery model

Every failed/waiting state states what is wrong, what it prevents, who can repair it, and
when/how it will be reevaluated. Stable codes include:

| Code | Meaning and recovery |
| --- | --- |
| `official_schedule_missing` | external official collection has not produced the business task |
| `identity_unresolved` | canonical match/team identity must be resolved externally |
| `evidence_missing` | named checklist categories are absent |
| `evidence_stale` | named facts fall outside required age/validity |
| `evidence_conflict` | conflicting required predicates need formal adjudication |
| `source_contract_invalid` | versioned import is quarantined; current task remains visible |
| `task_snapshot_changed` | official slate/version changed after the form opened |
| `audit_error` | candidate cannot advance without authorized human override |
| `confirmation_expired` | issue a new challenge only before the effective cutoff: the earlier of the approval-frozen minimum and every current referenced-offer deadline; cancelled offers are already terminal |
| `telegram_update_owner_conflict` | two consumers claim the same bot token; confirmation is blocked |
| `placement_ledger_integrity` | protected callback records disagree; block and reconcile from the Action ledger, never from a browser placement form |
| `result_source_missing` | the three-source result set is incomplete |
| `result_pending` | sources agree the match is postponed; wait for play or an official void disposition |
| `result_source_conflict` | normalized 90-minute results disagree and settlement is blocked |
| `projection_stale` | run the governed build-only projection rebuild |
| `app_instance_conflict` | another writable process owns this data directory |

Unexpected failures preserve task context and show a correlation ID. They never redirect
the operator to a generic system-health dashboard.

## 13. Runtime consistency

### 13.1 Single writable Application

`nutmeg app` acquires an advisory instance lock scoped to the resolved data directory.
The lock record includes PID, start time, data directory, bind address, and port. A second
writable instance fails fast with `app_instance_conflict`; stale locks are reclaimed only
after verifying that the recorded process no longer exists. Read-only test/replay instances
use explicit isolated data directories and do not share the production lock.

The lock path keeps one stable inode. Clean release marks its canonical record released and
fsyncs before unlocking; it does not unlink the path. A later owner can therefore distinguish
a clean release from a crashed `held` record without an unlink/open race, while an empty,
malformed, or unverifiable existing record still fails closed.

For the production data directory this lease identifies the one canonical Application root
and its infrastructure workers. It is not a global SQLite writer lock: existing CLI and
OpenClaw processes may still commit the typed Actions their runbooks authorize. The
production shadow route is mounted in the canonical process and may not be served by a
second Application instance.

A separate ontology-writer lease coordinates migrations with every formal Action UOW.
Normal Application, CLI, worker, and OpenClaw Action transactions hold a shared lease for
their complete transaction; guarded maintenance holds an exclusive lease. A production
schema migration must retain one exclusive descriptor continuously from the pre-backup audit
through SQLite online backup, backup reconciliation, migration, and post-migration audit.
Checking that a lease is free and releasing it before backup is not sufficient.

### 13.2 Scheduler ownership

The System maintenance page detects overlapping OpenClaw and launchd ownership and reports
the commands, labels, enabled/loaded state, last runs, and conflict. Its probe uses only fixed,
bounded, read-only argv calls for `openclaw cron list --all --json`,
`openclaw channels status --channel telegram --json`, and `launchctl print`; it never accepts
command text from a request. Normalization uses this closed stage registry; an unknown job is
reported as unmapped and cannot be silently assigned by substring guessing:

| Stage | OpenClaw exact name or normalized argv | launchd label |
| --- | --- | --- |
| `jczq_am` | `Nutmeg-AM数据入库`; `Nutmeg-临场数据刷新`; `nutmeg_scheduler_ops.py run-strict --stage am` | `com.nutmeg.decision.am` |
| `jczq_decision` | `Nutmeg-每日最终决策` | - |
| `jczq_decision_recovery` | `Nutmeg-最终决策受限补跑` | - |
| `jczq_preclose_check` | `Nutmeg-收盘前闸门`; `nutmeg_scheduler_ops.py validate-preclose` | - |
| `jczq_close` | `Nutmeg-收盘`; `nutmeg_scheduler_ops.py run-strict --stage close` | `com.nutmeg.decision.close` |
| `jczq_close_verify` | `Nutmeg-收盘交付确认`; `nutmeg_scheduler_ops.py verify-close` | - |
| `jczq_settle` | `Nutmeg-昨日结算`; `decision-settle`; `run-strict --stage settle` | `com.nutmeg.decision.settle` |
| `jczq_settlement_retry` | `Nutmeg-D1D2补结算`; `nutmeg_scheduler_ops.py retry-settlement` | - |
| `zucai_prep` | - | `com.nutmeg.zucai.prep` |
| `zucai_prep_revision` | - | `com.nutmeg.zucai.prep-revision` |
| `zucai_afternoon` | - | `com.nutmeg.zucai.afternoon` |
| `zucai_revision` | - | `com.nutmeg.zucai.revision` |

Each enabled OpenClaw job and each loaded launchd label is one ownership claim. More than one
claim for the same normalized stage is a conflict even when both claims come from OpenClaw or
share an executable; the recovery/check/retry stages above remain distinct and therefore do
not collide with their primary stage. A name and argv that map to different stages is
`diagnostic_unavailable`, not a guessed claim. The page does not enable, disable, edit, run,
or repair system schedules. Probe failure is a visible `diagnostic_unavailable` state, never
evidence that an owner is absent. Existing launchd user gates remain untouched.

### 13.3 Projection consistency

Normal product responses expose only the business state `projection ready/stale`. Exact
source Action and projection high-water marks live in the audit envelope and maintenance
view. If the projection is behind, affected controls block with `projection_stale`; a
governed build-only rebuild can be invoked from maintenance. Rebuilding does not mutate
`scoreboard.json` or perform a cutover.

Projection dependencies are declared per command and checked immediately before its Action.
In the initial surface, scoreboard effect disposition, scoreboard observation, and review
completion all require the current scoreboard projection high-water and are disabled while
it is stale. The build-only rebuild control stays available so the operator can recover.
Unrelated evidence, judgment, ticket, and result commands do not acquire an invented
scoreboard dependency. A stale token still fails after a rebuild, forcing a fresh GET.

### 13.4 Root rollout and rollback

Rollout uses two independent server-start settings:

```text
operator_surface_mode = legacy_read_only | shadow | active
operator_runtime_scope = production | isolated_candidate
production_data_dir = absolute path
candidate_commit = full source commit
operator_accepted_commit = full source commit or empty
telegram_update_owner = openclaw
```

The defaults are `legacy_read_only` and `production`. Environment variables use the normal
`NUTMEG_` prefix. Build/runtime metadata supplies the full running commit; request payloads
cannot choose any mode or commit.

| Scope / mode | `/` | `/operator-next` | Browser writes and side effects |
| --- | --- | --- | --- |
| production / `legacy_read_only` | existing focused UI, visibly read-only | 404 | every operator mutation and generic Action POST capable of bypassing it returns 405 |
| production / `shadow` | existing focused UI, read-only | new workbench reading production projections | all candidate and legacy mutations return 405; GET causes no Action, outbox, or shadow write |
| isolated_candidate / `active` | redirects to new workbench | full candidate workbench | only `/api/v2/operator` allowlisted writes reach the isolated Action gateway; all real Telegram, placement connectors, schedulers, and production scoreboard writes are disabled |
| production / `active` | new workbench | redirects to `/` | only `/api/v2/operator` allowlisted writes are enabled; legacy operator POST and generic `/api/v1/actions` remain 405 |

`isolated_candidate` requires an explicit CLI data directory whose resolved path differs
from `production_data_dir`. It uses its own instance lease and simulated confirmation
transport. A path match, missing production path, real Telegram token, placement connector,
or scheduler configuration makes startup fail. It never runs a production token consumer.

Production `active` startup additionally requires:

```text
operator_accepted_commit == candidate_commit == running_commit
```

Only Jun may set `operator_accepted_commit`. Passing tests, merging a branch, Release page
state, a Web request, or the Application itself cannot create acceptance or change the
surface mode. A mismatch or dirty/unidentifiable running build fails closed before binding
the server.

All schema migrations in this rebuild are expand-only, and old readers remain functional
through the acceptance window. Activation is a configuration change plus process restart,
never a migration side effect. Rollback uses the same forward-compatible binary, changes
the production surface to `legacy_read_only`, and restarts the canonical instance. It never
runs a down migration, restores a database, starts an old commit, deletes/rewrites Actions,
or reverses ledger entries.

Rollback immediately blocks new browser judgments, tickets, approvals, and confirmation
requests. Challenges already issued remain owned by the existing OpenClaw callback route;
the Application deadline scanner continues until each reaches placed or shadow. Surface
mode never abandons an in-flight protected artifact. Root activation remains distinct from
scoreboard cutover, soak entry, ReleaseApproval, and every launchd user gate.

## 14. Security and authority

- The server binds to loopback by default.
- Browser roles are server assigned; request payloads cannot choose an actor or role.
- All mutations enforce origin/CSRF, idempotency, expected versions, and policy permission.
- Source and AI text is escaped and treated as untrusted evidence.
- Secrets, source payloads, and Telegram tokens never enter DTOs, browser storage, or logs.
- AI roles cannot verify Claims, commit Forecasts, adjudicate, approve Tickets, grade,
  confirm placement, change rules, cut over the scoreboard, or approve a release.
- The Application cannot shell out to decision CLIs or edit operational JSON files.

## 15. Test and verification strategy

### 15.1 TDD rule

Every implementation task follows RED -> GREEN -> REFACTOR. Tests use
`uv run pytest ...`; no production implementation precedes its failing test. Each delivery
package has its own branch and commits, and the repository pre-commit hooks must pass.

### 15.2 Unit and contract tests

- official task discovery, lane recovery without a business key, confirmed-no-sale
  suppression, task-set changes, exact opening/deadline equality, rolling `next_deadline`,
  early-offer closure, time-only form invalidation, added-offer/new-wave behavior,
  no-ticket family-scope preservation, simultaneous early `await_result`/late
  `judge_matches` work items, server-derived artifact deadline, shortened/cancelled effective
  cutoff, all-cancelled aggregate expiry, work-item expiry, multiple concurrent/next-day
  tasks, recovery-only null focus, all-closed lane focus, and archive-state/Today review
  re-entry;
- all evidence categories, verification levels, validity intervals, whole-task gates, and
  conflict combinations;
- strict importer versions, unknown versions, malformed payloads, idempotent replay, and
  quarantine reports;
- both lane adapters and every phase transition;
- market-prior immutability, conditional-baseline labelling, baseline non-deployability,
  complete decision lineage, zero-delta provenance, non-zero Factor reconstruction, and
  stale descendant rejection;
- exhaustive enumeration or fail-without-pruning, exact multi-ticket union probability,
  decimal/tie determinism, all-candidate audit partitions, cap arithmetic, ERROR/WARN
  revalidation, and absence of recommendation/auto-selection;
- dedicated no-ticket phase references, closed reason code, judge-only permission,
  server-derived remaining scope, partial-placement preservation, challenge cancellation,
  idempotency, stale token, exact-cutoff expiry precedence with a delayed scanner, explicit
  reopen, not-applicable settlement with no-ticket/natural-expiry/cancellation
  operational-or-forecast review, and no hindsight-counterfactual cases;
- role restrictions, instance locking, command-specific projection high-water checks across
  every dependent control, rebuild recovery, and recovery codes;
- the full surface/scope route matrix, mutation 405s, acceptance-commit mismatch, shadow GET
  Action high-water stability, isolated-path refusal, disabled isolated side effects,
  active-to-read-only rollback data retention, and in-flight challenge completion;
- sole Telegram update ownership, per-artifact partial placement, atomic callback ledger,
  callback/scanner/correction/no-ticket CAS at the exact cutoff, approval-without-challenge
  shadow, native `ntc` interactive registration, account/auth/chat/sender denial, stdin-only
  bridge dispatch, `{handled: true}` without AI fallback, plugin-service heartbeat, and
  absence of a Web final-confirmation endpoint;
- heartbeat renewal leaves Action/projection high water unchanged while an actual callback
  advances it exactly once;
- strict three-source result manifests, normalized 90-minute/official-void Outcome revisions,
  invalid-source audit refs, closed Zucai prize tiers, disagreement and correction,
  result-set/request permissions, and `deterministic_system` execution;
- a two-match JCZQ ticket proving each leg uses its own Outcome, every enabled JCZQ market
  grader, persisted HHAD line, Decimal odds/rounding, JCZQ loss/win/all-void note states and
  unit counters, SFC fourteen-leg versus Renjiu nine-leg exact-match exclusive tiers,
  multi-note/multiplier payout, single-revision fixed-prize policy binding and every
  kind/currency/stake/tier invariant, sale-time operation before prize publication, negative
  prize-count/amount rejection, task-run count reconciliation, unsupported-market blocking,
  all four cash-correction transitions plus consecutive correction uniqueness, replay
  idempotency, and ledger conservation;
- scoreboard effect/no-effect disposition and a task-scoped completion receipt that rejects
  empty/duplicate required keys, keys on no-effect, the wrong JSON hash, observation Action,
  metric key, explicitly submitted shadow-review token, or high-water mark; rejection of
  automatic latest-review selection, disposition supersession, no-effect atomic completion,
  explicit effect-required completion request, and GET no-write behavior;
- DTOs and mutation commands reject extras, anonymous mappings, actor roles, raw IDs, and
  invalid money/probability representations; passive/archive actions are nullable, scope
  phase/outcome combinations are closed, and templates receive no arbitrary mappings.

### 15.3 Production-shaped integration tests

Fixtures include:

- Zucai issues 26113, 26114, 26115, and 26116 in their actual recorded shapes;
- a current-shape JCZQ business day containing multiple offered fixtures and markets;
- missing alias, provisional Team, empty evidence, stale market, conflicting Claim, rejected
  Action, changed official slate, expired deadline, and stale projection cases.

Both lanes must replay end to end on fresh isolated databases:

```text
official ingest -> evidence ingest/adjudication -> evidence freeze
-> market prior baseline -> envelope -> Forecasts/prescription
-> conditional baseline + exhaustive candidate set + all-candidate audit
-> human selection -> protected artifact -> human confirmation or shadow
-> ledger -> three-source result/prize set -> settlement -> review pending
-> external scoreboard.json update -> scoreboard observe
-> shadow reconciliation -> complete
```

Rejected/failed Actions must not advance progress. The database, Action ledger, rendered
report, and UI count must reconcile after every transition.

### 15.4 Browser and visual tests

Playwright covers desktop and mobile viewports for Today ordering, lane switching, evidence
gates, all-match judgment, baseline/candidate comparison, audit return-to-edit, explicit
no-ticket, Telegram waiting/expiry, ledger, settlement, review, and archive behavior.

Screenshots and DOM assertions verify:

- no raw JSON, internal IDs, hash, schema, or traceback in normal pages;
- no overlapping or clipped text at supported viewports;
- controls retain stable dimensions as data changes;
- keyboard/focus behavior and non-color status labels;
- the selected task and next action remain unambiguous;
- scoreboard review is visibly pending before external reconciliation and complete after it.

### 15.5 Completion gate

Before any package is called complete:

- run its focused tests and full affected-domain suite;
- run ruff/pre-commit and compile checks used by the repository;
- use the Nutmeg `verify` recipe for decision-domain changes;
- replay both lane chains with current production-shaped inputs;
- inspect fresh browser screenshots on desktop and mobile;
- run a read-only production audit proving the current task, evidence counts, Action high
  water, projection state, and active instance state;
- keep one verified local server running for Jun's actual acceptance test.

## 16. Delivery decomposition

Each package is independently branched, developed test-first, tested, committed, and
reported. A package starts from the main branch containing its declared dependencies. Shared
packages exercise both lanes; lane-specific behavior is never deferred to a later parallel
implementation.

1. **Single-instance lock and read-only rollout shell**: add the canonical root lease,
   surface/scope settings, accepted-commit startup gate, 405 mutation guards, candidate and
   v2 router mounts, owner/conflict status, isolated-side-effect guards, and rollback tests.
   Default production behavior is `legacy_read_only`.
2. **Official sale-slate ontology and dual-lane discovery**: migrate additive
   `OfficialSaleSlateRevision`/`OfficialOffer`/schedule-check storage, implement the strict
   official importer, offer-state/snapshot/current-task resolvers, lane recovery, and lane
   protocol, and test Zucai fourteen-order and JCZQ per-offer deadlines.
3. **Versioned legacy importer**: replace live rx discovery authority, implement declared
   v2/v3 import and quarantine, and satisfy the exact 26113-26116 golden replay table without
   making legacy candidate text deployable.
4. **Evidence policy and external ingest**: implement E1-E6 plus EC evaluation,
   `EvidenceIntakeManifestV1`, CLI/Telegram delegation to one deterministic ingest service,
   row-count reconciliation, and shadow-only RUNBOOK alignment.
5. **Evidence freeze and version invalidation**: create immutable per-match bundles, bind
   cutoff/policy/slate revisions, surface new evidence, and invalidate stale baselines,
   judgments, audits, and forms without rewriting prior versions.
6. **Judgment editor and market baseline**: create the non-deployable frozen matrix,
   revisioned baseline/envelope/prescription objects, all-match editor, judge-only
   Forecast/Read Actions, exact zero/non-zero Factor invariants, and database-backed progress
   reconciliation.
7. **Candidate comparison**: implement exhaustive operator-bounded lane enumeration,
   revisioned candidate sets, full-set audit partitions, decimal joint-probability ordering,
   cap/coverage/dead-face metrics, conditional market counterfactual labels, and report-only
   break-even values; synchronize contradictory RUNBOOK/RULEBOOK lines.
8. **Override, no-ticket, and protected artifact**: unify the named deviation structure,
   external human-only ERROR override Action, Web ERROR hard block, dedicated revisioned
   no-ticket/supersession Actions with cutoff-first CAS, full TicketDecisionLineage,
   current-revision audit binding, and immutable protected artifacts.
9. **Telegram ownership, ledger, and shadow**: keep OpenClaw as sole production update
   consumer, delegate callbacks to the existing service, prove atomic placement/ledger,
   support partial confirmation, and shadow approved artifacts without a challenge and
   artifacts with an unconsumed challenge under distinct reasons.
10. **Results and settlement**: implement versioned three-source 90-minute result evidence,
    official Zucai prize/fixed-policy tables, note multipliers, per-leg/per-note JCZQ and
    Zucai graders with closed note-state/exact-tier rules, single-policy binding, human
    settlement requests, task-run receipts, unsupported-market blocks, count/ledger
    reconciliation, and immutable correction reversal/replacement revisions.
11. **Review and scoreboard shadow**: expose truth, money, and intervention review queues;
    link grades, verdicts, calibration, and observations; add explicit scoreboard-effect
    disposition; prove projection rebuild does not write `scoreboard.json`; create the
    review-scoped completion request/receipt Actions with an exact shadow-review token;
    document and test the external update/reconcile step.
12. **UX, end-to-end replay, and root activation**: finish Today and lane views, remove raw
    JSON and the Web final-confirmation path, update the operator manual, run desktop/mobile
    Playwright and both full isolated chains, then make `active` available only after Jun's
    acceptance. Retain tested configuration rollback to `legacy_read_only`.

A package may be merged only after its fresh verification evidence is reported. Package 12
is the only package allowed to change the production root to `active`; earlier packages may
expose only read-only production views or fully isolated candidate writes.

## 17. Explicit exclusions

- autonomous research or probability judgment; software-inferred fixture/market/face options;
  software recommendation, automatic ticket selection, placement, or betting;
- re-enabling, disabling, or editing launchd decision schedules;
- scoreboard cutover, soak entry, ReleaseApproval, or production authority migration;
- modifying CONSTITUTION without a separate explicit Jun approval;
- resolving the C7 open-hole policy;
- WAF bypass or unsupported scraping of okooo/500.com;
- automatic inference that a board is `all dice`;
- generic multi-user, cloud, public, billing, or subscription features;
- a one-time migration of all historical narrative rx data.

## 18. Success criteria

The rebuild succeeds when Jun can open one local Application and, without reading JSON,
object IDs, schema versions, or CLI implementation details:

1. see the current official JCZQ day and Zucai issue together in deadline order;
2. never land on an expired issue while a current task exists;
3. understand every missing/stale/conflicting evidence item and why it blocks progress;
4. complete a structured judgment for every required match and see committed progress;
5. compare a frozen market prior and clearly labelled conditional market counterfactual with
   judgment-bound candidate tickets under the same human envelope;
6. see deterministic cost, exact joint probability, coverage loss, full audit partition,
   and persistent policy/decision lineage;
7. choose an adjusted ticket or explicitly adjudicate no-ticket without software bias;
8. follow the selected artifact through Telegram human confirmation, actual ledger entry,
   per-leg/per-note lane-correct settlement and correction, Application review, and the
   explicitly shown external scoreboard completion gate;
9. verify that an expired/unconfirmed artifact is shadow and never appears as placed;
10. verify that no AI or unattended process performed judgment or `ConfirmDispatch`;
11. run the same lifecycle for both lanes against current production-shaped data;
12. observe a single writable Application instance with no hidden scheduler ownership;
13. activate the new root only after explicit acceptance and restore `legacy_read_only`
    through configuration without reversing ontology data;
14. complete review with `scoreboard.json` still updated by the external governed step, then
    see the matching observation and shadow reconciliation in the Application.

## 19. Addendum 2026-09-10: judgment carries the leg audit's structure facts

Approved by Jun on 2026-09-10 after implementation exposed the gap. §8.3 requires
`create_ticket_batch` to rerun "the current authoritative leg audit". The authoritative audit
in `nutmeg/decision/legs_audit.py` reads two operator-authored facts that the judgment layer
did not carry, so the Application built every audit `Leg` with `anchor_integrity="unknown"`
and no precedents. The consequences were not cosmetic:

- C5 `broken_anchor_single` is ERROR-grade and blocks approval. It requires an explicit
  `anchor_integrity == "fail"`, so in the Application it could never fire. The CLI gate was
  strictly stronger than the surface Jun was being asked to activate.
- C7 `excluded_face_live_precedent` and C13 `broken_anchor_double` could never fire either.
- C14 `expensive_exclusion` fired on every candidate that dropped a face worth more than 20%,
  because its legal exit (anchor `pass` plus a `dead` precedent on that face) was unreachable.
  Every ticket would have demanded a WARN adjudication, which is how a gate becomes noise.

The judgment therefore records both facts as explicit human input, never inferred:

- `anchor_integrity` in the closed set `pass | fail | symmetric_damage | unknown`;
- `face_precedents`, each a `(face_code, precedent_ref, alive | dead)` row.

Storage is two additive append-only children of `OperatorMatchJudgmentRevision`
(`operator_match_judgment_anchor_facts`, `operator_match_judgment_face_precedents`,
schema 28) bound by the same content hash and typed Action. A judgment that declares
`unknown` with no precedents stores no rows; readers return `unknown` and an empty tuple, so
"not declared" and "declared unknown" stay the same fact and C14 still warns. The judgment
editor asks for both with no preselected default, and every rule keeps reading them only as
Jun recorded them.
