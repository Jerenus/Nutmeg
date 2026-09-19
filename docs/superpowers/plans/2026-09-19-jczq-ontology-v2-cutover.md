# JCZQ Ontology v2 Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ontology v2 the sole authority for the daily JCZQ A2-A7 workflow, with durable research history, committed per-match judgments, four odds-band candidate iteration, audited selection/no-ticket terminal state, settlement learning, and an isolated 2026-09-19 replay gate.

**Architecture:** Add small coordination and projection modules around the existing operator and RSI Actions; do not duplicate evidence, Forecast, experiment, candidate, audit, selection, placement, or settlement rules. Preserve the two canonical candidate set kinds, put Dream-RSI parent/delta lineage on Candidate Set Revisions, and add odds-band metadata to candidates. Make every legacy JSON file an ontology-derived compatibility view and gate authority cutover behind an isolated replay report.

**Tech Stack:** Python 3.12, Typer, SQLAlchemy/SQLite migrations, Pydantic product contracts, pytest, Ruff, existing Nutmeg ontology/operator Actions.

---

## File Structure

- Create `nutmeg/decision/research_ledger.py`: immutable filesystem run/attempt ledger and daily projection.
- Modify `nutmeg/decision/research_runner.py`: append ledger events instead of overwriting history.
- Modify `nutmeg/interfaces/cli/research.py`: expose run history/status without changing the research runner contract.
- Modify `nutmeg/ontology/operator/models.py`: add candidate odds-band and iteration fields.
- Modify `nutmeg/ontology/repository/schema_operator_result.py`: declare the additive candidate columns and no-feasible table.
- Modify `nutmeg/ontology/repository/migrations.py`: add the next gap-free migration.
- Modify `nutmeg/ontology/operator/result_actions.py`: validate and persist odds-band/iteration metadata and no-feasible outcomes.
- Modify `nutmeg/ontology/repository/operator_result.py`: read current band outcomes and iteration lineage.
- Modify `nutmeg/product/operator_candidates.py`: classify deterministic candidates into four odds bands.
- Create `nutmeg/product/jczq_board_workflow.py`: coordinate board terminal states, evidence, Forecast, prescription, candidates, audits, and terminal decision Actions.
- Create `nutmeg/product/jczq_compatibility.py`: project reads/legs/handoff from ontology state.
- Create `nutmeg/product/jczq_replay.py`: isolated replay runner and acceptance report.
- Modify `nutmeg/product/operator_contracts.py`: expose board workflow, band, terminal-state, and replay report views.
- Modify `nutmeg/product/operator_queries.py`: query authoritative board progress and terminal state.
- Modify `nutmeg/product/operator_actions.py`: expose product commands for orchestration and authority cutover.
- Modify `nutmeg/interfaces/cli/workflow.py`: add board status/replay/cutover commands.
- Modify `scripts/openclaw/nutmeg_command_router.py`: route supported JCZQ operations to product Actions only.
- Modify `scripts/openclaw/nutmeg_scheduler_ops.py`: stop accepting legacy JSON as close authority.
- Modify `docs/sop/RUNBOOK.md`: replace A2-A7 legacy commands with v2 commands and gates.
- Test in focused new files under `tests/decision/`, `tests/ontology/operator/`, and `tests/product/operator_v2/`, plus existing CLI/router tests.

### Task 1: Append-only research run ledger

**Files:**
- Create: `nutmeg/decision/research_ledger.py`
- Modify: `nutmeg/decision/research_runner.py`
- Modify: `nutmeg/interfaces/cli/research.py`
- Test: `tests/decision/test_research_ledger.py`
- Test: `tests/decision/test_research_runner.py`
- Test: `tests/test_cli_research.py`

- [ ] **Step 1: Write failing ledger tests**

