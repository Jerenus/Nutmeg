# Dream-RSI Meta-Exploration D0 Contract Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a machine-readable structural-candidate discovery pilot, its deterministic incumbent policy, evaluator, data-readiness gates, and archive limits without executing a harness or changing production behavior.

**Architecture:** D0 adds a strict Pydantic contract loader under `nutmeg/discovery/` and two reviewed JSON artifacts under `experiments/discovery/`. The artifacts point at the existing exhaustive candidate generator and audit surface, but they do not call them; D1 will register their content hashes in Ontology and D2 will execute them in shadow. An as-built evidence document records the exact reuse/gap boundary so later milestones cannot quietly redefine D0.

**Tech Stack:** Python 3.13, Pydantic v2, canonical JSON/SHA-256, pytest. Governing spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`.

---

## Milestone boundary

D0 is contract work only. It must not:

- add database tables, migrations, Actions, CLI mutations, or scheduler jobs;
- run candidate generation, audit, replay, tournament, shadow, canary, or deployment;
- write `.nutmeg-data`, experiment observations, verdicts, or production candidate state;
- change `nutmeg.product.operator_candidates`, football rules, audit rules, or model weights.

The next milestone consumes the frozen artifact hashes. D0 therefore completes only when the same files load deterministically, reject unknown fields, and produce stable hashes.

## File structure

- Create `nutmeg/discovery/__init__.py` — public exports for frozen discovery contracts.
- Create `nutmeg/discovery/contracts.py` — strict contract DTOs, cross-field validation, canonical hashing, and JSON loaders; no IO other than explicit file loading.
- Create `experiments/discovery/structural-candidate-v1.contract.json` — pilot, evaluator, readiness, archive, and safety contract.
- Create `experiments/discovery/structural-baseline-v1.policy.json` — current exhaustive deterministic behavior represented as the incumbent policy artifact.
- Create `tests/discovery/__init__.py` — discovery test package marker.
- Create `tests/discovery/test_contracts.py` — strict parsing, invariants, hash stability, and no-authority tests.
- Create `docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md` — reviewed as-built/gap matrix and D0 acceptance evidence template.

---

### Task 1: Add strict, content-addressed D0 contract models

**Files:**
- Create: `nutmeg/discovery/__init__.py`
- Create: `nutmeg/discovery/contracts.py`
- Create: `tests/discovery/__init__.py`
- Test: `tests/discovery/test_contracts.py`

- [x] **Step 1: Write the failing tests for strict loading and cross-field invariants**

```python
# tests/discovery/test_contracts.py
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nutmeg.discovery.contracts import (
    BaselinePolicyArtifact,
    PilotContract,
    canonical_hash,
    load_baseline_policy,
    load_pilot_contract,
)


