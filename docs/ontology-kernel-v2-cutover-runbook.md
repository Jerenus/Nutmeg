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

Latest read-only dry import over the production store (`.nutmeg-data/jczq`, no writes),
with superseded-read bucketing (`reconcile-v2`):

| Metric | Value |
|---|---|
| matches imported | 136 |
| snapshots imported / skipped | 350 / 6 (degenerate had fair) |
| reads imported | 245 |
| outcomes imported | 91 |
| factors dropped (old direction/weight_pp, not replayable) | 27 |
| rebuilt Brier **matched** old baseline (≤1e-6) | **90** |
| **mismatched** | **0** |
| superseded (earlier read of a revised series; not retained) | 10 |
| no baseline (`hhad`/`ttg` — 4A scores `had` only) | 89 |
| coverage (had, surviving reads) | 90/90 = **100%** |

**Reading this evidence:** the rebuild is **exact** — every surviving `had` read's
rebuilt Brier equals the old baseline to ≤1e-6, with **zero mismatches**. The earlier
investigation's "9 mismatches" were an artifact of joining by (match, market): a series
with multiple reads keeps only the latest committed belief, so an old settlement for a
superseded read is now bucketed as `superseded`, not a false mismatch. The 89
"no baseline" are `hhad`/`ttg` reads, which Package 4A does not score (a documented
had-only scope limit), plus the 27 dropped legacy factors (belief still imported
follow-market; only the factor attribution is absent).

**Conclusion:** nothing blocks a *fresh-start* cutover; the had scoring path is proven
faithful. The only bounded item is analytical *breadth* (hhad/ttg scoring) — a
follow-on, not a go-live blocker.

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

## 4. Adapter progress (flag-gated, inert by default)

The `NUTMEG_ONTOLOGY_V2` flag now exists (`AppSettings.ontology_v2`, default off). With
it unset the `decision-*` commands run the old JSONL path byte-for-byte; set, they route
to `nutmeg.decision.ontology_adapter`.

- **`decision-am` — cut over. ✅** `run_decision_am_v2` = fetch (best-effort, reused) →
  `market_day_ingest` into the kernel. No judgment, no money, no push. In the kernel the
  market snapshot *is* the market baseline, so the old JSONL "backfill shadow" step is
  unnecessary. Validated on a real production day (2026-07-19, read-only): 7 matches / 8
  snapshots / 14 teams ingested into a temp kernel.
- **`decision-read` — cut over. ✅** `run_decision_read_v2` commits each judged Read
  payload as a kernel ForecastRevision (old-style factors dropped + counted, new-style
  delta factors kept, unmapped markets rejected). Beliefs only — no money, no push. Read
  payloads carry kernel match ids (Claude reads them from the store after `am`).
- **`decision-close` — cut over (money core). ✅** `run_decision_close_v2` = express
  legs → kernel Tickets. The ¥400 cap stays enforced by the reused `compose_tickets`
  (single authoritative source); the kernel only stores its deterministic allocation.
  Each ticket is idempotency-keyed (re-run replays, never double-books); a leg with no
  committed Read or no matching selection is skipped and counted — never a fabricated
  bet. Empty legs = empty slate (空仓合法).
- **`decision-settle` — cut over. ✅** `run_decision_settle_v2` = reconcile (record
  outcomes from `daily/<date>/results.json` + settle each match's tickets; a match with
  no result is skipped — never a pending settlement) → `calibrate`.
- **Full loop validated on real data (2026-07-19, read-only temp kernel):** am (7 matches
  / 8 snapshots) → read (7/7) → express (**1 main ticket ¥100** — the ¥400 main-bucket
  cap) → settle (1 settled) → calibrate (3 scorecards).

> **Critical:** `NUTMEG_ONTOLOGY_V2` is a **single global flag** — setting it routes all
> four verbs. All four now have a v2 path, so enabling it is coherent — but keep it OFF in
> production until the **remaining follow-ons land** and a full shadow day (dry, no push)
> is reviewed. The flag stays a shadow-only tool until then.

## 5. Still open (honest, before flag-on)

- **capture-closing (CLV) v2** — close's closing-snapshot capture is not yet ported; the
  Ticket-Price CLV axis stays empty until it lands (Brier/settlement are unaffected).
- **v2 report renderer** — close/settle emit a text summary; the PDF report and Telegram
  push are **not** ported (the v2 report never pushes — it says so if `--dispatch`
  `--no-dry-run` is passed). No live push can happen through v2 yet.
- Brier reconciliation is clean (0 mismatches). The only bounded analytical item is
  breadth — Package 4A scores `had` only, so `hhad`/`ttg` reads have no rebuilt score yet.
  A scoring follow-on, not a go-live blocker.

Once capture-closing + the report renderer land, run a full **shadow day** with the flag
on (dry, no `--dispatch-telegram --no-dry-run`), review it, then follow §2 steps 5–6 to
restore the schedules — the single irreversible go-live step, on explicit user approval.
