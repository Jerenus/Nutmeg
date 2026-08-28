# Zucai Deployment Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

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

- [ ] Add tests that parse valid bonus/sale facts despite `*` results, reject absent or nonpositive facts, and expose 64% pool-implied bonus.
- [ ] Run tests and confirm the history API is absent.
- [ ] Add `OfficialRenjiuHistory`, parser, and payload fetch using the existing URL/headers.
- [ ] Run all official parser tests.

### Task 2: Gate Arithmetic RED/GREEN

- [ ] Add tests for cap filtering/max-P choice, tie break, capital utilization, median, break-even bonus, equivalent winners, and exact 0.95/2.2 boundaries.
- [ ] Add real official 14-row fixtures and replay 26103/26104.
- [ ] Run tests and confirm the deployment API is absent.
- [ ] Implement strict typed parsing, cohort selection, arithmetic, states, and report text.
- [ ] Run focused tests.

### Task 3: CLI RED/GREEN

- [ ] Add offline CliRunner tests for exit 0/2/3 and malformed history exit 1.
- [ ] Run tests and confirm the command is absent.
- [ ] Add `--gate-file`, optional `--official-history-file`, live fetch fallback, JSON/text output, and exact exit mapping.
- [ ] Run CLI help and decision tests.

### Task 4: Governance And Verification

- [ ] Update RULEBOOK deployment row and audit mapping; add the B9 command to RUNBOOK.
- [ ] Run offline 26103 and 26104 CLI replays with actual official rows.
- [ ] Run `uv run ruff check .` and `uv run pytest -q`.
- [ ] Run the Nutmeg close-chain dry replay.
- [ ] Commit design, plan, implementation, CLI, and SOP changes separately.

## Explicit Exclusions

- Auto-generated candidate structures or history-window judgments;
- automatic ticket changes, empty-slate action, Adjudication, or dispatch;
- `scoreboard.json`, production ontology, launchd, and cutover changes.