```python
def test_two_runs_append_attempts_and_daily_projection_keeps_both(tmp_path):
    ledger = ResearchRunLedger(tmp_path)
    first = ledger.append_run(_run("run-1", "周六001", "done"))
    second = ledger.append_run(_run("run-2", "周六029", "done"))

    assert first.run_id != second.run_id
    assert [row.run_id for row in ledger.runs("2026-09-19")] == ["run-1", "run-2"]
    assert {row.code for row in ledger.daily_projection("2026-09-19").matches} == {
        "周六001",
        "周六029",
    }


def test_replaying_same_idempotency_key_does_not_append(tmp_path):
    ledger = ResearchRunLedger(tmp_path)
    first = ledger.append_run(_run("run-1", "周六001", "done"))
    replay = ledger.append_run(_run("run-1", "周六001", "done"))
    assert replay == first
    assert len(ledger.runs("2026-09-19")) == 1
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/decision/test_research_ledger.py tests/decision/test_research_runner.py tests/test_cli_research.py -q`

Expected: FAIL because `ResearchRunLedger` and history projection do not exist.

- [ ] **Step 3: Implement the ledger and integrate the runner**

```python
@dataclass(frozen=True, slots=True)
class ResearchRunRecord:
    run_id: str
    idempotency_key: str
    day: str
    budget: int
    concurrency: int
    started_at: str
    finished_at: str
    matches: tuple[ResearchAttemptRecord, ...]


class ResearchRunLedger:
    def __init__(self, day_dir: Path) -> None:
        self._runs_dir = day_dir / "research-runs"

    def append_run(self, run: ResearchRunRecord) -> ResearchRunRecord:
        path = self._runs_dir / f"{run.idempotency_key}.json"
        if path.exists():
            return _decode_run(json.loads(path.read_text(encoding="utf-8")))
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(path, asdict(run))
        return run
```

Store one immutable JSON file per run under `daily/<day>/research-runs/` using a
stable idempotency key. Continue writing `research-run-<day>.json`, but derive it
from the full ledger rather than the latest invocation. `runs(day)` sorts decoded
records by `(started_at, run_id)`; `daily_projection(day)` folds attempts by board
code while retaining every run id and attempt.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/decision/test_research_ledger.py tests/decision/test_research_runner.py tests/test_cli_research.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/research_ledger.py nutmeg/decision/research_runner.py nutmeg/interfaces/cli/research.py tests/decision/test_research_ledger.py tests/decision/test_research_runner.py tests/test_cli_research.py
git commit -m "feat(research): preserve immutable JCZQ run history"
```

### Task 2: Candidate odds-band and Dream-RSI iteration ontology

**Files:**
- Modify: `nutmeg/ontology/operator/models.py`
- Modify: `nutmeg/ontology/repository/schema_operator_result.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/operator/result_actions.py`
- Modify: `nutmeg/ontology/repository/operator_result.py`
- Test: `tests/ontology/operator/test_candidate_band_migration.py`
- Test: `tests/ontology/operator/test_candidate_actions.py`

- [ ] **Step 1: Write failing migration and Action tests**

```python
def test_candidate_persists_odds_band_and_set_revision_persists_parent_delta(kernel):
    outcome = generate_candidates(
        kernel,
        candidate=_candidate(
            odds_band="20x",
            combined_decimal_odds="19.800000000000",
        ),
        supersedes_candidate_set_revision_id="candidate-set-parent",
        change_delta={"replace_leg": "周六029"},
        rationale="replace stale away leg",
    )
    row = candidate_row(kernel, outcome.result_refs[0].object_id)
    assert row.odds_band == "20x"
    assert row.combined_decimal_odds == "19.800000000000"
    revision = current_candidate_set_revision(kernel, row.candidate_set_revision_id)
    assert revision.supersedes_revision_id == "candidate-set-parent"
    assert revision.change_delta == {"replace_leg": "周六029"}
    assert revision.rationale == "replace stale away leg"


def test_generation_requires_one_outcome_for_every_band(kernel):
    request = _request(candidate_sets=_sets_missing_band("100x"))
    with pytest.raises(ValueError, match="one outcome for every odds band"):
        actions.generate_ticket_candidate_set(request)
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/ontology/operator/test_candidate_band_migration.py tests/ontology/operator/test_candidate_actions.py -q`

Expected: FAIL because the schema and request types lack band metadata.

- [ ] **Step 3: Add the additive schema and contract**

```python
ODDS_BANDS = ("10x", "20x", "50x", "100x")

