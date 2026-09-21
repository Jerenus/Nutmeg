# Dream-RSI Meta-Exploration D1 Ontology Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the six governed discovery object families, their append-only storage, typed Actions, permissions, lineage projections, holdout exposure ledger, and read-only status view without executing the Discovery Harness.

**Architecture:** D1 follows the existing Ontology Kernel v2 pattern: pure domain models, SQLAlchemy Core schema, a repository exposed by `OntologyUnitOfWork`, and Action facades wired through the shared `ActionService`. Six object families may use normalized child/event tables, but there is one source of truth: immutable base rows plus append-only events. The CLI is read-only; online execution, prefix replay, evaluator execution, tournament computation, and policy generation remain D2-D5 work.

**Tech Stack:** Python 3.13, SQLAlchemy Core, SQLite append-only triggers, Typer, pytest. Governing inputs: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md` and the two D0 artifacts under `experiments/discovery/`.

---

## Milestone boundary

D1 may accept fully formed records through typed Actions for contract testing, but it must not:

- call `enumerate_band_candidates`, an evaluator, a model, browser, network, or external tool;
- choose a branch, synthesize a replay child, rank tournament candidates, or generate policies;
- authorize candidate selection, ticket placement, funds, public output, RSI verdicts, or production mutation;
- update a world, node, policy, replay, tournament, or deployment row in place.

## File structure

- Create `nutmeg/ontology/discovery/__init__.py` — discovery domain exports.
- Create `nutmeg/ontology/discovery/models.py` — enums, frozen rows, canonical hashes, state projections, and transition validation.
- Create `nutmeg/ontology/repository/schema_discovery.py` — normalized immutable tables for the six object families and child events.
- Create `nutmeg/ontology/repository/discovery.py` — inserts, exact hydration, counts, and read projections.
- Modify `nutmeg/ontology/repository/migrations.py` — migration 40, append-only guards, and deny-by-default permissions.
- Modify `nutmeg/ontology/repository/unit_of_work.py` — expose `uow.discovery`.
- Create `nutmeg/ontology/actions/discovery_world_actions.py` — create/start/record/fail/seal world Actions.
- Create `nutmeg/ontology/actions/discovery_policy_actions.py` — register policy and start/finish policy replay Actions.
- Create `nutmeg/ontology/actions/discovery_governance_actions.py` — tournament, archive/exposure, deployment, and brake Actions.
- Create `nutmeg/ontology/discovery/read_service.py` — operational projections only.
- Modify `nutmeg/ontology/actions/service.py` — explicitly protect discovery deployment from replay binding.
- Modify `nutmeg/ontology/wiring.py` and `nutmeg/ontology/kernel.py` — wire Action facades and counts.
- Create `nutmeg/interfaces/cli/discovery.py`; modify `nutmeg/interfaces/cli/__init__.py` — read-only `nutmeg discovery status/show`.
- Create `tests/ontology/test_discovery_models.py`.
- Create `tests/ontology/test_discovery_migration.py`.
- Create `tests/ontology/test_discovery_repository.py`.
- Create `tests/ontology/test_discovery_world_actions.py`.
- Create `tests/ontology/test_discovery_policy_actions.py`.
- Create `tests/ontology/test_discovery_governance_actions.py`.
- Create `tests/ontology/test_discovery_read_service.py`.
- Create `tests/test_cli_discovery.py`.

---

### Task 1: Define pure discovery models, hashes, and projections

**Files:**
- Create: `nutmeg/ontology/discovery/__init__.py`
- Create: `nutmeg/ontology/discovery/models.py`
- Test: `tests/ontology/test_discovery_models.py`

- [x] **Step 1: Write failing tests for enums, hashes, and state projection**

```python
# tests/ontology/test_discovery_models.py
from __future__ import annotations

import pytest

from nutmeg.ontology.discovery.models import (
    ArchiveDisposition,
    ChangeSurface,
    DeploymentDecision,
    ProvenanceMode,
    WorldEventKind,
    canonical_hash,
    project_policy_lifecycle,
    project_world_state,
    validate_change_surfaces,
)


def test_canonical_hash_ignores_key_order_but_not_values():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_world_projection_is_append_only_and_terminal():
    assert project_world_state(()) == "missing"
    assert project_world_state((WorldEventKind.CREATED,)) == "created"
    assert project_world_state((WorldEventKind.CREATED, WorldEventKind.RUN_STARTED)) == "running"
    assert project_world_state((WorldEventKind.CREATED, WorldEventKind.SEALED)) == "sealed"
    with pytest.raises(ValueError, match="terminal"):
        project_world_state((WorldEventKind.CREATED, WorldEventKind.SEALED, WorldEventKind.RUN_STARTED))


def test_v1_rejects_frozen_change_surface():
    validate_change_surfaces((ChangeSurface.EXPLORATION_POLICY,))
    validate_change_surfaces((ChangeSurface.CLOSED_OPERATOR,))
    with pytest.raises(ValueError, match="frozen"):
        validate_change_surfaces((ChangeSurface.MODEL_OR_SYSTEM,))


def test_archive_is_not_deployment_and_lifecycle_is_conservative():
    assert ArchiveDisposition.STEPPING_STONE.value == "stepping_stone"
    assert project_policy_lifecycle(registered=True, winner=False, deployment=None) == "validated"
    assert project_policy_lifecycle(
        registered=True, winner=False, deployment=None,
        archive_disposition=ArchiveDisposition.STEPPING_STONE,
    ) == "stepping_stone"
    assert project_policy_lifecycle(
        registered=True, winner=True, deployment=DeploymentDecision.SHADOW,
    ) == "shadow"
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.ontology.discovery'`.

- [x] **Step 3: Implement the pure model layer**

