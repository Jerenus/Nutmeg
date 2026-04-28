# Feature Specification: Eval and Review Loop

**Feature Branch**: `033-eval-and-review-loop`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Close the v0.3 LangSmith eval and weekly Brier review gap.

## User Scenarios & Testing

### User Story 1 - Run local eval cases (Priority: P1)

As the operator, I want a local eval runner for tactical, odds, and synthesis
cases so prompt/model changes can be checked before daily use.

### User Story 2 - Record prediction outcomes (Priority: P1)

As the operator, I want to store a match prediction and later record the actual
result so Nutmeg can calculate Brier Score.

### User Story 3 - Review weekly performance (Priority: P2)

As the operator, I want a weekly review command showing count, hit quality,
Brier Score, and notes for calibration.

## Functional Requirements

- **FR-001**: Provide a local JSON eval dataset format under `nutmeg/evals/`.
- **FR-002**: Provide an `eval-run` CLI that works without LangSmith credentials.
- **FR-003**: Provide prediction record/review storage with user_id isolation.
- **FR-004**: Provide Brier Score calculation for three-way match-winner probabilities.
- **FR-005**: Optionally emit LangSmith metadata when configured, without requiring it.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_scoring.py tests/test_eval_service.py tests/test_prediction_repository.py tests/test_cli.py::test_eval_run_command_returns_json_contract tests/test_cli.py::test_prediction_review_command_returns_json_contract -q` -> 6 passed.
- Focused new-feature suite with `tests/test_cli.py` -> 57 passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass.
- `uv run ruff check .` -> pass.
- `python3 -m compileall nutmeg` -> pass.
- `bash scripts/verify.sh` -> 171 passed.
- `uv run nutmeg eval-run --dataset starter --format json` and `uv run nutmeg prediction-review --format json` -> JSON smoke pass.