@dataclass(frozen=True, slots=True)
class TicketCandidateInput:
    odds_band: Literal["10x", "20x", "50x", "100x"]
    target_odds_min_decimal: str
    target_odds_max_decimal: str
    combined_decimal_odds: str
    # existing fields remain unchanged

@dataclass(frozen=True, slots=True)
class CandidateSetInput:
    set_kind: Literal["judgment_bound", "conditional_market_counterfactual"]
    supersedes_candidate_set_revision_id: str | None
    change_delta: dict[str, object] | None
    rationale: str | None
    candidates: tuple[TicketCandidateInput, ...]

@dataclass(frozen=True, slots=True)
class CandidateBandOutcomeInput:
    odds_band: Literal["10x", "20x", "50x", "100x"]
    status: Literal["candidates", "no_feasible_candidate"]
    reason_code: str | None
```

Add nullable odds-band columns for imported historical candidates. Add
`change_delta_json` and `rationale` to Candidate Set Revisions and validate them
with the existing `supersedes_revision_id`: roots have none of the three;
revisions require all three. Existing candidate-level parent/delta columns from
migration 31 remain readable for compatibility but new Actions leave them null.
Add one unique band-outcome row per `candidate_set_revision_id, odds_band`.

- [ ] **Step 4: Run GREEN tests and migration drift checks**

Run: `uv run pytest tests/ontology/operator/test_candidate_band_migration.py tests/ontology/operator/test_candidate_actions.py tests/ontology/test_migrations.py -q`

Expected: PASS with the next gap-free migration applied once and replay-safe.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/operator/models.py nutmeg/ontology/repository/schema_operator_result.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/operator/result_actions.py nutmeg/ontology/repository/operator_result.py tests/ontology/operator/test_candidate_band_migration.py tests/ontology/operator/test_candidate_actions.py
git commit -m "feat(ontology): record candidate odds bands and iteration lineage"
```

### Task 3: Deterministic four-band candidate generation

**Files:**
- Modify: `nutmeg/product/operator_candidates.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Test: `tests/product/operator_v2/test_candidate_bands.py`
- Test: `tests/product/operator_v2/test_candidates.py`

- [ ] **Step 1: Write failing classification tests**

```python
@pytest.mark.parametrize(
    ("odds", "band"),
    [("10.000000000000", "10x"), ("19.900000000000", "20x"),
     ("49.500000000000", "50x"), ("101.000000000000", "100x")],
)
def test_candidate_is_assigned_to_nearest_declared_band(odds, band):
    result = enumerate_band_candidates(_input_with_combined_odds(odds))
    assert result.by_band[band].candidates[0].combined_decimal_odds == odds


def test_empty_band_is_explicit_not_omitted():
    result = enumerate_band_candidates(_only_ten_x_space())
    assert result.by_band["20x"].status == "no_feasible_candidate"
    assert result.by_band["20x"].reason_code == "candidate_space_empty"
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_candidate_bands.py tests/product/operator_v2/test_candidates.py -q`

Expected: FAIL because band enumeration is absent.

- [ ] **Step 3: Implement deterministic bands without changing set kinds**

```python
ODDS_BAND_INTERVALS = {
    "10x": (Decimal("8"), Decimal("15")),
    "20x": (Decimal("15"), Decimal("35")),
    "50x": (Decimal("35"), Decimal("75")),
    "100x": (Decimal("75"), Decimal("150")),
}

def enumerate_band_candidates(inputs, *, set_kind, audit_candidate):
    base = enumerate_candidates(inputs, set_kind=set_kind, audit_candidate=audit_candidate)
    return _partition_by_declared_odds_band(base, ODDS_BAND_INTERVALS)
```

Compute combined odds only from each JCZQ leg's bound booked odds. Preserve the
existing deterministic rank, partitions, audit completeness, and exhaustive
space cap. A candidate outside all intervals is retained only in the comparison
set with reason `outside_requested_bands`.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/product/operator_v2/test_candidate_bands.py tests/product/operator_v2/test_candidates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/product/operator_candidates.py nutmeg/product/operator_contracts.py tests/product/operator_v2/test_candidate_bands.py tests/product/operator_v2/test_candidates.py
git commit -m "feat(product): generate four audited JCZQ odds bands"
```

