# JCZQ Historical Replay Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete an isolated, provenance-stamped 2026-09-19 JCZQ A2-A7 replay that can satisfy the ontology-v2 cutover gate without impersonating Jun, fabricating source time, or contaminating prospective RSI evidence.

**Architecture:** Add one schema-35 replay authority layer beneath the existing Action services: a durable replay-run record, replay provenance on every Action, and a replay-bound `ActionService`. Reuse the existing proposal, adjudication, Forecast, prescription, candidate, audit, terminal, result, review, and RSI Actions; the replay runner only freezes historical inputs and orchestrates those existing contracts. Derive the acceptance report from the isolated ontology, then have the cutover gate independently recompute and validate it.

**Tech Stack:** Python 3.12, SQLAlchemy Core, SQLite, Typer, pytest, existing Nutmeg ontology/product services.

---

## File Map

- `nutmeg/ontology/repository/schema.py`: declare replay-run storage and Action provenance columns.
- `nutmeg/ontology/repository/migrations.py`: additive schema-35 migration, replay permissions, constraints, and append-only guards.
- `nutmeg/ontology/repository/replay.py`: typed replay-run persistence and queries.
- `nutmeg/ontology/repository/actions.py`: round-trip Action replay provenance and replay-scoped queries.
- `nutmeg/ontology/repository/unit_of_work.py`: expose the replay repository.
- `nutmeg/ontology/actions/models.py`: add `REPLAY_ADJUDICATOR` and the paired replay envelope fields.
- `nutmeg/ontology/actions/service.py`: bind and enforce replay context for all nested Actions.
- `nutmeg/ontology/actions/replay_actions.py`: typed start/finish replay Actions.
- `nutmeg/ontology/wiring.py`: construct production and replay-bound Action services explicitly.
- `nutmeg/product/jczq_replay_inputs.py`: freeze and hash the board, market, Read, research, and result inputs.
- `nutmeg/product/jczq_replay_adjudication.py`: map draft Reads to replay proposals and adjudicate/commit Forecasts.
- `nutmeg/product/jczq_replay_workflow.py`: orchestrate A3-A7 through existing services.
- `nutmeg/product/jczq_replay.py`: own run lifecycle, isolation checks, report derivation, and persistence.
- `nutmeg/product/jczq_cutover.py`: independently recompute the stronger report contract.
- `tests/ontology/test_migrations.py`: schema-35 migration contract.
- `tests/ontology/test_action_models.py`: request-hash and replay-envelope validation.
- `tests/ontology/test_action_service.py`: binding, nested propagation, and production/replay denial paths.
- `tests/ontology/test_replay_actions.py`: replay-run state machine and idempotency.
- `tests/product/operator_v2/test_jczq_replay_inputs.py`: frozen-manifest and missing-time quarantine behavior.
- `tests/product/operator_v2/test_jczq_replay_adjudication.py`: approve/revise/reject and Forecast lineage.
- `tests/product/operator_v2/test_jczq_replay_workflow.py`: A4-A7, no-ticket, results, and RSI isolation.
- `tests/product/operator_v2/test_jczq_20260919_replay.py`: full isolated replay and production-fingerprint gate.
- `tests/product/operator_v2/test_jczq_workflow_cli.py`: CLI and cutover report revalidation.

### Task 1: Schema 35 and Durable Replay Runs

**Files:**
- Modify: `nutmeg/ontology/repository/schema.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Create: `nutmeg/ontology/repository/replay.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `tests/ontology/test_migrations.py`
- Create: `tests/ontology/test_replay_repository.py`

- [ ] **Step 1: Write the failing migration test**

Add a test that initializes through migration 35 and asserts:

```python
assert migration_status(engine).current_version == 35
assert {
    "historical_replay_runs",
} <= set(inspect(engine).get_table_names())
columns = {column["name"] for column in inspect(engine).get_columns("actions")}
assert {"historical_replay", "replay_run_id"} <= columns
```

Also assert the database rejects the two invalid Action pairs `(1, NULL)` and `(0, non-NULL)`.

