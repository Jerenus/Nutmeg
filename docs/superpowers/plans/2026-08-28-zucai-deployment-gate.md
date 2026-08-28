# Zucai Deployment Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a deterministic Zucai deployment report and distinct PASS/REVIEW/REDUCE exit codes using official Renjiu history.

**Architecture:** Extend the existing official module with bonus-only history parsing, then keep candidate selection and gate arithmetic in a pure deployment module. The CLI is a thin live/offline adapter and never mutates ticket inputs.

**Tech Stack:** Python 3.12 dataclasses/statistics, Typer, httpx via existing official fetch pattern, pytest, Ruff.

---

## File Structure

- `nutmeg/decision/zucai_official.py`: official Renjiu history row parser and payload fetch.
- `nutmeg/decision/zucai_deployment.py`: typed input/result, validation, arithmetic, render.
- `nutmeg/interfaces/cli/decision.py`: `zucai-deployment-gate` command and exit mapping.
- `tests/decision/test_zucai_official.py`: cancellation-safe bonus parsing and 64% check.
- `tests/decision/test_zucai_deployment.py`: boundaries, cap selection, invalid data, 26103/26104 replays.
- `docs/sop/RULEBOOK.md`: deployment gate code mapping.
- `docs/sop/RUNBOOK.md`: B9 command.

### Task 1: Official History RED/GREEN

- [x] Add tests that parse valid bonus/sale facts despite `*` results, reject absent or nonpositive facts, and expose 64% pool-implied bonus.
- [x] Run tests and confirm the history API is absent.
- [x] Add `OfficialRenjiuHistory`, parser, and payload fetch using the existing URL/headers.
- [x] Run all official parser tests.

### Task 2: Gate Arithmetic RED/GREEN

- [x] Add tests for cap filtering/max-P choice, tie break, capital utilization, median, break-even bonus, equivalent winners, and exact 0.95/2.2 boundaries.
- [x] Add real official 14-row fixtures and replay 26103/26104.
- [x] Run tests and confirm the deployment API is absent.
- [x] Implement strict typed parsing, cohort selection, arithmetic, states, and report text.
- [x] Run focused tests.

### Task 3: CLI RED/GREEN

- [x] Add offline CliRunner tests for exit 0/2/3 and malformed history exit 1.
- [x] Run tests and confirm the command is absent.
- [x] Add `--gate-file`, optional `--official-history-file`, live fetch fallback, JSON/text output, and exact exit mapping.
- [x] Run CLI help and decision tests.

### Task 4: Governance And Verification

- [x] Update RULEBOOK deployment row and audit mapping; add the B9 command to RUNBOOK.
- [x] Run offline 26103 and 26104 CLI replays with actual official rows.
- [x] Run `uv run ruff check .` and `uv run pytest -q`.
- [x] Run the Nutmeg close-chain dry replay.
- [x] Commit design, plan, implementation, CLI, and SOP changes separately.

## Execution Record (2026-08-28)

- Focused official parser/deployment suite: 31 passed.
- `uv run ruff check .`: All checks passed; `uv run pytest -q`: 1,430 tests
  collected, exit 0.
- Offline 26103 replay over the 14 official rows: cap-optimal CNY 400, break-even
  CNY 14,412, median CNY 6,446, ratio 2.24x, `reduce_or_empty`, exit 3. The report
  says to prioritize dropped-match reduction and mention empty only when no qualified
  reduced candidate exists.
- Offline 26104 replay: M1296, cap utilization 81.0%, break-even CNY 6,097,
  median CNY 6,446, ratio 0.95x, `pass`, exit 0.
- The gate reports arithmetic and distinct exits only; it does not mutate tickets or
  make the reduction/placement decision.

## Explicit Exclusions

- Auto-generated candidate structures or history-window judgments;
- automatic ticket changes, empty-slate action, Adjudication, or dispatch;
- `scoreboard.json`, production ontology, launchd, and cutover changes.
