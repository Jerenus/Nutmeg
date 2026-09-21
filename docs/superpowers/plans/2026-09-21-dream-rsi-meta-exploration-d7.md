# Dream-RSI Meta-Exploration D7 Recursive Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operate repeated governed discovery cycles only when independently measured new information justifies a new frozen tournament, with protected holdout rotation, bounded archive maintenance and drift-driven hold signals.

**Architecture:** Each newly sealed D2 prospective world changes a read-only pool projection but never mutates prior tournaments. A versioned, operator-approved information-trigger contract compares effective new clusters, action coverage, failures and strata against the last completed round. A readiness review can propose a new D4 tournament to the human operator only after D3 replay integrity and D5 generation gates pass; D4 Actions still freeze it and expose holdout results atomically. D6 deployment/brake remains a separate human/reduce-only authority.

**Tech Stack:** Python 3.13, Ontology v2 append-only events and read projections, D2-D6 services, pytest, Ruff. Spec sections 11.3-11.6, 12.1 and 18.I/J/L; FR-018 through FR-022; SC-012 through SC-015.

---

## Preconditions and invariants

- Jun reviews D6 evidence. A prior tournament and new sealed prospective worlds are needed for a real second cycle. Temporary synthetic fixtures prove code behavior but cannot establish real effectiveness.
- D0 freezes numerical **readiness** gates and archive rules, but does not provide numeric **information-trigger** thresholds or drift limits. Before running a recursive cycle, freeze and get Jun's approval of a versioned trigger/drift contract with independent-cluster count, action-overlap change, failure/stratum shift, worst-stratum brake and maximum round frequency. An operator may request review earlier, not waive a failed gate.
- A completed tournament is immutable. The next candidate/world/holdout set is a new D1 `PolicyTournament` and new D4 proof. Exposed holdouts may enter later development only after a strictly newer, sealed time-forward hidden holdout has been frozen for that new tournament; an exposed world is never hidden again for the same lineage.
- No scheduler automatically creates a human-only `create_policy_tournament`, `register_policy_revision` or `approve_policy_deployment` Action. It may propose/notify, and may invoke only the preregistered reduce-only brake.
- Drift without proven quality gain means hold/review recommendation, not challenger win. D7 must not turn duplicate worlds, archive novelty or repeated tuning on an exposed slice into apparent improvement.

## File map

- Create `nutmeg/discovery/iteration_contract.py`: strict versioned information trigger and drift thresholds, frozen hash.
- Create `experiments/discovery/structural-iteration-v1.contract.json`: reviewed trigger/drift artifact, separate from D0 pilot contract.
- Create `nutmeg/discovery/iteration_readiness.py`: pure effective-new-information projection and fail-closed trigger result.
- Create `nutmeg/discovery/holdout_rotation.py`: exposure-ledger and lineage-aware time-forward role validation.
- Create `nutmeg/discovery/archive_maintenance.py`: bounded deterministic admission/eviction proposal built from D4 evidence, no direct deployment.
- Create `nutmeg/discovery/drift_monitor.py`: per-stratum behavior/quality/cost/failure and parallelism comparison; hold/brake proposals.
- Modify `nutmeg/ontology/actions/discovery_governance_actions.py`: server-side exposure/rotation checks for direct Action callers and separate archived/nonwinner evidence.
- Modify `nutmeg/ontology/discovery/read_service.py` and `nutmeg/interfaces/cli/discovery.py`: read-only operational timeline, effective count, trigger blocks, holdout lineage, archive and drift.
- Tests `tests/discovery/test_iteration_contract.py`, `test_iteration_readiness.py`, `test_holdout_rotation.py`, `test_archive_maintenance.py`, `test_drift_monitor.py`, `tests/ontology/test_discovery_governance_actions.py`, `tests/test_cli_discovery.py`.
- Evidence `docs/superpowers/evidence/2026-09-21-meta-exploration-d7-recursive-operation.md`.

### Task 1: Preregister information and drift rules

**Files:** Create `nutmeg/discovery/iteration_contract.py`, `experiments/discovery/structural-iteration-v1.contract.json`; test `tests/discovery/test_iteration_contract.py`.

- [ ] **Step 1 (RED):** Reject unknown fields, negative/zero effective-information threshold, threshold expressed only as elapsed time, missing duplicate-cluster key, weaker D0 readiness/holdout guard, absent per-stratum brake and a rule that auto-creates a tournament or deployment.

```python
def test_calendar_alone_cannot_trigger_round(contract_document):
    bad = {**contract_document, "min_effective_new_clusters": 0, "max_elapsed_days": 1}
    with pytest.raises(ValueError, match="effective"):
        IterationContract.model_validate(bad)
```

- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_iteration_contract.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Implement strict schema and an immutable artifact with exact cluster/action/failure/stratum thresholds, drift tolerances, holdout freshness and maximum repeat frequency; use D0's duplicate key and archive capacity unchanged. Get Jun's approval of exact numbers/hash **before** first operational trigger. No retroactive effect on completed rounds.
- [ ] **Step 4:** Re-run tests, record approved hash, commit only contract/model/tests.

### Task 2: Count effective information rather than raw worlds

**Files:** Create `nutmeg/discovery/iteration_readiness.py`; test `tests/discovery/test_iteration_readiness.py`.

- [ ] **Step 1 (RED):** Add a sealed new world distinct by D0 cluster key, a duplicate on same date/snapshot, a derivative tree, an added legal action, new failure case and a changed required stratum. Assert only independent clusters increase effective count; added action/failure/stratum gives explicit signal. Unknown replay availability or failed D0 readiness blocks trigger.

