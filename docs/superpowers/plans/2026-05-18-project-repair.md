# Project Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the consolidated Nutmeg betting assistant so live command surfaces, OpenClaw integration, JCZQ value orientation, R28 retirement, PDF dispatch, and verification are internally consistent.

**Architecture:** Retire stale live entry points instead of rebuilding obsolete selectors; keep sample compatibility for historical tests; enforce OpenClaw/CLI consistency with tests; normalize value candidates at the JCZQ boundary; make verification executable and documented.

**Tech Stack:** Python 3.12, Typer, pytest, ruff, reportlab, shell verification script, OpenClaw Python router.

---

### Task 1: Retire `jczq-mixed-report` live path

**Files:**
- Modify: `nutmeg/interfaces/cli/jczq.py`
- Test: `tests/test_cli.py`

- [ ] Step 1: Add a CLI regression test that invokes `jczq-mixed-report --provider live --format json` and asserts exit code 2 plus a message containing `retired` and `jczq-daily-brief`.
- [ ] Step 2: Run that test and verify it fails because live still calls the hard-coded selector.
- [ ] Step 3: Add a guard in `jczq_mixed_report` before service construction: when provider is live, print the retirement guidance and raise `typer.Exit(2)`.
- [ ] Step 4: Run the focused test and existing sample mixed-report service/CLI smoke.

### Task 2: Remove stale OpenClaw non-betting actions and add command-existence smoke

**Files:**
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`
- Test: `tests/test_openclaw_router.py`

- [ ] Step 1: Add a router test that iterates representative buildable actions and checks the first `nutmeg` command token appears in `uv run nutmeg --help` output.
- [ ] Step 2: Run the test and verify it fails on deleted commands.
- [ ] Step 3: Remove parser/action/build/render support for `content`, `daily-content-pack`, `video-production-packet`, `wechat-article-pack`, `wechat-draft-push`, `seedance-submit`, and `seedance-poll`.
- [ ] Step 4: Remove/update tests that expected those retired commands.
- [ ] Step 5: Run router tests.

### Task 3: Remap JCZQ value candidates when orientation is swapped

**Files:**
- Modify: `nutmeg/services/jczq_value_bridge.py`
- Modify: `nutmeg/services/jczq_parlay_constructor.py` if a helper type is needed
- Test: `tests/test_jczq_value_bridge.py` or `tests/test_jczq_parlay_constructor.py`

- [ ] Step 1: Add a test with an alignment where API-Football returns `Away vs Home`, a home-side model candidate, and assert the JCZQ report/parlay pick is `负`.
- [ ] Step 2: Run the test and verify it fails with `胜`.
- [ ] Step 3: Normalize copied `ValueCandidate` objects inside `JczqValueBridge.evaluate_day` when `orientation_swapped` is true: swap `home`/`away` outcome keys and labels for `match_winner` candidates.
- [ ] Step 4: Run focused value bridge/parlay tests.

### Task 4: Finish R28 cleanup in debate and second-leg helper

**Files:**
- Modify: `nutmeg/services/jczq_debate.py`
- Modify: `nutmeg/services/jczq_second_leg.py`
- Test: `tests/test_jczq_debate_service.py`, `tests/test_cli.py` or new focused second-leg test

- [ ] Step 1: Add tests that the default debate template has no `C Poisson` heading and that `jczq-second-leg --auto` resolves `solo_leg` or favorite ticket first leg instead of requiring `poisson_solo`.
- [ ] Step 2: Run tests and verify current failures.
- [ ] Step 3: Update template to A/B/D/E and neutral final-ticket language.
- [ ] Step 4: Update `solo_from_final` to prefer top-level `solo_leg`, then favorite ticket's first leg, then single-leg tickets; remove `poisson_solo` requirement.
- [ ] Step 5: Run focused debate and second-leg tests.

### Task 5: Make final-plan PDF caption tolerate unknown EV

**Files:**
- Modify: `nutmeg/services/jczq_final_plan_pdf.py`
- Test: `tests/test_jczq_final_plan_pdf.py`

- [ ] Step 1: Add a test that builds a caption from a plan whose `portfolio_metrics` lacks `total_expected_value_known` and asserts no exception and text includes `未知`.
- [ ] Step 2: Run the test and verify KeyError.
- [ ] Step 3: Change `_build_caption` to use `.get()` and format numeric EV only when present.
- [ ] Step 4: Run focused PDF tests.

### Task 6: Restore verification and clean lint

**Files:**
- Create: `scripts/verify.sh`
- Modify: files reported by `uv run ruff check .`
- Modify: `README.md`, `DESIGN.md`, `.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md`, `.specify/specs/046-jczq-mixed-parlay-report-v0/spec.md`

- [ ] Step 1: Restore `scripts/verify.sh` with `uv run ruff check .`, `uv run python -m compileall -q nutmeg scripts`, and `uv run pytest`.
- [ ] Step 2: Run `uv run ruff check .` and fix reported lint errors without changing behavior.
- [ ] Step 3: Update docs to remove deleted command references and mark 046 live mixed-report superseded.
- [ ] Step 4: Run final verification commands.

## Self-Review

- Spec coverage: all approved repair areas are covered by Tasks 1-6.
- Placeholder scan: no TBD/TODO placeholders remain; each task lists concrete files and expected commands.
- Type consistency: uses existing Typer CLI, router parser, dataclass ValueCandidate, and final-plan JSON field names.
