# Nutmeg Intelligence OS M5 Operations Contract

Date: 2026-08-24
Scope: settlement learning, scoreboard projection, and isolated authority rehearsal

## 1. Authority boundary

M5 has two scoreboard authority states:

| State | Authoritative source | Allowed next operation |
| --- | --- | --- |
| `legacy` | The exact bytes of the existing `scoreboard.json` | Record observations, rebuild projections, shadow, then approve cutover |
| `ontology` | SQLite ontology objects and versioned DuckDB projections | Export and verify generated compatibility JSON |

Migration 13 seeds one `scoreboard_authority:primary` row in `legacy` state at
version 1. Cutover is a one-way Action in M5. There is no command that changes an
`ontology` authority row back to `legacy`, and direct database edits are prohibited.

M5 code completion does not authorize a production scoreboard cutover. Production
cutover remains a separate human operation after the five authority documents are
updated, reviewed, backed up, and supplied explicitly to the cutover command. Feature
verification must use an isolated data root and fixture SOP files only.

## 2. Role matrix

| Operation | `judge_operator` | `deterministic_system` | AI roles | Browser |
| --- | --- | --- | --- | --- |
| `RecordScoreboardObservation` | Allowed | Denied | Denied and audited | May submit; server fixes the actor role |
| `RecordScoreboardShadowReview` | Denied | Allowed | Denied and audited | Not exposed |
| `ApproveScoreboardCutover` | Allowed with explicit approval | Denied | Denied and audited | Not exposed |
| `RecordScoreboardExport` | Denied | Allowed | Denied and audited | Not exposed |
| Apply a factor lifecycle proposal | Allowed through the existing judge Action | Denied | Denied and audited | May submit; server fixes the actor role |

AI can propose interpretations and lifecycle changes, but it cannot record manual
scoreboard truth, change factor state, switch authority, or export compatibility state.

## 3. Manual observations

Do not parse a legacy tally or prose into a numeric fact. The operator must record the
fact explicitly with stable group and metric keys, non-empty tally/detail/status, an
aware effective timestamp, and at least one real ontology evidence reference. Numeric
fields are optional; a supplied denominator must be non-negative and a numerator must
not exceed it.

Use a new immutable observation for a correction. Pass the prior observation ID with
`--supersedes`; keep the same group and metric keys. The referenced observation must
be the single current leaf for that group/metric. Parallel leaves and revisions of an
older, already-superseded row are rejected. Never overwrite the prior row.

```bash
UV_FROZEN=1 uv run nutmeg scoreboard observe \
  --data-dir /absolute/path/to/isolated-data \
  --group-key chains \
  --metric-key main \
  --tally 7/10 \
  --detail "operator-reviewed settled chain count" \
  --status active \
  --numerator 7 \
  --denominator 10 \
  --value 0.7 \
  --unit ratio \
  --evidence-type adjudication \
  --evidence-id ADJUDICATION_ID \
  --effective-at 2026-08-24T10:00:00+08:00 \
  --requested-at 2026-08-24T10:05:00+08:00 \
  --acknowledge-manual-source
```

After the last observation, run the current ontology reconcile/calibrate workflow and
record its `sb-v1` projection version and source high-watermark. Do not use the legacy
`decision-calibrate` JSONL command as a substitute for the M5 ontology projection.

## 4. Required operating order

The order is strict:

1. Stop writes to the isolated candidate store and take a coherent backup.
2. Record or supersede every manual-only metric through
   `RecordScoreboardObservation`.
3. Reconcile operational outcomes and settlements, then run ontology calibrate. Confirm
   the projection is successful and has one unambiguous scoreboard identity.
4. Hash the exact legacy file and prepare a complete classification JSON document.
5. Run `shadow` with the exact projection version and high-watermark.
6. Inspect `status`. Resolve every `unexplained` row by correcting a source, recording
   a supported manual observation, or documenting a supported source correction. Then
   rebuild and shadow again. A shadow Action itself advances the operational Action
   log, so every repeated shadow requires a fresh calibrate first. Do not proceed with
   unexplained differences.
7. Freeze operational writes. Supply the latest review, authority version, exact legacy
   file, projection identity, all five SOP files, and `--approve` to `cutover`.
