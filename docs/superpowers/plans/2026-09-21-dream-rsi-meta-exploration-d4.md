# Dream-RSI Meta-Exploration D4 Tournament Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare a human-frozen incumbent and deterministic baselines across eligible sealed worlds and a protected time-forward holdout, selecting by safety-first lexicographic proof without granting deployment authority.

**Architecture:** The operator freezes a complete candidate/world/evaluator/aggregation decision contract through D1 `create_policy_tournament`. A pure evaluator consumes D3 replay outputs, produces one result or machine-readable exclusion for every matrix cell, and a deterministic selector independently derives the winner, stratum summary, archive disposition and proof. D1 `finish_policy_tournament` atomically records results and holdout exposure only after the selector's result is verified.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy Core, Ontology v2 Actions, pytest, Ruff. Spec sections 7.5, 10.1, 11 and 18.C-E/J/L; FR-006 through FR-008, FR-014, FR-019 through FR-021.

---

## Entry gates and frozen decisions

- Jun reviews D3 evidence. A live tournament is **not** run until the D0 record-to-baseline readiness gate passes with proven D3 replay availability, effective independent dates/worlds and completeness. Synthetic test matrices do not count as readiness evidence.
- D0 fixes quality field names, tier order and archive capacity, but not the numeric minimum materiality or full within-tier aggregation/worst-stratum brake. Before the first scored tournament, create an operator-reviewed immutable selection contract defining units, missing-value treatment, within-tier ordering, minimum materiality, worst-stratum brake and cost policy. Keep the D0 pilot unchanged; bind the new contract hash into the D1 tournament `decision_contract`. No score may be observed before this freeze.
- Initial candidate set is unchanged incumbent plus operator-registered deterministic baselines only. D0 `BaselinePolicyArtifact` fixes `policy_revision_id` to `structural-baseline-v1`; D4 must introduce a narrowly parameterized, strict `DeterministicBaselineVariantArtifact` and an interpreter accepted by D3's policy runner. Otherwise a challenger cannot be registered at this milestone. D5-generated optimizers cannot enter D4's baseline-only acceptance run. No winner automatically enters shadow/canary/deploy.
- Preserve and extend D1's mandatory incumbent, complete result matrix, archive bounds and exposure ledger. D1 currently accepts a structurally valid supplied winner: D4 must recompute the winner server-side and reject a mismatching completion, rather than trusting `reproduction_hash` as ranking proof.

## File map

- Create `nutmeg/discovery/selection_contract.py`: strict frozen evaluator/aggregation/materiality/brake/cost schema and content-addressed loader; bind its hash to tournament manifest.
- Create `nutmeg/discovery/baseline_variants.py`: closed declarative deterministic challenger artifact (template-shard ordering, batch limit and stop selector only), validate through D1's human-only registration Action and interpret through D3's policy-visible environment.
- Create `experiments/discovery/structural-selection-v1.contract.json`: reviewed, versioned deterministic comparator and worst-stratum limits; never rewrite in place after approval.
- Create `nutmeg/discovery/world_pool.py`: cutoff, strata, derivative-cluster, replay-eligibility and exposed-holdout selection.
- Create `nutmeg/discovery/tournament_scores.py`: pure per-world score vector and explicit exclusion/failure conversion.
- Create `nutmeg/discovery/tournament_selector.py`: deterministic cell aggregation, lexicographic winner, incumbent tie and archived stepping-stone checks.
- Create `nutmeg/discovery/tournament_runner.py`: orchestrate D3 replay, verify complete matrix, call D1 governance Actions.
- Modify `nutmeg/ontology/actions/discovery_governance_actions.py`: enforce derived selection, contract hash, duplicate-cluster and exposure invariants for every caller.
- Modify `nutmeg/ontology/discovery/read_service.py` and `nutmeg/interfaces/cli/discovery.py`: read-only per-world/stratum comparison with explicit exclusions and exposure status.
- Tests `tests/discovery/test_selection_contract.py`, `test_baseline_variants.py`, `test_world_pool.py`, `test_tournament_scores.py`, `test_tournament_selector.py`, `test_tournament_runner.py`, `tests/ontology/test_discovery_policy_actions.py`, `test_discovery_governance_actions.py`, `tests/test_cli_discovery.py`.
- Evidence `docs/superpowers/evidence/2026-09-21-meta-exploration-d4-tournament.md`.

### Task 1: Review and lock the comparison contract

**Files:** Create `nutmeg/discovery/selection_contract.py`, `experiments/discovery/structural-selection-v1.contract.json`; test `tests/discovery/test_selection_contract.py`.

- [x] **Step 1 (RED):** Test strict unknown-field rejection, D0 tier order/evaluator equality, `Decimal`-safe nonnegative materiality, no missing-as-zero, incumbent tie rule, declared cost units and failure penalty, all D0 quality fields in declared order, all strata/worst-stratum thresholds and stable canonical hash.

