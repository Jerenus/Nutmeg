# Dream-RSI Meta-Exploration D2 Online Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and seal prospective structural-candidate discovery trees in an isolated shadow store, with deterministic data-readiness reporting and zero authoritative business writes.

**Architecture:** Freeze a board-level input manifest from the existing candidate-generation read path at a cutoff, then execute the D0 incumbent's closed template-shard vocabulary using the existing pure candidate generator and deterministic audit. Commit each completed or failed attempt through D1 Actions; compute readiness from sealed, independently clustered worlds. D2 does not expose a general replay environment, generate challengers, run tournaments, or authorize deployment.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy Core, Ontology v2 ActionService, pytest, Ruff. Governing spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md` sections 9.2, 11.4, 13, and 18.A.

**As-built checkpoint (2026-09-21):** D2 code and temporary-store acceptance checks
are delivered in `docs/superpowers/evidence/2026-09-21-meta-exploration-d2-online-recorder.md`.
The checklist below is the original execution recipe; the evidence records the
shared-function and commit-granularity differences. No prospective run occurred.
Jun's D2 evidence review remains required before D3 implementation.

---

## Boundaries and entry gate

- D1 evidence (`docs/superpowers/evidence/2026-09-21-meta-exploration-d1-foundation.md`) must be reviewed before D2 implementation. Do not treat this plan as authority to run against `.nutmeg-data`.
- Verify the D0 pilot and incumbent canonical hashes against D1 evidence before coding or executing a run. Do not edit their JSON artifacts to accommodate a runtime mismatch.
- A real shadow run needs an explicit operator-approved, registered baseline policy, a prospective cutoff, and a separately identified shadow database. A local test may use temporary stores, but no synthetic or historical tree is called prospective evidence.
- D2 may read frozen business inputs and call pure `enumerate_band_candidates` with the existing audit callable. It must not invoke `CandidateGenerationWorker.run_once`, result Actions, protected ticket Actions, production migrations, RSI Actions, dispatch, or funds.
- Seal only after all reserved attempts have terminal outcomes, immutable manifests and evaluations match their hashes, and a before/after protected-table comparison shows no authoritative writes. Invariant failure blocks sealing and preserves the failed run.
- Readiness is a descriptive projection. `record_only` is the initial and default mode; no D2 code may start an optimizer or promote a policy, even if the thresholds pass.

## File ownership

- Create `nutmeg/discovery/online_inputs.py`: frozen snapshot DTO and read-only adapter for the existing candidate request/input path; reject missing provenance or post-cutoff evidence.
- Create `nutmeg/discovery/online_adapter.py`: pure per-template-shard invocation, audit and artifact packaging; no Ontology connection or business Action access.
- Create `nutmeg/discovery/online_recorder.py`: bounded baseline run coordinator, execution receipts, D1 Action requests, stop and seal checks.
- Create `nutmeg/discovery/readiness.py`: deterministic sealed-world coverage and effective-sample projection.
- Modify `nutmeg/ontology/discovery/read_service.py`: read-only world-pool and readiness projection inputs; no query-time migration.
- Modify `nutmeg/interfaces/cli/discovery.py`: explicit readiness query and guarded shadow-run entry point only after all isolation tests pass; query remains read-only.
- Test `tests/discovery/test_online_inputs.py`, `test_online_adapter.py`, `test_online_recorder.py`, `test_readiness.py`, and `tests/test_cli_discovery.py`.
- Create `docs/superpowers/evidence/2026-09-21-meta-exploration-d2-online-recorder.md` after fresh verification.

### Task 1: Freeze the read-only structural input

- [ ] Write `test_online_inputs.py` fixtures from `CandidateGenerationInput` and `CandidateStructureTemplate`; assert canonical snapshot hash is stable under repeated reads, shard IDs are unique and ordered, and every referenced input has `captured_at <= cutoff_at` with an explicit source revision.

```python
def test_snapshot_refuses_post_cutoff_reference(candidate_request, frozen_refs):
    changed = (*frozen_refs, {"source_revision": "q-new", "captured_at": "2026-09-22T00:00:00+00:00"})
    with pytest.raises(ValueError, match="cutoff"):
        freeze_structural_input(candidate_request, changed, cutoff_at="2026-09-21T00:00:00+00:00")
```