```python
def test_duplicate_world_does_not_trigger_next_cycle(previous, duplicate):
    report = review_new_information(previous, (duplicate,))
    assert report.effective_new_clusters == 0
    assert report.ready_for_operator_tournament_request is False
```

- [ ] **Step 2:** Run `uv run pytest tests/discovery/test_iteration_readiness.py -q`; expected missing-module failure.
- [ ] **Step 3 (GREEN):** Compare only sealed, manifest-valid post-boundary worlds to the last completed frozen pool. Return separate stable failed metrics, raw/new/effective counts and change descriptors; retain `record_only` or baseline mode if optimizer coverage fails. Operator-requested review computes the same checks but does not override them.
- [ ] **Step 4:** Re-run tests and D2 readiness tests; commit.

### Task 3: Rotate exposed holdout under strict temporal lineage

**Files:** Create `nutmeg/discovery/holdout_rotation.py`; modify `nutmeg/ontology/actions/discovery_governance_actions.py`; test `tests/discovery/test_holdout_rotation.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [ ] **Step 1 (RED):** Reuse exposed world as hidden holdout always rejects. Reuse as development rejects until a **strictly later** sealed holdout has been frozen (before results). A merely newer calendar date, unsealed world, same cutoff, derivative cluster, world previously exposed for that policy lineage, or newly frozen holdout shared with generator input rejects.

```python
def test_exposed_slice_needs_newer_protected_holdout(ledger, exposed_world, same_day_world):
    with pytest.raises(ValueError, match="strictly newer"):
        freeze_roles(ledger, development=(exposed_world,), holdout=(same_day_world,))
```

- [ ] **Step 2:** Run focused tests red. Validate role allocation using D1 `policy_holdout_exposures`, D3 visibility and policy-parent lineage; bind role/cluster/cutoff to the next immutable world-pool manifest. Add an Action-side check so directly constructed requests cannot bypass it.
- [ ] **Step 3:** Re-run tests, including a positive later holdout and a failed Action with no partial exposure; commit.

### Task 4: Maintain bounded stepping stones without changing winner

**Files:** Create `nutmeg/discovery/archive_maintenance.py`; test `tests/discovery/test_archive_maintenance.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [ ] **Step 1 (RED):** With 12 archived policies, one complementary candidate and one dominated clone, evict the clone deterministically; preserve a unique earlier stepping stone. Reject disqualified/irreproducible candidate, unapproved generator parent, lineage cap >3 and an admission that changes the D4 winner or implies deployment.
- [ ] **Step 2:** Run tests red. Implement immutable admission/eviction proposals under D0 diversity descriptors and distance 0.2; persist decisions only via the next D1 tournament completion Action, never as an intermediate mutable archive update or policy-row edit.
- [ ] **Step 3:** Re-run tests and independent D4 proof verification; commit.

### Task 5: Detect behavior drift and provide an operator hold signal

**Files:** Create `nutmeg/discovery/drift_monitor.py`; test `tests/discovery/test_drift_monitor.py`.

- [ ] **Step 1 (RED):** Compare new sealed worlds to parent/incumbent by discovery quality, nodes, rounds, effective parallelism, failure recovery, solution diversity and each required stratum. Increased branch use with no frozen material quality improvement yields `hold_for_review`; a registered hard invariant yields a D6 brake signal only, never a new winning policy.
- [ ] **Step 2:** Run tests red. Implement explicit unavailable/insufficient-sample state rather than optimistic default; redact hidden holdout outcomes from generator input and preserve raw comparison evidence hash. Re-run green; commit.

### Task 6: Read-only operator timeline and second-cycle proof

**Files:** Modify `nutmeg/ontology/discovery/read_service.py`, `nutmeg/interfaces/cli/discovery.py`; test `tests/test_cli_discovery.py`.

- [ ] **Step 1 (RED):** Query shows policy lineage, latest pool and excluded duplicates, current data mode, trigger blocks, time-forward protected holdout, exposed slices, archive capacity, drift and any pending human approval. Empty store query must not initialize/migrate. Repeated review cannot enqueue a second tournament.
- [ ] **Step 2:** Run CLI tests red; implement read-only projections, run green; commit.
- [ ] **Step 3:** Run `uv run pytest tests/discovery tests/ontology/test_discovery_governance_actions.py tests/ontology/test_discovery_policy_actions.py tests/ontology/test_rsi_actions.py tests/ontology/test_protected_ticket_actions.py tests/test_cli_discovery.py -q`, `uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_governance_actions.py nutmeg/ontology/discovery/read_service.py nutmeg/interfaces/cli/discovery.py tests/discovery tests/test_cli_discovery.py`, `git diff --check`, `uv run pytest -q`. Record exact outputs and existing unrelated failures separately.
- [ ] **Step 4:** On a temporary store demonstrate two complete cycles with an unchanged old tournament, effective-world trigger, distinct newer hidden holdout, atomic exposure ledger, bounded archive and drift hold; verify zero protected Actions. A real second cycle requires actual D2-D6 evidence and fresh human tournament/deployment approvals. Write D7 evidence, commit only D7 paths and request Jun's final v1 review.

## Coverage

| Requirement | Tasks | Proof |
| --- | --- | --- |
| FR-018 / FR-022 / SC-012 | 1-2, 6 | frozen information trigger; fail-closed optimizer gate and no repeated tuning |
| FR-019 / FR-020 / SC-013 | 4 | bounded separate stepping-stone admission and eviction |
| FR-021 / SC-014 | 3, 6 | exposed slice never hidden again, strictly newer frozen holdout |
| FR-015 / SC-010 | 5-6 | drift hold and D6 reduce-only brake, visible to operator |

D7 reports readiness and can propose a new cycle; it does not autonomously approve a tournament, deployment, money action or public dispatch.