```python
def test_selection_contract_rejects_changed_tier_order(selection_document, pilot):
    bad = {**selection_document, "lexicographic_tiers": ["discovery_quality", "safety_isolation"]}
    with pytest.raises(ValueError, match="frozen|tier"):
        SelectionContract.model_validate_with_pilot(bad, pilot)
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_selection_contract.py -q`; expected missing-module failure.
- [x] **Step 3 (GREEN):** Implement strict schema and a draft immutable JSON contract with exact within-tier field order/directions and missing-value rules; set a conservative comparator (no higher-tier regression, strictly positive declared improvement, no worst-stratum decline) without altering the D0 evaluator. **Stop before registration/scoring** and get Jun's review of the numeric value and contract hash; only the approved version proceeds.
- [x] **Step 4:** Re-run tests and compare D0 hashes; commit schema/tests and approved artifact separately so the approval provenance is auditable.

### Task 2: Register one deterministic challenger without arbitrary code

**Files:** Create `nutmeg/discovery/baseline_variants.py`; modify `nutmeg/ontology/actions/discovery_policy_actions.py`, `nutmeg/discovery/replay_runner.py`; test `tests/discovery/test_baseline_variants.py`, `tests/ontology/test_discovery_policy_actions.py`.

- [x] **Step 1 (RED):** A challenger with a different ID but a closed template order/batch/stop configuration validates; two variants with identical content hash and seed replay identically. Unknown fields, executable code, model weights, changed evaluator/permissions, invalid operator, hidden holdout reference or `generator_family` other than `baseline` fail before replay. AI and deterministic actors cannot register.
- [x] **Step 2:** Run `uv run pytest tests/discovery/test_baseline_variants.py tests/ontology/test_discovery_policy_actions.py -q`; expected missing-module and new-case failures.
- [x] **Step 3 (GREEN):** Define a strict versioned `DeterministicBaselineVariantArtifact` that reuses D0's interface/constraint revision and grammar, with independent content-addressed policy ID. Extend D1 `register_policy` to validate this artifact separately from its fixed-ID incumbent and preserve the human-only Action. Extend D3 interpreter for exactly the declared deterministic choices; no dynamic import, filesystem/network or protected Actions.
- [x] **Step 4:** Re-run registration/replay tests, register a variant in a temporary store and compare two D3 traces. Commit.

### Task 3: Freeze a clean development/holdout world pool

**Files:** Create `nutmeg/discovery/world_pool.py`; test `tests/discovery/test_world_pool.py` and `tests/ontology/test_discovery_governance_actions.py`.

- [x] **Step 1 (RED):** Test sealed and manifest-verified only, all policies compatible, distinct time-forward development/holdout cutoffs, required available strata, failed/no-solution worlds retained, duplicate `(business_date, task_snapshot_hash, slate_revision_id)` clusters weighted once, exposed holdout never reused as hidden holdout, and explicit machine-readable rejection reasons.

```python
def test_same_snapshot_does_not_double_weight(world_pool, duplicated_world):
    sibling = dataclasses.replace(duplicated_world, world_id="sibling-world")
    selected = world_pool.freeze((duplicated_world, sibling), development_cutoff="2026-09-01T00:00:00+00:00")
    assert selected.effective_cluster_count == 1
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_world_pool.py -q`; expected missing-module failure.
- [x] **Step 3 (GREEN):** Compute canonical sorted candidate/world rows and hashes expected by D1 `CreatePolicyTournamentRequest`. Verify readiness **before** the human Action freezes the tournament; re-check inside that Action to avoid alternate-call bypass. No holdout result or child artifact is passed to candidate generation.
- [x] **Step 4:** Re-run tests and D1 governance regression; commit.

### Task 4: Evaluate every policy/world cell and aggregate strata

**Files:** Create `nutmeg/discovery/tournament_scores.py`; test `tests/discovery/test_tournament_scores.py`.

- [x] **Step 1 (RED):** Test success, explicit no-solution, unavailable branch, invalid output, absent cost, leakage/protected Action and replay hash mismatch. A higher discovery-quality score with a safety violation is disqualified. Report node count, rounds, retries, latency, actual cost, effective parallelism and unused budget separately; no ticket profit or RSI grade enters the vector.

```python
def test_safety_violation_disqualifies_even_with_best_quality(cell_fixture):
    result = score_replay(cell_fixture(quality="100", permission_breach=True))
    assert result.disqualified is True
    assert result.exclusion_reason == "permission_breach"
```