def _pilot() -> dict[str, object]:
    return {
        "schema_version": "1",
        "pilot_id": "structural-candidate-v1",
        "task_family": "structural_candidate_audit",
        "lane": "jczq",
        "mode": "shadow_only",
        "authoritative_workflow": {
            "generator": "nutmeg.product.operator_candidates:enumerate_band_candidates",
            "candidate_set_kind": "judgment_bound",
            "generator_version": "operator-candidate-v2-bands",
            "audit_policy_source": "candidate_set.audit_policy_version",
        },
        "operator_grammar": [
            {"name": "enumerate_template_shard", "parameters": ["template_ids"]},
            {"name": "stop", "parameters": ["selected_node_ids", "reason"]},
        ],
        "evaluator": {
            "revision": "structural-candidate-evaluator-v1",
            "lexicographic_tiers": [
                "safety_isolation", "validity", "discovery_quality",
                "robustness", "cost", "parallel_efficiency",
            ],
            "quality_fields": [
                "eligible_band_count", "best_objective_probability_by_band",
                "distinct_valid_candidate_count_capped",
            ],
            "candidate_count_cap_per_band": 20,
        },
        "readiness": {
            "record_to_baseline": {
                "min_sealed_worlds": 30,
                "min_independent_business_dates": 20,
                "min_effective_sample_size": 24,
                "min_manifest_completeness": 1.0,
                "min_multi_alternative_fraction": 0.80,
                "min_action_overlap": 0.0,
                "max_branch_unavailable_rate": 0.40,
                "min_failed_or_degraded_worlds": 0,
                "min_worlds_per_required_stratum": 0,
            },
            "baseline_to_optimizer": {
                "min_sealed_worlds": 60,
                "min_independent_business_dates": 40,
                "min_effective_sample_size": 48,
                "min_manifest_completeness": 1.0,
                "min_multi_alternative_fraction": 0.85,
                "min_action_overlap": 0.70,
                "max_branch_unavailable_rate": 0.25,
                "min_failed_or_degraded_worlds": 3,
                "min_worlds_per_required_stratum": 8,
            },
            "required_strata": ["board_size:small", "board_size:medium", "board_size:large"],
            "duplicate_cluster_key": ["business_date", "task_snapshot_hash", "slate_revision_id"],
        },
        "archive": {
            "capacity": 12,
            "max_per_lineage": 3,
            "diversity_descriptors": [
                "action_histogram", "stop_depth", "selected_band_coverage", "stratum_strengths"
            ],
            "admission_reasons": [
                "behavioral_coverage", "underrepresented_stratum", "novel_legal_trajectory"
            ],
            "minimum_action_jaccard_distance": 0.20,
            "eviction_order": ["disqualified", "irreproducible", "dominated_clone", "oldest"],
        },
        "budgets": {
            "max_rounds": 4, "max_nodes": 32, "max_concurrency": 4,
            "max_wall_seconds": 120, "max_candidate_generation_count": 50000,
        },
        "frozen_surfaces": [
            "model_weights", "evaluator_code", "action_permissions",
            "ontology_handlers", "football_rules", "audit_rules", "funds_actions",
        ],
        "protected_actions": [
            "confirm_ticket_placement", "record_cash_transaction", "rsi_approve_deployment",
        ],
    }


def _policy() -> dict[str, object]:
    return {
        "schema_version": "1",
        "policy_revision_id": "structural-baseline-v1",
        "family": "structural_candidate_exploration",
        "interface_version": "discovery-policy-v1",
        "constraints_version": "structural-candidate-v1",
        "generator_family": "baseline",
        "change_surfaces": ["exploration_policy"],
        "random_seed_policy": {"kind": "none", "deterministic": True},
        "compatible_world_families": ["structural_candidate_audit"],
        "steps": [
            {"round": 1, "action": "continue_batch", "selector": "all_template_shards"},
            {"round": 2, "action": "stop", "selector": "best_audit_clean_node_per_band"},
        ],
        "rationale": "Represent current bounded exhaustive generation as the incumbent.",
    }


def test_contracts_reject_unknown_fields_and_non_shadow_mode(tmp_path):
    bad = {**_pilot(), "unknown": True}
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError, match="unknown"):
        load_pilot_contract(path)

    bad = {**_pilot(), "mode": "production"}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError, match="shadow_only"):
        load_pilot_contract(path)


def test_optimizer_gate_is_stricter_than_baseline_gate():
    contract = PilotContract.model_validate(_pilot())
    baseline = contract.readiness.record_to_baseline
    optimizer = contract.readiness.baseline_to_optimizer
    assert optimizer.min_sealed_worlds >= baseline.min_sealed_worlds
    assert optimizer.min_independent_business_dates >= baseline.min_independent_business_dates
    assert optimizer.min_effective_sample_size >= baseline.min_effective_sample_size
    assert optimizer.min_action_overlap >= baseline.min_action_overlap
    assert optimizer.max_branch_unavailable_rate <= baseline.max_branch_unavailable_rate


def test_policy_is_baseline_only_and_has_no_authority_surface():
    policy = BaselinePolicyArtifact.model_validate(_policy())
    assert policy.generator_family == "baseline"
    assert policy.change_surfaces == ("exploration_policy",)
    assert all("deploy" not in step.selector for step in policy.steps)


def test_canonical_hash_is_stable_and_changes_with_semantics(tmp_path):
    pilot = PilotContract.model_validate(_pilot())
    first = canonical_hash(pilot)
    second = canonical_hash(PilotContract.model_validate(dict(reversed(_pilot().items()))))
    assert first == second
    changed = PilotContract.model_validate({**_pilot(), "budgets": {**_pilot()["budgets"], "max_nodes": 33}})
    assert canonical_hash(changed) != first

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy()), encoding="utf-8")
    assert load_baseline_policy(path).policy_revision_id == "structural-baseline-v1"
```

- [x] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/discovery/test_contracts.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'nutmeg.discovery'`.