- [ ] **Step 2: Run the RED test**

Run: `uv run pytest tests/ontology/test_migrations.py -q`

Expected: FAIL because migration 35 and the replay columns do not exist.

- [ ] **Step 3: Add the schema declarations and migration**

Declare `historical_replay_runs` with immutable identity and terminal state fields:

```python
historical_replay_runs = Table(
    "historical_replay_runs",
    metadata,
    Column("replay_run_id", Text, primary_key=True),
    Column("business_date", Text, nullable=False),
    Column("source_root_fingerprint", Text, nullable=False),
    Column("source_manifest_hash", Text, nullable=False),
    Column("isolated_database_identity", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("production_before_json", Text, nullable=False),
    Column("production_after_json", Text),
    Column("report_sha256", Text),
    Column("failure_codes_json", Text, nullable=False, server_default=text("'[]'")),
    UniqueConstraint(
        "business_date", "source_manifest_hash", "isolated_database_identity",
        name="uq_historical_replay_identity",
    ),
)
```

Migration 35 must rebuild `actions` using the repository's established guarded-alter pattern so the pair constraint is enforced by SQLite:

```sql
CHECK (
  (historical_replay = 0 AND replay_run_id IS NULL) OR
  (historical_replay = 1 AND replay_run_id IS NOT NULL)
)
```

Add an append-only trigger for replay identity fields and permit only the state transition `running -> accepted|failed`, filling finish/report fields exactly once.

- [ ] **Step 4: Add the typed repository**

Define `HistoricalReplayRunRecord`, `insert_running`, `get`, and `finish` in `replay.py`. `finish` must use one conditional UPDATE whose WHERE clause includes `status = 'running'`; zero updated rows raises `ValueError("historical replay run is not active")`.

- [ ] **Step 5: Run repository and migration tests**

Run: `uv run pytest tests/ontology/test_migrations.py tests/ontology/test_replay_repository.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/repository/replay.py nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_migrations.py tests/ontology/test_replay_repository.py
git commit -m "feat(ontology): persist historical replay authority"
```

### Task 2: Replay Provenance in the Action Envelope

**Files:**
- Modify: `nutmeg/ontology/actions/models.py`
- Modify: `nutmeg/ontology/repository/actions.py`
- Modify: `nutmeg/ontology/repository/outbox.py`
- Modify: `tests/ontology/test_action_models.py`
- Modify: `tests/ontology/test_action_repository.py`
- Modify: `tests/ontology/test_outbox.py`

- [ ] **Step 1: Write replay-envelope RED tests**

Cover all four combinations:

```python
ActionCommand.create(..., historical_replay=False, replay_run_id=None)  # legal
ActionCommand.create(..., historical_replay=True, replay_run_id="replay-1")  # legal
with pytest.raises(ValueError, match="paired"):
    ActionCommand.create(..., historical_replay=True, replay_run_id=None)
with pytest.raises(ValueError, match="paired"):
    ActionCommand.create(..., historical_replay=False, replay_run_id="replay-1")
```

Assert changing either replay field changes `request_hash`, and persisted Actions/outbox payloads round-trip both fields.

- [ ] **Step 2: Run the RED tests**

Run: `uv run pytest tests/ontology/test_action_models.py tests/ontology/test_action_repository.py tests/ontology/test_outbox.py -q`

Expected: FAIL because `ActionCommand` has no replay provenance.

- [ ] **Step 3: Extend `ActionCommand` and `ActionRecord`**

Add defaulted fields after existing non-default fields:

```python
historical_replay: bool = False
replay_run_id: str | None = None
```

Validate the atomic pair and include both values in `request_material`. Persist them as explicit columns, not inside `payload_json`.

- [ ] **Step 4: Stamp outbox events**

Add the exact envelope fragment to every terminal outbox payload:

```python
"historical_replay": command.historical_replay,
"replay_run_id": command.replay_run_id,
```

- [ ] **Step 5: Run the focused suite**

