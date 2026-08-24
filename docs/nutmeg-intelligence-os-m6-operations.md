# Nutmeg Intelligence OS M6 Operations

M6 records local release evidence without changing providers, schedules, dispatch,
Telegram, betting, or funds. Every path is explicit. Mutation commands emit resolved
`targets` and require an acknowledgement or approval flag.

## Release status

```bash
uv run nutmeg reliability status \
  --data-dir /absolute/isolated-data \
  --release-version v1.0.0 \
  --candidate-commit <git-commit> \
  --evaluated-at 2026-08-24T12:00:00+00:00
```

The result is canonical JSON. `ready=true` means the current evidence snapshot passes
`release-v1`; it does not dispatch or deploy anything. Real approval remains blocked
until both JCZQ and Zucai have 14 distinct, non-dispatch, non-synthetic calendar days
with zero unexplained divergence.

## Evidence

```bash
uv run nutmeg reliability record \
  --data-dir /absolute/isolated-data \
  --kind deterministic_suite \
  --report-file /absolute/report.json \
  --observed-from 2026-08-24T11:00:00+00:00 \
  --observed-to 2026-08-24T12:00:00+00:00 \
  --requested-at 2026-08-24T12:00:00+00:00 \
  --acknowledge
```

Reports use `policy_version=release-v1`, a candidate commit, and typed checks. Fault,
performance, and soak reports use their fixed schemas. Soak recording additionally
requires `--workflow jczq|zucai --business-date YYYY-MM-DD`. Synthetic or dispatch
soak reports cannot enter the ledger.

## Backup and restore drill

Stop writers before backup, then acknowledge that state explicitly:

```bash
uv run nutmeg reliability backup-create \
  --data-dir /absolute/isolated-data \
  --destination /absolute/new-backup \
  --requested-at 2026-08-24T12:00:00+00:00 \
  --acknowledge-writers-stopped

uv run nutmeg reliability restore-drill \
  --backup-dir /absolute/new-backup \
  --restore-data-dir /absolute/new-restore-root \
  --requested-at 2026-08-24T12:00:00+00:00
```

The backup destination and restore root must not exist or overlap their source. The
restore drill verifies every component hash, SQLite integrity, Action/outbox watermarks,
table counts, ticket hashes, and ledger balances before rebuilding DuckDB projections.

## Scheduler review

The runtime report is an operator-supplied JSON snapshot with schema
`scheduler-runtime-v1`, `candidate_commit`, `loaded_labels`, and
`effective_environment.NUTMEG_ONTOLOGY_V2`. Other environment values are never emitted.

```bash
uv run nutmeg reliability scheduler-review \
  --data-dir /absolute/isolated-data \
  --plist /absolute/com.nutmeg.decision.am.plist \
  --plist /absolute/com.nutmeg.decision.close.plist \
  --plist /absolute/com.nutmeg.decision.settle.plist \
  --runtime-report /absolute/runtime.json \
  --sop-file /absolute/CONSTITUTION.md \
  --sop-file /absolute/RUNBOOK.md \
  --sop-file /absolute/RULEBOOK.md \
  --sop-file /absolute/AGENTS.md \
  --sop-file /absolute/CLAUDE.md \
  --project-root /absolute/Nutmeg \
  --requested-at 2026-08-24T12:00:00+00:00 \
  --acknowledge
```

This command parses files only. It never invokes or mutates `launchctl`.

## Approval

Only Jun's judge identity may approve the exact current green snapshot:

```bash
uv run nutmeg reliability approve-release \
  --data-dir /absolute/isolated-data \
  --release-version v1.0.0 \
  --candidate-commit <git-commit> \
  --expected-snapshot <sha256-from-status> \
  --reason "reviewed release-v1 evidence" \
  --requested-at 2026-08-24T12:00:00+00:00 \
  --approve
```

The Action re-evaluates all gates inside its transaction. A blocked gate or changed
snapshot fails. Approval records no deployment, scheduler, dispatch, betting, or funds
action.
