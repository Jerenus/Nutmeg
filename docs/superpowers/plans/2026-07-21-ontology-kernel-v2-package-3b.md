# Ontology Kernel v2 Package 3B Implementation Plan — Finance Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn a committed forecast into a budget-checked, ledger-atomic ticket and settle it against a match outcome — every bet leg references a committed forecast, ticket approval writes ticket+legs+cash in one transaction, and settlement only happens when the outcome is sufficient (never a pending loss).

**Architecture:** Package 3B adds the finance/outcome layer on the delivered Packages 1/2/3A. New tables extend `schema.metadata` via migration 8; a `.finance` repository hangs off `OntologyUnitOfWork`; every write is an `ActionService.execute` handler. TicketProposal is built only from the current committed ForecastRevision (3A); ApproveTicket writes Ticket+BetLeg+CashTransaction atomically; SettleTicket grades legs against a MatchOutcome and never fabricates a pending settlement. The ¥400 budget is a cost ceiling, not a fill target — an empty proposal is a legal no-op. Scoring (Brier/CLV) is Package 4, not here.

**Tech Stack:** Python 3.13, frozen dataclasses, SQLAlchemy 2 Core, SQLite WAL, pytest, ruff; Packages 1/2A/2B/3A kernel + facts + belief layer.

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-3-design.md` (§1 scope 3B, §2.4/§2.5 decisions, §3 tables 3B, §4 actions 3B, §6 acceptance 3B).

**Depends on:** Packages 1, 2A, 2B, 3A (merged). Uses: `ActionCommand.create`, `ActionService.execute`, `ActorRole`, `OntologyUnitOfWork.{identity,market,decision}`, `DecisionRepository.current_committed_revision`, `schema.metadata`, `Migration`/`MIGRATIONS`/`run_migrations`, `canonical_json`, `OntologyKernelStatus`, `MarketDefinition.settlement_scope` (2A).

---

## Scope Boundary

Package 3B includes: finance/outcome tables (migration 8) + graded permissions; a `FinanceRepository` and
`OntologyUnitOfWork.finance`; a budget validation helper; Actions `change_budget_policy`, `propose_ticket`,
`approve_ticket`, `record_cash_transaction`, `record_outcome`, `correct_outcome`, `settle_ticket`; had 3-way
leg settlement grading; express + reconcile facades; kernel counts; a real-forecast express/settle e2e gate.

Package 3B excludes: Brier/CLV/calibration/scoring and DuckDB projections (Package 4 — `capture_closing` and
closing-based CLV live there; closing snapshots are already recordable via 2A `BuildMarketSnapshot` with
`snapshot_kind='closing'`); hhad/ttg/crs settlement grading beyond the had representative (a follow-on within
3B, noted, not silently skipped); historical migration and schedule restore (Package 5).

Only **additive** changes to earlier modules: one `MIGRATIONS` entry, one `.finance` UoW property, new
`OntologyKernelStatus` counts (`ticket_count`, `settlement_count`), and `build_ontology_kernel` exposing the
express/reconcile facades.

---

## File Structure

### New production modules
- `nutmeg/ontology/finance/__init__.py`, `nutmeg/ontology/finance/models.py`: TicketStatus, TransactionKind, OutcomeStatus, SettlementGrade, ProposalStatus enums; id minting.
- `nutmeg/ontology/finance/budget.py`: pure budget validation (total/bucket caps).
- `nutmeg/ontology/finance/settlement.py`: pure had 3-way leg grading from a score.
- `nutmeg/ontology/repository/schema_finance.py`: finance/outcome Core tables.
- `nutmeg/ontology/repository/finance.py`: FinanceRepository + row dataclasses.
- `nutmeg/ontology/actions/budget_actions.py`: ChangeBudgetPolicy.
- `nutmeg/ontology/actions/ticket_actions.py`: ProposeTicket / ApproveTicket / RecordCashTransaction.
- `nutmeg/ontology/actions/outcome_actions.py`: RecordOutcome / CorrectOutcome / SettleTicket.
- `nutmeg/ontology/finance/express_flow.py`: ExpressService (committed forecast → proposal → approve).
- `nutmeg/ontology/finance/reconcile_flow.py`: ReconcileService (outcome → settle).

### New tests
- `tests/ontology/test_finance_models.py`, `test_schema_finance_migration.py`, `test_budget.py`, `test_settlement_grading.py`, `test_finance_repository.py`, `test_budget_actions.py`, `test_ticket_actions.py`, `test_outcome_actions.py`, `test_express_flow.py`, `test_reconcile_flow.py`, `test_package3b_e2e.py`

### Existing files modified (additive)
- `nutmeg/ontology/repository/migrations.py`: migration 8 + finance permissions.
- `nutmeg/ontology/repository/unit_of_work.py`: `.finance`.
- `nutmeg/ontology/kernel.py`: `ticket_count`/`settlement_count` on status; `express`/`reconcile` on kernel.
- `nutmeg/ontology/wiring.py`: build finance actions + Express/Reconcile services.
- `docs/ontology-kernel-operations.md`: Package 3B section.

### User-owned files that must not be reverted
`SOUL.md`, three decision plists, untracked `media/`/memory/scripts. Execute in the Task 0 worktree.

---

### Task 0: Worktree
`git worktree add .claude/worktrees/ontology-kernel-v2-package3b -b feature/ontology-kernel-v2-package3b`; `uv sync --extra dev`. Confirm HEAD is the Package 3A merge; dirty entries only user-owned. Do not touch paused schedules/freeze archive.

---

### Task 1: Finance value objects
**Files:** Create `nutmeg/ontology/finance/__init__.py`, `models.py`; Test `tests/ontology/test_finance_models.py`

- [ ] **RED test:**
```python
from nutmeg.ontology.finance.models import (
    OutcomeStatus, ProposalStatus, SettlementGrade, TicketStatus, TransactionKind, mint_finance_id,
)