Run: `uv run pytest tests/ontology/test_action_models.py tests/ontology/test_action_repository.py tests/ontology/test_outbox.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/models.py nutmeg/ontology/repository/actions.py nutmeg/ontology/repository/outbox.py tests/ontology/test_action_models.py tests/ontology/test_action_repository.py tests/ontology/test_outbox.py
git commit -m "feat(actions): persist replay provenance"
```

### Task 3: Replay-Bound Action Service and Role Guard

**Files:**
- Modify: `nutmeg/ontology/actions/models.py`
- Modify: `nutmeg/ontology/actions/service.py`
- Modify: `nutmeg/ontology/actions/permissions.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `tests/ontology/test_action_service.py`
- Modify: `tests/ontology/test_permissions.py`

- [ ] **Step 1: Write denial and propagation tests**

Test these exact invariants:

1. A production service rejects `ActorRole.REPLAY_ADJUDICATOR`.
2. A replay-bound service rejects a non-replay command if stamping is disabled.
3. A replay-bound service stamps every command, including `execute_batch` items.
4. The bound run must exist, be `running`, match the isolated database identity, and match the command business date.
5. Protected action types (`place_ticket`, funds/cash, dispatch, deploy, prospective RSI fulfillment, cutover approval) are rejected before permission lookup.
6. A nested caller cannot replace or clear the bound run id.

- [ ] **Step 2: Run the RED tests**

Run: `uv run pytest tests/ontology/test_action_service.py tests/ontology/test_permissions.py -q`

Expected: FAIL because the replay role and service context do not exist.

- [ ] **Step 3: Add the replay role and explicit service binding**

Add `REPLAY_ADJUDICATOR = "replay_adjudicator"`. Extend `ActionService.__init__` with an immutable optional context:

```python
@dataclass(frozen=True, slots=True)
class ReplayActionContext:
    replay_run_id: str
    business_date: str
    isolated_database_identity: str

class ActionService:
    def __init__(self, unit_of_work_factory, *, replay_context=None): ...
```

Before lookup/permission checks, normalize the command with `dataclasses.replace`; reject a conflicting supplied run id. Validate the run row inside the same UOW used for permission checks.

- [ ] **Step 4: Seed only the approved replay permissions**

Migration 35 must grant `replay_adjudicator` only to existing judgment-chain Actions: create/resolve proposal, record adjudication, commit Forecast, freeze prescription, request/generate candidates, audit/reject candidate, record no-ticket, ingest authoritative result, grade replay Forecast, and replay-mode RSI grade/gap. Do not grant placement, cash, dispatch, deployment, prospective duty fulfillment, or cutover approval.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ontology/test_action_service.py tests/ontology/test_permissions.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/models.py nutmeg/ontology/actions/service.py nutmeg/ontology/actions/permissions.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/wiring.py tests/ontology/test_action_service.py tests/ontology/test_permissions.py
git commit -m "feat(actions): bind replay adjudication context"
```

### Task 4: Typed Replay Start and Finish Actions

**Files:**
- Create: `nutmeg/ontology/actions/replay_actions.py`
- Modify: `nutmeg/ontology/kernel.py`
- Modify: `nutmeg/ontology/wiring.py`
- Create: `tests/ontology/test_replay_actions.py`

- [ ] **Step 1: Write state-machine RED tests**

Test deterministic start idempotency, identity conflict, accepted finish, failed finish, double finish rejection, and production database path rejection. Assert result refs use `ObjectRef("historical_replay_run", replay_run_id)`.

- [ ] **Step 2: Run the RED test**

Run: `uv run pytest tests/ontology/test_replay_actions.py -q`

Expected: FAIL because replay Actions do not exist.

- [ ] **Step 3: Implement typed requests and Actions**

Define immutable `StartHistoricalReplayRequest` and `FinishHistoricalReplayRequest`. Start uses the deterministic actor `system:historical-replay` with `DETERMINISTIC_SYSTEM`; finish requires the same run identity and writes the report hash, failure codes, and production-after snapshot exactly once.

The handler must reject a production path before inserting the run:

```python
if Path(request.isolated_database_identity).resolve() == Path(request.production_database_identity).resolve():
    raise ValueError("isolated ontology path equals production ontology path")
```

