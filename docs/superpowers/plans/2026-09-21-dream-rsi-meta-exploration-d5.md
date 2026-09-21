# Dream-RSI Meta-Exploration D5 Constrained Policy Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate reproducible, strictly bounded exploration-policy candidates from development evidence, while preventing holdout access, executable-system mutation and optimizer execution below the frozen readiness gate.

**Architecture:** A content-addressed generation round freezes a restricted `GenerationContext` before candidate generation. A baseline generator and a seeded bounded-evolution generator emit declarative policy artifacts in a closed grammar; D3's interpreter runs them without executing arbitrary Python. The optimizer gate runs before reading candidate input or consuming resources. Generated artifacts are proposals until the existing human-only D1 `register_policy_revision` Action admits them; D4 inserts the unchanged incumbent separately.

**Tech Stack:** Python 3.13, Pydantic v2, immutable artifacts/SHA-256, Ontology v2 SQLAlchemy Core/ActionService, pytest, Ruff. Spec sections 10, 11.4, 11.6 and 18.I/K; FR-011, FR-016 through FR-020; SC-008, SC-011 through SC-013, SC-015.

---

## Entry gate and resolved contract tension

- D4 evidence reviewed. `baseline` generation may operate only with reviewed frozen inputs and baseline-comparison readiness. `bounded_evolution` requires **optimizer-enabled** readiness including D3 unavailable-branch rate, effective sample size and required failed/degraded strata. If not ready, return failed metrics and generate zero candidates; a direct API call cannot bypass this.
- D1 `register_policy_revision` is human-only. The total spec describes generator registration through a tournament service, but D5 must not silently grant registration rights to software. Treat outputs as immutable proposals; operator registration remains a distinct Action. The tournament inserts the original incumbent itself and refuses unregistered proposals.
- D0 `BaselinePolicyArtifact` is an exact, fixed incumbent schema. D4 already adds the closed `DeterministicBaselineVariantArtifact` for human-registered challengers. D5 reuses that artifact for baseline generation and adds a strict, versioned `PolicyProgramArtifact` only for bounded evolution, without relaxing frozen surfaces or arbitrary source execution.
- D1 stores generation metadata on policies but has no durable record of zero-output rounds. Add a narrow append-only `policy_generation_rounds` child table and deterministic-system `record_policy_generation_round` Action in a new migration; link candidate rows to its ID/hash. A rejected/empty round still has audit and cost.
- D5 does **not** implement `workflow_search` or `tree_search`, train weights, mutate prompts beyond D0's approved slots, or alter the evaluator, schema permissions, business rules or frozen holdouts.

## File map

- Create `nutmeg/discovery/generation_contracts.py`: strict generation context, declarative policy AST, immutable round/proposal DTO, surface allowlist and content hashes.
- Create `nutmeg/discovery/generator_baseline.py`: closed deterministic variants; no dynamic import or code generation.
- Create `nutmeg/discovery/generator_evolution.py`: bounded seeded mutation/recombination across approved parent policies.
- Create `nutmeg/discovery/generation_service.py`: preflight readiness, development-only context builder, resource accounting and generation receipt.
- Modify `nutmeg/discovery/replay_runner.py`: interpret validated declarative artifacts via the same D3 policy-visible contract.
- Create `nutmeg/ontology/repository/schema_discovery_generation.py`; modify `nutmeg/ontology/repository/migrations.py`, `nutmeg/ontology/repository/discovery.py` and `nutmeg/ontology/actions/discovery_policy_actions.py`: append-only generation round facts, guarded Action and artifact registration validation. Do not add the new table to `schema_discovery.TABLE_KEYS`: migration 40 iterates that mapping, so changing it would change already-applied D1 migration behavior. Seed its permission only in migration 41.
- Modify `nutmeg/ontology/discovery/read_service.py` and `nutmeg/interfaces/cli/discovery.py`: read-only round, parent, cost and archive projections.
- Tests `tests/discovery/test_generation_contracts.py`, `test_generator_baseline.py`, `test_generator_evolution.py`, `test_generation_service.py`, `test_replay_runner.py`, `tests/ontology/test_discovery_migration.py`, `test_discovery_policy_actions.py`, `tests/test_cli_discovery.py`.
- Evidence `docs/superpowers/evidence/2026-09-21-meta-exploration-d5-constrained-generation.md`.

