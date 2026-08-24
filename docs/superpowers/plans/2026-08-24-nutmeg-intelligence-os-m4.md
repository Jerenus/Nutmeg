# Nutmeg Intelligence OS M4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the ontology-backed Ticket and Adjudication Workbench with authoritative server-side composition/audit, immutable ticket artifacts, and protected per-ticket manual confirmation.

**Architecture:** Add an immutable pre-booking model beside the existing legacy Express facade. New typed Actions create/revise/approve audited batches, issue digest-only confirmation challenges, and atomically turn one confirmed artifact into the existing Ticket/BetLeg/CashTransaction model; all composition and C0-C7 behavior delegates to the current deterministic functions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy Core, SQLite WAL, immutable SHA-256 CAS, Jinja2 SSR, progressive JavaScript, pytest, Ruff, browser verification.

**Design Spec:** `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-m4-design.md`

**Execution note:** Repository instructions prohibit subagents. Execute this plan inline in the current dedicated worktree, one RED-GREEN-REFACTOR slice at a time. Prefix every `uv`, pre-commit, and hook invocation with `UV_FROZEN=1`.

---

## Scope and locked decisions

- M1-M3 are closed and may change only for an M4 integration point or a proven regression.
- Migration 12 is additive. Existing migration fingerprints and applied migrations never change.
- `compose_tickets()` and `audit_legs()` are imported and called; their logic is not copied.
- The formal product never invokes legacy `ExpressService` before confirmation.
- Legacy `decision-close` keeps immediate booking behavior through M4.
- New protected Actions are judge-only; no browser payload can supply an actor role.
- Receipt bytes are absent from Action payload JSON, outbox events, logs, and product reads.
- No live connector, dispatch, provider fetch, Telegram, scheduler, funds transfer, or production write is allowed in implementation or verification.
- `.nutmeg-data/scoreboard.json` remains untouched and authoritative until M5.

## File structure

### New production files

- `nutmeg/ontology/tickets/__init__.py`: stable protected-ticket exports.
- `nutmeg/ontology/tickets/models.py`: immutable batch, artifact, challenge, placement, input, and result value objects.
- `nutmeg/ontology/tickets/composition.py`: adapter into authoritative composition and C0-C7 functions plus canonical artifact bytes.
- `nutmeg/ontology/repository/schema_tickets.py`: migration-12 typed tables only.
- `nutmeg/ontology/repository/tickets.py`: protected-ticket persistence and optimistic revision queries.
- `nutmeg/ontology/finance/booking.py`: shared atomic Ticket/BetLeg/stake row writer used by legacy and protected paths.
- `nutmeg/ontology/actions/protected_ticket_actions.py`: Create/Remove/Approve/Issue/Confirm typed Actions.
- `nutmeg/product/tickets.py`: product request orchestration and connector port; no arithmetic.
- `nutmeg/interfaces/web/templates/product/tickets.html`: workbench and protected confirmation surface.
- `docs/nutmeg-intelligence-os-m4-operations.md`: authority, recovery, and no-live-dispatch runbook.

### Existing production files modified

- `nutmeg/ontology/repository/migrations.py`: append migration 12 and judge-only permissions.
- `nutmeg/ontology/repository/unit_of_work.py`: expose `.tickets` repository.
- `nutmeg/ontology/actions/ticket_actions.py`: delegate existing booking rows to the shared helper without changing public behavior.
- `nutmeg/ontology/kernel.py`: expose ProtectedTicketActions and M4 counts.
- `nutmeg/ontology/wiring.py`: wire CAS, ActionService, UoW, and ProtectedTicketActions.
- `nutmeg/product/contracts.py`: strict M4 DTOs.
- `nutmeg/product/repository.py`: workbench, batch, artifact, warning-Adjudication, quote, and placement reads.
- `nutmeg/product/queries.py`: assemble M4 DTOs without raw table leakage.
- `nutmeg/product/wiring.py`: wire ProductTicketService with no connector by default.
- `nutmeg/interfaces/product_api.py`: M4 query/mutation routes and stable error mapping.
- `nutmeg/interfaces/product_ui.py`: `/tickets` route.
- `nutmeg/interfaces/web/templates/product/layout.html`: Ticket Workbench navigation entry.
- `nutmeg/interfaces/web/static/product/app.js`: session-backed M4 forms and receipt encoding only.
- `nutmeg/interfaces/web/static/product/app.css`: responsive M4 states using existing tokens.
- `.pre-commit-config.yaml`: existing product/ontology hooks already cover these paths; change only if a missing path is proven.

