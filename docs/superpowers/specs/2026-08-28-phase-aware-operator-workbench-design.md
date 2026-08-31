# Nutmeg Phase-Aware Operator Workbench Design

Date: 2026-08-28  
Status: Implemented and verified on feature branch; awaiting Jun's merge decision
Scope: Reshape the local product UI around the active JCZQ/Zucai operator workflow

## 1. Problem statement

The current application exposes the ontology architecture more clearly than it serves
the operator. Its primary navigation is organized around command center, operations,
match investigation, ticket objects, review, calibration, ontology, and release
governance. The first viewport emphasizes readiness codes, object IDs, schema versions,
Action counts, hashes, and system health.

Those concepts are useful for engineering and audit, but they do not answer the daily
operator questions:

1. Which JCZQ day or Zucai issue needs attention now?
2. What has already been completed?
3. What requires Jun's judgment at this moment?
4. Which evidence and ticket impact matter to that judgment?
5. What single action advances the workflow?
6. What ticket, confirmation, ledger entry, result, or calibration followed?

The data disconnect is observable in the current production state. The 2026-08-28
command-center response contains 15 matches, all classified as blocked, and 45 alerts.
At the same time, issue 26112 has a current issue file, a 14-match prep snapshot, an rx
document, structured ticket candidates, predictions, and pending adjudications. The
product does not assemble those records into one issue-level task.

The result is technically inspectable but operationally unclear. Raw structures and
technical identifiers leak into normal use, while the actual issue workflow remains
implicit.

## 2. Product decision

Nutmeg becomes a phase-aware operator workbench.

The daily product uses two layers:

- **A: focused workbench** is the primary experience. It shows one current task, one
  current step, the business data required for that step, and one clear next action.
- **C: lightweight task entry** selects the most urgent active task at startup and
  provides a compact task switcher. It is not a dashboard and does not add a navigation
  step during normal use.

The product must open the most urgent actionable task automatically. When JCZQ and
Zucai are both active, selection is deterministic and based on workflow state and time,
never football judgment.

Ontology browsing, operations, calibration administration, and release governance
remain available under a secondary **System maintenance** entry. They do not occupy the
primary navigation or first viewport.

## 3. Product principles

### 3.1 Show operator meaning, preserve technical truth

The default UI presents business concepts: issue, day, match, kickoff, evidence,
probability movement, prescription, candidate ticket, audit finding, funding cap,
confirmation, ledger status, result, and review item.

Technical truth remains available, but it is progressive disclosure:

- source and freshness details are available under **Evidence and sources**;
- Action history, object versions, IDs, hashes, and correlation IDs are available under
  **Audit evidence**;
- raw API responses and ontology exploration remain in System maintenance;
- raw JSON is never rendered directly in a normal workflow view.

### 3.2 One current action

Each page state has one primary action. Secondary actions may inspect evidence, switch
tasks, return to the prior editable state, or open maintenance details. They may not
compete visually with the action that advances the current workflow.

The current action must state its result, for example:

- `Save judgment and continue to match 5`;
- `Use ticket version and start audit`;
- `Record deployment adjudication and request confirmation`;
- `Resend Telegram confirmation`;
- `Confirm actual placement and add ledger entry`;
- `Grade the next prediction`.

### 3.3 No hidden judgment

The application may collect facts, validate structure, perform deterministic arithmetic,
derive workflow state, and report policy results. It may not infer a probability change,
select faces, choose a ticket version, interpret whether a falsifier fired, decide to
place a ticket, or adjudicate an outcome.

Any control that records one of those choices is explicitly presented as Jun's action
and is committed through the relevant typed Action with `judge_operator` authority.

### 3.4 Do not bias toward no-ticket

The product does not present empty position as the default or safest generic choice.
Deployment reporting starts from the viable ticket structures and shows deterministic
comparisons. Empty position enters the primary choice set only when Jun has explicitly
adjudicated the inputs as materially indistinguishable or the deployment gate explicitly
fails. Software never decides that a match is "all dice."