### Task 1: Define a closed, immutable candidate program

**Files:** Create `nutmeg/discovery/generation_contracts.py`; test `tests/discovery/test_generation_contracts.py`.

- [ ] **Step 1 (RED):** Test allowed changes to shard priority, batch limit, budget allocation and STOP threshold only. Reject unknown fields, Python code/import, prompt text outside registered slots, model/evaluator/Action/football surface, undeclared resource, parent mismatch, unsorted duplicate parent, and program state exceeding the frozen size bound.

```python
def test_frozen_surface_is_rejected_before_replay(program_document):
    with pytest.raises(ValueError, match="frozen|unsupported"):
        PolicyProgramArtifact.model_validate({**program_document, "model_weights": {"x": 1}})
```

- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_generation_contracts.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Implement strict Pydantic models with explicit `schema_version`, `policy_revision_id`, ordered complete `parent_policy_revision_ids`, `generator_family`, `generator_revision`, seed, constraint revision, `change_surfaces`, a closed `program`, descriptor set and deterministic canonical hash. The interpreter maps that program to D3 `ContinueBatch`/`Stop`, not arbitrary calls.
- [ ] **Step 4:** Re-run tests; add a test that serialization/hash are deterministic across repeated validations. Commit.

### Task 2: Record an empty or successful generation round durably

**Files:** Create `nutmeg/ontology/repository/schema_discovery_generation.py`; modify `nutmeg/ontology/repository/migrations.py`, `discovery.py`, `nutmeg/ontology/actions/discovery_policy_actions.py`; tests `tests/ontology/test_discovery_migration.py`, `test_discovery_policy_actions.py`, `test_permissions.py`.

- [ ] **Step 1 (RED):** Test append-only round schema with round ID, development pool hash, eligible parent IDs, generator artifact hash, seed, candidate cap, compute budget, timeout, measured generation cost, status, ordered candidate hashes and trace hash. Assert an empty round is recorded, UPDATE/DELETE fail, AI/operator cannot masquerade as deterministic recorder, and Action+outbox commit atomically.
- [ ] **Step 2:** Run the migration and Action tests red.
- [ ] **Step 3 (GREEN):** Add migration 41 that creates only the new table, append-only triggers and the `record_policy_generation_round` permission for `deterministic_system`. Add one typed Action using `ActionService`. Validate source world IDs are development-only and frozen, and freeze input manifest **before** running generation. Do not edit `schema_discovery.TABLE_KEYS`, migration 40, D1 historical rows or read-only CLI schema automatically.
- [ ] **Step 4:** Re-run new tests plus `uv run pytest tests/ontology/test_migrations.py tests/ontology/test_permissions.py -q`; commit.

### Task 3: Deterministic baseline proposal generator

**Files:** Create `nutmeg/discovery/generator_baseline.py`; test `tests/discovery/test_generator_baseline.py`.

- [ ] **Step 1 (RED):** Same manifest/seed yields same ordered proposal hashes and zero hidden holdout accesses; cap and time budget yield explicit truncation/timeout receipts and charged generation cost. No proposal claims incumbent role or writes `exploration_policy_revisions`.
- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_generator_baseline.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Generate only enumerated legal D4 `DeterministicBaselineVariantArtifact` variants under D0 grammar, deduplicate by content hash, and persist the round receipt from Task 2. Keep generation cost separate from later D3 execution cost; D5 `PolicyProgramArtifact` is reserved for bounded evolution.
- [ ] **Step 4:** Re-run tests and register one proposal through operator `DiscoveryPolicyActions.register_policy` in a temporary store; commit.

### Task 4: Bounded seeded evolution behind fail-closed readiness