8. Export to a previously absent destination, or to the exact legacy path whose current
   bytes still hash to the cutover `legacy_sha256`, with the current authority version.
9. Run `verify-export`, archive the status output and hashes, then resume only the
   workflows approved by the production runbook.

The classification file must cover every object-valued legacy group/metric pair exactly
once. Allowed classifications are:

| Classification | Required proof |
| --- | --- |
| `matched` | Target plane/group/metric exists and its value exactly equals the legacy value |
| `formal_manual` | A current observation exists for the same group and metric |
| `source_correction` | Non-empty reason and evidence references |
| `unexplained` | Visible discrepancy; always blocks cutover |

## 5. Five-document gate

Each of these files must exist, no extra authority file may be supplied, and every file
must contain all five exact statements below:

```text
CONSTITUTION.md
RUNBOOK.md
RULEBOOK.md
AGENTS.md
CLAUDE.md
```

```text
scoreboard authority: ontology
scoreboard.json: generated read-only compatibility output
reconcile/calibrate rebuilds and exports scoreboard.json
manual facts: RecordScoreboardObservation
direct scoreboard.json edits are errors
```

The checker reads these files but never writes them. Production documents are
user-owned; feature tests use only `tests/fixtures/m5/sop/` copies.

## 6. Exact identity and concurrency gates

Four values bind a cutover:

- `legacy_sha256`: SHA-256 of the exact legacy file bytes captured by shadow. Any byte
  change, including whitespace, blocks cutover.
- `projection_version`: the sole version in `scoreboard_metrics`, currently `sb-v1`.
- `source_high_watermark`: the SQLite Action row watermark embedded by calibrate.
- `expected_authority_version`: optimistic version from `scoreboard status`.

The latest shadow review must be `succeeded`, have zero unexplained rows, and match the
legacy hash and projection identity. A newer review supersedes an older review for
cutover purposes. Cutover increments authority version once; first export records its
hash plus projection identity and increments the version again. A repeated export at
the same projection identity returns the recorded bytes; a newer successful projection
atomically refreshes the export and advances the stored projection identity. Always
reread status immediately before a mutating command. A version conflict is a
reload-and-review signal, never permission to retry with a guessed version.

No business, observation, settlement, lifecycle, or authority mutation may occur
between the final calibrate, shadow inspection, and cutover. If one occurs, rebuild the
projection and repeat shadow review before seeking approval. Cutover accepts only the
exact legacy artifact ingest and shadow-review Actions bound to that review after the
projection watermark. Export similarly rejects any committed business Action newer
than its current projection; administrative shadow/cutover/export Actions do not alter
scoreboard metric truth.

## 7. CLI authority sequence

Every command requires an explicit data root and performs no network action:

```bash
UV_FROZEN=1 uv run nutmeg scoreboard status \
  --data-dir /absolute/path/to/isolated-data

UV_FROZEN=1 uv run nutmeg scoreboard shadow \
  --data-dir /absolute/path/to/isolated-data \
  --legacy-file /absolute/path/to/legacy-scoreboard.json \
  --classification-file /absolute/path/to/classification.json \
  --projection-version sb-v1 \
  --source-high-watermark HIGH_WATERMARK \
  --requested-at 2026-08-24T11:00:00+08:00 \
  --acknowledge-manual-source

UV_FROZEN=1 uv run nutmeg scoreboard cutover \
  --data-dir /absolute/path/to/isolated-data \
  --legacy-file /absolute/path/to/legacy-scoreboard.json \
  --review-id SHADOW_REVIEW_ID \
  --expected-authority-version AUTHORITY_VERSION \
  --projection-version sb-v1 \
  --source-high-watermark HIGH_WATERMARK \
  --sop-file /absolute/path/to/CONSTITUTION.md \
  --sop-file /absolute/path/to/RUNBOOK.md \
  --sop-file /absolute/path/to/RULEBOOK.md \
  --sop-file /absolute/path/to/AGENTS.md \
  --sop-file /absolute/path/to/CLAUDE.md \
  --requested-at 2026-08-24T11:10:00+08:00 \
  --approve

UV_FROZEN=1 uv run nutmeg scoreboard export \
  --data-dir /absolute/path/to/isolated-data \
  --destination /absolute/path/to/compatibility/scoreboard.json \
  --expected-authority-version AUTHORITY_VERSION \
  --requested-at 2026-08-24T11:15:00+08:00

UV_FROZEN=1 uv run nutmeg scoreboard verify-export \
  --data-dir /absolute/path/to/isolated-data \
  --destination /absolute/path/to/compatibility/scoreboard.json
```