- [x] **Step 3: Implement strict contract models and canonical hashing**

```python
# nutmeg/discovery/__init__.py
from nutmeg.discovery.contracts import (
    BaselinePolicyArtifact,
    PilotContract,
    canonical_hash,
    load_baseline_policy,
    load_pilot_contract,
)

__all__ = [
    "BaselinePolicyArtifact",
    "PilotContract",
    "canonical_hash",
    "load_baseline_policy",
    "load_pilot_contract",
]
```

```python
# nutmeg/discovery/contracts.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nutmeg.ontology.actions.models import canonical_json


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowBinding(FrozenContract):
    generator: Literal["nutmeg.product.operator_candidates:enumerate_band_candidates"]
    candidate_set_kind: Literal["judgment_bound"]
    generator_version: Literal["operator-candidate-v2-bands"]
    audit_policy_source: Literal["candidate_set.audit_policy_version"]


class OperatorSpec(FrozenContract):
    name: Literal["enumerate_template_shard", "stop"]
    parameters: tuple[str, ...]


class EvaluatorContract(FrozenContract):
    revision: Literal["structural-candidate-evaluator-v1"]
    lexicographic_tiers: tuple[str, ...]
    quality_fields: tuple[str, ...]
    candidate_count_cap_per_band: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "EvaluatorContract":
        required = (
            "safety_isolation", "validity", "discovery_quality",
            "robustness", "cost", "parallel_efficiency",
        )
        if self.lexicographic_tiers != required:
            raise ValueError("evaluator lexicographic order is frozen")
        return self


class ReadinessThreshold(FrozenContract):
    min_sealed_worlds: int = Field(ge=1)
    min_independent_business_dates: int = Field(ge=1)
    min_effective_sample_size: int = Field(ge=1)
    min_manifest_completeness: float = Field(ge=0.0, le=1.0)
    min_multi_alternative_fraction: float = Field(ge=0.0, le=1.0)
    min_action_overlap: float = Field(ge=0.0, le=1.0)
    max_branch_unavailable_rate: float = Field(ge=0.0, le=1.0)
    min_failed_or_degraded_worlds: int = Field(ge=0)
    min_worlds_per_required_stratum: int = Field(ge=0)


class ReadinessContract(FrozenContract):
    record_to_baseline: ReadinessThreshold
    baseline_to_optimizer: ReadinessThreshold
    required_strata: tuple[str, ...]
    duplicate_cluster_key: tuple[str, ...]

    @model_validator(mode="after")
    def validate_monotonic_gates(self) -> "ReadinessContract":
        low, high = self.record_to_baseline, self.baseline_to_optimizer
        increasing = (
            "min_sealed_worlds", "min_independent_business_dates",
            "min_effective_sample_size", "min_manifest_completeness",
            "min_multi_alternative_fraction", "min_action_overlap",
            "min_failed_or_degraded_worlds", "min_worlds_per_required_stratum",
        )
        if any(getattr(high, name) < getattr(low, name) for name in increasing):
            raise ValueError("optimizer readiness gate must be at least as strict")
        if high.max_branch_unavailable_rate > low.max_branch_unavailable_rate:
            raise ValueError("optimizer unavailable-branch gate must be stricter")
        return self


class ArchiveContract(FrozenContract):
    capacity: int = Field(ge=1)
    max_per_lineage: int = Field(ge=1)
    diversity_descriptors: tuple[str, ...]
    admission_reasons: tuple[str, ...]
    minimum_action_jaccard_distance: float = Field(ge=0.0, le=1.0)
    eviction_order: tuple[str, ...]


class BudgetContract(FrozenContract):
    max_rounds: int = Field(ge=1)
    max_nodes: int = Field(ge=1)
    max_concurrency: int = Field(ge=1)
    max_wall_seconds: int = Field(ge=1)
    max_candidate_generation_count: int = Field(ge=1)


class PilotContract(FrozenContract):
    schema_version: Literal["1"]
    pilot_id: Literal["structural-candidate-v1"]
    task_family: Literal["structural_candidate_audit"]
    lane: Literal["jczq"]
    mode: Literal["shadow_only"]
    authoritative_workflow: WorkflowBinding
    operator_grammar: tuple[OperatorSpec, ...]
    evaluator: EvaluatorContract
    readiness: ReadinessContract
    archive: ArchiveContract
    budgets: BudgetContract
    frozen_surfaces: tuple[str, ...]
    protected_actions: tuple[str, ...]


class PolicyStep(FrozenContract):
    round: int = Field(ge=1)
    action: Literal["continue_batch", "stop"]
    selector: Literal["all_template_shards", "best_audit_clean_node_per_band"]


class BaselinePolicyArtifact(FrozenContract):
    schema_version: Literal["1"]
    policy_revision_id: Literal["structural-baseline-v1"]
    family: Literal["structural_candidate_exploration"]
    interface_version: Literal["discovery-policy-v1"]
    constraints_version: Literal["structural-candidate-v1"]
    generator_family: Literal["baseline"]
    change_surfaces: tuple[Literal["exploration_policy"], ...]
    random_seed_policy: dict[str, object]
    compatible_world_families: tuple[Literal["structural_candidate_audit"], ...]
    steps: tuple[PolicyStep, ...]
    rationale: str = Field(min_length=1)


def canonical_hash(contract: FrozenContract) -> str:
    payload = contract.model_dump(mode="json")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pilot_contract(path: Path) -> PilotContract:
    return PilotContract.model_validate(_load(path))


def load_baseline_policy(path: Path) -> BaselinePolicyArtifact:
    return BaselinePolicyArtifact.model_validate(_load(path))
```