### Tests and evidence

- `tests/ontology/test_m4_ticket_migration.py`
- `tests/ontology/test_ticket_composition.py`
- `tests/ontology/test_protected_ticket_actions.py`
- `tests/ontology/test_ticket_confirmation.py`
- `tests/product/test_m4_contracts.py`
- `tests/product/test_m4_queries.py`
- `tests/product/test_m4_api.py`
- `tests/product/test_m4_ui.py`
- `tests/product/test_m4_e2e.py`
- `docs/superpowers/evidence/m4/` browser screenshots created only during final verification.

## Task 1: Authoritative composition adapter and strict M4 value objects

**Files:**
- Create: `nutmeg/ontology/tickets/__init__.py`
- Create: `nutmeg/ontology/tickets/models.py`
- Create: `nutmeg/ontology/tickets/composition.py`
- Test: `tests/ontology/test_ticket_composition.py`

- [x] **Step 1: Write failing delegation, normalization, empty-slate, and hash tests**

Create tests that construct one `TicketLegDraft` with explicit audit facts and monkeypatch
the imported authoritative functions:

```python
def test_compose_batch_calls_authoritative_functions(monkeypatch):
    calls = []
    monkeypatch.setattr(composition, "compose_tickets", lambda legs, budget, **kw: (
        calls.append(("compose", legs, kw)) or {
            "channel": "jczq", "period_cap_yuan": 400,
            "total_stake_yuan": 100, "scaled": False, "n_tickets": 1,
            "tickets": [{"ticket_id": "T-1", "bucket": "main",
                         "budget_bucket": "had_modal", "structure": "single",
                         "stake_yuan": 100, "combined_odds": 2.1, "n_legs": 1,
                         "computed_hit_prob": None, "legs": [LEG.express_dict()]}],
            "by_bucket": {"main": {"cap": 100, "stake": 100, "n_tickets": 1}},
        }
    ))
    monkeypatch.setattr(composition, "audit_legs", lambda legs: (
        calls.append(("audit", legs)) or []
    ))

    result = composition.compose_batch([LEG], channel="jczq", made_at=AT)

    assert [call[0] for call in calls] == ["compose", "audit"]
    assert result.total_stake_yuan == 100
```

Also assert:

- empty input returns zero tickets/findings and `is_empty is True`;
- normalized findings preserve level/code/match/message/since;
- one material field change changes canonical SHA-256;
- mapping key order does not change canonical SHA-256;
- `TicketLegDraft` rejects naive deadlines, invalid faces, odds `<=1`, probability
  distributions not summing to one within tolerance, and blank committed revision IDs.

- [x] **Step 2: Run the focused test and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_composition.py -q`

Expected: collection fails because `nutmeg.ontology.tickets` does not exist.

- [x] **Step 3: Implement immutable models and the thin adapter**

Define frozen/slotted `TicketLegDraft`, `AuditFindingRecord`, `ComposedTicket`, and
`BatchComposition`. `TicketLegDraft.express_dict()` returns only the legacy express
shape; `.audit_leg()` returns the existing `Leg`. `compose_batch()` must be equivalent
to:

```python
summary = compose_tickets(
    [leg.express_dict() for leg in legs],
    budget or load_budget(),
    channel=channel,
    made_at=made_at,
    store=None,
)
findings = audit_legs([leg.audit_leg() for leg in legs])
```

Normalize the summary into immutable models. Canonical bytes use `canonical_json()`;
SHA-256 is computed over those bytes. Do not add fallback arithmetic.

- [x] **Step 4: Run focused tests and Ruff**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_composition.py tests/decision/test_express.py tests/decision/test_legs_audit.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/tickets tests/ontology/test_ticket_composition.py
```

Expected: all pass; authoritative decision tests remain unchanged.

- [x] **Step 5: Commit Task 1**

```bash
UV_FROZEN=1 git add nutmeg/ontology/tickets tests/ontology/test_ticket_composition.py
UV_FROZEN=1 git commit -m "feat(ontology): adapt authoritative ticket composition"
```

## Task 2: Migration 12 and protected-ticket repository