### Task 4: Revisioned board states, RSI Action fulfillment, and A2-A3 orchestration

**Files:**
- Create: `nutmeg/product/jczq_board_workflow.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/product/operator_queries.py`
- Test: `tests/product/operator_v2/test_jczq_board_workflow.py`

- [ ] **Step 1: Write failing board reconciliation tests**

```python
def test_board_requires_one_research_terminal_state_per_match(workflow):
    result = workflow.intake_board(_board(30), _artifacts(accepted=25, rejected=2))
    assert result.total == 30
    assert result.counts == {"researched": 25, "rejected": 2, "price_only": 3}


def test_post_kickoff_artifact_cannot_create_prospective_forecast(workflow):
    with pytest.raises(ValueError, match="post-kickoff evidence cannot be prospective"):
        workflow.propose_forecasts(_post_kickoff_artifact(), historical_replay=False)


def test_rejected_intake_never_records_r0_fulfillment(workflow, rsi_repo):
    workflow.intake_board(_board(1), [_rejected_artifact()])
    assert rsi_repo.fulfillments(exp_id="R0") == ()


def test_price_only_state_can_be_superseded_before_kickoff(workflow):
    first = workflow.intake_board(_board(1), [])
    second = workflow.intake_board(_board(1), [_accepted_artifact()])
    assert first.matches[0].status == "price_only"
    assert second.matches[0].status == "researched"
    assert second.matches[0].revision_no == 2
    assert second.matches[0].supersedes_revision_id == first.matches[0].revision_id


def test_r0_fulfillment_is_a_typed_rsi_action(workflow, action_repo):
    workflow.intake_board(_board(1), [_accepted_artifact()])
    actions = action_repo.by_type("rsi_fulfill_duty")
    assert len(actions) == 1
    assert actions[0].status == "committed"
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_board_workflow.py -q`

Expected: FAIL because the board workflow service is absent.

- [ ] **Step 3: Implement coordination through existing Actions**

```python
class JczqBoardWorkflow:
    def commit_judgment(self, command, *, actor_id, actor_role):
        return self._operator_actions.commit_match_judgment(
            command, actor_id=actor_id, actor_role=actor_role
        )
```

Use SourceRun/Artifact, evidence freeze, AgentProposal/draft Forecast,
Adjudication, and `commit_match_judgment`. Persist researched, price-only, and
rejected outcomes as append-only revisions with family, revision number, and
supersession fields; do not infer them from missing rows. Replace the product
`R0Recorder` callback with the existing `RsiActions.fulfill_duty` request so the
duty and Observation share RSI's prospective/gap/idempotency semantics. The
`intake_board` method returns counts only after `total == len(board.matches)`;
`propose_forecasts` rejects post-kickoff prospective input before creating an
AgentProposal; `progress` reads only current revisions and reconciles their match
ids against the current slate.

- [ ] **Step 4: Run GREEN and existing judgment tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_board_workflow.py tests/product/operator_v2/test_judgment_api.py tests/ontology/operator/test_judgment_actions.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/product/jczq_board_workflow.py nutmeg/product/operator_contracts.py nutmeg/product/operator_actions.py nutmeg/product/operator_queries.py tests/product/operator_v2/test_jczq_board_workflow.py
git commit -m "feat(product): commit every JCZQ board judgment through v2"
```

### Task 5: A4-A6 candidate iteration and unique terminal decision

**Files:**
- Modify: `nutmeg/product/jczq_board_workflow.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Test: `tests/product/operator_v2/test_jczq_candidate_flow.py`
- Test: `tests/ontology/operator/test_no_ticket_actions.py`

- [ ] **Step 1: Write failing end-to-end decision tests**