```python
# tests/discovery/__init__.py
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run pytest tests/discovery/test_contracts.py -v`

Expected: `4 passed`.

- [x] **Step 5: Commit the contract model**

```bash
git add nutmeg/discovery/__init__.py nutmeg/discovery/contracts.py tests/discovery/__init__.py tests/discovery/test_contracts.py
git commit -m "feat(discovery): define frozen pilot contracts"
```

---

### Task 2: Freeze the structural pilot and evaluator contract

**Files:**
- Create: `experiments/discovery/structural-candidate-v1.contract.json`
- Modify: `tests/discovery/test_contracts.py`

- [x] **Step 1: Add a failing repository-artifact test**

```python
# append to tests/discovery/test_contracts.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repository_pilot_contract_is_strict_and_shadow_only():
    contract = load_pilot_contract(
        ROOT / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    assert contract.mode == "shadow_only"
    assert contract.authoritative_workflow.candidate_set_kind == "judgment_bound"
    assert contract.readiness.record_to_baseline.min_sealed_worlds == 30
    assert contract.readiness.baseline_to_optimizer.min_sealed_worlds == 60
    assert "model_weights" in contract.frozen_surfaces
    assert "record_cash_transaction" in contract.protected_actions
    assert len(canonical_hash(contract)) == 64
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/discovery/test_contracts.py::test_repository_pilot_contract_is_strict_and_shadow_only -v`

Expected: FAIL with `FileNotFoundError`.

- [x] **Step 3: Add the frozen pilot artifact**

Create `experiments/discovery/structural-candidate-v1.contract.json` with exactly the `_pilot()` document from Task 1, formatted as two-space JSON with a trailing newline. Do not add comments or local paths. The frozen decisions are:

- current authority remains `enumerate_band_candidates(..., set_kind="judgment_bound")` plus its bound audit policy;
- the only continuation operators are `enumerate_template_shard` and `stop`;
- evaluator order is safety, validity, discovery quality, robustness, cost, parallel efficiency;
- baseline comparison opens at 30 sealed worlds / 20 independent dates / effective n 24;
- bounded optimization opens at 60 sealed worlds / 40 dates / effective n 48, with 0.70 action overlap, at most 0.25 unavailable branches, and at least three failed/degraded worlds;
- archive capacity is 12 with at most three policies per lineage;
- all operation remains shadow-only.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `uv run pytest tests/discovery/test_contracts.py::test_repository_pilot_contract_is_strict_and_shadow_only -v`

Expected: `1 passed`.

- [x] **Step 5: Commit the pilot contract**

```bash
git add experiments/discovery/structural-candidate-v1.contract.json tests/discovery/test_contracts.py
git commit -m "docs(discovery): freeze structural pilot contract"
```

---

### Task 3: Freeze the deterministic incumbent policy artifact

**Files:**
- Create: `experiments/discovery/structural-baseline-v1.policy.json`
- Modify: `tests/discovery/test_contracts.py`

- [x] **Step 1: Add a failing baseline-artifact test**