def test_enum_values() -> None:
    assert TicketStatus.APPROVED.value == "approved"
    assert TransactionKind.STAKE.value == "stake"
    assert TransactionKind.PAYOUT.value == "payout"
    assert OutcomeStatus.FINAL.value == "final"
    assert SettlementGrade.WIN.value == "win"
    assert SettlementGrade.LOSS.value == "loss"
    assert SettlementGrade.VOID.value == "void"
    assert ProposalStatus.PROPOSED.value == "proposed"


def test_mint_finance_id() -> None:
    a = mint_finance_id("tk")
    assert a.startswith("tk-") and a != mint_finance_id("tk")
```

- [ ] **Verify RED**, then implement StrEnums: `TicketStatus{PROPOSED=proposed, APPROVED=approved, SETTLED=settled, VOID=void}`, `TransactionKind{STAKE=stake, PAYOUT=payout, ADJUSTMENT=adjustment}`, `OutcomeStatus{PROVISIONAL=provisional, FINAL=final}`, `SettlementGrade{WIN=win, LOSS=loss, VOID=void, PUSH=push}`, `ProposalStatus{PROPOSED=proposed, APPROVED=approved, REJECTED=rejected}`, and `mint_finance_id(prefix)`. Export all. Run tests+ruff. Commit `feat(ontology): add finance value objects`.

---

### Task 2: Finance schema and migration 8
**Files:** Create `nutmeg/ontology/repository/schema_finance.py`; Modify `migrations.py`; Test `tests/ontology/test_schema_finance_migration.py`

- [ ] **RED test:** assert `migration_status >= 8`; tables `{budget_policies, ticket_proposals, tickets, bet_legs, cash_accounts, cash_transactions, match_outcomes, bet_leg_settlements, ticket_settlements}` present; permissions `("approve_ticket","judge_operator")` in, `("approve_ticket","ai_analyst")` not in, `("settle_ticket","deterministic_system")` in.

- [ ] **Implement** tables per design §3 (3B). All TEXT unless noted; JSON columns canonical; FKs:
  `bet_legs.forecast_revision_id → forecast_revisions` (each leg references a committed forecast),
  `bet_legs.ticket_id → tickets`, `bet_legs.match_id → matches`, `bet_legs.market_definition_id →
  market_definitions`, `bet_legs.selection_id → selection_definitions`, `bet_legs.entry_quote_id →
  market_quotes` (nullable — replay may lack a quote), `tickets.proposal_id → ticket_proposals` (nullable),
  `tickets.account_id → cash_accounts`, `cash_transactions.account_id → cash_accounts`,
  `cash_transactions.ticket_id → tickets` (nullable), `match_outcomes.match_id → matches`
  `UNIQUE(match_id, version)`, `bet_leg_settlements.bet_leg_id → bet_legs`,
  `bet_leg_settlements.outcome_id → match_outcomes`, `ticket_settlements.ticket_id → tickets`.
  `cash_transactions.amount REAL NOT NULL`; `cash_transactions.idempotency_key TEXT NOT NULL UNIQUE`;
  `budget_policies.total_cap REAL NOT NULL`.

- [ ] **Migration 8** `_apply_finance` creates the nine tables in FK order (cash_accounts, budget_policies,
  ticket_proposals, tickets, bet_legs, cash_transactions, match_outcomes, bet_leg_settlements,
  ticket_settlements) and seeds permissions (governance-v1):
```text
change_budget_policy:  judge_operator
propose_ticket:        ai_analyst, judge_operator
approve_ticket:        judge_operator
record_cash_transaction: deterministic_system, judge_operator
record_outcome:        deterministic_system
correct_outcome:       deterministic_system
settle_ticket:         deterministic_system
```
Append `Migration(version=8, name='finance', fingerprint='budget_policies..ticket_settlements+finance_permissions', apply=_apply_finance)`. Run schema+migration+kernel tests. Commit `feat(ontology): add finance schema and permissions`.

---

### Task 3: FinanceRepository and `.finance`
**Files:** Create `nutmeg/ontology/repository/finance.py`; Modify `unit_of_work.py`; Test `tests/ontology/test_finance_repository.py`

- [ ] **RED test:** insert a cash account, a ticket, a bet leg, a cash_transaction; read back `count_tickets()==1`, `ledger_balance(account_id)` reflects the stake (negative), `bet_leg_ids(ticket_id)`.

- [ ] **Implement** frozen row dataclasses (`BudgetPolicyRow`, `ProposalRow`, `TicketRow`, `BetLegRow`, `CashAccountRow`, `CashTransactionRow`, `OutcomeRow`, `BetLegSettlementRow`, `TicketSettlementRow`) and `FinanceRepository(connection)` with: `ensure_account`, `insert_budget_policy`, `active_budget_policy(channel)`, `insert_proposal`, `insert_ticket`, `insert_bet_leg`, `bet_leg_ids(ticket_id)`, `bet_legs_for(ticket_id) -> list[BetLegRow]`, `insert_cash_transaction`, `ledger_balance(account_id) -> float` (Σ signed amounts: stake negative, payout positive, adjustment as-is), `insert_outcome`, `current_outcome(match_id) -> OutcomeRow | None`, `max_outcome_version(match_id)`, `insert_bet_leg_settlement`, `insert_ticket_settlement`, `count_tickets`, `count_settlements`. Sign convention: store `cash_transactions.amount` signed (stake stored negative, payout positive) so `ledger_balance` is a plain SUM. Add `.finance` to the UoW. Run tests+ruff. Commit `feat(ontology): add finance repository`.

---

### Task 4: Budget validation + ChangeBudgetPolicy
**Files:** Create `nutmeg/ontology/finance/budget.py`, `nutmeg/ontology/actions/budget_actions.py`; Test `tests/ontology/test_budget.py`, `tests/ontology/test_budget_actions.py`

- [ ] **RED (budget.py):** `validate_within_budget(total_cap, bucket_caps, legs)` where each leg has `bucket` and `stake` — raises `ValueError` if Σstake > total_cap or any bucket's Σ > its cap; passes for an empty legs list (empty is legal).
- [ ] **Implement** pure `validate_within_budget`. Run+ruff. Commit.
- [ ] **RED (budget_actions):** `change_budget_policy` (judge_operator) inserts a versioned `budget_policies` row (channel jczq, total_cap 400, bucket caps); ai_analyst rejected.
- [ ] **Implement** `BudgetActions.change_budget_policy`. Run+ruff. Commit `feat(ontology): budget policy and validation`.

---

### Task 5: Had 3-way settlement grading
**Files:** Create `nutmeg/ontology/finance/settlement.py`; Test `tests/ontology/test_settlement_grading.py`

- [ ] **RED test:** `grade_had(selection_outcome_key, home_score, away_score)` returns `SettlementGrade`:
  home>away & key=="home" → WIN; key=="draw" & home==away → WIN; a wrong pick → LOSS.
```python
def test_grade_had() -> None:
    assert grade_had("home", 2, 1) is SettlementGrade.WIN
    assert grade_had("away", 2, 1) is SettlementGrade.LOSS
    assert grade_had("draw", 1, 1) is SettlementGrade.WIN
    assert grade_had("home", 1, 1) is SettlementGrade.LOSS