```python
def test_four_bands_iterate_with_parent_delta_and_audits(workflow):
    first = workflow.generate_candidates(_committed_board())
    second = workflow.revise_candidates(
        first.judgment_bound_revision_id,
        changes=[_replace_leg("周六029", reason="shared dead face")],
    )
    assert second.supersedes_revision_id == first.judgment_bound_revision_id
    assert second.delta_reason == "shared dead face"
    assert set(second.band_outcomes) == {"10x", "20x", "50x", "100x"}
    assert all(candidate.audit_complete for candidate in second.candidates)


def test_close_requires_exactly_one_terminal_state(workflow):
    with pytest.raises(ValueError, match="terminal decision is missing"):
        workflow.require_terminal_state("2026-09-19")
    workflow.record_no_ticket(_no_ticket_command())
    assert workflow.require_terminal_state("2026-09-19").kind == "no_ticket"
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_candidate_flow.py tests/ontology/operator/test_no_ticket_actions.py -q`

Expected: FAIL because band orchestration and the unique terminal query are absent.

- [ ] **Step 3: Implement prescription, generation, audit, and terminal query**

```python
class JczqDecisionTerminalV1(BaseModel):
    business_date: date
    kind: Literal["selected", "placed", "no_ticket"]
    selection_revision_id: str | None
    no_ticket_revision_id: str | None
    candidate_set_revision_id: str | None
    audit_complete: bool
```

Freeze the existing Judgment Prescription, request candidate generation, run
individual and cross-ticket audits, then call existing selection or no-ticket
Actions. Reject stale revisions and unadjudicated ERROR findings.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_candidate_flow.py tests/product/operator_v2/test_candidate_actions.py tests/ontology/operator/test_candidate_actions.py tests/ontology/operator/test_no_ticket_actions.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/product/jczq_board_workflow.py nutmeg/product/operator_contracts.py nutmeg/product/operator_queries.py tests/product/operator_v2/test_jczq_candidate_flow.py tests/ontology/operator/test_no_ticket_actions.py
git commit -m "feat(product): make JCZQ candidate iteration authoritative"
```

### Task 6: Ontology-derived compatibility projections and close gate

**Files:**
- Create: `nutmeg/product/jczq_compatibility.py`
- Modify: `scripts/openclaw/nutmeg_scheduler_ops.py`
- Modify: `nutmeg/decision/ontology_adapter.py`
- Test: `tests/product/operator_v2/test_jczq_compatibility.py`
- Test: `tests/test_openclaw_router.py`
- Test: `tests/decision/test_close_settle_adapter.py`

- [ ] **Step 1: Write failing authority tests**

```python
def test_projection_contains_source_revision_ids(projector):
    result = projector.export_day("2026-09-19")
    assert result.reads[0]["forecast_revision_id"].startswith("fr-")
    assert result.handoff["candidate_set_revision_id"].startswith("operator-candidate-set-")


def test_manual_legs_file_cannot_drive_close(tmp_path, close_service):
    (tmp_path / "daily/2026-09-19/legs.json").write_text("[]")
    with pytest.raises(ValueError, match="ontology terminal decision is missing"):
        close_service.close("2026-09-19")
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_compatibility.py tests/decision/test_close_settle_adapter.py tests/test_openclaw_router.py -q`

Expected: FAIL because close still accepts legacy authority.

- [ ] **Step 3: Implement one-way projections and the close gate**

```python
def require_ontology_terminal_state(kernel, business_date: str):
    terminal = OperatorQueries(kernel).jczq_terminal_state(business_date)
    if terminal is None or not terminal.audit_complete:
        raise ValueError("ontology terminal decision is missing or incomplete")
    return terminal
```

`JczqCompatibilityProjector.export_day` serializes current ForecastRevision,
Candidate Set Revision, Selection/no-ticket, and ticket rows with their source
ids. `verify_day` re-queries those ids and compares canonical JSON hashes.
Scheduler/router files may render projection paths, but all write and close
decisions must resolve the ontology terminal state first.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_compatibility.py tests/decision/test_close_settle_adapter.py tests/test_openclaw_router.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/product/jczq_compatibility.py scripts/openclaw/nutmeg_scheduler_ops.py nutmeg/decision/ontology_adapter.py tests/product/operator_v2/test_jczq_compatibility.py tests/decision/test_close_settle_adapter.py tests/test_openclaw_router.py
git commit -m "feat(decision): make JCZQ legacy files projection-only"
```