- [ ] **Step 4: Wire the Action facade**

Expose `kernel.replay_actions` using the same shared `ActionService` and repository UOW pattern as existing typed Actions.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ontology/test_replay_actions.py tests/ontology/test_action_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/replay_actions.py nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py tests/ontology/test_replay_actions.py
git commit -m "feat(replay): govern replay run lifecycle"
```

### Task 5: Frozen Input Manifest and Timestamp Quarantine

**Files:**
- Create: `nutmeg/product/jczq_replay_inputs.py`
- Modify: `nutmeg/product/jczq_replay.py`
- Create: `tests/product/operator_v2/test_jczq_replay_inputs.py`

- [ ] **Step 1: Write frozen-input RED tests**

Create fixtures for the real five input kinds and assert:

- each manifest entry records relative path, byte size, SHA-256, and semantic timestamp;
- manifest order does not change its hash;
- modifying copied bytes after run start raises `source_manifest_changed`;
- filesystem mtime is never used as evidence time;
- `周六002` without `captured_at` becomes one quarantined input with `temporal_status="unknown"`;
- the quarantined artifact cannot appear in an EvidenceBundle manifest.

- [ ] **Step 2: Run the RED test**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_inputs.py -q`

Expected: FAIL because manifest and quarantine types do not exist.

- [ ] **Step 3: Implement manifest types and copying**

Define `ReplayInputEntry`, `ReplayInputManifest`, and `QuarantinedReplayInput`. Copy files to a new run-specific directory under the isolated root, hash copied bytes, then make orchestration consume only manifest paths.

Accepted semantic timestamps are explicit JSON `captured_at`/`made_at`, official market update time, kickoff, and authoritative result publication time. Missing accepted-evidence time raises; missing time on a rejected research artifact creates quarantine only.

- [ ] **Step 4: Replace `_copy_inputs` and `_load_research_artifacts`**

`JczqReplayRunner` must start the run only after the input manifest is frozen, then pass the immutable manifest to later stages. Remove the current behavior that reports `research_capture_time_missing:周六002` as an unconditional failure; it becomes `historical_input_gap` only when quarantine exclusion is proven.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_inputs.py tests/product/operator_v2/test_jczq_20260919_replay.py -q`

Expected: PASS for input tests; the full replay test remains RED on missing A3-A7 implementation.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/product/jczq_replay_inputs.py nutmeg/product/jczq_replay.py tests/product/operator_v2/test_jczq_replay_inputs.py tests/product/operator_v2/test_jczq_20260919_replay.py
git commit -m "feat(replay): freeze historical JCZQ inputs"
```

### Task 6: A3 Replay Proposals, Adjudication, and Forecasts

**Files:**
- Create: `nutmeg/product/jczq_replay_adjudication.py`
- Modify: `nutmeg/product/jczq_board_workflow.py`
- Create: `tests/product/operator_v2/test_jczq_replay_adjudication.py`

- [ ] **Step 1: Write A3 RED tests**

Build three draft Reads representing approve, revise, and reject. Assert:

- all remain draft `AgentProposal` inputs;
- the actor id is `replay:<run-id>:adjudicator` and role is `replay_adjudicator`;
- approve, revise, and reject Adjudications all occur;
- reject does not become approval in place;
- a replacement market-anchor proposal has a distinct proposal id;
- every committed Forecast resolves `EvidenceBundle -> Artifact -> SourceRun`;
- the quarantined `周六002` artifact is absent from every accepted bundle;
- every Action carries the same replay run id.

- [ ] **Step 2: Run the RED test**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_adjudication.py -q`

Expected: FAIL because A3 replay orchestration does not exist.

- [ ] **Step 3: Implement deterministic replay adjudication input**

Map each Read and frozen market row to an existing `CreateAgentProposalRequest`. Select approve/revise/reject with an explicit replay fixture policy checked into the test fixture, not by changing production judgment rules. Revised proposals must carry a new payload and a reason; rejected research may only fall back to a separately created price-only proposal.

- [ ] **Step 4: Commit Forecasts through existing Actions**

Use existing proposal resolution, adjudication, EvidenceBundle freeze, and Forecast commit services. Do not insert proposal, adjudication, or Forecast rows directly. Mark replay Forecasts non-prospective in their formal payload even when source timestamps precede kickoff.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_adjudication.py tests/product/operator_v2/test_jczq_workflow.py -q`