```python
# append to tests/discovery/test_contracts.py
def test_repository_baseline_is_deterministic_and_contract_compatible():
    pilot = load_pilot_contract(
        ROOT / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    policy = load_baseline_policy(
        ROOT / "experiments/discovery/structural-baseline-v1.policy.json"
    )
    assert policy.constraints_version == pilot.pilot_id
    assert policy.random_seed_policy == {"kind": "none", "deterministic": True}
    assert [step.action for step in policy.steps] == ["continue_batch", "stop"]
    assert len(canonical_hash(policy)) == 64
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/discovery/test_contracts.py::test_repository_baseline_is_deterministic_and_contract_compatible -v`

Expected: FAIL with `FileNotFoundError`.

- [x] **Step 3: Add the baseline policy artifact**

Create `experiments/discovery/structural-baseline-v1.policy.json` with exactly the `_policy()` document from Task 1, formatted as two-space JSON with a trailing newline. This artifact wraps current behavior without running it: round one requests every approved template shard in deterministic order, and round two stops with the best audit-clean node per odds band. It contains no model, network, Action, deployment, or funds authority.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `uv run pytest tests/discovery/test_contracts.py::test_repository_baseline_is_deterministic_and_contract_compatible -v`

Expected: `1 passed`.

- [x] **Step 5: Commit the incumbent artifact**

```bash
git add experiments/discovery/structural-baseline-v1.policy.json tests/discovery/test_contracts.py
git commit -m "docs(discovery): freeze baseline incumbent"
```

---

### Task 4: Record the as-built boundary and D0 acceptance evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md`
- Modify: `tests/discovery/test_contracts.py`

- [x] **Step 1: Add a failing evidence-contract test**

```python
# append to tests/discovery/test_contracts.py
def test_d0_evidence_names_every_retained_boundary_and_gap():
    text = (
        ROOT / "docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md"
    ).read_text(encoding="utf-8")
    for required in (
        "ActionService", "OntologyUnitOfWork", "enumerate_band_candidates",
        "Candidate Set Revision", "Historical Replay Run", "Discovery Tree",
        "No harness execution in D0", "D1 entry gate",
    ):
        assert required in text
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/discovery/test_contracts.py::test_d0_evidence_names_every_retained_boundary_and_gap -v`

Expected: FAIL with `FileNotFoundError`.

- [x] **Step 3: Write the as-built/gap matrix**

Create `docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md` with these sections and concrete entries:

```markdown
# Meta-Exploration D0 As-Built And Gap Matrix

Date: 2026-09-21
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`

## Retained foundations

| Capability | Current authority | D0 decision |
| --- | --- | --- |
| Atomic typed writes | `ActionService` + `OntologyUnitOfWork` | Reuse unchanged |
| Candidate enumeration | `nutmeg.product.operator_candidates:enumerate_band_candidates` | Baseline binding only |
| Candidate audit | candidate-set `audit_policy_version` and current deterministic audit | Freeze reference; do not fork rules |
| Business lineage | Candidate Set Revision | Reference from future DiscoveryNode; never replace |
| Workflow replay | Historical Replay Run | Keep distinct from policy replay |
| RSI governance | Experiment/Duty/Observation/Grade/Verdict/Deployment | Keep distinct from discovery tournament |

## Missing before D1

| Gap | First owning milestone |
| --- | --- |
| DiscoveryWorld / DiscoveryNode persistence | D1 |
| ExplorationPolicyRevision persistence | D1 |
| PolicyReplayRun / Tournament / Deployment persistence | D1 |
| Discovery typed Actions and permissions | D1 |
| Online shadow recorder | D2 |
| Prefix-only replay environment | D3 |
| Tournament evaluator | D4 |
| Candidate generators beyond baseline | D5 |

## Non-equivalence rules

- Candidate Set Revision is business lineage, not a Discovery Tree.
- Historical Replay Run is workflow replay, not a PolicyReplayRun.
- A policy artifact is executable intent, not deployment authority.
- Archive admission is generation eligibility, not tournament victory.

## D0 execution statement

No harness execution in D0. No `.nutmeg-data`, production candidate, RSI observation,
verdict, deployment, ticket, dispatch, funds, or public-output state was changed.

## Frozen artifacts

- `experiments/discovery/structural-candidate-v1.contract.json`
- `experiments/discovery/structural-baseline-v1.policy.json`
- Record both canonical SHA-256 values from the verification command below.