- [x] **Step 2:** Run `uv run pytest tests/discovery/test_tournament_scores.py -q`; expected missing-module failure.
- [x] **Step 3 (GREEN):** Implement typed, versioned score vectors using the approved selection contract and D3 replay completion; explicit missing/estimated cost cannot silently become zero. Summarize by lane, competition, channel, odds band, board-size and degraded/failure strata when labels exist.
- [x] **Step 4:** Re-run scores tests; commit.

### Task 5: Select by lexicographic proof and independent holdout

**Files:** Create `nutmeg/discovery/tournament_selector.py`; modify `nutmeg/ontology/actions/discovery_governance_actions.py`; test `tests/discovery/test_tournament_selector.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [x] **Step 1 (RED):** Cover incumbent inclusion, complete matrix, policy disqualification on any safety violation, no higher-tier regression, materiality failure, exact tie favoring incumbent, worst-stratum decline, development winner losing holdout, favorable cost unable to offset worse validity, and permuted input order yielding the same winner/proof.

```python
def test_holdout_brake_keeps_incumbent(frozen_tournament):
    result = select_winner(frozen_tournament.with_challenger(dev_gain="1", worst_holdout_delta="-1"))
    assert result.winner_policy_revision_id == frozen_tournament.incumbent_policy_revision_id
```

- [x] **Step 2:** Run the selector and governance tests red.
- [x] **Step 3 (GREEN):** Derive result for each cell and stratum; independently recompute selection in `finish_tournament` from the frozen decision contract and matrix, reject a supplied winner/proof mismatch, hash contract+manifests+ordered cells+strata+winner. Keep selection separate from archive admission. If D1 proof formula changes, migrate tests/consumers in the same task without rewriting historical rows.
- [x] **Step 4:** Re-run tests, shared Ontology tests and protected-action regressions; commit.

### Task 6: Archive decisions and exposure atomicity

**Files:** Modify `nutmeg/discovery/tournament_selector.py`, `nutmeg/ontology/actions/discovery_governance_actions.py`; test `tests/discovery/test_tournament_selector.py`, `tests/ontology/test_discovery_governance_actions.py`.

- [x] **Step 1 (RED):** Test bounded nonwinner `stepping_stone` admission only for frozen reason, sufficient diversity and evidence; disqualified/irreproducible/clone rejected; capacity 12 and max 3 per lineage; deterministic dominated-clone eviction before unique candidate. Winner unchanged regardless of admission.
- [x] **Step 2:** Run focused tests red, implement independent archive result and eviction event through D1 Action; run green. Prove all holdout exposures and result/completion/archive rows commit atomically, with rollback on one invalid cell. Commit.

### Task 7: Reproduce report and acceptance gate

**Files:** Create `nutmeg/discovery/tournament_runner.py`; modify read-only projection/CLI; tests `tests/discovery/test_tournament_runner.py`, `tests/test_cli_discovery.py`.

- [x] **Step 1 (RED):** Two runs with identical frozen inputs yield identical ordered per-cell trace/proof. UI/CLI detail reports all cells or explicit exclusions, worst stratum, held-out period, incumbent, reason, archive decisions, exposures and contract hash; fresh-store read creates no DB.
- [x] **Step 2:** Run focused tests red, implement D3 replay orchestration and D1 Action calls with immutable input freeze, run green. Authoritative creation still requires a human operator; no AI/deterministic runner may self-create a tournament.
- [x] **Step 3:** Run `uv run pytest tests/discovery tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_governance_actions.py tests/ontology/test_protected_ticket_actions.py tests/ontology/test_rsi_actions.py tests/test_cli_discovery.py -q`, `uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_policy_actions.py nutmeg/ontology/actions/discovery_governance_actions.py nutmeg/ontology/discovery/read_service.py nutmeg/interfaces/cli/discovery.py tests/discovery tests/test_cli_discovery.py`, `git diff --check`, `uv run pytest -q`. Record exit codes/counts.
- [x] **Step 4:** On a temporary store, independently recompute matrix, selection proof and exposed slice from frozen artifacts; record exact readiness and operator approvals. A live tournament is deferred if world coverage fails; fixture pass is not real-world comparison evidence. Write D4 evidence, commit only D4 files, request Jun's review before D5 implementation.

## Coverage

| Requirement | Tasks | Gate |
| --- | --- | --- |
| FR-006 / FR-007 / SC-006 / SC-007 | 1-5, 7 | frozen incumbent/worlds/evaluator; complete safety-first matrix and time-forward holdout |
| FR-014 / FR-019 / FR-020 / SC-013 | 5-7 | reproducible proof and separate bounded archive decision |
| FR-021 / SC-014 | 3, 6 | exposed holdout ledger, no hidden reuse, atomic commit |

D4 has no policy generator, prospective promotion or deployment. D5 must enforce its own optimizer gate even when D4 baseline comparison passes.
