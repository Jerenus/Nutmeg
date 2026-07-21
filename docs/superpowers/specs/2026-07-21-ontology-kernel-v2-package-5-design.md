# Ontology Kernel v2 — Package 5 Design (Evidence Migration & Cutover)

> Self-contained design for Package 5 of `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md`
> (§13.2 Package 5, §12 cutover). Packages 1–4 are merged: the SQLite kernel + typed
> Actions + DuckDB projections are a complete five-verb system. Package 5 migrates the
> old append-only JSONL decision store into the new kernel, reconciles the rebuilt
> metrics against the old ones, rewires the live CLI onto the new verbs, and — as the
> **single irreversible step, gated on explicit user confirmation** — shuts the old
> write path and restores the paused schedules.

## 1. Scope & split

- **Package 5A — Historical importer + reconciliation.** A deterministic, idempotent
  importer that reads the old `.nutmeg-data/jczq/decision/*.jsonl` (and the zucai
  ledger) and replays each object into the new kernel through its typed Actions, then
  a reconciliation that rebuilds Brier/CLV/ledger via `calibrate` and compares against
  the old `settlements.jsonl`. Read-only on the source; writes only a **fresh** target
  store (never the production kernel path).
- **Package 5B — CLI rewire + replay + go-live prep.** An adapter that routes the live
  `decision-*` commands onto the kernel Actions behind a `NUTMEG_ONTOLOGY_V2` flag; a
  real-chain replay gate; and a documented, **not-executed** cutover runbook (old-writer
  shutdown + schedule restore) surfaced for user sign-off.

Package 5 **excludes** nothing further — it is the last package. What it does **not do
autonomously**: enable `NUTMEG_ONTOLOGY_V2` in production, delete the freeze archive,
re-enable the booted-out launchd schedules, or dispatch any Telegram/live push. Those
are the irreversible go-live, done only on explicit user confirmation.

## 2. Old → new object mapping (from the real JSONL shapes)

The old store is append-only JSONL, one file per object type (`DecisionStore`).
Observed record shapes:

| Old object (file) | Key fields | New kernel target (Action) |
|---|---|---|
| `Match` (matches.jsonl) | match_id, home/away, home/away_team_id, competition[_id], kickoff_at, channel_refs | Team/Competition/Match identity rows (Package 2A ingest Actions or a minimal import Action) |
| `MarketSnapshot` (snapshots.jsonl) | snapshot_id, match_id, kind, fair, raw_odds, lines, source, taken_at | `BuildMarketSnapshot` (2A): snapshot_kind=kind, as_of=taken_at, fair_distribution=fair |
| `Read` (reads.jsonl) | read_id, match_id, snapshot_id, market, prior, belief, factors, confidence, made_at, falsifier, note, shadow | `commit_forecast` (3A): prior/belief/factors→FactorApplications; market→market_definition |
| `Factor` (factors.jsonl) | factor id/family/scope/status | Factor family + definition rows (3A) |
| `Ticket` (tickets.jsonl) | ticket_id, legs, stake_yuan, budget_bucket, structure, channel, made_at | `propose_ticket`+`approve_ticket` (3B): legs→BetLegs, stake→CashTransaction |
| `Settlement` (settlements.jsonl) ref_type=Ticket | outcome_90, pnl_yuan, hit, settled_at | `record_outcome`+`settle_ticket` (3B) |
| `Settlement` ref_type=Read | brier, clv_pp, closing_snapshot_id, outcome_90 | **Not** an operational Settlement — the outcome is recorded so `calibrate` rebuilds the ForecastScore (spec §line 1167). The old brier/clv are the **reconciliation baseline**, not truth. |

Each mapping derives its Action `idempotency_key` from the old object id
(`import:<type>:<id>`), so the importer is **idempotent** — re-running imports nothing
twice. Markets map old `market` strings (`had`/`hhad`/`ttg`/`crs`) to the seeded
`md-*` definitions; unmappable objects are **counted and reported, never dropped
silently**.

## 3. Reconciliation

After import into a fresh target store, run `kernel.calibrate.build(...)`, then compare:

- **Forecast truth:** rebuilt `forecast_scores.brier` vs the old Read-`Settlement.brier`
  for the same `(match, market, made_at)` — report per-row delta, count matches within
  a tolerance, and list mismatches. A rebuilt score with no old baseline (or vice
  versa) is reported as coverage, not hidden.
- **Ledger:** rebuilt ticket ledger (stake/payout/pnl) vs old `Ticket`/`Settlement.pnl_yuan`.
- The reconciliation emits a report object (counts, matched, mismatched, coverage,
  tolerance, method_version). It **asserts nothing about production** — it is evidence
  for the go-live decision.

## 4. CLI rewire (5B)

A thin adapter (`nutmeg/decision/ontology_adapter.py`) exposes the five verbs against
the kernel. When `NUTMEG_ONTOLOGY_V2` is unset (default), the live `decision-*`
commands behave exactly as today (old path). When set, they route to the kernel. This
lets replay run the new path against a temp store with **zero** change to production
behavior until the flag is flipped — which is part of go-live.

## 5. Acceptance

**5A.** (a) importing a small golden JSONL fixture yields the expected Team/Match/
Snapshot/Forecast/Ticket/Outcome/Settlement rows in a fresh kernel; (b) re-running the
import is a no-op (idempotent by derived key); (c) an unmappable record is counted in
the report, never dropped; (d) reconciliation rebuilds Brier for an imported Read and
reports the delta vs the old baseline; (e) the importer never writes the production
kernel path (writes only the caller-provided target dir).

**5B.** (f) with `NUTMEG_ONTOLOGY_V2` unset, the adapter is inert and the old path is
unchanged; (g) a real-chain replay of one historical day into a temp store produces a
non-empty calibrate scorecard; (h) the cutover runbook documents the exact, reversible-
until-the-last-step sequence and is **not executed** by any test or command.

## 6. Go-live (NOT in autonomous scope)

The final, irreversible sequence — enable the flag in production, shut the old JSONL/
DuckDB writers, restore the three `com.nutmeg.decision.*` schedules — is documented as
a runbook and executed **only** after the user reviews the reconciliation evidence and
explicitly approves. The freeze archive is retained read-only throughout.
