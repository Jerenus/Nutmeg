# Nutmeg Intelligence OS M6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local reliability evidence, reproducible recovery, deterministic release gates, observability, and a judge-only ReleaseApproval that remains blocked until real 14-day JCZQ and Zucai soak exists.

**Architecture:** Migration 14 stores immutable evidence and approvals in SQLite. Pure policy validators and a release evaluator consume only typed rows; backup/restore and scheduler inspectors emit canonical reports that enter through the same Action boundary. Product API/UI and CLI expose the resulting state without duplicating gate arithmetic.

**Tech Stack:** Python 3.12, SQLAlchemy Core, SQLite backup API, DuckDB rebuilds, FastAPI/Jinja2, Typer, plistlib, pytest, Ruff, local Chrome browser verification.

**Design:** `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-m6-design.md`

---

## Scope and file structure

New modules:

- `nutmeg/ontology/repository/schema_reliability.py`: migration-14 table declarations.
- `nutmeg/ontology/repository/reliability.py`: typed evidence and approval persistence.
- `nutmeg/ontology/reliability/models.py`: immutable ontology rows.
- `nutmeg/ontology/actions/reliability_actions.py`: evidence and approval Actions.
- `nutmeg/reliability/contracts.py`: allowlists, fault/performance validators, gate DTOs.
- `nutmeg/reliability/release.py`: deterministic release evaluation and snapshot hash.
- `nutmeg/reliability/backup.py`: atomic backup and isolated restore drill.
- `nutmeg/reliability/scheduler.py`: read-only plist/runtime/SOP authority inspection.
- `nutmeg/reliability/metrics.py`: bounded process-local route metrics.
- `nutmeg/interfaces/cli/reliability.py`: explicit local reliability commands.
- `nutmeg/interfaces/web/templates/product/release.html`: release workspace.
- `docs/nutmeg-intelligence-os-m6-operations.md`: operator contract.

New tests live under `tests/reliability/`, `tests/ontology/`, and `tests/product/`.

## Task 1: Migration 14 and typed persistence

**Files:** schema, models, migrations, repository, UoW, kernel status, migration tests.

- [x] **Step 1: Write RED tests**

Create tests that initialize through migration 14, assert the two tables and exact
permissions, round-trip JSON/source refs, reject duplicate content hashes, paginate
evidence deterministically, and persist one approval per release version.

```python
with OntologyUnitOfWork(kernel.engine) as uow:
    uow.reliability.insert_evidence(evidence)
    assert uow.reliability.evidence(evidence.reliability_evidence_id) == evidence
    assert uow.reliability.latest_by_kind("fault_matrix").content_hash == "a" * 64
```

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_m6_reliability_migration.py -q`

Expected: schema/module imports fail.

- [x] **Step 3: Implement exact rows and repository**

Use frozen dataclasses matching the design. Repository methods are:

```python
insert_evidence(row) -> None
evidence(evidence_id) -> ReliabilityEvidenceRow | None
evidence_by_hash(content_hash) -> ReliabilityEvidenceRow | None
list_evidence(kind=None, recorded_to=None) -> list[ReliabilityEvidenceRow]
latest_by_kind(kind) -> ReliabilityEvidenceRow | None
insert_approval(row) -> None
approval_for_release(release_version) -> ReleaseApprovalRow | None
```

Append migration 14 after migration 13 and grant `record_reliability_evidence` to
deterministic/judge roles and `approve_release` only to judge.

- [x] **Step 4: Verify GREEN and commit**

Run migration tests plus all prior migration tests and Ruff. Commit:
`feat(ontology): add reliability evidence ledger`.

## Task 2: Strict evidence Actions and report validators

**Files:** reliability contracts/actions, wiring, tests.

- [x] **Step 1: Write RED validator and Action tests**

Cover aware bounds, exact kind allowlist, `observed_from <= observed_to`, finite JSON
numbers, source refs, canonical content hash, role denial, idempotency, rollback, strict
fault matrix, strict performance budgets, and soak non-dispatch/non-synthetic fields.

```python
assert validate_fault_matrix(report).passed is True
with pytest.raises(ValueError, match="missing fault scenario"):
    validate_fault_matrix({"scenarios": []})
with pytest.raises(ValueError, match="volume_multiplier"):
    validate_performance_report({"volume_multiplier": 9, "metrics": {}})
```

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/reliability/test_contracts.py tests/ontology/test_reliability_actions.py -q`

- [x] **Step 3: Implement validators and record Action**

`RecordReliabilityEvidenceRequest` derives its content hash from canonical kind,
workflow/date/bounds/report/source refs. The Action reuses an existing row for equal
content and records a new immutable row otherwise. Validation dispatch is exact:

```python
VALIDATORS = {
    "fault_matrix": validate_fault_matrix,
    "performance": validate_performance_report,
    "soak_run": validate_soak_report,
}
```

Other evidence kinds require `candidate_commit`, `policy_version=release-v1`, and
`checks` with at least one boolean value; `status=passed` is valid only when all checks
are true.

- [x] **Step 4: Verify GREEN and commit**