**Files:**
- Create: `nutmeg/ontology/repository/schema_tickets.py`
- Create: `nutmeg/ontology/repository/tickets.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Test: `tests/ontology/test_m4_ticket_migration.py`

- [x] **Step 1: Write failing migration, permission, immutability, and revision tests**

Assert migration 12 creates exactly the four tables declared by the design and seeds
only judge permissions:

```python
PROTECTED = {
    "create_ticket_batch", "remove_ticket_leg", "approve_ticket_batch",
    "issue_ticket_confirmation", "confirm_ticket_placement",
}

def test_migration_12_adds_protected_ticket_schema(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    report = run_migrations(engine)
    assert report.applied_versions[-1] == 12
    assert {"ticket_batch_revisions", "audited_ticket_artifacts",
            "ticket_confirmation_challenges", "ticket_placements"} <= set(
        inspect(engine).get_table_names()
    )
    with engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {(row["action_type"], row["actor_role"]) for row in rows}
    assert {(action, "judge_operator") for action in PROTECTED} <= seeded
    assert not {(action, "ai_analyst") for action in PROTECTED} & seeded
```

Repository tests must prove monotonic revisions, current-revision lookup, stale expected
version rejection, exact JSON round-trip, immutable inserts, challenge lookup/consume,
single placement per artifact, and all foreign keys.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_m4_ticket_migration.py -q`

Expected: current schema version is 11 and protected tables are absent.

- [x] **Step 3: Declare schema and append migration 12**

Declare the four tables exactly as the design spec, including self-FK, account,
SourceArtifact, ArtifactRetrieval, Action, Ticket, and uniqueness constraints. Append,
never edit, migration 12:

```python
Migration(
    version=12,
    name="protected_ticket_workbench",
    fingerprint=(
        "ticket_batch_revisions+audited_ticket_artifacts+"
        "ticket_confirmation_challenges+ticket_placements+judge_only_permissions"
    ),
    apply=_apply_protected_tickets,
)
```

Create tables in FK order and seed the five judge-only permissions.

- [x] **Step 4: Implement repository rows and methods**

Provide typed rows and these exact operations:

```text
insert_batch_revision(row)
batch_revision(revision_id)
current_batch_revision(batch_id)
assert_current_revision(batch_id, expected_revision_no)
insert_ticket_artifact(row)
ticket_artifacts_for_revision(revision_id)
ticket_artifact(artifact_id)
insert_confirmation(row)
confirmation(confirmation_id)
consume_confirmation(confirmation_id, consumed_at, action_id)
invalidate_open_confirmations(ticket_artifact_id, consumed_at, action_id)
insert_placement(row)
placement_for_artifact(ticket_artifact_id)
batch_history(batch_id)
count_batches() / count_artifacts() / count_placements()
```

Use canonical JSON and fail loudly on malformed persisted data.

- [x] **Step 5: Run migration/repository and all migration regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_m4_ticket_migration.py tests/ontology/test_migrations.py tests/ontology/test_schema_finance_migration.py tests/ontology/test_m3_workflow_migration.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/repository tests/ontology/test_m4_ticket_migration.py
```

Expected: all pass; migration sequence is 1-12 with no drift.

- [x] **Step 6: Commit Task 2**

```bash
UV_FROZEN=1 git add nutmeg/ontology/repository tests/ontology/test_m4_ticket_migration.py
UV_FROZEN=1 git commit -m "feat(ontology): add protected ticket persistence"
```

## Task 3: Create/remove batch Actions and server-side identity validation

**Files:**
- Create: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/kernel.py`
- Modify: `nutmeg/ontology/wiring.py`
- Test: `tests/ontology/test_protected_ticket_actions.py`

- [ ] **Step 1: Write failing Create/Remove Action tests**

Seed one Match, current committed Forecast, account, selection, and quote. Tests must
prove:

- Create writes revision 1, CAS SourceArtifact, committed Action, and outbox event;
- input Forecast must be the current committed revision;
- quote must match selection/match/market, be active, and have the same booking odds;
- AI Create and Remove return rejected without business rows;
- Remove creates revision 2 and leaves revision 1 unchanged;
- stale expected revision is rejected with `OptimisticConcurrencyError`;
- removing an absent leg fails;
- removing the final leg produces `empty` with zero composition tickets;
- identical idempotent replay creates no duplicate revision or CAS metadata.

Use a helper request with the exact fields from `TicketLegDraft`; do not mock the
authoritative functions in Action tests.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_protected_ticket_actions.py -q -x`

Expected: import failure for `ProtectedTicketActions`.

- [ ] **Step 3: Implement request/result contracts and CreateTicketBatch**

Define `CreateTicketBatchRequest`, `RemoveTicketLegRequest`, and `TicketBatchResult`.
The Action handler must validate account, current Forecast, selection, quote, and
deadline inside the same UoW, call `compose_batch()`, publish canonical bytes to CAS,
upsert SourceArtifact, and insert the revision with the accepted Action ID. Action JSON
stores hashes and identifiers, never full receipt/source bytes.

- [ ] **Step 4: Run the Create tests and verify GREEN**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_protected_ticket_actions.py -q -k 'create or ai'`

Expected: selected tests pass.

- [ ] **Step 5: Add RemoveTicketLeg under a fresh failing stale-version test**

Resolve the current revision in the handler, compare `expected_revision_no`, address a
leg by deterministic leg key, remove exactly one, and insert the next immutable
revision. Never update prior JSON/state.

- [ ] **Step 6: Run full Task 3 tests and regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_protected_ticket_actions.py tests/ontology/test_action_outbox.py tests/ontology/test_commit_forecast.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/tickets tests/ontology/test_protected_ticket_actions.py
```

Expected: all pass.

- [ ] **Step 7: Commit Task 3**

```bash
UV_FROZEN=1 git add nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py tests/ontology/test_protected_ticket_actions.py
UV_FROZEN=1 git commit -m "feat(ontology): govern ticket batch revisions"
```

## Task 4: WARN Adjudication and immutable batch approval

**Files:**
- Modify: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/repository/tickets.py`
- Modify: `nutmeg/product/repository.py`
- Test: `tests/ontology/test_protected_ticket_actions.py`

- [ ] **Step 1: Add failing ERROR/WARN/approval tests**

Build one batch with C1 ERROR and assert approval fails with no approved revision or
artifact. Build a C6/C7 WARN batch and assert it fails until an existing Adjudication
has:

```python
subject_type="ticket_audit_finding"
subject_id=warning.finding_id
decision="accept_warning"
reason="operator accepts this disclosed residual risk"
evidence_rejected=[{"object_type": "claim", "object_id": "claim-1"}]
```

Then assert approval writes the next immutable `approved` revision, one CAS artifact
per authoritative composed ticket, and no formal Ticket or ledger debit. Add an empty
batch test proving `approved_empty`, zero artifacts, zero Tickets, and zero cash rows.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_protected_ticket_actions.py -q -k approve`

Expected: missing `approve_ticket_batch` behavior.

- [ ] **Step 3: Implement stable finding IDs and Adjudication lookup**

Finding IDs use SHA-256 over revision ID, level, code, match number, and message with
prefix `taf-`. Add a repository read that returns the latest Adjudication for exact
subject type/id. It must not accept an Adjudication from a superseded revision.

- [ ] **Step 4: Implement ApproveTicketBatch**

Reject ERROR before CAS writes. Require all current WARN findings to resolve to
`accept_warning`. Insert an approved/approved-empty revision. For each composed ticket,
construct canonical artifact JSON, publish to CAS, register SourceArtifact, and insert
the artifact row. Return batch revision first, then artifacts. Do not call Express and
do not write finance rows.

- [ ] **Step 5: Run approval, workflow, and finance regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_protected_ticket_actions.py tests/ontology/test_workflow_actions.py tests/ontology/test_ticket_actions.py tests/ontology/test_express_flow.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/repository/tickets.py
```

Expected: all pass; legacy approval still debits exactly once, protected approval does not.

- [ ] **Step 6: Commit Task 4**

```bash
UV_FROZEN=1 git add nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/repository/tickets.py nutmeg/product/repository.py tests/ontology/test_protected_ticket_actions.py
UV_FROZEN=1 git commit -m "feat(ontology): approve immutable audited tickets"
```

## Task 5: Protected confirmation, receipt, and atomic booking

**Files:**
- Create: `nutmeg/ontology/finance/booking.py`
- Modify: `nutmeg/ontology/actions/ticket_actions.py`
- Modify: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/tickets/models.py`
- Test: `tests/ontology/test_ticket_confirmation.py`
- Test: `tests/ontology/test_ticket_actions.py`

- [ ] **Step 1: Write failing confirmation security and recovery tests**

Tests must prove:

- issue returns a plaintext nonce but DB stores only its SHA-256;
- AI cannot issue or confirm;
- challenge binds artifact hash, exact amount, currency, and channel;
- lifetime is five minutes under an injected aware clock;
- malformed, mismatched, expired, or consumed nonce writes no Ticket/cash/placement;
- manual confirm requires reference, receipt bytes, and content type;
- success writes one Ticket, all BetLegs, one negative stake transaction, receipt
  SourceArtifact/Retrieval, placement, and challenge consumption atomically;
- same-key duplicate returns the same Ticket and one debit;
- different-key duplicate with consumed nonce fails and still has one debit;
- restart after issuance can consume the durable challenge;
- Forecast revision change after approval blocks confirmation;
- injected failure after business-row insertion rolls back every database row;
- no default connector is callable; fake connector cannot be selected by a client actor.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_confirmation.py -q -x`

Expected: confirmation request/service objects are missing.

- [ ] **Step 3: Extract the shared atomic booking helper under legacy characterization tests**

First add assertions to `tests/ontology/test_ticket_actions.py` for exact refs, Ticket
status, BetLeg count, ledger amount, and idempotent replay. Then implement:

```python
def book_ticket_rows(
    uow, *, channel: str, account_id: str, proposal_id: str | None,
    legs: list[LegInput], at: str, stake_idempotency_key: str,
) -> tuple[str, tuple[str, ...], str | None]:
    ...
```

It validates current Forecasts and budget, writes current finance rows, and returns IDs.
Legacy `TicketActions.approve_ticket()` calls it with unchanged semantics.

- [ ] **Step 4: Run legacy characterization and verify GREEN**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_actions.py tests/ontology/test_express_flow.py tests/decision/test_close_settle_adapter.py -q`

Expected: all pass with no output contract changes.

- [ ] **Step 5: Implement IssueTicketConfirmation**

Generate at least 32 random bytes with `secrets.token_urlsafe`, store only SHA-256, bind
all displayed fields, and persist through a judge-only Action. Return a typed result
containing ActionOutcome, confirmation ID, plaintext nonce, and expiry. Never put the
nonce in Action payload or outbox result refs.

- [ ] **Step 6: Implement ConfirmTicketPlacement**

Use `hmac.compare_digest`, exact decimal-safe amount comparison in integer fen, injected
clock, current Forecast validation, and the shared booking helper. Manual receipt bytes
go through the existing CAS; the Action payload contains receipt hash/size/type only.
Register `source_name="manual-ticket-receipt"` and one deterministic Retrieval. Insert
placement and consume all open challenges only after finance writes succeed in the same
transaction.

- [ ] **Step 7: Run confirmation and full finance regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_confirmation.py tests/ontology/test_ticket_actions.py tests/ontology/test_express_flow.py tests/ontology/test_reconcile_flow.py tests/ontology/test_odds_faithful_settlement.py tests/analytics/test_integrity_action.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/finance/booking.py tests/ontology/test_ticket_confirmation.py
```

Expected: all pass; ledger conservation and legacy settlement remain intact.

- [ ] **Step 8: Commit Task 5**

```bash
UV_FROZEN=1 git add nutmeg/ontology/finance/booking.py nutmeg/ontology/actions/ticket_actions.py nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/tickets/models.py tests/ontology/test_ticket_confirmation.py tests/ontology/test_ticket_actions.py
UV_FROZEN=1 git commit -m "feat(ontology): protect ticket placement confirmation"
```

## Task 6: Strict product contracts and workbench queries

**Files:**
- Create: `nutmeg/product/tickets.py`
- Modify: `nutmeg/product/contracts.py`
- Modify: `nutmeg/product/repository.py`
- Modify: `nutmeg/product/queries.py`
- Modify: `nutmeg/product/wiring.py`
- Test: `tests/product/test_m4_contracts.py`
- Test: `tests/product/test_m4_queries.py`

- [ ] **Step 1: Write failing strict-contract tests**

Define fixtures and expected DTO JSON for:

- workbench eligible match with current committed Forecast and latest active quotes at
  `as_of`;
- no Forecast / no quote blocked rows with explicit reason;
- batch history with semantic added/removed/changed summary;
- approved artifact with hash/amount/deadline/placement state but no receipt bytes;
- strict mutation DTOs rejecting unknown fields, actor role, negative expected version,
  naive timestamps, invalid base64, or amount not representable as fen.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m4_contracts.py tests/product/test_m4_queries.py -q`

Expected: M4 contracts and queries are absent.

- [ ] **Step 3: Add strict DTOs**

Add `TicketWorkbenchResponse`, `TicketWorkbenchMatch`, `TicketSelection`,
`TicketBatchRevisionSummary`, `TicketBatchHistoryResponse`, `TicketArtifactDetail`,
`CreateTicketBatchCommand`, `RemoveTicketLegCommand`, `ApproveTicketBatchCommand`,
`IssueConfirmationCommand/Response`, and `ConfirmPlacementCommand`. All extend current
strict/versioned bases and expose only JSON-safe values.

- [ ] **Step 4: Add temporal repository reads**

Select current committed Forecast and latest quote per selection with SQLite
`julianday()` cutoffs, never lexical timestamp comparison. Add reads for batch history,
artifacts, placement, warning Adjudications, and exact object lookup. Stable ordering is
kickoff/match ID, revision number, and ticket index.

- [ ] **Step 5: Assemble Query Service and ProductTicketService**

The Query Service maps rows to DTOs and computes only display diffs, never domain
arithmetic. ProductTicketService parses DTOs into ontology requests, assigns actor from
the server, decodes receipt bytes, and delegates to ProtectedTicketActions. Its
connector dependency defaults to `None`.

- [ ] **Step 6: Run product and temporal regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m4_contracts.py tests/product/test_m4_queries.py tests/product/test_m3_queries.py tests/product/test_queries.py -q
UV_FROZEN=1 uv run ruff check nutmeg/product tests/product/test_m4_contracts.py tests/product/test_m4_queries.py
```

Expected: all pass; no future quote/Forecast leaks through `as_of`.

- [ ] **Step 7: Commit Task 6**

```bash
UV_FROZEN=1 git add nutmeg/product tests/product/test_m4_contracts.py tests/product/test_m4_queries.py
UV_FROZEN=1 git commit -m "feat(product): expose ticket workbench contract"
```

## Task 7: Protected M4 API and stable errors

**Files:**
- Modify: `nutmeg/interfaces/product_api.py`
- Modify: `nutmeg/product/errors.py`
- Test: `tests/product/test_m4_api.py`

- [ ] **Step 1: Write failing route/security/error tests**

Test all M4 GETs and POSTs. Every POST without session, CSRF, and exact Origin must be
403. Payload actor spoofing must be 422 because strict DTOs forbid it. Assert stable
status/code mappings for audit blocked, unadjudicated WARN, stale revision, deadline,
stale/reused/mismatched confirmation, already placed, missing receipt, connector absent,
not found, and idempotency conflict.

Also assert:

- OpenAPI contains all five POST and three GET routes;
- nonce appears only in the issue response;
- receipt base64 and nonce are absent from `/api/v1/actions` and `/api/v1/events`;
- confirmation responses carry formal Action and object references.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m4_api.py -q -x`

Expected: 404 for M4 routes.

- [ ] **Step 3: Implement dedicated routes through the existing security dependency**

All mutations use `Depends(require_mutation_session)` and server values:

```python
actor_id=services.settings.default_user_id
actor_role=ActorRole.JUDGE_OPERATOR
```

Do not add a second session or CSRF mechanism. Map typed ticket errors to the standard
`ProductError` envelope. Receipt decoding errors are 422; state conflicts are 409;
connector unavailable is 503; permission remains 403.

- [ ] **Step 4: Run API and security regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m4_api.py tests/product/test_m3_api.py tests/product/test_api.py -q
UV_FROZEN=1 uv run ruff check nutmeg/interfaces/product_api.py tests/product/test_m4_api.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 7**

```bash
UV_FROZEN=1 git add nutmeg/interfaces/product_api.py nutmeg/product/errors.py tests/product/test_m4_api.py
UV_FROZEN=1 git commit -m "feat(api): add protected ticket endpoints"
```

## Task 8: Ticket and Adjudication Workbench UI

**Files:**
- Create: `nutmeg/interfaces/web/templates/product/tickets.html`
- Modify: `nutmeg/interfaces/product_ui.py`
- Modify: `nutmeg/interfaces/web/templates/product/layout.html`
- Modify: `nutmeg/interfaces/web/static/product/app.js`
- Modify: `nutmeg/interfaces/web/static/product/app.css`
- Test: `tests/product/test_m4_ui.py`

- [ ] **Step 1: Write failing SSR and static-boundary tests**

Assert `/tickets?date=2026-08-24` returns the matrix, committed Forecast revision IDs,
server-provided odds, explicit empty state, audit panel, revision rail, artifact hashes,
and confirmation form. Assert HTML-escaped source/operator content.

Static tests must assert JavaScript calls M4 endpoints and handles receipt encoding,
but does not contain names/formulas for `compose_tickets`, `audit_legs`, devig, budget
allocation, combined odds, hash generation, expiry validation, payout, or settlement.
Assert skip link, labels, live regions, keyboard-native controls, and CSS narrow-screen
minimum height 44px.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m4_ui.py -q`

Expected: `/tickets` is 404 and the template is absent.

- [ ] **Step 3: Implement SSR route and intentional workbench layout**

Use the existing paper/ink/pine/cinnabar/gold tokens and typography. Desktop has the
face matrix and sticky audit ledger; mobile uses ordered full-width match cards. Render
all deterministic values from DTOs. Keep ERROR non-actionable, WARN forms explicit,
and confirmation visually separate from approval.

- [ ] **Step 4: Add progressive form behavior**

Reuse the existing session bootstrap and `postJson()`. JavaScript may collect form
values, generate idempotency keys with `crypto.randomUUID`, encode a selected receipt
with `FileReader`, update live regions, and reload server state after success. It must
not decide readiness or confirmation freshness locally.

- [ ] **Step 5: Run UI and adjacent route tests**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m4_ui.py tests/product/test_m3_ui.py tests/product/test_m2_ui.py -q
UV_FROZEN=1 uv run ruff check nutmeg/interfaces/product_ui.py tests/product/test_m4_ui.py
```

Expected: all pass.

- [ ] **Step 6: Commit Task 8**

```bash
UV_FROZEN=1 git add nutmeg/interfaces/product_ui.py nutmeg/interfaces/web/templates/product nutmeg/interfaces/web/static/product tests/product/test_m4_ui.py
UV_FROZEN=1 git commit -m "feat(ui): add ticket adjudication workbench"
```

## Task 9: M4 golden path, operational docs, and invariant regressions

**Files:**
- Create: `tests/product/test_m4_e2e.py`
- Create: `docs/nutmeg-intelligence-os-m4-operations.md`
- Modify: `.pre-commit-config.yaml` only if the existing hooks omit a new M4 path

- [ ] **Step 1: Write failing full M4 lifecycle E2E**

Drive the FastAPI app through:

```text
session -> workbench -> create batch -> blocked ERROR path
-> clean batch -> WARN blocked -> record Adjudication with evidence_rejected
-> approve -> inspect immutable hash -> issue nonce -> restart app
-> confirm manual receipt -> inspect Ticket/ledger/lineage/events
-> duplicate replay -> consumed-nonce rejection -> empty-slate approval
```

Assert exact object counts, one debit, CAS bytes/hash, no receipt/nonce leakage, AI
denials, and SSE cursor continuity.

- [ ] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m4_e2e.py -q -x`

Expected: the first unimplemented lifecycle assertion fails for the intended reason.

- [ ] **Step 3: Fix only integration gaps exposed by the E2E**

Apply the systematic-debugging protocol for each unexpected failure. Do not add new
features. Re-run the smallest failing test after each fix, then the full M4 E2E.

- [ ] **Step 4: Write the operations contract**

Document local-only authority, two-stage semantics, hashes, WARN/ERROR behavior,
confirmation expiry/recovery, manual receipt, connector disabled-by-default, empty
slate, backup inputs, audit queries, legacy Express compatibility, and explicit
prohibitions on direct SQL/CAS edits or live dispatch during M4.

- [ ] **Step 5: Run focused M4 and adjacent deterministic suites**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m4_e2e.py tests/product tests/ontology/test_ticket_composition.py tests/ontology/test_protected_ticket_actions.py tests/ontology/test_ticket_confirmation.py tests/decision/test_express.py tests/decision/test_legs_audit.py tests/decision/test_close_settle_adapter.py -q
UV_FROZEN=1 uv run pre-commit run pytest-product --all-files
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit Task 9**

```bash
UV_FROZEN=1 git add tests/product/test_m4_e2e.py docs/nutmeg-intelligence-os-m4-operations.md .pre-commit-config.yaml nutmeg tests
UV_FROZEN=1 git commit -m "test(product): prove protected ticket lifecycle"
```

## Task 10: Browser, frozen replay, and M4 completion gate

**Files:**
- Create evidence: `docs/superpowers/evidence/m4/*.png`
- Modify: this plan only to check tasks and record exact evidence
- Modify production only if a test-first browser/replay defect is proven

- [ ] **Step 1: Run repository static and full test gates from clean state**

Run:

```bash
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall -q nutmeg scripts
UV_FROZEN=1 uv run pytest -q
UV_FROZEN=1 uv run pytest tests/product -q
UV_FROZEN=1 uv run pytest tests/ontology -q
UV_FROZEN=1 uv run pre-commit run --all-files
git diff --check
```

Record exact pass counts in this plan.

- [ ] **Step 2: Run browser verification at desktop and narrow sizes**

Start the product against an isolated fixture database. Use the browser skill to inspect
1440x1000 and 390x844 for clean, ERROR, WARN, approved, confirmation, placed, empty,
offline, and restored states. Capture evidence under `docs/superpowers/evidence/m4/`.

Verify HTTP 200, no horizontal overflow, no clipped IDs/hash, controls at least 44px,
skip link first, visible focus, sensible keyboard order, no console/page errors, escaped
untrusted text, confirmation separation, and SSE reconnection.

- [ ] **Step 3: Run an isolated frozen M3-store replay**

Copy the prior verified M3 frozen root to a new `mktemp -d` root. Set all relevant data
paths to the copy, keep fetch/providers/connectors/dispatch disabled, apply migration 12,
and execute one manual M4 lifecycle with a fixture text receipt. Verify:

- all pre-existing object counts survive migration;
- one approved artifact hash equals its CAS bytes;
- one confirmed Ticket has correct Forecast refs and exact single stake debit;
- challenge digest is durable and plaintext nonce is absent;
- Action/outbox/lineage are complete;
- dry `decision-close` and dry `decision-settle` remain behaviorally callable;
- no production data, provider, Telegram, connector, scheduler, or real betting action
  occurs.

Record the resolved temporary path and counts in this plan; do not commit temporary data.

- [ ] **Step 4: Invoke project decision-chain verification**

Read and execute the `verify` skill with `UV_FROZEN=1`. Use replay/no-fetch inputs and
report any external-source unavailability explicitly. No stage may silently fall back
to legacy production data.

- [ ] **Step 5: Invoke the mandatory completion/spec-coverage gate**

Read and execute `speckit-superb-verify` and `verification-before-completion`. Build a
requirement-to-test/evidence matrix for every M4 design section. Do not mark a task done
without fresh command output.

- [ ] **Step 6: Record evidence, commit, and inspect without merging**

Check every box only after its evidence exists. Add pass counts, browser screenshot
paths, replay counts, no-side-effect statement, and the spec coverage matrix to this
plan. Then run:

```bash
UV_FROZEN=1 git add docs/superpowers/plans/2026-08-24-nutmeg-intelligence-os-m4.md docs/superpowers/evidence/m4
UV_FROZEN=1 git commit -m "docs(product): record M4 verification"
git status --short
git log --oneline --decorate -15
git diff --stat main...HEAD
```

Expected: clean worktree, focused commits, no unexplained file, and M4 coverage fully
green. Do not merge or enable any scheduler/connector.

## M4 completion boundary

M4 is complete only when Task 10 passes. Completion does not authorize Scoreboard
cutover, scheduler restoration, live connector configuration, or production betting.
M5 begins with a separate focused design and plan based on the verified M4 interfaces.

## M4 spec coverage checklist

| Requirement | Planned evidence |
| --- | --- |
| One composition implementation | Tasks 1, 9, 10 |
| One C0-C7 audit implementation | Tasks 1, 4, 9, 10 |
| Current committed Forecast binding | Tasks 3, 5, 6 |
| Immutable revisions and comparison | Tasks 2-4, 6, 8 |
| ERROR non-overridable | Tasks 4, 7-10 |
| WARN + `evidence_rejected` | Tasks 4, 8-10 |
| Immutable per-ticket CAS artifact/hash | Tasks 4, 6, 9, 10 |
| Approval does not debit | Tasks 4, 9, 10 |
| Fresh per-ticket confirmation | Tasks 5, 7-10 |
| AI cannot approve/confirm/dispatch | Tasks 2-5, 7, 9 |
| Manual receipt and placement | Tasks 5, 7-10 |
| Optional isolated connector | Tasks 5, 7, 9 |
| Empty slate legal and explicit | Tasks 1, 3, 4, 8-10 |
| Duplicate/stale/restart recovery | Tasks 2, 5, 7, 9, 10 |
| CLI/Express compatibility | Tasks 3-5, 9, 10 |
| Desktop/mobile/accessibility | Tasks 8, 10 |
| No live side effects | Scope lock, Tasks 9-10 |