```python
# nutmeg/ontology/discovery/models.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.ontology.actions.models import canonical_json


class ProvenanceMode(StrEnum):
    PROSPECTIVE_ONLINE = "prospective_online"
    HISTORICAL_REPLAY_SOURCE = "historical_replay_source"


class WorldEventKind(StrEnum):
    CREATED = "created"
    RUN_STARTED = "run_started"
    SEALED = "sealed"
    QUARANTINED = "quarantined"


class ChangeSurface(StrEnum):
    EXPLORATION_POLICY = "exploration_policy"
    CLOSED_OPERATOR = "closed_workflow_operator"
    MODEL_OR_SYSTEM = "model_weights_or_executable_system"


class ArchiveDisposition(StrEnum):
    INCUMBENT = "incumbent"
    CHALLENGER = "challenger"
    STEPPING_STONE = "stepping_stone"
    REJECTED = "rejected"
    RETIRED = "retired"


class DeploymentDecision(StrEnum):
    SHADOW = "shadow"
    CANARY = "canary"
    DEPLOY = "deploy"
    HOLD = "hold"
    ROLLBACK = "rollback"
    RETIRE = "retire"


class ReplayStopReason(StrEnum):
    POLICY_STOP = "policy_stop"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_ACTION = "invalid_action"
    POLICY_CRASH = "policy_crash"
    BRANCH_UNAVAILABLE = "branch_unavailable"


def canonical_hash(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def validate_change_surfaces(values: tuple[ChangeSurface, ...]) -> None:
    if not values:
        raise ValueError("at least one change surface is required")
    if ChangeSurface.MODEL_OR_SYSTEM in values:
        raise ValueError("model/system change surface is frozen in v1")


def project_world_state(events: tuple[WorldEventKind, ...]) -> str:
    if not events:
        return "missing"
    if events[0] is not WorldEventKind.CREATED:
        raise ValueError("world history must begin with created")
    state = "created"
    for event in events[1:]:
        if state in {"sealed", "quarantined"}:
            raise ValueError("world state is terminal")
        if event is WorldEventKind.RUN_STARTED:
            state = "running"
        elif event is WorldEventKind.SEALED:
            state = "sealed"
        elif event is WorldEventKind.QUARANTINED:
            state = "quarantined"
        else:
            raise ValueError(f"invalid world transition: {event}")
    return state


def project_policy_lifecycle(
    *,
    registered: bool,
    winner: bool,
    deployment: DeploymentDecision | None,
    archive_disposition: ArchiveDisposition | None = None,
) -> str:
    if not registered:
        return "missing"
    if deployment is not None:
        return deployment.value
    if winner:
        return "tournament_winner"
    if archive_disposition is ArchiveDisposition.STEPPING_STONE:
        return "stepping_stone"
    return "validated"


@dataclass(frozen=True, slots=True)
class DiscoveryStatus:
    incumbent_policy_revision_id: str | None
    active_deployment_state: str | None
    latest_tournament_id: str | None
    latest_world_id: str | None
    sealed_world_count: int
    exposed_holdout_count: int
    rollback_policy_revision_id: str | None
```

```python
# nutmeg/ontology/discovery/__init__.py
from nutmeg.ontology.discovery.models import DiscoveryStatus

__all__ = ["DiscoveryStatus"]
```

- [x] **Step 4: Run the test and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_models.py -v`

Expected: `4 passed`.

- [x] **Step 5: Commit**

```bash
git add nutmeg/ontology/discovery/__init__.py nutmeg/ontology/discovery/models.py tests/ontology/test_discovery_models.py
git commit -m "feat(ontology): define discovery domain models"
```

---

### Task 2: Add immutable discovery schema and migration 40

**Files:**
- Create: `nutmeg/ontology/repository/schema_discovery.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_discovery_migration.py`

- [x] **Step 1: Write the failing migration tests**

```python
# tests/ontology/test_discovery_migration.py
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import inspect

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


EXPECTED_TABLES = {
    "discovery_worlds", "discovery_world_events", "discovery_runs",
    "discovery_nodes", "discovery_node_evaluations",
    "exploration_policy_revisions", "exploration_policy_parent_links",
    "policy_replay_runs", "policy_replay_rounds", "policy_replay_completions",
    "policy_tournaments", "policy_tournament_candidates", "policy_tournament_worlds",
    "policy_tournament_results", "policy_tournament_completions",
    "policy_archive_decisions", "policy_holdout_exposures",
    "policy_deployments", "policy_brake_events",
}


def test_migration_40_creates_discovery_tables_and_permissions(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version == 40
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT action_type, actor_role FROM action_permissions "
            "WHERE action_type LIKE '%discovery%' OR action_type LIKE 'register_policy%' "
            "OR action_type LIKE '%policy_replay' OR action_type LIKE '%policy_tournament' "
            "OR action_type LIKE '%policy_deployment' OR action_type='trip_policy_brake'"
        ).all()
    assert ("approve_policy_deployment", "judge_operator") in rows
    assert ("approve_policy_deployment", "deterministic_system") not in rows
    assert ("trip_policy_brake", "deterministic_system") in rows


def test_discovery_base_rows_are_append_only(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO exploration_policy_revisions "
            "(policy_revision_id,family,source_artifact_hash,interface_version,"
            "constraints_version,generator_family,generator_revision,generation_trace_hash,"
            "generator_descriptors_json,generation_input_manifest_hash,"
            "generation_budget_json,generation_cost_json,generation_timeout_seconds,"
            "rationale,change_summary,configuration_json,random_seed_policy_json,"
            "compatible_world_families_json,max_resource_permissions_json,"
            "change_surfaces_json,novelty_descriptors_json,validation_result_json,"
            "created_by,created_at,action_id) VALUES "
            "('p1','f','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            "'v1','c1','baseline','g1',NULL,'{}',"
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
            "'{}','{}',1,'r','s','{}','{}','[]','{}','[]','{}','{}',"
            "'op','2026-09-21T00:00:00+00:00','a1')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE exploration_policy_revisions SET rationale='changed' WHERE policy_revision_id='p1'"
            )
```

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_migration.py -v`

Expected: FAIL because migration 40 and discovery tables do not exist.

- [x] **Step 3: Define the normalized tables**

In `nutmeg/ontology/repository/schema_discovery.py`, declare the 19 tables named in `EXPECTED_TABLES` against shared `metadata`. Use `Text` for canonical JSON and ISO timestamps, `Integer` for ordinal/count/boolean fields, and these keys:

```python
# Use this map as an assertion against the SQLAlchemy declarations below.
TABLE_KEYS = {
    "discovery_worlds": ("world_id",),
    "discovery_world_events": ("world_event_id",),
    "discovery_runs": ("discovery_run_id",),
    "discovery_nodes": ("node_id",),
    "discovery_node_evaluations": ("node_evaluation_id",),
    "exploration_policy_revisions": ("policy_revision_id",),
    "exploration_policy_parent_links": ("policy_revision_id", "parent_index"),
    "policy_replay_runs": ("policy_replay_run_id",),
    "policy_replay_rounds": ("policy_replay_run_id", "round_no"),
    "policy_replay_completions": ("policy_replay_run_id",),
    "policy_tournaments": ("policy_tournament_id",),
    "policy_tournament_candidates": ("policy_tournament_id", "candidate_index"),
    "policy_tournament_worlds": ("policy_tournament_id", "world_index"),
    "policy_tournament_results": ("policy_tournament_id", "policy_revision_id", "world_id"),
    "policy_tournament_completions": ("policy_tournament_id",),
    "policy_archive_decisions": ("archive_decision_id",),
    "policy_holdout_exposures": ("holdout_exposure_id",),
    "policy_deployments": ("policy_deployment_id",),
    "policy_brake_events": ("policy_brake_event_id",),
}
```

