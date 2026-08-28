# Phase-Aware Operator Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ontology-first root UI with a phase-aware JCZQ/Zucai workbench that opens the most urgent task, shows only decision-relevant business data, advances through governed actions, and hides technical internals by default.

**Architecture:** Add a typed operator contract above the current product contract, a strict read-only adapter for current Zucai artifacts, pure lane-specific state resolvers, and an operator query/action facade. Serve a focused SSR interface from new templates and static assets while preserving the existing ontology, operations, ticket, review, calibration, and release pages behind a secondary System maintenance entry.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, Jinja2, existing SQLite ontology and typed Actions, existing deterministic Zucai optimizer/deployment modules, vanilla JavaScript, CSS, pytest, Playwright, ruff, uv.

---

## Constraints to reread before implementation

- `AGENTS.md`
- `docs/sop/CONSTITUTION.md`
- `docs/sop/RUNBOOK.md`
- `docs/sop/RULEBOOK.md`
- `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`
- `docs/superpowers/specs/2026-08-28-phase-aware-operator-workbench-design.md`

The implementation may parse, validate, calculate, and report. It may not choose match
faces, a ticket version, a deployment adjudication, a prediction grade, or placement.
`ConfirmDispatch` remains owner-only. Do not modify `scoreboard.json`, restore launchd,
perform a scoreboard cutover, dispatch a real Telegram message during verification, or
create a second Zucai finance/ledger path.

Production issue 26112 currently has structured issue/prep/rx/legs files but no formal
protected ticket batch or audited ticket artifact. The workbench may take 26112 through
judgment, candidate comparison, and deployment reporting. It must show
`protected_artifact_missing` after a recorded deployment until an existing governed
ticket flow supplies an explicitly bound artifact; it may not infer a binding from date,
amount, prose, or similar faces, and it may not claim that confirmation is already open.

## File structure

### New product modules

- `nutmeg/product/operator_contracts.py`: versioned business DTOs and mutation commands;
  no persistence or arithmetic.
- `nutmeg/product/operator_artifacts.py`: strict, read-only parsing of current Zucai
  issue/prep/rx/legs/night artifacts into typed records; no template-facing dictionaries.
- `nutmeg/product/operator_state.py`: pure task priority and phase-resolution functions.
- `nutmeg/product/operator_queries.py`: joins artifacts, ontology facts, deterministic
  calculators, and existing product queries into one current `StepView`.
- `nutmeg/product/operator_actions.py`: narrow facade over the existing Product Action,
  protected ticket, and Telegram confirmation services.

### Existing product modules

- `nutmeg/product/repository.py`: add subject-scoped workflow reads needed by the
  operator projection.
- `nutmeg/product/wiring.py`: compose the artifact repository, operator query/action
  facades, and optional Telegram confirmation transport.
- `nutmeg/product/__init__.py`: export the operator contract/facades.
- `nutmeg/interfaces/product_api.py`: add versioned operator GET/POST endpoints with the
  existing session, CSRF, same-origin, role, and error envelope.
- `nutmeg/interfaces/product_ui.py`: move the old command center from `/` to
  `/system/command-center`; add `/system/*` aliases for the other maintenance pages while
  keeping their legacy URLs stable.
- `nutmeg/interfaces/operator_ui.py`: render `/`, `/tasks`, `/tasks/{task_id}`,
  evidence details, and the System maintenance index.

### New web assets

- `nutmeg/interfaces/web/templates/operator/layout.html`: compact task shell without
  ontology/system health chrome.
- `nutmeg/interfaces/web/templates/operator/task.html`: discriminated step dispatcher.
- `nutmeg/interfaces/web/templates/operator/steps/*.html`: one partial per workflow
  state, each with one primary action.
- `nutmeg/interfaces/web/templates/operator/tasks.html`: lightweight alternate-task list.
- `nutmeg/interfaces/web/templates/operator/evidence.html`: formatted source detail.
- `nutmeg/interfaces/web/templates/operator/system.html`: secondary maintenance index.
- `nutmeg/interfaces/web/static/product/operator.css`: responsive operator-only styles.
- `nutmeg/interfaces/web/static/product/operator.js`: form collection and governed API
  calls only; no odds, probability, audit, funding, or priority math.

### Tests and fixtures

- `tests/product/operator_fixtures.py`: reusable production-shaped 26112 fixture writers.
- `tests/product/test_operator_contracts.py`
- `tests/product/test_operator_artifacts.py`
- `tests/product/test_operator_state.py`
- `tests/product/test_operator_queries.py`
- `tests/product/test_operator_actions.py`
- `tests/product/test_operator_api.py`
- `tests/product/test_operator_ui.py`
- `tests/product/test_operator_e2e.py`
- `tests/product/test_operator_browser.py`

Do not expand `nutmeg/product/contracts.py`, `nutmeg/product/queries.py`, the 3,500-line
shared stylesheet, or the existing 500-line JavaScript file with the operator feature.
The new boundaries prevent those already-large files from becoming harder to verify.

### Task 1: Versioned Operator Contracts

**Files:**
- Create: `nutmeg/product/operator_contracts.py`
- Create: `tests/product/test_operator_contracts.py`
- Modify: `nutmeg/product/__init__.py`

- [ ] **Step 1: Write failing contract tests**

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.operator_contracts import (
    BusinessEvidenceSummary,
    JudgeMatchesStep,
    OperatorLane,
    PrescriptionDeviationCommand,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    TaskProgressSummary,
)


def test_operator_task_response_is_discriminated_and_business_facing() -> None:
    task = OperatorTaskSummary(
        task_id="zucai:26112",
        lane=OperatorLane.ZUCAI,
        business_key="26112",
        title="足彩 26112",
        state=OperatorTaskState.JUDGE_MATCHES,
        deadline_at=datetime(2026, 8, 29, 3, tzinfo=UTC),
        is_actionable=True,
        next_action_label="裁决 ADJ-1",
        priority_rank=0,
    )
    response = OperatorTaskResponse(
        as_of=datetime(2026, 8, 28, 10, tzinfo=UTC),
        mutation_token="a" * 64,
        selected=task,
        alternatives=[],
        progress=TaskProgressSummary(completed=3, total=14, label="逐场判断"),
        step=JudgeMatchesStep(
            task_id=task.task_id,
            item_key="ADJ-1",
            title="任九档位",
            prompt="选择本期部署档位",
            options=["V288", "R432"],
            evidence=[BusinessEvidenceSummary(label="资金帽", value="¥400")],
        ),
    )

    assert response.step.kind == "judge_matches"
    assert "schema_version" in response.model_dump(mode="json")
    assert "action_id" not in response.model_dump(mode="json")


def test_operator_contracts_forbid_unknown_and_actor_fields() -> None:
    with pytest.raises(ValidationError):
        OperatorTaskSummary.model_validate({
            "task_id": "zucai:26112",
            "lane": "zucai",
            "business_key": "26112",
            "title": "足彩 26112",
            "state": "judge_matches",
            "is_actionable": True,
            "next_action_label": "裁决",
            "priority_rank": 0,
            "actor_role": "ai_analyst",
        })


def test_prescription_deviation_requires_a_named_rule_per_match() -> None:
    valid = PrescriptionDeviationCommand(
        match_no=13,
        rule_ids=["q-两阶段"],
        reason="场 13 从单选改为双选",
    )
    assert valid.match_no == 13
    with pytest.raises(ValidationError):
        PrescriptionDeviationCommand(
            match_no=13,
            rule_ids=[],
            reason="没有命名规则",
        )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_contracts.py -v
```

Expected: FAIL during collection because `nutmeg.product.operator_contracts` does not
exist.

- [ ] **Step 3: Add the complete contract vocabulary**

Create strict contracts with these exact public enums and fields:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictOperatorContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedOperatorContract(StrictOperatorContract):
    schema_version: Literal["1"] = "1"


class OperatorLane(StrEnum):
    JCZQ = "jczq"
    ZUCAI = "zucai"


class OperatorTaskState(StrEnum):
    WAITING_DATA = "waiting_data"
    PREPARE = "prepare"
    JUDGE_MATCHES = "judge_matches"
    CONSTRUCT_TICKET = "construct_ticket"
    AUDIT_DEPLOYMENT = "audit_deployment"
    AWAIT_CONFIRMATION = "await_confirmation"
    AWAIT_LEDGER = "await_ledger"
    AWAIT_RESULT = "await_result"
    REVIEW = "review"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class OperatorTaskSummary(StrictOperatorContract):
    task_id: str = Field(min_length=1)
    lane: OperatorLane
    business_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    state: OperatorTaskState
    deadline_at: AwareDatetime | None = None
    waiting_until: AwareDatetime | None = None
    is_actionable: bool
    next_action_label: str = Field(min_length=1)
    priority_rank: int = Field(ge=0)
    block_reason_code: str | None = None


class TaskProgressSummary(StrictOperatorContract):
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    label: str


class BusinessEvidenceSummary(StrictOperatorContract):
    label: str
    value: str
    source_label: str | None = None
    freshness_label: str | None = None
    severity: Literal["info", "warn", "error"] = "info"
    evidence_href: str | None = None


class PrescriptionDifferenceSummary(StrictOperatorContract):
    match_no: int = Field(ge=1, le=14)
    prescribed_faces: str
    candidate_faces: str
    registered_rule_ids: list[str] = Field(default_factory=list)


class OperatorRecoverySummary(StrictOperatorContract):
    code: str
    missing: str
    impact: str
    action_label: str
    retry_at: AwareDatetime | None = None
    href: str | None = None


class WaitingDataStep(StrictOperatorContract):
    kind: Literal["waiting_data"] = "waiting_data"
    task_id: str
    title: str
    recovery: OperatorRecoverySummary


class PrepareStep(StrictOperatorContract):
    kind: Literal["prepare"] = "prepare"
    task_id: str
    title: str
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    recovery: OperatorRecoverySummary


class JudgeMatchesStep(StrictOperatorContract):
    kind: Literal["judge_matches"] = "judge_matches"
    task_id: str
    item_key: str
    title: str
    prompt: str
    options: list[str]
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)


class TicketVersionSummary(StrictOperatorContract):
    candidate_id: str
    label: str
    faces: dict[str, str]
    notes: int = Field(gt=0)
    cost_yuan: int = Field(gt=0)
    p_all: float = Field(ge=0, le=1)
    expected_broken: float = Field(ge=0)
    within_cap: bool | None = None
    common_dead_faces: list[str] = Field(default_factory=list)
    prescription_differences: list[PrescriptionDifferenceSummary] = Field(
        default_factory=list
    )


class ConstructTicketStep(StrictOperatorContract):
    kind: Literal["construct_ticket"] = "construct_ticket"
    task_id: str
    prescription: dict[str, str]
    candidates: list[TicketVersionSummary]


class AuditDeploymentStep(StrictOperatorContract):
    kind: Literal["audit_deployment"] = "audit_deployment"
    task_id: str
    candidate: TicketVersionSummary
    gate_candidate_id: str
    gate_candidate_cost_yuan: int = Field(gt=0)
    audit_state: Literal["pass", "warn", "error"]
    findings: list[BusinessEvidenceSummary]
    deployment_state: Literal["pass", "review", "reduce_or_empty"]
    capital_utilization: float = Field(ge=0)
    median_bonus: float = Field(ge=0)
    break_even_to_median: float = Field(ge=0)
    allowed_decisions: list[str]


class ConfirmationStep(StrictOperatorContract):
    kind: Literal["await_confirmation"] = "await_confirmation"
    task_id: str
    ticket_artifact_id: str
    amount: float = Field(gt=0)
    currency: str
    deadline_at: AwareDatetime
    confirmation_state: Literal["not_issued", "open", "expired"]
    confirmation_expires_at: AwareDatetime | None = None


class LedgerStep(StrictOperatorContract):
    kind: Literal["await_ledger"] = "await_ledger"
    task_id: str
    ticket_artifact_id: str
    placement_state: Literal["unplaced", "placed", "shadow"]
    amount: float
    currency: str
    external_reference: str | None = None


class AwaitResultStep(StrictOperatorContract):
    kind: Literal["await_result"] = "await_result"
    task_id: str
    title: str
    expected_at: AwareDatetime | None = None


class ReviewItemSummary(StrictOperatorContract):
    item_type: Literal["prediction", "adjudication", "factor_verdict"]
    item_id: str
    title: str
    evidence: list[BusinessEvidenceSummary] = Field(default_factory=list)
    allowed_outcomes: list[str]


class ReviewStep(StrictOperatorContract):
    kind: Literal["review"] = "review"
    task_id: str
    hit_count: int | None = None
    total_count: int | None = None
    stake_yuan: float | None = None
    payout_yuan: float | None = None
    pnl_yuan: float | None = None
    calibration_summary: str | None = None
    current_item: ReviewItemSummary


class CompleteStep(StrictOperatorContract):
    kind: Literal["complete"] = "complete"
    task_id: str
    title: str
    summary: str


class BlockedStep(StrictOperatorContract):
    kind: Literal["blocked"] = "blocked"
    task_id: str
    title: str
    recovery: OperatorRecoverySummary
    correlation_id: str | None = None


StepView = Annotated[
    WaitingDataStep | PrepareStep | JudgeMatchesStep | ConstructTicketStep
    | AuditDeploymentStep | ConfirmationStep | LedgerStep | AwaitResultStep
    | ReviewStep | CompleteStep | BlockedStep,
    Field(discriminator="kind"),
]


class OperatorWorklistResponse(VersionedOperatorContract):
    as_of: AwareDatetime
    selected: OperatorTaskSummary | None
    tasks: list[OperatorTaskSummary]


class OperatorTaskResponse(VersionedOperatorContract):
    as_of: AwareDatetime
    mutation_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected: OperatorTaskSummary
    alternatives: list[OperatorTaskSummary]
    progress: TaskProgressSummary
    step: StepView


class OperatorMutationCommand(VersionedOperatorContract):
    expected_snapshot_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)


class ResolveIssueAdjudicationCommand(OperatorMutationCommand):
    adjudication_key: str
    decision: str
    reason: str = Field(min_length=1)
    selected_option: str | None = None
    evidence_rejected: list[dict[str, str]] = Field(default_factory=list)


class PrescriptionDeviationCommand(StrictOperatorContract):
    match_no: int = Field(ge=1, le=14)
    rule_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class SelectTicketVersionCommand(OperatorMutationCommand):
    candidate_id: str
    reason: str = Field(min_length=1)
    deviations: list[PrescriptionDeviationCommand] = Field(default_factory=list)


class RecordDeploymentCommand(OperatorMutationCommand):
    candidate_id: str
    decision: Literal["keep", "drop_match", "change_structure", "empty_position"]
    reason: str = Field(min_length=1)


class RequestTelegramConfirmationCommand(OperatorMutationCommand):
    dry_run: bool = True
```