```
- [ ] **Implement** pure `grade_had(outcome_key, home_score, away_score)` mapping the 90-minute result to home/draw/away and comparing. (hhad/ttg/crs grading is a documented follow-on.) Run+ruff. Commit `feat(ontology): had settlement grading`.

---

### Task 6: ProposeTicket + ApproveTicket + RecordCashTransaction
**Files:** Create `nutmeg/ontology/actions/ticket_actions.py`; Test `tests/ontology/test_ticket_actions.py`

- [ ] **RED test:** with a committed forecast (via 3A ForecastActions) and a cash account, `propose_ticket`
  builds a proposal referencing the committed `forecast_revision_id`; `approve_ticket` (judge_operator)
  writes Ticket + one BetLeg + one stake CashTransaction **atomically** (assert all three exist and
  `ledger_balance == -stake`); a leg whose forecast is not committed is rejected with `ValueError`; an
  ai_analyst approve is REJECTED; over-budget approve raises `ValueError`.
- [ ] **Implement** frozen `LegInput(match_id, market_definition_id, selection_id, forecast_revision_id, entry_quote_id?, line?, bucket, stake)`, `ProposeTicketRequest`, `ApproveTicketRequest`. `propose_ticket` (ai_analyst/judge) validates each leg's `forecast_revision_id` is a **committed** current revision (else `ValueError`) and records a `ticket_proposals` row. `approve_ticket` (judge_operator): `validate_within_budget`; in one handler insert `tickets`, each `bet_legs`, and one `cash_transactions` (kind=stake, amount = −total_stake, unique idempotency key). `record_cash_transaction` records a standalone signed transaction. Run+ruff. Commit `feat(ontology): propose and approve tickets atomically`.

---

### Task 7: RecordOutcome + CorrectOutcome
**Files:** Create `nutmeg/ontology/actions/outcome_actions.py`; Test `tests/ontology/test_outcome_actions.py`

- [ ] **RED test:** `record_outcome` (deterministic_system) inserts a `match_outcomes` row (version 1, score_90, status final); `correct_outcome` inserts version 2 superseding version 1 (both rows kept; `current_outcome` returns v2); a connector record is REJECTED.
- [ ] **Implement** `OutcomeActions.record_outcome`/`correct_outcome` using `max_outcome_version + 1` and `supersedes_outcome_id`. Run+ruff. Commit `feat(ontology): record and correct match outcomes`.

---

### Task 8: SettleTicket
**Files:** Modify `nutmeg/ontology/actions/outcome_actions.py`; Test add to `tests/ontology/test_outcome_actions.py`

- [ ] **RED test:** with an approved ticket (one had leg) and a final outcome, `settle_ticket`
  (deterministic_system) creates one `bet_leg_settlements` (grade from `grade_had`) and one
  `ticket_settlements` (status settled, pnl); on a **missing** outcome, `settle_ticket` returns a result with
  `settled=False` and **creates no pending settlement**; a winning single leg records a payout
  CashTransaction so `ledger_balance` rises.
- [ ] **Implement** `SettleTicketRequest` and `OutcomeActions.settle_ticket`: read `current_outcome(match_id)`;
  if none → return `settled=False`, write nothing; else grade each leg via `grade_had` (had only; other
  markets → grade VOID with a note, documented), insert `bet_leg_settlements` + one `ticket_settlements`
  (stake/payout/pnl), and a payout `cash_transactions` when the ticket wins. Run+ruff. Commit `feat(ontology): settle tickets against outcomes`.

---

### Task 9: Express + Reconcile facades + wiring + counts
**Files:** Create `nutmeg/ontology/finance/express_flow.py`, `reconcile_flow.py`; Modify `wiring.py`, `kernel.py`, `unit_of_work.py`; Test `tests/ontology/test_express_flow.py`, `tests/ontology/test_reconcile_flow.py`

- [ ] **RED (express):** `kernel.express.approve_for_match(ExpressRequest(...))` with a committed forecast and
  a leg builds proposal+ticket atomically; an **empty legs** request returns a no-op result (no ticket) — an
  empty slate is legal. `kernel.status().ticket_count` reflects approved tickets.
- [ ] **RED (reconcile):** `kernel.reconcile.settle_match(ReconcileRequest(...))` records an outcome then
  settles the match's tickets; `kernel.status().settlement_count` reflects it.
- [ ] **Implement** `ExpressService` (propose+approve) and `ReconcileService` (record outcome + settle each
  ticket for the match). Extend `OntologyKernelStatus` with `ticket_count`/`settlement_count`; extend
  `build_ontology_kernel` to expose `express`/`reconcile`. Run+ruff. Commit `feat(ontology): express and reconcile facades`.

---

### Task 10: Full express→settle e2e gate, docs, verification
**Files:** Create `tests/ontology/test_package3b_e2e.py`; Modify `docs/ontology-kernel-operations.md`

- [ ] **RED e2e:** end-to-end on a real match: commit a forecast (3A) → express approve a had leg (Ticket+BetLeg+CashTransaction atomic, ledger = −stake) → record a final outcome → reconcile settle (BetLeg/Ticket settlement, payout on win, ledger balances) → assert **BetLeg references the committed forecast**, **no pending settlement when outcome missing** (a separate match with no outcome), and **ledger stake+payout reconciles**.
- [ ] Drive to GREEN. Document Package 3B in the operations doc (BudgetPolicy ¥400 ceiling not a fill target, atomic approve, no-pending settlement, express/reconcile).
- [ ] Full suite: `uv run pytest tests/ontology -q`; adjacent `tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness tests/decision/ -q`.
- [ ] Quality gates: `uv run ruff check .`, `uv run python -m compileall -q nutmeg scripts`, `bash scripts/verify.sh`.
- [ ] Project verify: 3B adds no code to the old decision path; rely on the e2e gate and state so.
- [ ] Commit `test(ontology): verify package 3b finance layer`; inspect branch; do not merge — hand back for review.

---

## Package 3B Spec Coverage
| Design (§) | Task |
|---|---|
| BetLeg references committed forecast (§2.4) | 6, 10 |
| Atomic Ticket+BetLeg+CashTransaction (§2.4) | 6, 10 |
| ¥400 ceiling not a fill target; empty is legal (§2.4) | 4, 9 |
| No pending settlement on missing outcome (§2.5) | 8, 10 |
| Outcome versions; correct not overwrite (§2.5) | 7 |
| Had 3-way settlement by scope+result (§2.5) | 5, 8 |
| Ledger stake/payout reconciles (§6) | 3, 8, 10 |
| Graded permissions (approve/settle) (§4) | 2, 6, 8 |
| express + reconcile facades (§5) | 9 |

Package 3B is complete only when Task 10 passes. Together with 3A it closes umbrella Package 3 (Decision &
Finance Loop). Package 4 (Learning & Regime) receives its own plan and consumes committed forecasts, closing
snapshots, outcomes and settlements to build DuckDB scoring/regime projections.
