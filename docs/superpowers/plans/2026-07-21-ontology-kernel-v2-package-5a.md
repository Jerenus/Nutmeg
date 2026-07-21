# Ontology Kernel v2 Package 5A Implementation Plan — Historical Importer & Reconciliation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deterministically replay the old append-only JSONL decision store into a fresh kernel through its typed Actions (idempotent, nothing dropped silently), then reconcile the rebuilt Brier/ledger against the old `settlements.jsonl` — read-only on the source, never touching the production kernel path.

**Architecture:** An `HistoricalImporter` reads `decision/*.jsonl`, keeps an old→new id map, and replays each object via the Package 2A/3A/3B Actions (teams→matches→snapshots→forecasts→tickets→outcomes/settlements). Snapshots re-enter through `build_snapshot` by synthesizing no-vig quotes from the stored `fair` (decimal odds = 1/p), so the de-vig reproduces the old fair exactly and the path stays Action-pure. A `Reconciler` runs `calibrate` and compares rebuilt `forecast_scores` to the old Read settlements, emitting an evidence report.

**Tech Stack:** Python 3.13, SQLAlchemy 2 Core, DuckDB, frozen dataclasses, pytest, ruff; Packages 1–4.

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-5-design.md` (§2 mapping, §3 reconciliation, §5 acceptance 5A).

**Depends on (merged):** `EntityActions.upsert_team`, `MatchActions.record_match`, `MarketActions.build_snapshot`, `ForecastActions.commit_forecast`, `TicketActions`/`ExpressService`, `OutcomeActions`, `CalibrateService`, `build_ontology_kernel`, `nutmeg.decision.market_data.devig`.

---

## Scope Boundary

Includes: `nutmeg/migration/` package with `HistoricalImporter` + `Reconciler` + an `ImportReport`; golden-fixture TDD; a `nutmeg migrate-decision-store` CLI that runs the import+reconcile into a caller-provided **target dir** and prints the report (dry by default).

Excludes (Package 5B): the live `decision-*` CLI rewire, the `NUTMEG_ONTOLOGY_V2` flag, real-chain replay of the live commands, and the go-live runbook.

**Never**: write the production kernel path, delete the freeze archive, dispatch Telegram, or re-enable schedules. The importer writes only the target dir it is given.

---

## File Structure
- `nutmeg/migration/__init__.py`
- `nutmeg/migration/old_store.py`: read-only reader for the old JSONL (`read_objects(path, type)`).
- `nutmeg/migration/importer.py`: `HistoricalImporter`, `ImportReport`.
- `nutmeg/migration/reconcile.py`: `Reconciler`, `ReconciliationReport`.
- `nutmeg/migration/cli.py` (or extend the Typer app): `migrate-decision-store`.
- Tests: `tests/migration/__init__.py`, `test_old_store.py`, `test_importer.py`, `test_reconcile.py`, `test_migration_cli.py`.

### User-owned files that must not be reverted
`SOUL.md`, three decision plists, untracked `media/`/`memory/`/`scripts/`. Execute in the Task 0 worktree.

---

### Task 0: Worktree
`git worktree add .claude/worktrees/ontology-kernel-v2-package5a -b feature/ontology-kernel-v2-package5a`; `uv sync --extra dev`. Confirm HEAD is the Package 4B merge.

---

### Task 1: Old-store reader
**Files:** Create `nutmeg/migration/__init__.py`, `old_store.py`; Test `tests/migration/test_old_store.py`

- [ ] **RED:** `read_objects(decision_dir, 'matches')` yields the dict rows of `matches.jsonl` (skips blank lines); a missing file yields `[]`. Use a golden fixture dir written in the test (two match rows).
- [ ] **Implement** `read_objects(decision_dir: Path, name: str) -> list[dict]` (one file per object name; tolerant of blank lines; missing file → `[]`). Commit `feat(migration): old JSONL store reader`.

---

### Task 2: Import teams + matches (id map)
**Files:** Create `nutmeg/migration/importer.py`; Test `tests/migration/test_importer.py`

- [ ] **RED:** `HistoricalImporter(kernel).import_matches(rows)` upserts home/away teams and records a match for each old row, returning an `ImportReport` whose `match_id_map` maps old→new match ids and `team_id_map` old team ref→new; a re-run imports nothing new (idempotent by `import:match:<old_id>` derived keys). Assert `kernel.status().match_count == 2` after importing two, and unchanged after a second run.
- [ ] **Implement** `HistoricalImporter` with an internal `_team_id(old_ref, name)` that upserts once and caches; `import_matches` calls `record_match` with home/away `MatchSideRef`s, mapping `kickoff_at`→scheduled_at (schedule_status `'scheduled'`, else `'unknown'`), and stores the returned new match id. `ImportReport` accumulates counts + id maps + `skipped` list. Commit `feat(migration): import teams and matches`.

---

### Task 3: Import snapshots (fair-implied quotes)
**Files:** Modify `importer.py`; Test extend `test_importer.py`

- [ ] **RED:** `import_snapshots(rows)` records a `build_snapshot` per old snapshot whose rebuilt fair equals the old `fair` within 1e-9 (synthesized no-vig quotes: decimal odds = 1/p), mapping old snapshot_id→new; a snapshot for an unmapped match is counted in `report.skipped`, not an error.
- [ ] **Implement** `import_snapshots`: resolve `match_id` via the map (skip+count if absent); for each outcome key in `fair`, synthesize a quote (decimal_odds = 1/p, guard p>0); call `build_snapshot` with `snapshot_kind=kind`; record the new snapshot id. Commit `feat(migration): import market snapshots`.

---

### Task 4: Import reads (forecasts) + outcomes
**Files:** Modify `importer.py`; Test extend `test_importer.py`

- [ ] **RED:** `import_reads(rows)` commits a forecast per old Read (prior/belief mapped, `market` string → `md-*`, made_at, factors→FactorApplications only when the deltas reconstruct belief−prior, else the read is committed follow-market and the factor mismatch is counted); `import_outcomes(settlement_rows)` records a `MatchOutcome` from each settlement's `outcome_90`. Assert `kernel.status().forecast_count` reflects imported reads.
- [ ] **Implement** `import_reads` (resolve match+snapshot via maps; map `market`; build `FactorInput`s from the old `factors` list, dropping any whose delta does not reconstruct, counted in the report — never silently) and `import_outcomes` (parse `outcome_90` to a `score_90`, dedupe per match). Commit `feat(migration): import reads and outcomes`.

---

### Task 5: Reconciliation
**Files:** Create `nutmeg/migration/reconcile.py`; Test `tests/migration/test_reconcile.py`

- [ ] **RED:** after importing a golden Read + its outcome, `Reconciler(kernel).reconcile(old_settlements)` runs `calibrate.build` and returns a `ReconciliationReport` matching the rebuilt `forecast_scores.brier` to the old Read-settlement `brier` within tolerance for the same match+market, reporting `matched`, `mismatched`, `coverage`, and a per-row delta list; a rebuilt score with no old baseline is counted as coverage, not hidden.
- [ ] **Implement** `Reconciler.reconcile`: `calibrate.build`, read `forecast_scores` from analytics DuckDB, join to old Read settlements by (match, market), compute deltas, tolerance 1e-6. Commit `feat(migration): reconcile rebuilt metrics against old store`.

---

### Task 6: migrate-decision-store CLI + e2e + docs + verification
**Files:** Create/extend `nutmeg/migration/cli.py`; Create `tests/migration/test_migration_cli.py`; Modify `docs/ontology-kernel-operations.md`

- [ ] **RED:** invoking the `migrate-decision-store --source <golden> --target <tmp>` command imports and reconciles into the **target** dir (never production), printing counts + reconciliation summary; asserting the target kernel has the imported rows and the source dir is unmodified.
- [ ] **RED e2e (`test_importer.py`):** a golden store (2 matches, 2 snapshots incl. a closing, 2 reads, 1 ticket-less outcome) imports end-to-end; a second import is a no-op; an unmappable snapshot is reported; `calibrate` then produces a non-empty scorecard.
- [ ] Drive to GREEN. Document Package 5A in the operations doc (importer is idempotent + read-only on source; reconciliation is evidence, not an assertion about production; go-live is Package 5B and user-gated).
- [ ] Full suite `uv run pytest -q`; `uv run ruff check .`; `uv run python -m compileall -q nutmeg scripts`; `bash scripts/verify.sh`.
- [ ] Project verify: 5A never writes the production kernel path nor mutates `.nutmeg-data`; state so. Optionally run a **read-only** dry import of one real day into a tmp dir and report counts (no production writes).
- [ ] Commit `test(migration): verify package 5a importer and reconciliation`; inspect branch; hand back for review.

---

## Package 5A Spec Coverage
| Design (§) | Task |
|---|---|
| Old→new object mapping via Actions (§2) | 2,3,4 |
| Idempotent by derived key (§5b) | 2,6 |
| Unmappable counted, never dropped (§5c) | 3,4 |
| Reconciliation rebuilds + reports delta (§3,§5d) | 5 |
| Never writes production path (§5e) | 6 |

Package 5B (CLI rewire + replay + go-live runbook) follows; go-live stays user-gated.