- [ ] Add rejection tests for a missing committed Forecast/Prescription, stale or post-cutoff quote, missing audit-policy version, empty template set, and a candidate request not belonging to the chosen board. An unknown provenance is a failure, never a default timestamp.
- [ ] Run `uv run pytest tests/discovery/test_online_inputs.py -q` and confirm these tests fail because the adapter does not exist.
- [ ] Implement a frozen DTO with `business_date`, `task_snapshot_hash`, `slate_revision_id`, cutoff, template IDs, candidate input, and audit-policy revision. Extract the already used `_candidate_generation_inputs` assembly from `nutmeg/product/operator_workers.py` into a shared read-only function and have both the existing worker and the shadow adapter call it; never claim a worker lease.
- [ ] Re-run that file; add a test that the source database opened read-only remains byte-for-byte unchanged. Commit the adapter and tests: `git add nutmeg/discovery/online_inputs.py nutmeg/product/operator_workers.py tests/discovery/test_online_inputs.py` followed by `git commit -m "feat(discovery): freeze structural shadow inputs"`.

### Task 2: Execute one closed continuation outside the Action transaction

- [ ] Write `test_online_adapter.py` with two disjoint template shards. Assert each invocation passes a restricted `CandidateGenerationInput` to `enumerate_band_candidates`, the frozen `set_kind="judgment_bound"` and `generator_version="operator-candidate-v2-bands"`, and the existing `_audit_candidate` semantics; no ActionService or production result writer is reachable from the adapter.

```python
def test_shard_cannot_enumerate_other_templates(snapshot, candidate_spy):
    execute_template_shard(snapshot, ("T1",), enumerate_fn=candidate_spy)
    assert tuple(t.structure_code for t in candidate_spy.call_args.args[0].templates) == ("T1",)
```

- [ ] Add fixed-fixture assertions for audit-clean output, no-feasible-candidate, over-cap, invalid input and adapter timeout. Persist diagnostic code, actual elapsed time, attempt cost and artifact hash for every case; unknown cost is explicit, not zero.
- [ ] Run `uv run pytest tests/discovery/test_online_adapter.py -q` for the expected missing-module failure.
- [ ] Implement the closed `enumerate_template_shard(template_ids)` vocabulary, candidate cap from the frozen pilot, deterministic output ordering and a content-addressed artifact manifest. The evaluator may compute D0 quality fields; it cannot inspect ticket outcomes or rewrite audit findings.
- [ ] Re-run adapter tests and `uv run pytest tests/product/operator_v2/test_candidate_bands.py -q`; commit.

### Task 3: Record a complete incumbent shadow tree

- [ ] Write `test_online_recorder.py` using a temporary business fixture and a separate temporary shadow Ontology database. Register the exact D0 baseline through `DiscoveryPolicyActions.register_policy` with an operator actor in the fixture, then call the coordinator with a deterministic-system actor for world/run/node/seal Actions.
- [ ] Assert root-only initial visibility, a bounded `continue_batch` of template shards, one immutable child per accepted shard, stable parent/sibling/creation/visibility order, a matching policy decision, per-node artifact/diagnostic/cost and evaluation, and STOP selecting only audit-clean selectable nodes. Parallel completion order must not affect assigned visibility order or the sealed hash.

```python
def test_completion_order_does_not_change_sealed_tree(shadow_rig):
    first = shadow_rig.record(completion_order=("T2", "T1"))
    second = shadow_rig.record(completion_order=("T1", "T2"))
    assert first.canonical_node_projection == second.canonical_node_projection
```

- [ ] Test partial timeout, invalid artifact, retries (new node linked to failed attempt), cost accumulation, no-solution terminal and round/node/concurrency/wall-budget exhaustion. No uncommitted attempt may be omitted from a sealed manifest. An Action commit error must retry by receipt/idempotency key without duplicate execution.
- [ ] Run `uv run pytest tests/discovery/test_online_recorder.py -q` to confirm missing implementation fails.
- [ ] Implement `online_recorder.py` using only D1 `DiscoveryWorldActions` and `DiscoveryPolicyActions` for writes. Reserve deterministic attempt IDs before invoking the adapter; run work outside transactions, then commit in deterministic shard order. Call `DiscoveryWorldActions.seal_manifest` and `seal_world` only after reconciliation.
- [ ] Re-run recorder tests plus `uv run pytest tests/ontology/test_discovery_world_actions.py -q`; commit.

### Task 4: Prove shadow isolation and production immutability

- [ ] Add tests that fingerprint Forecast, candidate request/set/terminal, ticket, placement, settlement, RSI prospective, and funds rows before and after a shadow run; all counts and content hashes must be identical. The only new records belong to the declared shadow store.

```python
def test_shadow_run_never_writes_authoritative_tables(shadow_rig):
    before = shadow_rig.protected_fingerprints()
    shadow_rig.record()
    assert shadow_rig.protected_fingerprints() == before
```