Run focused tests and Ruff. Commit: `feat(reliability): govern release evidence`.

## Task 3: Release evaluator and guarded approval

**Files:** release evaluator, approval Action, repository queries, tests.

- [x] **Step 1: Write RED policy tests**

Start with an empty ledger and assert six blocked gates. Seed one evidence kind at a
time. Prove candidate mismatch, failed/stale rows, future soak, synthetic/dispatch soak,
13-day spans, one missing workflow, and one divergence all block. A clearly labeled
test fixture with 14 dates per workflow may prove the green path.

```python
evaluation = evaluator.evaluate("v1.0.0", candidate_commit=COMMIT, evaluated_at=NOW)
assert evaluation.ready is False
assert evaluation.gates["G6"].code == "soak_days_insufficient"
```

Approval tests prove AI denial, blocked judge request, stale snapshot conflict, exact
green approval, idempotent replay, and superseded status after new evidence.

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/reliability/test_release_policy.py tests/ontology/test_release_actions.py -q`

- [x] **Step 3: Implement pure evaluation and in-transaction recheck**

`ReleaseEvaluator.evaluate()` selects current evidence for the exact candidate,
computes G1-G6, and hashes this canonical material:

```python
snapshot = canonical_json({
    "release_version": release_version,
    "candidate_commit": candidate_commit,
    "policy_version": "release-v1",
    "gates": [gate.to_dict() for gate in gates],
    "evidence": [(row.id, row.content_hash) for row in selected],
})
```

`ApproveReleaseRequest` carries release/candidate/snapshot/reason. The handler invokes
the same evaluator on its UoW repository, rejects non-green or mismatched snapshots,
then inserts one immutable approval.

- [x] **Step 4: Verify GREEN and commit**

Commit: `feat(reliability): enforce release approval gates`.

## Task 4: Atomic backup and restore drill

**Files:** backup service, tests, operations fixtures.

- [x] **Step 1: Write RED backup tests**

Use an isolated M5 lifecycle store. Assert explicit acknowledgement/destination, SQLite
backup integrity, DuckDB/CAS hashes, action HWM, outbox cursor, table counts, sorted
ticket hashes, and ledger balances. Inject a copy/replace failure and prove the prior
published backup is complete and unchanged. Tamper each component and prove restore
fails before reporting success.

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/reliability/test_backup.py -q`

- [x] **Step 3: Implement canonical manifest and restore comparison**

Public API:

```python
create_backup(kernel, destination, requested_at, acknowledge_writers_stopped) -> BackupResult
run_restore_drill(backup_dir, restore_data_dir, requested_at) -> RestoreDrillReport
```

Build in `destination.parent / ("." + destination.name + ".staging-<uuid>")`, use
`sqlite3.Connection.backup`, hash every copied file, fsync manifests/files/directories,
and publish with `os.replace`. Restore only into an absent directory, verify hashes,
open schema 14 with integrity `ok`, compare facts, then rebuild projections.

- [x] **Step 4: Verify GREEN and commit**

Commit: `feat(reliability): add atomic recovery drills`.

## Task 5: Scheduler authority inspector and reliability CLI

**Files:** scheduler inspector, CLI, registration, operations doc, tests.

- [x] **Step 1: Write RED inspector/CLI tests**

Parse fixture plists and runtime JSON. Cover missing/duplicate stage, wrong root, wrong
stage argument, missing calendar/log path, unloaded stage, ontology-v2 false, legacy
scoreboard authority, incomplete SOP, secret redaction, canonical output, required
acknowledgements, resolved targets, and no default production mutation.

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/reliability/test_scheduler.py tests/product/test_m6_cli.py -q`

- [x] **Step 3: Implement read-only inspection and commands**

Commands:

```text
reliability status --data-dir --release-version --candidate-commit --evaluated-at
reliability record --data-dir --kind --report-file --observed-from --observed-to --acknowledge
reliability backup-create --data-dir --destination --requested-at --acknowledge-writers-stopped
reliability restore-drill --backup-dir --restore-data-dir --requested-at
reliability scheduler-review --data-dir --plist ... --runtime-report --sop-file ... --requested-at --acknowledge
reliability approve-release --data-dir --release-version --candidate-commit --expected-snapshot --reason --requested-at --approve
```

Every mutation includes resolved `targets`; scheduler review calls no subprocess.

- [x] **Step 4: Document and commit**

Write `docs/nutmeg-intelligence-os-m6-operations.md`. Commit:
`feat(cli): add guarded reliability operations`.

## Task 6: Product release DTOs, queries, API, and Action mapping

**Files:** product contracts/repository/queries/actions/API/wiring, tests.

- [x] **Step 1: Write RED contracts/query/API tests**

Add strict DTOs for gate, evidence, soak coverage, release approval, release response,
route metrics, and reliability metrics. Exercise `GET /api/v1/release` and
`GET /api/v1/reliability/metrics`; verify blocked real-empty state, green fixture state,
strict aware time/candidate parameters, no report blobs/secrets, and generic
`approve_release` actor assignment/stale snapshot handling.

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m6_contracts.py tests/product/test_m6_api.py -q`

