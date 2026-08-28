# Prescription Deviation And User Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Audit unnamed prescription deviations and let Jun explicitly record ERROR overrides as exactly-once Adjudication Actions.

**Architecture:** Keep deterministic diff and registry parsing in `legs_audit`; put Action orchestration in a focused override module. Group ERRORs by match, preserve findings as rejected evidence, and derive the naked-wheel registration count from structured Adjudication alternatives.

**Tech Stack:** Python 3.12 dataclasses, Typer, SQLite ontology Actions, DuckDB analytics projection, pytest, Ruff.

---

## File Structure

- `nutmeg/decision/legs_audit.py`: known rule IDs, registry parser, prescription diff WARN.
- `nutmeg/decision/audit_override.py`: validate/group ERRORs and write Adjudication Actions.
- `nutmeg/interfaces/cli/decision.py`: explicit `--user-override` and `--data-dir` path.
- `nutmeg/analytics/intervention_projection.py`: registered naked-wheel count.
- `tests/decision/test_legs_audit.py`: diff trigger/non-trigger/edge coverage.
- `tests/decision/test_audit_override.py`: Action integration and CLI exit behavior.
- `tests/analytics/test_intervention_projection.py`: deterministic score registration.
- `docs/sop/RULEBOOK.md`: mark deviation registration and override as coded.

### Task 1: Deviation registry RED/GREEN

- [x] Write tests for unnamed diff WARN, named diff silence, unknown rule WARN, exact-face silence, omitted prescribed match, and historical no-prescription compatibility.
- [x] Run the focused tests and confirm missing API failures.
- [x] Add `DeviationRegistration`, a closed known-rule set, parser, and `audit_prescription_deviations`.
- [x] Combine deviation findings with leg findings in the CLI.
- [x] Run all decision audit tests.

### Task 2: Override Action RED/GREEN

- [x] Write integration tests proving default ERROR exit 1, explicit complete override exit 0, missing registration exit 1, one Action per match, multiple ERROR refs retained, idempotent retry, and an adjudication row query.
- [x] Run tests and confirm `--user-override` is absent/fails.
- [x] Implement deterministic grouping and `RecordAdjudicationRequest` creation in `audit_override.py`.
- [x] Add CLI options, ontology health guard, output summary, and error mapping.
- [x] Run focused decision and ontology tests.

### Task 3: Score Registration RED/GREEN

- [x] Add an intervention projection test with two override Adjudications, only one of which is a single-face `user_naked_wheels` record.
- [x] Run it and confirm the named metric is absent.
- [x] Emit `adjudication/user_naked_wheels/registered` count from structured alternatives.
- [x] Run analytics and scoreboard projection tests.

### Task 4: Governance And Replay

- [x] Update RULEBOOK `偏离登记` and audit mapping.
- [x] Run a temporary 26111 SFC-shaped replay against a temporary initialized ontology.
- [x] Query `adjudications` and show the stored rejected evidence/alternative.
- [x] Run `uv run ruff check .` and `uv run pytest -q`.
- [x] Commit design, plan, implementation, projection, and SOP changes in focused commits.

## Execution Record (2026-08-28)

- Focused deviation/override/projection suite: 37 passed.
- `uv run ruff check .`: All checks passed; `uv run pytest -q`: 1,407 tests
  collected, exit 0.
- Temporary schema-15 replay used the real 26111 match-12 fair, flag, ticket face
  `3`, and prescription face `31`: CLI output was
  `3 ERROR -> 1 Adjudication`, exit 0.
- SQLite verification: Action `ACT-8d34fe40dec241349a94ac236a5c241b` is
  `record_adjudication / judge_operator / committed`; adjudication
  `adj-d07bc2ced7f6436f9d5ce2ccb0d07915` stores three rejected findings and
  `user_naked_wheels`, ticket `3`, prescription `31`.
- Verification touched only a temporary kernel; production ontology was not changed.

## Explicit Exclusions

- Changes to `CONSTITUTION.md`, AGENTS/CLAUDE hard-gate wording, or C7;
- ticket confirmation or dispatch;
- result grading and scoreboard authority cutover;
- production ontology writes during verification.
