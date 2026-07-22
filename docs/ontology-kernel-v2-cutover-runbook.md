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
- **`decision-close` capture-closing — cut over. ✅** `_capture_closing_v2` ingests a
  closing market snapshot (CLV reference) from `daily/<date>/bold_odds_closing.json` via
  `market_day_ingest` with `snapshot_kind='closing'`; absent file → skip (CLV empty,
  Brier/settlement unaffected).
- **`decision-settle` — cut over. ✅** `run_decision_settle_v2` = reconcile (record
  outcomes from `daily/<date>/results.json` + settle each match's tickets; a match with
  no result is skipped — never a pending settlement) → `calibrate`.
- **v2 report — cut over. ✅** `_report_v2` renders a kernel-fed markdown daily report
  (matches / forecasts / tickets / settlements / stake·payout·ledger / coverage /
  calibration) to `daily/<date>/decision-report-v2-<date>.md`, and — only when
  `--dispatch-telegram` is passed — publishes it through the notification service, gated
  by `--dry-run` (default dry: **never** a live send unless `--no-dry-run` is explicit).
- **Full loop validated on real data (2026-07-19, read-only temp kernel):** am (7 matches)
  → read (7/7) → close (capture-closing 8 closing snapshots → express **1 main ticket
  ¥100** → report) → settle (reconcile 1 → calibrate 3 scorecards → report). Report:
  ¥100 staked / ¥200 payout / ¥100 net, **closing coverage 100%**. No push (dry).

> **`NUTMEG_ONTOLOGY_V2` is now shadow-ready:** all four verbs + capture-closing + the
> report (with a dry-gated push) are on the kernel. It is still a **single global flag**;
> keep it OFF in production until a full **shadow day** on real data is reviewed (below).

## 5. Still open (honest, before flag-on)

**P0 closed (2026-07-22):** settlement is now **odds-faithful** — `bet_legs.entry_odds`
(migration 9) is required at approve and settles payout = stake × Π(odds of WIN legs);
VOID legs push (×1.0), losses pay 0; legacy pre-migration legs stay auditable under
`settlement_method_version='had-3way-v1'`. And settle fetches **okooo live results**
automatically (竞彩号 → matchId → kernel match), with manual `results.json` as override;
unfinished matches skip and settle idempotently on the next day's re-run.

- **PDF report** — the v2 report is markdown + Telegram text; the reportlab PDF is not
  ported (a rendering nicety — the markdown carries the same content). Not a blocker.
- **Market breadth** — the kernel ingests/expresses/scores `had` only (parsers drop the
  sporttery hhad/ttg/crs pools). The judgment layer's ttg/handicap axes cannot be priced
  or expressed until this lands — the recommended next package, not a settlement blocker.
- Brier reconciliation is clean (0 mismatches).

**Ready for the shadow day.** Provision the prod kernel store (§2.2), set
`NUTMEG_ONTOLOGY_V2=1`, run one live day's `decision-am/read/close/settle` **dry** (no
`--dispatch-telegram --no-dry-run`), review the markdown report + `nutmeg ontology
status`, then — on explicit user approval — §2 steps 5–6 restore the schedules (the one
irreversible go-live step).