The UI reports the gate and the consequences of `keep`, `drop-match reduction`,
`change structure`, or `empty position`; it never chooses among them.

## 4. Operator journey

### 4.1 Startup and task selection

`GET /` resolves the current task and redirects or renders it directly. A compact task
switcher in the header shows other active items without replacing the current workbench.

The selector ranks tasks using this stable tuple:

1. tasks awaiting a human action before a deadline;
2. overdue placement or ledger confirmations requiring explicit resolution;
3. other actionable tasks ordered by earliest deadline or kickoff;
4. settled tasks awaiting review;
5. waiting tasks ordered by the next expected retry time;
6. completed tasks, which do not auto-open.

Within the same category, lane, business key, and stable task ID break ties. Deadline
resolution uses, in order, the protected ticket deadline, official sale stop, and
earliest unresolved kickoff. A missing deadline is displayed as unknown and sorts after
known deadlines in the same category; it never silently invents a cutoff. The algorithm
does not inspect odds direction, predicted value, confidence, or ticket EV.

If there is no actionable task, the page says what is currently waiting, what source or
event is required, and when the next deterministic refresh is expected. It does not fill
the screen with unrelated historical matches.

### 4.2 Focused match judgment

The primary judgment state contains:

- issue/day, lane, deadline, current progress, match number, teams, competition, and
  kickoff;
- latest market distribution and movement in percentage points;
- current fair or belief distribution, when a committed revision exists;
- official availability and confirmed structural evidence;
- relevant flags, audit constraints, named rule IDs, and evidence freshness;
- current prescription and the impact of the available choice on candidate tickets;
- a human control to select faces, cite a named rule, and provide a reason;
- one primary action: save the judgment and move to the next unresolved match.

The page does not display `match_id`, `forecast_revision_id`, source retrieval IDs, raw
claims, or JSON payloads by default. Each summarized evidence statement links to a
formatted source record.

### 4.3 Ticket construction

After all required judgments are recorded, the same workbench advances to ticket
construction. It displays version rows rather than serialized ticket documents.

Each version includes:

- singles, doubles, full covers, and dropped matches in operator notation;
- bet count and price;
- `P(all correct)`;
- expected broken legs;
- shared dead faces across the selected ticket set;
- differences from the prescription and the named rule for every deviation;
- funding-cap usage and any required operator adjudication.

The optimizer and ticket arithmetic use the existing deterministic domain modules. The
browser performs no probability, price, or coverage calculations.

The operator selects a version. The product does not recommend or rank versions based on
football judgment.

### 4.4 Audit and deployment

The audit state translates each machine result into an operator-readable finding:

- severity and code;
- affected match or ticket field;
- the violated named rule;
- business impact;
- the next permitted action.

The page shows leg audit, prescription-diff registration, funding-cap usage, median
payout multiple, and deployment-gate state. PASS, WARN, and ERROR retain their existing
exit-code and policy meaning.

WARN requires the existing adjudication path where applicable. ERROR remains blocked
unless the explicitly authorized `--user-override` flow converts it to an
`evidence_rejected` Adjudication. The UI does not create a second override mechanism.

After the operator records the deployment adjudication, the primary action submits the
approved ticket artifact to the protected confirmation flow. It does not place a ticket.

### 4.5 Confirmation and ledger

The confirmation state shows three distinct facts:

1. ticket and amount are frozen by the first protected step;
2. personal Telegram confirmation is open, with its exact expiry;
3. actual placement and ledger entry are either absent or recorded.

Only Jun can invoke `ConfirmDispatch`. AI actors never receive that Action. A placement
is not treated as real until the actual amount and receipt are confirmed and the ledger
Action commits.

At the deadline, an unconfirmed ticket is deterministically marked shadow through the
existing protected action. The page says `Not confirmed; treated as not placed` instead
of exposing the shadow payload.

### 4.6 Settlement and review

When authoritative results are available, the workbench shows:

- hit count, payout, stake, and P/L;
- broken legs and ticket-version context;
- reconciliation state;
- the night-calibration summary;
- pending factor verdicts, prediction grades, and adjudications.

The next unresolved review item becomes the one current action. The page provides
evidence and allowed outcomes, but interpretation and grade remain with
`judge_operator`.

## 5. Workflow state model

### 5.1 Task identity

An operator task is a read-model concept, not a new source of truth.

```text
task_id      = <lane>:<business_key>
lane         = jczq | zucai
business_key = Shanghai date for JCZQ | official issue number for Zucai
```

The initial state enum is:

```text
waiting_data
prepare
judge_matches
construct_ticket
audit_deployment
await_confirmation
await_ledger
await_result
review
complete
blocked
```

The state resolver is a pure function over a versioned task snapshot. It checks the
presence, status, and timestamps of formal facts. It does not inspect narrative meaning.

### 5.2 Phase transitions

```text
waiting_data -> prepare -> judge_matches -> construct_ticket
             -> audit_deployment -> await_confirmation -> await_ledger
             -> await_result -> review -> complete
```

Any phase may become `blocked` when a hard prerequisite fails. A blocked task carries a
stable reason code and a permitted recovery action. When the prerequisite becomes valid,
the resolver returns the corresponding normal phase without a manual status edit.

JCZQ and Zucai use the same public states but lane-specific resolvers and step views.
This avoids forcing two workflows into one internal implementation while preserving one
operator interaction model.

### 5.3 Progress

Progress is counted from formal records, not service return values or generated report
text. For example, `3 / 14 judgments recorded` is reconciled against committed ontology
rows or Actions. A failed or rejected write cannot increase progress.

## 6. Data and authority

### 6.1 Read sources

The workbench product contract is assembled from:

- ontology repositories and Action history;
- analytics and scoreboard projections, while respecting `scoreboard.json` as the
  shadow-period authority;
- existing deterministic decision services for audit, optimizer, deployment arithmetic,
  official results, and calibration;
- a narrow validated operational-artifact repository for current Zucai issue, prep, rx,
  candidate ticket, and ledger documents that have not yet been fully objectified.

The operational-artifact repository is a transitional read adapter. It uses explicit
Pydantic/domain contracts, rejects unknown or malformed shapes, and returns typed
business values. Templates and JavaScript cannot read those files or receive arbitrary
dicts. No artifact write is added through this adapter.

This bridge is required because current issue-level operator data is real and relevant,
but parts of it remain outside the ontology. As additional fields become typed objects,
the adapter can be replaced behind the unchanged workbench contract.

### 6.2 Write authority

All state-changing controls call existing or explicitly added typed Action handlers.
The workbench does not shell out to the Typer CLI, edit rx JSON, append directly to a
ledger file, execute SQL, or change `scoreboard.json`.

If a requested workflow step has no governed Action, that control remains read-only
until an Action is designed and tested. The implementation must not hide an ad hoc file
write behind a web button.

### 6.3 Information cutoffs

Every task snapshot carries `as_of`, source freshness, and the information cutoff used
for each forecast or audit. Historical views apply existing cutoff rules. The current
task may refresh, but a submitted judgment or ticket binds to the versions shown when
the form was opened and uses optimistic concurrency checks.

## 7. Product architecture

```text
Server-rendered focused workbench
        |
OperatorWorklistQuery + OperatorTaskQuery
        |
Lane resolvers and typed step presenters
        |
+--------------------------+--------------------------+
| Ontology/Product reads   | Validated artifact reads |
| Actions, evidence,       | issue, prep, rx, ticket,  |
| tickets, settlements     | ledger, calibration       |
+--------------------------+--------------------------+
        |
Existing deterministic domain services

Mutations:
browser form -> Product Action/Ticket gateway -> typed Action -> ontology/outbox
```

### 7.1 Product contracts

Add versioned DTO families with business fields rather than exposing ontology DTOs:

- `OperatorWorklistResponse`;
- `OperatorTaskSummary`;
- `OperatorTaskResponse`;
- `TaskProgressSummary`;
- one typed `StepView` variant for each public state;
- `BusinessEvidenceSummary`;
- `TicketVersionSummary`;
- `AuditReportSummary`;
- `ConfirmationStatusSummary`;
- `ReviewItemSummary`;
- `OperatorRecoverySummary`.

The top-level response includes a discriminated `step.kind`. A template never switches
on arbitrary properties or renders a generic mapping.

Technical references may exist in a separate `AuditEnvelope`; the normal view receives
only formatted labels and stable drill-down links.

### 7.2 Query services

`OperatorWorklistQuery` discovers active tasks, applies deterministic priority, and
returns the selected task plus alternatives.

`OperatorTaskQuery` builds a versioned task snapshot and delegates phase resolution to
the lane resolver. Each resolver produces exactly one typed step view.

Business presentation functions format probabilities, money, deadlines, source age,
and face notation on the server. They do not parse narrative strings to recover facts.

### 7.3 Action services

The workbench reuses the current `ProductActionGateway`, `ProductTicketService`, and
protected ticket Actions. New handlers are allowed only for a named workflow mutation
that is already authorized by the SOP and has a typed domain request.

Actor identity and role are assigned by the local server session. They are not accepted
from browser payloads. Every mutation includes an idempotency key and expected versions
where applicable.

### 7.4 Web routes

The primary routes are:

| Route | Purpose |
| --- | --- |
| `GET /` | Resolve and render the highest-priority task |
| `GET /tasks` | Compact active-task list, not a dashboard |
| `GET /tasks/{task_id}` | Render the current phase for one task |
| `POST /tasks/{task_id}/actions/{action}` | Submit one governed workflow action |
| `GET /tasks/{task_id}/evidence/{ref}` | Formatted evidence detail |
| `GET /system` | Secondary maintenance index |

The existing versioned APIs remain available for engineering consumers. Existing pages
move under `/system/...` or redirect there; their contracts are not silently repurposed.

## 8. Visual and interaction design

The application is quiet, compact, and optimized for repeated operational use.

- The first viewport identifies the issue/day, deadline, progress, current match or
  ticket, required evidence, and primary action.
- The task switcher is compact and ordered by urgency. It never becomes a grid of
  decorative cards.
- The workflow timeline is informational. The user does not need to select phases.
- Business tables use stable columns and responsive horizontal handling.
- Buttons use clear command labels; icon-only controls use the existing icon library or
  Lucide where available and include tooltips.
- PASS, WARN, ERROR, waiting, and completed states differ by label and icon as well as
  color.
- Mobile places evidence before the action form and keeps the primary action reachable
  without overlaying content.
- IDs, hashes, schema, outbox, Action counts, and connection state are removed from the
  global header.
- No normal-workflow template contains `<pre>` output or generic JSON rendering.

## 9. Error and waiting states

Every blocked, failed, or waiting state answers four questions:

1. What is missing or failed?
2. What workflow result does it prevent?
3. What can Jun do now?
4. When or how can the task be retried?

The public error model contains a stable business code, title, explanation, recovery
action, retryability, and optional correlation ID. Tracebacks, SQL errors, source
payloads, and Action payloads remain in audit logs.

Examples:

- `odds_snapshot_stale`: show source age and the next fetch action;
- `identity_unresolved`: name the affected match and link to maintenance resolution;
- `ticket_audit_blocked`: show findings and return to the ticket edit state;
- `confirmation_expired`: issue a fresh first-stage confirmation;
- `ledger_confirmation_missing`: request actual placement confirmation or mark not
  placed;
- `projection_stale`: offer the governed build-only projection rebuild operation.

Unexpected failures render a correlation ID and preserve the task context. They do not
drop the operator into a generic system-health page.

## 10. Safety and governance invariants

- Probability interpretation, face selection, ticket selection, falsifier interpretation,
  grade, and adjudication remain human/AI conversation work, never deterministic UI
  policy.
