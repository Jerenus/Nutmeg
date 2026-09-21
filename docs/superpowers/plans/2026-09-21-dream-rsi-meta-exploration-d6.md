# Dream-RSI Meta-Exploration D6 Prospective Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a replay winner on fresh prospective worlds in shadow, then permit only separate human decisions for pilot-scoped canary, deployment and rollback with an immediate reduce-only brake.

**Architecture:** The D4 tournament winner is a proposal, never an active controller. D6 authorizes an isolated D2-style shadow run after a human `approve_policy_deployment(shadow)` Action, tracks its preregistered window and freezes prospective evidence at close. A separate human Action can canary or deploy only at a safe business boundary with a previously human-approved fallback; runtime reads the latest scoped deployment and stops on a registered hard invariant. No policy controls protected business Actions.

**Tech Stack:** Python 3.13, Ontology v2 ActionService, D2 recorder, D3 policy environment, D4 proof/readiness, pytest, Ruff. Spec sections 7.6, 12, 13.4, 15 and 18.F-H; FR-009/010/012/015; SC-004/008/009/010.

---

## Entry gate and frozen-mode constraint

- Jun reviews D5 evidence. Every real shadow/canary/deploy/rollback/retire decision requires its own explicit human Action; this plan and a passing fixture never authorize it.
- D0 pilot contract `mode="shadow_only"` cannot be silently reinterpreted as canary/deploy permission. Shadow runs may use that frozen contract. To **actually enable** canary/deploy, first create and approve a prospective scope/contract revision specifying which structural operations may control which business boundary, the verified no-ticket fallback, maximum exposure and hard brake conditions. If that revision has not been reviewed, keep runtime shadow-only even if D1 can persist a deployment decision. Do not rewrite D0 artifact or change football rules.
- A challenger may enter prospective shadow only if it is the latest D4 tournament winner under a verified frozen proof. `canary` and `deploy` require sealed, fresh, out-of-tournament prospective shadow worlds after the holdout cutoff, a closed preregistered shadow window, zero protected writes, and a distinct earlier human-approved fallback in the same family/scope.
- D1 `approve_deployment` verifies a fresh sealed shadow world but does not check its predeclared window, protected-state fingerprint or shadow result. Add fail-closed Action-side validation; a CLI/view-only policy must not decide eligibility.
- The brake is deterministic and reduce-only; it never chooses a new fallback, silently resumes a braked policy, places a ticket or grants funds/public-output authority.

## File map

- Create `nutmeg/discovery/promotion_evidence.py`: immutable shadow window, cutoff, eligibility and isolation proof over D2/D4/D5 facts.
- Create `nutmeg/ontology/repository/schema_discovery_promotion.py`; modify `nutmeg/ontology/repository/migrations.py`, `discovery.py` and `nutmeg/ontology/actions/discovery_governance_actions.py`: migration 42 adds append-only preregistered shadow windows and a human-only `preregister_policy_shadow_window` Action; do not alter migration 40 or 41.
- Create `nutmeg/discovery/pilot_scope.py`: strictly validated, versioned canary/deploy scope and closed allowed-operator revision; rejects D0 shadow-only contract as control authorization.
- Create `nutmeg/discovery/deployment_runtime.py`: lookup scoped authority at boundary, select incumbent/fallback, stop new work on brake, record per-run policy identity.
- Create `nutmeg/discovery/brake_monitor.py`: deterministic evaluation of preregistered invariant codes, call D1 `trip_policy_brake` once.
- Modify `nutmeg/ontology/actions/discovery_governance_actions.py`: verify prospective/window/scope evidence and human actor at every path; preserve D1 append-only rows.
- Modify `nutmeg/ontology/discovery/read_service.py` and `nutmeg/interfaces/cli/discovery.py`: read-only incumbent, pending shadow, scope, effective boundary, brake and fallback projection.
- Tests `tests/discovery/test_promotion_evidence.py`, `test_pilot_scope.py`, `test_deployment_runtime.py`, `test_brake_monitor.py`, `tests/ontology/test_discovery_governance_actions.py`, `tests/test_cli_discovery.py`.
- Evidence `docs/superpowers/evidence/2026-09-21-meta-exploration-d6-prospective-promotion.md`.

### Task 1: Preregister and close a prospective shadow window

**Files:** Create `nutmeg/discovery/promotion_evidence.py`, `nutmeg/ontology/repository/schema_discovery_promotion.py`; modify migrations/repository/governance Action; test `tests/discovery/test_promotion_evidence.py`, `tests/ontology/test_discovery_migration.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [ ] **Step 1 (RED):** Test window with explicit family/scope/candidate/approved winner/tournament ID, start/end cutoffs, minimum effective independent worlds and invariant checks; reject shadow run before human Action, after cutoff, using tournament/development world, duplicate derivative world, replay source or unsealed world. A window still open is ineligible.

```python
def test_replay_winner_without_new_sealed_shadow_cannot_promote(window, tournament):
    result = evaluate_shadow_window(window, tournament, sealed_worlds=())
    assert result.eligible_for_canary is False
    assert "fresh_prospective_world" in result.blocking_codes