- [ ] Verify the shadow database path is distinct from the source and that `WorldRow.isolated_store_identity` begins with `shadow:`. Reject symlink/path aliasing, a source URL capable of writes, a copied post-cutoff input, and use of a production UoW in the adapter.
- [ ] Add a negative test where protected-table fingerprints change during execution; sealing must fail closed and preserve diagnostics for review. Run the tests red, implement narrow guards in `online_inputs.py` and `online_recorder.py`, then run green.
- [ ] Re-run protected business regressions: `uv run pytest tests/ontology/test_protected_ticket_actions.py tests/ontology/test_rsi_actions.py tests/product/operator_v2/test_candidates.py tests/product/operator_v2/test_candidate_replay.py -q`; commit.

### Task 5: Publish effective-information readiness

- [ ] Write `test_readiness.py` for an empty pool (`record_only`) and fixtures with exactly 30 sealed worlds/20 dates/24 effective samples and 60/40/48 respectively. These fixtures satisfy the count subchecks, **not** the overall mode: without a proven replay-integrity and unavailable-branch measurement (D3), the projected operational mode remains `record_only`. Assert each failed or unknown check names the metric and observed/required value; do not promote solely by raw count.

```python
def test_missing_replay_metric_blocks_mode_even_at_world_threshold(sealed_worlds_30, pilot):
    report = assess_readiness(sealed_worlds_30, pilot.readiness, replay_metrics=None)
    assert report.mode == "record_only"
    assert report.metrics["branch_unavailable_rate"].status == "unknown"
```

- [ ] Test duplicate clustering on `(business_date, task_snapshot_hash, slate_revision_id)`, missing manifest, absent required board-size stratum, fewer multi-alternative trees, insufficient action overlap, excessive branch-unavailable rate, and fewer than three failed/degraded worlds. A single duplicate cluster contributes at most one effective sample.
- [ ] Run `uv run pytest tests/discovery/test_readiness.py -q` red; implement a pure report over sealed D1 facts and the exact D0 `ReadinessContract` thresholds, with a stable sorted blocking-reason list. Do not infer replay-only unavailable-branch rates as zero: before D3 records them, report `unknown` and block that gate when its ceiling must be proven. D2 publishes the count/coverage subchecks, not an optimizer authorization.
- [ ] Re-run tests and add a read-only CLI `discovery readiness` view. Assert a fresh store query creates no files or migrations. Commit.

### Task 6: Acceptance and review gate

- [ ] Run `uv run pytest tests/discovery tests/ontology/test_discovery_world_actions.py tests/ontology/test_discovery_policy_actions.py tests/test_cli_discovery.py -q` and the protected business regressions from Task 4.
- [ ] Run `uv run ruff check nutmeg/discovery nutmeg/ontology/discovery nutmeg/interfaces/cli/discovery.py tests/discovery tests/test_cli_discovery.py`, `git diff --check`, and `uv run pytest -q`; record exit codes and exact counts, including unrelated failures separately.
- [ ] Run a **temporary-store** representative shadow world using a frozen fixture first; compare protected-table fingerprints and independently recompute the sealed manifest. A live prospective run needs a separately approved operational scope and must never be substituted with a fixture in the evidence claim.
- [ ] Record D0 hashes, input cutoff, policy ID, isolation proof, exact tests, failures, sealed fixture trace, readiness mode and unknown metrics in `docs/superpowers/evidence/2026-09-21-meta-exploration-d2-online-recorder.md`; commit only D2 files.
- [ ] Present D2 evidence to Jun for review before D3 implementation. No D2 result authorizes production cutover, historical backfill, tournament, policy promotion or protected Actions.

## Spec coverage and deferred work

| Requirement | D2 task | Proof |
| --- | --- | --- |
| FR-001, FR-002 | 1-3 | frozen cutoff, parent/action/artifact/evaluation/cost lineage |
| FR-011, FR-012 | 2-4 | closed adapter and zero authoritative writes |
| FR-013 | 2-3 | explicit failure, timeout, retry and charged cost |
| FR-018, FR-022 | 5 | deterministic coverage report; no optimizer or cadence authority |
| SC-004, SC-005 | 3-4, 6 | protected-state diff and seal completeness |

The common online/replay policy-visible interface (FR-003), sealed-tree replay (FR-004/005), and unavailable-branch measurements are D3. Tournament scoring and temporal holdout are D4; generation is D5; human promotion is D6; recursive triggers are D7. D2 may show that a threshold is numerically satisfied, but must never infer missing D3 replay integrity from it.