The complete columns are:

```text
discovery_worlds:
  world_id, task_family, business_date, lane, strata_json,
  input_manifest_hash, input_manifest_json, pilot_contract_hash,
  legal_action_schema_json, evaluator_revision, resource_budget_json,
  cutoff_at, provenance_mode, isolated_store_identity, root_node_id,
  created_at, action_id

discovery_world_events:
  world_event_id, world_id, sequence_no, event_kind, reason,
  manifest_hash, occurred_at, action_id

discovery_runs:
  discovery_run_id, world_id, policy_revision_id, environment_mode,
  started_at, action_id

discovery_nodes:
  node_id, world_id, discovery_run_id, parent_node_id, depth, sibling_order,
  creation_sequence, continuation_action_json, policy_decision_json,
  artifact_manifest_hash, artifact_manifest_json, business_refs_json,
  execution_status, diagnostic_codes_json, started_at, finished_at,
  latency_ms, resource_cost_json, retry_of_node_id, terminal_reason,
  frontier_eligible, visibility_sequence, action_id

discovery_node_evaluations:
  node_evaluation_id, node_id, revision_no, supersedes_evaluation_id,
  evaluator_revision, result_json, selectable, evaluated_at, action_id

exploration_policy_revisions:
  policy_revision_id, family, source_artifact_hash, interface_version,
  constraints_version, generator_family, generator_revision,
  generation_trace_hash, generator_descriptors_json,
  generation_input_manifest_hash, generation_budget_json, generation_cost_json,
  generation_timeout_seconds, rationale, change_summary, configuration_json,
  random_seed_policy_json, compatible_world_families_json,
  max_resource_permissions_json, change_surfaces_json,
  novelty_descriptors_json, validation_result_json, created_by, created_at, action_id

exploration_policy_parent_links:
  policy_revision_id, parent_index, parent_policy_revision_id

policy_replay_runs:
  policy_replay_run_id, policy_revision_id, world_id, initial_observation_hash,
  evaluator_revision, cost_policy_revision, random_seed, started_at, action_id

policy_replay_rounds:
  policy_replay_run_id, round_no, observation_hash, policy_state_hash,
  requested_actions_json, accepted_actions_json, rejected_actions_json,
  revealed_node_ids_json, remaining_budget_json, decided_at

policy_replay_completions:
  policy_replay_run_id, stop_reason, budget_used_json, failure_codes_json,
  selected_node_ids_json, aggregate_outcome_json, trace_hash, finished_at, action_id

policy_tournaments:
  policy_tournament_id, policy_family, incumbent_policy_revision_id,
  candidate_set_hash, world_pool_manifest_hash, evaluator_revision,
  aggregation_revision, decision_contract_json, development_cutoff_at,
  holdout_cutoff_at, created_at, action_id

policy_tournament_candidates:
  policy_tournament_id, candidate_index, policy_revision_id,
  candidate_generator_revision, candidate_role

policy_tournament_worlds:
  policy_tournament_id, world_index, world_id, pool_role, stratum_labels_json

policy_tournament_results:
  policy_tournament_id, policy_revision_id, world_id, score_vector_json,
  disqualified, exclusion_reason, trace_hash

policy_tournament_completions:
  policy_tournament_id, winner_policy_revision_id, tie_policy_revision_ids_json,
  disqualification_reasons_json, reproduction_hash, finished_at, action_id

policy_archive_decisions:
  archive_decision_id, policy_tournament_id, policy_revision_id, disposition,
  reason_code, diversity_descriptors_json, evidence_json, decided_at, action_id

policy_holdout_exposures:
  holdout_exposure_id, policy_tournament_id, world_id, policy_family,
  exposed_at, action_id

policy_deployments:
  policy_deployment_id, policy_family, policy_revision_id, decision,
  scope_json, effective_boundary, evidence_refs_json, human_actor_id,
  acted_by, reason, supersedes_deployment_id, rollback_policy_revision_id,
  brake_conditions_json, decided_at, action_id

policy_brake_events:
  policy_brake_event_id, policy_deployment_id, tripped_policy_revision_id,
  restored_policy_revision_id, condition_code, evidence_json,
  effective_boundary, tripped_at, action_id
```

`discovery_nodes.discovery_run_id` is nullable only for the root node; every non-root
node requires a run. Foreign keys bind every child to its owning base row. Add unique
constraints for `(world_id, sequence_no)`, `(world_id, creation_sequence)`,
`(world_id, visibility_sequence)`, `(node_id, revision_no)`, and
`(policy_family, effective_boundary, action_id)`. Action handlers enforce same-world,
same-family, and temporal relationships that cannot be represented by a single foreign
key.

- [x] **Step 4: Add migration 40 and role permissions**

Import `schema_discovery` in `migrations.py`, add `_apply_discovery_foundation`, and append exactly:

```python
_DISCOVERY_PERMISSIONS = (
    ("create_discovery_world", "judge_operator"),
    ("create_discovery_world", "deterministic_system"),
    ("start_discovery_run", "deterministic_system"),
    ("record_discovery_node", "deterministic_system"),
    ("record_discovery_failure", "deterministic_system"),
    ("seal_discovery_world", "deterministic_system"),
    ("register_policy_revision", "judge_operator"),
    ("start_policy_replay", "deterministic_system"),
    ("finish_policy_replay", "deterministic_system"),
    ("create_policy_tournament", "judge_operator"),
    ("finish_policy_tournament", "deterministic_system"),
    ("approve_policy_deployment", "judge_operator"),
    ("trip_policy_brake", "deterministic_system"),
)


def _apply_discovery_foundation(connection: Connection) -> None:
    tables = (
        # Use the dependency order from schema_discovery.py: worlds/policies first,
        # then runs/nodes/replays/tournaments, then child events.
        schema_discovery.discovery_worlds,
        schema_discovery.exploration_policy_revisions,
        schema_discovery.discovery_world_events,
        schema_discovery.discovery_runs,
        schema_discovery.discovery_nodes,
        schema_discovery.discovery_node_evaluations,
        schema_discovery.exploration_policy_parent_links,
        schema_discovery.policy_replay_runs,
        schema_discovery.policy_replay_rounds,
        schema_discovery.policy_replay_completions,
        schema_discovery.policy_tournaments,
        schema_discovery.policy_tournament_candidates,
        schema_discovery.policy_tournament_worlds,
        schema_discovery.policy_tournament_results,
        schema_discovery.policy_tournament_completions,
        schema_discovery.policy_archive_decisions,
        schema_discovery.policy_holdout_exposures,
        schema_discovery.policy_deployments,
        schema_discovery.policy_brake_events,
    )
    for table in tables:
        table.create(connection)
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER {table.name}_no_{operation.lower()} "
                f"BEFORE {operation} ON {table.name} BEGIN "
                f"SELECT RAISE(ABORT, '{table.name} is append-only'); END"
            )
    connection.execute(
        insert(schema.action_permissions),
        [
            {"policy_version_id": "governance-v1", "action_type": action, "actor_role": role}
            for action, role in _DISCOVERY_PERMISSIONS
        ],
    )
```