Expected: PASS for A3 coverage and existing workflow regressions.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/product/jczq_replay_adjudication.py nutmeg/product/jczq_board_workflow.py tests/product/operator_v2/test_jczq_replay_adjudication.py tests/product/operator_v2/test_jczq_workflow.py
git commit -m "feat(replay): adjudicate draft Reads through Forecasts"
```

### Task 7: A4-A7 Orchestration and RSI Isolation

**Files:**
- Create: `nutmeg/product/jczq_replay_workflow.py`
- Modify: `nutmeg/product/operator_workers.py`
- Modify: `nutmeg/decision/rsi.py`
- Create: `tests/product/operator_v2/test_jczq_replay_workflow.py`
- Modify: `tests/decision/test_rsi_wiring.py`

- [ ] **Step 1: Write the A4-A7 RED integration test**

Given committed replay Forecasts and authoritative results, assert:

1. one frozen prescription is produced;
2. exactly `judgment_bound` and `comparison_only` set kinds exist;
3. all four odds bands have candidates or `no_feasible_candidate`;
4. every non-root set revision has parent, delta, rationale, and dependency fingerprint;
5. candidate audits and cross-ticket audit are complete;
6. exactly one formal `record_no_ticket` terminal exists;
7. no placement, cash, receipt, confirmation, or dispatch row exists;
8. every Forecast has authoritative result and replay score;
9. replay RSI emits only replay grade/gap rows and leaves prospective duties, `n`, verdicts, and deployments unchanged.

- [ ] **Step 2: Run the RED test**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_workflow.py tests/decision/test_rsi_wiring.py -q`

Expected: FAIL because replay stops after A2.

- [ ] **Step 3: Orchestrate A4-A6 with existing services**

Call the production prescription and candidate workers with the replay-bound service. Reuse existing deterministic audit functions. Record audit-blocked branches without overriding ERROR. Finish through the existing formal no-ticket Action; do not create a selection or placement.

- [ ] **Step 4: Orchestrate A7**

Import only manifest-listed authoritative results and call existing result/Forecast score Actions. Add an explicit replay mode to the RSI adapter that can persist replay grades/gaps but rejects duty fulfillment, prospective observations, verdict mutation, and deployment.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_replay_workflow.py tests/decision/test_rsi_wiring.py tests/decision/test_rsi_grading.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/product/jczq_replay_workflow.py nutmeg/product/operator_workers.py nutmeg/decision/rsi.py tests/product/operator_v2/test_jczq_replay_workflow.py tests/decision/test_rsi_wiring.py tests/decision/test_rsi_grading.py
git commit -m "feat(replay): complete isolated JCZQ A4 to A7"
```

### Task 8: Derived Report, Independent Cutover Verification, and Real Replay

**Files:**
- Modify: `nutmeg/product/jczq_replay.py`
- Modify: `nutmeg/product/jczq_cutover.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Modify: `tests/product/operator_v2/test_jczq_20260919_replay.py`
- Modify: `tests/product/operator_v2/test_jczq_workflow_cli.py`
- Modify: `docs/sop/RUNBOOK.md`

- [ ] **Step 1: Write the acceptance-report RED tests**

Expand `JczqReplayReport` to cover run state, manifest hash, A2-A7 Action counts, adjudication branch counts, evidence coverage, prescription/set ids, four structured band outcomes, audit completeness, no-ticket id, result/score coverage, replay RSI outputs, quarantined gaps, production fingerprints, and protected deltas.

Test that cutover independently opens the isolated database and rejects a JSON report when any field is caller-tampered, even if its hash is recomputed.

