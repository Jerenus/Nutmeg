# Nutmeg Intelligence OS M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the versioned headless product contract that makes Ontology Kernel v2 the only runtime authority for future Nutmeg application workspaces.

**Architecture:** Add typed workflow objects and a transactional outbox to the existing SQLite kernel, then place a `nutmeg.product` application boundary above the kernel. FastAPI exposes versioned query, Action, health, lineage, and durable event endpoints; it never reads `DecisionStore`, daily JSONL, or raw client-side probability logic.

**Tech Stack:** Python 3.12, frozen dataclasses, Pydantic v2, SQLAlchemy 2 Core, SQLite WAL, FastAPI, SSE, Typer, pytest, ruff.

---

## Scope and file structure

M1 is deliberately headless. It delivers the contract consumed by M2-M6, not the
visual workspaces themselves.

### New kernel files

- `nutmeg/ontology/repository/schema_workflow.py`: workflow-domain and outbox tables.
- `nutmeg/ontology/repository/workflow.py`: typed persistence for workflow objects.
- `nutmeg/ontology/repository/outbox.py`: durable event append/read repository.
- `nutmeg/ontology/workflow/__init__.py`: public workflow exports.
- `nutmeg/ontology/workflow/models.py`: enums, row/request value objects, ID minting.
- `nutmeg/ontology/actions/workflow_actions.py`: typed workflow Action handlers.

### New product files

- `nutmeg/product/__init__.py`: stable product-layer exports.
- `nutmeg/product/contracts.py`: versioned Pydantic response/request contracts.
- `nutmeg/product/readiness.py`: pure READY/DEGRADED/BLOCKED policy.
- `nutmeg/product/repository.py`: read-only SQL queries over the ontology.
- `nutmeg/product/queries.py`: DTO assembly and `as_of` enforcement.
- `nutmeg/product/actions.py`: whitelisted product Action dispatcher.
- `nutmeg/product/wiring.py`: settings-to-product service composition.
- `nutmeg/interfaces/product_api.py`: FastAPI app, local session, CSRF, routes, SSE.
- `nutmeg/interfaces/cli/product.py`: `nutmeg app` local server command.

### New tests

- `tests/product/__init__.py`
- `tests/product/conftest.py`
- `tests/product/test_readiness.py`
- `tests/product/test_queries.py`
- `tests/product/test_actions.py`
- `tests/product/test_api.py`
- `tests/product/test_m1_e2e.py`
- `tests/ontology/test_workflow_migration.py`
- `tests/ontology/test_workflow_actions.py`
- `tests/ontology/test_action_outbox.py`

### Existing files modified

- `nutmeg/ontology/repository/migrations.py`: migration 10 and permissions.
- `nutmeg/ontology/repository/unit_of_work.py`: workflow/outbox repository accessors.
- `nutmeg/ontology/actions/service.py`: append terminal outbox events atomically.
- `nutmeg/ontology/actions/forecast_actions.py`: persist information cutoff.
- `nutmeg/ontology/decision/read_flow.py`: accept server-selected snapshot/evidence and caller idempotency.
- `nutmeg/ontology/kernel.py`: expose workflow/outbox counts in health.
- `nutmeg/ontology/wiring.py`: compose workflow Actions.
- `nutmeg/interfaces/cli/__init__.py`: register the product command module.
- `README.md`: document the M1 headless API and safety boundary.

## Task 1: Workflow and outbox schema migration

**Files:**
- Create: `nutmeg/ontology/repository/schema_workflow.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Create: `tests/ontology/test_workflow_migration.py`

- [x] **Step 1: Write the failing migration test**

```python
from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations


