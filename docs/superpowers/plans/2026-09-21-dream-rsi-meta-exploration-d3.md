# Dream-RSI Meta-Exploration D3 Prefix Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the same bounded exploration policy against online and sealed-tree environments, with replay revealing only recorded children and producing reproducible, isolated traces.

**Architecture:** A shared policy-visible observation/action codec sits above the D2 online recorder and a sealed-world replay adapter. Replay reads a verified frozen manifest, indexes recorded children internally, exposes only the root on reset and reveals a matching child after a legal frontier continuation. The D1 replay Actions persist the completed trace; neither the policy nor the replay adapter can access business Actions or the online executor.

**Tech Stack:** Python 3.13, Pydantic v2, Ontology v2 ActionService/SQLite, pytest, Ruff. Spec sections 7.4, 9, 10, 15; FR-003 through FR-005, FR-008, FR-011, FR-013; SC-001 through SC-003.

---

## As-built checkpoint (2026-09-21)

Tasks 1-4 have fixture-level implementations and tests. Task 5's focused,
protected, lint and full-suite verification passed; see
`docs/superpowers/evidence/2026-09-21-meta-exploration-d3-prefix-replay.md`.
The completed checklist uses Task 5's permitted fixture branch because D2 produced no
real sealed prospective world; real-world replay and SC-001 remain operationally open.
The optional Task 4 outbound invocation monkeypatch is not claimed, although the
replay constructor accepts no executable adapter.
Linked D2 retries are the narrow exception to Task 2's duplicate-key rejection:
only contiguous failed-attempt chains with explicit `retry_of_node_id` are valid.
Jun subsequently authorized continuation through D4-D7; that continuation did not
approve a real replay, tournament, deployment or other production action.

## Entry and authority

- Review D2 evidence and verify at least one sealed, reproducible D2 shadow tree before a representative replay. Synthetic sealed fixtures suffice for tests, not for SC-001's real-world claim.
- `DiscoveryPolicyActions.start_replay` currently permits only `{"visible_node_ids": [root_id]}` as its initial-observation hash input. Keep that storage contract: richer public observations are reconstructed from the root and frozen world metadata, never smuggled into Action payloads.
- D1 `finish_replay` checks parent visibility and trace hash, but does not by itself prove action-to-child matching, frontier legality, or complete budget accounting. D3 supplies those checks in the runtime and independently validates persisted trace before accepting completion; strengthen the Action validation if alternate callers could bypass the runtime.
- No model, tool, source business Action, prospective RSI, ticket/funds Action or synthetic branch in replay. Unknown branch returns `branch_unavailable`, records its charged attempt and never falls back to online execution.

## File map

- Create `nutmeg/discovery/environment.py`: versioned `Observation`, `Continue`, `ContinueBatch`, `Stop`, `TerminalObservation`, action validation, deterministic policy-state blob bounds and shared environment protocol.
- Modify `nutmeg/discovery/online_recorder.py`: implement that environment protocol without changing the D2 immutable artifact and Action boundaries.
- Create `nutmeg/discovery/sealed_tree.py`: verify manifest and build private `(parent_id, continuation_spec_hash) -> recorded child` index; reject corruption, duplicate action keys and post-cutoff references.
- Create `nutmeg/discovery/replay_environment.py`: isolated prefix visibility, frontier/budget checks, trace and cost accounting.
- Create `nutmeg/discovery/replay_runner.py`: validate a registered policy artifact, execute policy loop, persist via D1 `start_replay`/`finish_replay`, rerun from manifest for verification.
- Modify `nutmeg/ontology/actions/discovery_policy_actions.py` only for guards needed to prevent a forged completed trace bypassing the runtime; leave D1 storage semantics intact.
- Test `tests/discovery/test_environment.py`, `test_sealed_tree.py`, `test_replay_environment.py`, `test_replay_runner.py`, `tests/ontology/test_discovery_policy_actions.py`.
- Evidence: `docs/superpowers/evidence/2026-09-21-meta-exploration-d3-prefix-replay.md`.

### Task 1: Freeze one policy-visible action/observation interface

**Files:** Create `nutmeg/discovery/environment.py`; test `tests/discovery/test_environment.py`; modify `nutmeg/discovery/online_recorder.py`.

- [x] **Step 1 (RED):** Write parameterized tests rejecting unrevealed node IDs, unknown operator or template IDs, duplicate batch items, non-frontier parents, nonselectable STOP targets, oversized state blob and node/round/concurrency budget overflow. Use the same observation fixture for the online and replay implementations.

```python
def test_policy_action_cannot_name_hidden_child(root_observation):
    action = Continue(node_id="hidden-child", continuation_spec={"template_ids": ["T1"]})
    with pytest.raises(ValueError, match="visible frontier"):
        validate_action(root_observation, action)
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_environment.py -q`; expected missing-module failure.
- [x] **Step 3 (GREEN):** Implement frozen DTOs and a single `validate_action(observation, action, pilot_contract)` returning an ordered tuple of accepted/rejected items. `Observation` contains only declared world metadata, revealed-node summaries, frontier, remaining budgets and legal action IDs; never raw repositories or hidden node counts. Bound/version the serialized policy state and hash it each round.
- [x] **Step 4:** Re-run the test file, then D2 online-recorder tests to prove equivalent online action validation. Commit only the files above.

### Task 2: Verify sealed source before constructing the private index

**Files:** Create `nutmeg/discovery/sealed_tree.py`; test `tests/discovery/test_sealed_tree.py`.

- [x] **Step 1 (RED):** Test tampered seal hash, missing root, noncontiguous visibility order, missing artifact/evaluation, duplicate `(parent, spec)` keys, cross-world parent, future evidence and quarantine state. Confirm invalid worlds cannot enter replay.