**Files:** Create `nutmeg/discovery/generator_evolution.py`, `nutmeg/discovery/generation_service.py`; test `tests/discovery/test_generator_evolution.py`, `test_generation_service.py`.

- [ ] **Step 1 (RED):** With 59 sealed worlds, insufficient overlap, duplicate-inflated sample, missing failed/degraded strata or unknown D3 unavailable-branch rate, assert generator was never called and response names all failed metrics. Direct import/API invocation must enforce the same gate. Exposed hidden holdout and open prospective shadow worlds never appear in `GenerationContext`.

```python
def test_optimizer_is_not_invoked_below_gate(service, generator_spy, report):
    outcome = service.generate("bounded_evolution", report=report)
    assert outcome.candidate_hashes == ()
    assert "effective_sample_size" in outcome.blocking_metrics
    generator_spy.assert_not_called()
```

- [ ] **Step 2:** Run focused tests red.
- [ ] **Step 3 (GREEN):** Filter parents to eligible `incumbent`/non-disqualified archive policies under D0 capacity/per-lineage rules; stable seeded mutation/recombination within closed AST; freeze pool, descriptors, budget and generator revision. Enforce candidate/time/cost caps during the loop, not only after it. Save every attempt/timeout and selected proposals in the round trace.
- [ ] **Step 4:** Re-run with a passing synthetic gate fixture twice and compare exact hashes, lineage links, receipt cost and seed. Add negative tests for frozen-surface payloads and unsupported `workflow_search`/`tree_search`. Commit.

### Task 5: Validate admission and reproduce through D3/D4

**Files:** Modify `nutmeg/ontology/actions/discovery_policy_actions.py`, `nutmeg/discovery/replay_runner.py`, read-only projections/CLI; tests `tests/ontology/test_discovery_policy_actions.py`, `tests/discovery/test_replay_runner.py`, `tests/test_cli_discovery.py`.

- [ ] **Step 1 (RED):** Operator registration must verify round receipt, exact candidate artifact hash, ordered parent IDs, allowed surfaces and compatible family; bind `PolicyRevisionRow.generation_input_manifest_hash` and `generation_trace_hash` to the append-only round and store its ID in validated `generator_descriptors`. Generated result without operator Action is not replay-eligible. A registered proposal's D3 replay uses only observation passed by environment; no background memory, filesystem/network read or Action call.
- [ ] **Step 2:** Run tests red. Extend the policy Action and declarative interpreter; expose generator family/revision, seed, parent lineage, generation trace/cost, archive eligibility and source round in read-only detail. For stores at schema 40, return an explicit "generation unavailable; migration 41 required" read state rather than migrating during a query. Run tests green; commit.
- [ ] **Step 3:** Run `uv run pytest tests/discovery tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_governance_actions.py tests/ontology/test_permissions.py tests/ontology/test_migrations.py tests/test_cli_discovery.py -q`, `uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_policy_actions.py nutmeg/ontology/repository tests/discovery tests/ontology/test_discovery_policy_actions.py tests/test_cli_discovery.py`, `git diff --check`, `uv run pytest -q`. Record counts and unrelated failures.
- [ ] **Step 4:** On a temporary store reproduce a seeded generator round and verify its output hash/parent/seed/cost. Do not claim optimizer readiness from synthetic fixtures. Write D5 evidence, commit D5 paths only, submit for Jun's review before D6 implementation.

## Coverage

| Requirement | Tasks | Evidence |
| --- | --- | --- |
| FR-011 / FR-016 / FR-017 / SC-008 / SC-011 | 1-3, 5 | strict program, full lineage, separate cost and governed registration |
| FR-018 / SC-012 | 4 | fail-closed readiness before generation |
| FR-019 / FR-020 / SC-013 | 4-5 | bounded eligible parents; archive has no deployment rights |
| SC-015 | 2-4 | identical candidate/trace hashes on seeded repeat |

D5 does not approve any candidate for prospective shadow: only D4 winner evidence followed by the human-only D6 Action can do so.