### Task 7: A7 settlement and experiment eligibility

**Files:**
- Modify: `nutmeg/product/jczq_board_workflow.py`
- Modify: `nutmeg/product/operator_settlement.py`
- Modify: `nutmeg/decision/rsi_wiring.py`
- Test: `tests/product/operator_v2/test_jczq_learning_flow.py`
- Test: `tests/decision/test_rsi_wiring.py`

- [ ] **Step 1: Write failing learning tests**

```python
def test_no_ticket_still_grades_prospective_forecasts(workflow):
    workflow.record_no_ticket(_no_ticket_command())
    result = workflow.settle_and_project(_official_results())
    assert result.money_settlement_count == 0
    assert result.forecast_grade_count == 30


def test_historical_replay_never_increments_prospective_experiments(workflow, rsi_repo):
    before = rsi_repo.status_counts(("R0", "F5", "F9"))
    workflow.settle_and_project(_official_results(), historical_replay=True)
    assert rsi_repo.status_counts(("R0", "F5", "F9")) == before
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_learning_flow.py tests/decision/test_rsi_wiring.py -q`

Expected: FAIL because the JCZQ learning coordinator is absent.

- [ ] **Step 3: Implement settlement coordination and eligibility**

```python
def prospective_eligible(*, captured_at, kickoff_at, historical_replay):
    return not historical_replay and captured_at < kickoff_at
```

Use existing result, settlement, review, Forecast score, and RSI Actions.
Persist explicit gaps when a projection fails; do not infer eligibility from
filesystem mtime.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_learning_flow.py tests/decision/test_rsi_wiring.py tests/ontology/test_settlement_grading.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/product/jczq_board_workflow.py nutmeg/product/operator_settlement.py nutmeg/decision/rsi_wiring.py tests/product/operator_v2/test_jczq_learning_flow.py tests/decision/test_rsi_wiring.py
git commit -m "feat(settlement): project JCZQ forecasts and experiments"
```

### Task 8: CLI, router, SOP, and authority cutover

**Files:**
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `docs/sop/RUNBOOK.md`
- Test: `tests/product/operator_v2/test_jczq_workflow_cli.py`
- Test: `tests/test_openclaw_router.py`

- [ ] **Step 1: Write failing public-interface tests**

```python
def test_cutover_refuses_without_accepted_replay(runner, data_dir):
    result = runner.invoke(app, ["workflow", "jczq-cutover", "--day", "2026-09-20", "--data-dir", str(data_dir)])
    assert result.exit_code == 1
    assert "accepted replay is required" in result.stdout


def test_router_calls_same_workflow_action(router, action_spy):
    router.dispatch("竞彩状态 2026-09-20")
    assert action_spy.calls == [("jczq_board_status", "2026-09-20")]
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_workflow_cli.py tests/test_openclaw_router.py -q`

Expected: FAIL because the commands and authority gate are absent.

- [ ] **Step 3: Implement commands and document A2-A7**

Expose commands equivalent to:

```text
nutmeg workflow jczq-status --day YYYY-MM-DD
nutmeg workflow jczq-project --day YYYY-MM-DD
nutmeg workflow jczq-replay --day 2026-09-19 --isolated-root PATH
nutmeg workflow jczq-cutover --day YYYY-MM-DD --replay-report PATH --approve
```

The cutover Action verifies the replay report hash, acceptance state, schema
version, and zero production-side effects before setting
`ontology_v2_required`. Update RUNBOOK A2-A7 to use these product commands.

- [ ] **Step 4: Run GREEN tests**

Run: `uv run pytest tests/product/operator_v2/test_jczq_workflow_cli.py tests/test_openclaw_router.py tests/test_router.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli/workflow.py nutmeg/product/operator_actions.py scripts/openclaw/nutmeg_command_router.py docs/sop/RUNBOOK.md tests/product/operator_v2/test_jczq_workflow_cli.py tests/test_openclaw_router.py
git commit -m "feat(workflow): gate JCZQ ontology v2 cutover"
```

### Task 9: Isolated 2026-09-19 replay and release verification

**Files:**
- Create: `nutmeg/product/jczq_replay.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Test: `tests/product/operator_v2/test_jczq_20260919_replay.py`
- Create at runtime: isolated replay root from `mktemp -d`