def test_migration_10_adds_workflow_outbox_and_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    report = run_migrations(engine)
    assert report.applied_versions[-1] == 10
    assert {
        "adjudications", "flag_instances", "predictions", "precedent_links",
        "agent_proposals", "outbox_events",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        permissions = {
            (row.action_type, row.actor_role)
            for row in connection.execute(select(schema.action_permissions))
        }
    assert ("record_adjudication", "judge_operator") in permissions
    assert ("create_agent_proposal", "ai_analyst") in permissions
    assert ("resolve_agent_proposal", "judge_operator") in permissions
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_workflow_migration.py -q`  
Expected: FAIL because migration 10 and the six tables do not exist.

- [x] **Step 3: Declare the workflow tables**

Create `schema_workflow.py` with six explicit tables on the shared metadata:

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, Table, Text, UniqueConstraint

from nutmeg.ontology.repository.schema import metadata

adjudications = Table(
    "adjudications", metadata,
    Column("adjudication_id", Text, primary_key=True),
    Column("subject_type", Text, nullable=False, index=True),
    Column("subject_id", Text, nullable=False, index=True),
    Column("decision", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("evidence_rejected_json", Text, nullable=False),
    Column("alternative_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("supersedes_adjudication_id", Text, nullable=True),
)

flag_instances = Table(
    "flag_instances", metadata,
    Column("flag_instance_id", Text, primary_key=True),
    Column("flag_type", Text, nullable=False, index=True),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"),
           nullable=False, index=True),
    Column("direction", Text, nullable=True),
    Column("strength", Float, nullable=False),
    Column("evidence_refs_json", Text, nullable=False),
    Column("predicted_face", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

predictions = Table(
    "predictions", metadata,
    Column("prediction_id", Text, primary_key=True),
    Column("match_id", Text, ForeignKey("matches.match_id", ondelete="RESTRICT"),
           nullable=False, index=True),
    Column("claim", Text, nullable=False),
    Column("falsifier", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("outcome", Text, nullable=True),
    Column("registered_at", Text, nullable=False),
    Column("settled_at", Text, nullable=True),
)

precedent_links = Table(
    "precedent_links", metadata,
    Column("precedent_link_id", Text, primary_key=True),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("precedent_match_id", Text,
           ForeignKey("matches.match_id", ondelete="RESTRICT"), nullable=False),
    Column("scope", Text, nullable=False),
    Column("evidence_refs_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

agent_proposals = Table(
    "agent_proposals", metadata,
    Column("agent_proposal_id", Text, primary_key=True),
    Column("subject_type", Text, nullable=False, index=True),
    Column("subject_id", Text, nullable=False, index=True),
    Column("proposal_type", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("citation_refs_json", Text, nullable=False),
    Column("model_name", Text, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("resolved_at", Text, nullable=True),
    Column("resolved_by_action_id", Text, nullable=True),
)

outbox_events = Table(
    "outbox_events", metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("action_id", Text, ForeignKey("actions.action_id", ondelete="RESTRICT"),
           nullable=False, index=True),
    Column("topic", Text, nullable=False, index=True),
    Column("object_type", Text, nullable=True),
    Column("object_id", Text, nullable=True),
    Column("payload_json", Text, nullable=False),
    Column("occurred_at", Text, nullable=False),
    UniqueConstraint("action_id", "topic", name="uq_outbox_action_topic"),
)
```

- [x] **Step 4: Add migration 10 and exact permissions**

Import `schema_workflow`, create the tables in FK order, and seed:

```python
_WORKFLOW_ACTION_PERMISSIONS = (
    ("record_adjudication", "judge_operator"),
    ("record_flag_instance", "judge_operator"),
    ("record_flag_instance", "deterministic_system"),
    ("register_prediction", "ai_analyst"),
    ("register_prediction", "judge_operator"),
    ("link_precedent", "judge_operator"),
    ("link_precedent", "deterministic_system"),
    ("create_agent_proposal", "ai_analyst"),
    ("create_agent_proposal", "judge_operator"),
    ("resolve_agent_proposal", "judge_operator"),
)


def _apply_product_workflow(connection: Connection) -> None:
    for table in (
        schema_workflow.adjudications,
        schema_workflow.flag_instances,
        schema_workflow.predictions,
        schema_workflow.precedent_links,
        schema_workflow.agent_proposals,
        schema_workflow.outbox_events,
    ):
        table.create(connection)
    connection.execute(insert(schema.action_permissions), [
        {"policy_version_id": "governance-v1", "action_type": action_type,
         "actor_role": actor_role}
        for action_type, actor_role in _WORKFLOW_ACTION_PERMISSIONS
    ])
```

Append migration 10 with fingerprint
`adjudications+flags+predictions+precedents+agent_proposals+outbox+workflow_permissions`.

- [x] **Step 5: Run focused migration tests**

Run: `uv run pytest tests/ontology/test_workflow_migration.py tests/ontology/test_migrations.py -q`  
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_workflow.py \
  nutmeg/ontology/repository/migrations.py tests/ontology/test_workflow_migration.py
git commit -m "feat(ontology): add product workflow schema"
```

## Task 2: Workflow repositories and typed Actions

**Files:**
- Create: `nutmeg/ontology/workflow/__init__.py`
- Create: `nutmeg/ontology/workflow/models.py`
- Create: `nutmeg/ontology/repository/workflow.py`
- Create: `nutmeg/ontology/actions/workflow_actions.py`
- Modify: `nutmeg/ontology/errors.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Create: `tests/ontology/test_workflow_actions.py`

- [x] **Step 1: Write permission and persistence tests**

Test all six transitions explicitly:

```python
def test_ai_proposal_is_not_an_adjudication(workflow, engine):
    proposal = workflow.create_agent_proposal(_proposal(role=ActorRole.AI_ANALYST))
    assert proposal.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_agent_proposal(proposal.result_refs[0].object_id)
        assert row.status == "pending"
        assert uow.workflow.count_adjudications() == 0


def test_ai_cannot_record_operator_adjudication(workflow):
    outcome = workflow.record_adjudication(_adjudication(role=ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED


def test_operator_resolves_proposal_without_mutating_payload(workflow, engine):
    created = workflow.create_agent_proposal(_proposal(role=ActorRole.AI_ANALYST))
    proposal_id = created.result_refs[0].object_id
    resolved = workflow.resolve_agent_proposal(_resolve(proposal_id))
    assert resolved.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_agent_proposal(proposal_id)
        assert row.status == "approved"
        assert row.version == 2
        assert row.payload == {"belief": {"home": 0.52, "draw": 0.28, "away": 0.2}}


def test_stale_proposal_resolution_is_rejected(workflow):
    created = workflow.create_agent_proposal(_proposal(role=ActorRole.AI_ANALYST))
    proposal_id = created.result_refs[0].object_id
    workflow.resolve_agent_proposal(_resolve(proposal_id, expected_version=1))
    with pytest.raises(OptimisticConcurrencyError):
        workflow.resolve_agent_proposal(_resolve(proposal_id, expected_version=1,
                                                  key="proposal:resolve:stale"))
```

Also assert `record_flag_instance`, `register_prediction`, and `link_precedent`
persist their typed rows and reject roles not present in migration 10.

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_workflow_actions.py -q`  
Expected: collection FAIL because workflow modules do not exist.

- [x] **Step 3: Add immutable workflow value objects**

Use frozen dataclasses and explicit enums in `workflow/models.py`:

```python
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class PredictionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    VOID = "void"


def mint_workflow_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class AgentProposalRow:
    agent_proposal_id: str
    subject_type: str
    subject_id: str
    proposal_type: str
    payload: dict[str, object]
    citation_refs: list[dict[str, str]]
    model_name: str
    model_version: str
    status: ProposalStatus
    version: int
    created_at: str
    resolved_at: str | None
    resolved_by_action_id: str | None
```

Define matching frozen rows for `AdjudicationRow`, `FlagInstanceRow`,
`PredictionRow`, and `PrecedentLinkRow`. Define request dataclasses in
`workflow_actions.py`; each includes actor, role, idempotency key, and timezone-aware
`requested_at`.

- [x] **Step 4: Implement the workflow repository**

`WorkflowRepository` must expose explicit insert/get methods, JSON through
`canonical_json`, proposal resolution as an update, and counts. The proposal update is:

```python
def resolve_agent_proposal(
    self, proposal_id: str, status: ProposalStatus, expected_version: int,
    at: str, action_id: str
) -> None:
    result = self._connection.execute(
        update(sw.agent_proposals)
        .where(sw.agent_proposals.c.agent_proposal_id == proposal_id,
               sw.agent_proposals.c.status == ProposalStatus.PENDING.value,
               sw.agent_proposals.c.version == expected_version)
        .values(status=status.value, version=expected_version + 1,
                resolved_at=at, resolved_by_action_id=action_id)
    )
    if result.rowcount != 1:
        raise OptimisticConcurrencyError(
            f"proposal {proposal_id} is absent, resolved, or not at version {expected_version}"
        )
```

Add `OntologyUnitOfWork.workflow` returning this repository.

- [x] **Step 5: Implement typed workflow Actions**

`WorkflowActions` receives the existing `ActionService`. Every public method builds an
`ActionCommand`, writes exactly one workflow object in its handler, and returns an
`ObjectRef` with one of `adjudication`, `flag_instance`, `prediction`,
`precedent_link`, or `agent_proposal`.

For example, the adjudication handler is:

```python
def record_adjudication(self, request: RecordAdjudicationRequest) -> ActionOutcome:
    command = ActionCommand.create(
        action_type="record_adjudication", actor_id=request.actor_id,
        actor_role=request.actor_role, idempotency_key=request.idempotency_key,
        payload={"subject_type": request.subject_type, "subject_id": request.subject_id,
                 "decision": request.decision}, requested_at=request.requested_at,
    )

    def handler(uow, _command):
        adjudication_id = mint_workflow_id("adj")
        uow.workflow.insert_adjudication(AdjudicationRow(
            adjudication_id=adjudication_id, subject_type=request.subject_type,
            subject_id=request.subject_id, decision=request.decision,
            actor_id=request.actor_id, reason=request.reason,
            evidence_rejected=list(request.evidence_rejected),
            alternative=dict(request.alternative),
            created_at=request.requested_at.astimezone(UTC).isoformat(),
            supersedes_adjudication_id=request.supersedes_adjudication_id,
        ))
        return (ObjectRef("adjudication", adjudication_id),)

    return self._action_service.execute(command, handler)
```

Implement the other five methods with the same explicit request-to-row mapping. Proposal
resolution accepts only `approved`, `rejected`, or `withdrawn`, and places
`{"agent_proposal:<id>": expected_version}` in `ActionCommand.expected_versions`.
Add `OptimisticConcurrencyError` to `nutmeg/ontology/errors.py`.

- [x] **Step 6: Wire the workflow facade into the kernel**

Construct one `WorkflowActions(action_service)` in `build_ontology_kernel`, pass it to
`OntologyKernel`, and expose it as `kernel.workflow`.

- [x] **Step 7: Run focused tests**

Run: `uv run pytest tests/ontology/test_workflow_actions.py tests/ontology/test_permissions.py -q`  
Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add nutmeg/ontology/workflow nutmeg/ontology/repository/workflow.py \
  nutmeg/ontology/actions/workflow_actions.py nutmeg/ontology/repository/unit_of_work.py \
  nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py nutmeg/ontology/errors.py \
  tests/ontology/test_workflow_actions.py
git commit -m "feat(ontology): add governed workflow actions"
```

## Task 3: Transactional outbox and durable cursor

**Files:**
- Create: `nutmeg/ontology/repository/outbox.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/actions/service.py`
- Modify: `nutmeg/ontology/kernel.py`
- Create: `tests/ontology/test_action_outbox.py`

- [x] **Step 1: Write atomicity and replay tests**

```python
def test_committed_action_and_event_share_transaction(service, engine):
    outcome = service.execute(_command(), lambda _uow, _command: (ObjectRef("probe", "1"),))
    with OntologyUnitOfWork(engine) as uow:
        events = uow.outbox.after(0, limit=10)
    assert [(event.action_id, event.topic) for event in events] == [
        (outcome.action_id, "action.committed")
    ]


def test_handler_failure_has_only_failed_terminal_event(service, engine):
    with pytest.raises(RuntimeError):
        service.execute(_command("failure"), lambda _uow, _command: (_ for _ in ()).throw(
            RuntimeError("boom")
        ))
    with OntologyUnitOfWork(engine) as uow:
        events = uow.outbox.after(0, limit=10)
    assert [event.topic for event in events] == ["action.failed"]


def test_outbox_cursor_resumes_without_duplication(service, engine):
    service.execute(_command("one"), lambda _uow, _command: ())
    service.execute(_command("two"), lambda _uow, _command: ())
    with OntologyUnitOfWork(engine) as uow:
        first = uow.outbox.after(0, limit=1)
        second = uow.outbox.after(first[0].sequence, limit=10)
    assert len(first) == 1 and len(second) == 1
    assert second[0].sequence > first[0].sequence
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_action_outbox.py -q`  
Expected: FAIL because `OntologyUnitOfWork.outbox` is missing.

- [x] **Step 3: Implement the outbox repository**

Define `OutboxEventRow` and methods:

```python
def append_for_action(
    self, command: ActionCommand, status: ActionStatus,
    result_refs: tuple[ObjectRef, ...], occurred_at: str,
) -> None:
    primary = result_refs[0] if result_refs else None
    self._connection.execute(insert(sw.outbox_events).values(
        event_id=f"evt-{uuid4().hex}", action_id=command.action_id,
        topic=f"action.{status.value}",
        object_type=primary.object_type if primary else None,
        object_id=primary.object_id if primary else None,
        payload_json=canonical_json({
            "action_type": command.action_type,
            "status": status.value,
            "result_refs": [ref.to_dict() for ref in result_refs],
        }), occurred_at=occurred_at,
    ))


def after(self, sequence: int, *, limit: int) -> list[OutboxEventRow]:
    rows = self._connection.execute(
        select(sw.outbox_events)
        .where(sw.outbox_events.c.sequence > sequence)
        .order_by(sw.outbox_events.c.sequence)
        .limit(limit)
    ).mappings().all()
    return [self._to_row(row) for row in rows]
```

Add `count()` and `latest_sequence()` and expose the repository as `uow.outbox`.

- [x] **Step 4: Append events inside Action transactions**

After `mark_committed`, call `uow.outbox.append_for_action` before the UoW exits. In
`_audit_terminal`, insert the rejected/failed Action and its event in the same UoW.
Never put the Action payload in the event; only action type, status, and result refs are
safe product metadata.

- [x] **Step 5: Expose outbox counts in kernel status**

Add `outbox_event_count` and `outbox_latest_sequence` to `OntologyKernelStatus`,
`to_dict`, empty status, and live status.

- [x] **Step 6: Run Action and kernel regression tests**

Run: `uv run pytest tests/ontology/test_action_outbox.py tests/ontology/test_action_service.py tests/ontology/test_kernel.py tests/ontology/test_kernel_e2e.py -q`  
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add nutmeg/ontology/repository/outbox.py nutmeg/ontology/repository/unit_of_work.py \
  nutmeg/ontology/actions/service.py nutmeg/ontology/kernel.py \
  tests/ontology/test_action_outbox.py
git commit -m "feat(ontology): publish actions through transactional outbox"
```

## Task 4: Product contracts and readiness policy

**Files:**
- Create: `nutmeg/product/__init__.py`
- Create: `nutmeg/product/contracts.py`
- Create: `nutmeg/product/readiness.py`
- Create: `tests/product/__init__.py`
- Create: `tests/product/test_readiness.py`

- [x] **Step 1: Write pure readiness tests**

```python
def test_unresolved_identity_blocks_next_action():
    state = evaluate_readiness(identity_resolved=False, snapshot_at=None,
                               as_of=_at(), evidence_count=4)
    assert state.level is ReadinessLevel.BLOCKED
    assert [issue.code for issue in state.issues] == ["identity_unresolved"]


def test_no_evidence_is_degraded_but_not_hidden():
    state = evaluate_readiness(identity_resolved=True, snapshot_at=_at(),
                               as_of=_at(), evidence_count=0)
    assert state.level is ReadinessLevel.DEGRADED
    assert state.issues[0].code == "evidence_empty"


def test_absent_market_anchor_blocks_forecast():
    state = evaluate_readiness(identity_resolved=True, snapshot_at=None,
                               as_of=_at(), evidence_count=2)
    assert state.level is ReadinessLevel.BLOCKED
    assert any(issue.code == "market_anchor_missing" for issue in state.issues)
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/product/test_readiness.py -q`  
Expected: collection FAIL because `nutmeg.product` does not exist.

- [x] **Step 3: Define versioned contracts**

Use Pydantic `BaseModel` with `extra="forbid"`. Define:

```python
class ReadinessLevel(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class ReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    object_ref: ObjectRefContract | None = None
    observed_at: datetime | None = None


class ReadinessState(BaseModel):
    level: ReadinessLevel
    issues: list[ReadinessIssue] = Field(default_factory=list)


class ProductError(BaseModel):
    code: str
    message: str
    action_id: str | None = None
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    retryable: bool = False
    current_version: int | None = None
    details: dict[str, object] = Field(default_factory=dict)
```

Also define `MatchSummary`, `BoardResponse`, `EvidenceSummary`, `ForecastSummary`,
`MatchDetail`, `LineageResponse`, `ActionView`, `OutboxEventView`, `HealthResponse`,
`ProductActionRequest`, and `ProductActionResponse`. Every top-level response includes
`schema_version: Literal["1"]`.

- [x] **Step 4: Implement deterministic readiness precedence**

`evaluate_readiness` collects all issues, then sets BLOCKED if any hard issue exists,
otherwise DEGRADED if any issue exists. Hard codes are `identity_unresolved` and
`market_anchor_missing`. `evidence_empty` and `market_anchor_stale` are degraded.
Stale means older than six hours at `as_of`.

- [x] **Step 5: Run focused tests**

Run: `uv run pytest tests/product/test_readiness.py -q`  
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add nutmeg/product tests/product/__init__.py tests/product/test_readiness.py
git commit -m "feat(product): define v1 contracts and readiness policy"
```

## Task 5: Read-only product repository and Query Service

**Files:**
- Create: `nutmeg/product/repository.py`
- Create: `nutmeg/product/queries.py`
- Create: `tests/product/conftest.py`
- Create: `tests/product/test_queries.py`

- [x] **Step 1: Add a deterministic product fixture**

`tests/product/conftest.py` builds a temp kernel, applies migrations, and records two
teams, one resolved match revision, home/away appearances, one read-time HAD snapshot,
one Observation, one provisional Claim, and one legacy Forecast with no bundle. Return
the kernel and fixed clock `2026-08-24T10:00:00Z`.

- [x] **Step 2: Write query behavior tests**

```python
def test_board_returns_named_match_and_explicit_readiness(product_services):
    board = product_services.queries.board(date(2026, 8, 24), as_of=_clock())
    assert board.matches[0].home_team == "Home FC"
    assert board.matches[0].away_team == "Away FC"
    assert board.matches[0].readiness.level is ReadinessLevel.READY


def test_match_as_of_excludes_future_observation(product_services, seed_future_observation):
    detail = product_services.queries.match("match-1", as_of=_clock())
    assert {item.observation_id for item in detail.evidence.observations} == {"obs-before"}


def test_legacy_forecast_is_never_presented_as_bundled(product_services):
    detail = product_services.queries.match("match-1", as_of=_clock())
    assert detail.forecasts[0].evidence_status == "legacy_unbundled"


def test_lineage_and_action_queries_are_stable(product_services):
    lineage = product_services.queries.lineage("forecast_revision", "fr-legacy")
    assert any(edge.relation == "forecast_for_match" for edge in lineage.edges)
    assert product_services.queries.actions(limit=20).items
```

- [x] **Step 3: Run the test and verify RED**

Run: `uv run pytest tests/product/test_queries.py -q`  
Expected: FAIL because product query modules do not exist.

- [x] **Step 4: Implement read-only repository queries**

`ProductReadRepository` receives the ontology `Engine` and opens short read connections.
Implement explicit SQLAlchemy Core selects for:

- current/latest-at-cutoff match revision and appearances/team names;
- latest market snapshot at or before cutoff;
- Claims where `created_at <= as_of` and Observations where `recorded_at <= as_of`;
- Forecast revisions where `made_at <= as_of` with bundle presence;
- Action audit rows with stable cursor/order;
- workflow objects linked to a match;
- outbox events after a sequence;
- object lineage for Match, EvidenceBundle, ForecastRevision, Ticket, Settlement, and
  workflow objects.

The snapshot lookup must be server-authoritative:

```python
def latest_snapshot(self, match_id: str, market_id: str, as_of: str):
    with self._engine.connect() as connection:
        return connection.execute(
            select(sm.market_snapshots)
            .where(sm.market_snapshots.c.match_id == match_id,
                   sm.market_snapshots.c.market_definition_id == market_id,
                   sm.market_snapshots.c.as_of <= as_of)
            .order_by(sm.market_snapshots.c.as_of.desc()).limit(1)
        ).mappings().first()
```

Do not accept a client-supplied prior distribution in this repository.

- [x] **Step 5: Assemble DTOs in Query Service**

`ProductQueryService` converts repository records into Pydantic contracts, applies
`evaluate_readiness`, labels a Forecast `bundled` only when `evidence_bundle_id` is
non-null, and raises `ProductNotFoundError` for absent objects.

`board()` uses the Asia/Shanghai business-day interval and an explicit `as_of`; it does
not infer the system clock inside repository code.

- [x] **Step 6: Run query tests**

Run: `uv run pytest tests/product/test_queries.py tests/product/test_readiness.py -q`  
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add nutmeg/product/repository.py nutmeg/product/queries.py \
  tests/product/conftest.py tests/product/test_queries.py
git commit -m "feat(product): add temporal query service"
```

## Task 6: Whitelisted Product Action Gateway

**Files:**
- Create: `nutmeg/product/actions.py`
- Modify: `nutmeg/ontology/actions/forecast_actions.py`
- Modify: `nutmeg/ontology/decision/read_flow.py`
- Create: `tests/product/test_actions.py`

- [x] **Step 1: Write gateway safety tests**

```python
def test_forecast_commit_uses_server_snapshot_not_client_prior(product_services):
    response = product_services.actions.execute(_request(
        "commit_forecast", {"match_id": "match-1", "market_definition_id": "md-had",
        "cutoff_at": "2026-08-24T10:00:00+00:00",
        "belief_distribution": {"home": 0.52, "draw": 0.28, "away": 0.2},
        "factors": [], "commitment_tier": "judged", "falsifier": "lineup changes"}
    ))
    assert response.status == "committed"
    assert response.result_refs[0].object_type == "forecast_revision"


def test_unknown_action_is_rejected_before_kernel_write(product_services):
    with pytest.raises(ProductActionNotAllowedError):
        product_services.actions.execute(_request("raw_sql", {"sql": "drop table matches"}))


def test_ai_actor_cannot_be_spoofed_by_payload(product_services):
    request = _request("record_adjudication", {"actor_role": "judge_operator",
                                                "subject_type": "claim",
                                                "subject_id": "c1",
                                                "decision": "approve",
                                                "reason": "x",
                                                "evidence_rejected": [],
                                                "alternative": {}})
    response = product_services.actions.execute(request, actor_role=ActorRole.AI_ANALYST)
    assert response.status == "rejected"


def test_stale_forecast_version_is_a_conflict(product_services):
    first = _request("commit_forecast", _forecast_payload(),
                     expected_versions={"forecast:match-1:md-had": 0})
    product_services.actions.execute(first)
    stale = _request("commit_forecast", _forecast_payload(), key="forecast:stale",
                     expected_versions={"forecast:match-1:md-had": 0})
    with pytest.raises(OptimisticConcurrencyError):
        product_services.actions.execute(stale)
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/product/test_actions.py -q`  
Expected: FAIL because the gateway does not exist.

- [x] **Step 3: Persist the Forecast information cutoff**

Add optional `information_cutoff_at` and `expected_current_revision_no` to draft/commit
requests and write the cutoff in `_revision_row` rather than hard-coding `None`.
`ForecastActions._commit` compares the current revision number (`0` when absent) to the
expected value before writing, raises `OptimisticConcurrencyError` on mismatch, and
places the semantic forecast version key in `ActionCommand.expected_versions`.

Extend `ReadMatchRequest` with defaults:

```python
prior_snapshot_id: str | None = None
candidate_observation_ids: list[str] = field(default_factory=list)
caveat_claim_ids: list[str] = field(default_factory=list)
falsifier: str | None = None
idempotency_key: str | None = None
expected_current_revision_no: int | None = None
```

The read flow uses the caller key as the idempotency root, passes the selected snapshot,
evidence IDs, falsifier, and cutoff into bundle/forecast Actions, and returns the
Forecast Action ID in `ReadMatchResult`.

- [x] **Step 4: Implement the explicit Action dispatcher**

`ProductActionGateway.execute(request, actor_id="owner", actor_role=JUDGE_OPERATOR)`
accepts only:

- `commit_forecast`;
- `record_adjudication`;
- `record_flag_instance`;
- `register_prediction`;
- `link_precedent`;
- `create_agent_proposal`;
- `resolve_agent_proposal`.

For `commit_forecast`, ignore any `prior_distribution` in payload, load the latest
snapshot and eligible evidence at/before cutoff from `ProductReadRepository`, block if
readiness is BLOCKED, convert factor payloads to `FactorInput`, and call
`kernel.decision_read.read_match`. Pass
`request.expected_versions["forecast:<match_id>:<market_id>"]` as the expected current
revision number; reject the request if that key is absent.

For workflow Actions, construct the exact typed request and pass only the server actor.
Map `ActionOutcome` to `ProductActionResponse`; a rejected outcome stays a normal
response with `status="rejected"` for the HTTP layer to map.

- [x] **Step 5: Run gateway and decision regressions**

Run: `uv run pytest tests/product/test_actions.py tests/ontology/test_decision_read_flow.py tests/ontology/test_commit_forecast.py -q`  
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add nutmeg/product/actions.py nutmeg/ontology/actions/forecast_actions.py \
  nutmeg/ontology/decision/read_flow.py tests/product/test_actions.py
git commit -m "feat(product): add governed action gateway"
```

## Task 7: FastAPI, local session, stable errors, and SSE

**Files:**
- Create: `nutmeg/interfaces/product_api.py`
- Create: `tests/product/test_api.py`

- [ ] **Step 1: Write API contract and security tests**

```python
def _session(client):
    response = client.get("/api/v1/session")
    return {"X-CSRF-Token": response.json()["csrf_token"],
            "Origin": "http://testserver"}


def test_query_routes_publish_v1_contract(client):
    assert client.get("/api/v1/system/health").json()["schema_version"] == "1"
    assert client.get("/api/v1/board?date=2026-08-24").status_code == 200
    assert client.get("/api/v1/matches/match-1").status_code == 200


def test_mutation_requires_session_csrf_and_same_origin(client):
    payload = _action_payload()
    assert client.post("/api/v1/actions", json=payload).status_code == 403
    headers = _session(client)
    assert client.post("/api/v1/actions", json=payload,
                       headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/actions", json=payload, headers=headers).status_code == 200


def test_error_envelope_is_stable(client):
    response = client.get("/api/v1/matches/absent")
    assert response.status_code == 404
    assert response.json() == {
        "code": "object_not_found", "message": "match absent not found",
        "action_id": None, "field_errors": {}, "retryable": False,
        "current_version": None, "details": {},
    }


def test_events_resume_after_cursor(client, committed_event):
    first = client.get("/api/v1/events?after=0&limit=1").json()
    second = client.get(f"/api/v1/events?after={first['next_cursor']}&limit=20").json()
    assert all(event["sequence"] > first["next_cursor"] for event in second["items"])
```

Also test `GET /api/v1/events/stream?after=0&once=true` returns `text/event-stream`
with `id:`, `event:`, and JSON `data:` lines.

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/product/test_api.py -q`  
Expected: collection FAIL because `create_product_app` does not exist.

- [ ] **Step 3: Implement local session protection**

`create_product_app(services, session_secret=None, csrf_secret=None)` stores random
`secrets.token_urlsafe(32)` values when not injected. `GET /api/v1/session` sets an
HttpOnly, SameSite=strict `nutmeg_session` cookie and returns only the CSRF token.

The mutation dependency validates cookie, `X-CSRF-Token`, and Origin host. Payload
actor fields are ignored because the server always assigns `settings.default_user_id`
and `JUDGE_OPERATOR`.

- [ ] **Step 4: Implement query and Action routes**

Add the six design endpoints plus `/api/v1/session` and `/api/v1/events/stream`.
Register exception handlers for `ProductNotFoundError`,
`ProductActionNotAllowedError`, `IdempotencyConflictError`, `ValueError`, and
unexpected errors. Unexpected errors include a generated correlation ID and never
return stack traces.

For a rejected `ProductActionResponse`, return 403 with the standard envelope and the
Action ID; committed responses return 200.

- [ ] **Step 5: Implement durable SSE encoding**

The SSE generator reads `services.queries.events(after, limit=100)`, emits:

```text
id: <sequence>
event: <topic>
data: <canonical JSON payload>

```

When `once=true`, emit the current batch and close for deterministic tests. Otherwise
poll every 0.5 seconds and emit a comment heartbeat after 15 seconds of inactivity.

- [ ] **Step 6: Run API tests**

Run: `uv run pytest tests/product/test_api.py -q`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/interfaces/product_api.py tests/product/test_api.py
git commit -m "feat(api): expose secured product v1 contract"
```

## Task 8: Product wiring and `nutmeg app` command

**Files:**
- Create: `nutmeg/product/wiring.py`
- Modify: `nutmeg/product/__init__.py`
- Create: `nutmeg/interfaces/cli/product.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Modify: `README.md`
- Create: `tests/product/test_cli.py`

- [ ] **Step 1: Write wiring and CLI tests**

```python
def test_product_services_refuse_uninitialized_kernel(tmp_path):
    with pytest.raises(ProductNotReadyError, match="ontology is not initialized"):
        build_product_services(AppSettings(data_dir=tmp_path / "data"))


def test_app_command_binds_loopback_by_default(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(product_cli._cli, "get_settings",
                        lambda: AppSettings(data_dir=tmp_path / "data"))
    build_ontology_kernel(product_cli._cli.get_settings()).initialize()
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: captured.update(
        {"app": app, "host": host, "port": port}))
    result = CliRunner().invoke(app, ["app"])
    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8788
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/product/test_cli.py -q`  
Expected: FAIL because product wiring/command do not exist.

- [ ] **Step 3: Compose product services**

Define:

```python
@dataclass(frozen=True, slots=True)
class ProductServices:
    kernel: OntologyKernel
    queries: ProductQueryService
    actions: ProductActionGateway
    settings: AppSettings


def build_product_services(settings: AppSettings) -> ProductServices:
    kernel = build_ontology_kernel(settings)
    status = kernel.status()
    if not status.initialized or status.integrity_check != "ok" or status.pending_migrations:
        raise ProductNotReadyError("ontology is not initialized and current")
    repository = ProductReadRepository(kernel.engine)
    return ProductServices(
        kernel=kernel,
        queries=ProductQueryService(repository, kernel),
        actions=ProductActionGateway(kernel, repository),
        settings=settings,
    )
```

- [ ] **Step 4: Register `nutmeg app`**

The command uses `build_product_services`, `create_product_app`, warns on non-loopback
host with the existing `_warn_if_exposed` behavior, and calls Uvicorn on port 8788 by
default. Import the module in the CLI registration block.

- [ ] **Step 5: Document M1**

README must state:

- initialize with `uv run nutmeg ontology init`;
- launch with `uv run nutmeg app`;
- M1 is API-only and M2 supplies the command/operations UI;
- API mutations are Action-gated and no autonomous funds action exists;
- `decision-web` remains legacy and is not a product data source.

- [ ] **Step 6: Run CLI tests**

Run: `uv run pytest tests/product/test_cli.py tests/ontology/test_cli.py -q`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/product/wiring.py nutmeg/product/__init__.py \
  nutmeg/interfaces/cli/product.py nutmeg/interfaces/cli/__init__.py README.md \
  tests/product/test_cli.py
git commit -m "feat(product): wire local Nutmeg application service"
```

## Task 9: Golden-day M1 end-to-end contract

**Files:**
- Create: `tests/product/test_m1_e2e.py`
- Modify: `tests/product/conftest.py`
- Modify: `nutmeg/product/queries.py`
- Modify: `nutmeg/product/actions.py`

- [ ] **Step 1: Write the complete golden-day test**

```python
def test_m1_golden_day_from_board_to_forecast_and_lineage(client):
    board = client.get("/api/v1/board?date=2026-08-24").json()
    match = board["matches"][0]
    assert match["readiness"]["level"] == "ready"

    detail = client.get(f"/api/v1/matches/{match['match_id']}?as_of=2026-08-24T10:00:00Z").json()
    assert detail["evidence"]["observations"]
    assert all(item["recorded_at"] <= "2026-08-24T10:00:00+00:00"
               for item in detail["evidence"]["observations"])

    session = client.get("/api/v1/session")
    headers = {"X-CSRF-Token": session.json()["csrf_token"],
               "Origin": "http://testserver"}
    committed = client.post("/api/v1/actions", headers=headers, json={
        "action_type": "commit_forecast", "idempotency_key": "golden:forecast:1",
        "payload": {"match_id": match["match_id"],
                    "market_definition_id": "md-had",
                    "cutoff_at": "2026-08-24T10:00:00+00:00",
                    "belief_distribution": {"home": 0.52, "draw": 0.28, "away": 0.2},
                    "factors": [], "commitment_tier": "judged",
                    "falsifier": "official lineup contradicts availability"},
        "expected_versions": {},
    })
    assert committed.status_code == 200
    revision_id = committed.json()["result_refs"][0]["object_id"]

    lineage = client.get(f"/api/v1/lineage/forecast_revision/{revision_id}").json()
    assert {edge["relation"] for edge in lineage["edges"]} >= {
        "forecast_for_match", "forecast_uses_bundle"
    }
    events = client.get("/api/v1/events?after=0&limit=100").json()
    assert any(item["object_id"] == revision_id for item in events["items"])
```

- [ ] **Step 2: Add restart/idempotency assertions**

Rebuild `ProductServices` against the same temp `data_dir`, repeat the exact Action,
and assert the same Forecast revision/Action IDs and no extra committed revision. Then
resume events from the prior cursor and assert only later events are returned.

- [ ] **Step 3: Add architecture boundary assertion**

Use `inspect.getsource` on every module under `nutmeg.product` and
`nutmeg.interfaces.product_api`; assert none contains imports from
`nutmeg.decision.store` or `nutmeg.decision.workbench`.

- [ ] **Step 4: Run the M1 end-to-end tests**

Run: `uv run pytest tests/product/test_m1_e2e.py -q`  
Expected: PASS.

- [ ] **Step 5: Run all M1 tests and fix only observed failures**

Run: `uv run pytest tests/product tests/ontology -q`  
Expected: PASS. If an existing ontology test fails, preserve the existing public API
unless the approved M1 contract explicitly changes it.

- [ ] **Step 6: Commit**

```bash
git add tests/product/test_m1_e2e.py tests/product/conftest.py \
  nutmeg/product/queries.py nutmeg/product/actions.py
git commit -m "test(product): prove M1 golden-day contract"
```

## Task 10: M1 quality and verification gate

**Files:**
- Modify: `.pre-commit-config.yaml`
- Modify: `docs/ontology-kernel-operations.md`
- Modify: `docs/superpowers/plans/2026-08-24-nutmeg-intelligence-os-m1.md`

- [ ] **Step 1: Run formatting and static checks**

Run:

```bash
uv run ruff check nutmeg/ontology nutmeg/product nutmeg/interfaces/product_api.py \
  nutmeg/interfaces/cli/product.py tests/ontology tests/product
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 2: Run the fresh focused test gate**

Run:

```bash
uv run pytest tests/product tests/ontology -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run decision-adapter regressions**

Run:

```bash
uv run pytest tests/decision/test_ontology_adapter.py \
  tests/decision/test_close_settle_adapter.py \
  tests/decision/test_read_adapter.py \
  tests/decision/test_zucai_e2e.py -q
```

Expected: all tests pass. M1 must not change the cutover adapter's behavior.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`  
Expected: zero failures.

- [ ] **Step 5: Run a temp-store application smoke**

Run:

```bash
M1_DATA=$(mktemp -d)
NUTMEG_DATA_DIR="$M1_DATA" uv run nutmeg ontology init --format json
NUTMEG_DATA_DIR="$M1_DATA" uv run nutmeg ontology status --format json
```

Expected: migration 10 is applied, schema version is 10, integrity is `ok`, and the
production `.nutmeg-data` directory is untouched. Remove only the resolved temp path
after verifying it is under the system temp directory.

- [ ] **Step 6: Update operations documentation**

Document migration 10, outbox health fields, `nutmeg app`, local session behavior,
event cursor recovery, and the fact that M1 does not restore production schedules or
perform funds actions.

- [ ] **Step 7: Add the product pre-commit gate**

Append this local hook after the ontology hook:

```yaml
      - id: pytest-product
        name: pytest (product contract subset when touched)
        entry: bash -c 'uv run pytest tests/product/ -q'
        language: system
        files: ^(nutmeg/product/|nutmeg/interfaces/product_api\.py|nutmeg/interfaces/cli/product\.py|tests/product/)
        pass_filenames: false
```

- [ ] **Step 8: Record fresh verification evidence in this plan**

Append a `## Verification Evidence` section containing the exact UTC timestamp, commit,
commands, pass counts, and temp-store status. Do not mark a command passed without fresh
output from Step 1-5.

- [ ] **Step 9: Commit verification documentation**

```bash
git add docs/ontology-kernel-operations.md \
  docs/superpowers/plans/2026-08-24-nutmeg-intelligence-os-m1.md \
  .pre-commit-config.yaml
git commit -m "docs(product): record M1 operations and verification"
```

## M1 completion boundary

M1 is complete only when all ten tasks are checked, the full suite is green, the
temp-store smoke reports schema 10/integrity ok, and fresh verification evidence is
committed. M1 completion does not authorize restoring schedules, dispatching Telegram,
or placing any real bet.