- [x] **Step 3: Implement product adapters**

Query service converts `ReleaseEvaluation` and local metrics to strict DTOs. API routes
are read-only; Action gateway maps only `approve_release` and derives judge identity
server-side. Unexpected evidence report details remain summarized/allowlisted.

- [x] **Step 4: Verify GREEN and commit**

Commit: `feat(api): expose governed release readiness`.

## Task 7: Route metrics and Release workspace

**Files:** metrics registry, API middleware, release template, layout/CSS/JS, UI tests.

- [x] **Step 1: Write RED metrics and SSR tests**

Prove bounded samples, route-template aggregation, count/error/p95, no query/ID capture,
and reset on process restart. `/release` must SSR six gates, exact block codes, two soak
calendars, performance budgets, backup/scheduler evidence, and current approval. It must
not render an enabled approval form while blocked or contain client gate arithmetic.

- [x] **Step 2: Verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/reliability/test_metrics.py tests/product/test_m6_ui.py -q`

- [x] **Step 3: Implement bounded telemetry and SSR workspace**

Use `deque(maxlen=512)` per allowlisted route template and `perf_counter_ns`. Middleware
records after response and on exceptions; payloads and raw URLs are never retained.
Release UI uses full-width gate rows and compact evidence tables, reuses existing status
tokens, keeps controls at least 44px, and performs only Action submission in JS.

- [x] **Step 4: Verify GREEN and commit**

Commit: `feat(ui): add reliability release workspace`.

## Task 8: Fault, performance, lifecycle, and recovery E2E

**Files:** M6 E2E/fault/performance tests and fixtures.

- [x] **Step 1: Add executable fault matrix tests**

Map all eight `fault-v1` rows to real tests. Reuse provider/schema, Action duplicate,
SSE, and projection cases; add SQLite-lock and backup-interruption cases. Only after
each behavior passes may the test build a valid fault report.

- [x] **Step 2: Add reference performance test**

Build a deterministic isolated reference store with declared multiplier 10. Warm each
query/Action/event path, collect at least 20 samples, compute p95 server-side, validate
the report against fixed budgets, and store timings in test output. Never weaken a
budget based on the observed result.

- [x] **Step 3: Add full product lifecycle browser/API E2E**

Drive operations -> match -> Forecast -> ticket audit/confirmation -> settlement ->
review -> release. Exercise empty, conflict, blocked, DuckDB offline/restored, event
reconnect, keyboard focus, and approval-blocked states. Seeded 14-day rows may prove the
approval path only inside this test.

- [x] **Step 4: Run and commit**

Run all M1-M6 E2E, fault, recovery, and performance tests. Commit:
`test(product): prove M6 reliability lifecycle`.

## Task 9: Completion evidence and truthful real-state gate

**Files:** M6 evidence README/screenshots; defects only if verification exposes them.

- [x] **Step 1: Run independent critique**

Review design, plan, base-to-head diff, migrations, Action authority, backup safety,
snapshot logic, and tests. Resolve every Critical/Important finding with RED-GREEN.

- [x] **Step 2: Run full gates**

```bash
UV_FROZEN=1 uv run pytest -q
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall -q nutmeg scripts
UV_FROZEN=1 uv run pre-commit run --all-files
git diff --check main...HEAD
git diff --check
```

- [x] **Step 3: Run isolated recovery and project replay**

Create/restore/verify a temporary backup, rebuild projections, exercise event cursor
recovery, and run the project decision sense/backfill/settle/close recipe only in a
temporary root with dry-run dispatch.

- [x] **Step 4: Capture browser evidence**

At 1440x1000 and 390x844 capture the complete lifecycle and `/release` blocked state;
capture DuckDB offline/restored and keyboard focus. Require HTTP/assets 200, zero severe
console entries, no viewport overflow/overlap, and visible stable block codes.

- [x] **Step 5: Prove production non-mutation and real soak block**

Hash production scoreboard/ontology/SOP/harness files before/after. Run read-only
release evaluation against a copied production store. Record the actual missing soak
dates and prove no production ReleaseApproval exists or is created.

- [x] **Step 6: Record and commit evidence**

Create `docs/superpowers/evidence/m6/README.md`, mark this plan complete, and commit:
`docs(product): record M6 verification`.

## Coverage

| M6 requirement | Tasks |
| --- | --- |
| Reliability evidence and local observability | 1-3, 6-7 |
| Backup/restore with invariant comparison | 4, 8-9 |
| Fixed performance targets at 10x | 2, 8-9 |
| Fault injection and safe outcomes | 2, 4, 8-9 |
| Full lifecycle browser E2E | 6-9 |
| Real soak collection and truthful gating | 2-3, 5, 9 |
| Scheduler/authority review without mutation | 5, 9 |
| Guarded human ReleaseApproval | 1-3, 5-9 |

M6 software completion does not make the real release gate green. The truthful terminal
state is code verified, evidence collection operational, and release blocked until real
14-day JCZQ and Zucai soak satisfies `release-v1`.