- [ ] **Step 1: Write failing replay acceptance test**

```python
def test_20260919_replay_has_complete_lineage_and_zero_side_effects(replay):
    report = replay.run("2026-09-19")
    assert report.board_count == 30
    assert report.research_terminal_count == 30
    assert report.missing_lineage == ()
    assert set(report.odds_band_outcomes) == {"10x", "20x", "50x", "100x"}
    assert report.terminal_kind in {"selected", "no_ticket"}
    assert report.production_delta == {
        "objects": 0,
        "money_entries": 0,
        "dispatches": 0,
        "prospective_observations": 0,
    }
```

- [ ] **Step 2: Run RED test**

Run: `uv run pytest tests/product/operator_v2/test_jczq_20260919_replay.py -q`

Expected: FAIL because replay orchestration and its report do not exist.

- [ ] **Step 3: Implement replay isolation and acceptance report**

```python
@dataclass(frozen=True, slots=True)
class JczqReplayReport:
    replay_run_id: str
    day: str
    board_count: int
    research_terminal_count: int
    missing_lineage: tuple[str, ...]
    odds_band_outcomes: tuple[str, ...]
    terminal_kind: str
    production_delta: Mapping[str, int]
    failures: tuple[str, ...]
    accepted: bool
    report_sha256: str
```

Build the replay kernel only under the explicit isolated root. Refuse to run if
the resolved replay database path equals the production database path. Preserve
original capture and kickoff times and label replay-only observations.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
uv run pytest tests/decision/test_research_ledger.py tests/decision/test_research_runner.py tests/ontology/operator/test_candidate_band_migration.py tests/ontology/operator/test_candidate_actions.py tests/product/operator_v2/test_candidate_bands.py tests/product/operator_v2/test_jczq_board_workflow.py tests/product/operator_v2/test_jczq_candidate_flow.py tests/product/operator_v2/test_jczq_compatibility.py tests/product/operator_v2/test_jczq_learning_flow.py tests/product/operator_v2/test_jczq_workflow_cli.py tests/product/operator_v2/test_jczq_20260919_replay.py tests/test_openclaw_router.py -q
uv run ruff check nutmeg tests scripts/openclaw
uv run pytest -q
```

Expected: all tests pass and Ruff reports no errors in tracked project files.

- [ ] **Step 5: Execute the isolated replay**

```bash
replay_root="$(mktemp -d)"
cp -R .nutmeg-data/ontology "$replay_root/ontology"
uv run nutmeg workflow jczq-replay --day 2026-09-19 --isolated-root "$replay_root"
```

Expected: the report is accepted, shows 30 explicit match states and four band
outcomes, and reports zero production object, money, dispatch, and prospective
experiment deltas. Do not run placement or Telegram dispatch.

- [ ] **Step 6: Verify deployment readiness without activating real betting**

Run:

```bash
uv run nutmeg workflow jczq-status --day 2026-09-19
uv run nutmeg workflow jczq-cutover --day 2026-09-20 --replay-report "$replay_root/replay-2026-09-19.json" --check-only
```

Expected: readiness passes. The check-only command does not change production
authority; the explicit `--approve` cutover is run only at the next board-open
window after confirming no new replay discrepancy.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/product/jczq_replay.py nutmeg/interfaces/cli/workflow.py tests/product/operator_v2/test_jczq_20260919_replay.py
git commit -m "test(replay): prove JCZQ ontology v2 cutover readiness"
```

## Final Completion Gate

- [ ] Confirm `git status --short` contains only pre-existing unrelated user changes.
- [ ] Confirm every task commit is present and no task was squashed into unrelated work.
- [ ] Confirm no replay command wrote to the production ontology store.
- [ ] Confirm no placement, funds, or public dispatch action was executed.
- [ ] Report the accepted replay hash, terminal state, four band outcomes, test totals, and any spec deviation.