- [ ] **Step 2: Run the RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_20260919_replay.py tests/product/operator_v2/test_jczq_workflow_cli.py -q`

Expected: FAIL because the current report trusts summary fields and has no isolated-store identity.

- [ ] **Step 3: Derive the report from ontology state**

Replace `_lineage_status` count deltas with replay-run-scoped repository queries. Compute the report hash only after the finish Action commits. Save the report beside the isolated ontology and include the isolated database identity and replay run id.

- [ ] **Step 4: Make cutover independently recompute readiness**

Change `JczqCutoverGate.check` to require both `--replay-report` and the report's isolated database. Recompute every acceptance condition from that database, confirm the run is `accepted`, compare the manifest/report hashes, then separately verify the production fingerprint and zero protected deltas.

Keep `--approve` as the only authority mutation; `--check-only` remains read-only.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
uv run pytest tests/ontology/test_migrations.py tests/ontology/test_action_models.py tests/ontology/test_action_repository.py tests/ontology/test_action_service.py tests/ontology/test_permissions.py tests/ontology/test_replay_actions.py tests/product/operator_v2/test_jczq_replay_inputs.py tests/product/operator_v2/test_jczq_replay_adjudication.py tests/product/operator_v2/test_jczq_replay_workflow.py tests/product/operator_v2/test_jczq_20260919_replay.py tests/product/operator_v2/test_jczq_workflow_cli.py -q
uv run pytest -q
uv run ruff check nutmeg/ontology nutmeg/product/jczq_replay.py nutmeg/product/jczq_replay_inputs.py nutmeg/product/jczq_replay_adjudication.py nutmeg/product/jczq_replay_workflow.py tests/ontology tests/product/operator_v2
```

Expected: all commands exit 0.

- [ ] **Step 6: Run the real isolated 2026-09-19 replay**

Use a new explicit isolated root; do not reuse the failed replay database:

```bash
uv run nutmeg workflow jczq-replay \
  --day 2026-09-19 \
  --isolated-root .nutmeg-data/replay/2026-09-19-v35 \
  --data-dir .nutmeg-data
uv run nutmeg workflow jczq-cutover \
  --day 2026-09-20 \
  --replay-report .nutmeg-data/replay/2026-09-19-v35/replay-2026-09-19.json \
  --check-only \
  --data-dir .nutmeg-data
```

Expected: replay `accepted=true`; check-only exits 0; production authority remains `legacy_read_only`; production fingerprint and protected deltas remain unchanged.

- [ ] **Step 7: Record evidence and update the runbook**

Write the exact test/replay/cutover-check outputs under `docs/superpowers/evidence/2026-09-20-jczq-historical-replay/`. Update the RUNBOOK to state that replay acceptance never authorizes cutover by itself and that `--approve` still requires Jun's fresh explicit instruction.

- [ ] **Step 8: Commit without approving cutover**

```bash
git add nutmeg/product/jczq_replay.py nutmeg/product/jczq_cutover.py nutmeg/interfaces/cli/workflow.py tests/product/operator_v2/test_jczq_20260919_replay.py tests/product/operator_v2/test_jczq_workflow_cli.py docs/sop/RUNBOOK.md docs/superpowers/evidence/2026-09-20-jczq-historical-replay
git commit -m "feat(workflow): verify replay-only JCZQ cutover evidence"
```

Do not run `workflow jczq-cutover --approve` in this plan. That is a separate, explicit operator action after Jun reviews the accepted replay evidence.

## Self-Review

- Spec coverage: sections 3-4 map to Tasks 1-6; A2-A7 sequence maps to Tasks 5-7; report/acceptance maps to Task 8; failure injection maps to Tasks 3-8; recovery remains append-only through run revisions and fresh isolated roots.
- Placeholder scan: no TBD, TODO, "implement later", or undefined follow-up step remains.
- Type consistency: `replay_run_id`, `historical_replay`, `ReplayActionContext`, `HistoricalReplayRunRecord`, and report fields use the same names from schema through Action, repository, runner, and cutover verification.
- Boundary check: no parallel business decision engine, no historical placement reconstruction, no fabricated timestamps, no prospective RSI mutation, and no automatic production cutover.