## D1 entry gate

D1 may begin only after both artifacts parse strictly, their canonical hashes are
recorded here, the complete focused test file passes, and Jun approves this evidence.
```

After the file exists, run the hash command in Step 4 and replace the single instruction line under **Frozen artifacts** with the two actual hashes. This is not a placeholder: the values are generated from the committed semantic JSON by the project loader.

- [x] **Step 4: Generate and record the canonical hashes**

Run:

```bash
uv run python -c 'from pathlib import Path; from nutmeg.discovery.contracts import canonical_hash,load_baseline_policy,load_pilot_contract; root=Path("experiments/discovery"); print("pilot", canonical_hash(load_pilot_contract(root/"structural-candidate-v1.contract.json"))); print("baseline", canonical_hash(load_baseline_policy(root/"structural-baseline-v1.policy.json")))'
```

Expected: two labels followed by distinct 64-character lowercase hexadecimal hashes. Insert those exact values into the evidence document using `apply_patch`.

- [x] **Step 5: Run the evidence test and verify GREEN**

Run: `uv run pytest tests/discovery/test_contracts.py::test_d0_evidence_names_every_retained_boundary_and_gap -v`

Expected: `1 passed`.

- [x] **Step 6: Commit D0 evidence**

```bash
git add docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md tests/discovery/test_contracts.py
git commit -m "docs(discovery): record D0 as-built boundary"
```

---

### Task 5: Run the D0 completion gate

**Files:**
- Verify only; no new files.

- [x] **Step 1: Run focused discovery tests**

Run: `uv run pytest tests/discovery/test_contracts.py -v`

Expected: all tests pass.

- [x] **Step 2: Run affected existing candidate tests**

Run: `uv run pytest tests/product/operator_v2/test_candidates.py tests/product/operator_v2/test_candidate_bands.py tests/decision/test_candidate_builder.py -q`

Expected: all tests pass; D0 has not changed candidate behavior.

- [x] **Step 3: Run lint and repository diff checks**

Run: `uv run ruff check nutmeg/discovery tests/discovery`

Expected: `All checks passed!`

Run: `git diff --check`

Expected: no output and exit code 0.

- [x] **Step 4: Prove D0 did not write runtime state**

Run: `git status --short .nutmeg-data experiments/attempts.log experiments/corpus-v2.json`

Expected: no D0-created changes. Pre-existing unrelated changes must be documented and left untouched rather than reset.

- [x] **Step 5: Record final command evidence in the D0 evidence file and commit**

Append a `## Verification` table containing command, UTC timestamp, exit code, and concise result for Steps 1-4. Then commit only the evidence file:

```bash
git add docs/superpowers/evidence/2026-09-21-meta-exploration-d0-as-built.md
git commit -m "docs(discovery): accept D0 contract lock"
```

## D0 exit gate

D0 is complete only when:

1. both JSON artifacts load with `extra="forbid"` and stable canonical hashes;
2. the baseline remains deterministic, shadow-only, and limited to exploration policy;
3. readiness and archive numbers are frozen in the pilot contract;
4. the as-built/gap matrix is complete and hash-backed;
5. all focused and affected tests pass;
6. Jun reviews D0 evidence before D1 implementation starts.

## Spec coverage self-review

| Spec section | D0 task | Result |
| --- | --- | --- |
| 4.2 current gaps | Task 4 | As-built/gap authority is explicit |
| 10.1 candidate generators | Tasks 1 and 3 | Baseline artifact and common contract inputs are frozen |
| 10.2 change surfaces | Tasks 1 and 2 | v1 mutable/frozen surfaces are machine validated |
| 10.3 reproducibility/budgets | Tasks 1-3 | seed policy, resource limits, and canonical hashes are frozen |
| 11.2 evaluator order | Task 2 | Lexicographic order is immutable in the pilot contract |
| 11.4 readiness gates | Task 2 | Both transitions have concrete numeric thresholds |
| 11.6 archive | Task 2 | capacity, lineage cap, descriptors, admission, and eviction are frozen |
| 13 structural pilot | Tasks 2 and 3 | JCZQ structural candidate/audit scope and incumbent are fixed |
| 20 D0 delivery | Tasks 1-5 | Contract lock, evidence, tests, and review gate are complete |

No D1-D7 requirement is claimed complete by this plan.