```

- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_promotion_evidence.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Add migration 42 with a `policy_shadow_windows` append-only table and human-only `preregister_policy_shadow_window` permission/Action. Freeze family, scope, tournament, candidate, future start/end cutoff, minimum independent worlds and hard invariant codes before the first shadow run; record the window hash in D1 `PolicyDeploymentRow.evidence_refs`. Compute eligibility from actual D2 sealed `prospective_online` worlds and protected-table fingerprints. No replay grade counts as a prospective sample.
- [ ] **Step 4:** Re-run tests; include AI/deterministic actor denial, altered/late evidence and optimistic concurrency cases; commit.

### Task 2: Separate shadow authority from pilot control authority

**Files:** Create `nutmeg/discovery/pilot_scope.py`; modify `nutmeg/ontology/actions/discovery_governance_actions.py`; tests `tests/discovery/test_pilot_scope.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [ ] **Step 1 (RED):** `shadow` permits isolated recording only; `canary`/`deploy` on D0 `shadow_only` without a reviewed scope revision must reject. Scope may name only structural candidate exploration, explicit board/task family, capped exposure and safe effective boundary; unknown/expanded scope, protected Action grant, weaker brake or unapproved fallback rejects.
- [ ] **Step 2:** Run focused tests red.
- [ ] **Step 3 (GREEN):** Add strict scope revision hash referenced from `PolicyDeploymentRow.scope` and `evidence_refs`; require human actor/role, approved window evidence and earlier distinct human-approved fallback in the same scope at Action time. Leave production control disabled until Jun explicitly approves the new scope contract, then use only its enumerated structural operations.
- [ ] **Step 4:** Re-run governance and permission regressions; commit schema/validation and tests; request human scope approval separately from any run.

### Task 3: Determine one active controller per family and scope

**Files:** Create `nutmeg/discovery/deployment_runtime.py`; test `tests/discovery/test_deployment_runtime.py`.

- [ ] **Step 1 (RED):** After a human `shadow` decision, authoritative workflow remains unchanged. `canary` activates only at the approved future business boundary for in-scope boards and within exposure cap. `deploy` supersedes exactly one prior event, and out-of-scope boards continue the existing controller. Concurrent decisions cannot yield two incumbents.

```python
def test_shadow_never_controls_business_workflow(runtime, shadow_event, board):
    controller = runtime.controller_for(board, boundary=shadow_event.effective_boundary)
    assert controller.authoritative is False
    assert controller.mode == "shadow"
```

- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_deployment_runtime.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Resolve deployment from D1 latest event **for the exact scope**, check brake and effective boundary before starting each new run, bind policy revision and scope hash into world/run lineage; never infer authority from archive status or replay winner. Verify the existing candidate/ticket workflow remains the authority outside an explicitly approved canary/deploy scope.
- [ ] **Step 4:** Re-run tests and protected ticket/RSI regressions; commit.

### Task 4: Trip a preregistered brake and require human disposition

**Files:** Create `nutmeg/discovery/brake_monitor.py`; modify `nutmeg/ontology/actions/discovery_governance_actions.py` to enforce registered condition evidence; test `tests/discovery/test_brake_monitor.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [ ] **Step 1 (RED):** A registered permission leak, audit invalidation, protected-table mutation, resource overrun or manifest breach stops new policy runs, records one `trip_policy_brake` Action and restores only the deployment's previously human-approved fallback at the next safe boundary. A nonregistered condition cannot choose a target; repeated brake is idempotent.
- [ ] **Step 2:** Run focused tests red. Implement event-driven monitor consuming committed facts (not policy self-report) and invoke the D1 brake Action with deterministic-system actor, exact condition code and evidence hash. Re-run green.
- [ ] **Step 3:** Assert a braked candidate cannot resume or expand scope without a **new** human Action; human rollback/hold/retire preserves history. Commit.

### Task 5: Operator projection, verification and review

**Files:** Modify `nutmeg/ontology/discovery/read_service.py`, `nutmeg/interfaces/cli/discovery.py`; test `tests/test_cli_discovery.py`.

- [ ] **Step 1 (RED):** Status distinguishes replay winner, human-authorized shadow, current scoped canary/deploy, braked fallback and pending human disposition; reports latest tournament proof, shadow window end/effective count, scope hash and rollback target. Read-only query neither initializes nor migrates an empty store.
- [ ] **Step 2:** Run `uv run pytest tests/test_cli_discovery.py -q` red; implement read-only projections. A schema-40/41 store reports "promotion unavailable; migration 42 required" without query-time migration. Re-run green. Commit.
- [ ] **Step 3:** Run `uv run pytest tests/discovery tests/ontology/test_discovery_governance_actions.py tests/ontology/test_protected_ticket_actions.py tests/ontology/test_rsi_actions.py tests/test_cli_discovery.py -q`, `uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_governance_actions.py nutmeg/ontology/discovery/read_service.py nutmeg/interfaces/cli/discovery.py tests/discovery tests/test_cli_discovery.py`, `git diff --check`, `uv run pytest -q`. Record exact results.
- [ ] **Step 4:** Verify promotion denial and automatic brake with temporary stores; compare protected business hashes. Do **not** perform live canary/deploy/rollback without separate human approval. Record contract revision, scope, shadow evidence, fallback and gate denials in D6 evidence; commit D6 files and request Jun's review before D7 implementation.

## Coverage

| Requirement | Tasks | Proof |
| --- | --- | --- |
| FR-009 / SC-009 | 1-2 | fresh, sealed prospective shadow window, human Action before promotion |
| FR-010 / FR-015 / SC-010 | 2-5 | one scoped incumbent, human authority, reduce-only brake and visible rollback |
| FR-012 / SC-004 / SC-008 | 1-3, 5 | shadow isolation, protected fingerprint, no ticket/funds authority |

D6 changes exploration policy authority only. It does not approve football judgments, ticket placement, funds, public output or automatic promotion.