- The browser cannot invoke an Action outside the explicit product whitelist.
- AI roles cannot invoke `ConfirmDispatch`, protected placement, grade, adjudication,
  ReleaseApproval, cutover, or launchd controls.
- Real placement requires the existing two-stage protected flow and a bound artifact,
  amount, expiry, nonce, and receipt.
- `scoreboard.json` remains the shadow-period authority. The workbench may display its
  governed projection and add observations through `scoreboard observe`; it does not
  rewrite the file.
- The application does not restore disabled decision-chain launchd jobs.
- The application does not automate ticket placement or betting.

## 11. Testing and acceptance

### 11.1 Unit coverage

- task discovery, stable ordering, and all priority ties;
- each lane's state transitions and hard blocks;
- progress reconciled from committed records rather than service return counts;
- validated artifact parsing, missing fields, unknown versions, and malformed data;
- business presentation for probabilities, money, deadlines, face notation, and source
  freshness;
- no-ticket visibility only after a recorded operator indistinguishability adjudication
  or deployment failure;
- public error-to-recovery mapping;
- role and Action-whitelist enforcement.

### 11.2 Integration coverage

- production-shaped 26112 replay resolves to the correct active issue and step;
- JCZQ and Zucai simultaneous tasks choose the nearest actionable deadline;
- judgment, ticket, audit, confirmation, ledger, settlement, and review transitions
  observe committed facts after each action;
- rejected or failed Actions do not advance progress;
- protected confirmation cannot be invoked by AI and expires safely;
- unconfirmed deadline path becomes shadow and never becomes a ledger placement;
- System maintenance pages remain reachable without dominating primary navigation.

### 11.3 Browser coverage

Playwright exercises desktop and mobile viewports for:

- automatic task selection and task switching;
- judgment through next-match progression;
- ticket comparison, audit report, and return-to-edit behavior;
- Telegram waiting, confirmation expiry, and ledger completion;
- settlement and review progression;
- waiting, blocked, empty, stale, conflict, and unexpected-error states;
- absence of exposed raw JSON, internal IDs, schema, hashes, and overlapping text;
- keyboard navigation, focus state, labels, and readable status distinctions.

### 11.4 Regression coverage

Implementation must pass the relevant focused tests, ruff, compileall, the repository
pre-commit hooks, and the full existing suite. Decision-domain changes additionally run
the Nutmeg `verify` recipe with current snapshots. A local server is kept running after
implementation for Jun's real acceptance test.

## 12. Rollout

The reshape is delivered in vertical slices so each slice is usable and testable:

1. worklist, deterministic phase resolver, focused shell, and meaningful waiting states;
2. Zucai issue/judgment view over validated current data;
3. ticket construction and audit/deployment views;
4. confirmation and ledger views;
5. settlement/review view and maintenance relocation;
6. responsive/browser verification and production-shaped replay.

The old product pages remain under System maintenance during the transition. `/` moves
to the focused workbench only after the worklist and waiting state have production-shaped
tests; there is no interval where the root route is blank or misleading.

## 13. Explicit exclusions

- new football judgment or recommendation engines;
- new external data providers or WAF bypass work;
- automated face selection, ticket selection, ticket placement, or betting;
- scoreboard cutover, soak entry, ReleaseApproval, or launchd reactivation;
- constitution changes;
- C7 rule resolution;
- public deployment, multi-user permissions, subscriptions, or cloud synchronization;
- removal of ontology/API audit access;
- direct migration of all historical rx prose in this package.

## 14. Success criteria

The reshape is successful when Jun can open Nutmeg and, without knowing ontology types,
Action names, CLI commands, or JSON structure:

1. land on the most urgent current JCZQ/Zucai task;
2. understand why that task is current;
3. see the evidence and ticket impact required for the current decision;
4. record the permitted human action and advance automatically;
5. follow the same task through ticket, audit, Telegram confirmation, ledger, settlement,
   and review;
6. inspect technical evidence only when deliberately requested;
7. verify that no software component made a football judgment or confirmed placement on
   the operator's behalf.