- [ ] **Step 4: Export contracts and verify GREEN**

Add only stable public names to `nutmeg/product/__init__.py`, then run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_contracts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

```bash
git add nutmeg/product/operator_contracts.py nutmeg/product/__init__.py \
  tests/product/test_operator_contracts.py
UV_FROZEN=1 git commit -m "feat(product): define operator workbench contracts"
```

### Task 2: Strict Zucai Operational Artifact Adapter

**Files:**
- Create: `nutmeg/product/operator_artifacts.py`
- Create: `tests/product/operator_fixtures.py`
- Create: `tests/product/test_operator_artifacts.py`

- [ ] **Step 1: Add production-shaped fixture writers and failing tests**

`tests/product/operator_fixtures.py` must write a minimal strict bundle, not copy the
production directory:

```python
import json
from pathlib import Path


def write_26112_bundle(root: Path) -> Path:
    root.mkdir(parents=True)
    issue = {
        "issue_id": "26112",
        "sale_deadline": None,
        "sources": [{
            "label": "sporttery issue page",
            "url": "https://example.invalid/issue/26112",
            "captured_at": "2026-08-28T14:00:06",
        }],
        "matches": [{
            "match_no": 1,
            "competition": "英超",
            "home_team": "水晶宫",
            "away_team": "曼彻斯特城",
            "kickoff_bj": "2026-08-29 03:00",
            "match_date": "2026-08-29",
            "asian_ref": "1.04,受半球/一球,0.80",
        }],
    }
    prep = {
        "issue": "26112",
        "run_date": "2026-08-28",
        "slot": "afternoon",
        "captured_at": "2026-08-28T14:00:07",
        "n_matches": 1,
        "alignment": {"unmatched": [], "ambiguous": []},
        "screens": {
            "coinflip": [], "fattest_draws": [], "missing_euro_anchor": [],
            "missing_ttg_anchor": [], "strong_anchors": []
        },
        "records": {"1": {
            "name": "水晶宫-曼彻斯特城", "league": "英超",
            "kickoff_bj": "2026-08-29 03:00", "match_date": "2026-08-29",
            "sporttery_match_num": "5011",
            "fair_had": {"home": 0.1956, "draw": 0.2343, "away": 0.5702},
            "sporttery_had_date": "2026-08-27", "hhad_line": "+1",
            "ttg_anchor": True, "lambda": [1.101, 1.984, -0.07],
            "fit_loss": 0.000707, "dc_had": [0.199, 0.2294, 0.5716],
            "top_scores": [["1:1", 0.1069]], "ttg_bands": {"total_2": 0.2246},
            "over25": 0.5956, "margin": {"0": 0.2294},
            "home_by_2plus": 0.0766, "away_by_2plus": 0.3454,
            "hhad_cover": {"line": "+1", "让胜": 0.4284,
                           "让平": 0.2262, "让负": 0.3454},
        }},
        "judgment": None,
    }
    rx = {
        "issue": "26112", "registered_at": "2026-08-28T13:30:00+08:00",
        "decision": "任九主攻", "capital_report": {"票价": "V288=72%帽内"},
        "prescription_P14": {
            "singles": {"3": "3"}, "doubles": {"4": "31"}, "fulls": ["1"],
            "expected_broken_legs": 1.65, "difficulty_price_cny": 12,
            "correction_log": "fixture", "audit_R432": "0 ERROR 0 WARN",
        },
        "ticket_versions": {"R432": "human note; not parsed"},
        "pending_adjudications": [{
            "id": "ADJ-1", "status": "需你行权", "q": "任九档位",
            "options": "R432 / V288", "default": "R432",
        }],
        "predictions": [{"id": "P1", "claim": "至少一场平",
                         "falsifier": "全无平局"}],
        "notes": "fixture",
    }
    legs = {
        "issue": "26112", "version": "R432",
        "legs": {"1": {
            "name": "水晶宫-曼城·310", "faces": "310", "confidence": 2,
            "directional_flags": [["anchor_shield_out", "1"]],
            "nondirectional_flags": ["two_way_instability"],
            "anchor_integrity": "fail",
            "fair": {"home": 0.196, "draw": 0.289, "away": 0.515},
            "precedents": [["1", "fixture precedent", "live"]],
        }},
    }
    for name, value in {
        "26112-issue.json": issue,
        "26112-prep-afternoon.json": prep,
        "26112-rx.json": rx,
        "26112-legs-R432.json": legs,
    }.items():
        (root / name).write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    return root
```

Add these concrete adapter assertions:

```python
def test_discovers_and_loads_strict_26112_bundle(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    repository = ZucaiArtifactRepository(root)

    assert repository.discover_issues() == ["26112"]
    bundle = repository.load("26112")
    assert bundle.issue.issue_id == "26112"
    assert bundle.prep.records["1"].name == "水晶宫-曼彻斯特城"
    assert bundle.prep.captured_at.isoformat() == "2026-08-28T14:00:07+08:00"
    assert bundle.fallback_deadline().isoformat() == "2026-08-29T03:00:00+08:00"
    assert bundle.candidates[0].candidate_id == "R432"
    assert bundle.candidates[0].legs["1"].faces == "310"
    assert [item.candidate_id for item in bundle.candidates] == ["R432"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda root: (root / "26112-rx.json").write_text("{", "utf-8"), "invalid"),
        (lambda root: _replace_json(root / "26112-rx.json", "issue", "26113"),
         "binding mismatch"),
        (lambda root: _replace_json(root / "26112-issue.json", "unexpected", True),
         "invalid"),
        (lambda root: _replace_nested_fair(root / "26112-legs-R432.json", 0.4),
         "sum to 1"),
    ],
)
def test_rejects_malformed_or_misbound_bundle(tmp_path, mutation, message) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    mutation(root)
    with pytest.raises(OperatorArtifactError, match=message):
        ZucaiArtifactRepository(root).load("26112")


def test_rejects_issue_path_traversal(tmp_path: Path) -> None:
    repository = ZucaiArtifactRepository(write_26112_bundle(tmp_path / "zucai"))
    with pytest.raises(OperatorArtifactError, match="five digits"):
        repository.load("../26112")


def test_night_snapshot_is_summary_only(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    (root / "26112-night-2026-08-29-af.json").write_text(json.dumps({
        "issue": "26112",
        "source": "API-Football 90-minute fixture",
        "fetched_at": "2026-08-29T01:00:00+00:00",
        "results": {
            "1": {
                "code": "0", "ft": "1-2", "home": "水晶宫",
                "away": "曼彻斯特城", "status": "FT",
            }
        },
        "skipped": [],
    }, ensure_ascii=False), "utf-8")
    bundle = ZucaiArtifactRepository(root).load("26112")
    assert bundle.night_snapshots[-1].results["1"].code == "0"
    assert not hasattr(bundle.night_snapshots[-1], "prediction_grade")
```

`_replace_json` and `_replace_nested_fair` are test-only JSON load/mutate/write helpers.
Create `26112-legs-R432.json` and `26112-legs-r432.json` and assert the case-insensitive
candidate identity collision is rejected. The embedded `version` remains a display label,
not identity. Assert the rx `ticket_versions` prose never appears in the candidate list.

- [ ] **Step 2: Run the adapter tests and verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_artifacts.py -v
```

Expected: FAIL because `ZucaiArtifactRepository` and its contracts do not exist.

- [ ] **Step 3: Implement strict source models and loader**

Implement Pydantic source models with `ConfigDict(extra="forbid")` for the exact fixture
shape and the current production keys listed in the design. Import `Decimal`, `datetime`,
`field_validator`, and `ZoneInfo`; use `_SHANGHAI = ZoneInfo("Asia/Shanghai")`. Current
source timestamps without an offset are documented Shanghai local times, not UTC. Use
these public repository methods:

```python
class StrictSource(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ZucaiSourceRef(StrictSource):
    label: str
    url: str
    captured_at: str


class ZucaiIssueMatch(StrictSource):
    match_no: int = Field(ge=1, le=14)
    competition: str
    home_team: str
    away_team: str
    kickoff_bj: str
    match_date: str
    asian_ref: str | None = None


class ZucaiIssueDocument(StrictSource):
    issue_id: str = Field(pattern=r"^\d{5}$")
    sale_deadline: str | None = None
    sources: list[ZucaiSourceRef]
    matches: list[ZucaiIssueMatch] = Field(min_length=1, max_length=14)


class ProbabilityTriple(StrictSource):
    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)


class PrepScreenItem(StrictSource):
    match_no: int = Field(ge=1, le=14)
    name: str
    face: str | None = None
    top1: float | None = Field(default=None, ge=0, le=1)
    draw: float | None = Field(default=None, ge=0, le=1)


class PrepScreens(StrictSource):
    strong_anchors: list[PrepScreenItem]
    coinflip: list[PrepScreenItem]
    fattest_draws: list[PrepScreenItem]
    missing_euro_anchor: list[PrepScreenItem]
    missing_ttg_anchor: list[PrepScreenItem]


class AlignmentItem(StrictSource):
    match_no: int = Field(ge=1, le=14)
    home: str
    away: str
    competition: str


class PrepAlignment(StrictSource):
    unmatched: list[AlignmentItem]
    ambiguous: list[AlignmentItem]


class ZucaiPrepRecord(StrictSource):
    name: str
    league: str
    kickoff_bj: str
    match_date: str
    sporttery_match_num: str
    fair_had: ProbabilityTriple
    sporttery_had_date: str
    hhad_line: str | None = None
    ttg_anchor: bool
    lambdas: list[float] = Field(alias="lambda", min_length=3, max_length=3)
    fit_loss: float
    dc_had: list[float] = Field(min_length=3, max_length=3)
    top_scores: list[tuple[str, float]]
    ttg_bands: dict[str, float]
    over25: float = Field(ge=0, le=1)
    margin: dict[str, float]
    home_by_2plus: float = Field(ge=0, le=1)
    away_by_2plus: float = Field(ge=0, le=1)
    hhad_cover: dict[str, float | str]


class ZucaiPrepDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    run_date: str
    slot: str
    captured_at: datetime
    n_matches: int = Field(ge=1, le=14)
    alignment: PrepAlignment
    screens: PrepScreens
    records: dict[str, ZucaiPrepRecord]
    judgment: dict[str, object] | None = None

    @field_validator("captured_at", mode="after")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=_SHANGHAI)
        return value.astimezone(_SHANGHAI)


class ZucaiPrescription(StrictSource):
    singles: dict[str, str]
    doubles: dict[str, str]
    fulls: list[str]
    expected_broken_legs: float
    correction_log: str
    difficulty_price_cny: int
    audit_R432: str


class ZucaiPendingAdjudication(StrictSource):
    id: str
    status: str
    q: str
    options: str | None = None
    default: str | None = None
    reason: str | None = None
    evidence_rejected: str | None = None
    deployment_gate: str | None = None

    @property
    def requires_operator(self) -> bool:
        return not any(mark in self.status for mark in _RESOLVED_MARKS)


class ZucaiPrediction(StrictSource):
    id: str
    claim: str
    falsifier: str


class ZucaiRxDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    registered_at: AwareDatetime
    decision: str
    capital_report: dict[str, str]
    prescription_P14: ZucaiPrescription
    ticket_versions: dict[str, str]
    pending_adjudications: list[ZucaiPendingAdjudication]
    predictions: list[ZucaiPrediction]
    notes: str


class ZucaiCandidateLeg(StrictSource):
    name: str
    faces: str
    confidence: int = Field(ge=0, le=5)
    directional_flags: list[tuple[str, str]]
    nondirectional_flags: list[str]
    anchor_integrity: str
    fair: ProbabilityTriple
    precedents: list[tuple[str, str, str]]


class ZucaiCandidateDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    version: str
    legs: dict[str, ZucaiCandidateLeg]
    candidate_id: str = Field(exclude=True)

    def faces(self) -> dict[str, str]:
        return {match_no: leg.faces for match_no, leg in self.legs.items()}


class ZucaiNightResult(StrictSource):
    code: Literal["3", "1", "0"]
    ft: str
    home: str
    away: str
    status: str


class ZucaiNightDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    source: str
    fetched_at: AwareDatetime
    results: dict[str, ZucaiNightResult]
    skipped: list[str]


class ZucaiArtifactBundle(StrictSource):
    issue: ZucaiIssueDocument
    prep: ZucaiPrepDocument
    rx: ZucaiRxDocument
    candidates: list[ZucaiCandidateDocument]
    night_snapshots: list[ZucaiNightDocument] = Field(default_factory=list)
```

Use field validators to require unique match numbers, candidate leg keys that are unique
decimal strings in the inclusive range `1..14` (a Renjiu candidate may contain only nine
keys), and face strings containing unique `3/1/0`. Validate probability sums with
`abs(sum(Decimal(str(value))) - Decimal("1")) <= Decimal("0.001")`; do not use binary-float
comparison at this boundary because the production 26112 fair rows include exact `1.001`
sums. `judgment` is not exposed by any operator DTO; if production introduces a non-null
shape, add a named strict source contract before accepting it.

```python
class OperatorArtifactError(ValueError):
    pass