Append `Migration(version=40, name="discovery_foundation", fingerprint="discovery_six_families+append_only_events+holdout_exposure+role_separated_permissions", apply=_apply_discovery_foundation)` after version 39. Never edit fingerprints 1-39.

- [x] **Step 5: Run migration tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_migration.py tests/ontology/test_migrations.py -v`

Expected: all tests pass and schema high-water mark is 40.

- [x] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_discovery.py nutmeg/ontology/repository/migrations.py tests/ontology/test_discovery_migration.py
git commit -m "feat(ontology): add discovery foundation schema"
```

---

### Task 3: Add repository hydration and operational projections

**Files:**
- Create: `nutmeg/ontology/repository/discovery.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Test: `tests/ontology/test_discovery_repository.py`

- [x] **Step 1: Write failing repository round-trip tests**

```python
# tests/ontology/test_discovery_repository.py
from __future__ import annotations

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import WorldRow, WorldEventRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_world_round_trip_and_projected_state(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    world = WorldRow(
        world_id="world-1", task_family="structural_candidate_audit",
        business_date="2026-09-21", lane="jczq", strata={"board_size": "small"},
        input_manifest_hash="a" * 64, input_manifest={"task_snapshot_hash": "b" * 64},
        pilot_contract_hash="c" * 64, legal_action_schema={"operators": ["stop"]},
        evaluator_revision="structural-candidate-evaluator-v1",
        resource_budget={"max_nodes": 32}, cutoff_at="2026-09-21T07:00:00+00:00",
        provenance_mode="prospective_online", isolated_store_identity="shadow:test",
        root_node_id="node-root", created_at="2026-09-21T07:01:00+00:00", action_id="a1",
    )
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(world)
        uow.discovery.insert_world_event(WorldEventRow(
            world_event_id="we-1", world_id="world-1", sequence_no=1,
            event_kind="created", reason="world_created", manifest_hash="a" * 64,
            occurred_at="2026-09-21T07:01:00+00:00", action_id="a1",
        ))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world("world-1") == world
        assert uow.discovery.world_state("world-1") == "created"
        assert uow.discovery.count_sealed_worlds("structural_candidate_audit") == 0
```

Add the following exact repository cases to the same file:

| Test | Insert | Assertions |
| --- | --- | --- |
| `test_node_and_superseding_evaluation_round_trip` | root, child, evaluation revisions 1 and 2 | nodes sort by creation sequence; latest evaluation is revision 2; revision 1 still exists |
| `test_multi_parent_policy_lineage_is_ordered` | child policy with parent indexes 0 and 1 | `policy_parents(child)` returns both IDs in index order |
| `test_policy_replay_rounds_and_completion_round_trip` | replay envelope, rounds 1 and 2, completion | rounds are contiguous and completion trace hash is unchanged |
| `test_tournament_graph_round_trip` | tournament, incumbent/challenger, development/holdout worlds, matrix results, completion | all child rows hydrate in declared index order and winner is distinct from archive decisions |
| `test_archive_and_holdout_exposure_round_trip` | stepping-stone decision and one holdout exposure | both are queryable without changing policy/tournament base rows |
| `test_deployment_and_brake_round_trip` | deployed event with fallback, then brake event | latest deployment remains durable and latest brake names the same fallback |
| `test_duplicate_ordinals_are_rejected` | duplicate world sequence, node visibility, replay round, and candidate index | each insert raises `IntegrityError`; original row is unchanged |

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_repository.py -v`

Expected: FAIL because `repository.discovery` does not exist.

- [x] **Step 3: Implement frozen repository row types**

In `nutmeg/ontology/repository/discovery.py`, create frozen slot dataclasses named:

```python
WorldRow
WorldEventRow
DiscoveryRunRow
NodeRow
NodeEvaluationRow
PolicyRevisionRow
PolicyParentLinkRow
PolicyReplayRunRow
PolicyReplayRoundRow
PolicyReplayCompletionRow
TournamentRow
TournamentCandidateRow
TournamentWorldRow
TournamentResultRow
TournamentCompletionRow
ArchiveDecisionRow
HoldoutExposureRow
PolicyDeploymentRow
PolicyBrakeEventRow
```

Fields must match Task 2 columns, with decoded JSON represented as `dict`, `list`, or `tuple`, boolean integers hydrated as `bool`, and no repository-generated defaults.

- [x] **Step 4: Implement explicit inserts and reads**

Implement one `insert_<record>` method per row type. Add these exact reads:

| Method | Return and ordering |
| --- | --- |
| `world(world_id)` | `WorldRow | None` |
| `world_events(world_id)` | tuple ordered by sequence then event ID |
| `world_state(world_id)` | `project_world_state` over ordered event kinds |
| `run(discovery_run_id)` | `DiscoveryRunRow | None` |
| `node(node_id)` | `NodeRow | None` |
| `nodes_for_world(world_id)` | tuple ordered by creation sequence then node ID |
| `latest_node_evaluation(node_id)` | highest revision then evaluation ID |
| `policy(policy_revision_id)` | `PolicyRevisionRow | None` |
| `policy_parents(policy_revision_id)` | parent IDs ordered by parent index |
| `policy_replay(policy_replay_run_id)` | replay envelope or `None` |
| `policy_replay_rounds(policy_replay_run_id)` | rounds ordered by round number |
| `policy_replay_completion(policy_replay_run_id)` | completion or `None` |
| `tournament(policy_tournament_id)` | tournament or `None` |
| `tournament_candidates(policy_tournament_id)` | candidates ordered by candidate index |
| `tournament_worlds(policy_tournament_id)` | worlds ordered by world index |
| `tournament_completion(policy_tournament_id)` | completion or `None` |
| `latest_archive_decision(policy_revision_id)` | latest decision by time then ID |
| `exposed_holdouts(policy_family)` | exposures ordered by time then ID |
| `latest_deployment(policy_family)` | latest human decision by time then ID |
| `latest_brake(policy_deployment_id)` | latest brake by time then ID |
| `count_sealed_worlds(task_family)` | count of worlds whose final event is `sealed` |
| `counts()` | six base-family counts keyed by kernel status field name |

Use `canonical_json` for every JSON column and `json.loads` on hydration. Ordering is always explicit: event sequence, node creation sequence, parent index, replay round, tournament candidate/world index, then stable ID as final tie-break. `world_state` must call `project_world_state`; do not store a status column.

- [x] **Step 5: Expose the repository on the Unit of Work**

Add the TYPE_CHECKING import and property:

```python
@property
def discovery(self) -> DiscoveryRepository:
    from nutmeg.ontology.repository.discovery import DiscoveryRepository

    return DiscoveryRepository(self.connection)
```

- [x] **Step 6: Run repository tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_repository.py -v`

Expected: all repository cases pass.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/ontology/repository/discovery.py nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_discovery_repository.py
git commit -m "feat(ontology): persist discovery object families"
```

---

### Task 4: Add world, run, node, failure, and seal Actions

**Files:**
- Create: `nutmeg/ontology/actions/discovery_world_actions.py`
- Test: `tests/ontology/test_discovery_world_actions.py`

- [x] **Step 1: Write failing Action tests**

Create a `_rig(tmp_path)` fixture using `run_migrations`, `ActionService`, and
`DiscoveryWorldActions`, then implement this exact matrix:

| Test | Action | Required assertion |
| --- | --- | --- |
| `test_create_world_atomically_writes_root_and_created_event` | valid operator create | world, root, created event, Action, and outbox commit together |
| `test_create_world_rejects_manifest_hash_mismatch` | change one manifest value after hashing | raises hash mismatch; zero world/root rows |
| `test_start_run_requires_registered_compatible_policy` | start with missing policy, then wrong family | both fail; no run/event rows |
| `test_record_node_requires_visible_parent_same_world_and_cutoff_safe_refs` | submit foreign parent and post-cutoff reference | both fail atomically |
| `test_record_failure_charges_cost_and_has_no_selectable_evaluation` | record timeout with cost/diagnostics | failed node persists; no evaluation; cost remains non-zero |
| `test_retry_is_new_node_and_preserves_failed_node` | retry failed node | two node IDs remain; retry link points backward |
| `test_seal_requires_terminal_run_complete_lineage_and_matching_manifest` | omit cost, then use wrong seal hash | both fail; corrected request seals once |
| `test_sealed_world_rejects_new_nodes` | record after seal | fails with terminal-world error |
| `test_ai_analyst_cannot_create_or_mutate_world` | each world Action as `AI_ANALYST` | returns rejected outcome and writes no business rows |

Use D0 artifact hashes loaded through `nutmeg.discovery.contracts`. Assert every committed Action has both business refs and an outbox event.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_world_actions.py -v`

Expected: FAIL because `DiscoveryWorldActions` does not exist.

- [x] **Step 3: Define immutable request DTOs**

In `discovery_world_actions.py`, add frozen slot dataclasses:

```python
CreateDiscoveryWorldRequest
StartDiscoveryRunRequest
RecordDiscoveryNodeRequest
RecordDiscoveryFailureRequest
SealDiscoveryWorldRequest
```

Every request includes `actor_id`, `actor_role`, `idempotency_key`, and timezone-aware `requested_at`. Create-world includes the full world manifest plus a root-node manifest. Record-node includes parent/run/policy decision, artifact and cost payloads, optional evaluator result, and exact visibility/creation ordinals. Seal includes `world_id`, `terminal_reason`, and `sealed_manifest_hash`.

- [x] **Step 4: Implement the five Action handlers**

Use these exact action names and invariants:

```text
create_discovery_world:
  canonical_hash(input_manifest) == input_manifest_hash
  provenance_mode is prospective_online or historical_replay_source
  D0 pilot hash and evaluator revision match request
  atomically insert world, root node, created event

start_discovery_run:
  world state == created
  policy exists, validation_result.valid is true, family is compatible
  insert discovery_run + run_started event

record_discovery_node:
  world state == running
  run belongs to world and policy decision names only a legal operator
  parent exists in same world and creation/visibility ordinals are next
  referenced evidence cutoff <= world cutoff
  insert node and optional revision-1 evaluation atomically

record_discovery_failure:
  same lineage checks as record node
  execution_status == failed, frontier_eligible == false
  resource cost and diagnostic codes are required
  no selectable evaluation is inserted

seal_discovery_world:
  world state == running
  at least one terminal/selectable node or explicit no-solution terminal exists
  every non-root node has parent/action/artifact/diagnostic/cost lineage
  recomputed sealed manifest hash matches request
  insert sealed event; never update world/node rows
```

All handlers execute with `acquire_write_lock=True` for ordinal/state transitions.
Create returns refs for `discovery_world` and its root `discovery_node`; start returns
`discovery_run`; record/failure return `discovery_node` plus `node_evaluation` only
when one was inserted; seal returns `discovery_world_event`.

- [x] **Step 5: Run Action tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_world_actions.py tests/ontology/test_action_outbox.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/discovery_world_actions.py tests/ontology/test_discovery_world_actions.py
git commit -m "feat(ontology): govern discovery world actions"
```

---

### Task 5: Add policy registration and policy replay record Actions

**Files:**
- Create: `nutmeg/ontology/actions/discovery_policy_actions.py`
- Modify: `nutmeg/ontology/actions/service.py`
- Test: `tests/ontology/test_discovery_policy_actions.py`

- [x] **Step 1: Write failing policy and replay tests**

Implement this exact test matrix:

| Test | Required assertion |
| --- | --- |
| `test_register_policy_requires_operator_and_artifact_hash_match` | system role is rejected; wrong source hash rolls back; operator + exact hash commits |
| `test_register_policy_preserves_all_ordered_parents` | two parents hydrate in supplied index order |
| `test_register_policy_rejects_model_system_change_surface` | frozen class is rejected before any policy row |
| `test_start_replay_requires_sealed_world_and_valid_policy` | running/quarantined worlds and invalid policies are rejected |
| `test_finish_replay_persists_ordered_prefix_trace_and_hash` | rounds and one completion commit atomically with exact trace hash |
| `test_finish_replay_rejects_hidden_or_non_child_reveal` | grandchild-before-parent fails and leaves zero rounds/completion |
| `test_replay_cannot_mutate_source_world_or_call_protected_action` | source row counts/hashes are unchanged and protected Action raises permission denial |
| `test_replay_completion_is_single_assignment` | second completion fails; first remains unchanged |

The hidden-child test must create a sealed tree `root -> a -> a1` and `root -> b`, then submit a round revealing `a1` before `a`; expect `ValueError("unrevealed parent")` and zero completion rows.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_policy_actions.py -v`

Expected: FAIL because `DiscoveryPolicyActions` does not exist.

- [x] **Step 3: Define request DTOs and handlers**

Create frozen requests `RegisterPolicyRevisionRequest`, `StartPolicyReplayRequest`, and `FinishPolicyReplayRequest`. Use exact Action names `register_policy_revision`, `start_policy_replay`, and `finish_policy_replay`.

Registration validates the policy artifact with `load_baseline_policy` for D0 baseline artifacts or a generic strict mapping for later families; verifies source hash, complete parent existence, allowed change surfaces, compatible family, declared permissions, and validation result; then inserts the policy plus all parent links atomically.

Replay start validates sealed source world, evaluator match, no exposed hidden-node list in the initial observation, and creates only the replay envelope. Replay finish accepts all rounds at once, then performs this deterministic prefix check before any insert:

```python
visible = {world.root_node_id}
for expected_round, item in enumerate(request.rounds, start=1):
    if item.round_no != expected_round:
        raise ValueError("replay rounds must be contiguous")
    for node_id in item.revealed_node_ids:
        node = nodes[node_id]
        if node.parent_node_id not in visible:
            raise ValueError("replay revealed a node with an unrevealed parent")
        if node_id in visible:
            raise ValueError("replay revealed a node twice")
    visible.update(item.revealed_node_ids)
trace_document = {
    "policy_revision_id": request.policy_revision_id,
    "world_id": request.world_id,
    "rounds": [item.to_document() for item in request.rounds],
    "stop_reason": request.stop_reason,
    "selected_node_ids": list(request.selected_node_ids),
}
if canonical_hash(trace_document) != request.trace_hash:
    raise ValueError("policy replay trace hash mismatch")
```

After validation, atomically insert rounds and one completion row. No code path calls online adapters or alters world/node rows.

- [x] **Step 4: Add discovery deployment to replay-protected Actions**

Extend `_REPLAY_PROTECTED_ACTIONS` in `actions/service.py` with:

```python
"approve_policy_deployment",
"trip_policy_brake",
```

This is defense in depth; migration permissions still deny `replay_adjudicator` for both.

- [x] **Step 5: Run tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_policy_actions.py tests/ontology/test_replay_actions.py tests/ontology/test_action_service.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/discovery_policy_actions.py nutmeg/ontology/actions/service.py tests/ontology/test_discovery_policy_actions.py
git commit -m "feat(ontology): govern discovery policies and replay traces"
```

---

### Task 6: Add tournament, archive, exposure, deployment, and brake Actions

**Files:**
- Create: `nutmeg/ontology/actions/discovery_governance_actions.py`
- Test: `tests/ontology/test_discovery_governance_actions.py`

- [x] **Step 1: Write failing governance tests**

Implement this exact test matrix:

| Test | Required assertion |
| --- | --- |
| `test_create_tournament_requires_incumbent_in_frozen_candidates` | missing or duplicated incumbent is rejected before child rows |
| `test_create_tournament_rejects_unsealed_or_duplicate_worlds` | both inputs fail atomically |
| `test_create_tournament_rejects_exposed_world_as_hidden_holdout` | exposure ledger blocks reuse for the same family |
| `test_finish_tournament_requires_complete_policy_world_matrix_or_exclusions` | missing matrix cell fails unless it has machine-readable exclusion |
| `test_finish_tournament_separates_winner_from_archive_admission` | incumbent can win while challenger becomes stepping stone; states remain distinct |
| `test_disqualified_policy_cannot_enter_archive` | archive insert is rejected and completion does not partially commit |
| `test_only_operator_can_approve_shadow_canary_deploy_hold_rollback_retire` | all six system requests are permission-rejected |
| `test_replay_winner_without_fresh_shadow_can_only_receive_shadow_decision` | shadow commits; canary/deploy fail |
| `test_only_one_deployed_incumbent_exists_per_family_scope` | second active deployment fails until explicit superseding decision |
| `test_deterministic_brake_only_restores_recorded_approved_fallback` | alternate fallback fails; recorded fallback commits |
| `test_braked_policy_cannot_resume_without_new_human_action` | deterministic resume fails; operator superseding event commits |

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_governance_actions.py -v`

Expected: FAIL because `DiscoveryGovernanceActions` does not exist.

- [x] **Step 3: Implement tournament creation and completion**

Define `CreatePolicyTournamentRequest` and `FinishPolicyTournamentRequest`. Creation uses `acquire_write_lock=True` and validates:

- incumbent is present exactly once with role `incumbent`;
- candidate and world manifests hash to the supplied values;
- every world is sealed, unique, and labeled `development` or `holdout`;
- every holdout is strictly later than the development cutoff;
- no `(policy_family, world_id)` already in the exposure ledger is hidden holdout;
- evaluator, aggregation, tie rule, archive rule, and minimum materiality are frozen in `decision_contract`.

Completion validates a result or explicit exclusion for every candidate/world pair, applies no ranking logic of its own, and verifies the caller-supplied winner against the frozen lexicographic result document hash. It then atomically inserts results, completion, archive decisions, and one exposure row per holdout. Archive validation rejects disqualified/invalid/irreproducible candidates, capacity overflow, per-lineage overflow, and winner mislabeling.

D1 treats `finish_policy_tournament` as a governed persistence boundary, not as proof
that ranking was computed correctly. It additionally requires the winner to be a
registered, non-disqualified candidate. Its `reproduction_hash` stores the hash of the
frozen selection-proof document (candidate/world manifests, matrix, exclusions, and
declared winner); the D1 schema has no separate `selection_proof_hash` column. D4 owns
the deterministic aggregation implementation that checks the proof and ranking before
this Action is used operationally.

- [x] **Step 4: Implement human deployment and deterministic brake**

Define `ApprovePolicyDeploymentRequest` and `TripPolicyBrakeRequest` with exact Actions `approve_policy_deployment` and `trip_policy_brake`.

Deployment checks:

```text
shadow: policy is latest tournament winner; fresh shadow may be absent
canary/deploy: fresh prospective shadow worlds exist and are not development worlds
deploy: no other deployed incumbent exists for same family+scope at boundary
hold/rollback/retire: operator only, reason required
resume after brake: represented by a new operator deployment event, never by deleting brake
all decisions: ticket/dispatch/funds/public-output permissions remain absent
```

Brake checks that the named deployment is active, the condition code is in its frozen brake contract, and `restored_policy_revision_id` equals its recorded rollback target. It inserts one brake event; it cannot choose another policy, expand scope, or resume the tripped policy.

- [x] **Step 5: Run governance tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_governance_actions.py tests/ontology/test_permissions.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/actions/discovery_governance_actions.py tests/ontology/test_discovery_governance_actions.py
git commit -m "feat(ontology): govern discovery tournament deployment"
```

---

### Task 7: Wire the kernel and expose read-only projections

**Files:**
- Create: `nutmeg/ontology/discovery/read_service.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/ontology/kernel.py`
- Test: `tests/ontology/test_discovery_read_service.py`
- Modify: `tests/ontology/test_kernel.py`

- [x] **Step 1: Write failing wiring and projection tests**

Implement this exact test matrix:

| Test | Required assertion |
| --- | --- |
| `test_kernel_exposes_three_discovery_action_facades_and_counts` | all three facades exist; fresh counts are zero; inserted fixture increments only its family |
| `test_status_projection_returns_incumbent_tournament_world_and_rollback` | one query returns exact incumbent, deployment, tournament, latest world, sealed/exposure counts, and fallback |
| `test_world_detail_orders_nodes_by_visibility_and_never_exposes_hidden_children` | output order matches visibility sequence and contains only durable rows |
| `test_policy_lineage_reports_generator_parents_archive_and_deployment_separately` | four fields remain distinct and archive never implies winner/deployment |

The empty-kernel case must return zeros and `None`, not create rows or infer an incumbent.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_discovery_read_service.py tests/ontology/test_kernel.py -v`

Expected: FAIL because the discovery facades/read service are not wired.

- [x] **Step 3: Implement `DiscoveryReadService`**

Expose only read methods: `status(policy_family) -> DiscoveryStatus`,
`world_detail(world_id) -> dict[str, object]`,
`policy_lineage(policy_revision_id) -> dict[str, object]`, and
`tournament_detail(policy_tournament_id) -> dict[str, object]`. The constructor accepts
one SQLAlchemy `Engine` and stores it as `_engine`.

`status` reports the latest human-approved incumbent, latest tournament basis, latest world, sealed count, exposure count, and rollback target. `world_detail` returns only durable stored nodes ordered by visibility; it does not calculate legal actions or reveal any node not already in that world. `policy_lineage` keeps generator parents, archive disposition, tournament winner status, and deployment state as separate fields.

- [x] **Step 4: Wire facades and kernel counts**

In `wiring.py`, instantiate and inject:

```python
discovery_world_actions = DiscoveryWorldActions(action_service)
discovery_policy_actions = DiscoveryPolicyActions(action_service)
discovery_governance_actions = DiscoveryGovernanceActions(action_service)
discovery_read = DiscoveryReadService(engine)
```

Add matching constructor fields/properties to `OntologyKernel`. Extend `OntologyKernelStatus` and `to_dict()` with:

```text
discovery_world_count
discovery_node_count
exploration_policy_revision_count
policy_replay_run_count
policy_tournament_count
policy_deployment_count
```

When migration 40 is absent, all six counts are zero. When present, populate them from `DiscoveryRepository.counts()`.

- [x] **Step 5: Run tests and verify GREEN**

Run: `uv run pytest tests/ontology/test_discovery_read_service.py tests/ontology/test_kernel.py tests/ontology/test_kernel_e2e.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/discovery/read_service.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py tests/ontology/test_discovery_read_service.py tests/ontology/test_kernel.py
git commit -m "feat(ontology): expose discovery projections"
```

---

### Task 8: Add a read-only discovery CLI and end-to-end foundation test

**Files:**
- Create: `nutmeg/interfaces/cli/discovery.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Test: `tests/test_cli_discovery.py`

- [x] **Step 1: Write failing CLI tests**

```python
# tests/test_cli_discovery.py
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_discovery_status_is_read_only_and_empty_on_fresh_store(tmp_path):
    result = runner.invoke(app, ["discovery", "status", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "incumbent: none" in result.output
    assert "sealed worlds: 0" in result.output


def test_discovery_show_unknown_object_fails_without_mutation(tmp_path):
    result = runner.invoke(
        app, ["discovery", "show", "--kind", "world", "--id", "missing", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "not found" in result.output
```

Add an end-to-end test that initializes a temporary kernel, registers the D0 baseline policy through the operator Action, creates one shadow world through the deterministic Action, and verifies `discovery status` displays it. Do not invoke generation, replay, tournament ranking, or deployment.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_cli_discovery.py -v`

Expected: FAIL because the `discovery` command group does not exist.

- [x] **Step 3: Implement the read-only command group**

```python
# nutmeg/interfaces/cli/discovery.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import typer
from sqlalchemy import create_engine

import nutmeg.interfaces.cli as _cli
from nutmeg.ontology.discovery.models import DiscoveryStatus
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.paths import OntologyPaths

discovery_app = typer.Typer(help="Discovery Harness governed state (read-only in D1)")
_cli.app.add_typer(discovery_app, name="discovery")
DATA_DIR_OPTION = typer.Option(Path(".nutmeg-data"), "--data-dir")


def _service(data_dir: Path) -> DiscoveryReadService | None:
    database = OntologyPaths.from_data_dir(data_dir.resolve()).database
    if not database.is_file():
        return None
    uri = f"file:{quote(str(database), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        try:
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        except sqlite3.OperationalError:
            version = None
    if version is None or version < 40:
        typer.echo("discovery error: ontology schema 40 is required", err=True)
        raise typer.Exit(code=1)
    return DiscoveryReadService(create_engine(
        "sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True)
    ))


@discovery_app.command("status")
def status(
    policy_family: str = typer.Option("structural_candidate_exploration", "--family"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    service = _service(data_dir)
    state = (service.status(policy_family) if service is not None else
             DiscoveryStatus(None, None, None, None, 0, 0, None))
    typer.echo(f"incumbent: {state.incumbent_policy_revision_id or 'none'}")
    typer.echo(f"deployment: {state.active_deployment_state or 'none'}")
    typer.echo(f"latest tournament: {state.latest_tournament_id or 'none'}")
    typer.echo(f"latest world: {state.latest_world_id or 'none'}")
    typer.echo(f"sealed worlds: {state.sealed_world_count}")
    typer.echo(f"exposed holdouts: {state.exposed_holdout_count}")
    typer.echo(f"rollback: {state.rollback_policy_revision_id or 'none'}")


@discovery_app.command("show")
def show(
    kind: str = typer.Option(..., "--kind"),
    object_id: str = typer.Option(..., "--id"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    service = _service(data_dir)
    readers = {
        "world": service.world_detail,
        "policy": service.policy_lineage,
        "tournament": service.tournament_detail,
    }
    if kind not in readers:
        typer.echo("discovery error: kind must be world, policy, or tournament")
        raise typer.Exit(code=1)
    if service is None:
        typer.echo(f"discovery error: {kind} {object_id} not found")
        raise typer.Exit(code=1)
    try:
        payload = readers[kind](object_id)
    except KeyError:
        typer.echo(f"discovery error: {kind} {object_id} not found")
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
```

Import the module at the bottom of `nutmeg/interfaces/cli/__init__.py`:

```python
from nutmeg.interfaces.cli import discovery as discovery  # noqa: E402
```

No mutating CLI command is added in D1; tests and later harness code call typed facades directly.

- [x] **Step 4: Run CLI tests and verify GREEN**

Run: `uv run pytest tests/test_cli_discovery.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli/discovery.py nutmeg/interfaces/cli/__init__.py tests/test_cli_discovery.py
git commit -m "feat(cli): expose discovery foundation status"
```

---

### Task 9: Run the D1 completion and non-regression gate

**Files:**
- Verify only; create no production state.

- [ ] **Step 1: Run the complete discovery suite**

Run:

```bash
uv run pytest \
  tests/discovery/test_contracts.py \
  tests/ontology/test_discovery_models.py \
  tests/ontology/test_discovery_migration.py \
  tests/ontology/test_discovery_repository.py \
  tests/ontology/test_discovery_world_actions.py \
  tests/ontology/test_discovery_policy_actions.py \
  tests/ontology/test_discovery_governance_actions.py \
  tests/ontology/test_discovery_read_service.py \
  tests/test_cli_discovery.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run shared Ontology regression tests**

Run:

```bash
uv run pytest \
  tests/ontology/test_migrations.py \
  tests/ontology/test_action_models.py \
  tests/ontology/test_action_service.py \
  tests/ontology/test_action_outbox.py \
  tests/ontology/test_permissions.py \
  tests/ontology/test_replay_actions.py \
  tests/ontology/test_kernel.py \
  tests/ontology/test_kernel_e2e.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run protected business-flow regressions**

Run:

```bash
uv run pytest \
  tests/product/operator_v2/test_candidates.py \
  tests/product/operator_v2/test_candidate_bands.py \
  tests/product/operator_v2/test_candidate_replay.py \
  tests/ontology/test_protected_ticket_actions.py \
  tests/ontology/test_rsi_actions.py -q
```

Expected: all tests pass, proving D1 did not change candidate, ticket, or RSI behavior.

- [ ] **Step 4: Run lint and formatting checks**

Run:

```bash
uv run ruff check \
  nutmeg/discovery \
  nutmeg/ontology/discovery \
  nutmeg/ontology/repository/schema_discovery.py \
  nutmeg/ontology/repository/discovery.py \
  nutmeg/ontology/actions/discovery_world_actions.py \
  nutmeg/ontology/actions/discovery_policy_actions.py \
  nutmeg/ontology/actions/discovery_governance_actions.py \
  nutmeg/interfaces/cli/discovery.py \
  tests/discovery \
  tests/ontology/test_discovery_*.py \
  tests/test_cli_discovery.py
```

Expected: `All checks passed!`

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 5: Prove no harness or production mutation occurred**

Run: `git status --short .nutmeg-data experiments/attempts.log experiments/corpus-v2.json`

Expected: no D1-created changes. Preserve and report any pre-existing unrelated worktree changes.

- [ ] **Step 6: Commit final D1 verification evidence**

Create `docs/superpowers/evidence/2026-09-21-meta-exploration-d1-foundation.md` containing:

- migration 40 table/permission inventory;
- D0 pilot and baseline canonical hashes;
- test commands, timestamps, exit codes, and pass counts;
- explicit statement that no harness execution or production write occurred;
- remaining D2-D7 gaps.

Then commit only that file:

```bash
git add docs/superpowers/evidence/2026-09-21-meta-exploration-d1-foundation.md
git commit -m "docs(discovery): accept D1 ontology foundation"
```

## D1 exit gate

D1 is complete only when:

1. migration 40 creates all normalized tables and deny-by-default permissions;
2. every formal write passes through `ActionService` and emits outbox lineage;
3. all base rows and events are append-only;
4. world, node, policy, replay, tournament, archive, exposure, deployment, and brake invariants pass tests;
5. only a human can register policies, create tournaments, or approve deployment decisions;
6. the deterministic brake can only reduce authority and restore the recorded fallback;
7. the status CLI is read-only and reconstructs state from durable facts;
8. shared Ontology, candidate, replay, ticket, and RSI regressions pass;
9. Jun reviews D1 evidence before D2 online recorder planning or implementation begins.

## Spec coverage self-review

| Spec requirement | D1 task | D1 guarantee |
| --- | --- | --- |
| FR-001 / FR-002 | Tasks 2-4 | frozen world and complete immutable node lineage |
| FR-004 / FR-005 foundation | Tasks 2, 3, 5 | sealed-tree prefix trace storage and no source mutation; replay runtime remains D3 |
| FR-006 foundation | Tasks 2, 3, 6 | incumbent/candidate/world/evaluator/tie manifests freeze before results; ranking engine remains D4 |
| FR-008 | Tasks 2, 5, 6 | policy replay has no path to prospective RSI/business mutation |
| FR-010 / FR-015 | Tasks 2 and 6 | human deployment authority and reduce-only deterministic brake |
| FR-011 / FR-017 | Tasks 1, 2, 5 | declared permissions and frozen change-surface rejection |
| FR-013 / FR-014 | Tasks 2-7 | failures, retries, unavailable branches, lineage, and reproduction hashes are durable |
| FR-016 | Tasks 2, 3, 5 | generator revision, parents, seed policy, budgets, trace, and cost persist |
| FR-019 / FR-020 | Tasks 2, 3, 6 | winner and bounded archive decisions remain separate |
| FR-021 | Tasks 2, 3, 6 | holdout exposure ledger blocks hidden reuse |
| D1 delivery sequence | Tasks 1-9 | six families, Actions, permissions, projections, manifests; no harness execution |

FR-003 online/replay environment parity belongs to D2-D3. FR-007 tournament scoring
belongs to D4. FR-009 prospective promotion belongs to D6. FR-012 shadow recording
belongs to D2. FR-018/FR-022 readiness-triggered optimizer operation belongs to D2,
D4, D5, and D7. This D1 plan stores their required contracts but does not claim their
runtime behavior.
