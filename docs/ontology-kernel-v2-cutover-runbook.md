# Ontology Kernel v2 — Cutover Runbook (Package 5B, go-live is user-gated)

> **Status: NOT executed.** This runbook documents the single irreversible go-live
> sequence. Every step below is manual and gated on explicit user approval after the
> reconciliation evidence is reviewed. Nothing in the codebase runs this automatically.
> The read-only freeze archive `.nutmeg-data/archive/20260721-112449-ontology-v2-freeze`
> is retained throughout.

## 0. Where we are

Packages 1–5A are merged: the SQLite kernel + typed Actions + DuckDB projections are a
complete five-verb system (`sense → read → express → reconcile → calibrate`), and
`nutmeg migrate-decision-store` imports the old JSONL store and reconciles the rebuilt
metrics — read-only on the source, writing only a caller-chosen target.

The three live schedules (`com.nutmeg.decision.am`/`.close`/`.settle`) are **booted out
(paused)** and must stay paused until go-live.

## 1. Reconciliation evidence (review before deciding)

Latest read-only dry import over the production store (`.nutmeg-data/jczq`, no writes):

| Metric | Value |
|---|---|
| matches imported | 136 |
| snapshots imported / skipped | 350 / 6 (degenerate had fair) |
| reads imported | 245 |
| outcomes imported | 91 |
| factors dropped (old direction/weight_pp, not replayable) | 27 |
| rebuilt Brier **matched** old baseline (≤1e-6) | **91** |
| **mismatched** | 9 |
| no baseline (old settlement had no brier / unscored) | 89 |
| coverage | 0.53 |

**Reading this evidence:** the 91 exact Brier matches confirm the scoring rebuild is
faithful. Before go-live, the **9 mismatches** and the **0.53 coverage** should be
understood — likely causes to investigate (not yet done):

- old settlements that used a different/older Brier convention for some rows;
- reads on `hhad`/`ttg` markets (4A scores only `had`, so they land in "no baseline");
- the 27 dropped legacy factors (belief still imported follow-market; only the factor
  attribution is absent).

None of these block a *fresh-start* cutover; they only bound how much history the new
`calibrate` projections inherit. A clean go/no-go needs the user's call on whether the
9 mismatches are acceptable or warrant a scoring-convention reconciliation first.

## 2. Go-live sequence (manual, reversible until step 5)

1. **Re-run the dry import** into a scratch dir and re-read §1 — confirm the numbers are
   stable: `nutmeg migrate-decision-store --source .nutmeg-data/jczq --target $(mktemp -d)`.
2. **Provision the production kernel store** (one-time): point the new kernel at the
   production `data_dir` and `initialize()` (creates `ontology/ontology.db` +
   `analytics.duckdb`); optionally run the importer with `--target .nutmeg-data` to seed
   history. *Reversible:* delete the new `ontology/` dir to undo.
3. **Enable the adapter flag** `NUTMEG_ONTOLOGY_V2=1` in the environment the `decision-*`
   commands read. With the flag unset the old path is unchanged; setting it routes the
   verbs onto the kernel. *Reversible:* unset the flag.
4. **Shadow-run one live day** with the flag set but schedules still paused — run
   `decision-am/read/close/settle` manually (dry, no `--dispatch-telegram --no-dry-run`)
   and confirm the PDF/report + `nutmeg ontology status` counts. *Reversible:* unset flag.
5. **Restore the schedules** (the irreversible go-live):
   `launchctl bootstrap gui/$(id -u) ops/launchd/com.nutmeg.decision.am.plist` (and
   `.close`, `.settle`). From here the live loop runs on the new kernel. *To roll back:*
   boot the schedules out again and unset the flag.
6. **Retire the old writers** only after several clean live days: the old
   `nutmeg/decision` JSONL/DuckDB write paths become read-only archive. Keep the freeze
   archive.

## 3. Hard stops

- Do **not** delete the freeze archive at any step.
- Do **not** run any command with `--dispatch-telegram --no-dry-run` until step 5 is
  approved and the shadow day (step 4) is clean.
- Do **not** re-enable the schedules (step 5) without explicit user approval of the §1
  evidence.
- `.nutmeg-data` is production: the importer only ever writes the `--target` you pass.

## 4. What Package 5B still leaves open (honest)

- The flag-gated adapter that routes the live `decision-*` commands onto the kernel is
  the go-live mechanism itself (steps 3–5); it is documented here rather than wired into
  the default path, so that an unset flag is a guaranteed no-op.
- Investigating the 9 Brier mismatches and raising coverage above 0.53 is recommended
  pre-go-live work, not yet done.