class ZucaiArtifactRepository:
    RX_PATTERN = re.compile(r"^(?P<issue>\d{5})-rx\.json$")

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def discover_issues(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted({
            match.group("issue")
            for path in self._root.iterdir()
            if path.is_file() and (match := self.RX_PATTERN.fullmatch(path.name))
        })

    def load(self, issue: str) -> ZucaiArtifactBundle:
        if not re.fullmatch(r"\d{5}", issue):
            raise OperatorArtifactError("zucai issue must be five digits")
        issue_doc = self._read(f"{issue}-issue.json", ZucaiIssueDocument)
        rx = self._read(f"{issue}-rx.json", ZucaiRxDocument)
        prep = self._latest_prep(issue)
        candidates = self._candidate_documents(issue)
        night_snapshots = self._night_documents(issue)
        if issue_doc.issue_id != issue or rx.issue != issue:
            raise OperatorArtifactError("artifact issue binding mismatch")
        if any(candidate.issue != issue for candidate in candidates):
            raise OperatorArtifactError("candidate issue binding mismatch")
        return ZucaiArtifactBundle(
            issue=issue_doc,
            prep=prep,
            rx=rx,
            candidates=candidates,
            night_snapshots=night_snapshots,
        )

    def _read(self, name: str, model_type):
        path = (self._root / name).resolve()
        if path.parent != self._root:
            raise OperatorArtifactError("artifact path escaped root")
        try:
            payload = json.loads(path.read_text("utf-8"))
            return model_type.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise OperatorArtifactError(f"invalid operator artifact {name}") from error
```

`_latest_prep` selects the valid prep document with the greatest normalized aware
`captured_at` and then filename. `_candidate_documents` accepts only
`{issue}-legs-{candidate_id}.json`, rejects case-insensitive identity collisions, injects
the filename identity before validation, and sorts by ID:

```python
payload = self._json_payload(path)
payload["candidate_id"] = candidate_id
candidate = ZucaiCandidateDocument.model_validate(payload)
```

`_json_payload` has the same containment, JSON-decode, and error translation as `_read`.
It returns a fresh dictionary and rejects a source document that already supplies
`candidate_id`; source files cannot override filename identity.

`_night_documents` accepts only `{issue}-night-YYYY-MM-DD-af.json`, validates result keys
as unique decimal match numbers `1..14`, validates the embedded issue, and sorts by aware
`fetched_at` then filename. Missing night files produce an empty tuple/list. A night
snapshot may populate `calibration_summary`, but it cannot set `result_available`, settle
a ticket, or grade a Prediction; those transitions require their formal ontology facts.

Add pure helpers on `ZucaiArtifactBundle`:

```python
def fallback_deadline(self) -> datetime | None:
    if self.issue.sale_deadline:
        return parse_shanghai(self.issue.sale_deadline)
    kickoffs = [parse_shanghai(match.kickoff_bj) for match in self.issue.matches]
    return min(kickoffs, default=None)


def match_record(self, match_no: int) -> ZucaiPrepRecord | None:
    return self.prep.records.get(str(match_no)) if self.prep else None
```

- [ ] **Step 4: Verify strict parsing against fixture and production shape**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_artifacts.py -v
UV_FROZEN=1 uv run python -c \
  'from pathlib import Path; from nutmeg.product.operator_artifacts import ZucaiArtifactRepository as R; b=R(Path(".nutmeg-data/zucai")).load("26112"); print(b.rx.issue, b.prep.captured_at.isoformat(), b.fallback_deadline().isoformat(), [c.candidate_id for c in b.candidates])'
```

Expected: tests PASS; smoke output is exactly
`26112 2026-08-28T14:00:07+08:00 2026-08-28T22:00:00+08:00 ['R432', 'SFC256']`.
The smoke command is read-only.

- [ ] **Step 5: Commit the artifact adapter**

```bash
git add nutmeg/product/operator_artifacts.py tests/product/operator_fixtures.py \
  tests/product/test_operator_artifacts.py
UV_FROZEN=1 git commit -m "feat(product): parse current operator artifacts"
```

### Task 3: Pure Workflow State and Priority Resolver

**Files:**
- Create: `nutmeg/product/operator_state.py`
- Create: `tests/product/test_operator_state.py`

- [ ] **Step 1: Write failing state-transition tests**

```python
from dataclasses import replace
from datetime import UTC, datetime

from nutmeg.product.operator_contracts import OperatorLane, OperatorTaskState
from nutmeg.product.operator_state import OperatorTaskFacts, priority_key, resolve_state

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


def _facts(**changes) -> OperatorTaskFacts:
    base = OperatorTaskFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26112",
        deadline_at=datetime(2026, 8, 29, 3, tzinfo=UTC),
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=1,
        candidate_count=1,
        selected_candidate_id=None,
        audit_recorded=False,
        deployment_decision=None,
        ticket_artifact_id=None,
        confirmation_state=None,
        placement_state=None,
        result_available=False,
        pending_review_items=0,
    )
    return replace(base, **changes)


def test_zucai_state_advances_only_from_persisted_facts() -> None:
    assert resolve_state(_facts()) is OperatorTaskState.JUDGE_MATCHES
    assert resolve_state(_facts(unresolved_adjudications=0)) is OperatorTaskState.CONSTRUCT_TICKET
    assert resolve_state(_facts(
        unresolved_adjudications=0, selected_candidate_id="R432"
    )) is OperatorTaskState.AUDIT_DEPLOYMENT
    assert resolve_state(_facts(
        unresolved_adjudications=0, selected_candidate_id="R432",
        audit_recorded=True, deployment_decision="keep",
        ticket_artifact_id="tat-1", confirmation_state="not_issued",
    )) is OperatorTaskState.AWAIT_CONFIRMATION
    assert resolve_state(_facts(
        unresolved_adjudications=0, selected_candidate_id="R432",
        audit_recorded=True, deployment_decision="keep",
        ticket_artifact_id="tat-1", confirmation_state="consumed",
        placement_state="placed",
    )) is OperatorTaskState.AWAIT_RESULT
    assert resolve_state(_facts(
        unresolved_adjudications=0, selected_candidate_id="R432",
        audit_recorded=True, deployment_decision="keep",
        ticket_artifact_id="tat-1", confirmation_state="consumed",
        placement_state="placed", result_available=True,
        pending_review_items=2,
    )) is OperatorTaskState.REVIEW


def test_priority_uses_workflow_and_deadline_not_football_values() -> None:
    due = _facts()
    unknown_deadline = replace(due, business_key="26113", deadline_at=None)
    review = _facts(
        business_key="26111", result_available=True, pending_review_items=1,
        unresolved_adjudications=0, selected_candidate_id="R432",
        audit_recorded=True, deployment_decision="keep", ticket_artifact_id="tat-1",
        confirmation_state="consumed", placement_state="placed",
    )

    assert priority_key(due, NOW) < priority_key(unknown_deadline, NOW)
    assert priority_key(due, NOW) < priority_key(review, NOW)


def test_waiting_tasks_sort_by_retry_time_before_deadline() -> None:
    early_retry = _facts(
        has_issue=False,
        waiting_until=datetime(2026, 8, 28, 11, tzinfo=UTC),
        deadline_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    early_deadline = replace(
        early_retry,
        business_key="26113",
        waiting_until=datetime(2026, 8, 28, 12, tzinfo=UTC),
        deadline_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert priority_key(early_retry, NOW) < priority_key(early_deadline, NOW)
```

Cover the remaining transition table with one explicit parameterization:

```python
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"has_issue": False}, OperatorTaskState.WAITING_DATA),
        ({"has_prep": False}, OperatorTaskState.PREPARE),
        ({"source_error_code": "invalid"}, OperatorTaskState.BLOCKED),
        ({"unresolved_adjudications": 0, "candidate_count": 0},
         OperatorTaskState.CONSTRUCT_TICKET),
        ({"unresolved_adjudications": 0, "selected_candidate_id": "R432",
          "audit_recorded": True, "deployment_decision": "keep",
          "ticket_artifact_id": "tat-1", "confirmation_state": "consumed",
          "placement_state": "shadow"}, OperatorTaskState.COMPLETE),
        ({"unresolved_adjudications": 0, "selected_candidate_id": "R432",
          "audit_recorded": True, "deployment_decision": "change_structure"},
         OperatorTaskState.CONSTRUCT_TICKET),
        ({"unresolved_adjudications": 0, "selected_candidate_id": "R432",
          "audit_recorded": True, "deployment_decision": "drop_match"},
         OperatorTaskState.CONSTRUCT_TICKET),
        ({"unresolved_adjudications": 0, "selected_candidate_id": "R432",
          "audit_recorded": True, "deployment_decision": "empty_position"},
         OperatorTaskState.COMPLETE),
    ],
)
def test_transition_table(changes, expected) -> None:
    assert resolve_state(_facts(**changes)) is expected
```

Add direct `priority_key` assertions for JCZQ/Zucai tie-breaking, waiting time, complete
tasks, and identical timestamps; the expected order is lane value then business key.

- [ ] **Step 2: Run tests and verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_state.py -v
```

Expected: FAIL because `operator_state` is absent.

- [ ] **Step 3: Implement the immutable facts and pure transition table**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.product.operator_contracts import OperatorLane, OperatorTaskState

_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class OperatorTaskFacts:
    lane: OperatorLane
    business_key: str
    deadline_at: datetime | None
    waiting_until: datetime | None
    source_error_code: str | None
    has_issue: bool
    has_prep: bool
    unresolved_adjudications: int
    candidate_count: int
    selected_candidate_id: str | None
    audit_recorded: bool
    deployment_decision: str | None
    ticket_artifact_id: str | None
    confirmation_state: str | None
    placement_state: str | None
    result_available: bool
    pending_review_items: int


def resolve_state(facts: OperatorTaskFacts) -> OperatorTaskState:
    if facts.source_error_code:
        return OperatorTaskState.BLOCKED
    if not facts.has_issue:
        return OperatorTaskState.WAITING_DATA
    if not facts.has_prep:
        return OperatorTaskState.PREPARE
    if facts.unresolved_adjudications:
        return OperatorTaskState.JUDGE_MATCHES
    if not facts.candidate_count or facts.selected_candidate_id is None:
        return OperatorTaskState.CONSTRUCT_TICKET
    if not facts.audit_recorded:
        return OperatorTaskState.AUDIT_DEPLOYMENT
    if facts.deployment_decision in {"change_structure", "drop_match"}:
        return OperatorTaskState.CONSTRUCT_TICKET
    if facts.deployment_decision == "empty_position":
        return OperatorTaskState.COMPLETE
    if facts.deployment_decision != "keep":
        return OperatorTaskState.AUDIT_DEPLOYMENT
    if facts.ticket_artifact_id is None:
        return OperatorTaskState.BLOCKED
    if facts.placement_state == "shadow":
        return OperatorTaskState.COMPLETE
    if facts.confirmation_state in {None, "not_issued", "open", "expired"}:
        return OperatorTaskState.AWAIT_CONFIRMATION
    if facts.placement_state != "placed":
        return OperatorTaskState.AWAIT_LEDGER
    if not facts.result_available:
        return OperatorTaskState.AWAIT_RESULT
    if facts.pending_review_items:
        return OperatorTaskState.REVIEW
    return OperatorTaskState.COMPLETE


def priority_key(facts: OperatorTaskFacts, now: datetime) -> tuple:
    state = resolve_state(facts)
    deadline = facts.deadline_at or _FAR_FUTURE
    before_deadline_human = state in {
        OperatorTaskState.JUDGE_MATCHES,
        OperatorTaskState.CONSTRUCT_TICKET,
        OperatorTaskState.AUDIT_DEPLOYMENT,
        OperatorTaskState.AWAIT_CONFIRMATION,
    } and (facts.deadline_at is None or facts.deadline_at > now)
    overdue_resolution = (
        facts.deadline_at is not None
        and facts.deadline_at <= now
        and state in {
            OperatorTaskState.AWAIT_CONFIRMATION,
            OperatorTaskState.AWAIT_LEDGER,
            OperatorTaskState.BLOCKED,
        }
    )
    category = (
        0 if before_deadline_human else
        1 if overdue_resolution else
        2 if state not in {
            OperatorTaskState.WAITING_DATA,
            OperatorTaskState.REVIEW,
            OperatorTaskState.COMPLETE,
        } else
        3 if state is OperatorTaskState.REVIEW else
        4 if state is OperatorTaskState.WAITING_DATA else
        5
    )
    next_time = (
        facts.waiting_until or _FAR_FUTURE
        if state is OperatorTaskState.WAITING_DATA
        else deadline
    )
    task_id = f"{facts.lane.value}:{facts.business_key}"
    return (category, next_time, facts.lane.value, facts.business_key, task_id)
```

Keep state labels and next-action labels in explicit dictionaries keyed by
`OperatorTaskState`. Do not derive them from enum names in the template.

- [ ] **Step 4: Verify GREEN and mutation-free determinism**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_state.py -v
UV_FROZEN=1 uv run ruff check nutmeg/product/operator_state.py \
  tests/product/test_operator_state.py
```

Expected: all tests PASS and ruff reports no errors.

- [ ] **Step 5: Commit the resolver**

```bash
git add nutmeg/product/operator_state.py tests/product/test_operator_state.py
UV_FROZEN=1 git commit -m "feat(product): resolve current operator task"
```

### Task 4: Subject-Scoped Reads and Operator Query Service

**Files:**
- Modify: `nutmeg/product/repository.py`
- Create: `nutmeg/product/operator_queries.py`
- Create: `tests/product/test_operator_queries.py`

- [ ] **Step 1: Write failing repository and query tests**

Seed two issue-scoped Adjudications whose `alternative` values contain
`rx_adjudication_id`, `candidate_id`, and `deployment_decision`; seed one issue-scoped
Prediction and one protected ticket artifact. Use `write_26112_bundle` and a fake official
history provider.

```python
def test_26112_query_selects_unresolved_adjudication(
    operator_queries, artifact_root
) -> None:
    response = operator_queries.task("zucai:26112", as_of=NOW)

    assert response.selected.task_id == "zucai:26112"
    assert response.selected.state == "judge_matches"
    assert response.step.kind == "judge_matches"
    assert response.step.item_key == "ADJ-1"
    assert response.step.evidence[0].label == "资金"
    assert response.progress.completed == 0
    assert response.progress.total == 1


def test_query_computes_candidate_rows_without_parsing_rx_prose(
    operator_queries, record_issue_adjudication
) -> None:
    record_issue_adjudication(
        alternative={"rx_adjudication_id": "ADJ-1", "selected_option": "R432"}
    )

    response = operator_queries.task("zucai:26112", as_of=NOW)

    assert response.step.kind == "construct_ticket"
    assert [item.candidate_id for item in response.step.candidates] == ["R432"]
    assert response.step.candidates[0].notes == 3
    assert response.step.candidates[0].cost_yuan == 6
    assert "human note" not in response.model_dump_json()


def test_query_computes_structured_diffs_and_common_dead_faces(
    operator_queries_two_candidates, record_issue_adjudication
) -> None:
    record_issue_adjudication(
        alternative={"rx_adjudication_id": "ADJ-1", "selected_option": "R432"}
    )
    response = operator_queries_two_candidates.task("zucai:26112", as_of=NOW)
    r432 = next(item for item in response.step.candidates if item.candidate_id == "R432")
    assert {item.match_no for item in r432.prescription_differences} == {12, 13}
    assert response.step.candidates[0].common_dead_faces == ["场1: 10"]


def test_explicit_indistinguishability_allows_but_does_not_select_empty_position(
    operator_queries_at_gate, record_issue_adjudication
) -> None:
    record_issue_adjudication(
        alternative={"materially_indistinguishable": True}
    )
    task = operator_queries_at_gate.task("zucai:26112", as_of=NOW)
    assert "empty_position" in task.step.allowed_decisions
    assert task.step.allowed_decisions[0] == "keep"
```

Add these exact query outcomes:

```python
def test_worklist_prefers_earliest_actionable_deadline(operator_queries) -> None:
    worklist = operator_queries.worklist(as_of=NOW)
    assert worklist.selected.task_id == "zucai:26112"
    assert [item.priority_rank for item in worklist.tasks] == list(
        range(len(worklist.tasks))
    )


def test_invalid_bundle_is_visible_block_not_exception(operator_queries) -> None:
    worklist = operator_queries.worklist(as_of=NOW)
    task = next(item for item in worklist.tasks if item.business_key == "26113")
    assert task.state == "blocked"
    assert task.block_reason_code == "source_contract_invalid"


def test_unknown_task_is_not_found(operator_queries) -> None:
    with pytest.raises(ProductNotFoundError):
        operator_queries.task("zucai:99999", as_of=NOW)


def test_official_history_outage_is_retryable_recovery(operator_queries_at_gate) -> None:
    operator_queries_at_gate.official_history.side_effect = RuntimeError("offline")
    task = operator_queries_at_gate.task("zucai:26112", as_of=NOW)
    assert task.step.kind == "blocked"
    assert task.step.recovery.code == "official_history_unavailable"
    assert task.step.recovery.retry_at is not None


def test_gate_metrics_name_cap_candidate_when_it_differs_from_user_choice(
    operator_queries_over_cap_choice,
) -> None:
    task = operator_queries_over_cap_choice.task("zucai:26112", as_of=NOW)
    assert task.step.kind == "audit_deployment"
    assert task.step.candidate.candidate_id == "R432"
    assert task.step.gate_candidate_id == "V288"
    assert task.step.gate_candidate_cost_yuan == 288
    assert "keep" not in task.step.allowed_decisions


def test_complete_task_is_listed_but_never_auto_selected(operator_queries_complete) -> None:
    worklist = operator_queries_complete.worklist(as_of=NOW)
    complete = next(item for item in worklist.tasks if item.state == "complete")
    assert complete.task_id == "zucai:26111"
    assert worklist.selected is None or worklist.selected.task_id != complete.task_id


def test_rejected_action_does_not_advance_progress(operator_queries_rejected) -> None:
    before = operator_queries_rejected.task("zucai:26112", as_of=NOW)
    operator_queries_rejected.gateway.reject_next("record_adjudication")
    operator_queries_rejected.try_current_adjudication()
    after = operator_queries_rejected.task("zucai:26112", as_of=NOW)
    assert after.progress == before.progress
    assert after.step.kind == "judge_matches"


def test_shadow_scoreboard_authority_is_preserved(operator_queries_shadow) -> None:
    task = operator_queries_shadow.task("zucai:26111", as_of=NOW)
    assert task.step.kind == "review"
    assert operator_queries_shadow.scoreboard.authority.state == "legacy"
    assert operator_queries_shadow.scoreboard_write_count == 0
```

Use the protected ticket fixture for open/expired/placed/shadow transitions. Seed an
authoritative result and pending issue prediction; assert the state becomes `review` and
the current item is that prediction.

- [ ] **Step 2: Run query tests and verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_queries.py -v
```

Expected: FAIL because subject-scoped reads and `OperatorQueryService` do not exist.

- [ ] **Step 3: Add general subject-scoped repository reads**

Add these methods to `ProductReadRepository`; decode JSON through the existing
`_decode_json` helper and enforce `created_at/registered_at <= as_of`:

```python
def adjudications_for_subject(
    self, subject_type: str, subject_id: str, as_of: str
) -> list[dict]:
    statement = (
        select(sw.adjudications)
        .where(
            sw.adjudications.c.subject_type == subject_type,
            sw.adjudications.c.subject_id == subject_id,
            sw.adjudications.c.created_at <= as_of,
        )
        .order_by(sw.adjudications.c.created_at, sw.adjudications.c.adjudication_id)
    )
    with self._engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    return [
        self._decode_json(row, ("evidence_rejected_json", "alternative_json"))
        for row in rows
    ]


def predictions_for_subject(
    self, subject_type: str, subject_id: str, as_of: str
) -> list[dict]:
    statement = (
        select(sw.predictions)
        .where(
            sw.predictions.c.subject_type == subject_type,
            sw.predictions.c.subject_id == subject_id,
            sw.predictions.c.registered_at <= as_of,
        )
        .order_by(sw.predictions.c.registered_at, sw.predictions.c.prediction_id)
    )
    with self._engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings().all()]
```

Add `operator_ticket_artifacts(as_of)` that returns current batch run date, artifact,
confirmation, placement, and shadow columns plus decoded payload. It must use SQL joins
and timestamps, not inspect Action return counts. This read discovers JCZQ tasks from
formal batch `run_date`. It does not associate a Zucai issue by coincident date, price,
teams, faces, or artifact payload. A Zucai artifact is visible only after a future
governed binding exists; until then `protected_artifact_missing` is the truthful recovery.

- [ ] **Step 4: Implement `OperatorQueryService`**

The constructor and public API are fixed:

```python
class OperatorQueryService:
    def __init__(
        self,
        *,
        repository: ProductReadRepository,
        product_queries: ProductQueryService,
        artifacts: ZucaiArtifactRepository,
        official_history_provider: Callable[[], list[OfficialRenjiuHistory]],
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._product_queries = product_queries
        self._artifacts = artifacts
        self._official_history = official_history_provider
        self._clock = clock

    def worklist(self, *, as_of: datetime) -> OperatorWorklistResponse:
        cutoff = _aware(as_of, "as_of")
        built = sorted(
            self._build_all(cutoff),
            key=lambda item: priority_key(item.facts, cutoff),
        )
        tasks = [
            item.summary.model_copy(update={"priority_rank": rank})
            for rank, item in enumerate(built)
        ]
        selected = next(
            (item for item in tasks if item.state is not OperatorTaskState.COMPLETE),
            None,
        )
        return OperatorWorklistResponse(
            as_of=cutoff,
            selected=selected,
            tasks=tasks,
        )

    def task(self, task_id: str, *, as_of: datetime) -> OperatorTaskResponse:
        cutoff = _aware(as_of, "as_of")
        worklist = self.worklist(as_of=cutoff)
        selected = next(
            (item for item in worklist.tasks if item.task_id == task_id),
            None,
        )
        if selected is None:
            raise ProductNotFoundError(f"operator task {task_id} not found")
        built = self._build_task(task_id, cutoff)
        return OperatorTaskResponse(
            as_of=cutoff,
            mutation_token=built.mutation_token,
            selected=selected,
            alternatives=[
                item for item in worklist.tasks if item.task_id != task_id
            ],
            progress=built.progress,
            step=built.step,
        )

    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operator clock must be timezone-aware")
        return value
```

Define internal `_BuiltTask(facts, summary, progress, step, mutation_token)`,
`_build_all(cutoff)`, and
`_build_task(task_id, cutoff)` in the same module. `_build_all` is the only discovery
path: validated rx filenames produce Zucai IDs and formal current protected batches
produce JCZQ dates. `_build_task` accepts only `zucai:<five digits>` or
`jczq:<YYYY-MM-DD>` and delegates to a lane-specific builder. Both builders derive
progress from committed repository rows and return one typed `StepView`; they never
read a service return count.

Compute `mutation_token` as SHA-256 over canonical JSON containing the task ID, the
validated bundle `model_dump(mode="json")`, candidate IDs, committed Adjudication
`id/created_at`, Prediction `id/status/settled_at`, and any formal protected-ticket
revision/confirmation/placement/shadow IDs and timestamps used by the task. The token is
an optimistic-concurrency binding, not an authority fact. Never render it as text; every
mutation compares it against a freshly built task before calling an Action.

Implement the Zucai snapshot in this order:

```python
bundle = self._artifacts.load(issue)
adjudications = self._repository.adjudications_for_subject(
    "issue", issue, cutoff.isoformat()
)
predictions = self._repository.predictions_for_subject(
    "issue", issue, cutoff.isoformat()
)
resolved_rx_ids = {
    str(row["alternative"].get("rx_adjudication_id"))
    for row in adjudications
    if row["alternative"].get("rx_adjudication_id")
}
unresolved = [
    item for item in bundle.rx.pending_adjudications
    if item.id not in resolved_rx_ids and item.requires_operator
]
selection = next((
    row
    for row in reversed(adjudications)
    if row["alternative"].get("candidate_id")
), None)
selected = (
    str(selection["alternative"]["candidate_id"])
    if selection is not None
    else None
)
deployment = next((
    row for row in reversed(adjudications)
    if row["alternative"].get("deployment_decision")
    and selection is not None
    and row["created_at"] > selection["created_at"]
), None)
```

Thus a `change_structure` or `drop_match` decision sends the state back to construction;
a later candidate-selection Adjudication supersedes that deployment decision for state
resolution even though immutable history is retained. An explicit `empty_position`
completes as not placed. Only `keep` may advance toward a formally bound artifact.

Candidate comparison must call existing `optimize()` with only structured candidate
documents:

```python
comparison = optimize({
    "issue": issue,
    "price_per_note": 2,
    "budget_yuan": 400,
    "baseline_id": None,
    "fair": merged_fair,
    "versions": [
        {"id": candidate.candidate_id, "faces": candidate.faces()}
        for candidate in bundle.candidates
    ],
    "groups": [],
})
```

For each candidate, compare the structured face set against the flattened prescription
and populate typed `PrescriptionDifferenceSummary` rows, for example
`match_no=13, prescribed_faces="3", candidate_faces="31"` and
`match_no=12, prescribed_faces="31", candidate_faces=""`. Attach committed
`registered_rule_ids` only when the selected candidate's Adjudication contains a
matching `deviation_registry` row. Compute `common_dead_faces` from the structured face
sets; do not recover either field from rx prose. Add exact tests for the R432/SFC256 group
showing its common dead faces and for every prescription diff match number.

Audit maps each selected candidate leg to `Leg` and calls both `audit_legs` and
`audit_prescription_deviations`; the latter receives the flattened prescription, selected
structured legs, and committed named-rule deviation registry. Deployment uses
`evaluate_deployment_gate` with the injected official history provider. Map those typed
outputs to `BusinessEvidenceSummary` and `AuditDeploymentStep`. Allowed deployment
decisions are exact and non-recommending:

```python
allowed = {
    DeploymentGateState.PASS: ["keep", "change_structure"],
    DeploymentGateState.REVIEW: ["keep", "drop_match", "change_structure"],
    DeploymentGateState.REDUCE_OR_EMPTY: [
        "drop_match", "change_structure", "empty_position"
    ],
}[gate.state]
```

`AuditDeploymentStep.candidate` always remains the candidate explicitly selected by the
operator. `gate_candidate_id`, `gate_candidate_cost_yuan`, capital utilization, median,
and break-even metrics come from `evaluate_deployment_gate`'s cap-optimal result. If those
candidate IDs differ, remove `keep` from `allowed`; the page must say the chosen structure
is not the measured cap candidate and require `change_structure` or an otherwise
gate-permitted reduction. It must never relabel the gate candidate as the user's choice.

If a prior issue Adjudication explicitly carries
`alternative.materially_indistinguishable is True`, append `empty_position` to `allowed`.
Do not derive that flag from market probabilities, confidence, or narrative text.

For postmatch review, use `ProductQueryService.scoreboard(as_of=cutoff)` before
`ProductQueryService.review(as_of=cutoff)`. While authority state is `legacy` (the current
shadow period), label the projection as a governed observation rather than authority;
never read, rewrite, or supersede `.nutmeg-data/scoreboard.json` from this service. A
stale projection produces the `projection_stale` recovery instead of silently falling
back to action counts.

For JCZQ, create a task only from formal active ticket batches/artifacts. Do not classify
every ontology board match as JCZQ, because current Zucai matches share the same Match
ontology. A future lane-identity object may widen discovery without changing this API.

- [ ] **Step 5: Verify query behavior and production-shaped 26112 replay**

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_artifacts.py \
  tests/product/test_operator_state.py \
  tests/product/test_operator_queries.py -v
```

Expected: all tests PASS. The 26112 fixture resolves to `judge_matches`, contains no raw
JSON/prose ticket-version parsing, and computes candidate arithmetic through the existing
optimizer.

- [ ] **Step 6: Commit the query slice**

```bash
git add nutmeg/product/repository.py nutmeg/product/operator_queries.py \
  tests/product/test_operator_queries.py
UV_FROZEN=1 git commit -m "feat(product): assemble phase-aware operator tasks"
```

### Task 5: Governed Operator Actions and API Boundary

**Files:**
- Modify: `nutmeg/product/operator_contracts.py`
- Create: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/product/wiring.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Create: `tests/product/test_operator_actions.py`
- Create: `tests/product/test_operator_api.py`

- [ ] **Step 1: Write failing action-facade tests**

Use fake Product Action and Telegram services that record calls. Assert exact mapping,
current-step validation, and owner authority:

```python
def test_resolve_issue_adjudication_writes_named_typed_action(service) -> None:
    result = service.resolve_issue_adjudication(
        "zucai:26112",
        ResolveIssueAdjudicationCommand(
            expected_snapshot_token="a" * 64,
            adjudication_key="ADJ-1",
            decision="override",
            reason="Jun selected the disclosed exception",
            selected_option="R432",
            evidence_rejected=[{"object_type": "claim", "object_id": "claim-1"}],
            idempotency_key="ui:26112:ADJ-1",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert result.status == "committed"
    request = service.action_gateway.requests[-1]
    assert request.action_type == "record_adjudication"
    assert request.payload["subject_type"] == "issue"
    assert request.payload["subject_id"] == "26112"
    assert request.payload["alternative"] == {
        "rx_adjudication_id": "ADJ-1",
        "selected_option": "R432",
    }


def test_empty_position_is_rejected_when_gate_does_not_offer_it(service) -> None:
    with pytest.raises(ProductActionBlockedError, match="not allowed by current gate"):
        service.record_deployment(
            "zucai:26112",
            RecordDeploymentCommand(
                expected_snapshot_token="a" * 64,
                candidate_id="R432",
                decision="empty_position",
                reason="generic caution is not enough",
                idempotency_key="ui:26112:deployment",
            ),
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )
```

Add explicit facade assertions:

```python
def test_select_candidate_records_named_rules(service) -> None:
    service.select_ticket_version(
        "zucai:26112",
        SelectTicketVersionCommand(
            expected_snapshot_token="a" * 64,
            candidate_id="R432",
            reason="采用 R432",
            deviations=[
                PrescriptionDeviationCommand(
                    match_no=12,
                    rule_ids=["q-两阶段"],
                    reason="丢场式减注登记",
                ),
                PrescriptionDeviationCommand(
                    match_no=13,
                    rule_ids=["处方优先"],
                    reason="双选覆盖已命名偏离",
                ),
            ],
            idempotency_key="candidate:1",
        ),
        actor_id="owner", actor_role=ActorRole.JUDGE_OPERATOR,
    )
    alternative = service.action_gateway.requests[-1].payload["alternative"]
    assert alternative == {
        "candidate_id": "R432",
        "deviation_registry": [
            {
                "match_no": 12,
                "rule_ids": ["q-两阶段"],
                "reason": "丢场式减注登记",
            },
            {
                "match_no": 13,
                "rule_ids": ["处方优先"],
                "reason": "双选覆盖已命名偏离",
            },
        ],
    }


def test_candidate_selection_requires_registration_for_every_actual_diff(service) -> None:
    with pytest.raises(ProductActionBlockedError, match="13.*偏离登记"):
        service.select_ticket_version(
            "zucai:26112",
            SelectTicketVersionCommand(
                expected_snapshot_token="a" * 64,
                candidate_id="R432",
                reason="漏了一处",
                deviations=[PrescriptionDeviationCommand(
                    match_no=12,
                    rule_ids=["q-两阶段"],
                    reason="只登记了场 12",
                )],
                idempotency_key="candidate:missing-diff",
            ),
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )


def test_stale_snapshot_token_writes_no_action(service) -> None:
    stale = VALID_SELECTION.model_copy(
        update={"expected_snapshot_token": "f" * 64}
    )
    with pytest.raises(ProductActionBlockedError, match="form was opened"):
        service.select_ticket_version(
            "zucai:26112",
            stale,
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )
    assert service.action_gateway.requests == []


@pytest.mark.parametrize("role", [ActorRole.AI_ANALYST, ActorRole.DETERMINISTIC_SYSTEM])
def test_non_judge_roles_cannot_mutate_operator_task(service, role) -> None:
    with pytest.raises(ProductActionBlockedError, match="judge_operator"):
        service.select_ticket_version(
            "zucai:26112", VALID_SELECTION,
            actor_id="not-owner", actor_role=role,
        )


def test_telegram_uses_bound_artifact_and_configured_owner(service_at_confirmation) -> None:
    service_at_confirmation.request_telegram_confirmation(
        "jczq:2026-08-28", TELEGRAM_COMMAND,
        actor_id="owner", actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert service_at_confirmation.telegram.calls[-1] == {
        "ticket_artifact_id": "tat-1", "chat_id": 111, "dry_run": True,
        "requested_at": NOW,
    }
```

Validate stale-step and missing-owner failures with `pytest.raises`. Validate actor, chat,
amount, and hash rejection by calling each Pydantic command's `model_validate` with the
extra field and asserting `ValidationError`. `VALID_SELECTION` and `TELEGRAM_COMMAND`
must carry the fake current task's exact `expected_snapshot_token`; a token changed by one
hex character must fail before either fake service records a call.

- [ ] **Step 2: Run facade tests and verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_actions.py -v
```

Expected: FAIL because `OperatorActionService` is absent.

- [ ] **Step 3: Add the dispatch response contract and action facade**

Append this contract to `operator_contracts.py`:

```python
class TelegramConfirmationDispatch(VersionedOperatorContract):
    ticket_artifact_id: str
    confirmation_id: str
    expires_at: AwareDatetime
    dispatch_state: Literal["dry_run", "sent"]
    message_preview: str
```

Implement the facade with server-supplied actor identity:

Import `DEVIATION_RULE_IDS` from `nutmeg.decision.legs_audit` and
`PrescriptionDeviationCommand` from the new operator contracts. The rule registry is the
same one used by the audit; the web layer must not maintain a duplicate list.

```python
class OperatorActionService:
    def __init__(
        self,
        *,
        queries: OperatorQueryService,
        action_gateway: ProductActionGateway,
        telegram_confirmation=None,
        telegram_owner_chat_id: int | None = None,
    ) -> None:
        self._queries = queries
        self._actions = action_gateway
        self._telegram = telegram_confirmation
        self._owner_chat_id = telegram_owner_chat_id

    def _current_task(self, task_id, expected_snapshot_token):
        task = self._queries.task(task_id, as_of=self._queries.now())
        if task.mutation_token != expected_snapshot_token:
            raise ProductActionBlockedError(
                "operator task changed after the form was opened"
            )
        return task

    def resolve_issue_adjudication(
        self, task_id, command, *, actor_id, actor_role
    ) -> ProductActionResponse:
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "judge_matches":
            raise ProductActionBlockedError("task is no longer awaiting adjudication")
        if task.step.item_key != command.adjudication_key:
            raise ProductActionBlockedError("adjudication is no longer current")
        issue = _zucai_issue(task_id)
        return self._execute_adjudication(
            issue=issue,
            decision=command.decision,
            reason=command.reason,
            evidence_rejected=command.evidence_rejected,
            alternative={
                "rx_adjudication_id": command.adjudication_key,
                "selected_option": command.selected_option,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def select_ticket_version(
        self, task_id, command, *, actor_id, actor_role
    ) -> ProductActionResponse:
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "construct_ticket":
            raise ProductActionBlockedError("task is no longer constructing a ticket")
        valid = {item.candidate_id for item in task.step.candidates}
        if command.candidate_id not in valid:
            raise ProductActionBlockedError("candidate is no longer available")
        candidate = next(
            item for item in task.step.candidates
            if item.candidate_id == command.candidate_id
        )
        expected_matches = {
            item.match_no for item in candidate.prescription_differences
        }
        submitted_matches = {item.match_no for item in command.deviations}
        if submitted_matches != expected_matches:
            missing = sorted(expected_matches - submitted_matches)
            extra = sorted(submitted_matches - expected_matches)
            raise ProductActionBlockedError(
                f"场 {missing} 缺少偏离登记或提交了额外场次 {extra}"
            )
        if any(
            rule_id not in DEVIATION_RULE_IDS
            for item in command.deviations
            for rule_id in item.rule_ids
        ):
            raise ProductActionBlockedError("处方偏离引用了未知规则 ID")
        registry = [
            {
                "match_no": item.match_no,
                "rule_ids": sorted(set(item.rule_ids)),
                "reason": item.reason,
            }
            for item in sorted(command.deviations, key=lambda item: item.match_no)
        ]
        return self._execute_adjudication(
            issue=_zucai_issue(task_id),
            decision="select_ticket",
            reason=command.reason,
            evidence_rejected=[],
            alternative={
                "candidate_id": command.candidate_id,
                "deviation_registry": registry,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def record_deployment(
        self, task_id, command, *, actor_id, actor_role
    ) -> ProductActionResponse:
        task = self._current_task(task_id, command.expected_snapshot_token)
        if task.step.kind != "audit_deployment":
            raise ProductActionBlockedError("task is no longer at deployment")
        if command.candidate_id != task.step.candidate.candidate_id:
            raise ProductActionBlockedError("deployment candidate changed")
        if command.decision not in task.step.allowed_decisions:
            raise ProductActionBlockedError(
                "deployment decision is not allowed by current gate"
            )
        return self._execute_adjudication(
            issue=_zucai_issue(task_id),
            decision="deployment",
            reason=command.reason,
            evidence_rejected=[],
            alternative={
                "candidate_id": command.candidate_id,
                "deployment_decision": command.decision,
                "deployment_state": task.step.deployment_state,
            },
            idempotency_key=command.idempotency_key,
            actor_id=actor_id,
            actor_role=actor_role,
        )
```

`_execute_adjudication` builds `ProductActionRequest(action_type="record_adjudication",
policy_version="governance-v1")` and delegates to the existing gateway. It explicitly
requires `ActorRole.JUDGE_OPERATOR` before delegation.

`request_telegram_confirmation` first calls
`_current_task(task_id, command.expected_snapshot_token)`, then requires a current
`ConfirmationStep`, configured service, and configured single owner ID before it calls:

```python
prepared = self._telegram.request_confirmation(
    ticket_artifact_id=task.step.ticket_artifact_id,
    chat_id=self._owner_chat_id,
    dry_run=command.dry_run,
    requested_at=self._queries.now(),
)
```

Map the prepared object explicitly; `to_public_dict()` contains `callback_bytes`, which
is also an internal transport detail and must not be passed through:

```python
return TelegramConfirmationDispatch(
    ticket_artifact_id=prepared.ticket_artifact_id,
    confirmation_id=prepared.confirmation_id,
    expires_at=_parse_aware(prepared.expires_at, "expires_at"),
    dispatch_state="dry_run" if command.dry_run else "sent",
    message_preview=prepared.text,
)
```

Never return callback data, callback length, or nonce.

- [ ] **Step 4: Wire operator services without importing CLI commands**

Extend `ProductServices` with `operator_queries` and `operator_actions`. Build the artifact
repository from `settings.data_dir / "zucai"`. Add a small local parser for configured
Telegram owner IDs in product wiring; do not import `nutmeg.interfaces.cli`.

```python
def _telegram_owner(raw: str | None) -> int | None:
    values = {int(item.strip()) for item in (raw or "").split(",") if item.strip()}
    return next(iter(values)) if len(values) == 1 else None
```

Only construct `TelegramTicketConfirmationService` when token and exactly one owner are
configured. Use `TelegramBotClient` as the transport and inject it into the service. Tests
pass a fake transport; no verification command performs a real dispatch.

- [ ] **Step 5: Write failing API security and route tests**

Test these routes and commands:

```text
GET  /api/v1/operator/tasks
GET  /api/v1/operator/tasks/{task_id}
POST /api/v1/operator/tasks/{task_id}/adjudications
POST /api/v1/operator/tasks/{task_id}/candidate
POST /api/v1/operator/tasks/{task_id}/deployment
POST /api/v1/operator/tasks/{task_id}/telegram-confirmation
```

For every POST, assert no cookie, no CSRF, wrong Origin, actor spoofing, stale step, and AI
actor paths fail. Assert OpenAPI contains each route and successful responses use strict
versioned contracts.

- [ ] **Step 6: Add the API endpoints using the existing mutation dependency**

Use `Depends(require_mutation_session)` and the server values
`services.settings.default_user_id` / `ActorRole.JUDGE_OPERATOR` exactly as
`/api/v1/actions` does. The browser body contains only the typed command.

```python
@app.get("/api/v1/operator/tasks")
async def operator_tasks(as_of: Annotated[datetime | None, Query()] = None):
    return services.operator_queries.worklist(as_of=as_of or now())


@app.post("/api/v1/operator/tasks/{task_id}/candidate")
async def select_operator_candidate(
    task_id: str,
    command: SelectTicketVersionCommand,
    _session: None = Depends(require_mutation_session),
):
    return services.operator_actions.select_ticket_version(
        task_id,
        command,
        actor_id=services.settings.default_user_id,
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
```

Do not create a generic reflection dispatcher. Add these exact handlers:

```python
@app.get("/api/v1/operator/tasks/{task_id}")
async def operator_task(
    task_id: str,
    as_of: Annotated[datetime | None, Query()] = None,
):
    return services.operator_queries.task(task_id, as_of=as_of or now())


@app.post("/api/v1/operator/tasks/{task_id}/adjudications")
async def resolve_operator_adjudication(
    task_id: str,
    command: ResolveIssueAdjudicationCommand,
    _session: None = Depends(require_mutation_session),
):
    return services.operator_actions.resolve_issue_adjudication(
        task_id,
        command,
        actor_id=services.settings.default_user_id,
        actor_role=ActorRole.JUDGE_OPERATOR,
    )


@app.post("/api/v1/operator/tasks/{task_id}/deployment")
async def record_operator_deployment(
    task_id: str,
    command: RecordDeploymentCommand,
    _session: None = Depends(require_mutation_session),
):
    return services.operator_actions.record_deployment(
        task_id,
        command,
        actor_id=services.settings.default_user_id,
        actor_role=ActorRole.JUDGE_OPERATOR,
    )


@app.post("/api/v1/operator/tasks/{task_id}/telegram-confirmation")
async def request_operator_telegram_confirmation(
    task_id: str,
    command: RequestTelegramConfirmationCommand,
    _session: None = Depends(require_mutation_session),
):
    return services.operator_actions.request_telegram_confirmation(
        task_id,
        command,
        actor_id=services.settings.default_user_id,
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
```

- [ ] **Step 7: Verify facade and API GREEN**

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_actions.py \
  tests/product/test_operator_api.py -v
```

Expected: all tests PASS; actor/chat/amount/hash fields are rejected by strict commands.

- [ ] **Step 8: Commit the governed boundary**

```bash
git add nutmeg/product/operator_contracts.py nutmeg/product/operator_actions.py \
  nutmeg/product/wiring.py nutmeg/interfaces/product_api.py \
  tests/product/test_operator_actions.py tests/product/test_operator_api.py
UV_FROZEN=1 git commit -m "feat(product): expose governed operator actions"
```

### Task 6: Focused Shell, Root Routing, and Maintenance Relocation

**Files:**
- Create: `nutmeg/interfaces/operator_ui.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Modify: `nutmeg/interfaces/product_ui.py`
- Create: `nutmeg/interfaces/web/templates/operator/layout.html`
- Create: `nutmeg/interfaces/web/templates/operator/task.html`
- Create: `nutmeg/interfaces/web/templates/operator/tasks.html`
- Create: `nutmeg/interfaces/web/templates/operator/system.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/waiting_data.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/prepare.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/blocked.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/complete.html`
- Create: `nutmeg/interfaces/web/static/product/operator.css`
- Create: `nutmeg/interfaces/web/static/product/operator.js`
- Create: `tests/product/test_operator_ui.py`

- [ ] **Step 1: Write failing root-shell tests**

```python
def test_root_opens_selected_task_without_system_chrome(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-workspace="operator-task"' in response.text
    assert "足彩 26112" in response.text
    assert "当前需要你处理" in response.text
    assert "Schema" not in response.text
    assert "Outbox" not in response.text
    assert "Action ID" not in response.text
    assert "本体浏览" not in response.text
    assert 'href="/tasks"' in response.text
    assert 'href="/system"' in response.text


def test_system_index_contains_old_tools_without_owning_root(client) -> None:
    system = client.get("/system")
    legacy = client.get("/system/command-center?date=2026-08-28")

    assert system.status_code == 200
    assert 'data-workspace="system-maintenance"' in system.text
    assert 'href="/system/command-center"' in system.text
    assert 'href="/system/operations"' in system.text
    assert 'href="/system/ontology"' in system.text
    assert legacy.status_code == 200
    assert 'data-workspace="command-center"' in legacy.text

    alias = client.get("/system/operations")
    compatibility = client.get("/operations")
    assert alias.status_code == compatibility.status_code == 200
    assert 'data-workspace="operations"' in alias.text
```

Use this parameterized shell coverage in the same test file:

```python
@pytest.mark.parametrize(
    ("fixture_name", "marker"),
    [
        ("no_tasks", 'data-empty-state="operator-tasks"'),
        ("waiting", 'data-step-kind="waiting_data"'),
        ("invalid_source", 'data-step-kind="blocked"'),
    ],
)
def test_root_designed_states(request, fixture_name, marker) -> None:
    client = request.getfixturevalue(fixture_name)
    response = client.get("/")
    assert response.status_code == 200
    assert marker in response.text


def test_shell_is_semantic_local_and_escaped(client) -> None:
    html = client.get("/").text
    assert 'class="skip-link" href="#main-content"' in html
    assert all(tag in html for tag in ("<header", "<nav", "<main"))
    assert 'href="/tasks"' in html
    assert '<script>alert("fixture")</script>' not in html
    assert not re.search(r'(?:src|href)="https?://', html)
```

- [ ] **Step 2: Run UI tests and verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py -v
```

Expected: root still renders the old command center and tests FAIL.

- [ ] **Step 3: Mount operator routes and relocate the old root**

Change only the old command-center decorator:

```python
@app.get("/system/command-center", include_in_schema=False)
async def command_center_page(
    request: Request,
    day: Annotated[date | None, Query(alias="date")] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    readiness: Annotated[ReadinessLevel | None, Query()] = None,
    competition: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(alias="q")] = None,
):
    cutoff = as_of or clock()
    selected_day = day or cutoff.astimezone(_SHANGHAI).date()
    command = services.queries.command_center(
        selected_day,
        as_of=cutoff,
        readiness=readiness,
        competition=competition,
        query=query,
    )
    return templates.TemplateResponse(
        request=request,
        name="product/command_center.html",
        context={
            "workspace": "command-center",
            "active_nav": "command-center",
            "command": command,
            "health": command.health,
            "alerts": command.alerts,
            "filters": {
                "date": selected_day.isoformat(),
                "readiness": readiness.value if readiness is not None else "",
                "competition": competition or "",
                "query": query or "",
            },
        },
    )
```

Add these exact decorators immediately above the corresponding existing legacy
decorators; do not change their function signatures or bodies:

```python
@app.get("/system/operations", include_in_schema=False)
@app.get("/system/release", include_in_schema=False)
@app.get("/system/tickets", include_in_schema=False)
@app.get("/system/review", include_in_schema=False)
@app.get("/system/calibration", include_in_schema=False)
@app.get("/system/ontology", include_in_schema=False)
@app.get("/system/matches/{match_id}", include_in_schema=False)
@app.get("/system/lineage/{object_type}/{object_id}", include_in_schema=False)
```

Each line belongs above the handler with the matching final path segment, not together as
one decorator stack. `operator/system.html` links only the `/system/*` forms.

Create `mount_operator_ui(app, services, clock)` with:

```python
@app.get("/", include_in_schema=False)
async def operator_root(request: Request):
    worklist = services.operator_queries.worklist(as_of=clock())
    if worklist.selected is None:
        return templates.TemplateResponse(
            request=request,
            name="operator/tasks.html",
            context={"workspace": "operator-tasks", "worklist": worklist},
        )
    task = services.operator_queries.task(
        worklist.selected.task_id, as_of=worklist.as_of
    )
    return _task_response(request, templates, task)


@app.get("/tasks", include_in_schema=False)
async def operator_tasks_page(request: Request):
    worklist = services.operator_queries.worklist(as_of=clock())
    return templates.TemplateResponse(
        request=request,
        name="operator/tasks.html",
        context={"workspace": "operator-tasks", "worklist": worklist},
    )


@app.get("/tasks/{task_id}", include_in_schema=False)
async def operator_task_page(request: Request, task_id: str):
    return _task_response(
        request, templates, services.operator_queries.task(task_id, as_of=clock())
    )
```

Mount `operator_ui` before `product_ui` at the end of `create_product_app`.

- [ ] **Step 4: Build the focused template shell**

`operator/layout.html` contains only the wordmark, selected task/deadline, compact task
switcher, progress line, main content, action feedback, and System link:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Nutmeg{% endblock %}</title>
    <link rel="icon" href="/assets/product/favicon.svg" type="image/svg+xml">
    <link rel="stylesheet" href="/assets/product/operator.css">
  </head>
  <body data-workspace="{{ workspace }}">
    <a class="skip-link" href="#main-content">跳到当前任务</a>
    <header class="operator-header">
      <a class="operator-wordmark" href="/">
        <img src="/assets/product/favicon.svg" alt="" width="28" height="28">
        <span>Nutmeg</span>
      </a>
      {% if task is defined %}
        <div class="operator-context">
          <strong>{{ task.selected.title }}</strong>
          <span>{{ task.selected.next_action_label }}</span>
        </div>
        <a class="task-switcher" href="/tasks">
          另外 {{ task.alternatives|length }} 项
        </a>
      {% endif %}
      <a class="system-link" href="/system" aria-label="系统维护">设置</a>
    </header>
    {% if task is defined %}
      <nav class="phase-line" aria-label="当前流程进度">
        <span>{{ task.progress.label }}</span>
        <strong>{{ task.progress.completed }} / {{ task.progress.total }}</strong>
      </nav>
    {% endif %}
    <main id="main-content" tabindex="-1">{% block content %}{% endblock %}</main>
    <p id="action-feedback" aria-live="polite"></p>
    <script src="/assets/product/operator.js" defer></script>
  </body>
</html>
```

`task.html` includes only the enum-controlled partial:

```jinja2
{% extends "operator/layout.html" %}
{% block content %}
  <section class="current-step" data-step-kind="{{ task.step.kind }}"
           data-snapshot-token="{{ task.mutation_token }}">
    {% include "operator/steps/" ~ task.step.kind ~ ".html" %}
  </section>
{% endblock %}
```

`system.html` links the existing maintenance routes and explicitly labels them as
diagnostics, not the daily workflow.

Create `operator.js` as a valid no-op shell so the asset exists before Task 7 adds
mutations:

```javascript
(() => {
  "use strict";
})();
```

- [ ] **Step 5: Add only shell-level CSS**

Define a white/charcoal/gray working surface with restrained green PASS, amber WARN, and
red ERROR accents rather than one dominant hue. Use fixed header/progress dimensions,
`max-width: 1180px`, visible focus, 44px controls, non-overlapping mobile layout, and
`overflow-wrap: anywhere` for source labels. Give the existing favicon image a stable
`28px` square and keep the wordmark visible in the first viewport. Do not add gradients,
decorative orbs, nested cards, viewport-scaled text, or duplicated styles from `app.css`.

- [ ] **Step 6: Verify root and maintenance GREEN**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  tests/product/test_m2_ui.py tests/product/test_m5_ui.py tests/product/test_m6_ui.py -v
```

Expected: operator shell tests PASS and existing maintenance UI tests remain green after
updating only assertions whose old command-center link is now `/system/command-center`.

- [ ] **Step 7: Commit the focused shell**

```bash
git add nutmeg/interfaces/operator_ui.py nutmeg/interfaces/product_api.py \
  nutmeg/interfaces/product_ui.py nutmeg/interfaces/web/templates/operator \
  nutmeg/interfaces/web/static/product/operator.css \
  nutmeg/interfaces/web/static/product/operator.js \
  tests/product/test_operator_ui.py tests/product/test_m2_ui.py \
  tests/product/test_m5_ui.py tests/product/test_m6_ui.py
UV_FROZEN=1 git commit -m "feat(product): open focused operator workbench"
```

### Task 7: Judgment and Ticket-Comparison States

**Files:**
- Create: `nutmeg/interfaces/web/templates/operator/steps/judge_matches.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/construct_ticket.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `tests/product/test_operator_ui.py`

- [ ] **Step 1: Write failing semantic UI and no-leak tests**

```python
def test_judgment_state_shows_business_evidence_and_one_action(client) -> None:
    html = client.get("/tasks/zucai:26112").text

    assert 'data-step-kind="judge_matches"' in html
    assert "当前需要你处理" in html
    assert "任九档位" in html
    assert "V288=72%帽内" in html
    assert html.count('class="primary-action"') == 1
    assert 'data-action="resolve-issue-adjudication"' in html
    assert 'name="actor_id"' not in html
    assert 'name="actor_role"' not in html
    assert "payload_json" not in html


def test_ticket_state_is_a_business_table_not_rx_json(client_with_resolved_adj) -> None:
    html = client_with_resolved_adj.get("/tasks/zucai:26112").text

    assert 'data-step-kind="construct_ticket"' in html
    assert "版本" in html and "注数" in html and "票价" in html
    assert "P(全对)" in html and "期望断腿" in html
    assert "R432" in html
    assert 'data-action="select-ticket-version"' in html
    assert "ticket_versions" not in html
    assert "human note; not parsed" not in html
    assert "{" not in html
```

Add this exact escaping/control test:

```python
def test_operator_forms_escape_content_and_require_governed_fields(client) -> None:
    html = client.get("/tasks/zucai:26112").text
    assert '<script>alert("fixture")</script>' not in html
    assert "&lt;script&gt;" in html
    assert 'name="reason"' in html
    assert 'name="selected_option"' in html
    assert "更新于" in html
    assert re.search(r'action-[0-9a-f]{8}', html) is None
    assert re.search(r'\b[0-9a-f]{64}\b', html) is None
    assert html.count('class="primary-action"') == 1
```

For the ticket state, assert every rendered prescription difference has
`data-deviation-match`, a required named-rule input, and a required per-match reason.
Candidate selection uses radio inputs rather than a free-form candidate ID. A candidate
with no prescription differences submits an empty `deviations` list.

- [ ] **Step 2: Verify UI tests fail**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  -k "judgment or ticket_state" -v
```

Expected: FAIL because the two step partials do not exist.

- [ ] **Step 3: Implement the judgment partial**

```jinja2
<div class="step-heading">
  <div>
    <span class="step-kicker">当前需要你处理 · {{ task.step.item_key }}</span>
    <h1>{{ task.step.title }}</h1>
    <p>{{ task.step.prompt }}</p>
  </div>
</div>

<div class="judgment-layout">
  <section class="evidence-list" aria-labelledby="evidence-title">
    <h2 id="evidence-title">本次判断所需数据</h2>
    {% for evidence in task.step.evidence %}
      <div class="evidence-row severity-{{ evidence.severity }}">
        <strong>{{ evidence.label }}</strong>
        <span>{{ evidence.value }}</span>
        <small>{{ evidence.source_label or "当前工作流" }}</small>
        {% if evidence.evidence_href %}
          <a href="{{ evidence.evidence_href }}">查看来源</a>
        {% endif %}
      </div>
    {% endfor %}
  </section>

  <form class="operator-form" data-action="resolve-issue-adjudication"
        data-task-id="{{ task.selected.task_id }}"
        data-adjudication-key="{{ task.step.item_key }}">
    <fieldset>
      <legend>记录你的裁决</legend>
      {% for option in task.step.options %}
        <label><input type="radio" name="selected_option" value="{{ option }}" required>
          <span>{{ option }}</span></label>
      {% endfor %}
    </fieldset>
    <label><span>裁决类型</span>
      <select name="decision" required>
        <option value="approve">确认</option>
        <option value="override">行权偏离</option>
        <option value="reject">拒绝</option>
      </select>
    </label>
    <label><span>理由</span><textarea name="reason" required></textarea></label>
    <button class="primary-action" type="submit">保存并进入下一步</button>
  </form>
</div>
```

If an rx option is one prose line, show it as one radio label and allow the operator to
enter the exact selected option in a separate text input. Do not split prose into inferred
choices.

- [ ] **Step 4: Implement the ticket-comparison partial**

Render a semantic table whose cells use only `TicketVersionSummary` fields. Below the
table, render one candidate radio group and one deviation fieldset per candidate. Every
`PrescriptionDifferenceSummary` row renders `场次 / 处方 / 候选`, a required
comma-separated named-rule input, and a required per-match reason. Hide and disable
fieldsets for unselected candidates so the browser cannot submit stale registrations.
Render one overall selection reason and the single primary button `采用并进入审计`.
Prescription faces render as a sorted list of `场次 -> 面`, not a Python/Jinja mapping
dump.

- [ ] **Step 5: Implement only form collection in `operator.js`**

Start with the same local session/CSRF pattern as product `app.js`, but keep this file
independent:

```javascript
async function postJson(url, payload) {
  const session = await fetch("/api/v1/session", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  }).then((response) => response.json());
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": session.csrf_token,
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || result.code);
  return result;
}
```

Map forms exactly:

```javascript
const snapshotToken = form.closest("[data-snapshot-token]").dataset.snapshotToken;

if (action === "resolve-issue-adjudication") {
  return submit(form, () => postJson(
    `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/adjudications`,
    {
      schema_version: "1",
      expected_snapshot_token: snapshotToken,
      adjudication_key: form.dataset.adjudicationKey,
      decision: values.get("decision"),
      reason: values.get("reason"),
      selected_option: values.get("selected_option") || values.get("option_text"),
      evidence_rejected: [],
      idempotency_key: `ui:operator:adjudication:${crypto.randomUUID()}`,
    },
  ));
}

if (action === "select-ticket-version") {
  const candidateId = values.get("candidate_id");
  const deviations = [...form.querySelectorAll(
    `[data-deviation-candidate="${CSS.escape(candidateId)}"]`
  )].map((row) => ({
    match_no: Number(row.dataset.deviationMatch),
    rule_ids: commaValues(
      row.querySelector("[data-deviation-rules]").value,
    ),
    reason: row.querySelector("[data-deviation-reason]").value,
  }));
  return submit(form, () => postJson(
    `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/candidate`,
    {
      schema_version: "1",
      expected_snapshot_token: snapshotToken,
      candidate_id: candidateId,
      reason: values.get("reason"),
      deviations,
      idempotency_key: `ui:operator:candidate:${crypto.randomUUID()}`,
    },
  ));
}
```

On candidate-radio `change`, enable only inputs inside the matching
`data-deviation-candidate` rows and set all other deviation inputs `disabled=true`. The
server independently checks exact diff match numbers and known rule IDs; browser state is
not an authority boundary.

`submit` disables only the current form, writes operator-readable feedback, and reloads
after a committed response. It must not show `action_id` to the operator.

- [ ] **Step 6: Assert JavaScript contains no domain arithmetic**

Test that `operator.js` contains the two operator endpoints and none of:

```text
optimize, p_all *, expected_broken =, audit_legs, deployment gate,
capital_utilization =, median_bonus =, odds *, fair *, priority
```

- [ ] **Step 7: Verify and commit the two states**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  tests/product/test_operator_api.py -v
git add nutmeg/interfaces/web/templates/operator/steps/judge_matches.html \
  nutmeg/interfaces/web/templates/operator/steps/construct_ticket.html \
  nutmeg/interfaces/web/static/product/operator.js \
  nutmeg/interfaces/web/static/product/operator.css tests/product/test_operator_ui.py
UV_FROZEN=1 git commit -m "feat(product): guide judgment and ticket comparison"
```

### Task 8: Audit and Deployment State

**Files:**
- Create: `nutmeg/interfaces/web/templates/operator/steps/audit_deployment.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `tests/product/test_operator_ui.py`
- Modify: `tests/product/test_operator_actions.py`

- [ ] **Step 1: Write failing gate rendering tests**

```python
def test_deployment_view_translates_gate_without_defaulting_empty(client_at_gate) -> None:
    html = client_at_gate.get("/tasks/zucai:26112").text

    assert 'data-step-kind="audit_deployment"' in html
    assert "票面审计" in html
    assert "资金使用率" in html
    assert "中位奖金" in html
    assert "回本/中位" in html
    assert "需要你的部署裁决" in html
    assert 'value="keep"' in html
    assert 'value="empty_position"' not in html
    assert "系统建议空仓" not in html
    assert html.count('class="primary-action"') == 1


def test_empty_position_appears_only_for_explicit_gate_failure(
    client_at_reduce_or_empty_gate,
) -> None:
    html = client_at_reduce_or_empty_gate.get("/tasks/zucai:26112").text

    assert 'value="empty_position"' in html
    assert "部署门未通过" in html


def test_deployment_decision_routes_without_inventing_an_artifact(deployment_e2e) -> None:
    changed = deployment_e2e.record("change_structure")
    assert changed.selected.state == "construct_ticket"
    assert deployment_e2e.ticket_artifact_count == 0

    empty = deployment_e2e.fresh().record("empty_position")
    assert empty.selected.state == "complete"
    assert empty.step.summary == "已明确裁决空仓；没有出票或入账"
    assert deployment_e2e.ticket_artifact_count == 0
```

Use a gate-state parameterization:

```python
@pytest.mark.parametrize(
    ("audit_state", "label"),
    [("pass", "PASS"), ("warn", "WARN"), ("error", "ERROR")],
)
def test_audit_labels_are_textual_and_findings_are_escaped(
    gate_client_factory, audit_state, label
) -> None:
    html = gate_client_factory(audit_state).get("/tasks/zucai:26112").text
    assert label in html
    assert "C8" in html
    assert 'href="/tasks/zucai:26112"' in html
    assert '<img src=x onerror=alert("finding")>' not in html
    assert '"exit_code"' not in html
```

- [ ] **Step 2: Verify the tests fail**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  -k "deployment or empty_position" -v
```

Expected: FAIL because the partial is absent.

- [ ] **Step 3: Implement server-rendered audit/deployment report**

Render three stable metric columns: ticket audit, funding cap, and payout structure. Map
`pass`, `warn/review`, and `error/reduce_or_empty` to text and icons, not color alone. List
every `BusinessEvidenceSummary` finding with rule code and business message.

The form must iterate only `task.step.allowed_decisions`:

```jinja2
<form class="operator-form" data-action="record-deployment"
      data-task-id="{{ task.selected.task_id }}"
      data-candidate-id="{{ task.step.candidate.candidate_id }}">
  <fieldset>
    <legend>需要你的部署裁决</legend>
    {% for decision in task.step.allowed_decisions %}
      <label>
        <input type="radio" name="decision" value="{{ decision }}" required>
        <span>{{ deployment_labels[decision] }}</span>
      </label>
    {% endfor %}
  </fieldset>
  <label><span>裁决理由</span><textarea name="reason" required></textarea></label>
  <button class="primary-action" type="submit">记录裁决并继续</button>
</form>
```

Pass `deployment_labels` from `operator_ui.py`; do not construct labels from codes in
Jinja.

- [ ] **Step 4: Add the deployment POST mapping**

```javascript
if (action === "record-deployment") {
  return submit(form, () => postJson(
    `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/deployment`,
    {
      schema_version: "1",
      expected_snapshot_token: snapshotToken,
      candidate_id: form.dataset.candidateId,
      decision: values.get("decision"),
      reason: values.get("reason"),
      idempotency_key: `ui:operator:deployment:${crypto.randomUUID()}`,
    },
  ));
}
```

- [ ] **Step 5: Verify and commit the deployment state**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  tests/product/test_operator_actions.py tests/decision/test_zucai_deployment.py \
  tests/decision/test_legs_audit.py -v
git add nutmeg/interfaces/web/templates/operator/steps/audit_deployment.html \
  nutmeg/interfaces/web/static/product/operator.js \
  nutmeg/interfaces/web/static/product/operator.css \
  tests/product/test_operator_ui.py tests/product/test_operator_actions.py
UV_FROZEN=1 git commit -m "feat(product): present governed deployment gate"
```

### Task 9: Telegram Confirmation, Ledger, and Await-Result States

**Files:**
- Create: `nutmeg/interfaces/web/templates/operator/steps/await_confirmation.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/await_ledger.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/await_result.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `tests/product/test_operator_ui.py`
- Modify: `tests/product/test_operator_e2e.py`

- [ ] **Step 1: Write failing confirmation and ledger UI tests**

```python
def test_confirmation_state_has_one_owner_dispatch_action(client_with_artifact) -> None:
    html = client_with_artifact.get("/tasks/jczq:2026-08-28").text

    assert 'data-step-kind="await_confirmation"' in html
    assert "票面与金额已锁定" in html
    assert "Telegram 本人确认" in html
    assert "入账确认" in html
    assert 'data-action="request-telegram-confirmation"' in html
    assert "ConfirmDispatch" not in html
    assert "nonce" not in html
    assert "ticket_hash" not in html


def test_shadow_is_explained_as_not_placed(client_with_shadow) -> None:
    html = client_with_shadow.get("/tasks/jczq:2026-08-28").text

    assert "未确认，按未出票处理" in html
    assert "没有入账" in html
    assert "ticket_shadow_records" not in html
```

Use exact confirmation-state assertions:

```python
@pytest.mark.parametrize(
    ("state", "text", "has_send"),
    [
        ("not_issued", "发送 Telegram 本人确认", True),
        ("open", "等待你在 Telegram 点击", False),
        ("expired", "确认已过期", True),
    ],
)
def test_confirmation_states(confirmation_client, state, text, has_send) -> None:
    html = confirmation_client(state).get("/tasks/jczq:2026-08-28").text
    assert text in html
    assert ('data-action="request-telegram-confirmation"' in html) is has_send
    assert "receipt_content" not in html


def test_await_result_refreshes_without_exposing_ledger_payload(await_result_client) -> None:
    html = await_result_client.get("/tasks/jczq:2026-08-28").text
    assert 'data-auto-refresh="waiting"' in html
    assert "预计结果时间" in html
    assert "cash_transactions" not in html
```

- [ ] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_ui.py \
  -k "confirmation or shadow or await_result" -v
```

Expected: FAIL because the partials are absent.

- [ ] **Step 3: Implement confirmation timeline and explicit send**

The confirmation partial renders three ordered status rows and one primary button only
when confirmation is absent/expired:

```jinja2
<form data-action="request-telegram-confirmation"
      data-task-id="{{ task.selected.task_id }}">
  <button class="primary-action" type="submit">发送 Telegram 本人确认</button>
  <small>点击仅发送确认按钮，不代表已经出票或入账。</small>
</form>
```

An open challenge renders expiry and `等待你在 Telegram 点击`; it has no browser-side
placement button. A placed ticket renders amount/reference from the formal placement and
cash transaction. A shadow renders `未确认，按未出票处理`.

- [ ] **Step 4: Add Telegram dispatch and waiting refresh**

```javascript
if (action === "request-telegram-confirmation") {
  return submit(form, () => postJson(
    `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}`
      + "/telegram-confirmation",
    {
      schema_version: "1",
      expected_snapshot_token: snapshotToken,
      dry_run: false,
      idempotency_key: `ui:operator:telegram:${crypto.randomUUID()}`,
    },
  ));
}

const waiting = document.querySelector("[data-auto-refresh='waiting']");
if (waiting) window.setTimeout(() => window.location.reload(), 15000);
```

Verification tests inject a fake Telegram client and assert a message; they never use the
production token or network.

- [ ] **Step 5: Add an end-to-end protected transition test**

Use existing M4 helpers to create/approve one ticket artifact. Render the operator page,
POST Telegram dry-run, feed the callback to `TelegramBotRunner`, reload, and assert:

```python
assert before.step.kind == "await_confirmation"
assert dispatch.status_code == 200
assert after.step.kind == "await_result"
assert kernel_ticket_count == 1
assert cash_transaction_count == 1
assert ledger_balance == -artifact.amount
assert confirm_action_role == "judge_operator"
```

Create a sibling artifact, advance past its deadline, call existing `expire_due`, and
assert the page says not placed while Ticket/CashTransaction counts do not increase.

- [ ] **Step 6: Verify and commit the protected flow UI**

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_ui.py \
  tests/product/test_operator_e2e.py \
  tests/ontology/test_telegram_confirmation_e2e.py -v
git add nutmeg/interfaces/web/templates/operator/steps/await_confirmation.html \
  nutmeg/interfaces/web/templates/operator/steps/await_ledger.html \
  nutmeg/interfaces/web/templates/operator/steps/await_result.html \
  nutmeg/interfaces/web/static/product/operator.js \
  nutmeg/interfaces/web/static/product/operator.css \
  tests/product/test_operator_ui.py tests/product/test_operator_e2e.py
UV_FROZEN=1 git commit -m "feat(product): surface protected confirmation lifecycle"
```

### Task 10: Settlement Review and Judge-Only Prediction Grading

**Files:**
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/actions.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/review.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `tests/product/test_operator_actions.py`
- Modify: `tests/product/test_operator_api.py`
- Modify: `tests/product/test_operator_ui.py`
- Modify: `tests/product/test_operator_e2e.py`

- [ ] **Step 1: Write failing grade permission and transition tests**

```python
def test_grade_current_prediction_commits_as_judge_operator(review_service) -> None:
    result = review_service.grade_prediction(
        "zucai:26112",
        GradePredictionCommand(
            expected_snapshot_token="a" * 64,
            prediction_id="prediction-p1",
            outcome="hit",
            reason="Official 90-minute result satisfies the registered claim",
            idempotency_key="ui:26112:grade:p1",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert result.status == "committed"
    assert review_service.action_gateway.requests[-1].action_type == "grade_prediction"


def test_ai_cannot_grade_prediction(review_service) -> None:
    with pytest.raises(ProductActionBlockedError, match="judge_operator"):
        review_service.grade_prediction(
            "zucai:26112",
            GradePredictionCommand(
                expected_snapshot_token="a" * 64,
                prediction_id="prediction-p1", outcome="miss", reason="AI guess",
                idempotency_key="ai:grade",
            ),
            actor_id="model:test",
            actor_role=ActorRole.AI_ANALYST,
        )
```

Implement the transition assertion directly:

```python
def test_grading_advances_one_review_item_at_a_time(review_e2e) -> None:
    first = review_e2e.queries.task("zucai:26112", as_of=NOW)
    assert first.step.current_item.item_id == "prediction-p1"
    review_e2e.actions.grade_prediction(
        "zucai:26112", grade("prediction-p1", "hit", first.mutation_token),
        actor_id="owner", actor_role=ActorRole.JUDGE_OPERATOR,
    )
    second = review_e2e.queries.task("zucai:26112", as_of=NOW)
    assert second.step.current_item.item_id == "prediction-p2"
    review_e2e.actions.grade_prediction(
        "zucai:26112", grade("prediction-p2", "miss", second.mutation_token),
        actor_id="owner", actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert review_e2e.queries.task(
        "zucai:26112", as_of=NOW
    ).selected.state == "complete"
```

Use a rejecting fake gateway in a second test and assert `prediction-p1` remains current.

- [ ] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_actions.py \
  tests/product/test_operator_e2e.py -k "grade or review" -v
```

Expected: FAIL because the command and gateway action are absent.

- [ ] **Step 3: Add strict grade command and Product Action support**

```python
class GradePredictionCommand(OperatorMutationCommand):
    prediction_id: str = Field(min_length=1)
    outcome: Literal["hit", "miss", "na"]
    reason: str = Field(min_length=1)
```

In `nutmeg/product/actions.py`, import `GradePredictionRequest`, add
`"grade_prediction"` to `_ALLOWED_ACTIONS`, and add this branch before the proposal
fallback in `_execute_workflow`:

```python
if request.action_type == "grade_prediction":
    return self._kernel.workflow.grade_prediction(
        GradePredictionRequest(
            prediction_id=_required_str(payload, "prediction_id"),
            outcome=_required_str(payload, "outcome"),
            reason=_required_str(payload, "reason"),
            **common,
        )
    )
```

The ontology permission remains the authority; do not add or modify any permission row.

- [ ] **Step 4: Add current-review validation in the operator facade**

```python
def grade_prediction(self, task_id, command, *, actor_id, actor_role):
    if actor_role is not ActorRole.JUDGE_OPERATOR:
        raise ProductActionBlockedError("prediction grade requires judge_operator")
    task = self._current_task(task_id, command.expected_snapshot_token)
    if task.step.kind != "review":
        raise ProductActionBlockedError("task is no longer in review")
    current = task.step.current_item
    if current.item_type != "prediction" or current.item_id != command.prediction_id:
        raise ProductActionBlockedError("prediction is no longer the current review item")
    return self._actions.execute(
        ProductActionRequest(
            action_type="grade_prediction",
            idempotency_key=command.idempotency_key,
            payload={
                "prediction_id": command.prediction_id,
                "outcome": command.outcome,
                "reason": command.reason,
            },
        ),
        actor_id=actor_id,
        actor_role=actor_role,
    )
```

Expose the grade through the mutation session dependency:

```python
@app.post("/api/v1/operator/tasks/{task_id}/grade-prediction")
async def grade_operator_prediction(
    task_id: str,
    command: GradePredictionCommand,
    _session: None = Depends(require_mutation_session),
):
    return services.operator_actions.grade_prediction(
        task_id,
        command,
        actor_id=services.settings.default_user_id,
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
```

- [ ] **Step 5: Implement the review view and POST mapping**

The partial shows hit/total, stake, payout, P/L, night-calibration summary, then exactly
one `ReviewItemSummary`. For predictions, render claim/falsifier evidence and radio
outcomes `hit`, `miss`, `na` with a required reason. Do not show outcome probabilities or
preselect a grade.

```javascript
if (action === "grade-prediction") {
  return submit(form, () => postJson(
    `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}`
      + "/grade-prediction",
    {
      schema_version: "1",
      expected_snapshot_token: snapshotToken,
      prediction_id: form.dataset.predictionId,
      outcome: values.get("outcome"),
      reason: values.get("reason"),
      idempotency_key: `ui:operator:grade:${crypto.randomUUID()}`,
    },
  ));
}
```

If the current review item is an Adjudication or FactorVerdict, render its evidence and a
link to the existing governed maintenance control until a dedicated typed command exists.
Do not add a generic write form.

- [ ] **Step 6: Verify grade API, UI, permissions, and transitions**

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_actions.py \
  tests/product/test_operator_api.py \
  tests/product/test_operator_ui.py \
  tests/product/test_operator_e2e.py \
  tests/ontology/test_workflow_actions.py -v
```

Expected: all tests PASS; direct AI facade calls and spoofed API bodies fail.

- [ ] **Step 7: Commit the review slice**

```bash
git add nutmeg/product/operator_contracts.py nutmeg/product/actions.py \
  nutmeg/product/operator_actions.py nutmeg/interfaces/product_api.py \
  nutmeg/interfaces/web/templates/operator/steps/review.html \
  nutmeg/interfaces/web/static/product/operator.js \
  nutmeg/interfaces/web/static/product/operator.css \
  tests/product/test_operator_actions.py tests/product/test_operator_api.py \
  tests/product/test_operator_ui.py tests/product/test_operator_e2e.py
UV_FROZEN=1 git commit -m "feat(product): guide judge-only postmatch review"
```

### Task 11: Formatted Evidence, Waiting Recovery, and Error Translation

**Files:**
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/interfaces/operator_ui.py`
- Create: `nutmeg/interfaces/web/templates/operator/evidence.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/waiting_data.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/prepare.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/blocked.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `tests/product/test_operator_queries.py`
- Modify: `tests/product/test_operator_ui.py`

- [ ] **Step 1: Write failing recovery and evidence tests**

```python
@pytest.mark.parametrize(
    ("code", "missing", "impact", "action"),
    [
        ("odds_snapshot_stale", "赔率快照已过期", "不能冻结当前判断", "刷新数据"),
        ("identity_unresolved", "比赛身份未对齐", "不能构票", "打开身份维护"),
        ("ticket_audit_blocked", "票面存在 ERROR", "不能提交确认", "返回调整票面"),
        ("confirmation_expired", "Telegram 确认已过期", "尚未入账", "重新发送确认"),
        ("projection_stale", "记分投影已过期", "暂不能复盘", "重建投影"),
    ],
)
def test_recovery_answers_four_operator_questions(
    recovery_client, code, missing, impact, action
) -> None:
    html = recovery_client(code).get("/").text
    assert missing in html
    assert impact in html
    assert action in html
    assert "现在可以" in html
    assert "Traceback" not in html
```

Write an evidence test requesting
`/tasks/zucai:26112/evidence/prep-match-1`. Assert formatted labels, source, freshness,
and probability values appear while internal object IDs, arbitrary properties, JSON
braces, and SQL do not.

- [ ] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_queries.py \
  tests/product/test_operator_ui.py -k "recovery or evidence" -v
```

Expected: FAIL because the detail contract/route is absent and the initial partials lack
the required recovery language.

- [ ] **Step 3: Add typed evidence-detail contracts**

```python
class EvidenceFieldSummary(StrictOperatorContract):
    label: str
    value: str


class OperatorEvidenceResponse(VersionedOperatorContract):
    task_id: str
    evidence_key: str
    title: str
    source_label: str
    observed_at: AwareDatetime | None = None
    freshness_label: str | None = None
    fields: list[EvidenceFieldSummary]
    audit_href: str | None = None
```

Add `OperatorQueryService.evidence(task_id, evidence_key, as_of)` with an explicit
allowlist:

```python
match = re.fullmatch(r"prep-match-(\d{1,2})", evidence_key)
if match:
    record = bundle.match_record(int(match.group(1)))
    if record is None:
        raise ProductNotFoundError("operator evidence not found")
    return _prep_evidence(task_id, evidence_key, record, bundle.prep.captured_at)
if evidence_key == "rx-capital":
    return _capital_evidence(task_id, bundle.rx)
raise ProductNotFoundError("operator evidence not found")
```

`_prep_evidence` constructs a fixed list of label/value rows. It never iterates over a
source model's `model_dump()`.

- [ ] **Step 4: Add the evidence route and stable error rendering**

```python
@app.get("/tasks/{task_id}/evidence/{evidence_key}", include_in_schema=False)
async def operator_evidence_page(request: Request, task_id: str, evidence_key: str):
    detail = services.operator_queries.evidence(
        task_id, evidence_key, as_of=clock()
    )
    return templates.TemplateResponse(
        request=request,
        name="operator/evidence.html",
        context={"workspace": "operator-evidence", "detail": detail},
    )
```

Catch only `OperatorArtifactError` in task discovery and convert it into a `BlockedStep`
with `source_contract_invalid`. Let `ProductNotFoundError` keep its 404. For unexpected UI
exceptions, generate `err-<uuid>` and render a blocked page with the correlation ID; log
the exception server-side and never render its text.

- [ ] **Step 5: Implement all four recovery statements in partials**

Each waiting/prepare/blocked partial renders:

```jinja2
<dl class="recovery-ledger">
  <div><dt>缺少或失败</dt><dd>{{ task.step.recovery.missing }}</dd></div>
  <div><dt>影响</dt><dd>{{ task.step.recovery.impact }}</dd></div>
  <div><dt>现在可以</dt><dd>{{ task.step.recovery.action_label }}</dd></div>
  <div><dt>重试</dt><dd>
    {{ task.step.recovery.retry_at or "完成上项后可立即重试" }}
  </dd></div>
</dl>
```

Recovery links may point to the relevant operator step or `/system/...`; no link executes
a destructive or privileged operation.

- [ ] **Step 6: Verify no raw structures leak**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_queries.py \
  tests/product/test_operator_ui.py -v
```

Expected: PASS. Scan rendered normal workflow pages in the test for `<pre>`, JSON braces,
`schema_version`, `action_id`, `content_hash`, `forecast_revision_id`, and `Traceback`.

- [ ] **Step 7: Commit evidence and recovery**

```bash
git add nutmeg/product/operator_contracts.py nutmeg/product/operator_queries.py \
  nutmeg/interfaces/operator_ui.py \
  nutmeg/interfaces/web/templates/operator/evidence.html \
  nutmeg/interfaces/web/templates/operator/steps/waiting_data.html \
  nutmeg/interfaces/web/templates/operator/steps/prepare.html \
  nutmeg/interfaces/web/templates/operator/steps/blocked.html \
  nutmeg/interfaces/web/static/product/operator.css \
  tests/product/test_operator_queries.py tests/product/test_operator_ui.py
UV_FROZEN=1 git commit -m "feat(product): explain evidence and recovery states"
```

### Task 12: Responsive Playwright Acceptance

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/product/test_operator_browser.py`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`

- [ ] **Step 1: Add Playwright as a dev dependency**

```bash
uv add --dev 'playwright>=1.51,<2'
uv run playwright install chromium
```

Expected: `pyproject.toml` and `uv.lock` change; Chromium installs locally. Do not add a
runtime browser dependency.

- [ ] **Step 2: Write a failing live-browser test fixture**

```python
import re
import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def browser_page(operator_app):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        operator_app, host="127.0.0.1", port=port, log_level="error"
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.01)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        yield page, f"http://127.0.0.1:{port}"
        browser.close()
    server.should_exit = True
    thread.join(timeout=5)
```

- [ ] **Step 3: Add desktop/mobile workflow and layout assertions**

```python
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_current_task_has_no_overlap_or_horizontal_escape(
    browser_page, width, height
) -> None:
    page, base_url = browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/", wait_until="networkidle")

    assert page.locator("[data-workspace='operator-task']").count() == 1
    assert page.locator(".primary-action").count() == 1
    assert page.locator("pre").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    header = page.locator(".operator-header").bounding_box()
    main = page.locator("#main-content").bounding_box()
    assert header and main and header["y"] + header["height"] <= main["y"]


def test_keyboard_and_mutation_progress(browser_page) -> None:
    page, base_url = browser_page
    page.goto(base_url + "/")
    page.keyboard.press("Tab")
    assert page.locator(":focus").get_attribute("href") == "#main-content"
    page.locator("input[name='selected_option']").first.check()
    page.locator("textarea[name='reason']").fill("browser fixture judgment")
    page.locator("button.primary-action").click()
    page.wait_for_load_state("networkidle")
    assert page.locator("[data-step-kind='construct_ticket']").count() == 1
```

Save and inspect screenshots with concrete assertions:

```python
page.screenshot(path=str(tmp_path / f"operator-{width}x{height}.png"), full_page=True)
button_height = page.locator(".primary-action").bounding_box()["height"]
assert button_height >= 44
assert int(page.locator("h1").evaluate(
    "node => parseFloat(getComputedStyle(node).fontSize)"
)) <= 36
assert page.locator(".evidence-list").evaluate(
    "node => node.compareDocumentPosition(document.querySelector('.operator-form'))"
) & 4
assert not re.search(
    r"schema|outbox|action_id|content_hash", page.locator("body").inner_text(), re.I
)
```

- [ ] **Step 4: Run browser tests and fix CSS/JS only from evidence**

```bash
UV_FROZEN=1 uv run pytest tests/product/test_operator_browser.py -v
```

Expected: PASS in Chromium at 1440x900 and 390x844. Inspect the saved screenshots before
declaring GREEN. Do not change domain/query behavior to solve a layout failure.

- [ ] **Step 5: Commit browser coverage**

```bash
git add pyproject.toml uv.lock tests/product/test_operator_browser.py \
  nutmeg/interfaces/web/static/product/operator.css \
  nutmeg/interfaces/web/static/product/operator.js
UV_FROZEN=1 git commit -m "test(product): cover operator workbench in browser"
```

### Task 13: Production-Shaped Replay, Regression, and Handoff Evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-08-28-phase-aware-operator-workbench.md`
- Modify: `docs/superpowers/specs/2026-08-28-phase-aware-operator-workbench-design.md`

- [ ] **Step 1: Run the complete focused operator suite**

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_contracts.py \
  tests/product/test_operator_artifacts.py \
  tests/product/test_operator_state.py \
  tests/product/test_operator_queries.py \
  tests/product/test_operator_actions.py \
  tests/product/test_operator_api.py \
  tests/product/test_operator_ui.py \
  tests/product/test_operator_e2e.py \
  tests/product/test_operator_browser.py -q
```

Expected: all operator tests PASS with zero warnings that indicate unawaited work or leaked
resources.

- [ ] **Step 2: Run affected domain and legacy product regressions**

```bash
UV_FROZEN=1 uv run pytest \
  tests/decision/test_zucai_optimizer.py \
  tests/decision/test_zucai_deployment.py \
  tests/decision/test_legs_audit.py \
  tests/ontology/test_workflow_actions.py \
  tests/ontology/test_protected_ticket_actions.py \
  tests/ontology/test_telegram_confirmation_e2e.py \
  tests/product/ -q
```

Expected: PASS. Existing maintenance routes, protected Actions, and product APIs retain
their behavior.

- [ ] **Step 3: Run repository quality gates**

```bash
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall nutmeg tests
UV_FROZEN=1 uv run pytest \
  tests/decision/ tests/ontology/ tests/product/ tests/analytics/ tests/migration/ -q
UV_FROZEN=1 uv run pre-commit run --all-files
```

Expected: every command exits 0. Record exact test totals in the evidence document.

- [ ] **Step 4: Perform a read-only production-shaped 26112 smoke**

Start a separate local server; this command must not dispatch Telegram or POST actions:

```bash
NUTMEG_DATA_DIR=.nutmeg-data uv run nutmeg app --host 127.0.0.1 --port 8790
```

In another shell:

```bash
curl -fsS http://127.0.0.1:8790/ | rg "26112|当前需要你处理"
curl -fsS http://127.0.0.1:8790/api/v1/operator/tasks | \
  uv run python -m json.tool
curl -fsS http://127.0.0.1:8790/system/command-center?date=2026-08-28 \
  -o /dev/null -w '%{http_code}\n'
```

Expected: root identifies 26112 and its current action, the operator API is valid JSON,
and the maintenance command center returns `200`. Use the browser at desktop and mobile
sizes to confirm the real data is readable and no JSON/ID/schema health strip appears.

- [ ] **Step 5: Record evidence and mark the design implemented**

The evidence file contains:

```markdown
# Phase-Aware Operator Workbench Evidence

- Branch and commit list
- Focused and full test commands with exact passing totals
- 26112 selected task, state, deadline source, and current-action excerpt
- Browser viewport/screenshot paths and overlap checks
- Telegram fake-client E2E counts: one placement/ledger and one sibling shadow
- Confirmation that no production POST, Telegram dispatch, scoreboard write, cutover,
  launchd change, or automated ticket placement occurred
- Every implementation deviation from the approved design and its reason
```

Change the design status to `Implemented and verified on feature branch; awaiting Jun's
merge decision` only after all preceding commands pass.

- [ ] **Step 6: Commit final evidence**

```bash
git add docs/superpowers/evidence/2026-08-28-phase-aware-operator-workbench.md \
  docs/superpowers/specs/2026-08-28-phase-aware-operator-workbench-design.md
UV_FROZEN=1 git commit -m "docs(product): record operator workbench verification"
```

- [ ] **Step 7: Keep the acceptance server running and report the URL**

If port 8790 is occupied, select another explicit loopback port. Report the final URL,
branch name, commits, exact test totals, real 26112 output excerpt, and all deviations.
Do not merge, push, cut over scoreboard authority, restore launchd, or perform a real
Telegram/funds action without Jun's separate instruction.