All output is canonical JSON. Mutating results include a `targets` object containing
resolved absolute data, input, SOP, and destination paths as applicable. Preserve those
targets together with the Action IDs, shadow review ID, authority versions, projection
identity, legacy hash, and export hash in the change record.

## 8. Drift and atomic-write recovery

`scoreboard.json` is generated output after cutover. A changed, missing, or untracked
destination raises `scoreboard_export_drift`; it is never imported. The sole first-run
exception is the exact legacy destination whose bytes still match the authority row's
`legacy_sha256`; export may atomically replace that file with generated output.

| Condition | Required response |
| --- | --- |
| File hash differs from recorded export hash | Stop writers, preserve both bytes and hashes, inspect the diff and Action history, then restore the exact recorded file from a verified backup. |
| Recorded file is missing | Restore the exact file whose SHA-256 equals the authority row. If unavailable, restore the database, DuckDB, CAS, and compatibility file from one coherent pre-export backup. |
| Destination exists before first tracked export and differs from `legacy_sha256` | Move the unexpected file into incident evidence, verify the intended destination is absent, and rerun export only after review. |
| Process fails before `os.replace` | The prior complete destination remains; remove no evidence and rerun only after `verify-export` or status establishes a coherent authority state. |
| Export Action committed but file replacement failed | Do not edit SQLite or invent bytes. Restore the exact recorded file if backed up; otherwise restore the whole coherent pre-export recovery point and repeat the reviewed sequence. |
| Projection is stale against committed business Actions | Reconcile/calibrate before export; never reuse stale projection bytes. |
| A newer current projection exists after cutover | Export builds new canonical bytes, records the new projection identity, and atomically replaces the prior tracked output. |

Atomic write creates and fsyncs a temporary file in the destination directory, replaces
the destination, then fsyncs the directory. A failed replace leaves the prior complete
file intact and removes its temporary file. SQLite, DuckDB, CAS, the exact legacy bytes,
and the compatibility file must be backed up and restored as one authority unit.

## 9. Rollback boundary

Before cutover, rollback means discarding the isolated candidate and continuing to use
the untouched legacy file. After cutover, M5 supports no in-place reversal. Prefer a
forward repair. If a genuine disaster requires rollback, stop all writes and restore a
coherent pre-cutover backup of the entire authority unit; do not restore only the JSON
or only the SQLite database. Any operational Actions written after that recovery point
must be reconciled separately before service resumes.

Never treat a copied `scoreboard.json` as a database restore and never import generated
compatibility output back as authority.

## 10. Isolated rehearsal and production prohibition

The self-contained authority lifecycle test creates only temporary stores and is the
preferred rehearsal:

```bash
M5_REHEARSAL_ROOT="$(mktemp -d)"
UV_FROZEN=1 uv run pytest \
  tests/product/test_cli.py \
  tests/product/test_m5_e2e.py \
  tests/scoreboard/test_authority.py \
  --basetemp "${M5_REHEARSAL_ROOT}/pytest" -q
```

For a manual rehearsal, copy a frozen non-production store into a fresh explicit data
root, hash the source before and after, initialize/migrate only the copy, and use the CLI
sequence above with copies of `tests/fixtures/m5/sop/`. Never point a feature test,
browser session, replay, shadow, cutover, or export at production `.nutmeg-data`.

The following remain prohibited during M5 verification: providers/connectors,
Telegram dispatch, scheduler changes, public binding, live betting, funds actions,
production SOP edits, and production authority mutation.

## 11. M6 handoff

M6 must add backup/restore drills, explicit recovery automation, performance targets,
fault injection, full browser lifecycle E2E, scheduler/authority review, and real soak
evidence collection. A guarded `ReleaseApproval` must remain blocked until the required
calendar-duration evidence actually exists. No synthetic test run may be represented as
14 days of production or shadow evidence.