```python
def test_changed_node_invalidates_sealed_source(sealed_world_fixture):
    world, nodes, sealed_hash = sealed_world_fixture
    altered = dataclasses.replace(nodes[1], diagnostic_codes=["changed"])
    with pytest.raises(ValueError, match="manifest"):
        SealedTree.from_rows(world, (nodes[0], altered), sealed_hash)
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_sealed_tree.py -q`; expected import/behavior failure.
- [x] **Step 3 (GREEN):** Verify against `DiscoveryWorldActions.seal_manifest(world, nodes)` and the sealed event before indexing; reject ambiguous keys rather than choosing the first child. Keep the index private to the environment and expose only immutable revealed-node projections.
- [x] **Step 4:** Re-run tests and `uv run pytest tests/ontology/test_discovery_world_actions.py -q`; commit.

### Task 3: Reveal only an exact recorded child under a visible frontier

**Files:** Create `nutmeg/discovery/replay_environment.py`; test `tests/discovery/test_replay_environment.py`.

- [x] **Step 1 (RED):** Reset must expose exactly root ID; legal action listing must not reveal child IDs, child scores or generating policy. Continue with an exact recorded spec reveals the child; wrong spec, hidden parent, an already consumed action or absent child returns/rejects `branch_unavailable` without changing visibility.

```python
def test_missing_branch_never_executes_adapter(sealed_tree, online_adapter_spy):
    replay = ReplayEnvironment(sealed_tree)
    assert replay.reset().visible_node_ids == (sealed_tree.root_id,)
    result = replay.continue_batch((Continue(sealed_tree.root_id, {"template_ids": ["absent"]}),))
    assert result.failure_codes == ("branch_unavailable",)
    online_adapter_spy.assert_not_called()
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_replay_environment.py -q`; expected failure.
- [x] **Step 3 (GREEN):** Implement frontier and sibling visibility updates per decision round, stable batch order, historical recorded-cost charging, failed-attempt charges, stop selection and explicit budget exhaustion. The replay constructor accepts no executable adapter at runtime; the spy above is a test-only boundary assertion, not part of production API.
- [x] **Step 4:** Re-run tests. Include a property-style test iterating every hidden child: its ID, artifact and score must be absent from every preceding observation serialization. Commit.

### Task 4: Persist and independently reproduce traces

**Files:** Create `nutmeg/discovery/replay_runner.py`; modify `nutmeg/ontology/actions/discovery_policy_actions.py` to validate exact action-child pairs and a complete versioned trace hash; test `tests/discovery/test_replay_runner.py` and `tests/ontology/test_discovery_policy_actions.py`.

- [x] **Step 1 (RED):** Two runs with the same policy/world/seed must produce the same ordered requested/accepted/rejected/revealed lists, terminal selection, cost vector and trace hash. Fabricated revealed child, selection of an unrevealed node, noncontiguous round, altered policy-state hash or hash mismatch must fail before completion.
- [x] **Step 2:** Run `uv run pytest tests/discovery/test_replay_runner.py tests/ontology/test_discovery_policy_actions.py -q`; confirm only the intended new cases fail.
- [x] **Step 3 (GREEN):** Use the D1 request/row types (`PolicyReplayRunRow`, `PolicyReplayRoundRow`, `PolicyReplayCompletionRow`). Extend `DiscoveryPolicyActions.trace_document` to hash source seal, evaluator/cost-policy revisions, seed, ordered rounds, stop/selection, charged budget, failures and aggregate outcome (excluding the hash field itself); otherwise different costs could share a D1 trace hash. Build and validate rounds in isolation, then call `start_replay`/`finish_replay` with deterministic idempotency keys; reject different payload on retry. Validate exact accepted action/recorded-child relation in the Action for direct callers too.
- [x] **Step 4:** Re-run tests, then assert business and prospective table fingerprints unchanged, and monkeypatch outbound model/tool invocations to fail if reached. Commit.

### Task 5: Completion evidence and D4 handoff

- [x] Run `uv run pytest tests/discovery tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_world_actions.py tests/ontology/test_replay_actions.py tests/ontology/test_protected_ticket_actions.py tests/ontology/test_rsi_actions.py -q`, `uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_policy_actions.py tests/discovery tests/ontology/test_discovery_policy_actions.py`, `git diff --check`, then `uv run pytest -q`. Record exact exit codes, counts and unrelated worktree differences.
- [x] Replay one D2 sealed world with incumbent and an operator-registered deterministic challenger **only if** D2 evidence includes a real sealed prospective world and operator approval covers this isolated run. Otherwise prove fixture-level replay and mark SC-001 pending; do not invent a world.
- [x] Independently recompute trace hash, reveal sequence and cost from sealed manifest. Record D0 hashes, source world/seal, policy artifacts, deterministic rerun results, unavailable-branch rate, isolation proof and failure cases in the D3 evidence file.
- [x] Commit only D3 files. Submit D3 evidence for Jun's review before D4 implementation; replay does not authorize ranking, RSI grading or deployment.

## Coverage and deferrals

| Spec requirement | Tasks | Evidence |
| --- | --- | --- |
| FR-003 / FR-011 | 1, 3 | identical public observation/action validation; no adapter or protected Action exposure |
| FR-004 / FR-005 | 2-4 | root-only reset; exact recorded child; deterministic trace and no external execution |
| FR-008 / FR-013 | 3-5 | zero prospective writes; explicit unavailable/failed/retry cost |
| SC-001 / SC-002 / SC-003 / SC-008 | 1-5 | real sealed world if available, reproducibility, visibility and isolation tests |

D3 does not pick a winner or count replay as prospective evidence. D4 consumes only sealed worlds and D3-completed, reproducible policy/world traces.
